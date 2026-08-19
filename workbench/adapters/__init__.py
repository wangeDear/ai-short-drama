from __future__ import annotations

from sqlalchemy.orm import sessionmaker

from ..config import Settings
from ..db import session_scope
from ..models import GenerationJob
from .base import BaseAdapter
from .comfyui import ComfyUIAdapter
from .ffmpeg import FFmpegAdapter
from .llm_adapter import LLMAdapter
from .mock import MockAdapter

COMFY_JOB_TYPES = {"image", "video", "voice", "ambience", "inpaint"}
FFMPEG_JOB_TYPES = {"analyze", "compose", "export"}
LLM_ADAPTER_TYPES = {"story_plan", "script", "bible", "shot_plans"}

COMFYUI_ADAPTER = ComfyUIAdapter()
MOCK_ADAPTER = MockAdapter()
FFMPEG_ADAPTER = FFmpegAdapter()
LLM_ADAPTER = LLMAdapter()


def resolve_adapter(session_factory: sessionmaker, job_id: str) -> tuple[BaseAdapter, dict] | None:
    """返回 (适配器, endpoint信息)；None 表示任务应继续等待（无可用节点）。"""
    with session_scope(session_factory) as session:
        job = session.get(GenerationJob, job_id)
        if job is None:
            return None
        job_type = job.job_type
        endpoint_info = (job.request_snapshot or {}).get("endpoint") or {}
        if not endpoint_info and job.endpoint_id:
            from ..services.endpoints import get_endpoint

            endpoint = get_endpoint(session, job.endpoint_id)
            if endpoint is not None:
                endpoint_info = {
                    "id": endpoint.id,
                    "name": endpoint.name,
                    "type": endpoint.endpoint_type,
                    "base_url": endpoint.base_url,
                    "status": endpoint.status,
                }
        return _pick(job_type, endpoint_info)


def _pick(job_type: str, endpoint_info: dict) -> tuple[BaseAdapter, dict] | None:
    if job_type in LLM_ADAPTER_TYPES:
        return LLM_ADAPTER, endpoint_info
    if job_type in FFMPEG_JOB_TYPES:
        return FFMPEG_ADAPTER, endpoint_info
    if job_type in COMFY_JOB_TYPES:
        if not endpoint_info:
            return None
        endpoint_type = endpoint_info.get("type", "comfyui")
        if endpoint_type == "mock":
            return MOCK_ADAPTER, endpoint_info
        if not endpoint_info.get("base_url"):
            return None
        return COMFYUI_ADAPTER, endpoint_info
    return None


def dispatch(session_factory: sessionmaker, settings: Settings, job_id: str) -> None:
    resolved = resolve_adapter(session_factory, job_id)
    if resolved is None:
        with session_scope(session_factory) as session:
            job = session.get(GenerationJob, job_id)
            if job is not None:
                job.current_step = "等待可用生成节点"
                session.commit()
        return
    adapter, _endpoint_info = resolved
    adapter.run(session_factory, settings, job_id)
