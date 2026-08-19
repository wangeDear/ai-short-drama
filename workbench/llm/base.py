"""LLM 适配器基座：schema 校验 + 有限结构修复循环（§10.5 / 验收 28）。"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

from ..config import Settings


class LLMError(RuntimeError):
    pass


@dataclass
class GenerationResult:
    data: dict
    raw: str
    model: str
    template_version: str
    repaired: int = 0
    repair_errors: list[str] = field(default_factory=list)


def validate_schema(value: Any, schema: dict, path: str = "$") -> list[str]:
    """轻量 JSON Schema 校验（type/required/properties/items/minLength），返回错误列表。"""
    errors: list[str] = []
    if not isinstance(schema, dict):
        return errors

    expected = schema.get("type")
    type_map = {
        "object": dict, "array": list, "string": str,
        "number": (int, float), "integer": int, "boolean": bool,
    }
    if expected and expected in type_map:
        python_type = type_map[expected]
        if expected == "integer" and isinstance(value, bool):
            errors.append(f"{path}: boolean 不是 integer")
        elif not isinstance(value, python_type) or (expected == "number" and isinstance(value, bool)):
            errors.append(f"{path}: 期望 {expected}，实际 {type(value).__name__}")
            return errors

    if isinstance(value, dict):
        for key in schema.get("required", []):
            if key not in value:
                errors.append(f"{path}: 缺少必填字段 {key}")
        properties = schema.get("properties", {})
        if isinstance(properties, dict):
            for key, sub_schema in properties.items():
                if key in value:
                    errors.extend(validate_schema(value[key], sub_schema, f"{path}.{key}"))
    elif isinstance(value, list):
        items = schema.get("items")
        if isinstance(items, dict):
            for index, item in enumerate(value):
                errors.extend(validate_schema(item, items, f"{path}[{index}]"))
        min_items = schema.get("minItems")
        if isinstance(min_items, int) and len(value) < min_items:
            errors.append(f"{path}: 至少需要 {min_items} 项")

    if isinstance(value, str):
        min_length = schema.get("minLength")
        if isinstance(min_length, int) and len(value.strip()) < min_length:
            errors.append(f"{path}: 长度不足")

    if isinstance(value, (int, float)) and not isinstance(value, bool):
        minimum = schema.get("minimum")
        maximum = schema.get("maximum")
        if isinstance(minimum, (int, float)) and value < minimum:
            errors.append(f"{path}: {value} 小于下限 {minimum}")
        if isinstance(maximum, (int, float)) and value > maximum:
            errors.append(f"{path}: {value} 超出上限 {maximum}")

    return errors


class BaseLLMAdapter:
    name = "base"

    def chat(self, settings: Settings, system: str, user: str) -> str:
        raise NotImplementedError

    def model_name(self, settings: Settings) -> str:
        return settings.llm_model or self.name

    def generate_structured(
        self,
        settings: Settings,
        *,
        stage: str,
        system: str,
        user: str,
        schema: dict,
        context: dict,
        template_version: str = "",
    ) -> GenerationResult:
        """生成并校验结构化输出；失败自动修复（含修复指令重试），最多 max_repair 次。

        校验前先按阶段规范化输出（如 emotional_curve 的 dict 项压平为字符串），
        避免可容错的结构差异触发不必要的修复重试。
        """
        from ..creative.schemas import normalize_stage_output

        del context  # openai 适配器走提示词；mock 子类覆写本方法
        errors: list[str] = []
        repaired = 0
        prompt_user = user
        raw = ""
        for attempt in range(1 + settings.llm_max_repair):
            raw = self.chat(settings, system, prompt_user)
            try:
                parsed = json.loads(raw)
            except ValueError as exc:
                errors.append(f"JSON 解析失败: {exc}")
                parsed = None
            if parsed is not None:
                parsed = normalize_stage_output(stage, parsed)
                errors = validate_schema(parsed, schema)
                if not errors:
                    return GenerationResult(
                        data=parsed, raw=raw, model=self.model_name(settings),
                        template_version=template_version, repaired=repaired,
                    )
            if attempt < settings.llm_max_repair:
                repaired += 1
                prompt_user = (
                    user
                    + "\n\n你上一次的输出不符合要求，错误如下：\n- "
                    + "\n- ".join(errors[:12])
                    + "\n请修正上述字段的类型/结构后重新输出完整的单个 JSON 对象"
                    "（字符串数组必须是纯字符串，对象数组必须含要求的键），不要包含任何解释文字。"
                )
        raise LLMError("结构化输出校验失败（已尝试自动修复）: " + "; ".join(errors[:8]) + f" | raw={raw[:200]}")


def get_llm_adapter(llm_type: str) -> BaseLLMAdapter:
    from .mock import MockLLMAdapter
    from .openai_compat import OpenAICompatAdapter

    if llm_type == "openai":
        return OpenAICompatAdapter()
    if llm_type == "mock":
        return MockLLMAdapter()
    raise LLMError(f"未知文本模型类型: {llm_type}（可选 mock / openai）")
