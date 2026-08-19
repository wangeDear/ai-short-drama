from __future__ import annotations

import json
import shutil
from pathlib import Path
from types import SimpleNamespace

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.orm import Session

from ..config import LLM_CONFIG_KEYS, Settings, save_llm_config
from ..llm import LLMError
from ..llm.openai_compat import OpenAICompatAdapter
from ..media import PathOutsideWorkspace, resolve_workspace_path, unique_path
from ..models import (
    Asset,
    GenerationJob,
    Project,
    Shot,
    ShotVersion,
    WorkflowTemplate,
    JOB_TYPE_IMAGE,
    JOB_TYPE_VIDEO,
    JOB_TYPE_VOICE,
    JOB_TYPE_AMBIENCE,
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
from ..services.endpoints import EndpointError
from ..services.importer import ImportError_ as ImportFailure
from ..services.importer import import_legacy_studio, import_manifest, scan_videos
from ..services.jobs import JobError
from .deps import get_db, get_settings, load_endpoint, load_project, load_shot
from .helpers import is_cross_origin, is_hx, redirect_back

router = APIRouter(prefix="/api", include_in_schema=False)

GENERATION_TYPES = {JOB_TYPE_IMAGE: "图片", JOB_TYPE_VIDEO: "视频", JOB_TYPE_VOICE: "配音", JOB_TYPE_AMBIENCE: "环境音"}


def _render_card(request: Request, db: Session, shot: Shot) -> HTMLResponse | None:
    """HTMX 请求时返回更新后的分镜卡片片段。"""
    if not is_hx(request):
        return None
    project = db.get(Project, shot.project_id)
    views = shots_service.build_shot_views(db, [shot])
    templates = request.app.state.templates
    return templates.TemplateResponse(
        request=request,
        name="partials/shot_card.html",
        context={
            "project": project,
            "shot": shot,
            "views": views,
            "view_mode": "card",
        },
    )


# ------------------------------------------------------------------- 项目


@router.post("/projects/create")
def create_project(
    request: Request,
    name: str = Form(...),
    description: str = Form(""),
    aspect_ratio: str = Form("9:16"),
    resolution: str = Form("1216x704"),
    fps: int = Form(24),
    db: Session = Depends(get_db),
    settings_obj: Settings = Depends(get_settings),
):
    project = projects_service.create_project(
        db, settings_obj, name=name, description=description,
        aspect_ratio=aspect_ratio, resolution=resolution, fps=fps,
    )
    return redirect_back(request, default=f"/projects/{project.id}", msg=f"项目「{project.name}」已创建")


@router.post("/projects/create-creative")
def create_creative_project(
    request: Request,
    name: str = Form(...),
    source_text: str = Form(...),
    aspect_ratio: str = Form("9:16"),
    resolution: str = Form("704x1216"),
    fps: int = Form(24),
    genre: str = Form(""),
    target_shots: str = Form(""),
    realism: str = Form(""),
    ending: str = Form(""),
    db: Session = Depends(get_db),
    settings_obj: Settings = Depends(get_settings),
):
    """创意模式入口（§2）：建项目 + 存简报 + 自动入队故事方案生成。"""
    from urllib.parse import quote

    from ..services import creative as creative_service

    project = projects_service.create_project(
        db, settings_obj, name=name, description="创意模式（文本生成链路）",
        aspect_ratio=aspect_ratio, resolution=resolution, fps=fps,
    )
    constraints = {}
    for key, value in {"genre": genre, "realism": realism, "ending": ending}.items():
        if value.strip():
            constraints[key] = value.strip()
    if target_shots.strip().isdigit():
        constraints["target_shots"] = int(target_shots.strip())
    try:
        brief = creative_service.save_brief(db, project, source_text, constraints)
        job = creative_service.enqueue_story_plan(db, settings_obj, project)
    except creative_service.CreativeError as exc:
        target = f"/projects/{project.id}/creative?err={quote(str(exc))}"
        return RedirectResponse(target, status_code=303)
    estimate = creative_service.estimate_from_brief(brief)
    message = (
        f"项目已创建；故事方案生成中（{job.id[:12]}）。"
        f"预计 {estimate['shots']} 镜 / 约 {estimate['gpu_minutes']} GPU 分钟"
    )
    return RedirectResponse(f"/projects/{project.id}/creative?msg={quote(message)}", status_code=303)


@router.post("/projects/import")
def import_project(
    request: Request,
    mode: str = Form(...),
    path: str = Form(...),
    name: str = Form(""),
    db: Session = Depends(get_db),
    settings_obj: Settings = Depends(get_settings),
):
    try:
        if mode == "legacy":
            project = import_legacy_studio(db, settings_obj, path)
        elif mode == "manifest":
            project = import_manifest(db, settings_obj, path)
        elif mode == "scan":
            project = scan_videos(db, settings_obj, path, project_name=name or None)
        else:
            raise ImportFailure(f"未知导入模式: {mode}")
    except (ImportFailure, FileNotFoundError, ValueError) as exc:
        return redirect_back(request, default="/", err=f"导入失败: {exc}")
    return redirect_back(
        request, default=f"/projects/{project.id}",
        msg=f"已导入项目「{project.name}」（{len(project.shots)} 个分镜）",
    )


@router.post("/projects/{project_id}/update")
def update_project(
    project_id: str,
    request: Request,
    name: str = Form(None),
    description: str = Form(None),
    aspect_ratio: str = Form(None),
    resolution: str = Form(None),
    fps: int = Form(None),
    db: Session = Depends(get_db),
    settings_obj: Settings = Depends(get_settings),
):
    project = load_project(db, project_id)
    projects_service.update_project(db, settings_obj, project, {
        "name": name, "description": description, "aspect_ratio": aspect_ratio,
        "resolution": resolution, "fps": fps,
    })
    return redirect_back(request, msg="项目设置已保存")


@router.post("/projects/{project_id}/archive")
def archive_project(
    project_id: str,
    request: Request,
    archived: str = Form("1"),
    db: Session = Depends(get_db),
    settings_obj: Settings = Depends(get_settings),
):
    project = load_project(db, project_id)
    projects_service.archive_project(db, settings_obj, project, archived == "1")
    word = "归档" if archived == "1" else "恢复"
    return redirect_back(request, default="/", msg=f"项目已{word}")


@router.post("/projects/{project_id}/delete")
def delete_project(
    project_id: str,
    request: Request,
    delete_files: str = Form(""),
    db: Session = Depends(get_db),
    settings_obj: Settings = Depends(get_settings),
):
    from urllib.parse import quote

    project = load_project(db, project_id)
    name = project.name
    had_files = delete_files == "on"
    try:
        projects_service.delete_project(db, settings_obj, project, delete_files=had_files)
    except projects_service.ProjectDeleteError as exc:
        return redirect_back(request, err=str(exc))
    message = f"项目「{name}」已永久删除" + ("（含生成的项目文件）" if had_files else "（导入的源文件已保留）")
    return RedirectResponse(f"/?msg={quote(message)}", status_code=303)


@router.post("/projects/import-script")
def import_script(
    request: Request,
    name: str = Form(...),
    text: str = Form(...),
    default_seconds: float = Form(6.0),
    target_seconds: float = Form(10.0),
    aspect_ratio: str = Form("9:16"),
    resolution: str = Form("544x960"),
    fps: int = Form(24),
    auto_image: str = Form(""),
    db: Session = Depends(get_db),
    settings_obj: Settings = Depends(get_settings),
):
    """剧本文本 → 自动分段建分镜；可选自动批量提交图片生成。"""
    from ..services import script as script_service

    parsed = script_service.parse_script(
        text, default_duration=default_seconds, target_seconds=target_seconds
    )
    if not parsed:
        return redirect_back(request, err="未能从剧本文本中解析出任何分镜，请检查内容")

    project = projects_service.create_project(
        db, settings_obj, name=name, description=f"剧本自动分段（{len(parsed)} 镜）",
        aspect_ratio=aspect_ratio, resolution=resolution, fps=fps,
    )
    for item in parsed:
        shot = shots_service.create_shot(
            db, project,
            shot_code=item["code"], title=item["title"], duration=item["duration"],
            scene="", characters=item["characters"],
        )
        shot.description = item["description"]
        shot.voice_text = item["voice_text"]
        shot.ambience_text = item["ambience_text"]
        shot.seed = item["seed"]
        # 叙述文本作为提示词草稿基线（需人工润色为六段式模板）
        draft = item["description"] or item["voice_text"]
        shot.image_prompt = draft
        shot.video_prompt = draft
        db.flush()

    auto_note = ""
    if auto_image == "on":
        submitted, skipped = 0, 0
        for shot in list(project.shots):
            if not (shot.image_prompt or "").strip():
                skipped += 1
                continue
            try:
                jobs_service.enqueue_generation(db, settings_obj, shot, JOB_TYPE_IMAGE)
                submitted += 1
            except JobError:
                skipped += 1
        if submitted:
            auto_note = f"；已自动提交 {submitted} 个图片生成任务"
            if skipped:
                auto_note += f"（{skipped} 镜跳过）"
        else:
            auto_note = "；没有可用的生成节点/工作流，图片任务未提交（可在分镜工作台批量提交）"

    return redirect_back(
        request,
        default=f"/projects/{project.id}/shots",
        msg=f"剧本已解析为 {len(parsed)} 个分镜{auto_note}；提示词为草稿基线，请先润色再生成视频",
    )


# ------------------------------------------------------------------- 分镜


@router.post("/projects/{project_id}/shots/create")
def create_shot(
    project_id: str,
    request: Request,
    shot_code: str = Form(""),
    title: str = Form(""),
    duration: float = Form(8.0),
    scene: str = Form(""),
    characters: str = Form(""),
    image_prompt: str = Form(""),
    video_prompt: str = Form(""),
    db: Session = Depends(get_db),
):
    project = load_project(db, project_id)
    shot = shots_service.create_shot(
        db, project, shot_code=shot_code or None, title=title, duration=duration,
        scene=scene, characters=characters, image_prompt=image_prompt, video_prompt=video_prompt,
    )
    return redirect_back(request, msg=f"分镜 {shot.shot_code} 已创建")


@router.post("/shots/{shot_id}/update")
def update_shot(
    shot_id: str,
    request: Request,
    title: str | None = Form(None),
    description: str | None = Form(None),
    scene: str | None = Form(None),
    characters: str | None = Form(None),
    notes: str | None = Form(None),
    image_prompt: str | None = Form(None),
    image_negative: str | None = Form(None),
    video_prompt: str | None = Form(None),
    video_negative: str | None = Form(None),
    voice_text: str | None = Form(None),
    ambience_text: str | None = Form(None),
    duration: str | None = Form(None),
    seed: str | None = Form(None),
    workflow_template_id: str | None = Form(None),
    endpoint_id: str | None = Form(None),
    image_model: str | None = Form(None),
    video_model: str | None = Form(None),
    db: Session = Depends(get_db),
):
    shot = load_shot(db, shot_id)
    data = {
        "title": title,
        "description": description,
        "scene": scene,
        "characters": characters,
        "notes": notes,
        "image_prompt": image_prompt,
        "image_negative": image_negative,
        "video_prompt": video_prompt,
        "video_negative": video_negative,
        "voice_text": voice_text,
        "ambience_text": ambience_text,
        "duration": duration,
        "seed": seed,
        "workflow_template_id": workflow_template_id,
        "endpoint_id": endpoint_id,
        "image_model": image_model,
        "video_model": video_model,
    }
    notes = shots_service.update_shot(db, shot, data)
    message = "分镜已保存" + ("；" + "；".join(notes) if notes else "")
    card = _render_card(request, db, shot)
    if card is not None:
        return card
    return redirect_back(request, msg=message)


@router.post("/shots/{shot_id}/review")
def review_shot(
    shot_id: str,
    request: Request,
    action: str = Form(...),
    comment: str = Form(""),
    db: Session = Depends(get_db),
    settings_obj: Settings = Depends(get_settings),
):
    shot = load_shot(db, shot_id)
    try:
        if action == "approve_image":
            reviews_service.approve_image(db, shot, comment, settings=settings_obj)
            message = "分镜图片已批准"
        elif action == "return_image":
            reviews_service.return_image(db, shot, comment)
            message = "分镜图片已退回"
        elif action == "approve_audio":
            reviews_service.approve_audio(db, shot, comment)
            message = "配音已批准"
        elif action == "needs_revision":
            reviews_service.mark_needs_revision(db, shot, comment)
            message = "已标记需要修改"
        elif action == "comment":
            reviews_service.add_comment(db, shot, comment)
            message = "备注已保存"
        else:
            raise reviews_service.ReviewError(f"未知审核动作: {action}")
    except reviews_service.ReviewError as exc:
        card = _render_card(request, db, shot)
        if card is not None:
            return card
        return redirect_back(request, err=str(exc))
    card = _render_card(request, db, shot)
    if card is not None:
        return card
    return redirect_back(request, msg=message)


@router.post("/shots/{shot_id}/select-version")
def select_version(shot_id: str, request: Request, version_id: str = Form(...), db: Session = Depends(get_db)):
    shot = load_shot(db, shot_id)
    try:
        reviews_service.select_final_version(db, shot, version_id)
    except (reviews_service.ReviewError, ValueError) as exc:
        card = _render_card(request, db, shot)
        if card is not None:
            return card
        return redirect_back(request, err=str(exc))
    card = _render_card(request, db, shot)
    if card is not None:
        return card
    return redirect_back(request, msg="已选择最终采用版本")


@router.post("/shots/{shot_id}/generate")
def generate_for_shot(
    shot_id: str,
    request: Request,
    job_type: str = Form(JOB_TYPE_VIDEO),
    endpoint_id: str = Form(""),
    model_name: str = Form(""),
    db: Session = Depends(get_db),
    settings_obj: Settings = Depends(get_settings),
):
    shot = load_shot(db, shot_id)
    if job_type == JOB_TYPE_IMAGE and not (shot.image_prompt or "").strip():
        return _shot_error(request, db, shot, "请先填写图片提示词")
    if job_type in {JOB_TYPE_VIDEO, "inpaint"}:
        if not (shot.video_prompt or shot.image_prompt or "").strip():
            return _shot_error(request, db, shot, "请先填写视频提示词")
    try:
        job = jobs_service.enqueue_generation(
            db, settings_obj, shot, job_type,
            endpoint_id=endpoint_id or None,
            model_name=model_name or None,
        )
    except JobError as exc:
        return _shot_error(request, db, shot, str(exc))
    card = _render_card(request, db, shot)
    if card is not None:
        return card
    return redirect_back(request, msg=f"已提交{GENERATION_TYPES.get(job_type, job_type)}生成任务 {job.id[:12]}")


def _shot_error(request: Request, db: Session, shot: Shot, message: str):
    card = _render_card(request, db, shot)
    if card is not None:
        return card
    return redirect_back(request, err=message)


@router.post("/shots/{shot_id}/register-file")
def register_file(
    shot_id: str,
    request: Request,
    version_type: str = Form(...),
    file_path: str = Form(...),
    label: str = Form("导入"),
    db: Session = Depends(get_db),
    settings_obj: Settings = Depends(get_settings),
):
    shot = load_shot(db, shot_id)
    if version_type not in {"image", "video", "audio", "ambience"}:
        return redirect_back(request, err=f"不支持的版本类型: {version_type}")
    try:
        resolve_workspace_path(settings_obj.workspace_root, file_path)
        version, _asset = versions_service.register_existing_output(
            db, settings_obj, shot, version_type, file_path, label=label or "导入"
        )
    except PathOutsideWorkspace as exc:
        return redirect_back(request, err=str(exc))
    except FileNotFoundError as exc:
        return redirect_back(request, err=f"文件不存在: {exc}")
    card = _render_card(request, db, shot)
    if card is not None:
        return card
    return redirect_back(request, msg=f"已登记为 {version_type} v{version.version_number}")


@router.post("/shots/{shot_id}/upload-reference")
async def upload_reference(
    shot_id: str,
    request: Request,
    file: UploadFile = File(...),
    label: str = Form(""),
    db: Session = Depends(get_db),
    settings_obj: Settings = Depends(get_settings),
):
    shot = load_shot(db, shot_id)
    project = db.get(Project, shot.project_id)
    try:
        saved = await _save_upload(settings_obj, request, file, f"{project.root_path}/shots/{shot.shot_code}/inputs")
    except ValueError as exc:
        return redirect_back(request, err=str(exc))
    asset = versions_service.register_asset_file(
        db, settings_obj, project_id=project.id, absolute_path=saved,
        asset_type="reference", shot_id=shot.id,
        original_filename=file.filename or saved.name,
        extra_metadata={"label": label} if label else {},
    )
    card = _render_card(request, db, shot)
    if card is not None:
        return card
    return redirect_back(request, msg=f"参考素材已上传: {asset.original_filename}")


async def _save_upload(settings_obj: Settings, request: Request, upload: UploadFile, rel_dir: str) -> Path:
    directory = resolve_workspace_path(settings_obj.workspace_root, rel_dir)
    directory.mkdir(parents=True, exist_ok=True)
    suffix = Path(upload.filename or "upload.bin").suffix[:10] or ".bin"
    stem = Path(upload.filename or "upload").stem[:80] or "upload"
    target = unique_path(directory, stem, suffix)
    size = 0
    with target.open("wb") as handle:
        while chunk := await upload.read(1024 * 1024):
            size += len(chunk)
            handle.write(chunk)
    if size == 0:
        target.unlink(missing_ok=True)
        raise ValueError("上传的文件为空")
    if size > 2 * 1024 * 1024 * 1024:
        target.unlink(missing_ok=True)
        raise ValueError("文件超过 2GB 限制")
    return target


# ------------------------------------------------------------------- 批量操作


@router.post("/projects/{project_id}/shots/batch")
def batch_shots(
    project_id: str,
    request: Request,
    action: str = Form(...),
    shot_ids: list[str] = Form(default=[]),
    workflow_id: str = Form(""),
    job_type: str = Form(JOB_TYPE_VIDEO),
    db: Session = Depends(get_db),
    settings_obj: Settings = Depends(get_settings),
):
    project = load_project(db, project_id)
    shots = [shot for shot in (db.get(Shot, sid) for sid in shot_ids) if shot and shot.project_id == project.id]
    if not shots:
        return redirect_back(request, err="请先勾选分镜")

    if action == "approve_images":
        done, skipped = [], []
        for shot in shots:
            try:
                reviews_service.approve_image(db, shot, settings=settings_obj)
                done.append(shot.shot_code)
            except reviews_service.ReviewError:
                skipped.append(shot.shot_code)
        message = f"已批准 {len(done)} 张图片"
        if skipped:
            message += f"；{len(skipped)} 个分镜暂无可审图片（{'、'.join(skipped[:6])}）"
        return redirect_back(request, msg=message)

    if action == "generate":
        submitted, failed = [], []
        for shot in shots:
            try:
                jobs_service.enqueue_generation(db, settings_obj, shot, job_type)
                submitted.append(shot.shot_code)
            except JobError as exc:
                failed.append(f"{shot.shot_code}: {exc}")
        message = f"已提交 {len(submitted)} 个{GENERATION_TYPES.get(job_type, job_type)}生成任务"
        if failed:
            message += "；失败 " + "；".join(failed[:3])
        return redirect_back(request, msg=message)

    if action == "retry_failed":
        count = 0
        for shot in shots:
            for job in db.query(GenerationJob).filter(
                GenerationJob.shot_id == shot.id, GenerationJob.status == "failed"
            ).all():
                jobs_service.retry_job(db, settings_obj, job)
                count += 1
        return redirect_back(request, msg=f"已重新排队 {count} 个失败任务")

    if action == "change_workflow":
        if not workflow_id:
            return redirect_back(request, err="请选择要更换的工作流模板")
        for shot in shots:
            shots_service.update_shot(db, shot, {"workflow_template_id": workflow_id})
        return redirect_back(request, msg=f"已为 {len(shots)} 个分镜更换工作流")

    return redirect_back(request, err=f"未知批量操作: {action}")


# ------------------------------------------------------------------- 任务


def _render_job_row(request: Request, db: Session, job: GenerationJob) -> HTMLResponse | None:
    if not is_hx(request):
        return None
    project = db.get(Project, job.project_id) if job.project_id else None
    shot = db.get(Shot, job.shot_id) if job.shot_id else None
    templates = request.app.state.templates
    return templates.TemplateResponse(
        request=request,
        name="partials/job_row.html",
        context={"job": job, "project": project, "shot": shot},
    )


@router.post("/jobs/{job_id}/cancel")
def cancel_job(job_id: str, request: Request, db: Session = Depends(get_db), settings_obj: Settings = Depends(get_settings)):
    job = jobs_service.get_job(db, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="任务不存在")
    try:
        message = jobs_service.cancel_job(db, settings_obj, job)
    except JobError as exc:
        row = _render_job_row(request, db, job)
        if row is not None:
            return row
        return redirect_back(request, err=str(exc))
    row = _render_job_row(request, db, job)
    if row is not None:
        return row
    return redirect_back(request, msg=message)


@router.post("/jobs/{job_id}/retry")
def retry_job(job_id: str, request: Request, db: Session = Depends(get_db), settings_obj: Settings = Depends(get_settings)):
    job = jobs_service.get_job(db, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="任务不存在")
    try:
        jobs_service.retry_job(db, settings_obj, job)
    except JobError as exc:
        row = _render_job_row(request, db, job)
        if row is not None:
            return row
        return redirect_back(request, err=str(exc))
    row = _render_job_row(request, db, job)
    if row is not None:
        return row
    return redirect_back(request, msg="任务已重新排队")


@router.post("/jobs/{job_id}/rerun")
def rerun_job(job_id: str, request: Request, db: Session = Depends(get_db), settings_obj: Settings = Depends(get_settings)):
    job = jobs_service.get_job(db, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="任务不存在")
    new_job = jobs_service.rerun_job(db, settings_obj, job)
    return redirect_back(request, msg=f"已用相同参数创建新任务 {new_job.id[:12]}")


@router.post("/jobs/{job_id}/priority")
def job_priority(job_id: str, request: Request, delta: int = Form(...), db: Session = Depends(get_db)):
    job = jobs_service.get_job(db, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="任务不存在")
    jobs_service.bump_priority(db, job, delta)
    row = _render_job_row(request, db, job)
    if row is not None:
        return row
    return redirect_back(request, msg=f"优先级已调整为 {job.priority}")


# ------------------------------------------------------------------- 工作流与节点


@router.post("/workflows/create")
def create_workflow(
    request: Request,
    name: str = Form(...),
    category: str = Form("keyframe"),
    description: str = Form(""),
    workflow_json: str = Form("{}"),
    parameter_mapping_json: str = Form("{}"),
    required_models_json: str = Form("[]"),
    enabled: str = Form(""),
    db: Session = Depends(get_db),
):
    try:
        graph = _parse_json(workflow_json, "工作流 JSON", dict)
        mapping = _parse_json(parameter_mapping_json, "参数映射 JSON", dict)
        models = _parse_json(required_models_json, "依赖模型 JSON", list)
    except ValueError as exc:
        return redirect_back(request, err=str(exc))
    if not graph:
        return redirect_back(request, err="工作流 JSON 不能为空（请粘贴 ComfyUI API 格式导出）")
    template = WorkflowTemplate(
        name=name.strip(), category=category, description=description,
        workflow_json=graph, parameter_mapping_json=mapping,
        required_models_json=models, enabled=enabled == "on",
    )
    db.add(template)
    db.flush()
    return redirect_back(request, msg=f"工作流「{template.name}」已保存")


@router.post("/workflows/{template_id}/update")
def update_workflow(
    template_id: str,
    request: Request,
    name: str | None = Form(None),
    category: str | None = Form(None),
    description: str | None = Form(None),
    workflow_json: str | None = Form(None),
    parameter_mapping_json: str | None = Form(None),
    enabled: str | None = Form("__unset__"),
    db: Session = Depends(get_db),
):
    template = db.get(WorkflowTemplate, template_id)
    if template is None:
        raise HTTPException(status_code=404, detail="工作流不存在")
    if name:
        template.name = name.strip()
    if category:
        template.category = category
    if description is not None:
        template.description = description
    if workflow_json:
        try:
            template.workflow_json = _parse_json(workflow_json, "工作流 JSON", dict)
        except ValueError as exc:
            return redirect_back(request, err=str(exc))
    if parameter_mapping_json:
        try:
            template.parameter_mapping_json = _parse_json(parameter_mapping_json, "参数映射 JSON", dict)
        except ValueError as exc:
            return redirect_back(request, err=str(exc))
    if enabled != "__unset__":
        template.enabled = enabled == "on"
    db.flush()
    return redirect_back(request, msg="工作流已更新")


@router.post("/workflows/{template_id}/toggle")
def toggle_workflow(template_id: str, request: Request, db: Session = Depends(get_db)):
    template = db.get(WorkflowTemplate, template_id)
    if template is None:
        raise HTTPException(status_code=404, detail="工作流不存在")
    template.enabled = not template.enabled
    db.flush()
    state = "已启用" if template.enabled else "已禁用"
    return redirect_back(request, msg=f"工作流「{template.name}」{state}")


@router.post("/workflows/{template_id}/delete")
def delete_workflow(template_id: str, request: Request, db: Session = Depends(get_db)):
    template = db.get(WorkflowTemplate, template_id)
    if template is None:
        raise HTTPException(status_code=404, detail="工作流不存在")
    db.delete(template)
    db.flush()
    return redirect_back(request, msg=f"工作流「{template.name}」已删除")


def _parse_json(text: str, label: str, expected: type) -> object:
    try:
        value = json.loads(text or "")
    except ValueError as exc:
        raise ValueError(f"{label} 格式错误: {exc}") from exc
    if not isinstance(value, expected):
        raise ValueError(f"{label} 必须是{'对象' if expected is dict else '数组'}")
    return value


@router.post("/endpoints/create")
def create_endpoint(
    request: Request,
    name: str = Form(...),
    endpoint_type: str = Form("comfyui"),
    base_url: str = Form(""),
    check: str = Form(""),
    db: Session = Depends(get_db),
    settings_obj: Settings = Depends(get_settings),
):
    endpoint = endpoints_service.create_endpoint(db, name=name, endpoint_type=endpoint_type, base_url=base_url)
    if check == "on" and endpoint.endpoint_type == "comfyui":
        try:
            endpoints_service.check_endpoint(db, settings_obj, endpoint)
        except EndpointError:
            pass
    return redirect_back(request, msg=f"节点「{endpoint.name}」已登记")


@router.post("/endpoints/{endpoint_id}/check")
def check_endpoint(endpoint_id: str, request: Request, db: Session = Depends(get_db), settings_obj: Settings = Depends(get_settings)):
    endpoint = load_endpoint(db, endpoint_id)
    try:
        endpoints_service.check_endpoint(db, settings_obj, endpoint)
    except EndpointError as exc:
        return redirect_back(request, err=f"{endpoint.name}: {exc}")
    return redirect_back(request, msg=f"{endpoint.name} 连接正常（{endpoint.gpu_info or 'GPU 信息未知'}）")


@router.post("/endpoints/{endpoint_id}/fetch-models")
def fetch_models(endpoint_id: str, request: Request, db: Session = Depends(get_db), settings_obj: Settings = Depends(get_settings)):
    endpoint = load_endpoint(db, endpoint_id)
    models = endpoints_service.fetch_models(db, settings_obj, endpoint)
    if models:
        preview = "、".join(models[:5]) + ("…" if len(models) > 5 else "")
        return redirect_back(request, msg=f"{endpoint.name}: 获取到 {len(models)} 个模型（{preview}）")
    return redirect_back(request, err=f"{endpoint.name}: 未获取到模型列表（节点离线或无模型）")


@router.post("/endpoints/{endpoint_id}/delete")
def delete_endpoint(endpoint_id: str, request: Request, db: Session = Depends(get_db)):
    endpoint = load_endpoint(db, endpoint_id)
    endpoints_service.delete_endpoint(db, endpoint)
    return redirect_back(request, msg=f"节点「{endpoint.name}」已删除")


# ------------------------------------------------------------------- 角色与资产


@router.post("/projects/{project_id}/characters/create")
def create_character(
    project_id: str,
    request: Request,
    name: str = Form(...),
    description: str = Form(""),
    prompt_fragment: str = Form(""),
    db: Session = Depends(get_db),
):
    project = load_project(db, project_id)
    character = characters_service.create_character(
        db, project, name=name, description=description, prompt_fragment=prompt_fragment
    )
    return redirect_back(request, msg=f"角色「{character.name}」已创建")


@router.post("/characters/{character_id}/delete")
def delete_character(character_id: str, request: Request, db: Session = Depends(get_db)):
    character = characters_service.get_character(db, character_id)
    if character is None:
        raise HTTPException(status_code=404, detail="角色不存在")
    name = character.name
    characters_service.delete_character(db, character)
    return redirect_back(request, msg=f"角色「{name}」已删除")


@router.post("/characters/{character_id}/reference")
async def upload_character_reference(
    character_id: str,
    request: Request,
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    settings_obj: Settings = Depends(get_settings),
):
    character = characters_service.get_character(db, character_id)
    if character is None:
        raise HTTPException(status_code=404, detail="角色不存在")
    project = db.get(Project, character.project_id)
    try:
        saved = await _save_upload(settings_obj, request, file, "tmp/uploads")
    except ValueError as exc:
        return redirect_back(request, err=str(exc))
    asset = characters_service.attach_reference_image(
        db, settings_obj, character, saved, original_name=file.filename or ""
    )
    return redirect_back(request, msg=f"角色参考图已上传: {asset.original_filename}")


@router.post("/projects/{project_id}/assets/upload")
async def upload_project_asset(
    project_id: str,
    request: Request,
    asset_type: str = Form(...),
    label: str = Form(""),
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    settings_obj: Settings = Depends(get_settings),
):
    project = load_project(db, project_id)
    if asset_type not in {"reference", "mask", "control", "scene", "prop", "sound", "subtitle"}:
        return redirect_back(request, err=f"不支持的资产类型: {asset_type}")
    try:
        saved = await _save_upload(settings_obj, request, file, "tmp/uploads")
    except ValueError as exc:
        return redirect_back(request, err=str(exc))
    characters_service.register_public_asset(
        db, settings_obj, project, source=saved, asset_type=asset_type,
        original_name=file.filename or "", label=label,
    )
    return redirect_back(request, msg=f"资产已上传: {file.filename}")


@router.post("/assets/{asset_id}/delete")
def delete_asset(asset_id: str, request: Request, db: Session = Depends(get_db)):
    asset = db.get(Asset, asset_id)
    if asset is None:
        raise HTTPException(status_code=404, detail="素材不存在")
    if asset.version_id:
        return redirect_back(request, err="版本产物不能直接删除（受版本保护）")
    db.delete(asset)
    db.flush()
    return redirect_back(request, msg="素材记录已删除（文件保留在磁盘）")


# ------------------------------------------------------------------- 成片


@router.post("/projects/{project_id}/final/compose")
def compose_final(
    project_id: str,
    request: Request,
    force: str = Form(""),
    resolution: str = Form(""),
    fps: int = Form(0),
    crf: int = Form(20),
    preset: str = Form("medium"),
    music_path: str = Form(""),
    db: Session = Depends(get_db),
    settings_obj: Settings = Depends(get_settings),
):
    project = load_project(db, project_id)
    config = {
        "resolution": resolution or project.resolution,
        "fps": fps or project.fps,
        "crf": crf,
        "preset": preset,
        "music_path": music_path,
    }
    try:
        job = jobs_service.enqueue_compose(db, settings_obj, project, force=force == "on", config=config)
    except JobError as exc:
        return redirect_back(request, err=str(exc))
    label = "预览版（强制合成）" if force == "on" else "正式版"
    return redirect_back(request, msg=f"{label}合成任务已提交（{job.id[:12]}）")


# ------------------------------------------------------------------- 系统


@router.post("/settings/recover")
def settings_recover(request: Request, db: Session = Depends(get_db), settings_obj: Settings = Depends(get_settings)):
    recovered = jobs_service.recover_stale(db, settings_obj.stale_job_minutes)
    if recovered:
        return redirect_back(request, msg=f"已恢复 {len(recovered)} 个僵死任务为失败状态，可重试")
    return redirect_back(request, msg="没有发现心跳超时的任务")


@router.post("/settings/check-all")
def settings_check_all(request: Request, db: Session = Depends(get_db), settings_obj: Settings = Depends(get_settings)):
    results = []
    for endpoint in endpoints_service.list_endpoints(db):
        try:
            endpoints_service.check_endpoint(db, settings_obj, endpoint)
            results.append(f"{endpoint.name}: 在线")
        except EndpointError as exc:
            results.append(f"{endpoint.name}: {exc}")
    return redirect_back(request, msg="；".join(results) if results else "尚未登记任何生成节点")


@router.post("/settings/llm")
def settings_llm_save(
    request: Request,
    llm_type: str = Form(...),
    llm_base_url: str = Form(""),
    llm_model: str = Form(""),
    llm_api_key: str = Form(""),
    llm_timeout_seconds: str = Form(""),
    llm_max_repair: str = Form(""),
    clear_api_key: str = Form(""),
    settings_obj: Settings = Depends(get_settings),
):
    """设置页在线配置文本模型：写入 config.json 并即时生效（无需重启）。"""
    if is_cross_origin(request):
        return redirect_back(request, err="拒绝跨站请求：Origin/Referer 与本站不符")
    llm_type = llm_type.strip()
    if llm_type not in ("mock", "openai"):
        return redirect_back(request, err="文本模型类型仅支持 mock / openai")
    base_url = llm_base_url.strip().rstrip("/")
    model = llm_model.strip()
    if llm_type == "openai" and (not base_url or not model):
        return redirect_back(request, err="openai 类型必须填写接口地址与模型名")
    key_touched = bool(llm_api_key.strip()) or bool(clear_api_key)
    if (
        llm_type == "openai"
        and settings_obj.llm_api_key
        and base_url != settings_obj.llm_base_url
        and not key_touched
    ):
        return redirect_back(
            request,
            err="接口地址已变更：为防已保存的 API Key 被误发往新地址，请重新输入 Key（或勾选清除）",
        )

    numbers: dict[str, float | None] = {}
    for name, raw, low, high, cast in (
        ("llm_timeout_seconds", llm_timeout_seconds, 1.0, 600.0, float),
        ("llm_max_repair", llm_max_repair, 0.0, 5.0, int),
    ):
        raw = raw.strip()
        if not raw:
            numbers[name] = None  # 留空 = 删除覆盖，恢复默认
            continue
        try:
            value = cast(float(raw))
        except ValueError:
            return redirect_back(request, err=f"{name} 不是合法数字")
        if not low <= value <= high:
            return redirect_back(request, err=f"{name} 需在 {low:g} ~ {high:g} 之间")
        numbers[name] = value

    file_values: dict[str, object] = {
        "llm_type": llm_type,
        "llm_base_url": base_url or None,
        "llm_model": model or None,
        **numbers,
    }
    if clear_api_key:
        file_values["llm_api_key"] = None
    elif llm_api_key.strip():
        file_values["llm_api_key"] = llm_api_key.strip()
    # 未填 api_key 且未勾选清除：文件中保留原值

    try:
        save_llm_config(file_values)
    except (OSError, ValueError) as exc:
        return redirect_back(request, err=f"config.json 写入失败: {exc}")

    # 即时生效：按 file > env > default 的同一优先级刷新内存配置（Worker 共享同一对象）
    fresh = Settings()
    for key in LLM_CONFIG_KEYS:
        setattr(settings_obj, key, getattr(fresh, key))

    summary = f"文本模型已保存并即时生效：{llm_type}"
    if llm_type == "openai":
        summary += f"（{settings_obj.llm_model} @ {settings_obj.llm_base_url}）"
    if clear_api_key:
        summary += "；API Key 已清除"
    return redirect_back(request, msg=summary)


@router.post("/settings/llm/test")
def settings_llm_test(request: Request, settings_obj: Settings = Depends(get_settings)):
    """用当前生效配置发一次最小对话请求，验证连通性。"""
    if is_cross_origin(request):
        return redirect_back(request, err="拒绝跨站请求：Origin/Referer 与本站不符")
    if settings_obj.llm_type == "mock":
        return redirect_back(request, msg="mock 模式：离线确定性生成，无需外部连接")
    probe = SimpleNamespace(
        llm_base_url=settings_obj.llm_base_url,
        llm_model=settings_obj.llm_model,
        llm_api_key=settings_obj.llm_api_key,
        llm_timeout_seconds=min(15.0, settings_obj.llm_timeout_seconds or 15.0),
    )
    try:
        reply = OpenAICompatAdapter().chat(probe, system="你是连通性测试。", user="请只回复两个字：正常")
    except LLMError as exc:
        return redirect_back(request, err=f"连接失败：{exc}")
    return redirect_back(request, msg=f"连接成功（{settings_obj.llm_model}）：{str(reply)[:60]}")


# ------------------------------------------------------------------- v0.3 创作链路


@router.post("/projects/{project_id}/brief")
def save_brief(
    project_id: str,
    request: Request,
    source_text: str = Form(...),
    genre: str = Form(""),
    platform: str = Form(""),
    total_duration: str = Form(""),
    episodes: str = Form(""),
    language: str = Form(""),
    realism: str = Form(""),
    dialogue_density: str = Form(""),
    ending: str = Form(""),
    avoid: str = Form(""),
    target_shots: str = Form(""),
    db: Session = Depends(get_db),
):
    """FR-CREATIVE-001：保存创意简报（新版本，不覆盖）。"""
    from ..services import creative as creative_service

    project = load_project(db, project_id)
    constraints = {}
    for key, value in {
        "genre": genre, "platform": platform, "total_duration": total_duration,
        "episodes": episodes, "language": language, "realism": realism,
        "dialogue_density": dialogue_density, "ending": ending, "avoid": avoid,
    }.items():
        if value.strip():
            constraints[key] = value.strip()
    for key, value in {"episodes": episodes, "target_shots": target_shots}.items():
        if value.strip().isdigit():
            constraints[key] = int(value.strip())
    try:
        brief = creative_service.save_brief(db, project, source_text, constraints)
    except creative_service.CreativeError as exc:
        return redirect_back(request, err=str(exc))
    estimate = creative_service.estimate_from_brief(brief)
    return redirect_back(
        request,
        msg=f"简报 v{brief.version_number} 已保存；预计 {estimate['scenes']} 场 / "
            f"{estimate['shots']} 镜 / {estimate['image_tasks']} 图 / {estimate['video_tasks']} 视频 / "
            f"约 {estimate['gpu_minutes']} GPU 分钟",
    )


@router.post("/projects/{project_id}/creative/generate")
def creative_generate(
    project_id: str,
    request: Request,
    stage: str = Form(...),
    scope_shot_ids: str = Form(""),
    db: Session = Depends(get_db),
    settings_obj: Settings = Depends(get_settings),
):
    """四阶段文本生成入队（story_plan / script / bible / shot_plans，§10.3 异步）。"""
    from ..services import creative as creative_service

    project = load_project(db, project_id)
    try:
        if stage == "story_plan":
            job = creative_service.enqueue_story_plan(db, settings_obj, project)
            label = "故事方案"
        elif stage == "script":
            job = creative_service.enqueue_script(db, settings_obj, project)
            label = "结构化剧本"
        elif stage == "bible":
            job = creative_service.enqueue_bible(db, settings_obj, project)
            label = "生产设定"
        elif stage == "shot_plans":
            scope = [s for s in scope_shot_ids.split(",") if s.strip()]
            job = creative_service.enqueue_shot_plans(db, settings_obj, project, scope_shot_ids=scope or None)
            label = "分镜与提示词" + (f"（范围重做 {len(scope)} 镜）" if scope else "")
        else:
            return redirect_back(request, err=f"未知阶段: {stage}")
    except creative_service.CreativeError as exc:
        return redirect_back(request, err=str(exc))
    return redirect_back(request, msg=f"{label}生成任务已提交（{job.id[:12]}）")


@router.post("/projects/{project_id}/script/edit")
async def edit_script(
    project_id: str,
    request: Request,
    db: Session = Depends(get_db),
):
    """卡点 A 编辑剧本：表单字段 scene_{code}_action / _dialogue / _duration（FR-GATE-004）。"""
    from ..services import creative as creative_service

    project = load_project(db, project_id)
    updates: dict[str, dict] = {}
    form = await _form_data(request)
    for key, value in form.items():
        if not key.startswith("scene_") or not value.strip():
            continue
        remainder = key[len("scene_"):]
        for suffix in ("_action", "_dialogue", "_narration", "_duration"):
            if remainder.endswith(suffix):
                code = remainder[: -len(suffix)]
                updates.setdefault(code, {})[suffix[1:]] = value.strip()
                break
    if not updates:
        return redirect_back(request, err="没有发生任何修改")
    try:
        row = creative_service.edit_script_scene(db, project, updates)
    except creative_service.CreativeError as exc:
        return redirect_back(request, err=str(exc))
    return redirect_back(request, msg=f"剧本修改已保存为新版本（{len(updates)} 场），等待 A 卡点审核")


async def _form_data(request: Request) -> dict:
    return {key: value for key, value in (await request.form()).items()}


@router.post("/projects/{project_id}/bible/edit")
def edit_bible(
    project_id: str,
    request: Request,
    item_type: str = Form(...),
    name: str = Form(""),
    updates_json: str = Form("{}"),
    db: Session = Depends(get_db),
):
    """编辑生产设定项（新版本 + 精准失效，验收 24）。"""
    import json as json_module

    from ..services import creative as creative_service

    project = load_project(db, project_id)
    try:
        updates = json_module.loads(updates_json or "{}")
        if not isinstance(updates, dict):
            raise ValueError("必须是 JSON 对象")
    except ValueError as exc:
        return redirect_back(request, err=f"更新内容格式错误: {exc}")
    try:
        row = creative_service.edit_bible_item(db, project, item_type, name, updates)
    except creative_service.CreativeError as exc:
        return redirect_back(request, err=str(exc))
    return redirect_back(request, msg=f"生产设定已更新为 v{row.version_number}（引用镜头已标记过期）")


@router.post("/projects/{project_id}/gates/{gate}/decide")
def gate_decide(
    project_id: str,
    gate: str,
    request: Request,
    decision: str = Form(...),
    comment: str = Form(""),
    scope_type: str = Form("project"),
    scope_id: str = Form(""),
    db: Session = Depends(get_db),
    settings_obj: Settings = Depends(get_settings),
):
    """A/B 卡点决定（approve/return；return 必须填原因，FR-GATE-004）。"""
    from ..services import gates as gates_service

    project = load_project(db, project_id)
    try:
        record = gates_service.decide(
            db, settings_obj, project, gate, decision,
            comment=comment, scope_type=scope_type, scope_id=scope_id or None,
        )
    except gates_service.GateError as exc:
        return redirect_back(request, err=str(exc))
    word = "已批准" if decision == "approve" else "已退回"
    scope_note = f"（范围：{scope_type}）" if scope_type != "project" else ""
    return redirect_back(request, msg=f"{gate} 卡点{word}{scope_note}，决定已记录（{record.id[:10]}）")


@router.post("/projects/{project_id}/pipeline-config")
def pipeline_config(
    project_id: str,
    request: Request,
    gate_a: str = Form(""),
    gate_b: str = Form(""),
    auto_queue_after_c: str = Form(""),
    db: Session = Depends(get_db),
):
    """卡点开关与 C 通过自动排队配置（A/B 可关，C/D 强制开启）。"""
    from ..services import gates as gates_service

    project = load_project(db, project_id)
    gates_service.update_pipeline_config(db, project, {
        "gate_a": gate_a == "on",
        "gate_b": gate_b == "on",
        "auto_queue_after_c": auto_queue_after_c == "on",
    })
    auto_note = "；C 通过后将自动排队视频" if auto_queue_after_c == "on" else ""
    return redirect_back(request, msg=f"流水线配置已保存{auto_note}")


@router.post("/shots/{shot_id}/package/edit")
def edit_package(
    shot_id: str,
    request: Request,
    image_json: str = Form("{}"),
    video_json: str = Form("{}"),
    audio_json: str = Form("{}"),
    db: Session = Depends(get_db),
):
    """编辑分镜提示词包（新版本 + 重新拼装，FR-CREATIVE-004）。"""
    import json as json_module
    from copy import deepcopy

    from ..creative.schemas import TEMPLATE_VERSION
    from ..models import PromptPackage
    from ..services import creative as creative_service
    from ..services import prompt_compiler

    shot = load_shot(db, shot_id)
    project = db.get(Project, shot.project_id)
    latest = (
        db.query(PromptPackage)
        .filter(PromptPackage.shot_id == shot.id)
        .order_by(PromptPackage.version_number.desc())
        .first()
    )
    if latest is None:
        return redirect_back(request, err="该分镜还没有提示词包，请先生成分镜计划")
    try:
        parsed = {k: json_module.loads(v or "{}") for k, v in (("image", image_json), ("video", video_json), ("audio", audio_json))}
        for key, value in parsed.items():
            if not isinstance(value, dict):
                raise ValueError(f"{key}_json 必须是 JSON 对象")
    except ValueError as exc:
        return redirect_back(request, err=f"提示词包格式错误: {exc}")

    bible = creative_service.latest_bible(db, project, statuses=["approved", "reviewing"])
    package = PromptPackage(
        shot_id=shot.id,
        version_number=latest.version_number + 1,
        image_prompt_json=parsed["image"] or deepcopy(latest.image_prompt_json or {}),
        video_prompt_json=parsed["video"] or deepcopy(latest.video_prompt_json or {}),
        audio_prompt_json=parsed["audio"] or deepcopy(latest.audio_prompt_json or {}),
        required_references_json=list(latest.required_references_json or []),
        risk_tags_json=list(latest.risk_tags_json or []),
        route_suggestion_json=dict(latest.route_suggestion_json or {}),
        template_version=TEMPLATE_VERSION,
        content_hash=creative_service.content_hash(parsed),
        status="reviewing",
    )
    db.add(package)
    db.flush()
    prompt_compiler.apply_to_shot(db, shot, package, (bible.global_style_json if bible else None))
    return redirect_back(request, msg=f"提示词包已更新为 v{package.version_number}，提示词已重新拼装")
