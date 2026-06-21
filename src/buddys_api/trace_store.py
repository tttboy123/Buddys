from __future__ import annotations

import json
import sqlite3

from buddys_api.schemas import ActionTrace


class TraceStore:
    def __init__(self, connection: sqlite3.Connection | None = None) -> None:
        self.connection = connection
        self._traces: dict[str, ActionTrace] = {}

    def save(self, trace: ActionTrace) -> ActionTrace:
        if self.connection is not None:
            payload = json.dumps(trace.model_dump(mode="json"), ensure_ascii=False, sort_keys=True)
            with self.connection:
                self.connection.execute(
                    """
                    INSERT INTO action_traces (
                        trace_id, user_id, buddy_id, created_at, updated_at, payload_json
                    )
                    VALUES (?, ?, ?, ?, ?, ?)
                    ON CONFLICT(trace_id) DO UPDATE SET
                        user_id = excluded.user_id,
                        buddy_id = excluded.buddy_id,
                        created_at = excluded.created_at,
                        updated_at = excluded.updated_at,
                        payload_json = excluded.payload_json
                    """,
                    (
                        trace.trace_id,
                        trace.user_id,
                        trace.buddy_id,
                        trace.created_at,
                        trace.updated_at,
                        payload,
                    ),
                )
            return trace
        self._traces[trace.trace_id] = trace
        return trace

    def get(self, trace_id: str) -> ActionTrace:
        if self.connection is not None:
            row = self.connection.execute(
                "SELECT payload_json FROM action_traces WHERE trace_id = ?",
                (trace_id,),
            ).fetchone()
            if row is None:
                raise KeyError(f"trace not found: {trace_id}")
            return ActionTrace.model_validate(json.loads(row["payload_json"]))
        try:
            return self._traces[trace_id]
        except KeyError as exc:
            raise KeyError(f"trace not found: {trace_id}") from exc

    def list(self) -> list[ActionTrace]:
        if self.connection is not None:
            rows = self.connection.execute(
                """
                SELECT payload_json
                FROM action_traces
                ORDER BY created_at, trace_id
                """
            ).fetchall()
            return [ActionTrace.model_validate(json.loads(row["payload_json"])) for row in rows]
        return list(self._traces.values())
