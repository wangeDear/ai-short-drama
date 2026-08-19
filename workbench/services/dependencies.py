"""依赖图与精准失效（v0.3 §7 / §8.16）。

上游变化后下游标记 stale（带原因）而不是删除；旧版本与旧分支全部保留，
可随时查看或恢复（验收 24/25）。
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import DependencyEdge, Project, PromptPackage, Shot, utcnow


def record(
    session: Session,
    project_id: str,
    *,
    upstream_type: str,
    upstream_id: str,
    upstream_hash: str,
    downstream_type: str,
    downstream_id: str,
    dependency_kind: str = "derived",
) -> DependencyEdge:
    edge = DependencyEdge(
        project_id=project_id,
        upstream_type=upstream_type,
        upstream_id=upstream_id,
        upstream_hash=upstream_hash,
        downstream_type=downstream_type,
        downstream_id=downstream_id,
        dependency_kind=dependency_kind,
    )
    session.add(edge)
    session.flush()
    return edge


def mark_stale(
    session: Session,
    edge: DependencyEdge | None,
    reason: str,
) -> None:
    if edge is not None:
        edge.stale_reason = reason
        edge.updated_at = utcnow()
    session.flush()


def _set_shot_stale(shot: Shot, reason: str, scope: str = "all") -> None:
    params = dict(shot.params_json or {})
    stale = dict(params.get("stale") or {})
    stale["reason"] = reason
    stale["scope"] = scope
    stale["at"] = utcnow().isoformat()
    params["stale"] = stale
    shot.params_json = params
    if scope in {"all", "video"}:
        shot.video_config_stale = True


def mark_stale_shot(session: Session, shot: Shot, reason: str, scope: str = "all") -> Shot:
    _set_shot_stale(shot, reason, scope)
    session.add(DependencyEdge(
        project_id=shot.project_id,
        upstream_type="shot_config",
        upstream_id=shot.id,
        upstream_hash="",
        downstream_type="shot",
        downstream_id=shot.id,
        dependency_kind="self",
        stale_reason=reason,
    ))
    session.flush()
    return shot


def mark_all_shots_stale(session: Session, project: Project, reason: str, scope: str = "all") -> int:
    shots = list(session.scalars(select(Shot).where(Shot.project_id == project.id)))
    for shot in shots:
        _set_shot_stale(shot, reason, scope)
    session.flush()
    return len(shots)


def _shot_scene_code(shot: Shot) -> str:
    return (shot.params_json or {}).get("scene_code") or getattr(shot, "scene_code", "") or ""


def mark_stale_for_bible_item(
    session: Session,
    project: Project,
    item_type: str,
    name: str,
    *,
    reason: str,
) -> list[Shot]:
    """§7-3：修改角色/场景/道具设定，只使引用该项的镜头过期（验收 24）。"""
    shots = list(session.scalars(select(Shot).where(Shot.project_id == project.id)))
    affected: list[Shot] = []
    for shot in shots:
        references = False
        if item_type == "character":
            names = [part.strip() for part in (shot.characters or "").replace("，", ",").split(",") if part.strip]
            if name in names or name in (shot.characters or ""):
                references = True
        elif item_type == "scene":
            if name in (shot.scene or "") or name in _shot_scene_code(shot):
                references = True
        elif item_type == "prop":
            pkg = session.scalars(
                select(PromptPackage)
                .where(PromptPackage.shot_id == shot.id)
                .order_by(PromptPackage.version_number.desc())
                .limit(1)
            ).first()
            if pkg is not None:
                refs = list(pkg.required_references_json or [])
                for field in (pkg.image_prompt_json or {}).values():
                    if isinstance(field, str) and name in field:
                        references = True
                if any(name in str(r) for r in refs):
                    references = True
        if references:
            _set_shot_stale(shot, reason, "image")
            affected.append(shot)
    if affected:
        session.add(DependencyEdge(
            project_id=project.id,
            upstream_type=f"bible_{item_type}",
            upstream_id=name,
            upstream_hash="",
            downstream_type="shot",
            downstream_id=",".join(s.id for s in affected[:20]),
            dependency_kind="reference",
            stale_reason=reason,
        ))
    session.flush()
    return affected


def mark_stale_for_scene(session: Session, project: Project, scene_code: str, *, reason: str) -> list[Shot]:
    """§7-2：修改某个剧本场景，只使该场景的镜表/提示词/媒体过期（验收 21）。"""
    shots = list(session.scalars(select(Shot).where(Shot.project_id == project.id)))
    affected = [shot for shot in shots if _shot_scene_code(shot) == scene_code]
    for shot in affected:
        _set_shot_stale(shot, reason, "all")
    session.flush()
    return affected


def clear_stale(session: Session, shot: Shot) -> None:
    params = dict(shot.params_json or {})
    params.pop("stale", None)
    shot.params_json = params
    shot.video_config_stale = False
    session.flush()


def stale_summary(session: Session, project: Project) -> list[dict]:
    shots = list(session.scalars(select(Shot).where(Shot.project_id == project.id)))
    result = []
    for shot in shots:
        stale = (shot.params_json or {}).get("stale")
        if stale:
            result.append({
                "shot_id": shot.id,
                "shot_code": shot.shot_code,
                "reason": stale.get("reason", ""),
                "scope": stale.get("scope", "all"),
            })
        elif shot.video_config_stale:
            result.append({
                "shot_id": shot.id,
                "shot_code": shot.shot_code,
                "reason": "视频配置已修改，建议重做",
                "scope": "video",
            })
    return result
