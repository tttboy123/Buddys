from __future__ import annotations

import json
import re
import sqlite3
from collections.abc import Iterable
from typing import Any

from buddys_api.buddy_store import BuddyStore
from buddys_api.device_store import DeviceRegistry
from buddys_api.schemas import CostEvent, new_id, now_iso
from buddys_api.sync_models import SyncEvent, SyncVisibility


DENIED_SUMMARY_KEY_PARTS = (
    "secret",
    "token",
    "api_key",
    "password",
    "pairing_token",
    "provider_key",
    "adapter_token",
    "public_key",
    "provider_raw",
    "raw_payload",
    "tool_args",
    "action_args",
)

DENIED_SUMMARY_EXACT_KEYS = (
    "args",
    "message",
    "raw_message",
    "user_message",
)
DENIED_SUMMARY_EXACT_KEY_TERMS = {
    re.sub(r"[^a-z0-9]+", "", key.lower()) for key in DENIED_SUMMARY_EXACT_KEYS
}

DENIED_SUMMARY_VALUE_PARTS = DENIED_SUMMARY_KEY_PARTS

_REDACTED = object()


class SyncStore:
    def __init__(self, connection: sqlite3.Connection) -> None:
        self.connection = connection

    def append_event(
        self,
        event_type: str,
        entity_type: str,
        entity_id: str,
        payload_summary: dict[str, Any] | None = None,
        actor_user_id: str | None = None,
        visibility: SyncVisibility = "legacy",
    ) -> SyncEvent:
        summary = _sanitize_summary(payload_summary or {})
        event_id = new_id("sync")
        created_at = now_iso()
        with self.connection:
            cursor = self.connection.execute(
                """
                INSERT INTO sync_events (
                    event_id, event_type, entity_type, entity_id, actor_user_id, visibility, payload_summary, created_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    event_id,
                    event_type,
                    entity_type,
                    entity_id,
                    actor_user_id,
                    visibility,
                    json.dumps(summary, ensure_ascii=False, sort_keys=True),
                    created_at,
                ),
            )
            revision = int(cursor.lastrowid)
        return SyncEvent(
            revision=revision,
            event_id=event_id,
            event_type=event_type,
            entity_type=entity_type,
            entity_id=entity_id,
            actor_user_id=actor_user_id,
            visibility=visibility,
            payload_summary=summary,
            created_at=created_at,
        )

    def list_events(self, since_revision: int, user_id: str | None) -> list[SyncEvent]:
        visibility_clause, params = _visibility_clause(user_id)
        rows = self.connection.execute(
            f"""
            SELECT revision, event_id, event_type, entity_type, entity_id, actor_user_id,
                   visibility, payload_summary, created_at
            FROM sync_events
            WHERE revision > ? AND {visibility_clause}
            ORDER BY revision
            """,
            (since_revision, *params),
        ).fetchall()
        return [_event_from_row(row) for row in rows]

    def visible_state_revision(self, user_id: str | None) -> int:
        visibility_clause, params = _visibility_clause(user_id)
        row = self.connection.execute(
            f"SELECT COALESCE(MAX(revision), 0) AS state_revision FROM sync_events WHERE {visibility_clause}",
            params,
        ).fetchone()
        return int(row["state_revision"])


def build_snapshot(
    sync_store: SyncStore,
    buddy_store: BuddyStore,
    device_store: DeviceRegistry,
    traces: Iterable[Any],
    cost_events: Iterable[CostEvent],
    user_id: str | None,
) -> dict[str, Any]:
    buddies = buddy_store.list_for_user(user_id, created_via="auth") if user_id else buddy_store.list_legacy()
    visible_buddy_ids = {buddy.buddy_id for buddy in buddies}
    visible_device_ids = {
        device.device_id for device in device_store.list_devices() if device.buddy_id in visible_buddy_ids
    }
    costs = [cost for cost in cost_events if cost.buddy_id in visible_buddy_ids]
    visible_agent_machine_ids = {
        binding.agent_machine_id
        for binding in device_store.list_bindings()
        if binding.buddy_id in visible_buddy_ids
    }

    return {
        "state_revision": sync_store.visible_state_revision(user_id),
        "buddies": [_safe_dump(buddy) for buddy in buddies],
        "devices": [
            _safe_dump(device)
            for device in device_store.list_devices()
            if device.device_id in visible_device_ids
        ],
        "agent_machines": [
            _safe_dump(machine)
            for machine in device_store.list_agent_machines()
            if machine.agent_machine_id in visible_agent_machine_ids
        ],
        "bindings": [
            _safe_dump(binding)
            for binding in device_store.list_bindings()
            if binding.buddy_id in visible_buddy_ids
        ],
        "latest_heartbeats": {
            heartbeat.device_id: _safe_dump(heartbeat)
            for heartbeat in device_store.list_latest_heartbeats()
            if heartbeat.device_id in visible_device_ids
        },
        "desired_states": {
            device_id: _safe_dump(device_store.get_desired_state(device_id))
            for device_id in sorted(visible_device_ids)
        },
        "device_events": [
            _safe_dump(event)
            for event in device_store.list_all_events()
            if event.device_id in visible_device_ids
        ],
        "traces": [_trace_summary(trace) for trace in traces if trace.buddy_id in visible_buddy_ids],
        "cost_summary": _cost_summary(costs),
        "plan_usage": {},
        "agents": [],
    }


def _visibility_clause(user_id: str | None) -> tuple[str, tuple[str, ...]]:
    if user_id is None:
        return "visibility = 'legacy'", ()
    return "visibility = 'auth' AND actor_user_id = ?", (user_id,)


def _event_from_row(row: sqlite3.Row) -> SyncEvent:
    return SyncEvent(
        revision=row["revision"],
        event_id=row["event_id"],
        event_type=row["event_type"],
        entity_type=row["entity_type"],
        entity_id=row["entity_id"],
        actor_user_id=row["actor_user_id"],
        visibility=row["visibility"],
        payload_summary=json.loads(row["payload_summary"]),
        created_at=row["created_at"],
    )


def _sanitize_summary(value: dict[str, Any]) -> dict[str, Any]:
    sanitized: dict[str, Any] = {}
    for key, item in value.items():
        if _is_denied_summary_key(key):
            continue
        sanitized_value = _sanitize_value(item)
        if sanitized_value is _REDACTED:
            continue
        sanitized[key] = sanitized_value
    return sanitized


def _sanitize_value(value: Any) -> Any:
    if isinstance(value, dict):
        return _sanitize_summary(value)
    if isinstance(value, list):
        sanitized_items = [_sanitize_value(item) for item in value]
        return [item for item in sanitized_items if item is not _REDACTED]
    if isinstance(value, str):
        if _contains_denied_summary_term(value, DENIED_SUMMARY_VALUE_PARTS):
            return _REDACTED
        return value
    if isinstance(value, int | float | bool) or value is None:
        return value
    stringified = str(value)
    if _contains_denied_summary_term(stringified, DENIED_SUMMARY_VALUE_PARTS):
        return _REDACTED
    return stringified


def _dump(model: Any) -> dict[str, Any]:
    return model.model_dump(mode="json")


def _safe_dump(model: Any) -> dict[str, Any]:
    return _sanitize_summary(_dump(model))


def _trace_summary(trace: Any) -> dict[str, Any]:
    proposal = getattr(trace, "proposal", None)
    permission_decision = getattr(trace, "permission_decision", None)
    tool_result = getattr(trace, "tool_result", None)
    return _sanitize_summary(
        {
            "trace_id": trace.trace_id,
            "buddy_id": trace.buddy_id,
            "space_id": trace.space_id,
            "device_id": trace.device_id,
            "turn_id": trace.turn_id,
            "proposal_id": proposal.proposal_id if proposal else None,
            "requires_confirmation": proposal.requires_confirmation if proposal else None,
            "permission_policy_result": permission_decision.policy_result if permission_decision else None,
            "tool_result_status": tool_result.status if tool_result else None,
            "cost_refs": trace.cost_refs,
            "created_at": trace.created_at,
            "updated_at": trace.updated_at,
        }
    )


def _is_denied_summary_key(key: Any) -> bool:
    normalized_key = _normalize_summary_term(key)
    if normalized_key in DENIED_SUMMARY_EXACT_KEY_TERMS:
        return True
    return _contains_denied_summary_term(key, DENIED_SUMMARY_KEY_PARTS)


def _contains_denied_summary_term(value: Any, denied_terms: tuple[str, ...]) -> bool:
    normalized_value = _normalize_summary_term(value)
    return any(_normalize_summary_term(term) in normalized_value for term in denied_terms)


def _normalize_summary_term(value: Any) -> str:
    return re.sub(r"[^a-z0-9]+", "", str(value).lower())


def _cost_summary(cost_events: list[CostEvent]) -> dict[str, Any]:
    return {
        "event_count": len(cost_events),
        "total_tokens": sum(event.input_tokens + event.output_tokens for event in cost_events),
        "model_cost_usd": sum(event.model_cost_usd for event in cost_events),
        "tool_cost_usd": sum(event.tool_cost_usd for event in cost_events),
        "log_cost_usd": sum(event.log_cost_usd for event in cost_events),
    }
