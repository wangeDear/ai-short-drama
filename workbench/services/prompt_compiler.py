"""Prompt Compiler：结构化提示词包 → 最终拼装文本（FR-CREATIVE-004）。

确定性拼装六段式风格文本；图片/视频/声音三包结构不同，产物天然不同
（验收 19：禁止同一描述复制进 image_prompt 与 video_prompt）。
修改字段后重新拼装并写回分镜，用户无需手工维护整段提示词。
"""

from __future__ import annotations

from sqlalchemy.orm import Session

from ..models import PromptPackage, Shot


def compile_image_text(image: dict, style: dict | None = None) -> str:
    parts = [
        "[身份]" + "；".join(image.get("identity_refs") or []),
        "[瞬间]" + (image.get("moment") or ""),
        "[构图]" + "；".join(filter(None, [image.get("composition"), image.get("lens")])),
        "[环境]" + "；".join(filter(None, [image.get("environment"), image.get("lighting")])),
        "[风格]" + (image.get("style") or (style or {}).get("realism") or "写实"),
    ]
    negative = image.get("negative") or ""
    text = " ".join(p for p in parts if not p.endswith("]"))
    return (text + f" [负面]{negative}" if negative else text).strip()


def compile_video_text(video: dict, shot: Shot | None = None) -> str:
    duration = f"{shot.duration:.0f}s" if shot is not None and shot.duration else ""
    parts = [
        "[输入]" + (video.get("input_frame") or "以分镜图为首帧"),
        "[主体动作]" + (video.get("subject_action") or ""),
        "[交互]" + (video.get("object_interaction") or ""),
        "[运镜]" + "；".join(filter(None, [video.get("camera_motion"), duration])),
        "[节奏]" + (video.get("timing") or ""),
        "[边界]" + (video.get("boundary_constraints") or ""),
    ]
    negative = video.get("negative") or ""
    text = " ".join(p for p in parts if not p.endswith("]"))
    return (text + f" [负面]{negative}" if negative else text).strip()


def compile_audio(audio: dict) -> tuple[str, str]:
    voice = (audio.get("dialogue") or "").strip()
    delivery = (audio.get("delivery") or "").strip()
    if voice and delivery:
        voice = f"{voice}（{delivery}）"
    ambience = (audio.get("ambience") or "").strip()
    return voice, ambience


def apply_to_shot(session: Session, shot: Shot, package: PromptPackage, style: dict | None = None) -> Shot:
    """把提示词包确定性拼装写回分镜字段（生成管线零改动即可使用）。"""
    shot.image_prompt = compile_image_text(package.image_prompt_json or {}, style)
    shot.video_prompt = compile_video_text(package.video_prompt_json or {}, shot)
    shot.voice_text, shot.ambience_text = compile_audio(package.audio_prompt_json or {})
    session.flush()
    return shot
