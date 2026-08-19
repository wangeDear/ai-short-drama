from __future__ import annotations

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import Settings
from ..models import ModelEndpoint, utcnow


class EndpointError(ValueError):
    pass


def get_endpoint(session: Session, endpoint_id: str) -> ModelEndpoint | None:
    return session.get(ModelEndpoint, endpoint_id)


def list_endpoints(session: Session) -> list[ModelEndpoint]:
    return list(session.scalars(select(ModelEndpoint).order_by(ModelEndpoint.created_at.asc())))


def create_endpoint(session: Session, *, name: str, endpoint_type: str, base_url: str) -> ModelEndpoint:
    endpoint = ModelEndpoint(
        name=name.strip() or "未命名节点",
        endpoint_type=endpoint_type if endpoint_type in {"comfyui", "mock"} else "comfyui",
        base_url=base_url.strip().rstrip("/"),
    )
    session.add(endpoint)
    session.flush()
    return endpoint


def update_endpoint(session: Session, endpoint: ModelEndpoint, *, name=None, base_url=None, enabled=None) -> None:
    if name:
        endpoint.name = name.strip()
    if base_url is not None:
        endpoint.base_url = base_url.strip().rstrip("/")
    if enabled is not None:
        endpoint.enabled = bool(enabled)
    session.flush()


def delete_endpoint(session: Session, endpoint: ModelEndpoint) -> None:
    session.delete(endpoint)
    session.flush()


def check_endpoint(session: Session, settings: Settings, endpoint: ModelEndpoint) -> str:
    """探测 ComfyUI 节点（/system_stats + /queue），更新状态与 GPU 信息。"""
    if endpoint.endpoint_type == "mock":
        endpoint.status = "online"
        endpoint.gpu_info = "内置 Mock 节点（离线演示）"
        endpoint.queue_length = 0
        endpoint.last_heartbeat_at = utcnow()
        endpoint.capabilities_json = {"mock": True}
        session.flush()
        return "online"

    if not endpoint.base_url:
        endpoint.status = "offline"
        session.flush()
        raise EndpointError("节点地址为空")

    try:
        with httpx.Client(timeout=settings.comfy_timeout_seconds) as client:
            stats = client.get(f"{endpoint.base_url}/system_stats")
            queue = client.get(f"{endpoint.base_url}/queue")
    except httpx.HTTPError as exc:
        endpoint.status = "offline"
        endpoint.last_heartbeat_at = utcnow()
        session.flush()
        raise EndpointError(f"无法连接节点: {exc.__class__.__name__}") from exc

    if stats.status_code != 200:
        endpoint.status = "offline"
        session.flush()
        raise EndpointError(f"节点返回 HTTP {stats.status_code}")

    capabilities: dict = {}
    try:
        payload = stats.json()
        capabilities["comfyui_version"] = (payload.get("system") or {}).get("comfyui_version")
        devices = payload.get("devices") or []
        if devices:
            name = devices[0].get("name", "")
            vram_total = devices[0].get("vrme_total") or devices[0].get("vram_total") or 0
            endpoint.gpu_info = f"{name} · {int(vram_total) / (1024 ** 3):.1f}GB" if vram_total else name
    except ValueError:
        pass

    queue_pending: int = 0
    if queue.status_code == 200:
        try:
            data = queue.json()
            queue_pending = len(data.get("queue_running", [])) + len(data.get("queue_pending", []))
        except ValueError:
            pass

    endpoint.status = "online"
    endpoint.queue_length = queue_pending
    previous = dict(endpoint.capabilities_json or {})
    previous.update(capabilities)
    endpoint.capabilities_json = previous
    endpoint.last_heartbeat_at = utcnow()
    session.flush()
    return "online"


def fetch_models(session: Session, settings: Settings, endpoint: ModelEndpoint) -> list[str]:
    """从 ComfyUI 拉取可用模型列表，缓存到 capabilities_json['models']。

    优先 /models（新版），回退 /object_types/CheckpointLoaderSimple（旧版）。
    """
    models: list[str] = []
    if endpoint.endpoint_type == "mock":
        models = ["mock_sd_xl.safetensors", "mock_h3_video.safetensors"]
    elif endpoint.base_url:
        try:
            with httpx.Client(timeout=settings.comfy_timeout_seconds) as client:
                response = client.get(f"{endpoint.base_url}/models")
                if response.status_code == 200:
                    payload = response.json()
                    if isinstance(payload, dict):
                        for key in ("checkpoints", "unet", "diffusion_models"):
                            if payload.get(key):
                                models = [str(item) for item in payload[key]]
                                break
                if not models:
                    response = client.get(f"{endpoint.base_url}/object_types/CheckpointLoaderSimple")
                    if response.status_code == 200:
                        payload = response.json()
                        if isinstance(payload, list):
                            models = [str(item) for item in payload]
        except (httpx.HTTPError, ValueError):
            models = []

    capabilities = dict(endpoint.capabilities_json or {})
    capabilities["models"] = sorted(set(models))
    endpoint.capabilities_json = capabilities
    endpoint.updated_at = utcnow()
    session.flush()
    return capabilities["models"]


def default_endpoint(session: Session) -> ModelEndpoint | None:
    return (
        session.scalars(
            select(ModelEndpoint)
            .where(ModelEndpoint.enabled.is_(True))
            .order_by(ModelEndpoint.status.desc(), ModelEndpoint.created_at.asc())
            .limit(1)
        ).first()
    )
