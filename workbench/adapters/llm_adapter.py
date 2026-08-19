"""LLM 创作任务适配器（v0.3）：story_plan / script / bible / shot_plans。

由 Worker 从数据库队列领取执行（§10.3 任务解耦）；成功产物入库并登记依赖，
失败保留原始输出（不创建残缺下游实体，§11.1 / 验收 28）。
"""

from __future__ import annotations

import threading

from sqlalchemy.orm import sessionmaker

from ..config import Settings
from ..creative.schemas import TEMPLATE_VERSION
from ..db import session_scope
from ..llm import LLMError, get_llm_adapter
from ..models import JOB_STATUS_RUNNING, GenerationJob, Project, ProductionBibleVersion, Shot, StoryScriptVersion, utcnow
from ..services import creative as creative_service
from ..services import jobs as jobs_service
from .base import AdapterError, BaseAdapter, CancelRequested

LLM_HEARTBEAT_SECONDS = 10.0


class LLMAdapter(BaseAdapter):
    name = "llm"

    def run(self, session_factory: sessionmaker, settings: Settings, job_id: str) -> None:
        with session_scope(session_factory) as session:
            job = session.get(GenerationJob, job_id)
            if job is None:
                return
            snapshot = job.request_snapshot or {}
            stage = snapshot.get("stage") or job.job_type
            project = session.get(Project, job.project_id) if job.project_id else None
            jobs_service.mark_running(session, job)
            jobs_service.append_job_log(
                settings, job,
                f"[{utcnow().isoformat()}] 文本阶段开始: {stage}（模板 {snapshot.get('template_version', TEMPLATE_VERSION)}）",
            )
            if project is None:
                jobs_service.finish_failed(session, job, "任务缺少项目关联")
                return

        def heartbeat_while_waiting(model_label: str) -> threading.Event:
            """LLM 调用是阻塞式 HTTP 请求，期间由后台线程持续心跳，避免任务看似僵死。"""
            stop = threading.Event()

            def _beat() -> None:
                waited = 0.0
                while not stop.wait(LLM_HEARTBEAT_SECONDS):
                    waited += LLM_HEARTBEAT_SECONDS
                    try:
                        with session_scope(session_factory) as session:
                            job = session.get(GenerationJob, job_id)
                            if job is None or job.status != JOB_STATUS_RUNNING:
                                return
                            if job.current_step == "请求取消":
                                return  # 保留取消标志，交给主线程轮询处理
                            jobs_service.heartbeat(
                                session, job,
                                step=f"等待文本模型响应（{model_label}，已等待 {waited:.0f}s）",
                            )
                    except Exception:  # noqa: BLE001 - 心跳失败不中断生成
                        pass

            threading.Thread(target=_beat, daemon=True, name=f"llm-hb-{job_id}").start()
            return stop

        try:
            adapter = get_llm_adapter(settings.llm_type)
            model_label = adapter.model_name(settings)
            with session_scope(session_factory) as session:
                job = session.get(GenerationJob, job_id)
                if job is not None:
                    jobs_service.append_job_log(
                        settings, job,
                        f"[{utcnow().isoformat()}] 调用文本模型: {model_label}"
                        f"（超时 {settings.llm_timeout_seconds:.0f}s，校验失败自动修复 ≤{settings.llm_max_repair} 次）",
                    )
            heartbeat_stop = heartbeat_while_waiting(model_label)
            try:
                result = self._generate_with_cancel(
                    session_factory, adapter, settings, stage, snapshot, job_id
                )
            finally:
                heartbeat_stop.set()
            if result is None:
                return  # 已在取消路径处理
        except LLMError as exc:
            self._fail(session_factory, settings, job_id, str(exc), keep_raw=True)
            return
        except Exception as exc:  # noqa: BLE001 - 适配器边界兜底
            self._fail(session_factory, settings, job_id, f"文本模型异常: {exc.__class__.__name__}: {exc}")
            return

        with session_scope(session_factory) as session:
            job = session.get(GenerationJob, job_id)
            if job is None:
                return
            if jobs_service.is_cancel_requested(session, job_id):
                jobs_service.confirm_cancel(session, settings, job)
                return

        with session_scope(session_factory) as session:
            job = session.get(GenerationJob, job_id)
            if job is None:
                return
            snapshot = dict(job.request_snapshot or {})
            snapshot["llm_model"] = result.model
            snapshot["llm_template_version"] = result.template_version
            snapshot["llm_repaired"] = result.repaired
            job.request_snapshot = snapshot
            jobs_service.heartbeat(session, job, step="结构校验通过，写入版本", progress=80)
            project = session.get(Project, job.project_id)

        try:
            with session_scope(session_factory) as session:
                job = session.get(GenerationJob, job_id)
                project = session.get(Project, job.project_id)
                if job is None or project is None:
                    return
                if stage == "story_plan":
                    creative_service.ingest_story_plan(session, project, job, result)
                    message = f"故事方案已生成（{len(result.data.get('scenes') or [])} 场）"
                elif stage == "script":
                    creative_service.ingest_script(session, project, job, result)
                    message = f"结构化剧本已生成（{len(result.data.get('scenes') or [])} 场），等待 A 卡点审核"
                elif stage == "bible":
                    creative_service.ingest_bible(session, project, job, result)
                    message = "生产设定已提取，等待 B 卡点审核"
                elif stage == "shot_plans":
                    scope_codes = snapshot.get("scope_shot_codes") or []
                    shots = creative_service.ingest_shot_plans(session, project, job, result)
                    scope_note = f"（范围重做 {len(scope_codes)} 镜）" if scope_codes else ""
                    message = f"分镜与提示词包已生成（{len(shots)} 镜）{scope_note}"
                else:
                    raise AdapterError(f"未知文本阶段: {stage}")
                jobs_service.append_job_log(settings, job, f"[{utcnow().isoformat()}] {message}")
                jobs_service.finish_succeeded(session, job, message)
        except Exception as exc:  # noqa: BLE001
            self._fail(session_factory, settings, job_id, f"产物入库失败: {exc.__class__.__name__}: {exc}", keep_raw=True)

    def _generate_with_cancel(
        self,
        session_factory: sessionmaker,
        adapter,
        settings: Settings,
        stage: str,
        snapshot: dict,
        job_id: str,
    ):
        """LLM 调用放后台线程执行；主线程每 0.5s 轮询取消标志（阻塞期可取消）。

        返回 GenerationResult；用户取消时返回 None（任务已标记 cancelled，
        后台线程结果被丢弃——HTTP 调用受 llm_timeout_seconds 兜底自然结束）。
        """
        import threading

        holder: dict = {}
        done = threading.Event()

        def _worker() -> None:
            try:
                holder["result"] = adapter.generate_structured(
                    settings,
                    stage=stage,
                    system=snapshot.get("system") or "",
                    user=snapshot.get("user") or "",
                    schema=snapshot.get("schema") or {},
                    context=snapshot.get("context") or {},
                    template_version=snapshot.get("template_version") or TEMPLATE_VERSION,
                )
            except BaseException as exc:  # noqa: BLE001 - 原样传回主线程
                holder["error"] = exc
            finally:
                done.set()

        threading.Thread(target=_worker, daemon=True, name=f"llm-gen-{job_id}").start()
        while not done.wait(0.5):
            with session_scope(session_factory) as session:
                if jobs_service.is_cancel_requested(session, job_id):
                    job = session.get(GenerationJob, job_id)
                    if job is not None:
                        jobs_service.confirm_cancel(session, settings, job)
                    return None
        if "error" in holder:
            raise holder["error"]
        return holder["result"]

    def _fail(self, session_factory: sessionmaker, settings: Settings, job_id: str, message: str, *, keep_raw: bool = False) -> None:
        with session_scope(session_factory) as session:
            job = session.get(GenerationJob, job_id)
            if job is None:
                return
            project = session.get(Project, job.project_id) if job.project_id else None
            if keep_raw and project is not None:
                stage = (job.request_snapshot or {}).get("stage") or job.job_type
                raw = str(message)
                version_types = {"story_plan": "story_plan", "script": "script"}
                if stage in version_types:
                    failed = creative_service.record_failed_struct(
                        session, project, version_types[stage], job,
                        raw=(job.request_snapshot or {}).get("user", ""), error=message,
                    )
                    if failed is not None:
                        failed.raw_model_output = (message + "\n---\n" + failed.raw_model_output)[:20000]
            jobs_service.finish_failed(session, job, message[:2000])
