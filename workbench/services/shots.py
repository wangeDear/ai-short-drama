from __future__ import annotations

import re

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..models import (
    Asset,
    GenerationJob,
    Project,
    Shot,
    ShotVersion,
    WorkflowTemplate,
)

IMAGE_EDIT_FIELDS = {"image_prompt", "image_negative"}
VIDEO_EDIT_FIELDS = {
    "video_prompt",
    "video_negative",
    "params",
    "workflow_template_id",
    "endpoint_id",
    "seed",
    "duration",
}


def natural_key(value: str) -> list:
    return [int(part) if part.isdigit() else part.lower() for part in re.split(r"(\d+)", value)]


def next_sequence(session: Session, project: Project) -> int:
    current = session.scalar(
        select(func.max(Shot.sequence_index)).where(Shot.project_id == project.id)
    )
    return (current or 0) + 1


def suggest_shot_code(session: Session, project: Project) -> str:
    return f"S{next_sequence(session, project):02d}"


def get_shot(session: Session, shot_id: str) -> Shot | None:
    return session.get(Shot, shot_id)


def create_shot(
    session: Session,
    project: Project,
    *,
    shot_code: str | None = None,
    title: str = "",
    description: str = "",
    duration: float = 8.0,
    scene: str = "",
    characters: str = "",
    image_prompt: str = "",
    video_prompt: str = "",
) -> Shot:
    sequence = next_sequence(session, project)
    shot = Shot(
        project_id=project.id,
        shot_code=(shot_code or f"S{sequence:02d}").strip(),
        title=title.strip(),
        description=description or "",
        sequence_index=sequence,
        duration=float(duration or 8),
        scene=scene.strip(),
        characters=characters.strip(),
        image_prompt=image_prompt or "",
        video_prompt=video_prompt or "",
    )
    session.add(shot)
    session.flush()
    return shot


def update_shot(session: Session, shot: Shot, data: dict) -> list[str]:
    """编辑分镜并执行 §7 状态联动规则；返回发生的状态变化说明。"""
    notes: list[str] = []
    changed_image = False
    changed_video = False

    simple = {
        "title", "description", "scene", "characters", "notes",
        "shot_code",
    }
    for key in simple:
        if key in data and data[key] is not None:
            setattr(shot, key, str(data[key]))

    # §7-3/§7-7：修改配音/环境音文本 -> 已批准的对应音频版本失效；
    # 对白修改还会使需要口型/卡时长的视频配置过期（v0.3）
    for key, version_type, label in (
        ("voice_text", "audio", "配音"),
        ("ambience_text", "ambience", "环境音"),
    ):
        if key in data and data[key] is not None and (data[key] or "") != getattr(shot, key):
            old_value = getattr(shot, key) or ""
            new_value = data[key] or ""
            setattr(shot, key, new_value)
            if _invalidate_accepted_version(session, shot, version_type):
                notes.append(f"{label}文本已修改，已批准的{label}版本已失效")
            if key == "voice_text" and (old_value.strip() or new_value.strip()):
                if shot.selected_version_id:
                    shot.video_config_stale = True
                notes.append("对白已修改，口型/卡时长相关视频与成片需重做")

    for key in ("image_prompt", "image_negative"):
        if key in data and data[key] is not None and (data[key] or "") != getattr(shot, key):
            setattr(shot, key, data[key] or "")
            changed_image = True

    for key in ("video_prompt", "video_negative"):
        if key in data and data[key] is not None and (data[key] or "") != getattr(shot, key):
            setattr(shot, key, data[key] or "")
            changed_video = True

    if "duration" in data and data["duration"] not in (None, ""):
        try:
            new_duration = float(data["duration"])
            if new_duration != shot.duration:
                shot.duration = new_duration
                changed_video = True
        except (TypeError, ValueError):
            pass

    if "seed" in data:
        raw = data["seed"]
        seed = None
        if raw not in (None, ""):
            try:
                seed = int(raw)
            except (TypeError, ValueError):
                seed = None
        if seed != shot.seed:
            shot.seed = seed
            changed_video = True

    # 模型选择（图片/视频各自记忆；改动触发对应环节失效）
    for key, flag in (("image_model", "changed_image"), ("video_model", "changed_video")):
        if key in data and data[key] is not None:
            params = dict(shot.params_json or {})
            value = str(data[key]).strip() or None
            if params.get(key) != value:
                if value:
                    params[key] = value
                else:
                    params.pop(key, None)
                shot.params_json = params
                if flag == "changed_image":
                    changed_image = True
                else:
                    changed_video = True

    for key in ("workflow_template_id", "endpoint_id"):
        if key in data and data[key] is not None:
            value = data[key] or None
            if value != getattr(shot, key):
                setattr(shot, key, value)
                changed_video = True

    if "params" in data and isinstance(data["params"], dict):
        merged = dict(shot.params_json or {})
        merged.update(data["params"])
        shot.params_json = merged
        changed_video = True

    # 状态联动（§7）
    if changed_image:
        if shot.status in {"image_approved", "video_review", "accepted"}:
            shot.status = "image_review"
            notes.append("图片提示词已修改，图片需重新审核")
        if shot.selected_version_id:
            shot.video_config_stale = True
            notes.append("下游视频配置已标记为过期")

    if changed_video and shot.selected_version_id:
        shot.video_config_stale = True
        notes.append("视频配置已修改，已采用版本建议重做")

    if shot.status == "draft" and (shot.image_prompt or shot.video_prompt):
        shot.status = "image_review" if not shot.image_prompt else shot.status

    session.flush()
    return notes


def _invalidate_accepted_version(session: Session, shot: Shot, version_type: str) -> bool:
    """§7-3：文本修改使已批准的音频版本失效（退回 draft 待重新生成）。"""
    from . import versions as versions_service

    version = versions_service.latest_version(session, shot, version_type)
    if version is not None and version.status == "accepted":
        version.status = "draft"
        return True
    return False


def delete_shot(session: Session, shot: Shot) -> None:
    session.delete(shot)
    session.flush()


def filter_shots(session: Session, project: Project, filters: dict) -> list[Shot]:
    stmt = select(Shot).where(Shot.project_id == project.id)
    status = filters.get("status") or ""
    if status:
        stmt = stmt.where(Shot.status == status)
    scene = filters.get("scene") or ""
    if scene:
        stmt = stmt.where(Shot.scene.contains(scene))
    character = filters.get("character") or ""
    if character:
        stmt = stmt.where(Shot.characters.contains(character))
    workflow = filters.get("workflow") or ""
    if workflow:
        stmt = stmt.where(Shot.workflow_template_id == workflow)
    flag = filters.get("flag") or ""
    shots = list(session.scalars(stmt.order_by(Shot.sequence_index)))
    if flag == "failed":
        failed_shot_ids = set(
            session.scalars(
                select(GenerationJob.shot_id).where(
                    GenerationJob.project_id == project.id,
                    GenerationJob.status == "failed",
                )
            )
        )
        shots = [shot for shot in shots if shot.id in failed_shot_ids]
    elif flag == "revision":
        shots = [shot for shot in shots if shot.status == "needs_revision" or shot.video_config_stale]
    q = filters.get("q") or ""
    if q:
        needle = q.lower()
        shots = [
            shot
            for shot in shots
            if needle in shot.shot_code.lower()
            or needle in shot.title.lower()
            or needle in (shot.image_prompt or "").lower()
            or needle in (shot.video_prompt or "").lower()
        ]
    return shots


class ShotView:
    """分镜卡片的聚合展示数据（FR-SHOT-002）。"""

    def __init__(self) -> None:
        self.shot: Shot | None = None
        self.image_version: ShotVersion | None = None
        self.image_asset: Asset | None = None
        self.audio_asset: Asset | None = None
        self.ambience_asset: Asset | None = None
        self.video_version: ShotVersion | None = None
        self.video_asset: Asset | None = None
        self.selected_version: ShotVersion | None = None
        self.selected_asset: Asset | None = None
        self.reference_assets: list[Asset] = []
        self.jobs: list[GenerationJob] = []
        self.active_job: GenerationJob | None = None
        self.last_failed_job: GenerationJob | None = None
        self.version_counts: dict[str, int] = {}


def build_shot_views(session: Session, shots: list[Shot]) -> dict[str, ShotView]:
    if not shots:
        return {}
    shot_ids = [shot.id for shot in shots]

    versions = list(
        session.scalars(
            select(ShotVersion)
            .where(ShotVersion.shot_id.in_(shot_ids))
            .order_by(ShotVersion.created_at.asc(), ShotVersion.id.asc())
        )
    )
    version_ids = [version.id for version in versions]
    assets = list(
        session.scalars(select(Asset).where(Asset.version_id.in_(version_ids))) if version_ids else []
    )
    assets_by_version: dict[str, list[Asset]] = {}
    for asset in assets:
        assets_by_version.setdefault(asset.version_id, []).append(asset)

    refs = list(
        session.scalars(
            select(Asset).where(
                Asset.shot_id.in_(shot_ids),
                Asset.asset_type == "reference",
                Asset.version_id.is_(None),
            ).order_by(Asset.created_at.asc())
        )
    )
    refs_by_shot: dict[str, list[Asset]] = {}
    for asset in refs:
        refs_by_shot.setdefault(asset.shot_id, []).append(asset)

    jobs = list(
        session.scalars(
            select(GenerationJob)
            .where(GenerationJob.shot_id.in_(shot_ids))
            .order_by(GenerationJob.created_at.desc())
        )
    )

    views: dict[str, ShotView] = {}
    versions_by_shot: dict[str, list[ShotVersion]] = {}
    for version in versions:
        versions_by_shot.setdefault(version.shot_id, []).append(version)

    jobs_by_shot: dict[str, list[GenerationJob]] = {}
    for job in jobs:
        jobs_by_shot.setdefault(job.shot_id, []).append(job)

    selected_ids = {shot.selected_version_id for shot in shots if shot.selected_version_id}
    selected_versions = {
        version.id: version
        for version in versions
        if version.id in selected_ids
    }

    def pick_asset(version: ShotVersion | None, wanted: str) -> Asset | None:
        if version is None:
            return None
        candidates = assets_by_version.get(version.id, [])
        for asset in candidates:
            if asset.asset_type == wanted:
                return asset
        return candidates[0] if candidates else None

    for shot in shots:
        view = ShotView()
        view.shot = shot
        shot_versions = versions_by_shot.get(shot.id, [])
        counts: dict[str, int] = {}
        for version in shot_versions:
            counts[version.version_type] = counts.get(version.version_type, 0) + 1
        view.version_counts = counts

        image_versions = [v for v in shot_versions if v.version_type == "image"]
        video_versions = [v for v in shot_versions if v.version_type == "video"]
        audio_versions = [v for v in shot_versions if v.version_type == "audio"]

        view.image_version = image_versions[-1] if image_versions else None
        view.image_asset = pick_asset(view.image_version, "image")
        view.video_version = video_versions[-1] if video_versions else None
        view.video_asset = pick_asset(view.video_version, "video")
        if audio_versions:
            view.audio_asset = pick_asset(audio_versions[-1], "audio")
        view.selected_version = selected_versions.get(shot.selected_version_id or "")
        view.selected_asset = pick_asset(view.selected_version, "video")
        view.reference_assets = refs_by_shot.get(shot.id, [])
        shot_jobs = jobs_by_shot.get(shot.id, [])[:8]
        view.jobs = shot_jobs
        view.active_job = next(
            (job for job in shot_jobs if job.status in {"queued", "running"}), None
        )
        view.last_failed_job = next((job for job in shot_jobs if job.status == "failed"), None)
        views[shot.id] = view
    return views


def review_rows(session: Session, project: Project) -> list[dict]:
    """导出审核清单（FR-SHOT-005）。"""
    shots = list(
        session.scalars(select(Shot).where(Shot.project_id == project.id).order_by(Shot.sequence_index))
    )
    from ..models import SHOT_STATUS_LABELS

    rows = []
    for shot in shots:
        rows.append(
            {
                "shot_code": shot.shot_code,
                "title": shot.title,
                "status": SHOT_STATUS_LABELS.get(shot.status, shot.status),
                "selected_version": "",
                "duration": shot.duration,
                "scene": shot.scene,
                "characters": shot.characters,
                "notes": shot.notes,
            }
        )
    return rows


def workflow_options(session: Session) -> list[WorkflowTemplate]:
    return list(session.scalars(select(WorkflowTemplate).order_by(WorkflowTemplate.category, WorkflowTemplate.name)))
