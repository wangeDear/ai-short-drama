from __future__ import annotations

import time
from pathlib import Path

from sqlalchemy.orm import sessionmaker

from ..config import Settings
from ..db import session_scope
from ..media import resolve_workspace_path
from ..models import GenerationJob
from ..services import jobs as jobs_service
from ..services import versions as versions_service
from .base import AdapterError, BaseAdapter, CancelRequested

SAMPLE_SEARCH_DIRS = ["outputs"]


class MockAdapter(BaseAdapter):
    """内置离线演示节点：不依赖 ComfyUI，快速产出可预览产物。

    - 图片：Pillow 生成渐变图；
    - 音频：stdlib wave 生成 1s 静音；
    - 视频：复制 workspace 中已有样例视频（如 outputs/*.mp4）；
    """

    name = "mock"

    def run(self, session_factory: sessionmaker, settings: Settings, job_id: str) -> None:
        with session_scope(session_factory) as session:
            job = session.get(GenerationJob, job_id)
            if job is None:
                return
            snapshot = job.request_snapshot or {}
            jobs_service.mark_running(session, job)
            jobs_service.append_job_log(settings, job, "Mock 节点开始生成（离线演示）")
            output_spec = snapshot.get("output") or {}
            values = snapshot.get("values") or {}
            output_type = output_spec.get("type", "video")

        try:
            time.sleep(0.2)
            self._check_cancel(session_factory, job_id)

            directory = resolve_workspace_path(settings.workspace_root, output_spec.get("dir_rel", ""))
            directory.mkdir(parents=True, exist_ok=True)
            base = output_spec.get("prefix", f"mock_{job_id}")

            if output_type == "image":
                path = self._make_image(directory, base, values)
            elif output_type in {"audio", "ambience"}:
                path = self._make_audio(directory, base, values)
            else:
                path = self._make_video(settings, directory, base, job_id)

            with session_scope(session_factory) as session:
                job = session.get(GenerationJob, job_id)
                if job is None:
                    return
                jobs_service.heartbeat(session, job, step="写入输出文件", progress=80)
                version = _get_version(session, job)
                versions_service.attach_output(session, settings, version, path, output_type)
                jobs_service.append_job_log(settings, job, f"Mock 输出: {path.name}")
                jobs_service.finish_succeeded(session, job, "Mock 生成完成（离线演示）")
        except CancelRequested:
            with session_scope(session_factory) as session:
                job = session.get(GenerationJob, job_id)
                if job is not None:
                    jobs_service.confirm_cancel(session, settings, job)
        except AdapterError as exc:
            with session_scope(session_factory) as session:
                job = session.get(GenerationJob, job_id)
                if job is not None:
                    jobs_service.finish_failed(session, job, f"[Mock] {exc}")

    def _check_cancel(self, session_factory: sessionmaker, job_id: str) -> None:
        with session_scope(session_factory) as session:
            if jobs_service.is_cancel_requested(session, job_id):
                raise CancelRequested()

    def _make_image(self, directory: Path, base: str, values: dict) -> Path:
        from PIL import Image, ImageDraw

        width = min(int(values.get("width") or 768), 1536)
        height = min(int(values.get("height") or 1152), 2048)
        prompt = str(values.get("prompt") or "")[:40]
        image = Image.new("RGB", (width, height))
        draw = ImageDraw.Draw(image)
        top = (28, 34, 46)
        bottom = (94, 72, 52)
        for y in range(height):
            ratio = y / max(1, height - 1)
            color = tuple(int(top[i] + (bottom[i] - top[i]) * ratio) for i in range(3))
            draw.line([(0, y), (width, y)], fill=color)
        draw.rectangle([16, 16, width - 16, 64], outline=(240, 180, 80), width=2)
        draw.text((28, 30), f"MOCK KEYFRAME · seed={values.get('seed')} · {prompt}", fill=(240, 220, 180))
        path = directory / f"{base}.png"
        image.save(path, "PNG")
        return path

    def _make_audio(self, directory: Path, base: str, values: dict) -> Path:
        import struct
        import wave

        duration = min(max(float(values.get("duration") or 1.0), 0.5), 5.0)
        rate = 24000
        frames = int(rate * duration)
        path = directory / f"{base}.wav"
        with wave.open(str(path), "wb") as handle:
            handle.setnchannels(1)
            handle.setsampwidth(2)
            handle.setframerate(rate)
            handle.writeframes(struct.pack("<" + "h" * frames, *([0] * frames)))
        return path

    def _make_video(self, settings: Settings, directory: Path, base: str, job_id: str) -> Path:
        source = _find_sample_video(settings)
        if source is not None:
            target = directory / f"{base}.mp4"
            target.write_bytes(source.read_bytes())
            return target

        ffmpeg = _which_ffmpeg(settings)
        if ffmpeg is None:
            raise AdapterError("未找到 ffmpeg，且工作区内没有样例视频可复制；无法生成 Mock 视频")
        target = directory / f"{base}.mp4"
        import subprocess

        result = subprocess.run(
            [ffmpeg, "-y", "-f", "lavfi", "-i", "color=c=0x2a3038:s=704x1216:d=1:r=24",
             "-f", "lavfi", "-i", "anullsrc=r=48000:cl=stereo", "-shortest",
             "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", str(target)],
            capture_output=True,
            timeout=120,
        )
        if result.returncode != 0 or not target.exists():
            raise AdapterError("ffmpeg 生成 Mock 视频失败")
        return target


def _get_version(session, job: GenerationJob):
    from ..models import ShotVersion

    if not job.version_id:
        raise AdapterError("任务缺少版本关联")
    version = session.get(ShotVersion, job.version_id)
    if version is None:
        raise AdapterError("版本不存在")
    return version


def _find_sample_video(settings: Settings) -> Path | None:
    for dirname in SAMPLE_SEARCH_DIRS:
        base = settings.workspace_root / dirname
        if not base.is_dir():
            continue
        for path in sorted(base.rglob("*.mp4")):
            if path.stat().st_size > 100:
                return path
    return None


def _which_ffmpeg(settings: Settings) -> str | None:
    import shutil

    return shutil.which(settings.ffmpeg_bin)
