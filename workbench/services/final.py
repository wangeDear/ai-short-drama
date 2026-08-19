from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import Asset, Project, Shot, ShotVersion


def readiness(session: Session, project: Project) -> dict:
    """FR-FINAL-001：全部必需分镜选定最终版本才允许正式合成。"""
    shots = list(
        session.scalars(
            select(Shot).where(Shot.project_id == project.id).order_by(Shot.sequence_index)
        )
    )
    missing = [shot.shot_code for shot in shots if not shot.selected_version_id]
    return {
        "ready": bool(shots) and not missing,
        "missing": missing,
        "total": len(shots),
        "selected": len(shots) - len(missing),
    }


def composition_entries(session: Session, project: Project) -> list[dict]:
    """按分镜顺序返回 [{shot_code, version_id, asset_path, duration}]。"""
    entries: list[dict] = []
    shots = list(
        session.scalars(
            select(Shot).where(Shot.project_id == project.id).order_by(Shot.sequence_index)
        )
    )
    for shot in shots:
        version = session.get(ShotVersion, shot.selected_version_id) if shot.selected_version_id else None
        if version is None:
            continue
        asset = next(
            (
                asset
                for asset in session.scalars(
                    select(Asset).where(Asset.version_id == version.id, Asset.asset_type == "video")
                )
            ),
            None,
        )
        if asset is None:
            continue
        entries.append(
            {
                "shot_code": shot.shot_code,
                "version_id": version.id,
                "version_number": version.version_number,
                "asset_path": asset.file_path,
                "duration": asset.duration or shot.duration,
            }
        )
    return entries


def final_assets(session: Session, project: Project) -> list[Asset]:
    return list(
        session.scalars(
            select(Asset)
            .where(Asset.project_id == project.id, Asset.asset_type == "final")
            .order_by(Asset.created_at.desc())
        )
    )


def next_final_number(session: Session, project: Project) -> int:
    return len(final_assets(session, project)) + 1
