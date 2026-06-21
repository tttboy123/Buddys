import pytest
from datetime import datetime, timedelta, timezone

from tools.device_simulator.state import (
    ALLOWED_EVENTS,
    build_device_event,
    build_heartbeat_payload,
    render_screen,
)


def test_render_manual_required_includes_instruction_text() -> None:
    screen = render_screen(
        {
            "state": "manual_required",
            "display_text": "Manual action needed",
            "user_instruction": "Please dim the living room light to 35%.",
            "revision": 7,
        }
    )

    assert "manual_required" in screen
    assert "Manual action needed" in screen
    assert "Please dim the living room light to 35%." in screen
    assert "rev 7" in screen


def test_render_asking_confirmation_includes_proposal_action_text() -> None:
    screen = render_screen(
        {
            "state": "asking_confirmation",
            "display_text": "Dim living room lights?",
            "proposal": {"action": "set brightness to 35%"},
        }
    )

    assert "asking_confirmation" in screen
    assert "Dim living room lights?" in screen
    assert "set brightness to 35%" in screen


def test_render_state_memory_summary_includes_confirmed_pantry_and_pending_count() -> None:
    screen = render_screen(
        {
            "state": "idle",
            "state_memory": {
                "confirmed_items": [
                    {"name": "鸡蛋", "quantity": 5, "unit": "个"},
                    {"name": "牛奶", "quantity": 1, "unit": "盒"},
                ],
                "pending_proposal_count": 2,
            },
        }
    )

    assert "pantry: 鸡蛋 5个, 牛奶 1盒" in screen
    assert "pending: 2 proposal(s)" in screen


def test_render_screen_includes_proactive_hint_and_recent_activity_summary() -> None:
    screen = render_screen(
        {
            "state": "idle",
            "state_memory": {
                "confirmed_items": [
                    {"name": "鸡蛋", "quantity": 5, "unit": "个"},
                ],
                "pending_proposal_count": 1,
            },
            "proactive_hint": {
                "kind": "consumption_inference",
                "message": "Buddy noticed 鸡蛋 was used recently.",
                "item_names": ["鸡蛋"],
            },
            "recent_activity": [
                {
                    "kind": "query_answered",
                    "summary": "还有鸡蛋。",
                    "created_at": "2026-06-22T10:00:00+00:00",
                }
            ],
        }
    )

    assert "hint: Buddy noticed 鸡蛋 was used recently." in screen
    assert "recent: 还有鸡蛋。" in screen


def test_render_screen_includes_stale_sync_cue_from_desired_state_timestamp() -> None:
    screen = render_screen(
        {
            "state": "idle",
            "revision": 12,
            "updated_at": "2024-01-01T00:00:00+00:00",
        }
    )

    assert "rev 12" in screen
    assert "sync: stale @ 2024-01-01T00:00:00+00:00" in screen


def test_render_screen_marks_recent_desired_state_as_fresh() -> None:
    recent = (datetime.now(timezone.utc) - timedelta(seconds=30)).isoformat()

    screen = render_screen(
        {
            "state": "idle",
            "revision": 3,
            "updated_at": recent,
        }
    )

    assert "rev 3" in screen
    assert f"sync: fresh @ {recent}" in screen


def test_build_heartbeat_payload_matches_api_contract_without_secret_fields() -> None:
    payload = build_heartbeat_payload(
        firmware_version="0.2.0-sim",
        current_state="idle",
        uptime_ms=123_456,
        wifi_rssi=-58,
        idempotency_key="hb-sim-001",
    )

    assert payload == {
        "firmware_version": "0.2.0-sim",
        "current_state": "idle",
        "uptime_seconds": 123,
        "wifi_rssi": -58,
        "idempotency_key": "hb-sim-001",
    }
    serialized = str(payload).lower()
    assert "secret" not in serialized
    assert "token" not in serialized
    assert "password" not in serialized


def test_build_device_event_rejects_invalid_event_names() -> None:
    assert ALLOWED_EVENTS == {"approve", "reject", "ack", "manual_done"}

    with pytest.raises(ValueError, match="unsupported device event"):
        build_device_event("bad", idempotency_key="event-bad-001")


def test_build_device_event_rejects_secret_like_payload_keys() -> None:
    with pytest.raises(ValueError, match="payload key is not allowed"):
        build_device_event(
            "approve",
            idempotency_key="event-approve-001",
            payload={"nested": {"adapter_token": "plain-token"}},
        )
