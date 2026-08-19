"""四个结构化阶段的 JSON Schema（v0.3 §10.5：模板与 schema 带版本号）。"""

TEMPLATE_VERSION = "v1"

# H3 视频管线硬限制（docs/02 §五.2：单段 >15s 尾帧跑飞）
SHOT_DURATION_MAX = 15.0
SHOT_DURATION_MIN = 1.0

_COMMON = {"type": "object", "additionalProperties": True}

STORY_PLAN_SCHEMA = {
    **_COMMON,
    "required": ["title", "logline", "synopsis", "scenes"],
    "properties": {
        "title": {"type": "string", "minLength": 1},
        "logline": {"type": "string", "minLength": 1},
        "synopsis": {"type": "string", "minLength": 1},
        "characters": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["name", "goal"],
                "properties": {"name": {"type": "string"}, "goal": {"type": "string"}, "arc": {"type": "string"}},
            },
        },
        "conflict": {"type": "string"},
        "twist": {"type": "string"},
        "ending": {"type": "string"},
        "emotional_curve": {"type": "array", "items": {}},
        "scenes": {
            "type": "array",
            "minItems": 1,
            "items": {
                "type": "object",
                "required": ["scene_code", "summary"],
                "properties": {
                    "scene_code": {"type": "string"},
                    "title": {"type": "string"},
                    "location": {"type": "string"},
                    "time_of_day": {"type": "string"},
                    "summary": {"type": "string", "minLength": 2},
                    "beat": {"type": "string"},
                },
            },
        },
    },
}

SCRIPT_SCHEMA = {
    **_COMMON,
    "required": ["scenes"],
    "properties": {
        "scenes": {
            "type": "array",
            "minItems": 1,
            "items": {
                "type": "object",
                "required": ["scene_code", "action", "duration"],
                "properties": {
                    "scene_code": {"type": "string"},
                    "title": {"type": "string"},
                    "location": {"type": "string"},
                    "time_of_day": {"type": "string"},
                    "action": {"type": "string", "minLength": 2},
                    "dialogue": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "required": ["role", "line"],
                            "properties": {"role": {"type": "string"}, "line": {"type": "string"}},
                        },
                    },
                    "narration": {"type": "string"},
                    "goal": {"type": "string"},
                    "props": {"type": "array", "items": {"type": "string"}},
                    "duration": {"type": "number", "minimum": 1, "maximum": 60},
                },
            },
        }
    },
}

BIBLE_SCHEMA = {
    **_COMMON,
    "required": ["global_style", "characters", "scenes"],
    "properties": {
        "global_style": {"type": "object"},
        "characters": {
            "type": "array",
            "minItems": 1,
            "items": {
                "type": "object",
                "required": ["name"],
                "properties": {
                    "name": {"type": "string", "minLength": 1},
                    "appearance": {"type": "string"},
                    "hair": {"type": "string"},
                    "face": {"type": "string"},
                    "costume": {"type": "string"},
                    "voice": {"type": "string"},
                    "locked_features": {"type": "array", "items": {"type": "string"}},
                },
            },
        },
        "scenes": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["name"],
                "properties": {
                    "name": {"type": "string"},
                    "location": {"type": "string"},
                    "time": {"type": "string"},
                    "weather": {"type": "string"},
                    "layout": {"type": "string"},
                    "lighting": {"type": "string"},
                    "palette": {"type": "string"},
                    "reusable_background": {"type": "boolean"},
                },
            },
        },
        "props": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["name"],
                "properties": {
                    "name": {"type": "string"},
                    "appearance": {"type": "string"},
                    "size": {"type": "string"},
                    "material": {"type": "string"},
                    "owner": {"type": "string"},
                    "cross_shot_state": {"type": "string"},
                },
            },
        },
        "continuity": {"type": "array", "items": {"type": "object"}},
    },
}

SHOT_PLANS_SCHEMA = {
    **_COMMON,
    "required": ["shots"],
    "properties": {
        "shots": {
            "type": "array",
            "minItems": 1,
            "items": {
                "type": "object",
                "required": ["shot_code", "scene_code", "duration", "image_prompt", "video_prompt", "audio_prompt"],
                "properties": {
                    "shot_code": {"type": "string"},
                    "scene_code": {"type": "string"},
                    "purpose": {"type": "string"},
                    "duration": {"type": "number", "minimum": 1, "maximum": 15},
                    "shot_size": {"type": "string"},
                    "camera": {"type": "string"},
                    "composition": {"type": "string"},
                    "movement": {"type": "string"},
                    "subject": {"type": "string"},
                    "action": {"type": "string"},
                    "expression": {"type": "string"},
                    "dialogue": {"type": "string"},
                    "scene_ref": {"type": "string"},
                    "costume": {"type": "string"},
                    "props": {"type": "array", "items": {"type": "string"}},
                    "continuity_prev": {"type": "string"},
                    "continuity_next": {"type": "string"},
                    "risks": {"type": "array", "items": {"type": "string"}},
                    "route_suggestion": {"type": "object"},
                    "image_prompt": {"type": "object"},
                    "video_prompt": {"type": "object"},
                    "audio_prompt": {"type": "object"},
                },
            },
        }
    },
}

STAGE_SCHEMAS = {
    "story_plan": STORY_PLAN_SCHEMA,
    "script": SCRIPT_SCHEMA,
    "bible": BIBLE_SCHEMA,
    "shot_plans": SHOT_PLANS_SCHEMA,
}


def _flatten_item(value) -> str:
    """dict/数字等非字符串项压平为可读文本（真实模型常返回结构化情绪节点）。"""
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, dict):
        parts = []
        for key in ("stage", "emotion", "beat", "note", "label"):
            if isinstance(value.get(key), str) and value[key].strip():
                parts.append(value[key].strip())
        if parts:
            return "·".join(dict.fromkeys(parts))
        return "·".join(f"{k}={v}" for k, v in value.items() if isinstance(v, (str, int, float)))
    return str(value)


def normalize_story_plan(data: dict) -> dict:
    """把常见的高变异字段规范到约定形态（emotional_curve 统一为字符串数组）。"""
    if not isinstance(data, dict):
        return data
    curve = data.get("emotional_curve")
    if isinstance(curve, list):
        data["emotional_curve"] = [_flatten_item(item) for item in curve]
    characters = data.get("characters")
    if isinstance(characters, list):
        normalized = []
        for character in characters:
            if isinstance(character, str):
                normalized.append({"name": character, "goal": ""})
            elif isinstance(character, dict):
                normalized.append(character)
        data["characters"] = normalized
    return data


STAGE_NORMALIZERS = {
    "story_plan": normalize_story_plan,
}


def normalize_stage_output(stage: str, data) -> dict:
    """按阶段规范化模型输出；未知阶段原样返回。校验前调用，降低无谓修复重试。"""
    normalizer = STAGE_NORMALIZERS.get(stage)
    if normalizer is None or not isinstance(data, dict):
        return data
    return normalizer(data)
