"""创作链路服务（v0.3 §6.2 / FR-CREATIVE-001~005）。

- 简报/故事/剧本/圣经的版本化存取；
- 四个文本阶段经任务队列异步执行（§10.3）；
- 产物入库（失败保留原始输出，不创建残缺下游实体）；
- 工作量预估（验收 27）。
"""

from __future__ import annotations

import hashlib
import json

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..config import Settings
from ..creative.risks import detect_risks, route_for_risks
from ..creative.schemas import SHOT_DURATION_MAX, SHOT_DURATION_MIN, STAGE_SCHEMAS, TEMPLATE_VERSION
from ..creative.templates import SYSTEM_PROMPT, build_user_prompt
from ..llm import GenerationResult
from ..models import (
    GATE_A,
    GATE_B,
    JOB_STATUS_QUEUED,
    JOB_TYPE_BIBLE,
    JOB_TYPE_SCRIPT,
    JOB_TYPE_SHOT_PLANS,
    JOB_TYPE_STORY_PLAN,
    CreativeBriefVersion,
    GenerationJob,
    ProductionBibleVersion,
    Project,
    PromptPackage,
    Scene,
    Shot,
    StoryScriptVersion,
    utcnow,
)
from . import gates as gates_service
from . import jobs as jobs_service
from . import prompt_compiler
from . import shots as shots_service


class CreativeError(ValueError):
    pass


# --------------------------------------------------------------------- utils


def content_hash(payload) -> str:
    canonical = json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:32]


# --------------------------------------------------------------- lookups


def latest_brief(session: Session, project: Project) -> CreativeBriefVersion | None:
    return session.scalars(
        select(CreativeBriefVersion)
        .where(CreativeBriefVersion.project_id == project.id)
        .order_by(CreativeBriefVersion.version_number.desc())
        .limit(1)
    ).first()


def latest_struct(
    session: Session, project: Project, version_type: str, *, statuses: list[str] | None = None
) -> StoryScriptVersion | None:
    stmt = (
        select(StoryScriptVersion)
        .where(
            StoryScriptVersion.project_id == project.id,
            StoryScriptVersion.version_type == version_type,
        )
        .order_by(StoryScriptVersion.created_at.desc(), StoryScriptVersion.id.desc())
    )
    if statuses:
        rows = list(session.scalars(stmt))
        return next((row for row in rows if row.status in statuses), None)
    return session.scalars(stmt.limit(1)).first()


def latest_bible(session: Session, project: Project, *, statuses: list[str] | None = None) -> ProductionBibleVersion | None:
    stmt = (
        select(ProductionBibleVersion)
        .where(ProductionBibleVersion.project_id == project.id)
        .order_by(ProductionBibleVersion.created_at.desc(), ProductionBibleVersion.id.desc())
    )
    if statuses:
        rows = list(session.scalars(stmt))
        return next((row for row in rows if row.status in statuses), None)
    return session.scalars(stmt.limit(1)).first()


def project_scenes(session: Session, project: Project) -> list[Scene]:
    return list(
        session.scalars(
            select(Scene)
            .where(Scene.project_id == project.id)
            .order_by(Scene.sequence_index, Scene.created_at)
        )
    )


# ------------------------------------------------------------------- brief


BRIEF_CONSTRAINT_FIELDS = (
    "genre", "platform", "audience", "total_duration", "episodes",
    "aspect_ratio", "language", "realism", "dialogue_density",
    "narrative_pov", "ending", "avoid", "style_ref", "target_shots",
)


def infer_fields(source_text: str, constraints: dict) -> dict:
    """未填写项的系统推断（生成前必须展示，FR-CREATIVE-001）。"""
    inferred: dict = {}
    text = source_text or ""
    if not constraints.get("genre"):
        inferred["genre"] = "写实短剧"
    if not constraints.get("target_shots"):
        sentences = max(1, len([s for s in text.split("。") if s.strip()]))
        inferred["target_shots"] = max(6, min(24, sentences * 2 + 4))
    if not constraints.get("total_duration"):
        inferred["total_duration"] = f"{inferred.get('target_shots', 10) * 8}s"
    if not constraints.get("aspect_ratio"):
        inferred["aspect_ratio"] = "9:16"
    if not constraints.get("language"):
        inferred["language"] = "中文"
    if not constraints.get("realism"):
        inferred["realism"] = "写实"
    return inferred


def save_brief(
    session: Session,
    project: Project,
    source_text: str,
    constraints: dict | None = None,
) -> CreativeBriefVersion:
    source_text = (source_text or "").strip()
    if len(source_text) < 20:
        raise CreativeError("创意文本太短：请提供不少于 20 字的描述（验收要求 50 字以上更佳）")
    constraints = {k: v for k, v in (constraints or {}).items() if v not in (None, "")}
    inferred = infer_fields(source_text, constraints)
    current = session.scalar(
        select(func.max(CreativeBriefVersion.version_number)).where(
            CreativeBriefVersion.project_id == project.id
        )
    ) or 0
    brief = CreativeBriefVersion(
        project_id=project.id,
        version_number=current + 1,
        source_text=source_text,
        constraints_json=constraints,
        inferred_fields_json=inferred,
        content_hash=content_hash({"text": source_text, "constraints": constraints}),
        status="reviewing",
    )
    session.add(brief)
    session.flush()
    return brief


# ------------------------------------------------------------------ enqueue


def _enqueue_llm_job(
    session: Session,
    settings: Settings,
    project: Project,
    job_type: str,
    request: dict,
) -> GenerationJob:
    job = GenerationJob(
        project_id=project.id,
        job_type=job_type,
        status=JOB_STATUS_QUEUED,
        current_step="排队中",
        request_snapshot=request,
        queued_at=utcnow(),
    )
    session.add(job)
    session.flush()
    jobs_service.append_job_log(settings, job, f"[{utcnow().isoformat()}] 创作任务入队: {job_type}")
    return job


def _stage_request(stage: str, schema_name: str, context: dict, inputs: dict) -> dict:
    from ..creative.templates import build_user_prompt as _prompt

    return {
        "job_type": stage,
        "stage": stage,
        "system": SYSTEM_PROMPT,
        "user": _prompt(stage, context),
        "schema": STAGE_SCHEMAS[schema_name],
        "context": context,
        "template_version": TEMPLATE_VERSION,
        "inputs": inputs,
    }


def enqueue_story_plan(session: Session, settings: Settings, project: Project) -> GenerationJob:
    brief = latest_brief_row(session, project)
    if brief is None:
        raise CreativeError("请先保存创意简报")
    context = {
        "source_text": brief.source_text,
        "constraints": {**brief.inferred_fields_json, **brief.constraints_json},
    }
    return _enqueue_llm_job(
        session, settings, project, JOB_TYPE_STORY_PLAN,
        _stage_request("story_plan", "story_plan", context, {"brief_id": brief.id, "brief_hash": brief.content_hash}),
    )


def latest_brief_row(session: Session, project: Project) -> CreativeBriefVersion | None:
    return latest_brief(session, project)


def enqueue_script(session: Session, settings: Settings, project: Project) -> GenerationJob:
    story = latest_struct(session, project, "story_plan", statuses=["reviewing", "approved"])
    if story is None:
        raise CreativeError("请先生成故事方案")
    brief = latest_brief(session, project)
    context = {
        "story_plan": story.structured_content_json or {},
        "constraints": {**(brief.inferred_fields_json if brief else {}), **(brief.constraints_json if brief else {})},
    }
    return _enqueue_llm_job(
        session, settings, project, JOB_TYPE_SCRIPT,
        _stage_request("script", "script", context, {"story_version_id": story.id, "story_hash": story.content_hash}),
    )


def enqueue_bible(session: Session, settings: Settings, project: Project) -> GenerationJob:
    if not gates_service.gate_enabled(project, GATE_A):
        pass  # A 卡点关闭时不拦截
    elif not gates_service.gate_passed(session, project, GATE_A):
        raise CreativeError("A 卡点未通过：请先在「创意与剧本」页审核批准剧本")
    script = latest_struct(session, project, "script", statuses=["approved", "reviewing"])
    if script is None:
        raise CreativeError("请先生成结构化剧本")
    brief = latest_brief(session, project)
    context = {
        "script": script.structured_content_json or {},
        "constraints": {**(brief.inferred_fields_json if brief else {}), **(brief.constraints_json if brief else {})},
    }
    return _enqueue_llm_job(
        session, settings, project, JOB_TYPE_BIBLE,
        _stage_request("bible", "bible", context, {"script_version_id": script.id, "script_hash": script.content_hash}),
    )


def enqueue_shot_plans(
    session: Session,
    settings: Settings,
    project: Project,
    *,
    scope_shot_ids: list[str] | None = None,
) -> GenerationJob:
    """生成分镜计划。B 卡点审核的是其产物（圣经+镜表+提示词），故只要求 A 通过。"""
    if gates_service.gate_enabled(project, GATE_A) and not gates_service.gate_passed(session, project, GATE_A):
        raise CreativeError("A 卡点未通过：请先在「创意与剧本」页审核批准剧本")
    script = latest_struct(session, project, "script", statuses=["approved", "reviewing"])
    bible = latest_bible(session, project, statuses=["approved", "reviewing"])
    if script is None:
        raise CreativeError("请先生成结构化剧本")
    if bible is None:
        raise CreativeError("请先生成生产设定（B 阶段输入）")
    context = {"script": script.structured_content_json or {}, "bible": _bible_content(bible)}
    request = _stage_request("shot_plans", "shot_plans", context, {
        "script_version_id": script.id,
        "bible_version_id": bible.id,
        "script_hash": script.content_hash,
        "bible_hash": bible.content_hash,
    })
    if scope_shot_ids:
        scope_shots = [session.get(Shot, sid) for sid in scope_shot_ids]
        scope_codes = [s.shot_code for s in scope_shots if s is not None]
        request["scope_shot_codes"] = scope_codes
        request["context"]["only_shots"] = scope_codes
    return _enqueue_llm_job(session, settings, project, JOB_TYPE_SHOT_PLANS, request)


def _bible_content(bible: ProductionBibleVersion) -> dict:
    return {
        "global_style": bible.global_style_json or {},
        "characters": bible.characters_json or [],
        "scenes": bible.scenes_json or [],
        "props": bible.props_json or [],
        "continuity": bible.continuity_json or [],
    }


# ------------------------------------------------------------------ ingest


def record_failed_struct(
    session: Session,
    project: Project,
    version_type: str,
    job: GenerationJob,
    raw: str,
    error: str,
    parent_version_id: str | None = None,
):
    """结构化生成失败：保留原始输出供查看，不创建残缺下游实体（验收 28）。"""
    if version_type in {"story_plan", "script"}:
        row = StoryScriptVersion(
            project_id=project.id,
            parent_version_id=parent_version_id,
            created_by_job_id=job.id,
            version_type=version_type,
            schema_version=TEMPLATE_VERSION,
            structured_content_json={},
            raw_model_output=(raw or "")[:20000],
            model_snapshot_json={"llm": (job.request_snapshot or {}).get("llm_model", "")},
            prompt_template_version=TEMPLATE_VERSION,
            content_hash="",
            status="failed",
        )
        session.add(row)
        session.flush()
        return row
    return None


def ingest_story_plan(session: Session, project: Project, job: GenerationJob, result: GenerationResult) -> StoryScriptVersion:
    brief_id = (job.request_snapshot or {}).get("inputs", {}).get("brief_id")
    row = StoryScriptVersion(
        project_id=project.id,
        created_by_job_id=job.id,
        version_type="story_plan",
        schema_version=TEMPLATE_VERSION,
        structured_content_json=result.data,
        raw_model_output=result.raw[:20000],
        model_snapshot_json={"llm": result.model, "template": result.template_version, "repaired": result.repaired},
        prompt_template_version=result.template_version or TEMPLATE_VERSION,
        content_hash=content_hash(result.data),
        status="reviewing",
    )
    session.add(row)
    session.flush()
    _mark_superseded(session, project, "story_plan", row.id)
    _record_deps(session, project.id, "brief", str(brief_id or ""), "story_plan", row)
    return row


def ingest_script(session: Session, project: Project, job: GenerationJob, result: GenerationResult) -> StoryScriptVersion:
    story_id = (job.request_snapshot or {}).get("inputs", {}).get("story_version_id")
    row = StoryScriptVersion(
        project_id=project.id,
        parent_version_id=story_id,
        created_by_job_id=job.id,
        version_type="script",
        schema_version=TEMPLATE_VERSION,
        structured_content_json=result.data,
        raw_model_output=result.raw[:20000],
        model_snapshot_json={"llm": result.model, "template": result.template_version, "repaired": result.repaired},
        prompt_template_version=result.template_version or TEMPLATE_VERSION,
        content_hash=content_hash(result.data),
        status="reviewing",
    )
    session.add(row)
    session.flush()

    # 场景实体（§8.12）：仅成功时创建
    existing = {scene.scene_code for scene in project_scenes(session, project)}
    for index, scene_data in enumerate(result.data.get("scenes") or [], start=1):
        code = scene_data.get("scene_code") or f"SC{index:02d}"
        scene = Scene(
            project_id=project.id,
            script_version_id=row.id,
            scene_code=code,
            sequence_index=index,
            title=scene_data.get("title") or code,
            structured_content_json=scene_data,
            duration=float(scene_data.get("duration") or 0),
            status="reviewing",
        )
        session.add(scene)
    session.flush()
    del existing

    _mark_superseded(session, project, "script", row.id)
    _record_deps(session, project.id, "story_plan", str(story_id or ""), "script", row)
    return row


def ingest_bible(session: Session, project: Project, job: GenerationJob, result: GenerationResult) -> ProductionBibleVersion:
    script_id = (job.request_snapshot or {}).get("inputs", {}).get("script_version_id")
    current = session.scalar(
        select(func.max(ProductionBibleVersion.version_number)).where(
            ProductionBibleVersion.project_id == project.id
        )
    ) or 0
    row = ProductionBibleVersion(
        project_id=project.id,
        script_version_id=script_id,
        created_by_job_id=job.id,
        version_number=current + 1,
        global_style_json=result.data.get("global_style") or {},
        characters_json=result.data.get("characters") or [],
        scenes_json=result.data.get("scenes") or [],
        props_json=result.data.get("props") or [],
        continuity_json=result.data.get("continuity") or [],
        content_hash=content_hash(result.data),
        status="reviewing",
    )
    session.add(row)
    session.flush()
    _record_deps(session, project.id, "script", str(script_id or ""), "bible", row)
    return row


def ingest_shot_plans(
    session: Session,
    project: Project,
    job: GenerationJob,
    result: GenerationResult,
    *,
    bible: ProductionBibleVersion | None = None,
) -> list[Shot]:
    scope_codes = (job.request_snapshot or {}).get("scope_shot_codes") or []
    bible = bible or latest_bible(session, project, statuses=["approved", "reviewing"])
    style = (bible.global_style_json or {}) if bible else {}
    created_or_updated: list[Shot] = []

    existing_by_code = {shot.shot_code: shot for shot in session.scalars(
        select(Shot).where(Shot.project_id == project.id)
    )}

    for index, item in enumerate(result.data.get("shots") or [], start=1):
        code = str(item.get("shot_code") or f"S{index:02d}")
        if scope_codes and code not in scope_codes:
            continue
        shot = existing_by_code.get(code)
        characters = item.get("subject") or ""
        # H3 管线硬限制：单镜 ≤15s（docs/02 §五.2），任何来源超限都截断并留痕
        raw_duration = float(item.get("duration") or 8)
        duration = min(SHOT_DURATION_MAX, max(SHOT_DURATION_MIN, raw_duration))
        clamped = raw_duration > SHOT_DURATION_MAX + 1e-9 or raw_duration < SHOT_DURATION_MIN - 1e-9
        if shot is None:
            shot = shots_service.create_shot(
                session, project,
                shot_code=code,
                title=item.get("purpose") or code,
                duration=duration,
                scene=item.get("scene_ref") or "",
                characters=characters,
            )
        else:
            shot.duration = duration
            shot.scene = item.get("scene_ref") or shot.scene
            shot.characters = characters or shot.characters
            shot.title = item.get("purpose") or shot.title
        shot.scene_code = item.get("scene_code") or ""
        session.flush()

        # 系统侧风险检测兜底（保证任何来源的镜表都有标签）
        risks = item.get("risks") or []
        system_risks = detect_risks(
            " ".join([str(item.get("action") or ""), str(item.get("dialogue") or ""), " ".join(item.get("props") or [])]),
            has_dialogue=bool(item.get("dialogue")),
        )
        merged_risks = list(dict.fromkeys(risks + system_risks))
        if clamped:
            merged_risks = list(dict.fromkeys(merged_risks + ["long_action"]))
        route = item.get("route_suggestion") or route_for_risks(merged_risks)
        if not isinstance(route, dict):
            route = {"recommended": str(route)}
        if clamped:
            route = dict(route)
            notes = list(route.get("notes") or [])
            notes.append(
                f"系统已把时长 {raw_duration:.1f}s 截为 {duration:.1f}s（视频单镜上限 15s）；"
                "建议在剧本层拆分为多镜后重新生成本镜"
            )
            route["notes"] = notes

        current_pkg = session.scalar(
            select(func.max(PromptPackage.version_number)).where(PromptPackage.shot_id == shot.id)
        ) or 0
        package = PromptPackage(
            shot_id=shot.id,
            version_number=current_pkg + 1,
            image_prompt_json=item.get("image_prompt") or {},
            video_prompt_json=item.get("video_prompt") or {},
            audio_prompt_json=item.get("audio_prompt") or {},
            required_references_json=item.get("required_references") or [],
            risk_tags_json=merged_risks,
            route_suggestion_json=route,
            template_version=result.template_version or TEMPLATE_VERSION,
            content_hash=content_hash({k: item.get(k) for k in ("image_prompt", "video_prompt", "audio_prompt")}),
            status="reviewing",
        )
        session.add(package)
        session.flush()
        prompt_compiler.apply_to_shot(session, shot, package, style)
        created_or_updated.append(shot)

    session.flush()
    script_id = (job.request_snapshot or {}).get("inputs", {}).get("script_version_id")
    _record_deps(session, project.id, "script", str(script_id or ""), "shots", None, kind="shot_plans")
    return created_or_updated


def _mark_superseded(session: Session, project: Project, version_type: str, keep_id: str) -> None:
    rows = session.scalars(
        select(StoryScriptVersion).where(
            StoryScriptVersion.project_id == project.id,
            StoryScriptVersion.version_type == version_type,
            StoryScriptVersion.status.in_(["reviewing", "revision"]),
            StoryScriptVersion.id != keep_id,
        )
    )
    for row in rows:
        row.status = "superseded"
    session.flush()


def _record_deps(session: Session, project_id: str, up_type: str, up_id: str, down_type: str, down_row, kind: str = "derived") -> None:
    from ..models import DependencyEdge

    upstream_hash = ""
    if up_id:
        if up_type == "brief":
            brief = session.get(CreativeBriefVersion, up_id)
            upstream_hash = brief.content_hash if brief else ""
        elif up_type in {"story_plan", "script"}:
            struct = session.get(StoryScriptVersion, up_id)
            upstream_hash = struct.content_hash if struct else ""
    session.add(DependencyEdge(
        project_id=project_id,
        upstream_type=up_type,
        upstream_id=up_id,
        upstream_hash=upstream_hash,
        downstream_type=down_type,
        downstream_id=down_row.id if down_row is not None else "",
        dependency_kind=kind,
    ))
    session.flush()


# ------------------------------------------------------------------ editing


def edit_script_scene(
    session: Session,
    project: Project,
    scene_updates: dict[str, dict],
    *,
    comment: str = "",
) -> StoryScriptVersion:
    """编辑剧本（卡点 A）：基于当前 reviewing/approved 版本复制出新版本（FR-GATE-004）。"""
    source = latest_struct(session, project, "script", statuses=["reviewing", "approved"])
    if source is None:
        raise CreativeError("没有可编辑的剧本版本")
    content = json.loads(json.dumps(source.structured_content_json or {}, ensure_ascii=False))
    changed = False
    for scene in content.get("scenes") or []:
        code = scene.get("scene_code") or ""
        updates = scene_updates.get(code)
        if not updates:
            continue
        for field in ("action", "narration", "goal"):
            if field in updates and updates[field] is not None:
                scene[field] = str(updates[field])
        if "duration" in updates and updates["duration"]:
            try:
                scene["duration"] = float(updates["duration"])
                changed = True
            except ValueError:
                pass
        dialogue_lines = updates.get("dialogue")
        if dialogue_lines is not None:
            parsed = []
            for line_text in str(dialogue_lines).splitlines():
                if "：" in line_text:
                    role, _, line = line_text.partition("：")
                    parsed.append({"role": role.strip(), "line": line.strip()})
            scene["dialogue"] = parsed
        changed = True
    if not changed:
        raise CreativeError("没有发生任何修改")
    row = StoryScriptVersion(
        project_id=project.id,
        parent_version_id=source.parent_version_id,
        created_by_job_id=None,
        version_type="script",
        schema_version=TEMPLATE_VERSION,
        structured_content_json=content,
        raw_model_output="",
        model_snapshot_json={"edited_by": "user", "parent": source.id},
        prompt_template_version=source.prompt_template_version,
        content_hash=content_hash(content),
        status="reviewing",
    )
    session.add(row)
    session.flush()

    for scene in project_scenes(session, project):
        if scene.script_version_id == source.id:
            scene.status = "superseded"
    for index, scene_data in enumerate(content.get("scenes") or [], start=1):
        session.add(Scene(
            project_id=project.id,
            script_version_id=row.id,
            scene_code=scene_data.get("scene_code") or f"SC{index:02d}",
            sequence_index=index,
            title=scene_data.get("title") or "",
            structured_content_json=scene_data,
            duration=float(scene_data.get("duration") or 0),
            status="reviewing",
        ))
    source.status = "superseded"
    session.flush()
    return row


def edit_bible_item(
    session: Session,
    project: Project,
    item_type: str,
    name: str,
    updates: dict,
) -> ProductionBibleVersion:
    """编辑生产设定：复制出新版本并使引用该项的镜头过期（§7-3，验收 24）。"""
    source = latest_bible(session, project, statuses=["reviewing", "approved"])
    if source is None:
        raise CreativeError("没有可编辑的生产设定版本")
    from copy import deepcopy

    new_row = ProductionBibleVersion(
        project_id=project.id,
        script_version_id=source.script_version_id,
        version_number=source.version_number + 1,
        global_style_json=deepcopy(source.global_style_json or {}),
        characters_json=deepcopy(source.characters_json or []),
        scenes_json=deepcopy(source.scenes_json or []),
        props_json=deepcopy(source.props_json or []),
        continuity_json=deepcopy(source.continuity_json or []),
        content_hash="",
        status="reviewing",
    )
    field_map = {"character": "characters_json", "scene": "scenes_json", "prop": "props_json", "style": "global_style_json"}
    attr = field_map.get(item_type)
    if attr is None:
        raise CreativeError(f"未知设定类型: {item_type}")
    if item_type == "style":
        merged = dict(getattr(new_row, attr) or {})
        merged.update({k: v for k, v in updates.items() if v not in (None, "")})
        setattr(new_row, attr, merged)
    else:
        items = list(getattr(new_row, attr) or [])
        target = next((it for it in items if it.get("name") == name), None)
        if target is None:
            raise CreativeError(f"设定中不存在: {name}")
        for key, value in updates.items():
            if value not in (None, ""):
                target[key] = value
        setattr(new_row, attr, items)
    new_row.content_hash = content_hash({
        "style": new_row.global_style_json, "chars": new_row.characters_json,
        "scenes": new_row.scenes_json, "props": new_row.props_json,
    })
    session.add(new_row)
    session.flush()
    source.status = "superseded"

    from . import dependencies as deps_service
    if item_type != "style":
        deps_service.mark_stale_for_bible_item(session, project, item_type, name, reason=f"生产设定「{name}」已修改")
    else:
        deps_service.mark_all_shots_stale(session, project, reason="全局风格已修改", scope="image")
    return new_row


# ---------------------------------------------------------------- estimate


# 固定估算基准（§15.6：默认采用固定估算值，后续可换历史平均/节点上报）
ESTIMATE_SECONDS = {
    "image": 25.0,
    "video": 240.0,
    "voice": 15.0,
    "ambience": 10.0,
}


def estimate_from_brief(brief: CreativeBriefVersion | None) -> dict:
    constraints = {**(brief.inferred_fields_json if brief else {}), **(brief.constraints_json if brief else {})}
    try:
        shots = int(constraints.get("target_shots") or 10)
    except (TypeError, ValueError):
        shots = 10
    scenes = max(2, min(8, round(shots / 2.2)))
    dialogue_ratio = 0.5
    image_tasks, video_tasks = shots, shots
    voice_tasks = max(1, round(shots * dialogue_ratio))
    gpu_seconds = (
        image_tasks * ESTIMATE_SECONDS["image"]
        + video_tasks * ESTIMATE_SECONDS["video"]
        + voice_tasks * ESTIMATE_SECONDS["voice"]
        + shots * ESTIMATE_SECONDS["ambience"]
    )
    return {
        "scenes": scenes,
        "shots": shots,
        "image_tasks": image_tasks,
        "video_tasks": video_tasks,
        "voice_tasks": voice_tasks,
        "gpu_seconds": round(gpu_seconds),
        "gpu_minutes": round(gpu_seconds / 60),
        "basis": "固定估算值",
    }


def estimate_from_script(session: Session, project: Project) -> dict:
    script = latest_struct(session, project, "script", statuses=["reviewing", "approved"])
    scenes = script.structured_content_json.get("scenes") or [] if script else []
    shots = 0
    dialogue_shots = 0
    for scene in scenes:
        count = 2 if len(scene.get("dialogue") or []) <= 1 else 3
        shots += count
        dialogue_shots += len(scene.get("dialogue") or [])
    gpu_seconds = (
        shots * ESTIMATE_SECONDS["image"]
        + shots * ESTIMATE_SECONDS["video"]
        + dialogue_shots * ESTIMATE_SECONDS["voice"]
        + shots * ESTIMATE_SECONDS["ambience"]
    )
    return {
        "scenes": len(scenes),
        "shots": shots,
        "image_tasks": shots,
        "video_tasks": shots,
        "voice_tasks": dialogue_shots,
        "gpu_seconds": round(gpu_seconds),
        "gpu_minutes": round(gpu_seconds / 60),
        "basis": "按剧本场景推算",
    }
