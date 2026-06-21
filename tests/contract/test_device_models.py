from buddys_api.device_models import (
    AgentMachine,
    BuddyRuntimeBinding,
    Device,
    DeviceDesiredState,
    DeviceEvent,
    DeviceHeartbeat,
    SyncOutboxEvent,
)
from pydantic import ValidationError


def test_device_agent_machine_and_binding_export_cloud_safe_shape() -> None:
    device = Device(
        device_id="device_body_001",
        buddy_id="buddy_home_001",
        space_id="space_home",
        public_key="device-public-key",
        pairing_state="paired",
        firmware_version="0.1.0",
    )
    agent_machine = AgentMachine(
        agent_machine_id="agent_machine_home_mac",
        owner_user_id="user_demo",
        machine_type="local_mac",
        endpoint="https://agent-machine.example.test",
        public_key="agent-machine-public-key",
        runtime_version="0.1.0",
        status="online",
    )
    binding = BuddyRuntimeBinding(
        buddy_id="buddy_home_001",
        agent_machine_id="agent_machine_home_mac",
        role="primary",
        authority_epoch=1,
        state_revision=7,
    )

    exported = {
        "device": device.model_dump(),
        "agent_machine": agent_machine.model_dump(),
        "binding": binding.model_dump(),
    }

    assert exported["device"]["schema_version"] == "device.v1"
    assert exported["agent_machine"]["schema_version"] == "agent_machine.v1"
    assert exported["binding"]["schema_version"] == "buddy_runtime_binding.v1"
    assert exported["device"]["pairing_state"] == "paired"
    assert exported["agent_machine"]["status"] == "online"
    assert exported["binding"]["role"] == "primary"
    assert "created_at" in exported["device"]
    assert "updated_at" in exported["agent_machine"]

    serialized = str(exported).lower()
    assert "secret" not in serialized
    assert "provider_key" not in serialized
    assert "adapter_token" not in serialized


def test_device_heartbeat_desired_state_event_and_outbox_export_shape() -> None:
    heartbeat = DeviceHeartbeat(
        device_id="device_body_001",
        firmware_version="0.1.0",
        wifi_rssi=-58,
        uptime_seconds=120,
        current_state="manual_required",
        idempotency_key="hb-001",
    )
    desired_state = DeviceDesiredState(
        device_id="device_body_001",
        state="manual_required",
        revision=3,
        display_text="请手动把客厅灯调暗到约 35%。",
        manual_required=True,
        user_instruction="请手动把客厅灯调暗到约 35%。",
        source_trace_id="trace_001",
        state_memory={
            "confirmed_items": [
                {"name": "鸡蛋", "quantity": 5, "unit": "个"},
            ],
            "pending_proposal_count": 1,
        },
        proactive_hint={
            "kind": "consumption_inference",
            "message": "Buddy noticed 鸡蛋 was used recently.",
            "item_names": ["鸡蛋"],
        },
        recent_activity=[
            {
                "kind": "capture_confirmed",
                "summary": "Confirmed 鸡蛋 5个.",
                "created_at": "2026-06-22T10:00:00+00:00",
            }
        ],
    )
    event = DeviceEvent(
        device_id="device_body_001",
        event_type="manual_done",
        idempotency_key="event-001",
        payload={"source": "touch"},
    )
    outbox_event = SyncOutboxEvent(
        outbox_event_id="outbox_001",
        aggregate_type="device",
        aggregate_id="device_body_001",
        sequence=1,
        event_type="device_event",
        payload=event.model_dump(),
        idempotency_key="outbox-001",
    )

    assert heartbeat.model_dump()["schema_version"] == "device_heartbeat.v1"
    assert heartbeat.current_state == "manual_required"
    assert desired_state.model_dump()["schema_version"] == "device_desired_state.v1"
    assert desired_state.manual_required is True
    assert desired_state.state_memory.confirmed_items[0].name == "鸡蛋"
    assert desired_state.state_memory.pending_proposal_count == 1
    assert desired_state.proactive_hint.kind == "consumption_inference"
    assert desired_state.recent_activity[0].kind == "capture_confirmed"
    assert event.model_dump()["schema_version"] == "device_event.v1"
    assert event.event_type == "manual_done"
    assert outbox_event.model_dump()["schema_version"] == "sync_outbox_event.v1"
    assert outbox_event.sequence == 1


def test_device_models_reject_empty_identity_and_invalid_health_ranges() -> None:
    for factory in [
        lambda: Device(
            device_id="",
            buddy_id="buddy_home_001",
            space_id="space_home",
            public_key="device-public-key",
        ),
        lambda: AgentMachine(
            agent_machine_id="agent_machine_home_mac",
            owner_user_id="user_demo",
            machine_type="local_mac",
            endpoint="https://agent-machine.example.test",
            public_key="",
            runtime_version="0.1.0",
        ),
        lambda: DeviceHeartbeat(
            device_id="device_body_001",
            firmware_version="",
            wifi_rssi=-58,
            uptime_seconds=120,
            current_state="idle",
            idempotency_key="hb-001",
        ),
        lambda: DeviceHeartbeat(
            device_id="device_body_001",
            firmware_version="0.1.0",
            wifi_rssi=-200,
            uptime_seconds=120,
            current_state="idle",
            idempotency_key="hb-001",
        ),
        lambda: DeviceHeartbeat(
            device_id="device_body_001",
            firmware_version="0.1.0",
            wifi_rssi=-58,
            uptime_seconds=-1,
            current_state="idle",
            idempotency_key="hb-001",
        ),
    ]:
        try:
            factory()
        except ValidationError:
            continue
        raise AssertionError("expected model validation to fail")


def test_device_event_rejects_secret_and_action_shaped_payload_keys() -> None:
    for payload in [
        {"adapter_token": "plain-token"},
        {"nested": {"provider_key": "plain-key"}},
        {"tool_args": {"brightness": 35}},
        {"requested_action": "turn_light_on"},
    ]:
        try:
            DeviceEvent(
                device_id="device_body_001",
                event_type="approve",
                idempotency_key="event-001",
                payload=payload,
            )
        except ValidationError:
            continue
        raise AssertionError("expected payload validation to fail")
