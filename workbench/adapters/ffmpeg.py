from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

from sqlalchemy.orm import sessionmaker

from ..config import Settings
from ..db import session_scope
from ..media import probe_media, resolve_workspace_path
from ..models import Asset, GenerationJob, utcnow
from ..services import jobs as jobs_service
from ..services import versions as versions_service
from .base import AdapterError, BaseAdapter, CancelRequested

CREATE_NO_WINDOW = subprocess.CREATE_NO_WINDOW if hasattr(subprocess, "CREATE_NO_WINDOW") else 0


class FFmpegAdapter(BaseAdapter):
    """本地 FFmpeg 任务：最终合成（FR-FINAL）与视频抽帧分析（FR-JOB-001）。"""

    name = "ffmpeg"

    def run(self, session_factory: sessionmaker, settings: Settings, job_id: str) -> None:
        with session_scope(session_factory) as session:
            job = session.get(GenerationJob, job_id)
            if job is None:
                return
            snapshot = job.request_snapshot or {}
            jobs_service.mark_running(session, job)
            job_type = snapshot.get("job_type", job.job_type)

        try:
            if job_type == "compose":
                self._run_compose(session_factory, settings, job_id)
            elif job_type == "analyze":
                self._run_analyze(session_factory, settings, job_id)
            else:
                raise AdapterError(f"FFmpeg 适配器不支持任务类型: {job_type}")
        except CancelRequested:
            with session_scope(session_factory) as session:
                job = session.get(GenerationJob, job_id)
                if job is not None:
                    jobs_service.confirm_cancel(session, settings, job)
        except AdapterError as exc:
            with session_scope(session_factory) as session:
                job = session.get(GenerationJob, job_id)
                if job is not None:
                    jobs_service.finish_failed(session, job, f"[FFmpeg] {exc}")

    # -------------------------------------------------------------- helpers
    def _ffmpeg(self, settings: Settings) -> str:
        binary = shutil.which(settings.ffmpeg_bin)
        if binary is None:
            raise AdapterError(
                "未找到 ffmpeg。请安装 ffmpeg 并加入 PATH，或在 workbench/config.json 中配置 ffmpeg_bin"
            )
        return binary

    # -------------------------------------------------------------- compose
    def _run_compose(self, session_factory: sessionmaker, settings: Settings, job_id: str) -> None:
        ffmpeg = self._ffmpeg(settings)
        with session_scope(session_factory) as session:
            job = session.get(GenerationJob, job_id)
            assert job is not None
            snapshot = job.request_snapshot or {}
            entries = snapshot.get("entries") or []
            config = snapshot.get("config") or {}
            project_id = job.project_id or ""
            jobs_service.append_job_log(settings, job, f"开始合成 {len(entries)} 个分段")

        if not entries:
            raise AdapterError("没有可合成的分段（请先为分镜选择最终版本）")

        import tempfile

        width_s, _, height_s = str(config.get("resolution", "704x1216")).lower().partition("x")
        try:
            width, height = int(width_s), int(height_s)
        except ValueError as exc:
            raise AdapterError(f"分辨率配置无效: {config.get('resolution')}") from exc
        fps = int(config.get("fps", 24))
        crf = int(config.get("crf", 20))
        preset = str(config.get("preset", "medium"))

        work_dir = settings.joblogs_dir / job_id
        work_dir.mkdir(parents=True, exist_ok=True)
        normalized: list[Path] = []
        for index, entry in enumerate(entries):
            self._check_cancel(session_factory, job_id)
            source = resolve_workspace_path(settings.workspace_root, entry["asset_path"])
            if not source.exists():
                raise AdapterError(f"分段文件不存在: {entry['asset_path']}")
            target = work_dir / f"part_{index:03d}.mp4"
            has_audio = self._has_audio(settings, source)
            command = [
                ffmpeg, "-y", "-i", str(source),
                "-vf", f"scale={width}:{height}:force_original_aspect_ratio=decrease,pad={width}:{height}:(ow-iw)/2:(oh-ih)/2,setsar=1,fps={fps}",
                "-r", str(fps),
                "-c:v", "libx264", "-crf", str(crf), "-preset", preset,
                "-pix_fmt", "yuv420p",
            ]
            if has_audio:
                command += ["-c:a", "aac", "-b:a", "192k", "-ar", "48000", "-ac", "2"]
            else:
                command += ["-f", "lavfi", "-i", "anullsrc=r=48000:cl=stereo", "-shortest", "-c:a", "aac"]
            command += [str(target)]
            self._exec(settings, session_factory, job_id, command, f"归一化 {entry.get('shot_code', index)}",
                       progress_base=5 + int(70 * index / len(entries)), progress_span=max(1, int(70 / len(entries))))
            normalized.append(target)

        concat_list = work_dir / "concat.txt"
        concat_list.write_text(
            "\n".join(f"file '{path.as_posix()}'" for path in normalized), encoding="utf-8"
        )

        with session_scope(session_factory) as session:
            from ..services import final as final_service
            from ..models import Project

            job = session.get(GenerationJob, job_id)
            assert job is not None
            project = session.get(Project, project_id)
            version_number = final_service.next_final_number(session, project) if project else 1
            final_dir = resolve_workspace_path(
                settings.workspace_root, f"{(project.root_path if project else 'projects/' + project_id)}/final"
            )
            final_dir.mkdir(parents=True, exist_ok=True)
            stamp = utcnow().strftime("%Y%m%d_%H%M%S")
            final_path = final_dir / f"final_v{version_number}_{stamp}.mp4"
            jobs_service.heartbeat(session, job, step="拼接分段", progress=80)

        music_path = str(config.get("music_path") or "")
        command = [ffmpeg, "-y", "-f", "concat", "-safe", "0", "-i", str(concat_list)]
        if music_path:
            music = resolve_workspace_path(settings.workspace_root, music_path)
            if music.exists():
                command += [
                    "-stream_loop", "-1", "-i", str(music),
                    "-filter_complex", "[0:a][1:a]amix=inputs=2:duration=first:weights=1 0.35[a]",
                    "-map", "0:v", "-map", "[a]",
                ]
        command += ["-c:v", "copy", "-c:a", "aac", "-b:a", "192k", str(final_path)]
        self._exec(settings, session_factory, job_id, command, "拼接输出", progress_base=80, progress_span=15)

        with session_scope(session_factory) as session:
            job = session.get(GenerationJob, job_id)
            assert job is not None
            info = probe_media(final_path, settings)
            asset = Asset(
                project_id=project_id,
                asset_type="final",
                file_path=final_path.relative_to(settings.workspace_root).as_posix(),
                original_filename=final_path.name,
                mime_type="video/mp4",
                size_bytes=final_path.stat().st_size,
                width=info.get("width"),
                height=info.get("height"),
                duration=info.get("duration"),
                fps=info.get("fps"),
                metadata_json={
                    "config": config,
                    "entries": entries,
                    "force": snapshot.get("force", False),
                    "missing": snapshot.get("missing", []),
                },
                created_at=utcnow(),
            )
            session.add(asset)
            session.flush()
            jobs_service.append_job_log(settings, job, f"成片输出: {asset.file_path}")
            jobs_service.finish_succeeded(session, job, "合成完成")

    # -------------------------------------------------------------- analyze
    def _run_analyze(self, session_factory: sessionmaker, settings: Settings, job_id: str) -> None:
        ffmpeg = self._ffmpeg(settings)
        with session_scope(session_factory) as session:
            job = session.get(GenerationJob, job_id)
            assert job is not None
            snapshot = job.request_snapshot or {}
            shot_info = snapshot.get("shot") or {}
            jobs_service.append_job_log(settings, job, "抽帧分析开始")

        source = resolve_workspace_path(settings.workspace_root, snapshot.get("video_path", ""))
        if not source.exists():
            raise AdapterError(f"视频文件不存在: {snapshot.get('video_path')}")
        output_dir = resolve_workspace_path(settings.workspace_root, snapshot.get("output_dir_rel") or "tmp/analyze")
        output_dir.mkdir(parents=True, exist_ok=True)

        fps_arg = "fps=1"
        pattern = output_dir / "frame_%04d.jpg"
        command = [ffmpeg, "-y", "-i", str(source), "-vf", fps_arg, "-q:v", "3", str(pattern)]
        self._exec(settings, session_factory, job_id, command, "抽取关键帧", progress_base=10, progress_span=80)

        frames = sorted(output_dir.glob("frame_*.jpg"))
        with session_scope(session_factory) as session:
            job = session.get(GenerationJob, job_id)
            assert job is not None
            for frame in frames:
                asset = versions_service.register_asset_file(
                    session,
                    settings,
                    project_id=job.project_id or "",
                    absolute_path=frame,
                    asset_type="reference",
                    shot_id=shot_info.get("id"),
                    original_filename=frame.name,
                    extra_metadata={"source": "analyze", "shot_code": shot_info.get("code", "")},
                )
                session.add(asset)
            jobs_service.append_job_log(settings, job, f"抽出 {len(frames)} 帧")
            jobs_service.finish_succeeded(session, job, f"抽帧完成（{len(frames)} 帧）")

    # -------------------------------------------------------------- internals
    def _has_audio(self, settings: Settings, source: Path) -> bool:
        ffprobe = shutil.which(settings.ffprobe_bin)
        if ffprobe is None:
            return True
        try:
            result = subprocess.run(
                [ffprobe, "-v", "error", "-select_streams", "a", "-show_entries", "stream=index", "-of", "csv=p=0", str(source)],
                capture_output=True,
                text=True,
                timeout=30,
                creationflags=CREATE_NO_WINDOW,
            )
            return bool(result.stdout.strip())
        except (subprocess.SubprocessError, OSError):
            return True

    def _exec(
        self,
        settings: Settings,
        session_factory: sessionmaker,
        job_id: str,
        command: list[str],
        step: str,
        *,
        progress_base: int,
        progress_span: int,
    ) -> None:
        with session_scope(session_factory) as session:
            job = session.get(GenerationJob, job_id)
            if job is not None:
                jobs_service.append_job_log(settings, job, f"$ {' '.join(command[:6])} ...")
                jobs_service.heartbeat(session, job, step=step, progress=progress_base)
        try:
            result = subprocess.run(
                command,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=3600,
                creationflags=CREATE_NO_WINDOW,
            )
        except (subprocess.SubprocessError, OSError) as exc:
            raise AdapterError(f"执行 ffmpeg 失败: {exc}") from exc
        stderr_tail = (result.stderr or "").strip().splitlines()[-12:]
        if result.returncode != 0:
            with session_scope(session_factory) as session:
                job = session.get(GenerationJob, job_id)
                if job is not None:
                    jobs_service.append_job_log(settings, job, "\n".join(stderr_tail))
            raise AdapterError(f"ffmpeg 失败（exit={result.returncode}）: {' | '.join(stderr_tail[-3:])[:400]}")
        with session_scope(session_factory) as session:
            job = session.get(GenerationJob, job_id)
            if job is not None:
                jobs_service.heartbeat(session, job, step=f"{step} 完成", progress=progress_base + progress_span)

    def _check_cancel(self, session_factory: sessionmaker, job_id: str) -> None:
        with session_scope(session_factory) as session:
            if jobs_service.is_cancel_requested(session, job_id):
                raise CancelRequested()
