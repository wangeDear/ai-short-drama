from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager

from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from .config import Settings, settings
from .models import Base


def make_engine(settings_obj: Settings) -> Engine:
    settings_obj.db_path.parent.mkdir(parents=True, exist_ok=True)
    engine = create_engine(
        f"sqlite:///{settings_obj.db_path.as_posix()}",
        connect_args={"check_same_thread": False, "timeout": 30},
    )

    @event.listens_for(engine, "connect")
    def _set_sqlite_pragma(dbapi_connection, _record) -> None:  # noqa: ANN001
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA synchronous=NORMAL")
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    return engine


def make_session_factory(engine: Engine) -> sessionmaker[Session]:
    return sessionmaker(bind=engine, expire_on_commit=False, autoflush=False)


_default_engine: Engine | None = None
_default_factory: sessionmaker[Session] | None = None


def get_default_engine() -> Engine:
    global _default_engine, _default_factory
    if _default_engine is None:
        _default_engine = make_engine(settings)
        _default_factory = make_session_factory(_default_engine)
    return _default_engine


def get_default_session_factory() -> sessionmaker[Session]:
    if _default_factory is None:
        get_default_engine()
    assert _default_factory is not None
    return _default_factory


def init_db(engine: Engine | None = None) -> None:
    target = engine or get_default_engine()
    Base.metadata.create_all(target)
    _migrate_columns(target)


def _migrate_columns(engine: Engine) -> None:
    """轻量列迁移：为既有表补充新增列（可重复执行，保留既有数据）。"""
    from sqlalchemy import inspect, text

    inspector = inspect(engine)
    migrations: dict[str, list[tuple[str, str]]] = {
        # 表名 -> [(列名, 列DDL)]
        "projects": [("pipeline_json", "JSON DEFAULT '{}'")],
    }
    with engine.begin() as connection:
        for table, columns in migrations.items():
            if table not in inspector.get_table_names():
                continue
            existing = {column["name"] for column in inspector.get_columns(table)}
            for column_name, ddl in columns:
                if column_name not in existing:
                    connection.execute(text(f"ALTER TABLE {table} ADD COLUMN {column_name} {ddl}"))


@contextmanager
def session_scope(factory: sessionmaker[Session] | None = None) -> Iterator[Session]:
    factory = factory or get_default_session_factory()
    session = factory()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
