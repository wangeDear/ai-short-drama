"""一键导入演示数据：旧审核台 forest_fire + outputs/ 下 csr/c3 两组分段视频。"""

from __future__ import annotations

from .config import Settings, settings
from .db import init_db, make_engine, make_session_factory, session_scope
from .models import Project
from .services.importer import import_legacy_studio, scan_videos


def seed(session_factory, settings_obj: Settings) -> list[str]:
    created: list[str] = []
    with session_scope(session_factory) as session:
        existing = {project.name for project in session.query(Project).all()}

        legacy_path = settings_obj.workspace_root / "studio" / "data" / "project.json"
        if legacy_path.exists() and not any("取火" in name for name in existing):
            try:
                project = import_legacy_studio(session, settings_obj, legacy_path)
                created.append(f"{project.name}（{len(project.shots)} 分镜，来自旧审核台）")
            except Exception as exc:  # noqa: BLE001
                created.append(f"旧审核台导入失败: {exc}")

        for prefix, title in (("csr", "财神爷被裁员"), ("c3", "财神 v3 第一幕")):
            if any(prefix in name.lower() or title in name for name in existing):
                continue
            try:
                project = scan_videos(
                    session,
                    settings_obj,
                    settings_obj.workspace_root / "outputs",
                    project_name=title,
                    prefix=prefix,
                )
                created.append(f"{project.name}（{len(project.shots)} 分镜，扫描 outputs/）")
            except Exception as exc:  # noqa: BLE001
                created.append(f"扫描 {prefix} 失败: {exc}")
    return created


def main() -> None:
    settings.ensure_dirs()
    engine = make_engine(settings)
    init_db(engine)
    factory = make_session_factory(engine)
    for line in seed(factory, settings):
        print(line)


if __name__ == "__main__":
    main()
