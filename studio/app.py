from __future__ import annotations

import json
import os
import subprocess
import threading
import uuid
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field


STUDIO_ROOT = Path(__file__).resolve().parent
WORKSPACE_ROOT = STUDIO_ROOT.parent.resolve()
STATIC_ROOT = STUDIO_ROOT / "static"
DATA_ROOT = STUDIO_ROOT / "data"
PROJECT_FILE = Path(os.environ.get("STUDIO_PROJECT_FILE", DATA_ROOT / "project.json")).resolve()
CONFIG_FILE = Path(os.environ.get("STUDIO_CONFIG_FILE", STUDIO_ROOT / "config.json")).resolve()
JOBS_ROOT = DATA_ROOT / "jobs"

DATA_LOCK = threading.RLock()
ACTIVE_PROCESSES: dict[str, subprocess.Popen[str]] = {}


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def load_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return deepcopy(default)
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def atomic_write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    with temporary.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2)
        handle.write("\n")
    temporary.replace(path)


def load_project() -> dict[str, Any]:
    with DATA_LOCK:
        project = load_json(PROJECT_FILE, {"segments": [], "jobs": []})
    project["runner_configured"] = runner_config() is not None
    return project


def save_project(project: dict[str, Any]) -> None:
    clean = deepcopy(project)
    clean.pop("runner_configured", None)
    clean["updated_at"] = utc_now()
    with DATA_LOCK:
        atomic_write_json(PROJECT_FILE, clean)


def find_segment(project: dict[str, Any], segment_id: str) -> dict[str, Any]:
    for segment in project.get("segments", []):
        if segment.get("id") == segment_id:
            return segment
    raise HTTPException(status_code=404, detail="分段不存在")


def resolve_workspace_path(relative_path: str) -> Path:
    candidate = (WORKSPACE_ROOT / relative_path).resolve()
    try:
        candidate.relative_to(WORKSPACE_ROOT)
    except ValueError as exc:
        raise HTTPException(status_code=403, detail="禁止访问工作区之外的文件") from exc
    return candidate


def runner_config() -> dict[str, Any] | None:
    config = load_json(CONFIG_FILE, {})
    runner = config.get("runner") if isinstance(config, dict) else None
    if not isinstance(runner, dict) or not runner.get("enabled"):
        return None
    command = runner.get("command")
    if not isinstance(command, list) or not command or not all(isinstance(item, str) for item in command):
        return None
    return runner


def render_template(value: str, replacements: dict[str, str]) -> str:
    rendered = value
    for key, replacement in replacements.items():
        rendered = rendered.replace("{" + key + "}", replacement)
    return rendered


def update_job(job_id: str, **changes: Any) -> None:
    project = load_project()
    project.pop("runner_configured", None)
    for job in project.get("jobs", []):
        if job.get("id") == job_id:
            job.update(changes)
            job["updated_at"] = utc_now()
            save_project(project)
            return


def job_status(job_id: str) -> str | None:
    project = load_project()
    for job in project.get("jobs", []):
        if job.get("id") == job_id:
            return job.get("status")
    return None


def finalize_job(job_id: str, segment_id: str, process: subprocess.Popen[str], output_path: str | None) -> None:
    exit_code = process.wait()
    ACTIVE_PROCESSES.pop(job_id, None)
    if job_status(job_id) == "cancelled":
        return
    if exit_code != 0:
        update_job(job_id, status="failed", exit_code=exit_code, message="生成命令执行失败")
        return

    project = load_project()
    project.pop("runner_configured", None)
    segment = find_segment(project, segment_id)
    resolved_output: str | None = None
    if output_path:
        output_candidate = resolve_workspace_path(output_path)
        if output_candidate.exists() and output_candidate.is_file():
            resolved_output = output_path.replace("\\", "/")

    if resolved_output:
        version_id = f"v-{uuid.uuid4().hex[:8]}"
        segment.setdefault("versions", []).insert(
            0,
            {
                "id": version_id,
                "label": f"生成 {datetime.now().strftime('%m-%d %H:%M')}",
                "video_path": resolved_output,
                "created_at": utc_now(),
                "source": "runner",
            },
        )
        segment["video_status"] = "review"
        save_project(project)
        update_job(job_id, status="completed", exit_code=0, output_path=resolved_output, message="生成完成，等待审核")
    else:
        update_job(job_id, status="completed", exit_code=0, message="命令完成，但未发现配置的输出文件")


class SegmentPatch(BaseModel):
    title: str | None = Field(default=None, max_length=120)
    prompt: str | None = Field(default=None, max_length=20_000)
    notes: str | None = Field(default=None, max_length=4_000)
    image_status: str | None = None
    video_status: str | None = None


class SelectVersionRequest(BaseModel):
    version_id: str


class AttachVersionRequest(BaseModel):
    video_path: str
    label: str | None = Field(default=None, max_length=80)


app = FastAPI(title="Project023 导演审核台", version="0.1.0")
app.mount("/static", StaticFiles(directory=STATIC_ROOT), name="static")


@app.get("/")
def index() -> FileResponse:
    return FileResponse(STATIC_ROOT / "index.html")


@app.get("/media/{relative_path:path}")
def media(relative_path: str) -> FileResponse:
    path = resolve_workspace_path(relative_path)
    if not path.exists() or not path.is_file():
        raise HTTPException(status_code=404, detail="媒体文件不存在")
    return FileResponse(path)


@app.get("/api/project")
def get_project() -> dict[str, Any]:
    return load_project()


@app.patch("/api/segments/{segment_id}")
def patch_segment(segment_id: str, patch: SegmentPatch) -> dict[str, Any]:
    project = load_project()
    project.pop("runner_configured", None)
    segment = find_segment(project, segment_id)
    changes = patch.model_dump(exclude_none=True)
    segment.update(changes)
    if "prompt" in changes:
        segment["video_status"] = "stale" if segment.get("selected_version_id") else segment.get("video_status", "missing")
        segment["stale_reason"] = "提示词已修改"
    save_project(project)
    return segment


@app.post("/api/segments/{segment_id}/approve-image")
def approve_image(segment_id: str) -> dict[str, Any]:
    project = load_project()
    project.pop("runner_configured", None)
    segment = find_segment(project, segment_id)
    segment["image_status"] = "approved"
    save_project(project)
    return segment


@app.post("/api/segments/{segment_id}/flag-image")
def flag_image(segment_id: str) -> dict[str, Any]:
    project = load_project()
    project.pop("runner_configured", None)
    segment = find_segment(project, segment_id)
    segment["image_status"] = "changes_requested"
    save_project(project)
    return segment


@app.post("/api/segments/{segment_id}/select-version")
def select_version(segment_id: str, body: SelectVersionRequest) -> dict[str, Any]:
    project = load_project()
    project.pop("runner_configured", None)
    segment = find_segment(project, segment_id)
    if segment.get("image_status") != "approved":
        raise HTTPException(status_code=409, detail="请先确认分镜图，再采用视频版本")
    versions = segment.get("versions", [])
    if not any(version.get("id") == body.version_id for version in versions):
        raise HTTPException(status_code=404, detail="视频版本不存在")
    segment["selected_version_id"] = body.version_id
    segment["video_status"] = "approved"
    segment.pop("stale_reason", None)
    save_project(project)
    return segment


@app.post("/api/segments/{segment_id}/versions")
def attach_version(segment_id: str, body: AttachVersionRequest) -> dict[str, Any]:
    path = resolve_workspace_path(body.video_path)
    if not path.exists() or not path.is_file():
        raise HTTPException(status_code=400, detail="指定的视频文件不存在")
    project = load_project()
    project.pop("runner_configured", None)
    segment = find_segment(project, segment_id)
    version = {
        "id": f"v-{uuid.uuid4().hex[:8]}",
        "label": body.label or f"手动导入 {datetime.now().strftime('%m-%d %H:%M')}",
        "video_path": body.video_path.replace("\\", "/"),
        "created_at": utc_now(),
        "source": "manual",
    }
    segment.setdefault("versions", []).insert(0, version)
    segment["video_status"] = "review"
    save_project(project)
    return version


@app.post("/api/segments/{segment_id}/generate")
def generate_segment(segment_id: str) -> dict[str, Any]:
    runner = runner_config()
    if runner is None:
        raise HTTPException(status_code=409, detail="Runner 尚未配置；请先复制 config.example.json 为 config.json 并填写生产命令")

    project = load_project()
    project.pop("runner_configured", None)
    segment = find_segment(project, segment_id)
    if segment.get("image_status") != "approved":
        raise HTTPException(status_code=409, detail="请先确认分镜图")

    job_id = f"job-{uuid.uuid4().hex[:10]}"
    job_dir = JOBS_ROOT / job_id
    job_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = job_dir / "manifest.json"
    log_path = job_dir / "runner.log"
    manifest = {
        "job_id": job_id,
        "project_id": project.get("id"),
        "segment": deepcopy(segment),
        "workspace_root": str(WORKSPACE_ROOT),
        "submitted_at": utc_now(),
    }
    atomic_write_json(manifest_path, manifest)

    replacements = {
        "job_id": job_id,
        "segment_id": segment_id,
        "manifest_path": str(manifest_path),
        "workspace": str(WORKSPACE_ROOT),
    }
    command = [render_template(item, replacements) for item in runner["command"]]
    cwd_raw = runner.get("cwd", "{workspace}")
    cwd = Path(render_template(str(cwd_raw), replacements)).resolve()
    if not cwd.exists() or not cwd.is_dir():
        raise HTTPException(status_code=400, detail="Runner 工作目录不存在")

    output_template = runner.get("output_path")
    output_path = render_template(str(output_template), replacements) if output_template else None
    log_handle = log_path.open("w", encoding="utf-8")
    try:
        process = subprocess.Popen(
            command,
            cwd=cwd,
            stdout=log_handle,
            stderr=subprocess.STDOUT,
            text=True,
            shell=False,
        )
    except Exception:
        log_handle.close()
        raise
    log_handle.close()
    ACTIVE_PROCESSES[job_id] = process

    job = {
        "id": job_id,
        "segment_id": segment_id,
        "status": "running",
        "message": "生成命令已启动",
        "pid": process.pid,
        "log_path": str(log_path.relative_to(WORKSPACE_ROOT)).replace("\\", "/"),
        "created_at": utc_now(),
        "updated_at": utc_now(),
    }
    project.setdefault("jobs", []).insert(0, job)
    segment["video_status"] = "generating"
    save_project(project)

    thread = threading.Thread(
        target=finalize_job,
        args=(job_id, segment_id, process, output_path),
        daemon=True,
    )
    thread.start()
    return job


@app.post("/api/jobs/{job_id}/cancel")
def cancel_job(job_id: str) -> dict[str, Any]:
    process = ACTIVE_PROCESSES.get(job_id)
    if process is None or process.poll() is not None:
        raise HTTPException(status_code=409, detail="任务未运行或已经结束")
    process.terminate()
    update_job(job_id, status="cancelled", message="用户已取消")
    return {"id": job_id, "status": "cancelled"}


@app.get("/api/jobs")
def list_jobs() -> list[dict[str, Any]]:
    return load_project().get("jobs", [])[:50]


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="127.0.0.1", port=8765)
