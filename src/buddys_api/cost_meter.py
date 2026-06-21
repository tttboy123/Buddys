from __future__ import annotations

import json
import sqlite3

from buddys_api.schemas import CostEvent, new_id


class CostMeter:
    def __init__(self, connection: sqlite3.Connection | None = None) -> None:
        self.connection = connection
        self._events: list[CostEvent] = []

    def record_model_call(
        self,
        trace_id: str,
        buddy_id: str,
        provider: str,
        model: str,
        input_tokens: int,
        output_tokens: int,
    ) -> CostEvent:
        event = CostEvent(
            cost_event_id=new_id("cost"),
            trace_id=trace_id,
            buddy_id=buddy_id,
            provider=provider,
            model=model,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            model_cost_usd=0.0,
            tool_cost_usd=0.0,
            log_cost_usd=0.0,
        )
        if self.connection is not None:
            payload = json.dumps(event.model_dump(mode="json"), ensure_ascii=False, sort_keys=True)
            with self.connection:
                self.connection.execute(
                    """
                    INSERT INTO cost_events_runtime (
                        cost_event_id, trace_id, buddy_id, created_at, payload_json
                    )
                    VALUES (?, ?, ?, ?, ?)
                    ON CONFLICT(cost_event_id) DO UPDATE SET
                        trace_id = excluded.trace_id,
                        buddy_id = excluded.buddy_id,
                        created_at = excluded.created_at,
                        payload_json = excluded.payload_json
                    """,
                    (
                        event.cost_event_id,
                        event.trace_id,
                        event.buddy_id,
                        event.created_at,
                        payload,
                    ),
                )
            return event
        self._events.append(event)
        return event

    def list(self) -> list[CostEvent]:
        if self.connection is not None:
            rows = self.connection.execute(
                """
                SELECT payload_json
                FROM cost_events_runtime
                ORDER BY created_at, cost_event_id
                """
            ).fetchall()
            return [CostEvent.model_validate(json.loads(row["payload_json"])) for row in rows]
        return list(self._events)
