"""离线确定性文本模型（Mock LLM）。

不依赖外部 API：根据创意简报/上游结构化内容确定性生成 StoryPlan、
Script、ProductionBible、ShotPlans（含结构化提示词包），供测试与
离线演示全流程使用（与 Mock 生成节点同一设计哲学）。
"""

from __future__ import annotations

import hashlib
import json
import re

from ..config import Settings
from ..creative.risks import detect_risks, route_for_risks
from .base import BaseLLMAdapter, GenerationResult, validate_schema

SHOT_SIZES = ["远景", "全景", "中景", "近景", "特写"]
CAMERAS = ["平视", "微仰", "高角度俯拍", "过肩", "低角度"]
MOVES = ["固定", "缓推", "横移", "跟拍", "轻微手持晃动"]
LIGHTS = ["自然光", "黄昏侧逆光", "正午顶光", "夜晚火光", "阴天漫射光"]
PROP_WORDS = ["手机", "太阳能板", "水壶", "刀", "背包", "手套", "工具", "卡车", "篝火", "收音机", "地图", "绳索", "相机", "镜子", "酒瓶", "枪", "纸条", "钥匙"]
LOCATION_HINTS = ["沙漠", "森林", "城市", "房间", "办公室", "街道", "海边", "山中", "地下室", "屋顶", "车里"]
TIME_HINTS = ["清晨", "白天", "黄昏", "夜晚", "深夜", "正午"]
NEGATIVE_IMAGE = "畸形手指, 多手多脚, 文字, 水印, 低质量, 面部扭曲"
NEGATIVE_VIDEO = "画面闪烁, 人物变形, 主体漂移, 镜头撕裂, 多余肢体"


def _sentences(text: str) -> list[str]:
    parts = [s.strip() for s in re.split(r"(?<=[。！？；.!?\n])", text or "") if s.strip()]
    return parts or [(text or "").strip()]


def _seed_of(*parts: str) -> int:
    digest = hashlib.sha256("|".join(p or "" for p in parts).encode("utf-8")).hexdigest()
    return int(digest[:8], 16)


def _pick(items: list[str], seed: int, offset: int = 0):
    return items[(seed + offset) % len(items)]


def _find_words(text: str, words: list[str]) -> list[str]:
    return [word for word in words if word in text]


class MockLLMAdapter(BaseLLMAdapter):
    name = "mock"

    def chat(self, settings: Settings, system: str, user: str) -> str:  # pragma: no cover - 兜底
        return "{}"

    def model_name(self, settings: Settings) -> str:
        return "mock-llm-offline"

    # ------------------------------------------------------------------ stages
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
        builder = {
            "story_plan": self._story_plan,
            "script": self._script,
            "bible": self._bible,
            "shot_plans": self._shot_plans,
        }.get(stage)
        if builder is None:
            raise ValueError(f"mock 不支持的阶段: {stage}")
        data = builder(context)
        errors = validate_schema(data, schema)
        if errors:  # pragma: no cover - 自产数据应始终合规
            raise ValueError("mock 输出不符合 schema: " + "; ".join(errors[:5]))
        return GenerationResult(
            data=data,
            raw=json.dumps(data, ensure_ascii=False, indent=1),
            model=self.model_name(settings),
            template_version=template_version,
        )

    # ------------------------------------------------------------- story plan
    def _story_plan(self, context: dict) -> dict:
        text = context.get("source_text") or ""
        constraints = context.get("constraints") or {}
        seed = _seed_of(text)
        sents = _sentences(text)
        title = re.sub(r"[，。,.！!？?\s].*$", "", sents[0])[:16] or "未命名短剧"

        target_shots = int(constraints.get("target_shots") or 0) or (8 + seed % 5)
        scene_count = max(2, min(6, round(target_shots / 2.2)))
        locations = _find_words(text, LOCATION_HINTS) or ["野外"]
        times = _find_words(text, TIME_HINTS) or ["白天"]

        scenes = []
        for index in range(scene_count):
            summary = sents[index % len(sents)] if sents else "推进剧情"
            scenes.append({
                "scene_code": f"SC{index + 1:02d}",
                "title": f"第{index + 1}场",
                "location": _pick(locations, seed, index),
                "time_of_day": _pick(times, seed, index + 1),
                "summary": summary[:120],
                "beat": ["建立", "发展", "冲突", "转折", "高潮", "收束"][min(index, 5)],
            })

        return {
            "title": title,
            "logline": (sents[0] if sents else text)[:80],
            "synopsis": " ".join(sents)[:400],
            "characters": [
                {"name": "主角", "goal": "解决眼前困境并达成目标", "arc": "从被动应对到主动决断"},
                {"name": "配角", "goal": "推动或阻碍主角", "arc": "态度转变"},
            ],
            "conflict": sents[1][:80] if len(sents) > 1 else "主角与环境的对抗",
            "twist": sents[-1][:80] if len(sents) > 2 else "关键道具的意外作用",
            "ending": constraints.get("ending") or "留有余味的开放式结尾",
            "emotional_curve": ["平静", "紧张", "加剧", "顶点", "释放"],
            "scenes": scenes,
        }

    # ----------------------------------------------------------------- script
    def _script(self, context: dict) -> dict:
        story = context.get("story_plan") or {}
        seed = _seed_of(json.dumps(story, ensure_ascii=False, sort_keys=True))
        scenes_out = []
        for index, scene in enumerate(story.get("scenes") or []):
            summary = scene.get("summary") or ""
            props = _find_words(summary, PROP_WORDS)
            dialogue = []
            if index % 2 == 0:
                dialogue.append({"role": "主角", "line": f"必须想办法{summary[:12]}。"})
            if index % 3 == 1:
                dialogue.append({"role": "配角", "line": "别急，先看看周围有什么可用。"})
            narration = "" if dialogue else summary[:60]
            text_len = len(re.sub(r"\s", "", summary))
            duration = round(min(30.0, max(8.0, 4 + text_len / 6 + 2 * len(dialogue))), 1)
            scenes_out.append({
                "scene_code": scene.get("scene_code") or f"SC{index + 1:02d}",
                "title": scene.get("title") or f"第{index + 1}场",
                "location": scene.get("location", "野外"),
                "time_of_day": scene.get("time_of_day", "白天"),
                "action": summary or "角色推进当前目标",
                "dialogue": dialogue,
                "narration": narration,
                "goal": scene.get("beat", "推进"),
                "props": props,
                "duration": duration,
            })
        return {"scenes": scenes_out}

    # ------------------------------------------------------------------ bible
    def _bible(self, context: dict) -> dict:
        script = context.get("script") or {}
        seed = _seed_of(json.dumps(script, ensure_ascii=False, sort_keys=True))
        constraints = context.get("constraints") or {}

        names: list[str] = []
        for scene in script.get("scenes") or []:
            for line in scene.get("dialogue") or []:
                role = line.get("role", "").strip()
                if role and role not in names:
                    names.append(role)
        names = names or ["主角"]

        characters = []
        for index, name in enumerate(names):
            characters.append({
                "name": name,
                "appearance": f"{25 + seed % 10}岁左右，体型{_pick(['精瘦', '匀称', '结实'], seed, index)}",
                "hair": _pick(["短发", "微卷中发", "束发", "板寸"], seed, index + 1),
                "face": "轮廓分明，眼神坚毅" if index == 0 else "面部特征稳定，表情克制",
                "costume": f"耐磨{_pick(['工装', '外套', '衬衫'], seed, index + 2)}，全程同款",
                "voice": "低沉平稳" if index == 0 else "语速中等",
                "locked_features": ["面部特征", "服装", "发型"],
            })

        scene_json = []
        seen_locations: list[str] = []
        for scene in script.get("scenes") or []:
            location = scene.get("location", "野外")
            if location in seen_locations:
                continue
            seen_locations.append(location)
            scene_json.append({
                "name": location,
                "location": location,
                "time": scene.get("time_of_day", "白天"),
                "weather": "晴" if scene.get("time_of_day") in {"白天", "正午"} else "夜空晴朗",
                "layout": f"{location}的开阔区域，有明确前景与背景层次",
                "lighting": _pick(LIGHTS, seed, len(scene_json)),
                "palette": "暖沙色与青灰对比" if "沙漠" in location else "自然色，低饱和",
                "reusable_background": True,
            })

        all_text = json.dumps(script.get("scenes") or [], ensure_ascii=False)
        props = [
            {
                "name": word,
                "appearance": f"{word}（外观细节稳定）",
                "size": "手持尺寸",
                "material": "常规材质",
                "owner": names[0],
                "cross_shot_state": "同一状态跨镜保持",
            }
            for word in _find_words(all_text, PROP_WORDS)[:6]
        ]

        return {
            "global_style": {
                "aspect_ratio": constraints.get("aspect_ratio") or "9:16",
                "cinematic_language": "自然表演，克制运镜",
                "lens_tendency": "35mm 与 85mm 交替",
                "color": "低饱和写实",
                "grain": "轻微胶片颗粒",
                "realism": constraints.get("realism") or "写实",
                "sound_principle": "环境声为主，配乐克制",
            },
            "characters": characters,
            "scenes": scene_json,
            "props": props,
            "continuity": [
                {"aspect": "服装与发型", "rule": "全部镜头保持一致", "affected_shots": []},
                {"aspect": "关键道具状态", "rule": "道具状态只按剧本节点变化", "affected_shots": []},
            ],
        }

    # ------------------------------------------------------------- shot plans
    def _shot_plans(self, context: dict) -> dict:
        script = context.get("script") or {}
        bible = context.get("bible") or {}
        characters = {c.get("name"): c for c in bible.get("characters") or []}
        scene_settings = {s.get("name"): s for s in bible.get("scenes") or []}
        prop_names = [p.get("name") for p in bible.get("props") or []]
        style = bible.get("global_style") or {}

        shots_out = []
        counter = 0
        for scene in script.get("scenes") or []:
            scene_code = scene.get("scene_code", "")
            location = scene.get("location", "野外")
            setting = scene_settings.get(location, {})
            action = scene.get("action") or scene.get("summary") or "推进剧情"
            dialogues = scene.get("dialogue") or []
            scene_seed = _seed_of(scene_code, action)
            per_scene = 2 if len(dialogues) <= 1 else 3
            for part in range(per_scene):
                counter += 1
                shot_code = f"S{counter:02d}"
                seed = scene_seed + part
                size = SHOT_SIZES[(counter - 1) % len(SHOT_SIZES)]
                move = _pick(MOVES, seed)
                line = dialogues[part] if part < len(dialogues) else None
                involved = [d.get("role", "主角") for d in dialogues] or ["主角"]
                subject = involved[0] if size in {"中景", "近景", "特写"} else "、".join(involved)
                action_text = (action if part == 0 else f"{action}（继续，第{part + 1}拍）")[:100]
                prop_in_shot = _find_words(action + (line or {}).get("line", ""), prop_names)
                risk_text = " ".join([action_text, (line or {}).get("line", ""), " ".join(prop_in_shot)])
                risks = detect_risks(risk_text)
                costume = (characters.get(involved[0]) or {}).get("costume", "日常服装")

                shots_out.append({
                    "shot_code": shot_code,
                    "scene_code": scene_code,
                    "purpose": ("交代环境与人物关系" if part == 0 else "推进动作与对白" if part == 1 else "收束本场情绪"),
                    "duration": round(max(3.0, min(12.0, scene.get("duration", 8) / per_scene)), 1),
                    "shot_size": size,
                    "camera": _pick(CAMERAS, seed, 1),
                    "composition": f"{size}，主体置于画面{_pick(['三分线右', '中心', '三分线左'], seed, 2)}",
                    "movement": move,
                    "subject": subject,
                    "action": action_text,
                    "expression": "专注" if size == "特写" else "自然",
                    "dialogue": (line or {}).get("line", ""),
                    "scene_ref": location,
                    "costume": costume,
                    "props": prop_in_shot,
                    "continuity_prev": f"与上一镜服装/道具状态一致" if counter > 1 else "开场镜",
                    "continuity_next": "衔接下一镜同场景光线",
                    "risks": risks,
                    "route_suggestion": route_for_risks(risks),
                    "image_prompt": {
                        "identity_refs": [f"{name}（{characters.get(name, {}).get('costume', '同前')}）" for name in involved],
                        "moment": f"{subject}{action_text[:40] if size != '远景' else '所处环境的全景瞬间'}",
                        "composition": f"{size}，{_pick(CAMERAS, seed, 1)}，{_pick(['三分线右', '中心', '三分线左'], seed, 2)}构图",
                        "environment": f"{location}，{scene.get('time_of_day', '白天')}，{setting.get('weather', '晴')}",
                        "lighting": setting.get("lighting", "自然光"),
                        "lens": style.get("lens_tendency", "35mm"),
                        "style": f"{style.get('realism', '写实')}，{style.get('color', '低饱和')}，{style.get('grain', '轻微颗粒')}",
                        "negative": NEGATIVE_IMAGE,
                    },
                    "video_prompt": {
                        "input_frame": "已批准分镜图作为首帧",
                        "subject_action": action_text,
                        "object_interaction": f"与{prop_in_shot[0]}自然交互" if prop_in_shot else "无关键道具交互",
                        "camera_motion": move,
                        "timing": "前 1/3 建立，中段动作，尾 1/5 收住",
                        "boundary_constraints": "首帧与分镜图一致，尾帧动作到位不越界",
                        "negative": NEGATIVE_VIDEO,
                    },
                    "audio_prompt": {
                        "dialogue": (line or {}).get("line", ""),
                        "delivery": "自然口语，不抢画面",
                        "ambience": setting.get("sound") or f"{location}环境声",
                        "music": style.get("sound_principle", "配乐克制"),
                    },
                })
        return {"shots": shots_out}
