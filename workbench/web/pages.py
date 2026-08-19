from __future__ import annotations

import csv
import difflib
import io
import json
from urllib.parse import quote

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import FileResponse, PlainTextResponse, StreamingResponse
from sqlalchemy.orm import Session

from ..config import WORKBENCH_ROOT, Settings, config_path
from ..media import PathOutsideWorkspace, make_thumbnail, resolve_workspace_path
from ..models import (
    Asset,
    GenerationJob,
    Project,
    PromptPackage,
    Shot,
    ShotVersion,
    WorkflowTemplate,
)
from ..services import characters as characters_service
from ..services import endpoints as endpoints_service
from ..services import final as final_service
from ..services import jobs as jobs_service
from ..services import projects as projects_service
from ..services import reviews as reviews_service
from ..services import shots as shots_service
from ..services import versions as versions_service
from ..services import workflows as workflows_service
from .deps import get_db, get_settings, load_project, load_shot
from .main import render

router = APIRouter()


# --------------------------------------------------------------------- 首页


@router.get("/")
def projects_page(
    request: Request,
    include_archived: str = "",
    db: Session = Depends(get_db),
):
    include = include_archived == "1"
    projects = projects_service.list_projects(db, include_archived=include)
    stats = {project.id: projects_service.project_stats(db, project) for project in projects}
    stages = {project.id: projects_service.production_stage(stats[project.id]) for project in projects}
    return render(request, "projects.html", {
        "projects": projects,
        "stats": stats,
        "stages": stages,
        "include_archived": include,
    })


# ------------------------------------------------------------------- 项目页


@router.get("/projects/{project_id}")
def project_overview(request: Request, project_id: str, db: Session = Depends(get_db)):
    from ..services import gates as gates_service
    from ..services.pipeline import pipeline_stages

    project = load_project(db, project_id)
    stats = projects_service.project_stats(db, project)
    stage = projects_service.production_stage(stats)
    stages = pipeline_stages(db, project)
    recent_jobs = jobs_service.list_jobs(db, project_id=project.id, limit=10)
    status_counts: dict[str, int] = {}
    for shot in project.shots:
        status_counts[shot.status] = status_counts.get(shot.status, 0) + 1
    version_total = projects_service.count_versions(db, project.id)
    return render(request, "project_overview.html", {
        "project": project,
        "stats": stats,
        "stage": stage,
        "stages": stages,
        "recent_jobs": recent_jobs,
        "status_counts": status_counts,
        "version_total": version_total,
        "active_jobs": jobs_service.list_jobs(db, project_id=project.id, active_only=True, limit=10),
        "gate_states": gates_service.gate_states(db, project),
    })


@router.get("/projects/{project_id}/shots")
def shots_page(
    request: Request,
    project_id: str,
    status: str = "",
    scene: str = "",
    character: str = "",
    workflow: str = "",
    flag: str = "",
    q: str = "",
    view: str = "card",
    partial: str = "",
    db: Session = Depends(get_db),
):
    project = load_project(db, project_id)
    filters = {
        "status": status, "scene": scene, "character": character,
        "workflow": workflow, "flag": flag, "q": q,
    }
    shots = shots_service.filter_shots(db, project, filters)
    views = shots_service.build_shot_views(db, shots)
    workflows = shots_service.workflow_options(db)
    stats = projects_service.project_stats(db, project)

    grid_qs = _with_param(request, "partial", "grid")
    context = {
        "project": project,
        "shots": shots,
        "views": views,
        "filters": {key: value for key, value in filters.items() if value},
        "view": "list" if view == "list" else "card",
        "workflows": workflows,
        "stats": stats,
        "grid_url": request.url.path + grid_qs,
    }
    if partial == "grid":
        return render(request, "partials/shots_grid.html", context)
    return render(request, "shots.html", context)


def _with_param(request: Request, key: str, value: str) -> str:
    from .helpers import qs

    return qs(request, **{key: value})


def model_options(session) -> list[str]:
    """可选模型列表：节点拉取的模型 ∪ 各工作流模板登记的依赖模型。"""
    options: set[str] = set()
    for endpoint in endpoints_service.list_endpoints(session):
        if endpoint.enabled:
            options.update((endpoint.capabilities_json or {}).get("models") or [])
    for template in session.query(WorkflowTemplate).all():
        options.update(template.required_models_json or [])
    return sorted(options)


@router.get("/projects/{project_id}/shots/{shot_id}")
def shot_detail(request: Request, project_id: str, shot_id: str, db: Session = Depends(get_db)):
    project = load_project(db, project_id)
    shot = load_shot(db, shot_id)
    if shot.project_id != project.id:
        raise HTTPException(status_code=404, detail="分镜不属于该项目")
    view = shots_service.build_shot_views(db, [shot])[shot.id]
    versions = list(shot.versions)
    version_assets = {version.id: versions_service.version_assets(db, version) for version in versions}
    jobs = list(
        db.query(GenerationJob)
        .filter(GenerationJob.shot_id == shot.id)
        .order_by(GenerationJob.created_at.desc())
        .limit(20)
    )
    review_list = reviews_service.shot_reviews(db, shot)
    workflows = shots_service.workflow_options(db)
    endpoints = endpoints_service.list_endpoints(db)
    return render(request, "shot_detail.html", {
        "project": project,
        "shot": shot,
        "view": view,
        "versions": versions,
        "version_assets": version_assets,
        "jobs": jobs,
        "reviews": review_list,
        "workflows": workflows,
        "endpoints": endpoints,
        "model_options": model_options(db),
        "package": (
            db.query(PromptPackage)
            .filter(PromptPackage.shot_id == shot.id)
            .order_by(PromptPackage.version_number.desc())
            .first()
        ),
    })


@router.get("/projects/{project_id}/shots/{shot_id}/compare")
def shot_compare(
    request: Request,
    project_id: str,
    shot_id: str,
    v1: str = "",
    v2: str = "",
    type: str = "video",
    db: Session = Depends(get_db),
):
    project = load_project(db, project_id)
    shot = load_shot(db, shot_id)
    versions = [version for version in shot.versions if version.version_type == type]
    if not versions:
        raise HTTPException(status_code=404, detail="该分镜没有可对比的版本")

    def find(version_id: str, offset: int) -> ShotVersion:
        for version in versions:
            if version.id == version_id:
                return version
        return versions[offset]

    left = find(v1, 0 if len(versions) == 1 else len(versions) - 2)
    right = find(v2, -1)
    assets = {version.id: versions_service.version_assets(db, version) for version in (left, right)}

    left_text = json.dumps(left.prompt_snapshot, ensure_ascii=False, indent=1, sort_keys=True)
    right_text = json.dumps(right.prompt_snapshot, ensure_ascii=False, indent=1, sort_keys=True)
    diff = "\n".join(
        difflib.unified_diff(
            left_text.splitlines(), right_text.splitlines(),
            fromfile=f"v{left.version_number}", tofile=f"v{right.version_number}", lineterm="",
        )
    )
    return render(request, "shot_compare.html", {
        "project": project,
        "shot": shot,
        "versions": versions,
        "left": left,
        "right": right,
        "left_assets": assets.get(left.id, []),
        "right_assets": assets.get(right.id, []),
        "diff": diff,
        "type": type,
    })


@router.get("/projects/{project_id}/characters")
def characters_page(request: Request, project_id: str, db: Session = Depends(get_db)):
    project = load_project(db, project_id)
    character_list = characters_service.list_characters(db, project)
    character_assets = {
        character.id: characters_service.character_assets(db, character) for character in character_list
    }
    public_assets = characters_service.list_project_assets(db, project)
    return render(request, "characters.html", {
        "project": project,
        "characters": character_list,
        "character_assets": character_assets,
        "public_assets": public_assets,
    })


@router.get("/projects/{project_id}/final")
def final_page(request: Request, project_id: str, db: Session = Depends(get_db)):
    project = load_project(db, project_id)
    readiness = final_service.readiness(db, project)
    entries = final_service.composition_entries(db, project)
    finals = final_service.final_assets(db, project)
    compose_jobs = [
        job for job in jobs_service.list_jobs(db, project_id=project.id, limit=30)
        if job.job_type in {"compose", "export"}
    ]
    return render(request, "final.html", {
        "project": project,
        "readiness": readiness,
        "entries": entries,
        "finals": finals,
        "compose_jobs": compose_jobs,
        "active_job": next((job for job in compose_jobs if job.status in {"queued", "running"}), None),
    })


@router.get("/projects/{project_id}/review.csv")
def export_review_csv(project_id: str, db: Session = Depends(get_db)):
    project = load_project(db, project_id)
    rows = shots_service.review_rows(db, project)
    buffer = io.StringIO()
    buffer.write("\ufeff")
    writer = csv.DictWriter(buffer, fieldnames=list(rows[0].keys()) if rows else ["shot_code"])
    writer.writeheader()
    writer.writerows(rows)
    buffer.seek(0)
    filename = quote(f"{project.name}_审核清单.csv")
    return StreamingResponse(
        iter([buffer.getvalue()]),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f"attachment; filename*=UTF-8''{filename}"},
    )


# ------------------------------------------------------------------- v0.3 创作链路


@router.get("/projects/{project_id}/partial/active-jobs")
def partial_active_jobs(request: Request, project_id: str, db: Session = Depends(get_db)):
    """活跃任务状态条片段（HTMX 轮询）。"""
    project = load_project(db, project_id)
    active = jobs_service.list_jobs(db, project_id=project.id, active_only=True, limit=10)
    return render(request, "partials/active_jobs_bar.html", {
        "project": project,
        "active_jobs": active,
    })


@router.get("/projects/{project_id}/creative")
def creative_page(request: Request, project_id: str, db: Session = Depends(get_db)):
    """创意与剧本页（FR-CREATIVE-001/002，卡点 A）。"""
    from ..services import creative as creative_service
    from ..services import gates as gates_service

    project = load_project(db, project_id)
    from ..models import StoryScriptVersion

    brief = creative_service.latest_brief(db, project)
    story = creative_service.latest_struct(db, project, "story_plan")
    script = creative_service.latest_struct(db, project, "script")
    scenes = creative_service.project_scenes(db, project)
    script_scenes = [s for s in scenes if script is not None and s.script_version_id == script.id]
    estimate = creative_service.estimate_from_brief(brief)
    if script is not None:
        script_estimate = creative_service.estimate_from_script(db, project)
    else:
        script_estimate = None
    failed_structs = [
        row for row in db.query(StoryScriptVersion).filter(
            StoryScriptVersion.project_id == project.id,
            StoryScriptVersion.status == "failed",
        ).all()
    ]
    return render(request, "creative.html", {
        "project": project,
        "brief": brief,
        "story": story,
        "script": script,
        "script_scenes": script_scenes,
        "estimate": estimate,
        "script_estimate": script_estimate,
        "failed_structs": failed_structs,
        "active_jobs": jobs_service.list_jobs(db, project_id=project.id, active_only=True, limit=10),
        "gate_states": gates_service.gate_states(db, project),
        "gate_history": gates_service.gate_history(db, project),
    })


@router.get("/projects/{project_id}/bible")
def bible_page(request: Request, project_id: str, db: Session = Depends(get_db)):
    """生产设定与分镜计划页（FR-CREATIVE-003/004/005，卡点 B）。"""
    import json as json_module

    from ..models import PromptPackage
    from ..services import creative as creative_service
    from ..services import dependencies as deps_service
    from ..services import gates as gates_service
    from ..creative.risks import RISK_LABELS

    project = load_project(db, project_id)
    bible = creative_service.latest_bible(db, project)
    shots = list(db.query(Shot).filter(Shot.project_id == project.id).order_by(Shot.sequence_index).all())
    packages = {}
    for shot in shots:
        latest = (
            db.query(PromptPackage)
            .filter(PromptPackage.shot_id == shot.id)
            .order_by(PromptPackage.version_number.desc())
            .first()
        )
        if latest is not None:
            packages[shot.id] = latest
    for shot in shots:
        pkg = packages.get(shot.id)
        if pkg is not None:
            shot.latest_package = pkg
            shot.risk_labels = [RISK_LABELS.get(tag, tag) for tag in (pkg.risk_tags_json or [])]
        else:
            shot.latest_package = None
            shot.risk_labels = []
    return render(request, "bible.html", {
        "project": project,
        "bible": bible,
        "bible_json": json_module.dumps({
            "characters": bible.characters_json or [],
            "scenes": bible.scenes_json or [],
            "props": bible.props_json or [],
            "global_style": bible.global_style_json or {},
        }, ensure_ascii=False, indent=1) if bible else "",
        "shots": shots,
        "stale_shots": deps_service.stale_summary(db, project),
        "active_jobs": jobs_service.list_jobs(db, project_id=project.id, active_only=True, limit=10),
        "gate_states": gates_service.gate_states(db, project),
        "auto_queue": gates_service.auto_queue_after_c(project),
    })


@router.get("/jobs")
def jobs_page(
    request: Request,
    status: str = "",
    project: str = "",
    partial: str = "",
    db: Session = Depends(get_db),
):
    jobs = jobs_service.list_jobs(db, project_id=project or None, status=status or None, limit=200)
    project_names = {
        item.id: item.name for item in db.query(Project).all()
    }
    shot_codes = {
        item.id: item.shot_code for item in db.query(Shot).all()
    }
    context = {
        "jobs": jobs,
        "project_names": project_names,
        "shot_codes": shot_codes,
        "status_filter": status,
        "project_filter": project,
        "projects": projects_service.list_projects(db, include_archived=True),
        "table_url": request.url.path + _with_param(request, "partial", "table"),
    }
    if partial == "table":
        return render(request, "partials/jobs_table.html", context)
    return render(request, "jobs.html", context)


@router.get("/jobs/{job_id}")
def job_detail(request: Request, job_id: str, db: Session = Depends(get_db)):
    job = jobs_service.get_job(db, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="任务不存在")
    project = db.get(Project, job.project_id) if job.project_id else None
    shot = db.get(Shot, job.shot_id) if job.shot_id else None
    version = db.get(ShotVersion, job.version_id) if job.version_id else None
    snapshot_display = {key: value for key, value in (job.request_snapshot or {}).items() if key != "workflow"}
    workflow_display = (job.request_snapshot or {}).get("workflow") or {}
    snapshot_display["workflow(graph omitted)"] = {
        key: value for key, value in workflow_display.items() if key != "graph"
    }
    context = {
        "job": job,
        "project": project,
        "shot": shot,
        "version": version,
        "snapshot_json": json.dumps(snapshot_display, ensure_ascii=False, indent=2, default=str),
        "log": jobs_service.read_job_log(request.app.state.settings, job),
    }
    if request.query_params.get("partial") == "status":
        return render(request, "partials/job_status.html", context)
    return render(request, "job_detail.html", context)


@router.get("/jobs/{job_id}/log")
def job_log(request: Request, job_id: str, db: Session = Depends(get_db)):
    import html as html_module

    job = jobs_service.get_job(db, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="任务不存在")
    text = jobs_service.read_job_log(request.app.state.settings, job) or "（暂无日志）"
    return PlainTextResponse(html_module.escape(text))


# ------------------------------------------------------------------- 工作流与节点


@router.get("/workflows")
def workflows_page(request: Request, db: Session = Depends(get_db)):
    templates = list(db.query(WorkflowTemplate).order_by(WorkflowTemplate.category, WorkflowTemplate.name))
    endpoints = endpoints_service.list_endpoints(db)
    example_mapping = json.dumps(
        {
            "prompt": "12.inputs.text",
            "negative": "13.inputs.text",
            "seed": "24.inputs.seed",
            "input_image": "5.inputs.image",
            "output_prefix": "31.inputs.filename_prefix",
        },
        ensure_ascii=False,
        indent=2,
    )
    return render(request, "workflows.html", {
        "templates": templates,
        "endpoints": endpoints,
        "example_mapping": example_mapping,
    })


@router.get("/settings")
def settings_page(request: Request, db: Session = Depends(get_db), settings_obj: Settings = Depends(get_settings)):
    worker = getattr(request.app.state, "worker", None)
    endpoints = endpoints_service.list_endpoints(db)
    waiting_jobs = [
        job for job in jobs_service.list_jobs(db, status="queued", limit=200)
        if "等待" in (job.current_step or "")
    ]
    api_key = settings_obj.llm_api_key
    if api_key:
        masked = f"{api_key[:4]}…{api_key[-4:]}" if len(api_key) > 8 else "已配置（隐藏）"
    else:
        masked = ""
    return render(request, "settings.html", {
        "cfg": settings_obj,
        "worker_running": bool(worker and worker.is_running),
        "endpoints": endpoints,
        "waiting_jobs": waiting_jobs,
        "llm_key_masked": masked,
        "llm_config_file": config_path(),
    })


# ------------------------------------------------------------------- 媒体文件


@router.get("/media/{relative_path:path}")
def media_file(relative_path: str, request: Request):
    settings_obj: Settings = request.app.state.settings
    try:
        path = resolve_workspace_path(settings_obj.workspace_root, relative_path)
    except PathOutsideWorkspace as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    if path == config_path() or path.is_relative_to(WORKBENCH_ROOT):
        raise HTTPException(status_code=403, detail="禁止访问工作台内部文件（配置/数据库/缓存）")
    if not path.exists() or not path.is_file():
        raise HTTPException(status_code=404, detail="文件不存在")
    return FileResponse(path)


@router.get("/thumb/{asset_id}")
def thumb(asset_id: str, request: Request, db: Session = Depends(get_db)):
    settings_obj: Settings = request.app.state.settings
    asset = db.get(Asset, asset_id)
    if asset is None:
        raise HTTPException(status_code=404, detail="素材不存在")
    try:
        source = resolve_workspace_path(settings_obj.workspace_root, asset.file_path)
    except PathOutsideWorkspace as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    thumb_path = make_thumbnail(settings_obj, asset, source)
    if thumb_path is None:
        raise HTTPException(status_code=404, detail="无法生成缩略图")
    return FileResponse(thumb_path)
