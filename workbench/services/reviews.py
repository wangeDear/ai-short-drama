from __future__ import annotations

from sqlalchemy.orm import Session

from ..models import (
    SHOT_STATUS_NEEDS_REVISION,
    Review,
    Shot,
    ShotVersion,
)
from . import versions as versions_service


class ReviewError(ValueError):
    pass


def _record(
    session: Session,
    shot: Shot,
    review_type: str,
    decision: str,
    comment: str = "",
    version_id: str | None = None,
) -> None:
    session.add(
        Review(
            project_id=shot.project_id,
            shot_id=shot.id,
            version_id=version_id,
            review_type=review_type,
            decision=decision,
            comment=comment or "",
        )
    )
    session.flush()


def shot_reviews(session: Session, shot: Shot, limit: int = 30) -> list[Review]:
    from sqlalchemy import select

    return list(
        session.scalars(
            select(Review)
            .where(Review.shot_id == shot.id)
            .order_by(Review.created_at.desc())
            .limit(limit)
        )
    )


def approve_image(session: Session, shot: Shot, comment: str = "", settings=None) -> None:
    image_version = versions_service.latest_version(session, shot, "image")
    if image_version is None or not versions_service.version_assets(session, image_version):
        raise ReviewError("该分镜还没有可审核的分镜图片，请先生成或导入图片")

    # §7-6：更换已批准图片（批准不同版本）→ 依赖该图片的视频过期
    previous_accepted = next(
        (
            version
            for version in shot.versions
            if version.version_type == "image" and version.status == "accepted" and version.id != image_version.id
        ),
        None,
    )
    swapped = previous_accepted is not None
    if swapped:
        previous_accepted.status = "superseded"

    image_version.status = "accepted"
    _record(session, shot, "image", "approved", comment, image_version.id)
    if shot.status not in {"accepted"}:
        shot.status = "image_approved"
    session.flush()

    if swapped:
        from . import dependencies as deps_service

        deps_service.mark_stale_shot(
            session, shot, f"已批准图片更换为 v{image_version.version_number}，依赖视频需重做", scope="video"
        )

    # FR-GATE-002：C 通过后自动排队（按项目配置，只作用于该已批准镜头）
    if settings is not None:
        from ..models import Project

        project = session.get(Project, shot.project_id)
        if project is not None:
            from . import gates as gates_service

            gates_service.maybe_auto_queue_video(session, settings, shot)


def return_image(session: Session, shot: Shot, comment: str = "") -> None:
    image_version = versions_service.latest_version(session, shot, "image")
    _record(session, shot, "image", "returned", comment, image_version.id if image_version else None)
    shot.status = SHOT_STATUS_NEEDS_REVISION
    session.flush()


def approve_audio(session: Session, shot: Shot, comment: str = "") -> None:
    audio_version = versions_service.latest_version(session, shot, "audio")
    if audio_version is None:
        raise ReviewError("该分镜还没有配音版本")
    audio_version.status = "accepted"
    _record(session, shot, "audio", "approved", comment, audio_version.id)
    session.flush()


def select_final_version(session: Session, shot: Shot, version_id: str) -> None:
    version = versions_service.get_version(session, version_id)
    if version is None:
        raise ReviewError("版本不存在")
    versions_service.select_final(session, shot, version)
    session.flush()


def mark_needs_revision(session: Session, shot: Shot, comment: str = "") -> None:
    _record(session, shot, "video", "returned", comment)
    shot.status = SHOT_STATUS_NEEDS_REVISION
    session.flush()


def add_comment(session: Session, shot: Shot, comment: str) -> None:
    if not comment.strip():
        raise ReviewError("备注不能为空")
    shot.notes = (shot.notes or "").rstrip() + ("\n" if shot.notes else "") + comment.strip()
    _record(session, shot, "image", "comment", comment)
    session.flush()
