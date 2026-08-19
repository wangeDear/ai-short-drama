from __future__ import annotations

from datetime import timedelta
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import Settings
from ..media import resolve_workspace_path
from ..models import (
    JOB_STATUS_CANCELLED,
    JOB_STATUS_FAILED,
    JOB_STATUS_QUEUED,
    JOB_STATUS_RUNNING,
    JOB_TYPE_COMPOSE,
    JOB_TYPE_IMAGE,
    JOB_TYPE_VIDEO,
    JOB_TYPE_WORKFLOW_CATEGORY,
    JOB_TYPE_VERSION_TYPE,
    GenerationJob,
    ModelEndpoint,
    Project,
    Shot,
    ShotVersion,
    utcnow,
)
from ..services import workflows as workflows_service
from . import versions as versions_service


class JobError(ValueError):
    pass


def job_log_path(settings: Settings, job: GenerationJob) -> Path:
    return settings.joblogs_dir / f"{job.id}.log"


def append_job_log(settings: Settings, job: GenerationJob, text: str) -> None:
    path = job_log_path(settings, job)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(text if text.endswith("\n") else text + "\n")
    job.log_path = path.name


def read_job_log(settings: Settings, job: GenerationJob, tail: int = 400) -> str:
    path = job_log_path(settings, job)
    if not path.exists():
        return ""
    lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    return "\n".join(lines[-tail:])


def _default_endpoint(session: Session, preferred_id: str | None) -> ModelEndpoint | None:
    if preferred_id:
        endpoint = session.get(ModelEndpoint, preferred_id)
        if endpoint is not None and endpoint.enabled:
            return endpoint
    return session.scalars(
        select(ModelEndpoint)
        .where(ModelEndpoint.enabled.is_(True))
        .order_by(ModelEndpoint.status.desc(), ModelEndpoint.created_at.asc())
        .limit(1)
    ).first()


def _image_gate_message(session: Session, shot: Shot) -> str | None:
    """人工审核卡点：视频生成前必须有已批准的分镜图片。

    已导入视频版本的旧分镜豁免（可直接重做视频）。
    """
    latest_image = versions_service.latest_version(session, shot, "image")
    if latest_image is not None and latest_image.status == "accepted":
        return None
    if any(version.version_type == "video" for version in shot.versions):
        return None
    return "请先生成并批准分镜图片，再提交视频生成（人工审核卡点；已导入视频的分镜可直接重做）"


def enqueue_generation(
    session: Session,
    settings: Settings,
    shot: Shot,
    job_type: str,
    *,
    endpoint_id: str | None = None,
    priority: int = 0,
    model_name: str | None = None,
) -> GenerationJob:
    version_type = JOB_TYPE_VERSION_TYPE.get(job_type)
    if version_type is None:
        raise JobError(f"不支持的任务类型: {job_type}")

    if job_type in {JOB_TYPE_VIDEO, "inpaint"}:
        blocked = _image_gate_message(session, shot)
        if blocked:
            raise JobError(blocked)

    template = workflows_service.resolve_template(session, shot, job_type)
    if template is None and not _any_endpoint(session):
        raise JobError(
            "没有可用的工作流模板或生成节点：请先在「工作流与节点」中导入模板并登记 ComfyUI 地址"
        )

    # 生成时选择的模型持久化到分镜参数（图片/视频分开记忆）
    if model_name is not None and model_name.strip():
        params = dict(shot.params_json or {})
        key = "image_model" if job_type in {JOB_TYPE_IMAGE, "inpaint"} else "video_model"
        params[key] = model_name.strip()
        shot.params_json = params
    elif model_name is not None:
        params = dict(shot.params_json or {})
        key = "image_model" if job_type in {JOB_TYPE_IMAGE, "inpaint"} else "video_model"
        params.pop(key, None)
        shot.params_json = params
    session.flush()

    endpoint = _default_endpoint(session, endpoint_id or shot.endpoint_id)
    version = versions_service.create_version(
        session,
        shot,
        version_type,
        prompt_snapshot={
            "image_prompt": shot.image_prompt,
            "image_negative": shot.image_negative,
            "video_prompt": shot.video_prompt,
            "video_negative": shot.video_negative,
            "voice_text": shot.voice_text,
            "ambience_text": shot.ambience_text,
        },
        parameter_snapshot={
            "seed": shot.seed,
            "duration": shot.duration,
            "params": shot.params_json,
            "workflow_name": template.name if template else None,
            "workflow_id": template.id if template else None,
            "endpoint_name": endpoint.name if endpoint else None,
        },
        workflow_template_id=template.id if template else None,
        workflow_hash=workflows_service.workflow_hash(template.workflow_json) if template else None,
        seed=shot.seed,
        status="queued",
    )

    endpoint_info = (
        {"id": endpoint.id, "name": endpoint.name, "type": endpoint.endpoint_type, "base_url": endpoint.base_url}
        if endpoint
        else None
    )
    request = workflows_service.build_request_snapshot(
        session, settings, shot, job_type, template, version, endpoint_info
    )

    job = GenerationJob(
        project_id=shot.project_id,
        shot_id=shot.id,
        version_id=version.id,
        job_type=job_type,
        status=JOB_STATUS_QUEUED,
        priority=priority,
        endpoint_id=endpoint.id if endpoint else None,
        endpoint_name=endpoint.name if endpoint else "",
        request_snapshot=request,
        current_step="排队中",
        queued_at=utcnow(),
    )
    session.add(job)
    session.flush()
    version.created_by_job_id = job.id
    append_job_log(settings, job, f"[{utcnow().isoformat()}] 任务入队: {job_type} / {shot.shot_code} / v{version.version_number}")
    session.flush()
    return job


def _any_endpoint(session: Session) -> bool:
    return session.scalars(select(ModelEndpoint.id).limit(1)).first() is not None


def enqueue_compose(
    session: Session,
    settings: Settings,
    project: Project,
    *,
    force: bool = False,
    config: dict | None = None,
) -> GenerationJob:
    from . import final as final_service

    readiness = final_service.readiness(session, project)
    if not readiness["ready"] and not force:
        missing = "、".join(readiness["missing"]) or "无"
        raise JobError(f"还有分镜未选择最终版本: {missing}。可先生成预览版（强制合成）。")

    config = config or {}
    entries = final_service.composition_entries(session, project)
    job = GenerationJob(
        project_id=project.id,
        job_type=JOB_TYPE_COMPOSE,
        status=JOB_STATUS_QUEUED,
        priority=0,
        current_step="排队中",
        request_snapshot={
            "job_type": JOB_TYPE_COMPOSE,
            "force": force,
            "missing": readiness["missing"],
            "entries": entries,
            "config": {
                "resolution": config.get("resolution", project.resolution),
                "fps": int(config.get("fps", project.fps)),
                "crf": int(config.get("crf", 20)),
                "preset": config.get("preset", "medium"),
                "transition": config.get("transition", "cut"),
                "with_subtitle": bool(config.get("with_subtitle", False)),
                "music_path": config.get("music_path", ""),
            },
        },
        queued_at=utcnow(),
    )
    session.add(job)
    session.flush()
    append_job_log(settings, job, f"[{utcnow().isoformat()}] 合成任务入队: {project.name}（{'强制预览' if force else '正式'}）")
    return job


def enqueue_analyze(session: Session, settings: Settings, version: ShotVersion) -> GenerationJob:
    shot = session.get(Shot, version.shot_id)
    if shot is None:
        raise JobError("分镜不存在")
    project = session.get(Project, shot.project_id)
    root_rel = project.root_path if project else f"projects/{shot.project_id}"
    assets = versions_service.version_assets(session, version)
    video_asset = next((asset for asset in assets if asset.asset_type == "video"), None)
    if video_asset is None:
        raise JobError("该版本没有视频文件")
    job = GenerationJob(
        project_id=shot.project_id,
        shot_id=shot.id,
        version_id=version.id,
        job_type="analyze",
        status=JOB_STATUS_QUEUED,
        current_step="排队中",
        request_snapshot={
            "job_type": "analyze",
            "video_path": video_asset.file_path,
            "output_dir_rel": f"{root_rel}/shots/{shot.shot_code}/inputs/extracted",
            "shot": {"id": shot.id, "code": shot.shot_code},
        },
        queued_at=utcnow(),
    )
    session.add(job)
    session.flush()
    append_job_log(settings, job, f"[{utcnow().isoformat()}] 抽帧分析任务入队: {shot.shot_code}")
    return job


def get_job(session: Session, job_id: str) -> GenerationJob | None:
    return session.get(GenerationJob, job_id)


def list_jobs(
    session: Session,
    *,
    project_id: str | None = None,
    status: str | None = None,
    active_only: bool = False,
    limit: int = 100,
) -> list[GenerationJob]:
    stmt = select(GenerationJob).order_by(GenerationJob.created_at.desc()).limit(limit)
    if project_id:
        stmt = stmt.where(GenerationJob.project_id == project_id)
    if status:
        stmt = stmt.where(GenerationJob.status == status)
    if active_only:
        stmt = stmt.where(GenerationJob.status.in_([JOB_STATUS_QUEUED, JOB_STATUS_RUNNING]))
    return list(session.scalars(stmt))


def cancel_job(session: Session, settings: Settings, job: GenerationJob) -> str:
    if job.status == JOB_STATUS_QUEUED:
        job.status = JOB_STATUS_CANCELLED
        job.finished_at = utcnow()
        job.current_step = "已取消"
        _version_status(session, job, "failed", "任务取消")
        append_job_log(settings, job, f"[{utcnow().isoformat()}] 用户取消（排队中）")
        return "任务已取消"
    if job.status == JOB_STATUS_RUNNING:
        # 心跳停止超过 90s 视为无执行体响应（服务重启孤儿 / 卡死），直接强制取消；
        # 健康任务心跳周期 ≤30s（含 LLM 等待心跳线程）。
        reference = job.last_heartbeat_at or job.started_at
        heartbeat_silent = reference is None or (utcnow() - reference).total_seconds() > 90
        if heartbeat_silent:
            confirm_cancel(session, settings, job)
            append_job_log(settings, job, f"[{utcnow().isoformat()}] 心跳已停止，强制取消（无执行节点响应）")
            return "任务已强制取消（执行心跳已停止）"
        job.current_step = "请求取消"
        append_job_log(settings, job, f"[{utcnow().isoformat()}] 用户请求取消运行中任务")
        session.flush()
        return "已请求取消，等待执行节点确认"
    raise JobError("任务已结束，无法取消")


def retry_job(session: Session, settings: Settings, job: GenerationJob) -> GenerationJob:
    if job.status not in {JOB_STATUS_FAILED, JOB_STATUS_CANCELLED}:
        raise JobError("仅失败或已取消的任务可以重试")
    job.status = JOB_STATUS_QUEUED
    job.error_message = ""
    job.progress = 0
    job.current_step = "排队中（重试）"
    job.attempt += 1
    job.finished_at = None
    job.queued_at = utcnow()
    _version_status(session, job, "queued", None)
    append_job_log(settings, job, f"[{utcnow().isoformat()}] 用户重试（第 {job.attempt} 次尝试）")
    session.flush()
    return job


def rerun_job(session: Session, settings: Settings, job: GenerationJob) -> GenerationJob:
    """使用相同参数重新运行（新任务、新版本，FR-JOB-004）。

    生成型任务会基于原快照创建新版本，并改写输出路径（prefix 带新版本号），
    保证适配器收集输出时能关联到版本且不覆盖旧文件。
    """
    snapshot = dict(job.request_snapshot or {})
    snapshot["rerun_of"] = job.id

    version_id = None
    shot = session.get(Shot, job.shot_id) if job.shot_id else None
    version_type = JOB_TYPE_VERSION_TYPE.get(job.job_type)
    if shot is not None and version_type is not None:
        old_version = session.get(ShotVersion, job.version_id) if job.version_id else None
        version = versions_service.create_version(
            session,
            shot,
            version_type,
            prompt_snapshot=dict(old_version.prompt_snapshot) if old_version else {},
            parameter_snapshot=dict(old_version.parameter_snapshot) if old_version else {},
            workflow_template_id=old_version.workflow_template_id if old_version else None,
            workflow_hash=old_version.workflow_hash if old_version else None,
            seed=old_version.seed if old_version else None,
            status="queued",
        )
        version_id = version.id
        base_name = workflows_service.output_base_name(shot.shot_code, version_type, version.version_number)
        values = dict(snapshot.get("values") or {})
        values["output_prefix"] = base_name
        snapshot["values"] = values
        output = dict(snapshot.get("output") or {})
        if output:
            output["prefix"] = base_name
            snapshot["output"] = output
        workflow = dict(snapshot.get("workflow") or {})
        graph = workflow.get("graph")
        mapping = workflow.get("mapping") or {}
        if isinstance(graph, dict) and graph and mapping:
            workflow["graph"] = workflows_service.apply_mapping(graph, mapping, values)
            snapshot["workflow"] = workflow
        snapshot["version_id"] = version.id

    new_job = GenerationJob(
        project_id=job.project_id,
        shot_id=job.shot_id,
        version_id=version_id,
        job_type=job.job_type,
        status=JOB_STATUS_QUEUED,
        priority=job.priority,
        endpoint_id=job.endpoint_id,
        endpoint_name=job.endpoint_name,
        request_snapshot=snapshot,
        current_step="排队中（重跑）",
        queued_at=utcnow(),
    )
    session.add(new_job)
    session.flush()
    append_job_log(settings, new_job, f"[{utcnow().isoformat()}] 复制自任务 {job.id}")
    if version_id is not None:
        new_version = session.get(ShotVersion, version_id)
        if new_version is not None:
            new_version.created_by_job_id = new_job.id
            session.flush()
    return new_job


def bump_priority(session: Session, job: GenerationJob, delta: int) -> None:
    job.priority = max(0, min(99, (job.priority or 0) + delta))
    session.flush()


def _version_status(session: Session, job: GenerationJob, status: str, error: str | None) -> None:
    if job.version_id:
        version = session.get(ShotVersion, job.version_id)
        if version is not None and version.status not in {"accepted", "superseded"}:
            version.status = status
            if error and status == "failed":
                parameter = dict(version.parameter_snapshot or {})
                parameter["error"] = error
                version.parameter_snapshot = parameter


def mark_running(session: Session, job: GenerationJob) -> None:
    job.status = JOB_STATUS_RUNNING
    job.started_at = job.started_at or utcnow()
    job.current_step = job.current_step or "已提交"
    session.flush()


def heartbeat(session: Session, job: GenerationJob, step: str | None = None, progress: int | None = None) -> None:
    job.last_heartbeat_at = utcnow()
    if step:
        job.current_step = step[:200]
    if progress is not None:
        job.progress = max(0, min(100, int(progress)))
    session.commit()


def finish_failed(session: Session, job: GenerationJob, message: str) -> None:
    job.status = JOB_STATUS_FAILED
    job.error_message = message[:2000]
    job.finished_at = utcnow()
    job.current_step = "失败"
    _version_status(session, job, "failed", message)
    session.commit()


def finish_succeeded(session: Session, job: GenerationJob, step: str = "生成完成") -> None:
    job.status = "succeeded"
    job.progress = 100
    job.finished_at = utcnow()
    job.current_step = step
    session.commit()


def is_cancel_requested(session: Session, job_id: str) -> bool:
    job = session.get(GenerationJob, job_id)
    if job is None:
        return True
    return job.current_step == "请求取消" or job.status == JOB_STATUS_CANCELLED


def confirm_cancel(session: Session, settings: Settings, job: GenerationJob) -> None:
    job.status = JOB_STATUS_CANCELLED
    job.finished_at = utcnow()
    job.current_step = "已取消"
    _version_status(session, job, "failed", "任务取消")
    append_job_log(settings, job, f"[{utcnow().isoformat()}] 执行节点确认取消")
    session.commit()


def recover_stale(session: Session, stale_minutes: int) -> list[str]:
    """Worker 异常退出后，超时任务标记失败，可手动重试（FR-JOB-003）。

    已请求取消的任务恢复为 cancelled（尊重用户决定），其余标 failed。
    """
    recovered: list[str] = []
    threshold = utcnow() - timedelta(minutes=stale_minutes)
    running_jobs = list(
        session.scalars(select(GenerationJob).where(GenerationJob.status == JOB_STATUS_RUNNING))
    )
    for job in running_jobs:
        reference = job.last_heartbeat_at or job.started_at
        if reference is None:
            continue
        if reference < threshold:
            if job.current_step == "请求取消":
                job.status = JOB_STATUS_CANCELLED
                job.error_message = ""
                job.current_step = "已取消（心跳超时）"
            else:
                job.status = JOB_STATUS_FAILED
                job.error_message = f"执行心跳超过 {stale_minutes} 分钟，判定 Worker 中断；可重试。"
                job.current_step = "失败（心跳超时）"
                _version_status(session, job, "failed", job.error_message)
            job.finished_at = utcnow()
            recovered.append(job.id)
    if recovered:
        session.commit()
    return recovered
