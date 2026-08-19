"""生产流水线人工卡点（v0.3 §6.11 / FR-GATE-001~004）。

- A/B 卡点经 ApprovalGate 表持久化决定；刷新/重启后状态可恢复（验收 23）；
- C 卡点 = 图片批准前置（复用既有 image 版本状态与 reviews 表）；
- D 卡点 = 逐镜最终采用（复用 select_final 与 reviews 表）；
- 「C 通过后自动排队」按项目配置，只作用于已批准镜头（FR-GATE-002）。
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import Settings
from ..models import (
    GATE_A,
    GATE_B,
    GATE_C,
    GATE_D,
    GATE_LABELS,
    JOB_STATUS_QUEUED,
    JOB_TYPE_VIDEO,
    ApprovalGate,
    Project,
    PromptPackage,
    Shot,
    ShotVersion,
    utcnow,
)
from . import creative as creative_service
from . import jobs as jobs_service
from . import versions as versions_service
from .jobs import JobError


class GateError(ValueError):
    pass


# ------------------------------------------------------------------ config


def gate_enabled(project: Project, gate: str) -> bool:
    """A/B 卡点可关闭；C/D 不可关闭（图片批准是视频生成硬前置）。"""
    if gate in {GATE_C, GATE_D}:
        return True
    gates = (project.pipeline_json or {}).get("gates") or {}
    return bool(gates.get(gate, True))


def auto_queue_after_c(project: Project) -> bool:
    return bool((project.pipeline_json or {}).get("auto_queue_after_c"))


def update_pipeline_config(session: Session, project: Project, updates: dict) -> Project:
    config = dict(project.pipeline_json or {})
    gates = dict(config.get("gates") or {})
    for gate in (GATE_A, GATE_B):
        key = f"gate_{gate.lower()}"
        if key in updates:
            gates[gate] = updates[key] in (True, "on", "1", 1)
    if "auto_queue_after_c" in updates:
        config["auto_queue_after_c"] = updates["auto_queue_after_c"] in (True, "on", "1", 1)
    config["gates"] = gates
    project.pipeline_json = config
    session.flush()
    return project


# ------------------------------------------------------------------ status


def gate_passed(session: Session, project: Project, gate: str) -> bool:
    """A/B：最新结构化版本已批准。"""
    if not gate_enabled(project, gate):
        return True
    if gate == GATE_A:
        script = creative_service.latest_struct(session, project, "script", statuses=["approved"])
        return script is not None
    if gate == GATE_B:
        return gate_b_partial_passed(session, project)
    return False


def gate_b_partial_passed(session: Session, project: Project) -> bool:
    """B 卡点通过条件：圣经已批准且存在已批准提示词包（scope 全量时）。"""
    if not gate_enabled(project, GATE_B):
        return True
    bible = creative_service.latest_bible(session, project, statuses=["approved"])
    if bible is None:
        return False
    shot_ids = list(session.scalars(select(Shot.id).where(Shot.project_id == project.id)))
    if not shot_ids:
        return False
    approved = session.scalars(
        select(PromptPackage).where(
            PromptPackage.shot_id.in_(shot_ids), PromptPackage.status == "approved"
        )
    )
    approved_shots = {pkg.shot_id for pkg in approved}
    return set(shot_ids) <= approved_shots


def gate_states(session: Session, project: Project) -> list[dict]:
    """项目概览卡点面板数据（FR-GATE-002）：待办/过期/阻塞原因。"""
    shots = list(
        session.scalars(select(Shot).where(Shot.project_id == project.id).order_by(Shot.sequence_index))
    )
    states: list[dict] = []

    # A：剧本
    story = creative_service.latest_struct(session, project, "story_plan")
    script = creative_service.latest_struct(session, project, "script")
    brief = creative_service.latest_brief(session, project)
    if gate_enabled(project, GATE_A):
        if brief is None and not shots:
            status, reason = "empty", "尚未输入创意/剧本"
        elif script is not None and script.status == "approved":
            status, reason = "passed", "剧本已批准"
        elif script is not None and script.status == "reviewing":
            status, reason = "waiting", "剧本待审核（可编辑后批准）"
        elif script is not None and script.status == "revision":
            status, reason = "returned", "剧本已退回，修改后重新提交"
        elif script is not None and script.status == "failed":
            status, reason = "failed", "剧本生成失败，请查看原始输出"
        else:
            status, reason = "pending", "故事方案待生成" if story is None else "结构化剧本待生成"
        enabled = True
    else:
        status, reason, enabled = "off", "A 卡点已关闭", False
    states.append({"gate": GATE_A, "label": GATE_LABELS[GATE_A], "status": status, "reason": reason, "enabled": enabled,
                   "pending": 1 if status == "waiting" else 0, "stale": 0})

    # B：生产包（圣经 + 镜表提示词）
    bible = creative_service.latest_bible(session, project)
    pending_pkgs = _pending_packages(session, shots)
    stale_shots = [s for s in shots if _shot_stale(s)]
    if not gate_enabled(project, GATE_B):
        states.append({"gate": GATE_B, "label": GATE_LABELS[GATE_B], "status": "off", "reason": "B 卡点已关闭",
                       "enabled": False, "pending": 0, "stale": len(stale_shots)})
    elif bible is None:
        states.append({"gate": GATE_B, "label": GATE_LABELS[GATE_B], "status": "pending", "reason": "生产设定待生成（需 A 通过）",
                       "enabled": True, "pending": 0, "stale": len(stale_shots)})
    elif gate_b_partial_passed(session, project):
        states.append({"gate": GATE_B, "label": GATE_LABELS[GATE_B], "status": "passed", "reason": "生产包已批准",
                       "enabled": True, "pending": len(pending_pkgs), "stale": len(stale_shots)})
    elif bible.status == "revision":
        states.append({"gate": GATE_B, "label": GATE_LABELS[GATE_B], "status": "returned", "reason": "生产包已退回",
                       "enabled": True, "pending": len(pending_pkgs), "stale": len(stale_shots)})
    elif bible.status == "failed":
        states.append({"gate": GATE_B, "label": GATE_LABELS[GATE_B], "status": "failed", "reason": "生产设定提取失败",
                       "enabled": True, "pending": len(pending_pkgs), "stale": len(stale_shots)})
    else:
        states.append({"gate": GATE_B, "label": GATE_LABELS[GATE_B], "status": "waiting",
                       "reason": f"生产设定待审核；{len(pending_pkgs)} 个提示词包待审",
                       "enabled": True, "pending": max(1, len(pending_pkgs)), "stale": len(stale_shots)})

    # C：图片
    image_pending = [s for s in shots if _image_pending(s)]
    states.append({"gate": GATE_C, "label": GATE_LABELS[GATE_C],
                   "status": "passed" if shots and not image_pending else ("waiting" if image_pending else "empty"),
                   "reason": f"{len(image_pending)} 个分镜图片待批准" if image_pending else "全部图片已批准",
                   "enabled": True, "pending": len(image_pending), "stale": 0})

    # D：视频
    video_pending = [s for s in shots if _video_pending(s)]
    states.append({"gate": GATE_D, "label": GATE_LABELS[GATE_D],
                   "status": "passed" if shots and not video_pending else ("waiting" if video_pending else "empty"),
                   "reason": f"{len(video_pending)} 个分镜待采用最终视频" if video_pending else "全部分镜已采用最终版",
                   "enabled": True, "pending": len(video_pending), "stale": 0})
    return states


def _image_pending(shot: Shot) -> bool:
    versions = [v for v in shot.versions if v.version_type == "image"]
    if not versions:
        return True
    latest = versions[-1]
    return latest.status not in {"accepted"}


def _video_pending(shot: Shot) -> bool:
    return not shot.selected_version_id


def _shot_stale(shot: Shot) -> bool:
    return bool((shot.params_json or {}).get("stale")) or bool(shot.video_config_stale)


def _pending_packages(session: Session, shots: list[Shot]) -> list[PromptPackage]:
    result = []
    for shot in shots:
        pkgs = session.scalars(
            select(PromptPackage).where(PromptPackage.shot_id == shot.id).order_by(PromptPackage.version_number.desc())
        )
        latest = next(iter(pkgs), None)
        if latest is not None and latest.status == "reviewing":
            result.append(latest)
    return result


# ------------------------------------------------------------------ decide


def _latest_input_refs(session: Session, project: Project, gate: str) -> dict:
    refs: dict = {}
    if gate == GATE_A:
        story = creative_service.latest_struct(session, project, "story_plan")
        script = creative_service.latest_struct(session, project, "script")
        refs = {"story_version_id": story.id if story else None, "script_version_id": script.id if script else None,
                "story_hash": story.content_hash if story else "", "script_hash": script.content_hash if script else ""}
    elif gate == GATE_B:
        bible = creative_service.latest_bible(session, project)
        refs = {"bible_version_id": bible.id if bible else None, "bible_hash": bible.content_hash if bible else ""}
    return refs


def decide(
    session: Session,
    settings: Settings,
    project: Project,
    gate: str,
    decision: str,
    *,
    comment: str = "",
    scope_type: str = "project",
    scope_id: str | None = None,
) -> ApprovalGate:
    """卡点决定：approve / return（FR-GATE-004：退回需结构化原因）。"""
    if gate not in {GATE_A, GATE_B}:
        raise GateError("C/D 卡点通过分镜审核动作推进（批准图片 / 采用最终版本）")
    if decision not in {"approve", "return"}:
        raise GateError(f"未知决定: {decision}")
    if decision == "return" and not (comment or "").strip():
        raise GateError("退回必须填写原因（供下一次生成使用）")

    refs = _latest_input_refs(session, project, gate)
    record = ApprovalGate(
        project_id=project.id,
        gate_type=gate,
        scope_type=scope_type,
        scope_id=scope_id,
        input_version_refs_json=refs,
        decision="approved" if decision == "approve" else "revision",
        comment=(comment or "").strip(),
        decided_at=utcnow(),
    )
    session.add(record)
    session.flush()

    if gate == GATE_A:
        _apply_gate_a(session, project, decision)
    else:
        _apply_gate_b(session, project, decision, scope_type, scope_id, comment)
    session.flush()
    return record


def _apply_gate_a(session: Session, project: Project, decision: str) -> None:
    script = creative_service.latest_struct(session, project, "script")
    story = creative_service.latest_struct(session, project, "story_plan")
    if script is None:
        raise GateError("尚无可审核的剧本版本")
    target_status = "approved" if decision == "approve" else "revision"
    script.status = target_status
    if story is not None and story.status in {"reviewing", "approved", "revision"}:
        story.status = target_status
    for scene in creative_service.project_scenes(session, project):
        if scene.script_version_id == script.id:
            scene.status = target_status


def _apply_gate_b(
    session: Session,
    project: Project,
    decision: str,
    scope_type: str,
    scope_id: str | None,
    comment: str,
) -> None:
    bible = creative_service.latest_bible(session, project)
    if bible is None:
        raise GateError("尚无可审核的生产设定版本")

    shots = list(
        session.scalars(select(Shot).where(Shot.project_id == project.id).order_by(Shot.sequence_index))
    )
    if scope_type == "shot" and scope_id:
        scope_shots = [s for s in shots if s.id == scope_id]
    elif scope_type == "scene" and scope_id:
        scope_shots = [s for s in shots if (s.params_json or {}).get("scene_code") == scope_id or getattr(s, "scene_code", "") == scope_id]
    else:
        scope_shots = shots

    target = "approved" if decision == "approve" else "revision"
    if scope_type == "project":
        bible.status = target
    for shot in scope_shots:
        pkg = session.scalars(
            select(PromptPackage).where(PromptPackage.shot_id == shot.id)
            .order_by(PromptPackage.version_number.desc()).limit(1)
        ).first()
        if pkg is not None and pkg.status == "reviewing":
            pkg.status = target
        if decision == "return":
            shot.status = "needs_revision"
            notes = (shot.notes or "").rstrip()
            shot.notes = notes + (f"\n[B退回] {comment}" if notes else f"[B退回] {comment}")
        elif decision == "approve" and shot.status == "draft":
            shot.status = "image_review"


def gate_history(session: Session, project: Project, limit: int = 20) -> list[ApprovalGate]:
    return list(
        session.scalars(
            select(ApprovalGate)
            .where(ApprovalGate.project_id == project.id)
            .order_by(ApprovalGate.created_at.desc())
            .limit(limit)
        )
    )


# -------------------------------------------------------- auto queue after C


def maybe_auto_queue_video(session: Session, settings: Settings, shot: Shot) -> GenerationJob | None:
    """图片批准后按配置自动提交视频（只作用于该已批准镜头）。

    尽力而为：排队失败（如未登记节点）不影响批准动作本身。
    """
    from ..models import Project

    project = session.get(Project, shot.project_id)
    if project is None or not auto_queue_after_c(project):
        return None
    if not shot.selected_version_id and shot.status == "image_approved":
        if (shot.video_prompt or shot.image_prompt or "").strip():
            try:
                job = jobs_service.enqueue_generation(session, settings, shot, JOB_TYPE_VIDEO)
            except JobError:
                return None
            jobs_service.append_job_log(
                settings, job, f"[{utcnow().isoformat()}] C 卡点通过自动排队（镜头 {shot.shot_code}）"
            )
            return job
    return None
