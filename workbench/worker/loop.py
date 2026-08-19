from __future__ import annotations

import threading
import time
from datetime import timedelta

from sqlalchemy import select, update
from sqlalchemy.orm import sessionmaker

from ..adapters import COMFY_JOB_TYPES, dispatch
from ..config import Settings
from ..db import session_scope
from ..models import (
    JOB_STATUS_QUEUED,
    JOB_STATUS_RUNNING,
    GenerationJob,
    ModelEndpoint,
    utcnow,
)
from ..services import jobs as jobs_service
from ..services.endpoints import check_endpoint


class Worker:
    """基于数据库队列的后台 Worker（FR-JOB-003）。

    - 浏览器关闭/刷新/切换项目不影响任务；
    - 心跳超时任务可恢复；
    - ComfyUI 离线时任务保留在队列中。
    """

    def __init__(self, session_factory: sessionmaker, settings: Settings, concurrency: int | None = None) -> None:
        self.session_factory = session_factory
        self.settings = settings
        self.concurrency = concurrency or settings.worker_concurrency
        self._stop = threading.Event()
        self._threads: list[threading.Thread] = []
        self._last_recover = 0.0
        self._endpoint_checks: dict[str, float] = {}
        self._lock = threading.Lock()

    # ------------------------------------------------------------- control
    @property
    def is_running(self) -> bool:
        return any(thread.is_alive() for thread in self._threads)

    def start(self) -> None:
        self._recover_on_boot()
        for index in range(self.concurrency):
            thread = threading.Thread(
                target=self._loop, name=f"workbench-worker-{index}", daemon=True
            )
            thread.start()
            self._threads.append(thread)

    def stop(self, timeout: float = 5.0) -> None:
        self._stop.set()
        for thread in self._threads:
            thread.join(timeout=timeout)
        self._threads.clear()

    def _loop(self) -> None:  # pragma: no cover - threaded
        while not self._stop.is_set():
            try:
                claimed = run_once(self.session_factory, self.settings, worker=self)
            except Exception:
                claimed = False
                time.sleep(self.settings.poll_interval)
            if not claimed:
                self._stop.wait(self.settings.poll_interval)

    # ------------------------------------------------------------- boot
    def _recover_on_boot(self) -> None:
        # 只做 stale 判定。不覆盖 running 任务的 current_step / 心跳：
        # - 覆盖会抹掉用户的"请求取消"标志；
        # - 刷新心跳会让孤儿任务（重启后无执行体）伪装成活跃，延长卡死时间。
        # 真正的恢复由 recover_stale（心跳超时→failed/cancelled）与用户取消兜底。
        with session_scope(self.session_factory) as session:
            jobs_service.recover_stale(session, self.settings.stale_job_minutes)

    # ------------------------------------------------------------- claim
    def _endpoint_available(self, endpoint_id: str | None, endpoint_info: dict) -> bool:
        endpoint_id = endpoint_id or endpoint_info.get("id")
        if endpoint_info.get("type") == "mock":
            return True
        if not endpoint_id or not endpoint_info.get("base_url"):
            return False
        now = time.monotonic()
        with self._lock:
            last = self._endpoint_checks.get(endpoint_id, 0.0)
            if now - last < 30.0:
                return endpoint_info.get("status") != "offline"
            self._endpoint_checks[endpoint_id] = now
        with session_scope(self.session_factory) as session:
            endpoint = session.get(ModelEndpoint, endpoint_id)
            if endpoint is None:
                return False
            try:
                check_endpoint(session, self.settings, endpoint)
                session.commit()
                return endpoint.status == "online"
            except Exception:
                return False

    def claim_next(self) -> tuple[str, bool] | None:
        """领取一个排队任务；返回 (job_id, claimed)。claimed=False 表示需等待。"""
        self._maybe_recover()
        with session_scope(self.session_factory) as session:
            candidates = list(
                session.scalars(
                    select(GenerationJob)
                    .where(GenerationJob.status == JOB_STATUS_QUEUED)
                    .order_by(GenerationJob.priority.desc(), GenerationJob.queued_at.asc())
                    .limit(20)
                )
            )
            if not candidates:
                return None
            for job in candidates:
                if job.job_type in COMFY_JOB_TYPES:
                    endpoint_info = (job.request_snapshot or {}).get("endpoint") or {}
                    if not endpoint_info.get("base_url") and not job.endpoint_id:
                        job.current_step = "等待生成节点（未配置 ComfyUI 地址）"
                        session.commit()
                        continue
                    if not self._endpoint_available(job.endpoint_id, endpoint_info):
                        job.current_step = "生成节点离线，任务保留在队列"
                        session.commit()
                        continue
                result = session.execute(
                    update(GenerationJob)
                    .where(GenerationJob.id == job.id, GenerationJob.status == JOB_STATUS_QUEUED)
                    .values(
                        status=JOB_STATUS_RUNNING,
                        started_at=utcnow(),
                        last_heartbeat_at=utcnow(),
                        current_step="启动中",
                    )
                )
                if result.rowcount == 1:
                    session.commit()
                    return job.id, True
        return None

    def _maybe_recover(self) -> None:
        now = time.monotonic()
        if now - self._last_recover < 60.0:
            return
        self._last_recover = now
        with session_scope(self.session_factory) as session:
            jobs_service.recover_stale(session, self.settings.stale_job_minutes)


def run_once(session_factory: sessionmaker, settings: Settings, worker: Worker | None = None) -> bool:
    """同步处理一个排队任务（供测试与单步执行使用）。返回是否有任务被处理。"""
    if worker is None:
        worker = Worker(session_factory, settings, concurrency=0)
    claimed = worker.claim_next()
    if claimed is None:
        return False
    job_id, ok = claimed
    if not ok:
        return False
    dispatch(session_factory, settings, job_id)
    return True
