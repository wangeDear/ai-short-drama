"""文本模型适配器（v0.3 §10.5）。

- mock：离线确定性生成，无外部依赖，用于测试与离线演示全流程；
- openai：OpenAI-compatible chat/completions 接口；
- 结构化输出强制 JSON Schema 校验，失败自动修复有限次数（默认 2 次），
  仍失败抛 LLMError，禁止用不完整 JSON 静默推进（§11.1）。
"""

from .base import GenerationResult, LLMError, BaseLLMAdapter, get_llm_adapter, validate_schema
from .mock import MockLLMAdapter
from .openai_compat import OpenAICompatAdapter

__all__ = [
    "BaseLLMAdapter",
    "GenerationResult",
    "LLMError",
    "MockLLMAdapter",
    "OpenAICompatAdapter",
    "get_llm_adapter",
    "validate_schema",
]
