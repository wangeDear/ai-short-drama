from __future__ import annotations

import hashlib
import shutil
import subprocess
from pathlib import Path
from typing import Any

from PIL import Image, ImageOps

from .config import Settings
from .models import Asset, Project

CHUNK_SIZE = 1024 * 1024


class PathOutsideWorkspace(ValueError):
    """路径越界（安全边界，FR-COMFY-004 / 11.4）。"""


def resolve_workspace_path(workspace: Path, relative: str | Path) -> Path:
    candidate = (workspace / relative).resolve()
    try:
        candidate.relative_to(workspace.resolve())
    except ValueError as exc:
        raise PathOutsideWorkspace(f"禁止访问工作区之外的文件: {relative}") from exc
    return candidate


def to_workspace_relpath(workspace: Path, absolute: Path | str) -> str:
    path = Path(absolute).resolve()
    return path.relative_to(workspace.resolve()).as_posix()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(CHUNK_SIZE), b""):
            digest.update(chunk)
    return digest.hexdigest()


def guess_mime(path: Path) -> str:
    suffix = path.suffix.lower()
    return {
        ".png": "image/png",
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".webp": "image/webp",
        ".gif": "image/gif",
        ".mp4": "video/mp4",
        ".webm": "video/webm",
        ".mov": "video/quicktime",
        ".mkv": "video/x-matroska",
        ".mp3": "audio/mpeg",
        ".wav": "audio/wav",
        ".flac": "audio/flac",
        ".json": "application/json",
    }.get(suffix, "application/octet-stream")


def ffmpeg_available(ffmpeg_bin: str = "ffmpeg") -> bool:
    return shutil.which(ffmpeg_bin) is not None


def probe_media(path: Path, settings: Settings) -> dict[str, Any]:
    """尽量探测媒体信息；缺 ffprobe/解码器时静默降级。"""
    info: dict[str, Any] = {}
    suffix = path.suffix.lower()
    if suffix in {".png", ".jpg", ".jpeg", ".webp", ".gif"}:
        try:
            with Image.open(path) as image:
                info["width"], info["height"] = image.size
        except Exception:
            pass
        return info

    ffprobe = shutil.which(settings.ffprobe_bin)
    if ffprobe:
        try:
            result = subprocess.run(
                [
                    ffprobe,
                    "-v", "error",
                    "-select_streams", "v:0",
                    "-show_entries", "stream=width,height,avg_frame_rate,duration",
                    "-show_entries", "format=duration",
                    "-of", "json",
                    str(path),
                ],
                capture_output=True,
                text=True,
                timeout=30,
                creationflags=subprocess.CREATE_NO_WINDOW if hasattr(subprocess, "CREATE_NO_WINDOW") else 0,
            )
            if result.returncode == 0:
                import json

                data = json.loads(result.stdout or "{}")
                streams = data.get("streams") or []
                if streams:
                    stream = streams[0]
                    info["width"] = stream.get("width")
                    info["height"] = stream.get("height")
                    rate = stream.get("avg_frame_rate") or ""
                    if "/" in rate:
                        num, _, den = rate.partition("/")
                        try:
                            if den and int(den):
                                info["fps"] = round(int(num) / int(den), 2)
                        except ValueError:
                            pass
                duration = (data.get("format") or {}).get("duration") or streams and streams[0].get("duration")
                if duration:
                    try:
                        info["duration"] = round(float(duration), 2)
                    except ValueError:
                        pass
        except Exception:
            pass
    return info


def ensure_project_dirs(settings: Settings, project: Project) -> Path:
    """按需求 §9 建立项目目录骨架。"""
    root = resolve_workspace_path(settings.workspace_root, project.root_path or f"projects/{project.id}")
    for sub in ("script", "characters", "final", "logs"):
        (root / sub).mkdir(parents=True, exist_ok=True)
    return root


def shot_output_dir(settings: Settings, project: Project, shot_code: str, kind: str) -> Path:
    kinds = {"image": "image_versions", "video": "video_versions", "audio": "audio_versions", "ambience": "audio_versions"}
    folder = kinds.get(kind, "video_versions")
    root = resolve_workspace_path(settings.workspace_root, project.root_path or f"projects/{project.id}")
    target = root / "shots" / shot_code / folder
    target.mkdir(parents=True, exist_ok=True)
    return target


def make_thumbnail(settings: Settings, asset: Asset, source: Path, max_size: int = 480) -> Path | None:
    """生成缩略图（图片用 Pillow；视频依赖 ffmpeg，缺失时返回 None）。"""
    if not source.exists():
        return None
    cache_key = f"{asset.id}_{asset.file_hash or sha256_file(source)[:12]}"
    target = settings.thumbs_dir / f"{cache_key}.jpg"
    if target.exists():
        return target

    settings.thumbs_dir.mkdir(parents=True, exist_ok=True)
    suffix = source.suffix.lower()
    if suffix in {".png", ".jpg", ".jpeg", ".webp", ".gif"}:
        try:
            with Image.open(source) as image:
                image = ImageOps.exif_transpose(image)
                if image.mode not in ("RGB", "L"):
                    image = image.convert("RGB")
                image.thumbnail((max_size, max_size))
                image.save(target, "JPEG", quality=82)
            return target
        except Exception:
            return None

    ffmpeg = shutil.which(settings.ffmpeg_bin)
    if ffmpeg and suffix in {".mp4", ".webm", ".mov", ".mkv"}:
        try:
            result = subprocess.run(
                [ffmpeg, "-y", "-ss", "0.5", "-i", str(source), "-frames:v", "1", "-vf",
                 f"scale='min({max_size},iw)':-2", str(target)],
                capture_output=True,
                timeout=60,
                creationflags=subprocess.CREATE_NO_WINDOW if hasattr(subprocess, "CREATE_NO_WINDOW") else 0,
            )
            if result.returncode == 0 and target.exists():
                return target
        except Exception:
            pass
    return None


def unique_path(directory: Path, stem: str, suffix: str) -> Path:
    suffix = suffix if suffix.startswith(".") else f".{suffix}"
    candidate = directory / f"{stem}{suffix}"
    counter = 2
    while candidate.exists():
        candidate = directory / f"{stem}_{counter}{suffix}"
        counter += 1
    return candidate
