from __future__ import annotations

from pathlib import Path

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..config import Settings
from ..media import (
    guess_mime,
    probe_media,
    resolve_workspace_path,
    sha256_file,
    to_workspace_relpath,
    unique_path,
)
from ..models import (
    Review,
    Shot,
    ShotVersion,
    Asset,
    utcnow,
)


def next_version_number(session: Session, shot: Shot, version_type: str) -> int:
    current = session.scalar(
        select(func.max(ShotVersion.version_number)).where(
            ShotVersion.shot_id == shot.id, ShotVersion.version_type == version_type
        )
    )
    return (current or 0) + 1


def latest_version(session: Session, shot: Shot, version_type: str) -> ShotVersion | None:
    return session.scalars(
        select(ShotVersion)
        .where(ShotVersion.shot_id == shot.id, ShotVersion.version_type == version_type)
        .order_by(ShotVersion.version_number.desc())
        .limit(1)
    ).first()


def create_version(
    session: Session,
    shot: Shot,
    version_type: str,
    *,
    prompt_snapshot: dict | None = None,
    parameter_snapshot: dict | None = None,
    workflow_template_id: str | None = None,
    workflow_hash: str | None = None,
    seed: int | None = None,
    source: str = "generated",
    job_id: str | None = None,
    status: str = "draft",
) -> ShotVersion:
    version = ShotVersion(
        shot_id=shot.id,
        version_number=next_version_number(session, shot, version_type),
        version_type=version_type,
        status=status,
        prompt_snapshot=prompt_snapshot or {},
        parameter_snapshot=parameter_snapshot or {},
        workflow_template_id=workflow_template_id,
        workflow_hash=workflow_hash,
        seed=seed,
        source=source,
        created_by_job_id=job_id,
    )
    session.add(version)
    session.flush()
    return version


def register_asset_file(
    session: Session,
    settings: Settings,
    *,
    project_id: str,
    absolute_path: Path,
    asset_type: str,
    shot_id: str | None = None,
    version_id: str | None = None,
    character_id: str | None = None,
    original_filename: str = "",
    extra_metadata: dict | None = None,
) -> Asset:
    """把一个已存在的文件登记为资产（含哈希与媒体探测）。"""
    rel_path = to_workspace_relpath(settings.workspace_root, absolute_path)
    info = probe_media(absolute_path, settings) if absolute_path.exists() else {}
    asset = Asset(
        project_id=project_id,
        shot_id=shot_id,
        version_id=version_id,
        character_id=character_id,
        asset_type=asset_type,
        file_path=rel_path,
        original_filename=original_filename or absolute_path.name,
        mime_type=guess_mime(absolute_path),
        size_bytes=absolute_path.stat().st_size if absolute_path.exists() else 0,
        width=info.get("width"),
        height=info.get("height"),
        duration=info.get("duration"),
        fps=info.get("fps"),
        file_hash=sha256_file(absolute_path) if absolute_path.exists() else None,
        metadata_json=extra_metadata or {},
    )
    session.add(asset)
    session.flush()
    return asset


def register_existing_output(
    session: Session,
    settings: Settings,
    shot: Shot,
    version_type: str,
    relative_path: str,
    *,
    label: str = "导入",
) -> tuple[ShotVersion, Asset]:
    """登记一个已有媒体文件为该分镜的新版本（不覆盖旧版本，FR-VER-001）。"""
    absolute = resolve_workspace_path(settings.workspace_root, relative_path)
    if not absolute.exists() or not absolute.is_file():
        raise FileNotFoundError(f"文件不存在: {relative_path}")
    version = create_version(
        session,
        shot,
        version_type,
        prompt_snapshot={"label": label, "source_path": relative_path},
        parameter_snapshot={"source": "import"},
        source="imported",
        status="reviewing",
    )
    version.started_at = version.finished_at = utcnow()
    asset = register_asset_file(
        session,
        settings,
        project_id=shot.project_id,
        absolute_path=absolute,
        asset_type=version_type if version_type != "audio" else "audio",
        shot_id=shot.id,
        version_id=version.id,
        extra_metadata={"label": label},
    )
    session.flush()
    return version, asset


def attach_output(
    session: Session,
    settings: Settings,
    version: ShotVersion,
    absolute_path: Path,
    asset_type: str,
) -> Asset:
    version.status = "reviewing"
    version.finished_at = utcnow()
    if version.started_at is None:
        version.started_at = utcnow()
    asset = register_asset_file(
        session,
        settings,
        project_id=_project_id_for_version(session, version),
        absolute_path=absolute_path,
        asset_type=asset_type,
        shot_id=version.shot_id,
        version_id=version.id,
    )
    session.flush()
    return asset


def _project_id_for_version(session: Session, version: ShotVersion) -> str:
    shot = session.get(Shot, version.shot_id)
    if shot is None:
        raise ValueError(f"分镜不存在: {version.shot_id}")
    return shot.project_id


def version_assets(session: Session, version: ShotVersion) -> list[Asset]:
    return list(
        session.scalars(
            select(Asset).where(Asset.version_id == version.id).order_by(Asset.created_at.asc())
        )
    )


def get_version(session: Session, version_id: str) -> ShotVersion | None:
    return session.get(ShotVersion, version_id)


def select_final(session: Session, shot: Shot, version: ShotVersion) -> None:
    """FR-VER-003 / FR-SHOT-004：显式选择最终采用版本；旧版本保留为 superseded。"""
    if version.shot_id != shot.id:
        raise ValueError("版本不属于该分镜")
    if version.version_type != "video":
        raise ValueError("仅支持选择视频版本为最终版本")
    previous = shot.selected_version_id
    shot.selected_version_id = version.id
    shot.status = "accepted"
    shot.video_config_stale = False
    session.add(
        Review(
            project_id=shot.project_id,
            shot_id=shot.id,
            version_id=version.id,
            review_type="video",
            decision="accepted",
            comment="采用为最终版本",
        )
    )
    if previous and previous != version.id:
        old = session.get(ShotVersion, previous)
        if old is not None and old.status == "accepted":
            old.status = "superseded"
    version.status = "accepted"
    session.flush()


def version_display(version: ShotVersion) -> str:
    return f"v{version.version_number}"
