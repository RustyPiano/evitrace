from sqlalchemy import create_engine, text

from app import database


def test_initialize_database_migrates_legacy_sqlite_schema(tmp_path, monkeypatch):
    db_path = tmp_path / "legacy.db"
    legacy_engine = create_engine(f"sqlite:///{db_path}")
    with legacy_engine.begin() as connection:
        connection.execute(
            text(
                """
                CREATE TABLE users (
                    id TEXT PRIMARY KEY,
                    username TEXT NOT NULL,
                    password_hash TEXT NOT NULL,
                    role TEXT NOT NULL,
                    is_active BOOLEAN NOT NULL,
                    created_at DATETIME NOT NULL,
                    updated_at DATETIME NOT NULL
                )
                """
            )
        )
        connection.execute(
            text(
                """
                CREATE TABLE tasks (
                    id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    objective TEXT NOT NULL,
                    owner_id TEXT NOT NULL,
                    status TEXT NOT NULL,
                    created_at DATETIME NOT NULL,
                    updated_at DATETIME NOT NULL
                )
                """
            )
        )
        connection.execute(
            text(
                """
                CREATE TABLE task_runs (
                    id TEXT PRIMARY KEY,
                    task_id TEXT NOT NULL,
                    status TEXT NOT NULL,
                    plan_json TEXT NOT NULL,
                    progress INTEGER NOT NULL,
                    warnings_json TEXT NOT NULL
                )
                """
            )
        )
        connection.execute(
            text(
                """
                CREATE TABLE task_files (
                    id TEXT PRIMARY KEY,
                    task_id TEXT NOT NULL,
                    original_name TEXT NOT NULL,
                    stored_name TEXT NOT NULL,
                    extension TEXT NOT NULL,
                    size_bytes INTEGER NOT NULL,
                    modality TEXT NOT NULL,
                    status TEXT NOT NULL,
                    created_at DATETIME NOT NULL
                )
                """
            )
        )
        connection.execute(
            text(
                """
                INSERT INTO task_runs (id, task_id, status, plan_json, progress, warnings_json)
                VALUES ('run-1', 'task-1', 'succeeded', '{}', 100, '[]')
                """
            )
        )
        connection.execute(
            text(
                """
                CREATE TABLE evidence (
                    id TEXT PRIMARY KEY,
                    display_id TEXT NOT NULL,
                    task_id TEXT NOT NULL,
                    file_id TEXT NOT NULL,
                    modality TEXT NOT NULL,
                    evidence_type TEXT NOT NULL,
                    content TEXT NOT NULL,
                    locator_json TEXT NOT NULL,
                    skill_id TEXT NOT NULL,
                    created_at DATETIME NOT NULL,
                    CONSTRAINT uq_evidence_task_display_id UNIQUE (task_id, display_id)
                )
                """
            )
        )
        connection.execute(
            text(
                """
                CREATE TABLE analysis_results (
                    id TEXT PRIMARY KEY,
                    task_id TEXT NOT NULL UNIQUE,
                    run_id TEXT NOT NULL,
                    entities_json TEXT NOT NULL,
                    events_json TEXT NOT NULL,
                    timeline_json TEXT NOT NULL,
                    conflicts_json TEXT NOT NULL,
                    citation_check_json TEXT NOT NULL,
                    created_at DATETIME NOT NULL,
                    updated_at DATETIME NOT NULL
                )
                """
            )
        )
        connection.execute(
            text(
                """
                INSERT INTO analysis_results (
                    id, task_id, run_id, entities_json, events_json, timeline_json,
                    conflicts_json, citation_check_json, created_at, updated_at
                )
                VALUES ('result-1', 'task-1', 'run-1', '[]', '[]', '[]', '[]', '{}', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
                """
            )
        )
        connection.execute(
            text(
                """
                INSERT INTO evidence (
                    id, display_id, task_id, file_id, modality, evidence_type,
                    content, locator_json, skill_id, created_at
                )
                VALUES ('evidence-1', 'E-0001', 'task-1', 'file-1', 'text', 'paragraph', 'old', '{}', 'document_parse', CURRENT_TIMESTAMP)
                """
            )
        )

    monkeypatch.setattr(database, "engine", legacy_engine)

    database.initialize_database()

    with legacy_engine.begin() as connection:
        evidence_columns = {row[1] for row in connection.execute(text("PRAGMA table_info(evidence)"))}
        task_run_columns = {row[1] for row in connection.execute(text("PRAGMA table_info(task_runs)"))}
        indexes = connection.execute(text("PRAGMA index_list(analysis_results)")).fetchall()
        assert "run_id" in evidence_columns
        assert "cancel_requested" in task_run_columns
        assert not any(row[2] and connection.execute(text(f"PRAGMA index_info({row[1]})")).fetchall()[0][2] == "task_id" for row in indexes)
        assert connection.execute(text("SELECT run_id FROM evidence WHERE id='evidence-1'")).scalar() == "run-1"
        assert connection.execute(text("SELECT cancel_requested FROM task_runs WHERE id='run-1'")).scalar() == 0
        assert connection.execute(text("SELECT id FROM analysis_results WHERE id='result-1'")).scalar() == "result-1"
        connection.execute(
            text(
                """
                INSERT INTO analysis_results (
                    id, task_id, run_id, entities_json, events_json, timeline_json,
                    conflicts_json, citation_check_json, created_at, updated_at
                )
                VALUES ('result-2', 'task-1', 'run-2', '[]', '[]', '[]', '[]', '{}', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
                """
            )
        )
