"""四阶段提示模板（带版本号，写入生成快照以满足可追溯，验收 29）。"""

from __future__ import annotations

import json

SYSTEM_PROMPT = (
    "你是一名短视频剧本策划与分镜导演。你只输出单个合法 JSON 对象，"
    "不输出 markdown 代码块或解释文字。所有文本使用简体中文。"
)


def build_user_prompt(stage: str, context: dict) -> str:
    if stage == "story_plan":
        return (
            "根据以下创意简报生成故事方案（单个 JSON 对象）。\n"
            "字段与类型必须严格一致：\n"
            '- title/logline/synopsis/conflict/twist/ending：字符串；\n'
            '- emotional_curve：字符串数组，例如 ["平静", "不安", "紧张", "顶点", "释放"]，'
            "不要输出对象或嵌套结构；\n"
            "- characters：对象数组，每项 {name, goal, arc}（都是字符串）；\n"
            "- scenes：对象数组，每项 {scene_code, title, location, time_of_day, summary, beat}"
            "（都是字符串），scene_code 形如 SC01。\n"
            f"创意文本：{context.get('source_text', '')}\n"
            f"约束：{json.dumps(context.get('constraints') or {}, ensure_ascii=False)}"
        )
    if stage == "script":
        return (
            "根据以下故事方案生成结构化剧本（JSON）。\n"
            "要求：scenes 每项含 scene_code/title/location/time_of_day/action/dialogue[{role,line}]/"
            "narration/goal/props/duration（秒）。\n"
            "时长规则：每场 duration 建议 8~15 秒且不超过 60 秒；视频生成单镜上限 15 秒，"
            "超过 15 秒的情节必须拆分为多场。\n"
            f"故事方案：{json.dumps(context.get('story_plan') or {}, ensure_ascii=False)}"
        )
    if stage == "bible":
        return (
            "根据以下剧本提取生产设定（JSON）。\n"
            "要求：global_style（aspect_ratio/cinematic_language/lens_tendency/color/grain/realism/sound_principle）、"
            "characters（name/appearance/hair/face/costume/voice/locked_features）、"
            "scenes（name/location/time/weather/layout/lighting/palette/reusable_background）、"
            "props（name/appearance/size/material/owner/cross_shot_state）、continuity。\n"
            f"剧本：{json.dumps(context.get('script') or {}, ensure_ascii=False)}\n"
            f"约束：{json.dumps(context.get('constraints') or {}, ensure_ascii=False)}"
        )
    if stage == "shot_plans":
        return (
            "根据以下剧本和生产设定生成分镜计划（JSON）。\n"
            "要求：shots 每项含 shot_code/scene_code/purpose/duration/shot_size/camera/composition/movement/"
            "subject/action/expression/dialogue/scene_ref/costume/props/continuity_prev/continuity_next/"
            "risks/route_suggestion，以及三类结构化提示词：\n"
            "image_prompt{identity_refs,moment,composition,environment,lighting,lens,style,negative}；"
            "video_prompt{input_frame,subject_action,object_interaction,camera_motion,timing,boundary_constraints,negative}；"
            "audio_prompt{dialogue,delivery,ambience,music}。\n"
            "时长硬规则：每镜 duration 在 1~15 秒之间（视频生成单段上限 15 秒）；"
            "口型镜按台词字数÷4字/s+2秒估算；长场景必须拆分为多个 4~6 秒短镜，不得输出超过 15 秒的单镜。\n"
            "图片提示词描述画面瞬间，视频提示词描述动作与镜头运动，二者用途不同不得互相复制。\n"
            f"剧本：{json.dumps(context.get('script') or {}, ensure_ascii=False)}\n"
            f"生产设定：{json.dumps(context.get('bible') or {}, ensure_ascii=False)}"
        )
    raise ValueError(f"未知阶段: {stage}")
