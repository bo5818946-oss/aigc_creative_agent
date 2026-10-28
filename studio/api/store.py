"""SQLite storage for the standalone studio.

The new app keeps its own tables in ``studio/data/lumen.sqlite3``. It never
touches the legacy Streamlit database, so the old workbench remains runnable
side by side.
"""

from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator
from uuid import uuid4

from studio.api import config
from studio.api.models import (
    Plan,
    ProjectList,
    ProjectRecord,
    ProjectResponse,
    RenderRecord,
    UploadRecord,
    utc_now,
)

SCHEMA = """
CREATE TABLE IF NOT EXISTS studio_projects (
    project_id TEXT PRIMARY KEY,
    title TEXT NOT NULL,
    mode TEXT NOT NULL,
    route TEXT NOT NULL,
    brief TEXT NOT NULL,
    plan_json TEXT NOT NULL,
    reference_id TEXT,
    status TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS studio_renders (
    render_id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL,
    shot_index INTEGER NOT NULL,
    status TEXT NOT NULL,
    file_url TEXT NOT NULL DEFAULT '',
    file_path TEXT NOT NULL DEFAULT '',
    error TEXT NOT NULL DEFAULT '',
    prompt_id TEXT NOT NULL DEFAULT '',
    width INTEGER NOT NULL DEFAULT 0,
    height INTEGER NOT NULL DEFAULT 0,
    started_at TEXT,
    finished_at TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE (project_id, shot_index),
    FOREIGN KEY (project_id) REFERENCES studio_projects(project_id)
);

CREATE TABLE IF NOT EXISTS studio_uploads (
    upload_id TEXT PRIMARY KEY,
    filename TEXT NOT NULL,
    mime TEXT NOT NULL,
    path TEXT NOT NULL,
    url TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_studio_renders_project
    ON studio_renders(project_id, shot_index);
CREATE INDEX IF NOT EXISTS idx_studio_projects_updated
    ON studio_projects(updated_at DESC);
"""


@contextmanager
def connection() -> Iterator[sqlite3.Connection]:
    conn = sqlite3.connect(config.DB_PATH, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA busy_timeout = 10000")
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_db() -> None:
    config.DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    with connection() as conn:
        conn.execute("PRAGMA journal_mode = WAL")
        conn.executescript(SCHEMA)


# ---------------------------------------------------------------------------
# Projects
# ---------------------------------------------------------------------------


def save_project(
    *,
    project_id: str,
    brief: str,
    plan: Plan,
    reference_id: str | None,
    created_at: str | None = None,
) -> None:
    now = utc_now()
    with connection() as conn:
        conn.execute(
            """
            INSERT INTO studio_projects (
                project_id, title, mode, route, brief, plan_json,
                reference_id, status, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                project_id,
                plan.title,
                plan.mode,
                plan.route,
                brief,
                plan.model_dump_json(),
                reference_id,
                "planned",
                created_at or now,
                now,
            ),
        )


def _load_renders(conn: sqlite3.Connection, project_id: str) -> list[RenderRecord]:
    rows = conn.execute(
        "SELECT * FROM studio_renders WHERE project_id = ? ORDER BY shot_index",
        (project_id,),
    ).fetchall()
    return [_render_from_row(row) for row in rows]


def _render_from_row(row: sqlite3.Row) -> RenderRecord:
    return RenderRecord(
        render_id=row["render_id"],
        project_id=row["project_id"],
        shot_index=int(row["shot_index"]),
        status=row["status"],
        file_url=row["file_url"] or "",
        error=row["error"] or "",
        prompt_id=row["prompt_id"] or "",
        width=int(row["width"] or 0),
        height=int(row["height"] or 0),
        started_at=row["started_at"],
        finished_at=row["finished_at"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


def _project_from_row(
    row: sqlite3.Row, renders: list[RenderRecord]
) -> ProjectRecord:
    plan = Plan.model_validate_json(row["plan_json"])
    shot_count = len(plan.shots)
    done = sum(1 for item in renders if item.status == "done")
    failed = sum(1 for item in renders if item.status == "failed")
    working = sum(1 for item in renders if item.status in {"queued", "running"})
    if working:
        status = "rendering"
    elif done and done == shot_count:
        status = "done"
    elif done:
        status = "partial"
    elif failed:
        status = "failed"
    else:
        status = "planned"
    covers = [
        item.file_url
        for item in renders
        if item.status == "done" and item.file_url
    ][:4]
    return ProjectRecord(
        project_id=row["project_id"],
        title=row["title"],
        mode=row["mode"],
        route=row["route"],
        brief=row["brief"],
        plan=plan,
        reference_id=row["reference_id"],
        status=status,
        created_at=row["created_at"],
        updated_at=row["updated_at"],
        render_count=done,
        done_count=done,
        failed_count=failed,
        cover_urls=covers,
    )


def get_project(project_id: str) -> ProjectResponse | None:
    with connection() as conn:
        row = conn.execute(
            "SELECT * FROM studio_projects WHERE project_id = ?", (project_id,)
        ).fetchone()
        if row is None:
            return None
        renders = _load_renders(conn, project_id)
        base = _project_from_row(row, renders)
        return ProjectResponse(**base.model_dump(), renders=renders)


def list_projects(limit: int = 40, offset: int = 0) -> ProjectList:
    limit = max(1, min(int(limit), 100))
    offset = max(0, int(offset))
    with connection() as conn:
        total = int(
            conn.execute("SELECT COUNT(*) FROM studio_projects").fetchone()[0]
        )
        rows = conn.execute(
            "SELECT * FROM studio_projects ORDER BY updated_at DESC, created_at DESC "
            "LIMIT ? OFFSET ?",
            (limit, offset),
        ).fetchall()
        items: list[ProjectRecord] = []
        for row in rows:
            renders = _load_renders(conn, row["project_id"])
            items.append(_project_from_row(row, renders))
    return ProjectList(items=items, total=total)


def update_plan(project_id: str, plan: Plan) -> None:
    with connection() as conn:
        conn.execute(
            """
            UPDATE studio_projects
               SET title = ?, plan_json = ?, status = 'planned', updated_at = ?
             WHERE project_id = ?
            """,
            (plan.title, plan.model_dump_json(), utc_now(), project_id),
        )


def touch_project(project_id: str) -> None:
    with connection() as conn:
        conn.execute(
            "UPDATE studio_projects SET updated_at = ? WHERE project_id = ?",
            (utc_now(), project_id),
        )


def set_shot_status(project_id: str, shot_index: int, status: str) -> None:
    with connection() as conn:
        row = conn.execute(
            "SELECT plan_json FROM studio_projects WHERE project_id = ?",
            (project_id,),
        ).fetchone()
        if row is None:
            return
        plan = Plan.model_validate_json(row["plan_json"])
        for shot in plan.shots:
            if shot.index == shot_index:
                shot.status = status  # type: ignore[assignment]
                break
        conn.execute(
            "UPDATE studio_projects SET plan_json = ?, updated_at = ? WHERE project_id = ?",
            (plan.model_dump_json(), utc_now(), project_id),
        )


def project_count() -> int:
    with connection() as conn:
        return int(conn.execute("SELECT COUNT(*) FROM studio_projects").fetchone()[0])


def fail_interrupted_renders(message: str) -> int:
    """Mark jobs left queued/running by a crashed server as failed.

    ComfyUI work does not survive an API restart, so pretending these jobs are
    still running would be a lie. Every affected shot gets the same honest
    message and can be rendered again.
    """

    now = utc_now()
    with connection() as conn:
        rows = conn.execute(
            "SELECT render_id, project_id, shot_index FROM studio_renders "
            "WHERE status IN ('queued', 'running')"
        ).fetchall()
        if not rows:
            return 0
        by_project: dict[str, list[int]] = {}
        for row in rows:
            conn.execute(
                """
                UPDATE studio_renders
                   SET status = 'failed', error = ?, finished_at = ?, updated_at = ?
                 WHERE render_id = ?
                """,
                (message[:4000], now, now, row["render_id"]),
            )
            by_project.setdefault(row["project_id"], []).append(
                int(row["shot_index"])
            )
        for project_id, indices in by_project.items():
            project_row = conn.execute(
                "SELECT plan_json FROM studio_projects WHERE project_id = ?",
                (project_id,),
            ).fetchone()
            if project_row is None:
                continue
            plan = Plan.model_validate_json(project_row["plan_json"])
            for shot in plan.shots:
                if shot.index in indices:
                    shot.status = "failed"  # type: ignore[assignment]
            conn.execute(
                "UPDATE studio_projects SET plan_json = ?, updated_at = ? "
                "WHERE project_id = ?",
                (plan.model_dump_json(), now, project_id),
            )
    return len(rows)


# ---------------------------------------------------------------------------
# Renders
# ---------------------------------------------------------------------------


def begin_render(project_id: str, shot_index: int) -> RenderRecord:
    now = utc_now()
    with connection() as conn:
        row = conn.execute(
            "SELECT render_id, created_at FROM studio_renders "
            "WHERE project_id = ? AND shot_index = ?",
            (project_id, shot_index),
        ).fetchone()
        if row is None:
            render_id = uuid4().hex
            conn.execute(
                """
                INSERT INTO studio_renders (
                    render_id, project_id, shot_index, status, file_url,
                    file_path, error, prompt_id, width, height,
                    started_at, finished_at, created_at, updated_at
                ) VALUES (?, ?, ?, 'queued', '', '', '', '', 0, 0, NULL, NULL, ?, ?)
                """,
                (render_id, project_id, shot_index, now, now),
            )
        else:
            render_id = row["render_id"]
            conn.execute(
                """
                UPDATE studio_renders
                   SET status = 'queued', file_url = '', file_path = '',
                       error = '', prompt_id = '', width = 0, height = 0,
                       started_at = NULL, finished_at = NULL, updated_at = ?
                 WHERE render_id = ?
                """,
                (now, render_id),
            )
        conn.execute(
            "UPDATE studio_projects SET updated_at = ? WHERE project_id = ?",
            (now, project_id),
        )
        fresh = conn.execute(
            "SELECT * FROM studio_renders WHERE render_id = ?", (render_id,)
        ).fetchone()
    return _render_from_row(fresh)


_PATCHABLE = {
    "status",
    "file_url",
    "file_path",
    "error",
    "prompt_id",
    "width",
    "height",
    "started_at",
    "finished_at",
}


def update_render(render_id: str, **fields: Any) -> None:
    cleaned = {key: value for key, value in fields.items() if key in _PATCHABLE}
    if not cleaned:
        return
    cleaned["updated_at"] = utc_now()
    assignments = ", ".join(f"{key} = ?" for key in cleaned)
    with connection() as conn:
        conn.execute(
            f"UPDATE studio_renders SET {assignments} WHERE render_id = ?",
            (*cleaned.values(), render_id),
        )


def get_render(render_id: str) -> RenderRecord | None:
    with connection() as conn:
        row = conn.execute(
            "SELECT * FROM studio_renders WHERE render_id = ?", (render_id,)
        ).fetchone()
    return _render_from_row(row) if row is not None else None


def delete_render(project_id: str, shot_index: int) -> str:
    """Remove one render row and return the local file path it pointed at."""

    with connection() as conn:
        row = conn.execute(
            "SELECT file_path FROM studio_renders "
            "WHERE project_id = ? AND shot_index = ?",
            (project_id, shot_index),
        ).fetchone()
        conn.execute(
            "DELETE FROM studio_renders WHERE project_id = ? AND shot_index = ?",
            (project_id, shot_index),
        )
    return str(row["file_path"]) if row is not None and row["file_path"] else ""


# ---------------------------------------------------------------------------
# Uploads
# ---------------------------------------------------------------------------


def save_upload(
    *,
    upload_id: str,
    filename: str,
    mime: str,
    path: Path,
    url: str,
) -> UploadRecord:
    created = utc_now()
    with connection() as conn:
        conn.execute(
            """
            INSERT INTO studio_uploads (
                upload_id, filename, mime, path, url, created_at
            ) VALUES (?, ?, ?, ?, ?, ?)
            """,
            (upload_id, filename, mime, str(path), url, created),
        )
    return UploadRecord(
        upload_id=upload_id,
        filename=filename,
        mime=mime,
        url=url,
        created_at=created,
    )


def get_upload(upload_id: str) -> UploadRecord | None:
    with connection() as conn:
        row = conn.execute(
            "SELECT * FROM studio_uploads WHERE upload_id = ?", (upload_id,)
        ).fetchone()
    if row is None:
        return None
    return UploadRecord(
        upload_id=row["upload_id"],
        filename=row["filename"],
        mime=row["mime"],
        url=row["url"],
        created_at=row["created_at"],
    )


def upload_path(upload_id: str) -> Path | None:
    with connection() as conn:
        row = conn.execute(
            "SELECT path FROM studio_uploads WHERE upload_id = ?", (upload_id,)
        ).fetchone()
    if row is None:
        return None
    path = Path(row["path"])
    return path if path.is_file() else None
