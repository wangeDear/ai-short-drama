from __future__ import annotations

from ..config import Settings
from ..db import session_scope


class AdapterError(RuntimeError):
    pass


class CancelRequested(RuntimeError):
    pass


class BaseAdapter:
    name = "base"

    def run(self, session_factory, settings: Settings, job_id: str) -> None:  # pragma: no cover - interface
        raise NotImplementedError
