from __future__ import annotations

import json
import shutil
from pathlib import Path

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..config import Settings
from ..media import PathOutsideWorkspace, ensure_project_dirs, resolve_workspace_path, to_workspace_relpath
from ..models import (
    JOB_STATUS_FAILED,
    JOB_STATUS_QUEUED,
    JOB_STATUS_RUNNING,
    ApprovalGate,
    Asset,
    Character,
    CreativeBriefVersion,
    DependencyEdge,
    GenerationJob,
    ProductionBibleVersion,
    Project,
    PromptPackage,
    Review,
    Scene,
    Shot,
    ShotVersion,
    StoryScriptVersion,
)


class ProjectDeleteError(ValueError):
    pass


def get_project(session: Session, project_id: str) -> Project | None:
    return session.get(Project, project_id)


def list_projects(session: Session, include_archived: bool = False) -> list[Project]:
    stmt = select(Project).order_by(Project.updated_at.desc())
    projects = list(session.scalars(stmt))
    if include_archived:
        return projects
    return [project for project in projects if project.status == "active"]


def create_project(
    session: Session,
    settings: Settings,
    *,
    name: str,
    description: str = "",
    aspect_ratio: str = "9:16",
    resolution: str = "1216x704",
    fps: int = 24,
) -> Project:
    project = Project(
        name=name.strip() or "未命名项目",
        description=description or "",
        aspect_ratio=aspect_ratio or "9:16",
        resolution=resolution or "1216x704",
        fps=int(fps or 24),
        root_path="",
    )
    session.add(project)
    session.flush()
    project.root_path = f"projects/{project.id}"
    session.flush()
    ensure_project_dirs(settings, project)
    write_project_manifest(session, settings, project)
    return project


def update_project(session: Session, settings: Settings, project: Project, data: dict) -> Project:
    for key in ("name", "description", "aspect_ratio", "resolution", "fps"):
        if key in data and data[key] not in (None, ""):
            if key == "fps":
                project.fps = int(data[key])
            else:
                setattr(project, key, str(data[key]).strip())
    write_project_manifest(session, settings, project)
    return project


def archive_project(session: Session, settings: Settings, project: Project, archived: bool) -> Project:
    from ..models import utcnow

    project.status = "archived" if archived else "active"
    project.archived_at = utcnow() if archived else None
    write_project_manifest(session, settings, project)
    return project


def delete_project(session: Session, settings: Settings, project: Project, *, delete_files: bool = False) -> None:
    """永久删除项目（FR-PROJ-005 补充的危险操作）。

    - 有排队/运行任务时拒绝删除；
    - 清除数据库记录（项目、分镜、版本、任务、审核、角色、素材记录）；
    - 导入引用的源文件（如 outputs/）一律保留；仅可选删除本项目生成的 projects/{id}/ 目录。
    """
    active = session.scalars(
        select(GenerationJob).where(
            GenerationJob.project_id == project.id,
            GenerationJob.status.in_([JOB_STATUS_QUEUED, JOB_STATUS_RUNNING]),
        )
    ).first()
    if active is not None:
        raise ProjectDeleteError("项目还有排队或运行中的任务，请先在任务中心取消后再删除")

    root: Path | None = None
    if delete_files:
        try:
            root = resolve_workspace_path(
                settings.workspace_root, project.root_path or f"projects/{project.id}"
            )
        except PathOutsideWorkspace:
            root = None

    session.query(GenerationJob).filter(GenerationJob.project_id == project.id).delete(
        synchronize_session=False
    )
    session.query(Review).filter(Review.project_id == project.id).delete(synchronize_session=False)
    session.query(Asset).filter(
        Asset.project_id == project.id, Asset.version_id.is_(None)
    ).delete(synchronize_session=False)
    session.query(Character).filter(Character.project_id == project.id).delete(
        synchronize_session=False
    )
    # v0.3 创作实体（无 ORM 级联，需在删除项目/分镜前显式清理，否则外键约束失败）
    session.query(PromptPackage).filter(
        PromptPackage.shot_id.in_(select(Shot.id).where(Shot.project_id == project.id))
    ).delete(synchronize_session=False)
    for model in (Scene, StoryScriptVersion, ProductionBibleVersion, CreativeBriefVersion, ApprovalGate, DependencyEdge):
        session.query(model).filter(model.project_id == project.id).delete(
            synchronize_session=False
        )
    session.delete(project)  # 级联：shots -> versions -> 版本产物 assets
    session.flush()

    if root is not None and root.exists():
        shutil.rmtree(root, ignore_errors=True)


def write_project_manifest(session: Session, settings: Settings, project: Project) -> None:
    root = ensure_project_dirs(settings, project)
    manifest = {
        "id": project.id,
        "name": project.name,
        "description": project.description,
        "status": project.status,
        "aspect_ratio": project.aspect_ratio,
        "resolution": project.resolution,
        "fps": project.fps,
        "updated_at": project.updated_at.isoformat() if project.updated_at else None,
    }
    (root / "project.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


def project_stats(session: Session, project: Project) -> dict:
    total = session.scalar(
        select(func.count()).select_from(Shot).where(Shot.project_id == project.id)
    ) or 0
    accepted = session.scalar(
        select(func.count()).select_from(Shot).where(
            Shot.project_id == project.id, Shot.status == "accepted"
        )
    ) or 0

    status_expr = select(GenerationJob.status, func.count()).where(
        GenerationJob.project_id == project.id
    ).group_by(GenerationJob.status)
    job_counts = {status: count for status, count in session.execute(status_expr)}

    last_final = session.scalars(
        select(Asset)
        .where(Asset.project_id == project.id, Asset.asset_type == "final")
        .order_by(Asset.created_at.desc())
        .limit(1)
    ).first()

    return {
        "total_shots": total,
        "accepted_shots": accepted,
        "running_jobs": job_counts.get(JOB_STATUS_RUNNING, 0),
        "queued_jobs": job_counts.get(JOB_STATUS_QUEUED, 0),
        "failed_jobs": job_counts.get(JOB_STATUS_FAILED, 0),
        "last_final": last_final,
    }


def production_stage(stats: dict) -> str:
    if stats["total_shots"] == 0:
        return "空项目"
    if stats["running_jobs"] or stats["queued_jobs"]:
        return "生成中"
    if stats["failed_jobs"]:
        return "有失败任务"
    if stats["accepted_shots"] >= stats["total_shots"]:
        return "可合成成片"
    if stats["accepted_shots"] > 0:
        return "审核中"
    return "待审核"


def count_versions(session: Session, project_id: str) -> int:
    return session.scalar(
        select(func.count())
        .select_from(ShotVersion)
        .join(Shot, ShotVersion.shot_id == Shot.id)
        .where(Shot.project_id == project_id)
    ) or 0
