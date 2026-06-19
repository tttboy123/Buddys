from __future__ import annotations

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
    if display_text:
        lines.append(f"text: {_compact(display_text)}")
    if state == "manual_required" and instruction:
        lines.append(f"manual: {_compact(instruction)}")
    if state == "asking_confirmation" and proposal_text:
        lines.append(f"confirm: {_compact(proposal_text)}")
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
