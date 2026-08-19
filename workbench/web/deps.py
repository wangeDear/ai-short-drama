from __future__ import annotations

from collections.abc import Iterator

from fastapi import Depends, HTTPException, Request
from sqlalchemy.orm import Session

from ..config import Settings
from ..db import session_scope
from ..models import ModelEndpoint, Project, Shot


def get_settings(request: Request) -> Settings:
    return request.app.state.settings


def get_db(request: Request) -> Iterator[Session]:
    with session_scope(request.app.state.session_factory) as session:
        yield session


def load_project(session: Session, project_id: str) -> Project:
    project = session.get(Project, project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="项目不存在")
    return project


def load_shot(session: Session, shot_id: str) -> Shot:
    shot = session.get(Shot, shot_id)
    if shot is None:
        raise HTTPException(status_code=404, detail="分镜不存在")
    return shot


def load_endpoint(session: Session, endpoint_id: str) -> ModelEndpoint:
    endpoint = session.get(ModelEndpoint, endpoint_id)
    if endpoint is None:
        raise HTTPException(status_code=404, detail="生成节点不存在")
    return endpoint
