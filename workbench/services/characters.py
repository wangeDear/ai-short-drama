from __future__ import annotations

from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import Settings
from ..media import resolve_workspace_path, unique_path
from ..models import Asset, Character, Project
from .versions import register_asset_file


def list_characters(session: Session, project: Project) -> list[Character]:
    return list(
        session.scalars(
            select(Character).where(Character.project_id == project.id).order_by(Character.created_at.asc())
        )
    )


def get_character(session: Session, character_id: str) -> Character | None:
    return session.get(Character, character_id)


def create_character(session: Session, project: Project, *, name: str, description: str = "", prompt_fragment: str = "", voice_config: dict | None = None) -> Character:
    character = Character(
        project_id=project.id,
        name=name.strip() or "未命名角色",
        description=description or "",
        prompt_fragment=prompt_fragment or "",
        voice_config_json=voice_config or {},
    )
    session.add(character)
    session.flush()
    return character


def update_character(session: Session, character: Character, data: dict) -> None:
    for key in ("name", "description", "prompt_fragment"):
        if key in data and data[key] is not None:
            setattr(character, key, str(data[key]))
    if isinstance(data.get("voice_config"), dict):
        character.voice_config_json = data["voice_config"]
    session.flush()


def delete_character(session: Session, character: Character) -> None:
    session.delete(character)
    session.flush()


def attach_reference_image(session: Session, settings: Settings, character: Character, uploaded: Path, original_name: str = "") -> Asset:
    directory = resolve_workspace_path(
        settings.workspace_root,
        f"{_project_root(session, character.project_id)}/characters/{character.id}",
    )
    directory.mkdir(parents=True, exist_ok=True)
    suffix = uploaded.suffix or ".png"
    target = unique_path(directory, f"{character.name}_ref", suffix)
    uploaded.replace(target)
    return register_asset_file(
        session,
        settings,
        project_id=character.project_id,
        absolute_path=target,
        asset_type="character_ref",
        character_id=character.id,
        original_filename=original_name or target.name,
        extra_metadata={"character": character.name},
    )


def _project_root(session: Session, project_id: str) -> str:
    project = session.get(Project, project_id)
    return project.root_path if project and project.root_path else f"projects/{project_id}"


def character_assets(session: Session, character: Character) -> list[Asset]:
    return list(
        session.scalars(
            select(Asset).where(Asset.character_id == character.id).order_by(Asset.created_at.desc())
        )
    )


def register_public_asset(
    session: Session,
    settings: Settings,
    project: Project,
    *,
    source: Path,
    asset_type: str,
    original_name: str = "",
    label: str = "",
) -> Asset:
    """公共资产：场景/道具参考、遮罩、控制视频等（FR-CHAR-002/003）。"""
    directory = resolve_workspace_path(
        settings.workspace_root, f"{_project_root(session, project.id)}/characters/library"
    )
    directory.mkdir(parents=True, exist_ok=True)
    suffix = source.suffix or ".bin"
    stem = (label or source.stem).strip() or source.stem
    target = unique_path(directory, stem, suffix)
    source.replace(target)
    return register_asset_file(
        session,
        settings,
        project_id=project.id,
        absolute_path=target,
        asset_type=asset_type,
        original_filename=original_name or target.name,
        extra_metadata={"label": label} if label else {},
    )


def list_project_assets(session: Session, project: Project, asset_type: str | None = None) -> list[Asset]:
    stmt = select(Asset).where(
        Asset.project_id == project.id,
        Asset.shot_id.is_(None),
        Asset.version_id.is_(None),
    ).order_by(Asset.created_at.desc())
    if asset_type:
        stmt = stmt.where(Asset.asset_type == asset_type)
    return list(session.scalars(stmt))
