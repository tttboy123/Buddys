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

    def list(
        self,
        *,
        buddy_id: str | None = None,
        reverse: bool = False,
        limit: int | None = None,
    ) -> list[ActionTrace]:
        if self.connection is not None:
            order = "DESC" if reverse else "ASC"
            query = """
            SELECT payload_json
            FROM action_traces
            """
            params: list[str] = []
            if buddy_id is not None:
                query += "\n            WHERE buddy_id = ?"
                params.append(buddy_id)
            query += f"\n            ORDER BY created_at {order}, trace_id {order}"
            if limit is not None:
                query += "\n            LIMIT ?"
                params.append(str(limit))
            rows = self.connection.execute(
                query,
                tuple(params),
            ).fetchall()
            return [ActionTrace.model_validate(json.loads(row["payload_json"])) for row in rows]
        traces = list(self._traces.values())
        if buddy_id is not None:
            traces = [trace for trace in traces if trace.buddy_id == buddy_id]
        traces.sort(key=lambda trace: (trace.created_at, trace.trace_id), reverse=reverse)
        if limit is not None:
            traces = traces[:limit]
        return traces

    def get_by_proposal_id(self, proposal_id: str) -> ActionTrace | None:
        if self.connection is not None:
            row = self.connection.execute(
                """
                SELECT payload_json
                FROM action_traces
                WHERE json_extract(payload_json, '$.proposal.proposal_id') = ?
                ORDER BY updated_at DESC, trace_id DESC
                LIMIT 1
                """,
                (proposal_id,),
            ).fetchone()
            if row is None:
                return None
            return ActionTrace.model_validate(json.loads(row["payload_json"]))
        for trace in self._traces.values():
            if trace.proposal is not None and trace.proposal.proposal_id == proposal_id:
                return trace
        return None
