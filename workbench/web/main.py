from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from .. import __version__
from ..config import Settings, settings
from ..db import init_db, make_engine, make_session_factory
from ..db import session_scope
from ..models import (
    JOB_STATUS_LABELS,
    JOB_STATUS_QUEUED,
    JOB_STATUS_RUNNING,
    JOB_TYPE_LABELS,
    SHOT_STATUS_LABELS,
    VERSION_STATUS_LABELS,
    VERSION_TYPE_LABELS,
    WORKFLOW_CATEGORY_LABELS,
    ASSET_TYPE_LABELS,
    REVIEW_DECISIONS,
)
from ..services.workflows import seed_example_templates
from ..worker import Worker

WORKBENCH_ROOT = Path(__file__).resolve().parent.parent
TEMPLATES = Jinja2Templates(directory=str(WORKBENCH_ROOT / "templates"))


def _fmt_dt(value) -> str:
    if value is None:
        return "—"
    return value.strftime("%m-%d %H:%M")


def _fmt_dt_full(value) -> str:
    if value is None:
        return "—"
    return value.strftime("%Y-%m-%d %H:%M:%S")


def _fmt_duration(value) -> str:
    if value is None:
        return "—"
    try:
        seconds = float(value)
    except (TypeError, ValueError):
        return "—"
    if seconds < 60:
        return f"{seconds:.0f}s"
    minutes, sec = divmod(int(seconds), 60)
    hours, minutes = divmod(minutes, 60)
    return f"{hours}h{minutes:02d}m" if hours else f"{minutes}m{sec:02d}s"


def _fmt_size(value) -> str:
    if not value:
        return "—"
    size = float(value)
    for unit in ("B", "KB", "MB", "GB"):
        if size < 1024:
            return f"{size:.0f}{unit}"
        size /= 1024
    return f"{size:.1f}TB"


def _status_css(status: str) -> str:
    palette = {
        "queued": "st-queued",
        "running": "st-running",
        "succeeded": "st-ok",
        "accepted": "st-ok",
        "failed": "st-failed",
        "cancelled": "st-muted",
        "reviewing": "st-warn",
        "draft": "st-muted",
        "image_review": "st-warn",
        "image_approved": "st-info",
        "video_review": "st-warn",
        "needs_revision": "st-failed",
        "online": "st-ok",
        "offline": "st-failed",
        "unknown": "st-muted",
        "superseded": "st-muted",
        "revision": "st-failed",
    }
    return palette.get(status, "st-muted")


def _omit_filter(params, *keys) -> str:
    from urllib.parse import urlencode

    try:
        items = list(params.multi_items())
    except AttributeError:
        items = list(params.items())
    return urlencode([(key, value) for key, value in items if key not in keys])


def register_template_globals(app: FastAPI, settings_obj: Settings) -> None:
    TEMPLATES.env.filters["omit"] = _omit_filter
    TEMPLATES.env.globals.update(
        app_version=__version__,
        job_status_labels=JOB_STATUS_LABELS,
        job_type_labels=JOB_TYPE_LABELS,
        shot_status_labels=SHOT_STATUS_LABELS,
        version_status_labels=VERSION_STATUS_LABELS,
        version_type_labels=VERSION_TYPE_LABELS,
        workflow_categories=WORKFLOW_CATEGORY_LABELS,
        asset_type_labels=ASSET_TYPE_LABELS,
        review_decisions=REVIEW_DECISIONS,
        fmt_dt=_fmt_dt,
        fmt_dt_full=_fmt_dt_full,
        fmt_duration=_fmt_duration,
        fmt_size=_fmt_size,
        status_css=_status_css,
        htmx_url=settings_obj.htmx_url,
        ffmpeg_available=_ffmpeg_available(settings_obj),
    )


def _ffmpeg_available(settings_obj: Settings) -> bool:
    import shutil

    return shutil.which(settings_obj.ffmpeg_bin) is not None


def nav_counts(session) -> dict:
    from sqlalchemy import func, select

    from ..models import GenerationJob

    active = session.execute(
        select(GenerationJob.status, func.count())
        .where(GenerationJob.status.in_([JOB_STATUS_QUEUED, JOB_STATUS_RUNNING]))
        .group_by(GenerationJob.status)
    ).all()
    counts = {status: count for status, count in active}
    return {
        "active_jobs": counts.get(JOB_STATUS_RUNNING, 0) + counts.get(JOB_STATUS_QUEUED, 0),
        "running_jobs": counts.get(JOB_STATUS_RUNNING, 0),
        "queued_jobs": counts.get(JOB_STATUS_QUEUED, 0),
    }


def create_app(settings_obj: Settings | None = None) -> FastAPI:
    settings_obj = settings_obj or settings
    settings_obj.ensure_dirs()
    engine = make_engine(settings_obj)
    init_db(engine)
    factory = make_session_factory(engine)
    with session_scope(factory) as session:
        seed_example_templates(session)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        worker = None
        if settings_obj.worker_enabled:
            worker = Worker(factory, settings_obj)
            worker.start()
        app.state.worker = worker
        yield
        if worker is not None:
            worker.stop()

    app = FastAPI(title="AI 短剧生成审核工作台", version=__version__, lifespan=lifespan)
    app.state.settings = settings_obj
    app.state.session_factory = factory
    app.state.engine = engine

    register_template_globals(app, settings_obj)
    app.state.templates = TEMPLATES

    static_dir = WORKBENCH_ROOT / "static"
    app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")

    from . import actions, pages

    app.include_router(pages.router)
    app.include_router(actions.router)

    @app.get("/healthz")
    def healthz() -> dict:
        worker = getattr(app.state, "worker", None)
        return {
            "status": "ok",
            "version": __version__,
            "worker_running": bool(worker and worker.is_running),
        }

    return app


def render(request: Request, name: str, context: dict | None = None, status_code: int = 200) -> HTMLResponse:
    from ..db import session_scope

    with session_scope(request.app.state.session_factory) as session:
        context = dict(context or {})
        context.setdefault("nav", nav_counts(session))
    context["request"] = request
    return TEMPLATES.TemplateResponse(request=request, name=name, context=context, status_code=status_code)
