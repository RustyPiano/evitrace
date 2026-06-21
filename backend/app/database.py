from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.engine import make_url
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from .config import settings


class Base(DeclarativeBase):
    pass


def _sqlite_connect_args(database_url: str) -> dict[str, bool]:
    url = make_url(database_url)
    if url.drivername.startswith("sqlite"):
        return {"check_same_thread": False}
    return {}


def _ensure_data_paths() -> None:
    settings.data_root_path.mkdir(parents=True, exist_ok=True)

    url = make_url(settings.resolved_database_url)
    if not url.drivername.startswith("sqlite"):
        return

    database = url.database
    if database and database != ":memory:":
        Path(database).parent.mkdir(parents=True, exist_ok=True)


_ensure_data_paths()

engine = create_engine(
    settings.resolved_database_url,
    connect_args=_sqlite_connect_args(settings.resolved_database_url),
)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def initialize_database() -> None:
    from . import models  # noqa: F401

    _ensure_data_paths()
    with engine.begin() as connection:
        Base.metadata.create_all(bind=connection)
