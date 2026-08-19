"""风险识别与生成路径建议（FR-CREATIVE-005 / 验收 26）。

系统侧确定性检测（不依赖文本模型），对任何来源的镜表统一生效：
风险标签只用于推荐工作流与提醒，用户保留覆盖权（§6.9）。
"""

from __future__ import annotations

import re

RISK_LABELS = {
    "hand_object": "手与物体接触",
    "multi_person": "多人肢体交互",
    "tool_operation": "复杂工具操作",
    "readable_text": "可读文字/界面",
    "object_appear": "物体凭空出现/消失",
    "long_action": "长距离连续动作",
    "lip_sync": "口型同步",
    "state_change": "明显状态变化",
}

_ROUTE_RULES = [
    ({"hand_object", "tool_operation"}, "建议：VACE 局部修补或手部特写参考图；必要时分拍"),
    ({"multi_person"}, "建议：MoCha/Wan Animate 角色替换或参考视频控制；优先分镜到单人"),
    ({"readable_text"}, "建议：界面文字用局部重绘生成，或后期贴图；提示词避免要求可读文字"),
    ({"object_appear"}, "建议：拆分为出现前后两镜，或用首尾帧约束"),
    ({"long_action"}, "建议：拆分为多个 4~6 秒短镜头；或提供姿态/深度控制视频"),
    ({"lip_sync"}, "建议：先在 B 卡点生成配音草稿锁定时长，再做口型约束生成"),
    ({"state_change"}, "建议：首尾帧约束 + 局部重绘衔接"),
]

_HAND_WORDS = re.compile(r"手|拿|握|抓|递|拧|掰|系|打结|指")
_TOOL_WORDS = re.compile(r"操作|拧开|安装|拆卸|接线|修理|组装|使用工具|打火|充电|按键|敲")
_TEXT_WORDS = re.compile(r"手机屏幕|屏幕|界面|短信|字|标牌|招牌|说明书|文字|编号")
_PERSON_WORDS = re.compile(r"两人|三人|多人|他们一起|拉住|扶|拥抱|推搡|搏斗|握手")
_APPEAR_WORDS = re.compile(r"突然出现|凭空|变出|消失|不见")
_LONG_WORDS = re.compile(r"穿过|跑过|走过.*米|一路|长途|连续|追")
_STATE_WORDS = re.compile(r"点燃|熄灭|破碎|融化|倒塌|变湿|变干|烧毁|充满|排空")


def detect_risks(text: str, *, has_dialogue: bool = False) -> list[str]:
    risks: list[str] = []
    if not text:
        return risks
    if _PERSON_WORDS.search(text):
        risks.append("multi_person")
    if _TOOL_WORDS.search(text) and _HAND_WORDS.search(text):
        risks.append("tool_operation")
    elif _HAND_WORDS.search(text) and re.search(r"拿|握|抓|递|拧|接", text):
        risks.append("hand_object")
    if _TEXT_WORDS.search(text):
        risks.append("readable_text")
    if _APPEAR_WORDS.search(text):
        risks.append("object_appear")
    if _LONG_WORDS.search(text):
        risks.append("long_action")
    if _STATE_WORDS.search(text):
        risks.append("state_change")
    if has_dialogue or re.search(r"说|喊|回答|问道|台词", text):
        risks.append("lip_sync")
    return risks


def route_for_risks(risks: list[str]) -> dict:
    suggestions = [rule_text for keys, rule_text in _ROUTE_RULES if keys & set(risks)]
    if not suggestions:
        return {"recommended": "默认图生视频工作流", "notes": []}
    return {"recommended": suggestions[0], "notes": suggestions[1:]}
