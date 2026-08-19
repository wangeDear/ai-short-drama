from __future__ import annotations

from .config import settings
from .web.main import create_app


def main() -> None:
    import uvicorn

    app = create_app(settings)
    print(f"AI 短剧生成审核工作台已启动: http://{settings.host}:{settings.port}")
    uvicorn.run(app, host=settings.host, port=settings.port, log_level="info")


if __name__ == "__main__":
    main()
