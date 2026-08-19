from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import JSON, Boolean, DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


def utcnow() -> datetime:
    """统一使用 naïve UTC（SQLite 读回的 datetime 无时区信息）。"""
    return datetime.now(timezone.utc).replace(tzinfo=None)


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:12]}"


class Base(DeclarativeBase):
    pass


# ---------------------------------------------------------------------------
# 状态常量（FR-JOB-002 / 分镜状态 / 枚举）
# ---------------------------------------------------------------------------

JOB_STATUS_DRAFT = "draft"
JOB_STATUS_WAITING_REVIEW = "waiting_review"
JOB_STATUS_APPROVED = "approved"
JOB_STATUS_QUEUED = "queued"
JOB_STATUS_RUNNING = "running"
JOB_STATUS_REVIEWING = "reviewing"
JOB_STATUS_SUCCEEDED = "succeeded"
JOB_STATUS_ACCEPTED = "accepted"
JOB_STATUS_REVISION = "revision"
JOB_STATUS_FAILED = "failed"
JOB_STATUS_CANCELLED = "cancelled"

JOB_STATUSES = [
    JOB_STATUS_DRAFT,
    JOB_STATUS_WAITING_REVIEW,
    JOB_STATUS_APPROVED,
    JOB_STATUS_QUEUED,
    JOB_STATUS_RUNNING,
    JOB_STATUS_REVIEWING,
    JOB_STATUS_SUCCEEDED,
    JOB_STATUS_ACCEPTED,
    JOB_STATUS_REVISION,
    JOB_STATUS_FAILED,
    JOB_STATUS_CANCELLED,
]

JOB_STATUS_LABELS = {
    JOB_STATUS_DRAFT: "草稿",
    JOB_STATUS_WAITING_REVIEW: "等待审核",
    JOB_STATUS_APPROVED: "已批准",
    JOB_STATUS_QUEUED: "排队中",
    JOB_STATUS_RUNNING: "生成中",
    JOB_STATUS_REVIEWING: "等待结果审核",
    JOB_STATUS_SUCCEEDED: "生成完成",
    JOB_STATUS_ACCEPTED: "已通过",
    JOB_STATUS_REVISION: "需要修改",
    JOB_STATUS_FAILED: "失败",
    JOB_STATUS_CANCELLED: "已取消",
}

JOB_TYPE_IMAGE = "image"
JOB_TYPE_VIDEO = "video"
JOB_TYPE_VOICE = "voice"
JOB_TYPE_AMBIENCE = "ambience"
JOB_TYPE_INPAINT = "inpaint"
JOB_TYPE_ANALYZE = "analyze"
JOB_TYPE_COMPOSE = "compose"
JOB_TYPE_EXPORT = "export"
JOB_TYPE_STORY_PLAN = "story_plan"
JOB_TYPE_SCRIPT = "script"
JOB_TYPE_BIBLE = "bible"
JOB_TYPE_SHOT_PLANS = "shot_plans"

JOB_TYPE_LABELS = {
    JOB_TYPE_IMAGE: "图片生成",
    JOB_TYPE_VIDEO: "视频生成",
    JOB_TYPE_VOICE: "配音生成",
    JOB_TYPE_AMBIENCE: "环境音生成",
    JOB_TYPE_INPAINT: "局部修复",
    JOB_TYPE_ANALYZE: "视频分析与抽帧",
    JOB_TYPE_COMPOSE: "音视频合成",
    JOB_TYPE_EXPORT: "最终成片导出",
    JOB_TYPE_STORY_PLAN: "故事方案生成",
    JOB_TYPE_SCRIPT: "结构化剧本生成",
    JOB_TYPE_BIBLE: "生产设定提取",
    JOB_TYPE_SHOT_PLANS: "分镜与提示词生成",
}

LLM_JOB_TYPES = {JOB_TYPE_STORY_PLAN, JOB_TYPE_SCRIPT, JOB_TYPE_BIBLE, JOB_TYPE_SHOT_PLANS}

# 生成型任务 -> 产物版本类型
JOB_TYPE_VERSION_TYPE = {
    JOB_TYPE_IMAGE: "image",
    JOB_TYPE_INPAINT: "image",
    JOB_TYPE_VIDEO: "video",
    JOB_TYPE_VOICE: "audio",
    JOB_TYPE_AMBIENCE: "ambience",
}

SHOT_STATUS_DRAFT = "draft"
SHOT_STATUS_IMAGE_REVIEW = "image_review"
SHOT_STATUS_IMAGE_APPROVED = "image_approved"
SHOT_STATUS_VIDEO_REVIEW = "video_review"
SHOT_STATUS_NEEDS_REVISION = "needs_revision"
SHOT_STATUS_ACCEPTED = "accepted"

SHOT_STATUSES = [
    SHOT_STATUS_DRAFT,
    SHOT_STATUS_IMAGE_REVIEW,
    SHOT_STATUS_IMAGE_APPROVED,
    SHOT_STATUS_VIDEO_REVIEW,
    SHOT_STATUS_NEEDS_REVISION,
    SHOT_STATUS_ACCEPTED,
]

SHOT_STATUS_LABELS = {
    SHOT_STATUS_DRAFT: "草稿",
    SHOT_STATUS_IMAGE_REVIEW: "待审图片",
    SHOT_STATUS_IMAGE_APPROVED: "图片已批准",
    SHOT_STATUS_VIDEO_REVIEW: "待审视频",
    SHOT_STATUS_NEEDS_REVISION: "需要修改",
    SHOT_STATUS_ACCEPTED: "已通过",
}

VERSION_TYPE_LABELS = {
    "image": "图片",
    "video": "视频",
    "audio": "配音",
    "ambience": "环境音",
}

VERSION_STATUS_LABELS = {
    "draft": "草稿",
    "queued": "排队中",
    "running": "生成中",
    "reviewing": "待审核",
    "accepted": "已采用",
    "superseded": "已被替换",
    "failed": "失败",
}

ASSET_TYPE_LABELS = {
    "image": "分镜图片",
    "video": "分段视频",
    "audio": "配音",
    "ambience": "环境音",
    "reference": "参考图",
    "mask": "遮罩",
    "control": "控制视频",
    "character_ref": "角色参考图",
    "final": "最终成片",
    "cover": "封面",
    "other": "其他",
}

WORKFLOW_CATEGORIES = [
    ("keyframe", "关键帧图片生成"),
    ("h3_t2v", "H3 文生视频"),
    ("h3_i2v", "H3 图生视频"),
    ("ref_video", "参考视频/角色一致性"),
    ("character_swap", "MoCha/Wan Animate 角色替换"),
    ("inpaint", "VACE 局部修补"),
    ("voice", "配音"),
    ("ambience", "环境音"),
    ("ffmpeg", "FFmpeg 合成"),
]
WORKFLOW_CATEGORY_LABELS = dict(WORKFLOW_CATEGORIES)

# 生成任务类型 -> 默认工作流类别
JOB_TYPE_WORKFLOW_CATEGORY = {
    JOB_TYPE_IMAGE: "keyframe",
    JOB_TYPE_VIDEO: "h3_i2v",
    JOB_TYPE_VOICE: "voice",
    JOB_TYPE_AMBIENCE: "ambience",
    JOB_TYPE_INPAINT: "inpaint",
}

REVIEW_DECISIONS = {
    "approved": "批准",
    "returned": "退回修改",
    "comment": "备注",
    "accepted": "采用为最终版",
}


# ---------------------------------------------------------------------------
# ORM 模型（需求 §8）
# ---------------------------------------------------------------------------


class Project(Base):
    __tablename__ = "projects"

    id: Mapped[str] = mapped_column(String(24), primary_key=True, default=lambda: new_id("p"))
    name: Mapped[str] = mapped_column(String(200))
    description: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[str] = mapped_column(String(20), default="active")  # active / archived
    aspect_ratio: Mapped[str] = mapped_column(String(12), default="9:16")
    resolution: Mapped[str] = mapped_column(String(20), default="1216x704")
    fps: Mapped[int] = mapped_column(Integer, default=24)
    root_path: Mapped[str] = mapped_column(String(500), default="")
    cover_asset_id: Mapped[str | None] = mapped_column(String(24), nullable=True)
    pipeline_json: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    shots = relationship(
        "Shot", back_populates="project", order_by="Shot.sequence_index", cascade="all, delete-orphan"
    )

    @property
    def is_archived(self) -> bool:
        return self.status == "archived"


class Shot(Base):
    __tablename__ = "shots"

    id: Mapped[str] = mapped_column(String(24), primary_key=True, default=lambda: new_id("sh"))
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id"), index=True)
    shot_code: Mapped[str] = mapped_column(String(40))
    title: Mapped[str] = mapped_column(String(200), default="")
    description: Mapped[str] = mapped_column(Text, default="")
    sequence_index: Mapped[int] = mapped_column(Integer, default=0)
    duration: Mapped[float] = mapped_column(Float, default=8.0)
    status: Mapped[str] = mapped_column(String(24), default=SHOT_STATUS_DRAFT, index=True)
    selected_version_id: Mapped[str | None] = mapped_column(String(24), nullable=True)
    scene: Mapped[str] = mapped_column(String(120), default="")
    characters: Mapped[str] = mapped_column(String(300), default="")
    image_prompt: Mapped[str] = mapped_column(Text, default="")
    image_negative: Mapped[str] = mapped_column(Text, default="")
    video_prompt: Mapped[str] = mapped_column(Text, default="")
    video_negative: Mapped[str] = mapped_column(Text, default="")
    voice_text: Mapped[str] = mapped_column(Text, default="")
    ambience_text: Mapped[str] = mapped_column(Text, default="")
    notes: Mapped[str] = mapped_column(Text, default="")
    params_json: Mapped[dict] = mapped_column(JSON, default=dict)
    workflow_template_id: Mapped[str | None] = mapped_column(String(24), nullable=True)
    endpoint_id: Mapped[str | None] = mapped_column(String(24), nullable=True)
    seed: Mapped[int | None] = mapped_column(Integer, nullable=True)
    video_config_stale: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)

    project = relationship("Project", back_populates="shots")
    versions = relationship(
        "ShotVersion",
        back_populates="shot",
        order_by="[ShotVersion.version_type, ShotVersion.version_number]",
        cascade="all, delete-orphan",
    )

    @property
    def character_list(self) -> list[str]:
        return [item.strip() for item in self.characters.replace("，", ",").split(",") if item.strip()]


class ShotVersion(Base):
    __tablename__ = "shot_versions"

    id: Mapped[str] = mapped_column(String(24), primary_key=True, default=lambda: new_id("sv"))
    shot_id: Mapped[str] = mapped_column(ForeignKey("shots.id"), index=True)
    version_number: Mapped[int] = mapped_column(Integer, default=1)
    version_type: Mapped[str] = mapped_column(String(16), default="video")  # image/video/audio/ambience
    status: Mapped[str] = mapped_column(String(16), default="draft")
    prompt_snapshot: Mapped[dict] = mapped_column(JSON, default=dict)
    parameter_snapshot: Mapped[dict] = mapped_column(JSON, default=dict)
    workflow_template_id: Mapped[str | None] = mapped_column(String(24), nullable=True)
    workflow_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    seed: Mapped[int | None] = mapped_column(Integer, nullable=True)
    source: Mapped[str] = mapped_column(String(16), default="generated")  # generated / imported
    created_by_job_id: Mapped[str | None] = mapped_column(String(24), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    shot = relationship("Shot", back_populates="versions")
    assets = relationship("Asset", back_populates="version", cascade="all, delete-orphan")


class Asset(Base):
    __tablename__ = "assets"

    id: Mapped[str] = mapped_column(String(24), primary_key=True, default=lambda: new_id("a"))
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id"), index=True)
    shot_id: Mapped[str | None] = mapped_column(String(24), nullable=True, index=True)
    version_id: Mapped[str | None] = mapped_column(ForeignKey("shot_versions.id"), nullable=True, index=True)
    character_id: Mapped[str | None] = mapped_column(String(24), nullable=True)
    asset_type: Mapped[str] = mapped_column(String(20), default="other", index=True)
    file_path: Mapped[str] = mapped_column(String(600))  # 相对 workspace 的 posix 路径
    original_filename: Mapped[str] = mapped_column(String(300), default="")
    mime_type: Mapped[str] = mapped_column(String(100), default="")
    size_bytes: Mapped[int] = mapped_column(Integer, default=0)
    width: Mapped[int | None] = mapped_column(Integer, nullable=True)
    height: Mapped[int | None] = mapped_column(Integer, nullable=True)
    duration: Mapped[float | None] = mapped_column(Float, nullable=True)
    fps: Mapped[float | None] = mapped_column(Float, nullable=True)
    file_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    metadata_json: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    version = relationship("ShotVersion", back_populates="assets")


class GenerationJob(Base):
    __tablename__ = "generation_jobs"

    id: Mapped[str] = mapped_column(String(24), primary_key=True, default=lambda: new_id("job"))
    project_id: Mapped[str | None] = mapped_column(String(24), nullable=True, index=True)
    shot_id: Mapped[str | None] = mapped_column(String(24), nullable=True, index=True)
    version_id: Mapped[str | None] = mapped_column(String(24), nullable=True, index=True)
    job_type: Mapped[str] = mapped_column(String(16), default=JOB_TYPE_VIDEO, index=True)
    status: Mapped[str] = mapped_column(String(16), default=JOB_STATUS_QUEUED, index=True)
    priority: Mapped[int] = mapped_column(Integer, default=0)
    endpoint_id: Mapped[str | None] = mapped_column(String(24), nullable=True)
    endpoint_name: Mapped[str] = mapped_column(String(120), default="")
    external_job_id: Mapped[str | None] = mapped_column(String(120), nullable=True)
    progress: Mapped[int] = mapped_column(Integer, default=0)
    current_step: Mapped[str] = mapped_column(String(200), default="")
    request_snapshot: Mapped[dict] = mapped_column(JSON, default=dict)
    error_message: Mapped[str] = mapped_column(Text, default="")
    log_path: Mapped[str] = mapped_column(String(500), default="")
    attempt: Mapped[int] = mapped_column(Integer, default=1)
    queued_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_heartbeat_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class WorkflowTemplate(Base):
    __tablename__ = "workflow_templates"

    id: Mapped[str] = mapped_column(String(24), primary_key=True, default=lambda: new_id("wf"))
    name: Mapped[str] = mapped_column(String(200))
    category: Mapped[str] = mapped_column(String(30), default="keyframe", index=True)
    description: Mapped[str] = mapped_column(Text, default="")
    workflow_json: Mapped[dict] = mapped_column(JSON, default=dict)
    parameter_mapping_json: Mapped[dict] = mapped_column(JSON, default=dict)
    required_models_json: Mapped[list] = mapped_column(JSON, default=list)
    enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class ModelEndpoint(Base):
    __tablename__ = "model_endpoints"

    id: Mapped[str] = mapped_column(String(24), primary_key=True, default=lambda: new_id("ep"))
    name: Mapped[str] = mapped_column(String(120))
    endpoint_type: Mapped[str] = mapped_column(String(20), default="comfyui")  # comfyui / mock
    base_url: Mapped[str] = mapped_column(String(400), default="")
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    status: Mapped[str] = mapped_column(String(16), default="unknown")  # unknown / online / offline
    gpu_info: Mapped[str] = mapped_column(String(300), default="")
    queue_length: Mapped[int] = mapped_column(Integer, default=0)
    capabilities_json: Mapped[dict] = mapped_column(JSON, default=dict)
    last_heartbeat_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class Character(Base):
    __tablename__ = "characters"

    id: Mapped[str] = mapped_column(String(24), primary_key=True, default=lambda: new_id("ch"))
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id"), index=True)
    name: Mapped[str] = mapped_column(String(120))
    description: Mapped[str] = mapped_column(Text, default="")
    prompt_fragment: Mapped[str] = mapped_column(Text, default="")
    voice_config_json: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class Review(Base):
    __tablename__ = "reviews"

    id: Mapped[str] = mapped_column(String(24), primary_key=True, default=lambda: new_id("rv"))
    project_id: Mapped[str | None] = mapped_column(String(24), nullable=True, index=True)
    shot_id: Mapped[str | None] = mapped_column(String(24), nullable=True, index=True)
    version_id: Mapped[str | None] = mapped_column(String(24), nullable=True)
    review_type: Mapped[str] = mapped_column(String(16), default="image")  # image/video/audio/final
    decision: Mapped[str] = mapped_column(String(16), default="comment")
    comment: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


# ---------------------------------------------------------------------------
# v0.3 创作链路实体（需求 §8.10～8.16）
# ---------------------------------------------------------------------------

GATE_A = "A"
GATE_B = "B"
GATE_C = "C"
GATE_D = "D"
GATE_LABELS = {GATE_A: "剧本审核", GATE_B: "生产包审核", GATE_C: "图片审核", GATE_D: "视频审核"}

# 结构化版本通用状态
STRUCT_VERSION_STATUSES = ["generating", "reviewing", "approved", "revision", "failed", "superseded"]
STRUCT_VERSION_STATUS_LABELS = {
    "generating": "生成中",
    "reviewing": "待审核",
    "approved": "已批准",
    "revision": "已退回",
    "failed": "失败",
    "superseded": "已被替换",
}


class CreativeBriefVersion(Base):
    """创意简报版本（§8.10 / FR-CREATIVE-001）。修改产生新版本，不覆盖。"""

    __tablename__ = "creative_brief_versions"

    id: Mapped[str] = mapped_column(String(24), primary_key=True, default=lambda: new_id("cb"))
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id"), index=True)
    version_number: Mapped[int] = mapped_column(Integer, default=1)
    source_text: Mapped[str] = mapped_column(Text, default="")
    constraints_json: Mapped[dict] = mapped_column(JSON, default=dict)
    inferred_fields_json: Mapped[dict] = mapped_column(JSON, default=dict)
    content_hash: Mapped[str] = mapped_column(String(64), default="")
    status: Mapped[str] = mapped_column(String(16), default="draft")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class StoryScriptVersion(Base):
    """故事方案/剧本版本（§8.11 / FR-CREATIVE-002）。version_type 区分两步。"""

    __tablename__ = "story_and_script_versions"

    id: Mapped[str] = mapped_column(String(24), primary_key=True, default=lambda: new_id("ss"))
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id"), index=True)
    parent_version_id: Mapped[str | None] = mapped_column(String(24), nullable=True)
    created_by_job_id: Mapped[str | None] = mapped_column(String(24), nullable=True)
    version_type: Mapped[str] = mapped_column(String(16), default="story_plan", index=True)
    schema_version: Mapped[str] = mapped_column(String(16), default="")
    structured_content_json: Mapped[dict] = mapped_column(JSON, default=dict)
    raw_model_output: Mapped[str] = mapped_column(Text, default="")
    model_snapshot_json: Mapped[dict] = mapped_column(JSON, default=dict)
    prompt_template_version: Mapped[str] = mapped_column(String(16), default="")
    content_hash: Mapped[str] = mapped_column(String(64), default="")
    status: Mapped[str] = mapped_column(String(16), default="generating", index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Scene(Base):
    """剧本场景（§8.12）。镜表与失效按场景范围传播。"""

    __tablename__ = "scenes"

    id: Mapped[str] = mapped_column(String(24), primary_key=True, default=lambda: new_id("sc"))
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id"), index=True)
    script_version_id: Mapped[str | None] = mapped_column(String(24), nullable=True, index=True)
    scene_code: Mapped[str] = mapped_column(String(40), default="")
    sequence_index: Mapped[int] = mapped_column(Integer, default=0)
    title: Mapped[str] = mapped_column(String(200), default="")
    structured_content_json: Mapped[dict] = mapped_column(JSON, default=dict)
    duration: Mapped[float] = mapped_column(Float, default=0.0)
    status: Mapped[str] = mapped_column(String(16), default="reviewing")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class ProductionBibleVersion(Base):
    """生产设定版本（§8.13 / FR-CREATIVE-003）。批准后锁定，修改产生新版本。"""

    __tablename__ = "production_bible_versions"

    id: Mapped[str] = mapped_column(String(24), primary_key=True, default=lambda: new_id("pb"))
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id"), index=True)
    script_version_id: Mapped[str | None] = mapped_column(String(24), nullable=True)
    created_by_job_id: Mapped[str | None] = mapped_column(String(24), nullable=True)
    version_number: Mapped[int] = mapped_column(Integer, default=1)
    global_style_json: Mapped[dict] = mapped_column(JSON, default=dict)
    characters_json: Mapped[list] = mapped_column(JSON, default=list)
    scenes_json: Mapped[list] = mapped_column(JSON, default=list)
    props_json: Mapped[list] = mapped_column(JSON, default=list)
    continuity_json: Mapped[list] = mapped_column(JSON, default=list)
    content_hash: Mapped[str] = mapped_column(String(64), default="")
    status: Mapped[str] = mapped_column(String(16), default="generating", index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class PromptPackage(Base):
    """分镜结构化提示词包（§8.14 / FR-CREATIVE-004）。图片/视频/声音三包独立。"""

    __tablename__ = "prompt_packages"

    id: Mapped[str] = mapped_column(String(24), primary_key=True, default=lambda: new_id("pp"))
    shot_id: Mapped[str] = mapped_column(ForeignKey("shots.id"), index=True)
    version_number: Mapped[int] = mapped_column(Integer, default=1)
    image_prompt_json: Mapped[dict] = mapped_column(JSON, default=dict)
    video_prompt_json: Mapped[dict] = mapped_column(JSON, default=dict)
    audio_prompt_json: Mapped[dict] = mapped_column(JSON, default=dict)
    required_references_json: Mapped[list] = mapped_column(JSON, default=list)
    risk_tags_json: Mapped[list] = mapped_column(JSON, default=list)
    route_suggestion_json: Mapped[dict] = mapped_column(JSON, default=dict)
    template_version: Mapped[str] = mapped_column(String(16), default="")
    content_hash: Mapped[str] = mapped_column(String(64), default="")
    status: Mapped[str] = mapped_column(String(16), default="reviewing")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class ApprovalGate(Base):
    """人工卡点决定记录（§8.15 / FR-GATE-002）。C/D 的逐镜决定沿用 reviews 表。"""

    __tablename__ = "approval_gates"

    id: Mapped[str] = mapped_column(String(24), primary_key=True, default=lambda: new_id("gt"))
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id"), index=True)
    gate_type: Mapped[str] = mapped_column(String(8), default=GATE_A, index=True)
    scope_type: Mapped[str] = mapped_column(String(16), default="project")  # project/scene/shot
    scope_id: Mapped[str | None] = mapped_column(String(24), nullable=True)
    input_version_refs_json: Mapped[dict] = mapped_column(JSON, default=dict)
    decision: Mapped[str] = mapped_column(String(16), default="waiting_review")
    comment: Mapped[str] = mapped_column(Text, default="")
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class DependencyEdge(Base):
    """依赖图与内容指纹（§8.16 / §7）。上游变化后下游标记 stale 而不是删除。"""

    __tablename__ = "dependencies"

    id: Mapped[str] = mapped_column(String(24), primary_key=True, default=lambda: new_id("dep"))
    project_id: Mapped[str | None] = mapped_column(String(24), nullable=True, index=True)
    upstream_type: Mapped[str] = mapped_column(String(24), default="")
    upstream_id: Mapped[str] = mapped_column(String(24), default="")
    upstream_hash: Mapped[str] = mapped_column(String(64), default="")
    downstream_type: Mapped[str] = mapped_column(String(24), default="")
    downstream_id: Mapped[str] = mapped_column(String(24), default="")
    dependency_kind: Mapped[str] = mapped_column(String(24), default="derived")
    stale_reason: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)
