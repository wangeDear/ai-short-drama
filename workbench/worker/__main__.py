from __future__ import annotations

from ..config import settings
from ..db import init_db, make_engine, make_session_factory
from .loop import Worker


def main() -> None:
    settings.ensure_dirs()
    engine = make_engine(settings)
    init_db(engine)
    factory = make_session_factory(engine)
    worker = Worker(factory, settings)
    print(f"workbench worker 启动（db={settings.db_path}），Ctrl+C 退出")
    worker.start()
    try:
        import threading

        while True:
            threading.Event().wait(3600)
    except KeyboardInterrupt:
        worker.stop()
        print("worker 已停止")


if __name__ == "__main__":
    main()
