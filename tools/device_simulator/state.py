from __future__ import annotations

from datetime import datetime, timezone
from textwrap import shorten
from typing import Any


ALLOWED_EVENTS = {"approve", "reject", "ack", "manual_done"}
ALLOWED_STATES = {
    "idle",
    "thinking",
    "asking_confirmation",
    "executing",
    "success",
    "manual_required",
    "error",
}
DENIED_PAYLOAD_KEY_PARTS = (
    "secret",
    "token",
    "api_key",
    "password",
    "provider_key",
    "adapter_token",
    "tool_args",
    "action",
)


def render_screen(desired_state: dict[str, Any]) -> str:
    state = str(desired_state.get("state") or "idle")
    revision = desired_state.get("revision", 0)
    display_text = _first_text(
        desired_state.get("display_text"),
        desired_state.get("user_instruction"),
        desired_state.get("message"),
    )
    instruction = _first_text(desired_state.get("user_instruction"), desired_state.get("instruction"))
    proposal_text = _proposal_text(desired_state)

    lines = [
        "+----------------------+",
        "| Buddys Body 240x240 |",
        "+----------------------+",
        f"state: {state}",
        f"rev {revision}",
    ]
    sync_cue = _sync_cue_line(desired_state.get("updated_at"))
    if sync_cue:
        lines.append(sync_cue)
    if display_text:
        lines.append(f"text: {_compact(display_text)}")
    if state == "manual_required" and instruction:
        lines.append(f"manual: {_compact(instruction)}")
    if state == "asking_confirmation" and proposal_text:
        lines.append(f"confirm: {_compact(proposal_text)}")
    lines.extend(_state_memory_lines(desired_state.get("state_memory")))
    shopping_line = _shopping_pass_line(desired_state.get("shopping_pass"))
    if shopping_line:
        lines.append(shopping_line)
    hint_line = _proactive_hint_line(desired_state.get("proactive_hint"))
    if hint_line:
        lines.append(hint_line)
    recent_line = _recent_activity_line(desired_state.get("recent_activity"))
    if recent_line:
        lines.append(recent_line)
    if desired_state.get("source_trace_id"):
        lines.append(f"trace: {desired_state['source_trace_id']}")
    return "\n".join(lines)


def build_heartbeat_payload(
    *,
    firmware_version: str,
    current_state: str,
    uptime_ms: int,
    wifi_rssi: int,
    idempotency_key: str,
) -> dict[str, object]:
    if current_state not in ALLOWED_STATES:
        raise ValueError(f"unsupported device state: {current_state}")
    if uptime_ms < 0:
        raise ValueError("uptime_ms must be non-negative")
    if not -127 <= wifi_rssi <= 0:
        raise ValueError("wifi_rssi must be between -127 and 0")
    if not firmware_version.strip():
        raise ValueError("firmware_version is required")
    if not idempotency_key.strip():
        raise ValueError("idempotency_key is required")

    return {
        "firmware_version": firmware_version,
        "current_state": current_state,
        "uptime_seconds": uptime_ms // 1000,
        "wifi_rssi": wifi_rssi,
        "idempotency_key": idempotency_key,
    }


def build_device_event(
    event_type: str,
    *,
    idempotency_key: str,
    payload: dict[str, Any] | None = None,
) -> dict[str, object]:
    if event_type not in ALLOWED_EVENTS:
        raise ValueError(f"unsupported device event: {event_type}")
    if not idempotency_key.strip():
        raise ValueError("idempotency_key is required")

    event_payload = payload or {}
    _reject_denied_payload_keys(event_payload)
    return {
        "event_type": event_type,
        "idempotency_key": idempotency_key,
        "payload": event_payload,
    }


def _proposal_text(desired_state: dict[str, Any]) -> str | None:
    proposal = desired_state.get("proposal")
    if isinstance(proposal, dict):
        return _first_text(proposal.get("display_text"), proposal.get("action"), proposal.get("summary"))
    return _first_text(desired_state.get("action"), desired_state.get("proposal_text"))


def _first_text(*values: object) -> str | None:
    for value in values:
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def _compact(value: str) -> str:
    return shorten(value, width=68, placeholder="...")


def _sync_cue_line(updated_at: Any) -> str | None:
    if not isinstance(updated_at, str) or not updated_at.strip():
        return None
    freshness = _freshness_label(updated_at)
    if freshness is None:
        return None
    return f"sync: {freshness} @ {updated_at}"


def _freshness_label(updated_at: str) -> str | None:
    timestamp = _parse_timestamp(updated_at)
    if timestamp is None:
        return None
    age_seconds = max((datetime.now(timezone.utc) - timestamp).total_seconds(), 0.0)
    if age_seconds <= 120:
        return "fresh"
    return "stale"


def _parse_timestamp(value: str) -> datetime | None:
    try:
        timestamp = datetime.fromisoformat(value)
    except ValueError:
        return None
    if timestamp.tzinfo is None:
        return timestamp.replace(tzinfo=timezone.utc)
    return timestamp.astimezone(timezone.utc)


def _state_memory_lines(state_memory: Any) -> list[str]:
    if not isinstance(state_memory, dict):
        return []

    lines: list[str] = []
    pantry = _pantry_summary(state_memory.get("confirmed_items"))
    if pantry:
        lines.append(f"pantry: {_compact(pantry)}")

    pending_count = state_memory.get("pending_proposal_count")
    if isinstance(pending_count, int) and pending_count >= 0:
        lines.append(f"pending: {pending_count} proposal(s)")
    return lines


def _proactive_hint_line(proactive_hint: Any) -> str | None:
    if not isinstance(proactive_hint, dict):
        return None
    message = proactive_hint.get("message")
    if not isinstance(message, str) or not message.strip():
        return None
    return f"hint: {_compact(message.strip())}"


def _shopping_pass_line(shopping_pass: Any) -> str | None:
    if not isinstance(shopping_pass, dict):
        return None
    names = shopping_pass.get("top_open_names")
    if isinstance(names, list):
        labels = [str(name).strip() for name in names if str(name).strip()]
        if labels:
            return f"shopping: {_compact(', '.join(labels))}"
    open_count = shopping_pass.get("open_count")
    if isinstance(open_count, int) and open_count > 0:
        return f"shopping: {open_count} item(s)"
    return None


def _recent_activity_line(recent_activity: Any) -> str | None:
    if not isinstance(recent_activity, list) or not recent_activity:
        return None
    latest = recent_activity[-1]
    if not isinstance(latest, dict):
        return None
    summary = latest.get("summary")
    if not isinstance(summary, str) or not summary.strip():
        return None
    return f"recent: {_compact(summary.strip())}"


def _pantry_summary(items: Any) -> str | None:
    if not isinstance(items, list):
        return None

    ordered_items = sorted(items, key=_state_memory_sort_key)
    labels = [_state_memory_item_label(item) for item in ordered_items]
    labels = [label for label in labels if label]
    if not labels:
        return None
    return ", ".join(labels)


def _state_memory_item_label(item: Any) -> str | None:
    if not isinstance(item, dict):
        return None
    name = item.get("name")
    if not isinstance(name, str) or not name.strip():
        return None
    quantity = _format_quantity(item.get("quantity"))
    unit = item.get("unit")
    if quantity is None:
        return name.strip()
    if isinstance(unit, str) and unit.strip():
        return f"{name.strip()} {quantity}{unit.strip()}"
    return f"{name.strip()} {quantity}"


def _format_quantity(value: Any) -> str | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        if value.is_integer():
            return str(int(value))
        return f"{value:g}"
    return None


def _state_memory_sort_key(item: Any) -> tuple[float, str]:
    if not isinstance(item, dict):
        return (0.0, "")
    quantity = item.get("quantity")
    if isinstance(quantity, bool):
        numeric_quantity = 0.0
    elif isinstance(quantity, int | float):
        numeric_quantity = float(quantity)
    else:
        numeric_quantity = 0.0
    name = item.get("name")
    if not isinstance(name, str):
        name = ""
    return (-numeric_quantity, name)


def _reject_denied_payload_keys(value: Any) -> None:
    if isinstance(value, dict):
        for key, nested_value in value.items():
            normalized_key = str(key).lower()
            if any(denied in normalized_key for denied in DENIED_PAYLOAD_KEY_PARTS):
                raise ValueError(f"device event payload key is not allowed: {key}")
            _reject_denied_payload_keys(nested_value)
    elif isinstance(value, list):
        for item in value:
            _reject_denied_payload_keys(item)
