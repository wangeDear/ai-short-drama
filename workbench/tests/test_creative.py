from __future__ import annotations

"""v0.3 创作链路端到端测试：覆盖需求 §12 验收标准 18～29。

使用离线 Mock LLM（llm_type=mock）与 Mock 生成节点，不依赖外部服务。
"""

import tempfile
import unittest
from pathlib import Path
from unittest import mock

from fastapi.testclient import TestClient
from PIL import Image

from ..config import Settings
from ..db import session_scope
from ..llm.base import LLMError
from ..models import (
    DependencyEdge,
    GenerationJob,
    ProductionBibleVersion,
    Project,
    PromptPackage,
    Scene,
    Shot,
    StoryScriptVersion,
)
from ..services import creative as creative_service
from ..services import gates as gates_service
from ..web.main import create_app
from ..worker import run_once

MP4_BYTES = (
    b"\x00\x00\x00\x18ftypmp42\x00\x00\x00\x00mp42isom"
    b"\x00\x00\x00\x08free"
) * 40

CREATIVE_TEXT = (
    "一个电工在沙漠深处独自维护离网光伏电站，沙暴即将来临，他的手机只剩百分之二的电量。"
    "他必须在保住昂贵设备与赶回公路求救之间做出选择。风暴逼近时，他用太阳能板给手机充上最后的电，"
    "录下一段留言，然后选择留下守护电站。"
)


class BrokenLLM:
    name = "broken"

    def model_name(self, settings):
        return self.name

    def generate_structured(self, *args, **kwargs):
        raise LLMError("结构化输出校验失败（测试注入）: title 长度不足")


class CreativeTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        root = Path(self._tmp.name)
        self.workspace = root / "workspace"
        (self.workspace / "outputs").mkdir(parents=True)
        (self.workspace / "outputs" / "sample.mp4").write_bytes(MP4_BYTES)
        self.settings = Settings(
            {
                "workspace_root": str(self.workspace),
                "data_dir": str(root / "data"),
                "worker_enabled": "false",
                "llm_type": "mock",
                "ffmpeg_bin": "missing_ffmpeg_for_test",
                "ffprobe_bin": "missing_ffprobe_for_test",
                "poll_interval": 0.05,
            }
        )
        self.app = create_app(self.settings)
        self.client = TestClient(self.app)

    def tearDown(self) -> None:
        try:
            self.client.close()
        except Exception:  # noqa: BLE001
            pass
        engine = getattr(self.app.state, "engine", None)
        if engine is not None:
            engine.dispose()
        self._tmp.cleanup()

    # ------------------------------------------------------------- helpers
    def db(self):
        return session_scope(self.app.state.session_factory)

    def post(self, path: str, data: dict) -> None:
        response = self.client.post(path, data=data, follow_redirects=False)
        assert response.status_code == 303, f"{path} -> {response.status_code}: {response.text[:200]}"

    def add_project(self, name: str) -> Project:
        self.post("/api/projects/create", {"name": name, "resolution": "704x1216", "fps": "24"})
        with self.db() as session:
            return session.query(Project).filter_by(name=name).one()

    def add_mock_endpoint(self) -> None:
        from ..services.endpoints import create_endpoint

        with self.db() as session:
            create_endpoint(session, name="Mock 节点", endpoint_type="mock", base_url="")

    def run_pending(self, rounds: int = 6) -> int:
        """逐个执行排队任务，返回执行数。"""
        count = 0
        for _ in range(rounds):
            if not run_once(self.app.state.session_factory, self.settings):
                break
            count += 1
        return count

    def build_full_chain(self, name: str = "创意链路项目") -> tuple[Project, list[Shot]]:
        """创意 → 故事 → 剧本 → A 批准 → 圣经 → B 批准 → 分镜提示词。"""
        project = self.add_project(name)
        self.post(f"/api/projects/{project.id}/brief", {"source_text": CREATIVE_TEXT, "target_shots": "8"})
        self.post(f"/api/projects/{project.id}/creative/generate", {"stage": "story_plan"})
        assert self.run_pending() == 1
        self.post(f"/api/projects/{project.id}/creative/generate", {"stage": "script"})
        assert self.run_pending() == 1
        self.post(f"/api/projects/{project.id}/gates/A/decide", {"decision": "approve"})
        self.post(f"/api/projects/{project.id}/creative/generate", {"stage": "bible"})
        assert self.run_pending() == 1
        self.post(f"/api/projects/{project.id}/gates/B/decide", {"decision": "approve"})
        self.post(f"/api/projects/{project.id}/creative/generate", {"stage": "shot_plans"})
        assert self.run_pending() == 1
        with self.db() as session:
            shots = list(session.query(Shot).filter(Shot.project_id == project.id).all())
            return project, shots

    # ---------------------------------------------------------------- tests

    def test_shot_duration_limit_enforced(self) -> None:
        """H3 单镜 ≤15s：schema 数值范围校验 + 入库钳制三层防护。"""
        from ..creative.schemas import SHOT_DURATION_MAX, SHOT_PLANS_SCHEMA
        from ..llm.base import GenerationResult, validate_schema

        # 1) 校验器支持 minimum/maximum
        schema = {"type": "object", "properties": {"duration": {"type": "number", "minimum": 1, "maximum": 15}}}
        self.assertEqual(validate_schema({"duration": 10}, schema), [])
        self.assertTrue(any("超出上限" in e for e in validate_schema({"duration": 30}, schema)))
        self.assertTrue(any("小于下限" in e for e in validate_schema({"duration": 0}, schema)))
        self.assertTrue(any("小于下限" in e for e in validate_schema({"duration": 0}, schema)))
        self.assertTrue(validate_schema({"duration": True}, schema))  # bool 在类型层被拒

        # 2) SHOT_PLANS_SCHEMA 对 30s 单镜报错（真实 LLM 会触发自动修复循环）
        bad = {"shots": [{"shot_code": "S01", "scene_code": "SC01", "duration": 30,
                          "image_prompt": {}, "video_prompt": {}, "audio_prompt": {}}]}
        self.assertTrue(any("duration" in e for e in validate_schema(bad, SHOT_PLANS_SCHEMA)))

        # 3) 入库钳制：任何来源超 15s 截为 15s + long_action 风险 + 拆镜建议
        project, _ = self.build_full_chain("超长镜头钳制")
        with self.db() as session:
            project = session.get(Project, project.id)
            job = GenerationJob(project_id=project.id, job_type="shot_plans", request_snapshot={})
            session.add(job)
            session.flush()
            result = GenerationResult(
                data={"shots": [{
                    "shot_code": "SX01", "scene_code": "SC01", "purpose": "超长测试",
                    "duration": 30, "subject": "主角", "action": "走过小道",
                    "image_prompt": {"moment": "测试"}, "video_prompt": {"subject_action": "测试"},
                    "audio_prompt": {},
                }]},
                raw="{}", model="test", template_version="v1",
            )
            created = creative_service.ingest_shot_plans(session, project, job, result)
            self.assertEqual(len(created), 1)
            self.assertEqual(created[0].duration, SHOT_DURATION_MAX)
            from ..models import PromptPackage
            package = session.query(PromptPackage).filter(PromptPackage.shot_id == created[0].id).order_by(
                PromptPackage.version_number.desc()).first()
            self.assertIn("long_action", package.risk_tags_json)
            notes = " ".join(package.route_suggestion_json.get("notes") or [])
            self.assertIn("截为", notes)
            self.assertIn("拆分", notes)

    def test_creative_full_chain(self) -> None:
        """验收 18/19/26：≥50 字创意 → 全链路；图片≠视频提示词；风险标签。"""
        project, shots = self.build_full_chain()

        self.assertGreaterEqual(len(shots), 4)  # 8 目标镜 → 至少 4 场 × 2 镜
        with self.db() as session:
            story = creative_service.latest_struct(session, project, "story_plan")
            script = creative_service.latest_struct(session, project, "script")
            bible = creative_service.latest_bible(session, project)
            self.assertEqual(story.status, "approved")
            self.assertEqual(script.status, "approved")
            self.assertEqual(bible.status, "approved")
            self.assertGreaterEqual(len(script.structured_content_json.get("scenes") or []), 2)
            scene_rows = session.query(Scene).filter(Scene.project_id == project.id).all()
            self.assertGreaterEqual(len(scene_rows), 2)

            for shot in shots:
                self.assertTrue((shot.image_prompt or "").strip(), f"{shot.shot_code} 图片提示词为空")
                self.assertTrue((shot.video_prompt or "").strip(), f"{shot.shot_code} 视频提示词为空")
                self.assertNotEqual(shot.image_prompt, shot.video_prompt, f"{shot.shot_code} 提示词被复制")

            # 风险标签（26）：含 手/按键/屏幕 的镜必须有标签与路径建议
            risky = [
                shot for shot in shots
                if any(tag for tag in self._packages(session, shot).risk_tags_json or [])
            ]
            self.assertTrue(risky, "应至少有一镜带风险标签")
            for shot in risky:
                package = self._packages(session, shot)
                self.assertTrue((package.route_suggestion_json or {}).get("recommended"))

    def _packages(self, session, shot: Shot) -> PromptPackage:
        return (
            session.query(PromptPackage)
            .filter(PromptPackage.shot_id == shot.id)
            .order_by(PromptPackage.version_number.desc())
            .first()
        )

    def test_gate_a_blocks_bible_and_edit(self) -> None:
        """验收 20：A 未通过时圣经生成被拒；编辑剧本产生新版本后批准放行。"""
        project = self.add_project("A卡点")
        self.post(f"/api/projects/{project.id}/brief", {"source_text": CREATIVE_TEXT})
        self.post(f"/api/projects/{project.id}/creative/generate", {"stage": "story_plan"})
        assert self.run_pending() == 1
        self.post(f"/api/projects/{project.id}/creative/generate", {"stage": "script"})
        assert self.run_pending() == 1

        # A 未批准 → bible 被服务层拒绝且不产生任务
        self.post(f"/api/projects/{project.id}/creative/generate", {"stage": "bible"})
        with self.db() as session:
            bible_jobs = (
                session.query(GenerationJob)
                .filter(GenerationJob.project_id == project.id, GenerationJob.job_type == "bible")
                .all()
            )
            self.assertEqual(len(bible_jobs), 0)

        # 编辑剧本（卡点 A，验收 20 的"编辑后批准"）
        with self.db() as session:
            script = creative_service.latest_struct(session, project, "script")
            code = (script.structured_content_json.get("scenes") or [{}])[0].get("scene_code", "SC01")
        self.post(
            f"/api/projects/{project.id}/script/edit",
            {f"scene_{code}_action": "修改后的动作：他把太阳能板转向太阳。"},
        )
        with self.db() as session:
            versions = (
                session.query(StoryScriptVersion)
                .filter(StoryScriptVersion.project_id == project.id, StoryScriptVersion.version_type == "script")
                .all()
            )
            self.assertEqual(len(versions), 2)  # 旧版本保留
            latest = creative_service.latest_struct(session, project, "script")
            self.assertEqual(latest.status, "reviewing")
            self.assertIn("修改后的动作", str(latest.structured_content_json))

        self.post(f"/api/projects/{project.id}/gates/A/decide", {"decision": "approve"})
        self.post(f"/api/projects/{project.id}/creative/generate", {"stage": "bible"})
        self.assertEqual(self.run_pending(), 1)
        with self.db() as session:
            self.assertIsNotNone(creative_service.latest_bible(session, project))

    def test_gate_b_partial_return_and_scope_redo(self) -> None:
        """验收 21：B 卡点只退回一镜，且仅重做该镜。"""
        project, shots = self.build_full_chain("B卡点范围")
        target = shots[0]
        other = next(shot for shot in shots if shot.id != target.id)

        self.post(
            f"/api/projects/{project.id}/gates/B/decide",
            {"decision": "return", "scope_type": "shot", "scope_id": target.id, "comment": "动作描述不清"},
        )
        with self.db() as session:
            target_row = session.get(Shot, target.id)
            other_row = session.get(Shot, other.id)
            self.assertEqual(target_row.status, "needs_revision")
            self.assertIn("动作描述不清", target_row.notes or "")
            self.assertNotEqual(other_row.status, "needs_revision")
            target_pkg = self._packages(session, target_row)
            self.assertEqual(target_pkg.status, "revision")

        # 仅重做该镜（范围重做）
        with self.db() as session:
            before = {
                shot.id: self._packages(session, shot).version_number
                for shot in session.query(Shot).filter(Shot.project_id == project.id).all()
            }
        self.post(
            f"/api/projects/{project.id}/creative/generate",
            {"stage": "shot_plans", "scope_shot_ids": target.id},
        )
        self.assertEqual(self.run_pending(), 1)
        with self.db() as session:
            for shot in session.query(Shot).filter(Shot.project_id == project.id).all():
                version_now = self._packages(session, shot).version_number
                if shot.id == target.id:
                    self.assertEqual(version_now, before[shot.id] + 1)
                else:
                    self.assertEqual(version_now, before[shot.id], "范围外的镜不应被重做")

    def test_auto_queue_after_c(self) -> None:
        """验收 22：C 通过自动排队（仅已批准镜头）；未批准镜直接生成被拒（FR-GATE-001）。"""
        self.add_mock_endpoint()
        project, shots = self.build_full_chain("自动排队")
        self.post(
            f"/api/projects/{project.id}/pipeline-config",
            {"gate_a": "on", "gate_b": "on", "auto_queue_after_c": "on"},
        )

        # 为第一镜生成图片并批准 → 自动创建视频任务
        shot = shots[0]
        self.post(f"/api/shots/{shot.id}/generate", {"job_type": "image"})
        self.run_pending()
        self.post(f"/api/shots/{shot.id}/review", {"action": "approve_image"})
        with self.db() as session:
            video_jobs = (
                session.query(GenerationJob)
                .filter(GenerationJob.shot_id == shot.id, GenerationJob.job_type == "video")
                .all()
            )
            self.assertEqual(len(video_jobs), 1, "图片批准后应自动排队视频任务")

        # 未批准图片的镜直接提交视频 → 被拒且不产生任务
        other = shots[1]
        self.post(f"/api/shots/{other.id}/generate", {"job_type": "video"})
        with self.db() as session:
            jobs = (
                session.query(GenerationJob)
                .filter(GenerationJob.shot_id == other.id, GenerationJob.job_type == "video")
                .all()
            )
            self.assertEqual(len(jobs), 0)

    def test_gate_state_persists_across_restart(self) -> None:
        """验收 23：重启后 A~D 卡点输入/决定/待办可恢复。"""
        project = self.add_project("重启恢复")
        self.post(f"/api/projects/{project.id}/brief", {"source_text": CREATIVE_TEXT})
        self.post(f"/api/projects/{project.id}/creative/generate", {"stage": "story_plan"})
        self.run_pending()
        self.post(f"/api/projects/{project.id}/creative/generate", {"stage": "script"})
        self.run_pending()
        self.post(f"/api/projects/{project.id}/gates/A/decide", {"decision": "approve", "comment": "结构完整"})

        with self.db() as session:
            before = [g["status"] for g in gates_service.gate_states(session, project)]

        # 模拟重启：关掉客户端与引擎，用同一 DB 重建 app
        self.client.close()
        self.app.state.engine.dispose()
        self.app = create_app(self.settings)
        self.client = TestClient(self.app)

        with self.db() as session:
            project_row = session.get(Project, project.id)
            after = [g["status"] for g in gates_service.gate_states(session, project_row)]
        self.assertEqual(after, before)
        history = gates_service.gate_history(session, project_row)
        self.assertEqual(len(history), 1)
        self.assertEqual(history[0].decision, "approved")
        self.assertTrue(history[0].decided_at is not None)
        self.assertTrue(history[0].input_version_refs_json.get("script_version_id"))

    def test_bible_edit_marks_only_referencing_shots_stale(self) -> None:
        """验收 24：修改角色设定只使引用该角色的镜头过期。"""
        project, shots = self.build_full_chain("精准失效")
        # 造一个不引用主角的对照镜
        self.post(
            f"/api/projects/{project.id}/shots/create",
            {"shot_code": "S99", "title": "空镜", "characters": "无人", "image_prompt": "x", "video_prompt": "y"},
        )

        self.post(
            f"/api/projects/{project.id}/bible/edit",
            {"item_type": "character", "name": "主角", "updates_json": '{"costume": "深蓝工装（改）"}'},
        )
        with self.db() as session:
            bible = creative_service.latest_bible(session, project)
            self.assertEqual(bible.version_number, 2)
            protagonist = next(c for c in bible.characters_json if c["name"] == "主角")
            self.assertEqual(protagonist["costume"], "深蓝工装（改）")

            for shot in session.query(Shot).filter(Shot.project_id == project.id).all():
                stale = (shot.params_json or {}).get("stale")
                if shot.shot_code == "S99":
                    self.assertIsNone(stale, "未引用该角色的镜不应过期")
                elif "主角" in (shot.characters or ""):
                    self.assertIsNotNone(stale, f"{shot.shot_code} 应过期")
                    self.assertIn("主角", stale.get("reason", ""))

    def test_image_swap_invalidates_video(self) -> None:
        """验收 25 下半：更换已批准图片 → 依赖视频过期。"""
        project = self.add_project("换图失效")
        self.post(
            f"/api/projects/{project.id}/shots/create",
            {"shot_code": "S01", "title": "测试", "characters": "主角",
             "image_prompt": "原始画面", "video_prompt": "原始动作"},
        )
        with self.db() as session:
            shot = session.query(Shot).filter(Shot.project_id == project.id).one()
            shot_id = shot.id
        for name in ("img1.png", "img2.png"):
            image_path = self.workspace / "outputs" / name
            Image.new("RGB", (64, 96), (30, 40, 50)).save(image_path)
            self.post(
                f"/api/shots/{shot_id}/register-file",
                {"version_type": "image", "file_path": f"outputs/{name}", "label": name},
            )
            self.post(f"/api/shots/{shot_id}/review", {"action": "approve_image"})

        with self.db() as session:
            shot_row = session.get(Shot, shot_id)
            self.assertTrue(shot_row.video_config_stale, "更换已批准图片应使依赖视频过期")
            stale = (shot_row.params_json or {}).get("stale")
            self.assertIsNotNone(stale)
            self.assertIn("更换", stale.get("reason", ""))

    def test_llm_invalid_output_no_partial_data(self) -> None:
        """验收 28：模型输出不符合 schema → 明确失败，不创建残缺下游实体。"""
        project = self.add_project("坏输出")
        self.post(f"/api/projects/{project.id}/brief", {"source_text": CREATIVE_TEXT})
        self.post(f"/api/projects/{project.id}/creative/generate", {"stage": "story_plan"})

        with mock.patch(
            "workbench.adapters.llm_adapter.get_llm_adapter", return_value=BrokenLLM()
        ):
            self.run_pending()

        with self.db() as session:
            job = (
                session.query(GenerationJob)
                .filter(GenerationJob.project_id == project.id, GenerationJob.job_type == "story_plan")
                .one()
            )
            self.assertEqual(job.status, "failed")
            self.assertIn("结构化输出校验失败", job.error_message)
            failed_versions = (
                session.query(StoryScriptVersion)
                .filter(StoryScriptVersion.project_id == project.id)
                .all()
            )
            self.assertTrue(all(v.status == "failed" for v in failed_versions))
            self.assertTrue(failed_versions, "失败原始输出应保留供查看")
            # 无下游实体
            self.assertEqual(
                session.query(Scene).filter(Scene.project_id == project.id).count(), 0
            )
            self.assertEqual(
                session.query(Shot).filter(Shot.project_id == project.id).count(), 0
            )

    def test_estimate_before_generation(self) -> None:
        """验收 27：批量生成前展示任务数与 GPU 工作量预估。"""
        project = self.add_project("预估")
        self.post(f"/api/projects/{project.id}/brief", {"source_text": CREATIVE_TEXT, "target_shots": "12"})
        with self.db() as session:
            brief = creative_service.latest_brief(session, project)
            estimate = creative_service.estimate_from_brief(brief)
        self.assertEqual(estimate["shots"], 12)
        self.assertEqual(estimate["image_tasks"], 12)
        self.assertEqual(estimate["video_tasks"], 12)
        self.assertGreater(estimate["gpu_minutes"], 0)
        page = self.client.get(f"/projects/{project.id}/creative")
        self.assertEqual(page.status_code, 200)
        self.assertIn("GPU 分钟", page.text)

    def test_traceability(self) -> None:
        """验收 29：文本/媒体版本可追溯到输入、模型、模板与审核决定。"""
        project, _shots = self.build_full_chain("追溯")
        with self.db() as session:
            story = creative_service.latest_struct(session, project, "story_plan")
            script = creative_service.latest_struct(session, project, "script")
            bible = creative_service.latest_bible(session, project)

            for row in (story, script):
                self.assertTrue(row.content_hash)
                self.assertEqual(row.prompt_template_version, "v1")
            self.assertTrue(bible.content_hash)
            self.assertTrue(bible.created_by_job_id)
            self.assertEqual((story.model_snapshot_json or {}).get("llm"), "mock-llm-offline")
            self.assertTrue(script.created_by_job_id)

            edges = session.query(DependencyEdge).filter(DependencyEdge.project_id == project.id).all()
            upstream_types = {edge.upstream_type for edge in edges}
            self.assertIn("brief", upstream_types)
            self.assertIn("story_plan", upstream_types)
            self.assertIn("script", upstream_types)

            records = gates_service.gate_history(session, project)
            decisions = {record.gate_type: record for record in records}
            self.assertIn("A", decisions)
            self.assertIn("B", decisions)
            self.assertTrue(decisions["A"].input_version_refs_json.get("script_version_id"))

    def test_creative_wizard_creates_and_generates(self) -> None:
        """创建向导创意模式：建项目 + 简报 + 自动入队故事方案。"""
        response = self.client.post(
            "/api/projects/create-creative",
            data={"name": "向导项目", "source_text": CREATIVE_TEXT, "target_shots": "6"},
            follow_redirects=False,
        )
        self.assertEqual(response.status_code, 303)
        self.assertIn("/creative", response.headers["location"])
        self.run_pending()
        with self.db() as session:
            project = session.query(Project).filter_by(name="向导项目").one()
            story = creative_service.latest_struct(session, project, "story_plan")
            self.assertIsNotNone(story)
            self.assertEqual(story.status, "reviewing")

    def test_cancel_running_llm_job(self) -> None:
        """LLM 阻塞期间可取消：适配器轮询取消标志并确认取消（孤儿任务强取消）。"""
        import threading
        import time

        project = self.add_project("取消LLM")
        self.post(f"/api/projects/{project.id}/brief", {"source_text": CREATIVE_TEXT})
        self.post(f"/api/projects/{project.id}/creative/generate", {"stage": "story_plan"})

        release = threading.Event()

        class SlowLLM:
            name = "slow"

            def model_name(self, settings):  # noqa: ANN001
                return "slow-llm"

            def generate_structured(self, *args, **kwargs):
                release.wait(timeout=30)  # 模拟慢模型阻塞
                return {}

        from ..adapters import llm_adapter as llm_adapter_module

        worker_done = threading.Event()
        worker_error: list = []

        def run_worker() -> None:
            try:
                from ..worker import run_once

                run_once(self.app.state.session_factory, self.settings)
            except Exception as exc:  # noqa: BLE001
                worker_error.append(exc)
            finally:
                worker_done.set()

        with mock.patch.object(llm_adapter_module, "get_llm_adapter", return_value=SlowLLM()):
            thread = threading.Thread(target=run_worker, daemon=True)
            thread.start()
            # 等任务进入 running
            deadline = time.time() + 10
            job_id = None
            while time.time() < deadline:
                with self.db() as session:
                    job = (
                        session.query(GenerationJob)
                        .filter(GenerationJob.project_id == project.id)
                        .first()
                    )
                    if job is not None and job.status == "running":
                        job_id = job.id
                        break
                time.sleep(0.1)
            self.assertIsNotNone(job_id, "任务应进入 running")

            # 阻塞期间请求取消 → 适配器 0.5s 轮询应确认取消
            self.post(f"/api/jobs/{job_id}/cancel", {})
            worker_done.wait(timeout=15)
            release.set()
            self.assertFalse(worker_error, f"worker 异常: {worker_error}")

        with self.db() as session:
            job = session.get(GenerationJob, job_id)
            self.assertEqual(job.status, "cancelled")
            self.assertEqual(job.current_step, "已取消")

    def test_cancel_orphan_running_job_force(self) -> None:
        """心跳停止的孤儿 running 任务：取消直接强制生效（服务重启场景）。"""
        from datetime import timedelta

        from ..models import JOB_STATUS_RUNNING
        from ..services import jobs as jobs_service
        from ..services.jobs import utcnow as jobs_utcnow

        project = self.add_project("孤儿任务")
        with self.db() as session:
            job = GenerationJob(
                project_id=project.id, job_type="story_plan", status=JOB_STATUS_RUNNING,
                started_at=jobs_utcnow() - timedelta(minutes=10),
                last_heartbeat_at=jobs_utcnow() - timedelta(minutes=10),
            )
            session.add(job)
            session.flush()
            job_id = job.id

        self.post(f"/api/jobs/{job_id}/cancel", {})
        with self.db() as session:
            job = session.get(GenerationJob, job_id)
            self.assertEqual(job.status, "cancelled", "无心跳任务应被强制取消")

        # 心跳新鲜的 running 任务仍是"请求取消"等待节点确认
        with self.db() as session:
            job2 = GenerationJob(
                project_id=project.id, job_type="story_plan", status=JOB_STATUS_RUNNING,
                started_at=jobs_utcnow(),
                last_heartbeat_at=jobs_utcnow(),
            )
            session.add(job2)
            session.flush()
            job2_id = job2.id
        self.post(f"/api/jobs/{job2_id}/cancel", {})
        with self.db() as session:
            job2 = session.get(GenerationJob, job2_id)
            self.assertEqual(job2.status, JOB_STATUS_RUNNING)
            self.assertEqual(job2.current_step, "请求取消")

    def test_story_plan_dict_emotional_curve_normalized(self) -> None:
        """真实模型（DeepSeek）返回 dict 型情绪节点：规范化后校验通过，不触发无谓修复。"""
        from ..creative.schemas import STORY_PLAN_SCHEMA, normalize_stage_output
        from ..creative.templates import build_user_prompt
        from ..llm.base import BaseLLMAdapter
        from ..llm.base import validate_schema

        payload = {
            "title": "红帽归途",
            "logline": "穿红裙的女孩用智慧与陌生人周旋，安全抵达外婆家。",
            "synopsis": "林晓红独行送药，途中识破灰衣男子的搭讪意图。",
            "emotional_curve": [
                {"stage": "开场", "emotion": "平静"},
                {"stage": "相遇", "emotion": "不安"},
                {"stage": "高潮", "emotion": "恐惧"},
            ],
            "characters": [{"name": "林晓红", "goal": "把药送到外婆家", "arc": "从警惕到机智应对"}],
            "scenes": [{"scene_code": "SC01", "summary": "乡间公路，晓红独行"}],
        }
        normalized = normalize_stage_output("story_plan", payload)
        self.assertEqual(
            normalized["emotional_curve"], ["开场·平静", "相遇·不安", "高潮·恐惧"]
        )
        self.assertEqual(validate_schema(normalized, STORY_PLAN_SCHEMA), [])

        # 端到端：chat 返回 dict 形态 → generate_structured 一次通过（repaired=0）
        class DictCurveLLM(BaseLLMAdapter):
            name = "dict-curve"
            calls = 0

            def chat(self, settings, system, user):  # noqa: ANN001
                DictCurveLLM.calls += 1
                import json as json_module

                return json_module.dumps({
                    "title": "红帽归途", "logline": "…", "synopsis": "…",
                    "emotional_curve": [{"stage": "开场", "emotion": "平静"}],
                    "characters": [{"name": "晓红", "goal": "送药"}],
                    "scenes": [{"scene_code": "SC01", "summary": "公路独行"}],
                }, ensure_ascii=False)

        result = DictCurveLLM().generate_structured(
            self.settings, stage="story_plan", system="", user="x",
            schema=STORY_PLAN_SCHEMA, context={},
        )
        self.assertEqual(result.repaired, 0)
        self.assertEqual(result.data["emotional_curve"], ["开场·平静"])
        self.assertEqual(DictCurveLLM.calls, 1)

        # 提示词包含显式格式约束
        prompt = build_user_prompt("story_plan", {"source_text": "文本", "constraints": {}})
        self.assertIn("字符串数组", prompt)
        self.assertIn("emotional_curve", prompt)


if __name__ == "__main__":
    unittest.main()
