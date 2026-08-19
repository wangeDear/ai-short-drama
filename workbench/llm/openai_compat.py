"""OpenAI-compatible 文本模型适配器（v0.3 §10.5）。

凭据仅从后端配置/环境变量读取，不写日志（FR-COMFY-004 同等边界）。
"""

from __future__ import annotations

import httpx

from ..config import Settings
from .base import BaseLLMAdapter, LLMError


class OpenAICompatAdapter(BaseLLMAdapter):
    name = "openai"

    def chat(self, settings: Settings, system: str, user: str) -> str:
        if not settings.llm_base_url:
            raise LLMError("未配置 llm_base_url：请在「设置 → 文本模型」页或 workbench/config.json 填写 OpenAI-compatible 地址")
        if not settings.llm_model:
            raise LLMError("未配置 llm_model：请在「设置 → 文本模型」页或 workbench/config.json 填写模型名")
        payload = {
            "model": settings.llm_model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "temperature": 0.7,
        }
        headers = {"Content-Type": "application/json"}
        if settings.llm_api_key:
            headers["Authorization"] = f"Bearer {settings.llm_api_key}"
        try:
            with httpx.Client(timeout=settings.llm_timeout_seconds) as client:
                response = client.post(f"{settings.llm_base_url}/chat/completions", json=payload, headers=headers)
        except httpx.TimeoutException:
            raise LLMError(
                f"文本模型响应超时（>{settings.llm_timeout_seconds:.0f}s）："
                "推理型模型生成大 JSON 较慢，可在「设置 → 文本模型」调大请求超时后重试"
            ) from None
        except httpx.HTTPError as exc:
            raise LLMError(f"文本模型连接失败: {exc.__class__.__name__}") from exc
        if response.status_code != 200:
            raise LLMError(f"文本模型返回 HTTP {response.status_code}: {response.text[:200]}")
        try:
            body = response.json()
            content = body["choices"][0]["message"]["content"]
        except (ValueError, KeyError, IndexError) as exc:
            raise LLMError("文本模型响应结构异常") from exc
        text = str(content or "").strip()
        if text.startswith("```"):
            text = text.strip("`")
            if text.lower().startswith("json"):
                text = text[4:]
        return text.strip()

    def model_name(self, settings: Settings) -> str:
        return settings.llm_model or self.name
