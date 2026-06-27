from __future__ import annotations

import json
import re
import sqlite3
from collections.abc import Iterable
from typing import Any

from buddys_api.buddy_store import BuddyStore
from buddys_api.db import connection_lock
from buddys_api.device_store import DeviceRegistry
from buddys_api.schemas import CostEvent, new_id, now_iso
from buddys_api.state_memory_store import is_recent_consumption_timestamp
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
        self._connection_lock = connection_lock(connection)

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
        with self._connection_lock:
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
        with self._connection_lock:
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
        with self._connection_lock:
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
    usage_store: Any | None = None,
    agent_store: Any | None = None,
    state_memory_store: Any | None = None,
) -> dict[str, Any]:
    buddies = buddy_store.list_for_user(user_id, created_via="auth") if user_id else buddy_store.list_legacy()
    visible_buddy_ids = {buddy.buddy_id for buddy in buddies}
    visible_device_ids = {
        device.device_id for device in device_store.list_devices() if device.buddy_id in visible_buddy_ids
    }
    visible_traces = [trace for trace in traces if trace.buddy_id in visible_buddy_ids]
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
        "traces": [_trace_summary(trace) for trace in visible_traces],
        "cost_summary": _cost_summary(costs),
        "plan_usage": _plan_usage_summary(buddies=buddies, user_id=user_id, usage_store=usage_store),
        "agents": _agent_summaries(agent_store=agent_store, user_id=user_id),
        "state_memory": _state_memory_projection(
            buddies=buddies,
            user_id=user_id,
            state_memory_store=state_memory_store,
            traces=visible_traces,
        ),
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


def _plan_usage_summary(buddies: list[Any], user_id: str | None, usage_store: Any | None) -> dict[str, Any]:
    if usage_store is None:
        return {}
    target_user_id = user_id
    if target_user_id is None:
        visible_user_ids = sorted({buddy.user_id for buddy in buddies})
        if len(visible_user_ids) != 1:
            return {}
        target_user_id = visible_user_ids[0]
    return _safe_plan_usage_dump(usage_store.usage_summary(target_user_id).model_dump(mode="json"))


def _safe_plan_usage_dump(summary: dict[str, Any]) -> dict[str, Any]:
    allowed_fields = {
        "user_id",
        "plan_id",
        "plan_display_name",
        "monthly_token_limit",
        "hard_limit",
        "byok",
        "usage_month",
        "used_tokens",
        "remaining_tokens",
        "over_limit",
        "provider_usage",
        "model_usage",
    }
    return {key: value for key, value in summary.items() if key in allowed_fields}


def _agent_summaries(agent_store: Any | None, user_id: str | None) -> list[dict[str, Any]]:
    if agent_store is None or user_id is None:
        return []
    return [_safe_dump(agent) for agent in agent_store.list_for_user(user_id)]


def _state_memory_projection(
    *,
    buddies: list[Any],
    user_id: str | None,
    state_memory_store: Any | None,
    traces: list[Any],
) -> dict[str, Any]:
    if state_memory_store is None or user_id is None:
        return _empty_state_memory_projection()

    items_by_buddy_models: dict[str, list[Any]] = {}
    pending_by_buddy_models: dict[str, list[Any]] = {}
    recipes_by_buddy_models: dict[str, list[Any]] = {}
    history_by_buddy_models: dict[str, list[Any]] = {}
    summary_by_buddy: dict[str, dict[str, Any]] = {}

    for buddy in buddies:
        items = state_memory_store.list_items(user_id=user_id, buddy_id=buddy.buddy_id)
        pending = state_memory_store.list_pending_proposals(user_id=user_id, buddy_id=buddy.buddy_id)
        recipes = state_memory_store.list_recipes(user_id=user_id, buddy_id=buddy.buddy_id)
        history = state_memory_store.list_history(user_id=user_id, buddy_id=buddy.buddy_id)
        items_by_buddy_models[buddy.buddy_id] = items
        pending_by_buddy_models[buddy.buddy_id] = pending
        recipes_by_buddy_models[buddy.buddy_id] = recipes
        history_by_buddy_models[buddy.buddy_id] = history
        summary_by_buddy[buddy.buddy_id] = state_memory_store.summarize_buddy_state(
            user_id=user_id,
            buddy_id=buddy.buddy_id,
        )

    latest_queries_by_buddy = _latest_state_memory_queries_by_buddy(
        traces=traces,
        items_by_buddy=items_by_buddy_models,
    )
    return {
        "items_by_buddy": {
            buddy_id: [_safe_dump(item) for item in items]
            for buddy_id, items in items_by_buddy_models.items()
            if items
        },
        "pending_proposals_by_buddy": {
            buddy_id: [_safe_dump(proposal) for proposal in proposals]
            for buddy_id, proposals in pending_by_buddy_models.items()
            if proposals
        },
        "recipes_by_buddy": {
            buddy_id: [_safe_dump(recipe) for recipe in recipes]
            for buddy_id, recipes in recipes_by_buddy_models.items()
            if recipes
        },
        "summary_by_buddy": {
            buddy_id: summary
            for buddy_id, summary in summary_by_buddy.items()
            if (
                summary["confirmed_item_count"]
                or summary["pending_proposal_count"]
                or summary["recently_consumed_count"]
            )
        },
        "latest_query_by_buddy": latest_queries_by_buddy,
        "proactive_hint_by_buddy": _proactive_state_memory_hints_by_buddy(
            items_by_buddy=items_by_buddy_models,
            history_by_buddy=history_by_buddy_models,
        ),
        "recent_activity_by_buddy": _recent_state_memory_activity_by_buddy(
            history_by_buddy=history_by_buddy_models,
            pending_by_buddy=pending_by_buddy_models,
            latest_query_by_buddy=latest_queries_by_buddy,
        ),
    }


def _empty_state_memory_projection() -> dict[str, Any]:
    return {
        "items_by_buddy": {},
        "pending_proposals_by_buddy": {},
        "recipes_by_buddy": {},
        "summary_by_buddy": {},
        "latest_query_by_buddy": {},
        "proactive_hint_by_buddy": {},
        "recent_activity_by_buddy": {},
    }


def _latest_state_memory_queries_by_buddy(
    *,
    traces: list[Any],
    items_by_buddy: dict[str, list[Any]],
) -> dict[str, dict[str, Any]]:
    latest_by_buddy: dict[str, Any] = {}
    for trace in traces:
        proposal = getattr(trace, "proposal", None)
        intent = getattr(trace, "intent", None)
        if proposal is None or intent is None:
            continue
        if intent.name != "state_memory_query" or proposal.action_type != "reply_only":
            continue
        latest_by_buddy[trace.buddy_id] = trace

    query_by_buddy: dict[str, dict[str, Any]] = {}
    for buddy_id, trace in latest_by_buddy.items():
        args = getattr(trace.proposal, "args", {}) or {}
        item_index = {
            item.item_id: item
            for item in items_by_buddy.get(buddy_id, [])
        }
        evidence_item_ids = list(args.get("evidence_item_ids", []))
        query_by_buddy[buddy_id] = {
            "trace_id": trace.trace_id,
            "question": args.get("question"),
            "answer_type": args.get("answer_type"),
            "subject_name": args.get("subject_name"),
            "summary": trace.proposal.summary,
            "evidence_item_ids": evidence_item_ids,
            "evidence_items": [
                _state_memory_evidence_summary(item_index[item_id])
                for item_id in evidence_item_ids
                if item_id in item_index
            ],
            "missing_items": list(args.get("missing_items", [])),
            "has_item": args.get("has_item"),
            "created_at": trace.created_at,
        }
    return query_by_buddy


def _state_memory_evidence_summary(item: Any) -> dict[str, Any]:
    return {
        "item_id": item.item_id,
        "name": item.name,
        "quantity": item.quantity,
        "unit": item.unit,
        "status": item.status,
        "source": item.source,
        "last_seen_at": item.last_seen_at,
    }


def _proactive_state_memory_hints_by_buddy(
    *,
    items_by_buddy: dict[str, list[Any]],
    history_by_buddy: dict[str, list[Any]],
) -> dict[str, dict[str, Any]]:
    hints: dict[str, dict[str, Any]] = {}
    buddy_ids = set(items_by_buddy) | set(history_by_buddy)
    for buddy_id in buddy_ids:
        hint = _build_state_memory_hint(
            items=items_by_buddy.get(buddy_id, []),
            history=history_by_buddy.get(buddy_id, []),
        )
        if hint is not None:
            hints[buddy_id] = hint
    return hints


def _recent_state_memory_activity_by_buddy(
    *,
    history_by_buddy: dict[str, list[Any]],
    pending_by_buddy: dict[str, list[Any]],
    latest_query_by_buddy: dict[str, dict[str, Any]],
) -> dict[str, list[dict[str, Any]]]:
    activity_by_buddy: dict[str, list[dict[str, Any]]] = {}
    buddy_ids = set(history_by_buddy) | set(pending_by_buddy) | set(latest_query_by_buddy)
    for buddy_id in buddy_ids:
        activity: list[dict[str, Any]] = []
        for entry in history_by_buddy.get(buddy_id, [])[-5:]:
            activity.append(
                {
                    "kind": "capture_confirmed",
                    "summary": _history_activity_summary(entry),
                    "created_at": entry.created_at,
                    "basis": {
                        "item_names": [entry.item_name],
                        "change_type": entry.change_type,
                    },
                }
            )
        for proposal in pending_by_buddy.get(buddy_id, [])[-3:]:
            item_names = [delta.item_name for delta in proposal.deltas if delta.item_name]
            activity.append(
                {
                    "kind": "proposal_waiting",
                    "summary": _proposal_activity_summary(proposal, item_names),
                    "created_at": proposal.updated_at,
                    "basis": {
                        "item_names": item_names,
                        "unrecognized": list(proposal.unrecognized),
                    },
                }
            )
        latest_query = latest_query_by_buddy.get(buddy_id)
        if latest_query is not None:
            evidence_names = [item["name"] for item in latest_query.get("evidence_items", []) if item.get("name")]
            basis_item_names = evidence_names or list(latest_query.get("missing_items", [])) or [
                latest_query.get("subject_name")
            ]
            activity.append(
                {
                    "kind": "query_answered",
                    "summary": _query_activity_summary(latest_query),
                    "created_at": latest_query.get("created_at"),
                    "basis": {
                        "item_names": [name for name in basis_item_names if name],
                        "question": latest_query.get("question"),
                    },
                }
            )
        activity = [entry for entry in activity if entry.get("created_at") and entry.get("summary")]
        activity.sort(key=lambda entry: entry["created_at"])
        if activity:
            activity_by_buddy[buddy_id] = activity[-5:]
    return activity_by_buddy


def _build_state_memory_hint(*, items: list[Any], history: list[Any]) -> dict[str, Any] | None:
    recent_consumption = [
        entry
        for entry in history
        if entry.change_type in {"consume", "consumed"}
        and is_recent_consumption_timestamp(entry.created_at)
    ]
    if recent_consumption:
        recent_consumption.sort(key=lambda entry: (entry.created_at, entry.history_id))
        entry = recent_consumption[-1]
        matching_item = next((item for item in items if item.item_id == entry.item_id), None)
        return {
            "kind": "consumption_inference",
            "message": f"Buddy noticed {entry.item_name} was used recently. Want to review whether it needs a refill?",
            "basis": {
                "item_ids": [entry.item_id],
                "item_names": [entry.item_name],
                "recent_change_type": entry.change_type,
                "last_seen_at": matching_item.last_seen_at if matching_item is not None else None,
            },
        }

    low_items = [
        item
        for item in items
        if item.status == "active" and item.quantity is not None and item.quantity <= 2
    ]
    if not low_items:
        return None
    low_items.sort(key=lambda item: (item.quantity, item.updated_at, item.name))
    item = low_items[0]
    return {
        "kind": "consumption_inference",
        "message": f"{item.name} might be running low. Add it to the next shopping pass?",
        "basis": {
            "item_ids": [item.item_id],
            "item_names": [item.name],
            "last_seen_at": item.last_seen_at,
        },
    }


def _history_activity_summary(entry: Any) -> str:
    quantity_after = _format_state_memory_quantity(entry.quantity_after, entry.unit_after)
    if entry.change_type in {"consume", "consumed"}:
        return f"Buddy noted that {entry.item_name} was used{quantity_after}."
    if entry.change_type in {"remove", "removed"}:
        return f"Buddy removed {entry.item_name} from confirmed state."
    if quantity_after:
        return f"Buddy saved {entry.item_name} as {quantity_after}."
    return f"Buddy saved {entry.item_name}."


def _proposal_activity_summary(proposal: Any, item_names: list[str]) -> str:
    if item_names:
        return f"Buddy is waiting for review on {' / '.join(item_names)}."
    return f"Buddy is waiting for review on a {proposal.source} update."


def _query_activity_summary(latest_query: dict[str, Any]) -> str:
    answer_type = latest_query.get("answer_type")
    subject_name = latest_query.get("subject_name")
    if answer_type == "have_item" and subject_name:
        return f"Buddy answered whether {subject_name} is still at home."
    if answer_type == "missing_for_recipe" and subject_name:
        return f"Buddy answered what is still missing for {subject_name}."
    question = latest_query.get("question")
    if question:
        return f"Buddy answered your question about {question}."
    return "Buddy answered your latest question."


def _format_state_memory_quantity(quantity: Any, unit: Any) -> str:
    if quantity is None:
        return ""
    if float(quantity).is_integer():
        value = str(int(quantity))
    else:
        value = str(quantity)
    return f" {value}{unit or ''}"


def _latest_timestamp(timestamps: list[str]) -> str | None:
    return max(timestamps) if timestamps else None
