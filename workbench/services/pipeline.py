from __future__ import annotations

"""生产流水线卡点视图：五个关键节点，节点之间必须人工审核推进。

① 提示词审核（剧本解析后人工润色）
② 图片审核（批量生图 → 人工批量批准）
③ 视频生成（图已批准 → 人工批量提交）
④ 视频审核（逐镜人工采用最终版）
⑤ 成片合成（人工确认提交）
"""

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import Project, Shot

INFLIGHT = {"queued", "running"}


def _latest(versions, version_type: str):
    items = [v for v in versions if v.version_type == version_type]
    return items[-1] if items else None


class Stage:
    def __init__(self, key: str, title: str, hint: str) -> None:
        self.key = key
        self.title = title
        self.hint = hint
        self.shots: list[Shot] = []

    @property
    def count(self) -> int:
        return len(self.shots)

    @property
    def ids(self) -> list[str]:
        return [shot.id for shot in self.shots]


def pipeline_stages(session: Session, project: Project) -> list[Stage]:
    shots = list(
        session.scalars(
            select(Shot).where(Shot.project_id == project.id).order_by(Shot.sequence_index)
        )
    )
    versions_by_shot = {shot.id: list(shot.versions) for shot in shots}

    prompt_empty = Stage("prompt", "① 提示词审核", "剧本已解析；提示词为空的分镜需人工补写/润色")
    image_todo = Stage("image_todo", "② 生成分镜图", "提示词就绪、尚无分镜图的分镜（人工点击批量生图）")
    image_inflight = Stage("image_inflight", "② 图片生成中", "等待生成完成，自动进入待审")
    image_pending = Stage("image_pending", "② 图片待人工审核", "已生成的分镜图需逐张/批量批准")
    video_ready = Stage("video_ready", "③ 提交视频生成", "图片已批准、尚未生成视频（人工批量提交）")
    video_inflight = Stage("video_inflight", "③ 视频生成中", "等待生成完成")
    video_pending = Stage("video_pending", "④ 视频待人工采用", "已有视频候选，逐镜对比并采用最终版")
    selected = Stage("selected", "⑤ 可合成", "已选定最终版本")

    for shot in shots:
        versions = versions_by_shot[shot.id]
        image = _latest(versions, "image")
        video = _latest(versions, "video")

        if not ((shot.image_prompt or "").strip() or (shot.video_prompt or "").strip()):
            prompt_empty.shots.append(shot)

        if image is None:
            if (shot.image_prompt or "").strip():
                image_todo.shots.append(shot)
        elif image.status in INFLIGHT:
            image_inflight.shots.append(shot)
        elif image.status != "accepted":
            image_pending.shots.append(shot)

        if shot.selected_version_id:
            selected.shots.append(shot)
        elif video is not None and video.status in INFLIGHT:
            video_inflight.shots.append(shot)
        elif video is not None:
            video_pending.shots.append(shot)
        elif image is not None and image.status == "accepted" and (
            (shot.video_prompt or shot.image_prompt or "").strip()
        ):
            video_ready.shots.append(shot)

    return [
        prompt_empty,
        image_todo,
        image_inflight,
        image_pending,
        video_ready,
        video_inflight,
        video_pending,
        selected,
    ]


def compose_readiness(session: Session, project: Project) -> dict:
    from .final import readiness

    return readiness(session, project)
