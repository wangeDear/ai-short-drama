from __future__ import annotations

import json
import re
from pathlib import Path

from sqlalchemy.orm import Session

from ..config import Settings
from ..media import resolve_workspace_path
from ..models import Project, Shot
from . import shots as shots_service
from . import versions as versions_service
from .projects import create_project, write_project_manifest

VIDEO_SUFFIXES = {".mp4", ".webm", ".mov", ".mkv"}
IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp"}
AUDIO_SUFFIXES = {".mp3", ".wav", ".flac"}


class ImportError_(ValueError):
    pass


def import_legacy_studio(session: Session, settings: Settings, json_path: str | Path) -> Project:
    """FR-PROJ-002：从旧导演审核台 studio/data/project.json 导入。"""
    path = Path(json_path)
    if not path.is_absolute():
        path = resolve_workspace_path(settings.workspace_root, json_path)
    if not path.exists():
        raise ImportError_(f"文件不存在: {json_path}")
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except ValueError as exc:
        raise ImportError_(f"JSON 解析失败: {exc}") from exc

    episode = data.get("episode") or {}
    name = data.get("title") or episode.get("title") or path.parent.name
    if name.startswith("Project023"):
        name = episode.get("title") or f"导入项目 {data.get('id', '')}"
    project = create_project(
        session,
        settings,
        name=name,
        description=episode.get("description", ""),
        aspect_ratio="9:16",
        resolution="704x1216",
        fps=24,
    )

    segments = data.get("segments") or []
    for index, segment in enumerate(segments, start=1):
        shot = shots_service.create_shot(
            session,
            project,
            shot_code=str(segment.get("id") or f"S{index:02d}"),
            title=segment.get("title", ""),
            description="",
            duration=float(segment.get("duration") or 8),
        )
        shot.video_prompt = segment.get("prompt", "")
        shot.notes = segment.get("notes", "")
        image_status = segment.get("image_status")
        if image_status == "approved":
            shot.status = "image_approved"
        session.flush()

        for version_item in reversed(segment.get("versions") or []):
            video_path = version_item.get("video_path", "")
            if not video_path:
                continue
            _try_register(session, settings, shot, "video", video_path, label=version_item.get("label", "导入"))
    write_project_manifest(session, settings, project)
    session.flush()
    return project


def import_manifest(session: Session, settings: Settings, json_path: str | Path) -> Project:
    """FR-PROJ-002：从约定 JSON 清单导入。

    格式:
    {
      "name": "...", "description": "...", "aspect_ratio": "9:16",
      "resolution": "1216x704", "fps": 24,
      "shots": [
        {"code": "S01", "title": "...", "description": "...", "duration": 8,
         "scene": "...", "characters": "主角",
         "image_prompt": "...", "image_negative": "...",
         "video_prompt": "...", "video_negative": "...",
         "voice_text": "...", "ambience_text": "...",
         "image": "outputs/x/S01.png", "videos": ["outputs/x/S01.mp4"],
         "audio": "outputs/x/S01.wav"}
      ]
    }
    """
    path = Path(json_path)
    if not path.is_absolute():
        path = resolve_workspace_path(settings.workspace_root, json_path)
    if not path.exists():
        raise ImportError_(f"文件不存在: {json_path}")
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except ValueError as exc:
        raise ImportError_(f"JSON 解析失败: {exc}") from exc

    project = create_project(
        session,
        settings,
        name=data.get("name") or path.stem,
        description=data.get("description", ""),
        aspect_ratio=data.get("aspect_ratio", "9:16"),
        resolution=data.get("resolution", "1216x704"),
        fps=int(data.get("fps", 24)),
    )

    for index, item in enumerate(data.get("shots") or [], start=1):
        shot = shots_service.create_shot(
            session,
            project,
            shot_code=item.get("code") or f"S{index:02d}",
            title=item.get("title", ""),
            description=item.get("description", ""),
            duration=float(item.get("duration") or 8),
            scene=item.get("scene", ""),
            characters=item.get("characters", ""),
        )
        shot.image_prompt = item.get("image_prompt", "")
        shot.image_negative = item.get("image_negative", "")
        shot.video_prompt = item.get("video_prompt", "")
        shot.video_negative = item.get("video_negative", "")
        shot.voice_text = item.get("voice_text", "")
        shot.ambience_text = item.get("ambience_text", "")
        session.flush()

        _try_register(session, settings, shot, "image", item.get("image"))
        _try_register(session, settings, shot, "audio", item.get("audio"))
        for video in item.get("videos") or []:
            _try_register(session, settings, shot, "video", video)

    write_project_manifest(session, settings, project)
    session.flush()
    return project


def scan_videos(
    session: Session,
    settings: Settings,
    folder: str | Path,
    *,
    project_name: str | None = None,
    prefix: str | None = None,
) -> Project:
    """FR-PROJ-002：扫描目录中的分段视频，按文件名系列前缀 + 分镜编号建项目。

    兼容 `csr_S01_00001_.mp4` / `fr2_C008_00001_.mp4` 命名；不同前缀分属不同系列，
    默认导入文件最多的前缀，可用 prefix 参数指定系列（如 "csr"）。
    """
    directory = Path(folder)
    if not directory.is_absolute():
        directory = resolve_workspace_path(settings.workspace_root, folder)
    if not directory.is_dir():
        raise ImportError_(f"目录不存在: {folder}")

    pattern = re.compile(r"^(?P<prefix>[A-Za-z][A-Za-z0-9]*)_(?P<code>[A-Za-z]+[0-9]+)_\d+")

    groups: dict[str, dict[str, list[Path]]] = {}
    loose: dict[str, list[Path]] = {}
    for file in sorted(directory.iterdir()):
        if not file.is_file() or file.suffix.lower() not in VIDEO_SUFFIXES:
            continue
        match = pattern.match(file.stem)
        if match:
            series_prefix = match.group("prefix")
            code = match.group("code").upper()
            groups.setdefault(series_prefix, {}).setdefault(code, []).append(file)
        else:
            loose.setdefault(file.stem.upper(), []).append(file)

    if not groups and loose:
        groups[directory.name] = loose
    if not groups:
        raise ImportError_(f"目录中没有可识别的视频文件: {folder}")

    if prefix is not None:
        if prefix not in groups:
            raise ImportError_(f"目录中没有前缀为 {prefix} 的视频文件")
        chosen = prefix
    else:
        chosen = max(groups, key=lambda key: sum(len(v) for v in groups[key].values()))
    series = groups[chosen]
    name = project_name or f"{chosen}（扫描导入）"
    return _build_scan_project(session, settings, name, series)


def _build_scan_project(session: Session, settings: Settings, name: str, series: dict[str, list[Path]]) -> Project:
    project = create_project(
        session,
        settings,
        name=name,
        description=f"扫描导入的 {len(series)} 个分镜",
        resolution="704x1216",
        fps=24,
    )

    ordered_codes = sorted(series.keys(), key=shots_service.natural_key)
    for sequence, code in enumerate(ordered_codes, start=1):
        shot = Shot(
            project_id=project.id,
            shot_code=code,
            title=f"场 {code}",
            sequence_index=sequence,
            duration=8.0,
        )
        session.add(shot)
        session.flush()
        for file in series[code]:
            _try_register(
                session,
                settings,
                shot,
                "video",
                file,
                label=f"导入 {file.name}",
            )

    write_project_manifest(session, settings, project)
    session.flush()
    return project


def _try_register(session: Session, settings: Settings, shot: Shot, version_type: str, path_value: str | Path | None, label: str = "导入") -> bool:
    if not path_value:
        return False
    try:
        versions_service.register_existing_output(
            session,
            settings,
            shot,
            version_type,
            str(path_value),
            label=label,
        )
        return True
    except (FileNotFoundError, ValueError):
        return False
