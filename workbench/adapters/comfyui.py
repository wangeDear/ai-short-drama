from __future__ import annotations

import time
from datetime import timedelta
from pathlib import Path

import httpx
from sqlalchemy.orm import sessionmaker

from ..config import Settings
from ..db import session_scope
from ..media import resolve_workspace_path
from ..models import GenerationJob, ShotVersion, utcnow
from ..services import jobs as jobs_service
from ..services import versions as versions_service
from .base import AdapterError, BaseAdapter, CancelRequested


class ComfyUIAdapter(BaseAdapter):
    """FR-COMFY-003：提交 /prompt、查询 /queue、/history、获取输出、解析错误。

    无状态设计：external_job_id 持久化在任务行上，Worker 重启后可凭它重新同步。
    """

    name = "comfyui"

    # ------------------------------------------------------------------ run
    def run(self, session_factory: sessionmaker, settings: Settings, job_id: str) -> None:
        with session_scope(session_factory) as session:
            job = session.get(GenerationJob, job_id)
            if job is None:
                return
            endpoint_info = (job.request_snapshot or {}).get("endpoint") or {}
            base_url = endpoint_info.get("base_url", "")
            if not base_url:
                jobs_service.finish_failed(session, job, "任务缺少 ComfyUI 节点地址，请重试或更换节点")
                return
            jobs_service.mark_running(session, job)

        try:
            with httpx.Client(timeout=settings.comfy_timeout_seconds) as client:
                prompt_id = self._ensure_submitted(session_factory, settings, client, job_id, base_url)
                self._wait_and_collect(session_factory, settings, client, job_id, base_url, prompt_id)
        except CancelRequested:
            self._cancel_remote(session_factory, settings, job_id, base_url)
            with session_scope(session_factory) as session:
                job = session.get(GenerationJob, job_id)
                if job is not None:
                    jobs_service.confirm_cancel(session, settings, job)
        except AdapterError as exc:
            with session_scope(session_factory) as session:
                job = session.get(GenerationJob, job_id)
                if job is not None and job.status != "cancelled":
                    jobs_service.finish_failed(session, job, str(exc))
        except httpx.HTTPError as exc:
            with session_scope(session_factory) as session:
                job = session.get(GenerationJob, job_id)
                if job is not None and job.status != "cancelled":
                    jobs_service.finish_failed(session, job, f"ComfyUI 连接错误: {exc.__class__.__name__}: {exc}")

    # ------------------------------------------------------------ submitted
    def _ensure_submitted(
        self,
        session_factory: sessionmaker,
        settings: Settings,
        client: httpx.Client,
        job_id: str,
        base_url: str,
    ) -> str:
        with session_scope(session_factory) as session:
            job = session.get(GenerationJob, job_id)
            assert job is not None
            if job.external_job_id:
                jobs_service.heartbeat(session, job, step="恢复监控（已提交）", progress=50)
                return job.external_job_id
            snapshot = job.request_snapshot or {}
            graph = (snapshot.get("workflow") or {}).get("graph")
            if not graph:
                raise AdapterError("工作流图为空：请检查工作流模板 JSON 与参数映射")
            values = snapshot.get("values") or {}
            self._upload_input_image(settings, client, base_url, values)
            jobs_service.append_job_log(settings, job, f"提交 /prompt -> {base_url}")

        response = client.post(f"{base_url}/prompt", json={"prompt": graph, "client_id": job_id})
        if response.status_code != 200:
            raise AdapterError(f"/prompt 返回 HTTP {response.status_code}: {response.text[:300]}")
        try:
            payload = response.json()
        except ValueError as exc:
            raise AdapterError("/prompt 响应不是 JSON") from exc

        node_errors = payload.get("node_errors") or {}
        if node_errors:
            raise AdapterError(f"工作流节点校验失败: {str(node_errors)[:500]}")
        prompt_id = payload.get("prompt_id")
        if not prompt_id:
            raise AdapterError("/prompt 未返回 prompt_id")

        with session_scope(session_factory) as session:
            job = session.get(GenerationJob, job_id)
            assert job is not None
            job.external_job_id = prompt_id
            jobs_service.heartbeat(session, job, step="已提交，等待调度", progress=20)
        return prompt_id

    def _upload_input_image(self, settings: Settings, client: httpx.Client, base_url: str, values: dict) -> None:
        rel_path = values.get("input_image_path")
        filename = values.get("input_image")
        if not rel_path or not filename:
            return
        try:
            source = resolve_workspace_path(settings.workspace_root, rel_path)
        except ValueError as exc:
            raise AdapterError(f"输入图片路径非法: {rel_path}") from exc
        if not source.exists():
            raise AdapterError(f"输入图片不存在: {rel_path}")
        try:
            response = client.post(
                f"{base_url}/upload/image",
                files={"image": (filename, source.read_bytes(), "application/octet-stream")},
                data={"overwrite": "true"},
            )
        except httpx.HTTPError as exc:
            raise AdapterError(f"上传输入图片失败: {exc.__class__.__name__}") from exc
        if response.status_code != 200:
            raise AdapterError(f"上传输入图片失败: HTTP {response.status_code}")
        try:
            payload = response.json()
        except ValueError:
            payload = {}
        remote_name = payload.get("name", filename)
        subfolder = payload.get("subfolder", "")
        values["input_image"] = f"{subfolder}/{remote_name}" if subfolder else remote_name

    # ------------------------------------------------------------- polling
    def _wait_and_collect(
        self,
        session_factory: sessionmaker,
        settings: Settings,
        client: httpx.Client,
        job_id: str,
        base_url: str,
        prompt_id: str,
    ) -> None:
        deadline = utcnow() + timedelta(minutes=settings.comfy_max_wait_minutes)
        while True:
            with session_scope(session_factory) as session:
                job = session.get(GenerationJob, job_id)
                if job is None:
                    return
                if jobs_service.is_cancel_requested(session, job_id):
                    raise CancelRequested()

            history = self._fetch_history(client, base_url, prompt_id)
            if history is not None:
                self._collect(session_factory, settings, job_id, base_url, prompt_id, history)
                return

            queue_position = self._queue_position(client, base_url, prompt_id)
            step = "生成中" if queue_position == 0 else f"排队位置 {queue_position}"
            progress = 50 if queue_position == 0 else 30
            with session_scope(session_factory) as session:
                job = session.get(GenerationJob, job_id)
                if job is None:
                    return
                if job.current_step == "请求取消":
                    raise CancelRequested()  # 取消发生在 HTTP 间隙，不再覆盖标志
                jobs_service.heartbeat(session, job, step=step, progress=progress)

            if utcnow() > deadline:
                raise AdapterError(f"等待超过 {settings.comfy_max_wait_minutes} 分钟，判定超时")
            time.sleep(max(1.0, settings.poll_interval))

    def _fetch_history(self, client: httpx.Client, base_url: str, prompt_id: str) -> dict | None:
        try:
            response = client.get(f"{base_url}/history/{prompt_id}")
        except httpx.HTTPError as exc:
            raise AdapterError(f"查询 /history 失败: {exc.__class__.__name__}") from exc
        if response.status_code != 200:
            raise AdapterError(f"/history 返回 HTTP {response.status_code}")
        try:
            payload = response.json()
        except ValueError as exc:
            raise AdapterError("/history 响应不是 JSON") from exc
        return payload.get(prompt_id)

    def _queue_position(self, client: httpx.Client, base_url: str, prompt_id: str) -> int:
        try:
            response = client.get(f"{base_url}/queue")
            if response.status_code != 200:
                return 0
            data = response.json()
        except (httpx.HTTPError, ValueError):
            return 0
        pending = data.get("queue_pending") or []
        for index, item in enumerate(pending):
            if isinstance(item, list) and item and item[0] == prompt_id:
                return index + 1
        return 0

    # ------------------------------------------------------------- collect
    def _collect(
        self,
        session_factory: sessionmaker,
        settings: Settings,
        job_id: str,
        base_url: str,
        prompt_id: str,
        history_entry: dict,
    ) -> None:
        status = history_entry.get("status") or {}
        if status.get("status_str") == "error":
            messages = status.get("messages") or []
            detail = ""
            for item in messages:
                if isinstance(item, list) and item:
                    if item[0] == "execution_error":
                        payload = item[1] if len(item) > 1 else {}
                        detail = f"{payload.get('node_type', '')}: {payload.get('exception_message', str(payload)[:200])}"
                        break
            raise AdapterError(f"ComfyUI 执行出错 {detail}".strip())

        outputs = history_entry.get("outputs") or {}
        output_spec: dict = {}
        values: dict = {}
        version_id = None
        with session_scope(session_factory) as session:
            job = session.get(GenerationJob, job_id)
            assert job is not None
            output_spec = (job.request_snapshot or {}).get("output") or {}
            values = (job.request_snapshot or {}).get("values") or {}
            version_id = job.version_id
            jobs_service.heartbeat(session, job, step="下载输出文件", progress=85)

        prefix_dir = output_spec.get("dir_rel", "")
        wanted_type = output_spec.get("type", "video")
        remote_files: list[dict] = []
        for node_payload in outputs.values():
            for key in ("images", "gifs", "video", "audio"):
                for file_info in node_payload.get(key) or []:
                    if isinstance(file_info, dict) and file_info.get("filename"):
                        remote_files.append(file_info)

        matched = [
            item
            for item in remote_files
            if (item.get("subfolder", "") + "/" + item.get("filename", "")).lstrip("/").startswith(prefix_dir)
        ] or [item for item in remote_files if item.get("type") == "output"]

        if not matched:
            available = ", ".join(item.get("filename", "?") for item in remote_files[:8]) or "无"
            raise AdapterError(f"ComfyUI 完成但没有匹配到输出文件（prefix={prefix_dir}）。可用文件: {available}")

        expected_ext = {"image": (".png", ".jpg", ".jpeg", ".webp"), "video": (".mp4", ".webm", ".mkv", ".mov"),
                        "audio": (".wav", ".mp3", ".flac"), "ambience": (".wav", ".mp3", ".flac")}.get(wanted_type)
        if expected_ext:
            preferred = [item for item in matched if Path(item.get("filename", "")).suffix.lower() in expected_ext]
            matched = preferred or matched

        primary = matched[0]
        target_dir = resolve_workspace_path(settings.workspace_root, prefix_dir)
        target_dir.mkdir(parents=True, exist_ok=True)
        target = target_dir / primary.get("filename", "output.bin")
        self._download(client, base_url, primary, target)

        extra = matched[1:4]
        for file_info in extra:
            extra_target = target_dir / file_info.get("filename", "extra.bin")
            try:
                self._download(client, base_url, file_info, extra_target)
            except AdapterError:
                continue

        with session_scope(session_factory) as session:
            job = session.get(GenerationJob, job_id)
            if job is None:
                return
            version = session.get(ShotVersion, version_id) if version_id else None
            if version is None:
                raise AdapterError("任务关联的版本不存在")
            asset_type = {"image": "image", "video": "video", "audio": "audio", "ambience": "ambience"}[wanted_type]
            versions_service.attach_output(session, settings, version, target, asset_type)
            jobs_service.append_job_log(settings, job, f"输出: {target.name}")
            jobs_service.finish_succeeded(session, job, "生成完成，等待结果审核")

    def _download(self, client: httpx.Client, base_url: str, file_info: dict, target: Path) -> None:
        params = {
            "filename": file_info.get("filename", ""),
            "subfolder": file_info.get("subfolder", ""),
            "type": file_info.get("type", "output"),
        }
        try:
            with client.stream("GET", f"{base_url}/view", params=params) as response:
                if response.status_code != 200:
                    raise AdapterError(f"下载输出失败: HTTP {response.status_code}")
                with target.open("wb") as handle:
                    for chunk in response.iter_bytes(1024 * 512):
                        handle.write(chunk)
        except httpx.HTTPError as exc:
            raise AdapterError(f"下载输出失败: {exc.__class__.__name__}") from exc

    # -------------------------------------------------------------- cancel
    def _cancel_remote(self, session_factory: sessionmaker, settings: Settings, job_id: str, base_url: str) -> None:
        with session_scope(session_factory) as session:
            job = session.get(GenerationJob, job_id)
            prompt_id = job.external_job_id if job else None
        if not prompt_id:
            return
        with httpx.Client(timeout=settings.comfy_timeout_seconds) as client:
            try:
                client.post(f"{base_url}/queue", json={"delete": [prompt_id]})
                client.post(f"{base_url}/interrupt")
            except httpx.HTTPError:
                pass
        with session_scope(session_factory) as session:
            job = session.get(GenerationJob, job_id)
            if job is not None:
                jobs_service.append_job_log(settings, job, f"已向 ComfyUI 发送取消请求 ({prompt_id})")
