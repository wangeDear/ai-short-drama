from __future__ import annotations

import hashlib
import json
import random

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import Settings
from ..models import (
    JOB_TYPE_IMAGE,
    JOB_TYPE_WORKFLOW_CATEGORY,
    JOB_TYPE_VERSION_TYPE,
    Project,
    Shot,
    ShotVersion,
    WorkflowTemplate,
)
from ..services import versions as versions_service


def output_base_name(shot_code: str, version_type: str, version_number: int) -> str:
    """输出文件基础名（§9：文件名必须包含分镜与版本信息）。"""
    return f"{shot_code}_{version_type}_v{version_number}"


def workflow_hash(workflow_json: dict) -> str:
    canonical = json.dumps(workflow_json, ensure_ascii=False, sort_keys=True)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:16]


def _set_dotted(graph: dict, dotted_path: str, value) -> None:
    parts = [part for part in dotted_path.split(".") if part]
    if len(parts) < 2:
        return
    node = graph
    for part in parts[:-1]:
        if isinstance(node, dict) and part in node:
            node = node[part]
        else:
            return
    if isinstance(node, dict):
        node[parts[-1]] = value


def apply_mapping(graph: dict, mapping: dict[str, str], values: dict) -> dict:
    """FR-COMFY-002：把业务字段写入工作流图（深拷贝，不改模板）。"""
    import copy

    rendered = copy.deepcopy(graph)
    for field, dotted_path in (mapping or {}).items():
        if field in values and values[field] is not None and dotted_path:
            _set_dotted(rendered, str(dotted_path), values[field])
    return rendered


def resolve_template(session: Session, shot: Shot, job_type: str) -> WorkflowTemplate | None:
    if shot.workflow_template_id:
        template = session.get(WorkflowTemplate, shot.workflow_template_id)
        if template is not None:
            return template
    category = JOB_TYPE_WORKFLOW_CATEGORY.get(job_type)
    if category is None:
        return None
    template = session.scalars(
        select(WorkflowTemplate)
        .where(WorkflowTemplate.category == category, WorkflowTemplate.enabled.is_(True))
        .order_by(WorkflowTemplate.updated_at.desc())
        .limit(1)
    ).first()
    return template


def prompt_values(shot: Shot, job_type: str) -> tuple[str, str]:
    if job_type in {JOB_TYPE_IMAGE, "inpaint"}:
        return shot.image_prompt or "", shot.image_negative or ""
    return shot.video_prompt or shot.image_prompt or "", shot.video_negative or ""


def parse_resolution(project: Project) -> tuple[int, int]:
    try:
        width, _, height = project.resolution.lower().partition("x")
        return int(width), int(height)
    except ValueError:
        return 1216, 704


def build_values(session: Session, settings: Settings, shot: Shot, template: WorkflowTemplate | None, job_type: str, version_number: int) -> dict:
    project = session.get(Project, shot.project_id)
    width, height = parse_resolution(project) if project else (1216, 704)
    fps = project.fps if project else 24
    prompt_text, negative_text = prompt_values(shot, job_type)

    seed = shot.seed
    if seed is None:
        seed = random.randint(0, 2**32 - 1)

    input_image = None
    input_image_path = None
    if job_type in {"video", "inpaint"}:
        image_version = versions_service.latest_version(session, shot, "image")
        if image_version is not None:
            for asset in versions_service.version_assets(session, image_version):
                if asset.asset_type == "image":
                    input_image_path = asset.file_path
                    input_image = asset.file_path.rsplit("/", 1)[-1]
                    break

    version_type = JOB_TYPE_VERSION_TYPE.get(job_type, "video")
    base_name = output_base_name(shot.shot_code, version_type, version_number)

    params = dict(shot.params_json or {})
    model_key = "image_model" if job_type in {JOB_TYPE_IMAGE, "inpaint"} else "video_model"
    model_name = params.get(model_key) or None

    return {
        "prompt": prompt_text,
        "negative": negative_text,
        "seed": seed,
        "width": width,
        "height": height,
        "fps": fps,
        "frames": max(1, int(round(shot.duration * fps))),
        "duration": shot.duration,
        "input_image": input_image,
        "input_image_path": input_image_path,
        "output_prefix": base_name,
        "model_name": model_name,
        "voice_text": shot.voice_text,
        "ambience_text": shot.ambience_text,
    }


def build_request_snapshot(
    session: Session,
    settings: Settings,
    shot: Shot,
    job_type: str,
    template: WorkflowTemplate | None,
    version: ShotVersion,
    endpoint: dict | None,
) -> dict:
    values = build_values(session, settings, shot, template, job_type, version.version_number)
    graph = None
    wf_hash = None
    if template is not None and template.workflow_json:
        graph = apply_mapping(template.workflow_json, template.parameter_mapping_json or {}, values)
        wf_hash = workflow_hash(template.workflow_json)

    project = session.get(Project, shot.project_id)
    root_rel = project.root_path if project else f"projects/{shot.project_id}"
    version_type = JOB_TYPE_VERSION_TYPE.get(job_type, "video")
    folder = {"image": "image_versions", "video": "video_versions", "audio": "audio_versions", "ambience": "audio_versions"}[version_type]
    output_dir_rel = f"{root_rel}/shots/{shot.shot_code}/{folder}"
    base_name = output_base_name(shot.shot_code, version_type, version.version_number)
    output_ext = {"image": "png", "video": "mp4", "audio": "wav", "ambience": "wav"}[version_type]

    return {
        "job_type": job_type,
        "shot": {"id": shot.id, "code": shot.shot_code, "project_id": shot.project_id},
        "workflow": {
            "id": template.id if template else None,
            "name": template.name if template else None,
            "hash": wf_hash,
            "graph": graph,
            "mapping": template.parameter_mapping_json if template else {},
        },
        "values": values,
        "output": {
            "dir_rel": output_dir_rel,
            "prefix": base_name,
            "type": version_type,
            "ext": output_ext,
        },
        "endpoint": endpoint,
        "version_id": version.id,
    }


EXAMPLE_TEMPLATES: list[dict] = [
    {
        "name": "示例 · 图生视频（占位模板，需替换为 ComfyUI API JSON）",
        "category": "h3_i2v",
        "description": "演示参数映射格式；导入真实工作流后请禁用或删除本模板。",
        "workflow_json": {
            "4": {"class_type": "CheckpointLoaderSimple", "inputs": {"ckpt_name": "model.safetensors"}},
            "5": {"class_type": "LoadImage", "inputs": {"image": "example.png"}},
            "12": {"class_type": "CLIPTextEncode", "inputs": {"text": "positive"}},
            "13": {"class_type": "CLIPTextEncode", "inputs": {"text": "negative"}},
            "24": {"class_type": "KSampler", "inputs": {"seed": 0}},
            "31": {"class_type": "SaveVideo", "inputs": {"filename_prefix": "out"}},
        },
        "parameter_mapping_json": {
            "prompt": "12.inputs.text",
            "negative": "13.inputs.text",
            "seed": "24.inputs.seed",
            "input_image": "5.inputs.image",
            "model_name": "4.inputs.ckpt_name",
            "output_prefix": "31.inputs.filename_prefix",
        },
        "required_models_json": [],
        "enabled": False,
    }
]


def seed_example_templates(session: Session) -> int:
    created = 0
    for item in EXAMPLE_TEMPLATES:
        exists = session.scalars(
            select(WorkflowTemplate).where(WorkflowTemplate.name == item["name"]).limit(1)
        ).first()
        if exists is None:
            session.add(WorkflowTemplate(**item))
            created += 1
    if created:
        session.flush()
    return created
