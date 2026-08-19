from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

WORKBENCH_ROOT = Path(__file__).resolve().parent
DEFAULT_WORKSPACE_ROOT = WORKBENCH_ROOT.parent

_TRUTHY = {"1", "true", "yes", "on"}


def config_path() -> Path:
    return Path(os.environ.get("WORKBENCH_CONFIG", WORKBENCH_ROOT / "config.json"))


def _load_config_file() -> dict[str, Any]:
    path = config_path()
    if path.exists():
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            return data if isinstance(data, dict) else {}
        except (OSError, ValueError):
            return {}
    return {}


LLM_CONFIG_KEYS = (
    "llm_type",
    "llm_base_url",
    "llm_model",
    "llm_api_key",
    "llm_timeout_seconds",
    "llm_max_repair",
)


def save_llm_config(values: dict[str, Any]) -> Path:
    """保存 LLM 配置：合并写入 config.json（保留其它键），供设置页在线修改。

    values 中键为 LLM_CONFIG_KEYS 子集；值为 None 表示删除该键（恢复默认/环境变量），
    键缺席表示不改动文件中的现有值。写入为同目录临时文件 + 原子替换；
    现有文件损坏时抛 ValueError 拒绝合并，防止覆盖丢失其它键。
    """
    path = config_path()
    data: dict[str, Any] = {}
    if path.exists():
        loaded = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(loaded, dict):
            raise ValueError("config.json 根结构不是对象，为防覆盖丢失拒绝合并，请人工修复")
        data = loaded
    for key in LLM_CONFIG_KEYS:
        if key not in values:
            continue
        if values[key] is None:
            data.pop(key, None)
        else:
            data[key] = values[key]
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_suffix(path.suffix + ".tmp")
    tmp_path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(tmp_path, path)
    return path


class Settings:
    """运行配置：workbench/config.json > WORKBENCH_* 环境变量 > 默认值。"""

    def __init__(self, overrides: dict[str, Any] | None = None) -> None:
        raw = _load_config_file()
        if overrides:
            raw = {**raw, **overrides}

        def pick(key: str, default: Any) -> Any:
            if key in raw and raw[key] is not None:
                return raw[key]
            return os.environ.get("WORKBENCH_" + key.upper(), default)

        self.workspace_root = Path(str(pick("workspace_root", DEFAULT_WORKSPACE_ROOT))).resolve()
        self.data_dir = Path(str(pick("data_dir", WORKBENCH_ROOT / "data"))).resolve()
        self.db_path = Path(str(pick("db_path", self.data_dir / "workbench.db"))).resolve()
        self.thumbs_dir = self.data_dir / "thumbs"
        self.joblogs_dir = self.data_dir / "joblogs"
        self.projects_root = self.workspace_root / "projects"

        self.host = str(pick("host", "127.0.0.1"))
        self.port = int(pick("port", 8770))
        self.worker_enabled = str(pick("worker_enabled", "true")).lower() in _TRUTHY
        self.worker_concurrency = max(1, int(pick("worker_concurrency", 1)))
        self.poll_interval = float(pick("poll_interval", 2.0))
        self.stale_job_minutes = int(pick("stale_job_minutes", 15))
        self.comfy_timeout_seconds = float(pick("comfy_timeout_seconds", 8.0))
        self.comfy_max_wait_minutes = int(pick("comfy_max_wait_minutes", 180))
        self.ffmpeg_bin = str(pick("ffmpeg_bin", "ffmpeg"))
        self.ffprobe_bin = str(pick("ffprobe_bin", "ffprobe"))
        self.htmx_url = str(
            pick("htmx_url", "https://cdn.jsdelivr.net/npm/htmx.org@2.0.4/dist/htmx.min.js")
        )

        # 文本模型（v0.3 §10.5）：mock 为离线确定性演示；openai 为 OpenAI-compatible 接口
        self.llm_type = str(pick("llm_type", "mock"))
        self.llm_base_url = str(pick("llm_base_url", "")).rstrip("/")
        self.llm_api_key = str(pick("llm_api_key", os.environ.get("WORKBENCH_LLM_API_KEY", "")))
        self.llm_model = str(pick("llm_model", ""))
        self.llm_timeout_seconds = float(pick("llm_timeout_seconds", 180.0))
        self.llm_max_repair = max(0, int(pick("llm_max_repair", 2)))

    def ensure_dirs(self) -> None:
        for path in (self.data_dir, self.thumbs_dir, self.joblogs_dir, self.projects_root):
            path.mkdir(parents=True, exist_ok=True)


settings = Settings()
