"""SQLite connection and schema management."""

from __future__ import annotations

import sqlite3
from contextlib import closing
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS projects (
    project_id TEXT PRIMARY KEY,
    project_name TEXT NOT NULL,
    status TEXT NOT NULL,
    raw_requirement TEXT NOT NULL,
    structured_requirement TEXT NOT NULL,
    task_plan TEXT NOT NULL,
    storyboard TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS executions (
    execution_id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL,
    status TEXT NOT NULL,
    started_at TEXT NOT NULL,
    finished_at TEXT,
    error TEXT,
    FOREIGN KEY (project_id) REFERENCES projects(project_id)
);

CREATE TABLE IF NOT EXISTS execution_traces (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    execution_id TEXT NOT NULL,
    project_id TEXT NOT NULL,
    node_name TEXT NOT NULL,
    tool_name TEXT,
    tool_arguments TEXT,
    input_summary TEXT,
    output_summary TEXT,
    status TEXT NOT NULL,
    error TEXT,
    created_at TEXT NOT NULL,
    FOREIGN KEY (project_id) REFERENCES projects(project_id),
    FOREIGN KEY (execution_id) REFERENCES executions(execution_id)
);

CREATE TABLE IF NOT EXISTS validation_reports (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    execution_id TEXT NOT NULL,
    project_id TEXT NOT NULL,
    report_type TEXT NOT NULL,
    passed INTEGER NOT NULL,
    report_json TEXT NOT NULL,
    created_at TEXT NOT NULL,
    FOREIGN KEY (project_id) REFERENCES projects(project_id),
    FOREIGN KEY (execution_id) REFERENCES executions(execution_id)
);

CREATE TABLE IF NOT EXISTS revision_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    execution_id TEXT NOT NULL,
    project_id TEXT NOT NULL,
    revision_number INTEGER NOT NULL,
    status TEXT NOT NULL,
    reason TEXT NOT NULL,
    details_json TEXT NOT NULL,
    created_at TEXT NOT NULL,
    FOREIGN KEY (project_id) REFERENCES projects(project_id),
    FOREIGN KEY (execution_id) REFERENCES executions(execution_id)
);

CREATE INDEX IF NOT EXISTS idx_traces_project
    ON execution_traces(project_id, id);
CREATE INDEX IF NOT EXISTS idx_reports_project
    ON validation_reports(project_id, id);
CREATE INDEX IF NOT EXISTS idx_revisions_project
    ON revision_history(project_id, id);

CREATE TABLE IF NOT EXISTS creative_sessions (
    session_id TEXT PRIMARY KEY,
    project_id TEXT,
    status TEXT NOT NULL,
    original_idea TEXT NOT NULL,
    state_json TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_creative_sessions_updated
    ON creative_sessions(updated_at DESC);

CREATE TABLE IF NOT EXISTS creative_assets (
    asset_id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    kind TEXT NOT NULL,
    description TEXT NOT NULL,
    attributes_json TEXT NOT NULL,
    rules_json TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_creative_assets_kind
    ON creative_assets(kind, updated_at DESC);

CREATE TABLE IF NOT EXISTS generated_media (
    media_id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL,
    shot_number INTEGER NOT NULL,
    kind TEXT NOT NULL,
    backend TEXT NOT NULL,
    workflow TEXT NOT NULL,
    prompt TEXT NOT NULL,
    file_path TEXT NOT NULL,
    duration_seconds REAL,
    status TEXT NOT NULL,
    error TEXT,
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_generated_media_project
    ON generated_media(project_id, shot_number);
"""


def connect(db_path: str | Path) -> sqlite3.Connection:
    path = Path(db_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(str(path), timeout=30)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    connection.execute("PRAGMA busy_timeout = 5000")
    connection.execute("PRAGMA journal_mode = WAL")
    return connection


def initialize_schema(db_path: str | Path) -> None:
    with closing(connect(db_path)) as connection:
        with connection:
            connection.executescript(SCHEMA)
