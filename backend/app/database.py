import logging
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.engine import make_url
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from .config import settings

logger = logging.getLogger(__name__)


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
        if connection.dialect.name == "sqlite":
            _migrate_sqlite_schema(connection)


def _quote_sqlite_identifier(value: str) -> str:
    return '"' + value.replace('"', '""') + '"'


def _sqlite_table_columns(connection, table_name: str) -> set[str]:
    rows = connection.exec_driver_sql(f"PRAGMA table_info({_quote_sqlite_identifier(table_name)})").fetchall()
    return {row[1] for row in rows}


def _sqlite_index_columns(connection, index_name: str) -> list[str]:
    rows = connection.exec_driver_sql(f"PRAGMA index_info({_quote_sqlite_identifier(index_name)})").fetchall()
    return [row[2] for row in rows]


def _analysis_results_has_unique_task_id_index(connection) -> bool:
    try:
        indexes = connection.exec_driver_sql("PRAGMA index_list(analysis_results)").fetchall()
    except Exception as exc:  # pragma: no cover - defensive startup migration
        logger.warning("SQLite migration skipped analysis_results index inspection: %s", type(exc).__name__)
        return False

    for index in indexes:
        name = index[1]
        is_unique = bool(index[2])
        origin = index[3] if len(index) > 3 else None
        if not is_unique:
            continue
        try:
            columns = _sqlite_index_columns(connection, name)
        except Exception as exc:  # pragma: no cover - defensive startup migration
            logger.warning("SQLite migration skipped index column inspection: %s", type(exc).__name__)
            continue
        if columns == ["task_id"] and (origin in {"u", "pk"} or is_unique):
            return True
    return False


def _rebuild_analysis_results_without_legacy_unique(connection) -> None:
    if not _analysis_results_has_unique_task_id_index(connection):
        return

    try:
        from .models import AnalysisResult

        connection.exec_driver_sql("ALTER TABLE analysis_results RENAME TO analysis_results_legacy")
        AnalysisResult.__table__.create(bind=connection)

        legacy_columns = _sqlite_table_columns(connection, "analysis_results_legacy")
        current_columns = [
            row[1]
            for row in connection.exec_driver_sql("PRAGMA table_info(analysis_results)").fetchall()
            if row[1] in legacy_columns
        ]
        if current_columns:
            quoted_columns = ", ".join(_quote_sqlite_identifier(column) for column in current_columns)
            connection.exec_driver_sql(
                f"""
                INSERT INTO analysis_results ({quoted_columns})
                SELECT {quoted_columns}
                FROM analysis_results_legacy
                """
            )
        connection.exec_driver_sql("DROP TABLE analysis_results_legacy")
        logger.info("SQLite migration rebuilt analysis_results without legacy unique task_id constraint")
    except Exception as exc:  # pragma: no cover - defensive startup migration
        logger.warning("SQLite migration could not rebuild analysis_results: %s", type(exc).__name__)


def _migrate_sqlite_schema(connection) -> None:
    try:
        evidence_columns = _sqlite_table_columns(connection, "evidence")
    except Exception as exc:  # pragma: no cover - defensive startup migration
        logger.warning("SQLite migration skipped evidence inspection: %s", type(exc).__name__)
        evidence_columns = set()

    if evidence_columns and "run_id" not in evidence_columns:
        try:
            connection.exec_driver_sql("ALTER TABLE evidence ADD COLUMN run_id TEXT")
            logger.info("SQLite migration added evidence.run_id")
        except Exception as exc:  # pragma: no cover - defensive startup migration
            logger.warning("SQLite migration could not add evidence.run_id: %s", type(exc).__name__)

    try:
        connection.exec_driver_sql(
            """
            UPDATE evidence
            SET run_id = (
                SELECT ar.run_id
                FROM analysis_results ar
                WHERE ar.task_id = evidence.task_id
                ORDER BY ar.created_at DESC
                LIMIT 1
            )
            WHERE run_id IS NULL
            """
        )
        logger.info("SQLite migration backfilled nullable evidence.run_id values")
    except Exception as exc:  # pragma: no cover - defensive startup migration
        logger.warning("SQLite migration skipped evidence.run_id backfill: %s", type(exc).__name__)

    _rebuild_analysis_results_without_legacy_unique(connection)
