"""Data access for projects, executions, traces, and validation reports."""

from __future__ import annotations

import json
from contextlib import closing
from pathlib import Path
from typing import Any

from database.db import connect, initialize_schema
from schemas.project import CreativeRequirement


def _to_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False)


def _from_json(value: str | None, default: Any = None) -> Any:
    if value is None or value == "":
        return default
    return json.loads(value)


class ProjectRepository:
    def __init__(self, db_path: str | Path):
        self.db_path = Path(db_path)
        initialize_schema(self.db_path)

    def create_project(
        self,
        *,
        project_id: str,
        requirement: CreativeRequirement,
        raw_requirement: str,
        created_at: str,
    ) -> None:
        with closing(connect(self.db_path)) as connection:
            with connection:
                connection.execute(
                    """
                    INSERT INTO projects (
                        project_id, project_name, status, raw_requirement,
                        structured_requirement, task_plan, storyboard,
                        created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        project_id,
                        requirement.project_name,
                        "running",
                        raw_requirement,
                        _to_json(requirement.model_dump(mode="json")),
                        "[]",
                        "{}",
                        created_at,
                        created_at,
                    ),
                )

    def start_execution(
        self,
        *,
        execution_id: str,
        project_id: str,
        started_at: str,
    ) -> None:
        with closing(connect(self.db_path)) as connection:
            with connection:
                connection.execute(
                    """
                    INSERT INTO executions (
                        execution_id, project_id, status, started_at
                    ) VALUES (?, ?, ?, ?)
                    """,
                    (execution_id, project_id, "running", started_at),
                )

    def finish_run(
        self,
        *,
        project_id: str,
        execution_id: str,
        status: str,
        task_plan: list[dict[str, Any]],
        storyboard: dict[str, Any],
        validation_report: dict[str, Any] | None,
        trace_events: list[dict[str, Any]],
        error: str | None,
        finished_at: str,
        structured_requirement: dict[str, Any] | None = None,
        project_name: str | None = None,
        revision_history: list[dict[str, Any]] | None = None,
        raw_requirement: str | None = None,
    ) -> None:
        with closing(connect(self.db_path)) as connection:
            with connection:
                project_update = connection.execute(
                    """
                    UPDATE projects
                    SET status = ?, task_plan = ?, storyboard = ?, updated_at = ?,
                        structured_requirement = COALESCE(
                            ?, structured_requirement
                        ),
                        project_name = COALESCE(?, project_name),
                        raw_requirement = COALESCE(?, raw_requirement)
                    WHERE project_id = ?
                    """,
                    (
                        status,
                        _to_json(task_plan),
                        _to_json(storyboard),
                        finished_at,
                        (
                            _to_json(structured_requirement)
                            if structured_requirement is not None
                            else None
                        ),
                        project_name,
                        raw_requirement,
                        project_id,
                    ),
                )
                if project_update.rowcount != 1:
                    raise ValueError(f"Project not found: {project_id}")

                execution_update = connection.execute(
                    """
                    UPDATE executions
                    SET status = ?, finished_at = ?, error = ?
                    WHERE execution_id = ?
                    """,
                    (status, finished_at, error, execution_id),
                )
                if execution_update.rowcount != 1:
                    raise ValueError(f"Execution not found: {execution_id}")

                if trace_events:
                    connection.executemany(
                        """
                        INSERT INTO execution_traces (
                            execution_id, project_id, node_name, tool_name,
                            tool_arguments, input_summary, output_summary,
                            status, error, created_at
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        [
                            (
                                execution_id,
                                project_id,
                                event.get("node_name", ""),
                                event.get("tool_name"),
                                (
                                    _to_json(event["tool_arguments"])
                                    if event.get("tool_arguments") is not None
                                    else None
                                ),
                                event.get("input_summary", ""),
                                event.get("output_summary", ""),
                                event.get("status", "success"),
                                event.get("error"),
                                event.get("created_at", finished_at),
                            )
                            for event in trace_events
                        ],
                    )

                if validation_report is not None:
                    connection.execute(
                        """
                        INSERT INTO validation_reports (
                            execution_id, project_id, report_type, passed,
                            report_json, created_at
                        ) VALUES (?, ?, ?, ?, ?, ?)
                        """,
                        (
                            execution_id,
                            project_id,
                            validation_report.get("check_type", "unknown"),
                            1 if validation_report.get("passed") else 0,
                            _to_json(validation_report),
                            finished_at,
                        ),
                    )

                if revision_history:
                    connection.executemany(
                        """
                        INSERT INTO revision_history (
                            execution_id, project_id, revision_number,
                            status, reason, details_json, created_at
                        ) VALUES (?, ?, ?, ?, ?, ?, ?)
                        """,
                        [
                            (
                                execution_id,
                                project_id,
                                int(record.get("revision_number", 0)),
                                record.get("status", "completed"),
                                record.get("reason", ""),
                                _to_json(record),
                                record.get("created_at", finished_at),
                            )
                            for record in revision_history
                        ],
                    )

    def list_projects(
        self,
        *,
        search: str | None = None,
        status: str | None = None,
        order_by: str = "updated_at_desc",
        limit: int = 100,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        """Return lightweight project summaries for the history view."""

        limit = max(1, min(int(limit), 200))
        offset = max(0, int(offset))
        order_map = {
            "updated_at_desc": "updated_at DESC",
            "created_at_desc": "created_at DESC",
            "name_asc": "project_name ASC",
            "name_desc": "project_name DESC",
        }
        order_clause = order_map.get(order_by, order_map["updated_at_desc"])

        query = """
            SELECT project_id, project_name, status, raw_requirement,
                   structured_requirement, task_plan, storyboard,
                   created_at, updated_at
            FROM projects
            WHERE 1 = 1
        """
        params: list[Any] = []
        if search and search.strip():
            pattern = f"%{search.strip()}%"
            query += (
                " AND (project_name LIKE ? OR raw_requirement LIKE ?)"
            )
            params.extend([pattern, pattern])
        if status and status.strip():
            query += " AND status = ?"
            params.append(status.strip())
        query += f" ORDER BY {order_clause} LIMIT ? OFFSET ?"
        params.extend([limit, offset])

        with closing(connect(self.db_path)) as connection:
            rows = connection.execute(query, params).fetchall()

        summaries: list[dict[str, Any]] = []
        for row in rows:
            summary = dict(row)
            structured = _from_json(
                summary.pop("structured_requirement", None), {}
            )
            storyboard = _from_json(
                summary.pop("storyboard", None), {}
            )
            summary["task_plan"] = _from_json(
                summary.get("task_plan"), []
            )
            summary["duration_seconds"] = structured.get(
                "duration_seconds"
            )
            summary["scene_count"] = len(
                structured.get("scene_requirements", [])
            )
            summary["shot_count"] = len(storyboard.get("shots", []))
            summary["generation_method"] = storyboard.get(
                "generation_method", ""
            )
            summary["raw_requirement_preview"] = (
                summary.get("raw_requirement", "")[:160]
            )
            summaries.append(summary)
        return summaries

    def count_projects(
        self,
        *,
        search: str | None = None,
        status: str | None = None,
    ) -> int:
        query = "SELECT COUNT(*) FROM projects WHERE 1 = 1"
        params: list[Any] = []
        if search and search.strip():
            pattern = f"%{search.strip()}%"
            query += (
                " AND (project_name LIKE ? OR raw_requirement LIKE ?)"
            )
            params.extend([pattern, pattern])
        if status and status.strip():
            query += " AND status = ?"
            params.append(status.strip())
        with closing(connect(self.db_path)) as connection:
            row = connection.execute(query, params).fetchone()
        return int(row[0]) if row else 0

    def save_conversation(self, state: dict[str, Any]) -> None:
        """Upsert one guided conversation snapshot.

        The full state, including messages and field provenance, is stored as
        JSON. This keeps the schema migration additive and lets the UI resume
        a project without re-asking decisions the user already made.
        """

        session_id = str(state.get("session_id") or "").strip()
        if not session_id:
            raise ValueError("conversation state is missing session_id")
        now = str(state.get("updated_at") or "")
        created_at = str(state.get("created_at") or now)
        with closing(connect(self.db_path)) as connection:
            with connection:
                connection.execute(
                    """
                    INSERT INTO creative_sessions (
                        session_id, project_id, status, original_idea,
                        state_json, created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(session_id) DO UPDATE SET
                        project_id = excluded.project_id,
                        status = excluded.status,
                        original_idea = excluded.original_idea,
                        state_json = excluded.state_json,
                        updated_at = excluded.updated_at
                    """,
                    (
                        session_id,
                        state.get("project_id"),
                        str(state.get("status") or "guiding"),
                        str(state.get("original_idea") or ""),
                        _to_json(state),
                        created_at,
                        now,
                    ),
                )

    def get_conversation(self, session_id: str) -> dict[str, Any] | None:
        with closing(connect(self.db_path)) as connection:
            row = connection.execute(
                "SELECT * FROM creative_sessions WHERE session_id = ?",
                (session_id,),
            ).fetchone()
        if row is None:
            return None
        record = dict(row)
        record["state"] = _from_json(record.pop("state_json"), {})
        return record

    def get_conversation_for_project(
        self,
        project_id: str,
    ) -> dict[str, Any] | None:
        with closing(connect(self.db_path)) as connection:
            row = connection.execute(
                """
                SELECT * FROM creative_sessions
                WHERE project_id = ?
                ORDER BY updated_at DESC
                LIMIT 1
                """,
                (project_id,),
            ).fetchone()
        if row is None:
            return None
        record = dict(row)
        record["state"] = _from_json(record.pop("state_json"), {})
        return record

    def list_conversations(self, *, limit: int = 20) -> list[dict[str, Any]]:
        limit = max(1, min(int(limit), 100))
        with closing(connect(self.db_path)) as connection:
            rows = connection.execute(
                """
                SELECT session_id, project_id, status, original_idea,
                       state_json, created_at, updated_at
                FROM creative_sessions
                ORDER BY updated_at DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
        summaries: list[dict[str, Any]] = []
        for row in rows:
            summary = dict(row)
            state = _from_json(summary.pop("state_json"), {})
            brief = state.get("brief") or {}
            fields = brief.get("fields") or {}
            proposal = state.get("proposal") or {}
            summary["stage"] = state.get("stage", "idea")
            summary["message_count"] = len(state.get("messages") or [])
            summary["proposal_title"] = proposal.get("title", "")
            summary["duration_seconds"] = (
                (fields.get("duration_seconds") or {}).get("value")
            )
            summary["original_idea_preview"] = str(
                summary.get("original_idea", "")
            )[:160]
            summaries.append(summary)
        return summaries

    def save_asset(self, asset: dict[str, Any]) -> None:
        asset_id = str(asset.get("asset_id") or "").strip()
        if not asset_id:
            raise ValueError("asset is missing asset_id")
        now = str(asset.get("updated_at") or asset.get("created_at") or "")
        with closing(connect(self.db_path)) as connection:
            with connection:
                connection.execute(
                    """
                    INSERT INTO creative_assets (
                        asset_id, name, kind, description, attributes_json,
                        rules_json, created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(asset_id) DO UPDATE SET
                        name = excluded.name,
                        kind = excluded.kind,
                        description = excluded.description,
                        attributes_json = excluded.attributes_json,
                        rules_json = excluded.rules_json,
                        updated_at = excluded.updated_at
                    """,
                    (
                        asset_id,
                        str(asset.get("name") or "未命名资产"),
                        str(asset.get("kind") or "vehicle"),
                        str(asset.get("description") or ""),
                        _to_json(asset.get("attributes") or {}),
                        _to_json(asset.get("rules") or []),
                        str(asset.get("created_at") or now),
                        now,
                    ),
                )

    def list_assets(
        self,
        *,
        kind: str | None = None,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        limit = max(1, min(int(limit), 200))
        query = "SELECT * FROM creative_assets"
        params: list[Any] = []
        if kind:
            query += " WHERE kind = ?"
            params.append(kind)
        query += " ORDER BY updated_at DESC LIMIT ?"
        params.append(limit)
        with closing(connect(self.db_path)) as connection:
            rows = connection.execute(query, params).fetchall()
        assets: list[dict[str, Any]] = []
        for row in rows:
            asset = dict(row)
            asset["attributes"] = _from_json(asset.pop("attributes_json"), {})
            asset["rules"] = _from_json(asset.pop("rules_json"), [])
            assets.append(asset)
        return assets

    def get_asset(self, asset_id: str) -> dict[str, Any] | None:
        with closing(connect(self.db_path)) as connection:
            row = connection.execute(
                "SELECT * FROM creative_assets WHERE asset_id = ?",
                (asset_id,),
            ).fetchone()
        if row is None:
            return None
        asset = dict(row)
        asset["attributes"] = _from_json(asset.pop("attributes_json"), {})
        asset["rules"] = _from_json(asset.pop("rules_json"), [])
        return asset

    def get_project(self, project_id: str) -> dict[str, Any] | None:
        with closing(connect(self.db_path)) as connection:
            project_row = connection.execute(
                "SELECT * FROM projects WHERE project_id = ?",
                (project_id,),
            ).fetchone()
            if project_row is None:
                return None

            project = dict(project_row)
            project["structured_requirement"] = _from_json(
                project["structured_requirement"], {}
            )
            project["task_plan"] = _from_json(project["task_plan"], [])
            project["storyboard"] = _from_json(project["storyboard"], {})

            executions = [
                dict(row)
                for row in connection.execute(
                    """
                    SELECT * FROM executions
                    WHERE project_id = ?
                    ORDER BY started_at, execution_id
                    """,
                    (project_id,),
                ).fetchall()
            ]
            for execution in executions:
                traces = [
                    dict(row)
                    for row in connection.execute(
                        """
                        SELECT * FROM execution_traces
                        WHERE execution_id = ?
                        ORDER BY id
                        """,
                        (execution["execution_id"],),
                    ).fetchall()
                ]
                for trace in traces:
                    trace["tool_arguments"] = _from_json(
                        trace["tool_arguments"], None
                    )
                execution["traces"] = traces

            reports = [
                dict(row)
                for row in connection.execute(
                    """
                    SELECT * FROM validation_reports
                    WHERE project_id = ?
                    ORDER BY id
                    """,
                    (project_id,),
                ).fetchall()
            ]
            for report in reports:
                report["report_json"] = _from_json(report["report_json"], {})

            revisions = [
                dict(row)
                for row in connection.execute(
                    """
                    SELECT * FROM revision_history
                    WHERE project_id = ?
                    ORDER BY id
                    """,
                    (project_id,),
                ).fetchall()
            ]
            for revision in revisions:
                revision["details_json"] = _from_json(
                    revision["details_json"], {}
                )

            project["executions"] = executions
            project["validation_reports"] = reports
            project["revision_history"] = revisions
            return project

    # ------------------------------------------------------------------
    # local generation output
    # ------------------------------------------------------------------
    def save_media(self, record: dict[str, Any]) -> None:
        """Record one rendered file (or one failed shot) for a project."""

        with closing(connect(self.db_path)) as connection:
            with connection:
                connection.execute(
                    """
                    INSERT OR REPLACE INTO generated_media (
                        media_id, project_id, shot_number, kind, backend,
                        workflow, prompt, file_path, duration_seconds,
                        status, error, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        record["media_id"],
                        record["project_id"],
                        int(record["shot_number"]),
                        record["kind"],
                        record["backend"],
                        record["workflow"],
                        record["prompt"],
                        record["file_path"],
                        record.get("duration_seconds"),
                        record["status"],
                        record.get("error") or "",
                        record["created_at"],
                    ),
                )

    def list_media(self, project_id: str) -> list[dict[str, Any]]:
        with closing(connect(self.db_path)) as connection:
            rows = connection.execute(
                """
                SELECT * FROM generated_media
                WHERE project_id = ?
                ORDER BY shot_number, created_at
                """,
                (project_id,),
            ).fetchall()
        return [dict(row) for row in rows]
