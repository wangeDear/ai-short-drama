"""创作链路公共定义：JSON Schema、模板版本、风险检测（v0.3 §6.2 / §10.5）。"""

from .risks import detect_risks, route_for_risks, RISK_LABELS
from .schemas import (
    BIBLE_SCHEMA,
    SCRIPT_SCHEMA,
    SHOT_PLANS_SCHEMA,
    STORY_PLAN_SCHEMA,
    TEMPLATE_VERSION,
)
from .templates import SYSTEM_PROMPT, build_user_prompt

__all__ = [
    "BIBLE_SCHEMA",
    "RISK_LABELS",
    "SCRIPT_SCHEMA",
    "SHOT_PLANS_SCHEMA",
    "STORY_PLAN_SCHEMA",
    "SYSTEM_PROMPT",
    "TEMPLATE_VERSION",
    "build_user_prompt",
    "detect_risks",
    "route_for_risks",
]
