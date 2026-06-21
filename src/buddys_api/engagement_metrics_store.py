from __future__ import annotations

import sqlite3
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone

from buddys_api.engagement_metrics_models import (
    EngagementEvent,
    EngagementEventType,
    EngagementMetricsResponse,
    RetentionSummaryResponse,
)
from buddys_api.schemas import new_id, now_iso


class EngagementMetricsStore:
    def __init__(self, connection: sqlite3.Connection) -> None:
        self.connection = connection

    def record_event(
        self,
        *,
        user_id: str,
        buddy_id: str,
        event_type: EngagementEventType,
        capture_source: str | None = None,
        answer_type: str | None = None,
    ) -> EngagementEvent:
        event = EngagementEvent(
            event_id=new_id("engagement"),
            user_id=user_id,
            buddy_id=buddy_id,
            event_type=event_type,
            capture_source=capture_source,
            answer_type=answer_type,
            created_at=now_iso(),
        )
        with self.connection:
            self.connection.execute(
                """
                INSERT INTO engagement_events (
                    event_id, user_id, buddy_id, event_type, capture_source, answer_type, created_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    event.event_id,
                    event.user_id,
                    event.buddy_id,
                    event.event_type,
                    event.capture_source,
                    event.answer_type,
                    event.created_at,
                ),
            )
        return event

    def engagement_metrics_for_user(self, *, user_id: str) -> EngagementMetricsResponse:
        events = self._list_events_for_user(user_id=user_id)
        capture_by_source = Counter(
            event.capture_source
            for event in events
            if event.event_type == "capture_submitted" and event.capture_source
        )
        query_by_answer_type = Counter(
            event.answer_type
            for event in events
            if event.event_type == "query_answered" and event.answer_type
        )
        event_types = {event.event_type for event in events}
        activation_time = _first_activation_time(events)
        has_capture = "capture_submitted" in event_types
        has_confirmation = bool({"proposal_confirmed", "proposal_corrected"} & event_types)
        has_query = "query_answered" in event_types
        return EngagementMetricsResponse(
            activation={
                "has_capture": has_capture,
                "has_confirmation": has_confirmation,
                "has_query": has_query,
                "completed_first_capture_confirm_query": activation_time is not None,
            },
            capture_by_source=dict(capture_by_source),
            query_by_answer_type=dict(query_by_answer_type),
            event_count=len(events),
        )

    def retention_summary(self) -> RetentionSummaryResponse:
        events = self._list_all_events()
        events_by_user: dict[str, list[EngagementEvent]] = defaultdict(list)
        for event in events:
            events_by_user[event.user_id].append(event)
        active_users_by_window = {1: 0, 3: 0, 7: 0}
        activated_users = 0
        capture_by_source = Counter()
        for user_events in events_by_user.values():
            activation_time = _first_activation_time(user_events)
            if activation_time is None:
                continue
            activated_users += 1
            for event in user_events:
                if event.event_type == "capture_submitted" and event.capture_source:
                    event_time = datetime.fromisoformat(event.created_at)
                    if event_time > activation_time:
                        capture_by_source[event.capture_source] += 1
            for day in active_users_by_window:
                if _has_maintenance_event_in_window(user_events, activation_time=activation_time, day=day):
                    active_users_by_window[day] += 1
        return RetentionSummaryResponse(
            d1_active_users=active_users_by_window[1],
            d3_active_users=active_users_by_window[3],
            d7_active_users=active_users_by_window[7],
            activated_users=activated_users,
            capture_by_source=dict(capture_by_source),
        )

    def _list_events_for_user(self, *, user_id: str) -> list[EngagementEvent]:
        rows = self.connection.execute(
            """
            SELECT event_id, user_id, buddy_id, event_type, capture_source, answer_type, created_at
            FROM engagement_events
            WHERE user_id = ?
            ORDER BY created_at, event_id
            """,
            (user_id,),
        ).fetchall()
        return [_event_from_row(row) for row in rows]

    def _list_all_events(self) -> list[EngagementEvent]:
        rows = self.connection.execute(
            """
            SELECT event_id, user_id, buddy_id, event_type, capture_source, answer_type, created_at
            FROM engagement_events
            ORDER BY created_at, event_id
            """
        ).fetchall()
        return [_event_from_row(row) for row in rows]


def _event_from_row(row: sqlite3.Row) -> EngagementEvent:
    return EngagementEvent(
        event_id=row["event_id"],
        user_id=row["user_id"],
        buddy_id=row["buddy_id"],
        event_type=row["event_type"],
        capture_source=row["capture_source"],
        answer_type=row["answer_type"],
        created_at=row["created_at"],
    )


def _first_activation_time(events: list[EngagementEvent]) -> datetime | None:
    has_capture = False
    has_confirmation = False
    for event in events:
        if event.event_type == "capture_submitted":
            has_capture = True
            has_confirmation = False
            continue
        if event.event_type in {"proposal_confirmed", "proposal_corrected"} and has_capture:
            has_confirmation = True
            continue
        if event.event_type == "query_answered" and has_capture and has_confirmation:
            return datetime.fromisoformat(event.created_at)
    return None


def _has_maintenance_event_in_window(
    events: list[EngagementEvent],
    *,
    activation_time: datetime,
    day: int,
) -> bool:
    window_start = activation_time + timedelta(days=day)
    window_end = activation_time + timedelta(days=day + 1)
    for event in events:
        if event.event_type not in {"capture_submitted", "query_answered"}:
            continue
        event_time = datetime.fromisoformat(event.created_at)
        if window_start <= event_time < window_end:
            return True
    return False
