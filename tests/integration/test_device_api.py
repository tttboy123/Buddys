from fastapi.testclient import TestClient
import pytest

from buddys_api.device_models import AgentMachine, BuddyRuntimeBinding, Device, DeviceDesiredState
from buddys_api.device_store import DeviceRegistry
from buddys_api.main import create_app


def make_client(store: DeviceRegistry | None = None) -> TestClient:
    return TestClient(create_app(device_store=store))


def test_pair_device_creates_device_agent_machine_and_binding() -> None:
    client = make_client()
    buddy = create_buddy(client)

    response = client.post(
        "/devices/device_body_001/pair",
        json=pair_payload(buddy),
    )

    assert response.status_code == 201
    body = response.json()
    assert body["device"]["device_id"] == "device_body_001"
    assert body["device"]["pairing_state"] == "paired"
    assert body["agent_machine"]["agent_machine_id"] == "agent_machine_home_mac"
    assert body["binding"]["buddy_id"] == buddy["buddy_id"]
    assert body["binding"]["role"] == "primary"

    serialized = str(body).lower()
    assert "secret" not in serialized
    assert "provider_key" not in serialized
    assert "adapter_token" not in serialized


def test_heartbeat_updates_latest_device_health() -> None:
    client = make_client()
    headers = pairing_headers()
    pair_device(client)

    response = client.post(
        "/devices/device_body_001/heartbeat",
        headers=headers,
        json={
            "firmware_version": "0.1.0",
            "wifi_rssi": -55,
            "uptime_seconds": 300,
            "current_state": "idle",
            "idempotency_key": "hb-001",
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["device_id"] == "device_body_001"
    assert body["firmware_version"] == "0.1.0"
    assert body["wifi_rssi"] == -55
    assert body["current_state"] == "idle"


def test_pair_device_rejects_unknown_buddy_and_owner_mismatch() -> None:
    client = make_client()
    unknown_response = client.post(
        "/devices/device_body_001/pair",
        json=pair_payload({"buddy_id": "missing_buddy", "space_id": "home"}, owner_user_id="user_demo"),
    )
    assert unknown_response.status_code == 404
    assert unknown_response.json() == {"detail": {"code": "buddy_not_found"}}

    buddy = create_buddy(client, user_id="user_demo")
    mismatch_response = client.post(
        "/devices/device_body_002/pair",
        json=pair_payload(buddy, owner_user_id="other_user", idempotency_key="pair-002", pairing_token="pair-token-002"),
    )
    assert mismatch_response.status_code == 403
    assert mismatch_response.json() == {"detail": {"code": "agent_machine_owner_mismatch"}}


def test_unauthenticated_pair_device_rejects_auth_owned_buddy_without_side_effects(tmp_path) -> None:
    store = DeviceRegistry()
    client = TestClient(create_app(device_store=store, db_path=tmp_path / "buddys.sqlite3"))
    owner_token = register(client, "owner@example.com")
    auth_buddy_response = client.post(
        "/me/buddies",
        headers={"Authorization": f"Bearer {owner_token}"},
        json={"name": "Private Buddy", "space_id": "study"},
    )
    assert auth_buddy_response.status_code == 201
    auth_buddy = auth_buddy_response.json()

    response = client.post(
        "/devices/device_body_auth_probe/pair",
        json=pair_payload(
            auth_buddy,
            owner_user_id=auth_buddy["user_id"],
            idempotency_key="pair-auth-owned",
            pairing_token="pair-token-auth-owned",
        ),
    )

    assert response.status_code == 404
    assert response.json() == {"detail": {"code": "buddy_not_found"}}
    with pytest.raises(KeyError):
        store.get_device("device_body_auth_probe")
    with pytest.raises(KeyError):
        store.get_binding(auth_buddy["buddy_id"])
    assert store.list_events("device_body_auth_probe") == []


def test_pair_device_rejects_invalid_url_empty_fields_and_missing_pairing_token() -> None:
    client = make_client()
    buddy = create_buddy(client)

    invalid_url = pair_payload(buddy)
    invalid_url["agent_machine"]["endpoint"] = "not-a-url"
    assert client.post("/devices/device_body_001/pair", json=invalid_url).status_code == 422

    empty_key = pair_payload(buddy, idempotency_key="pair-002", pairing_token="pair-token-002")
    empty_key["public_key"] = ""
    assert client.post("/devices/device_body_002/pair", json=empty_key).status_code == 422

    missing_pairing_token = pair_payload(buddy, idempotency_key="pair-003", pairing_token="pair-token-003")
    missing_pairing_token.pop("pairing_token")
    assert client.post("/devices/device_body_003/pair", json=missing_pairing_token).status_code == 422


def test_pair_device_is_idempotent_for_duplicate_device_and_key() -> None:
    store = DeviceRegistry()
    client = make_client(store)
    buddy = create_buddy(client)
    payload = pair_payload(buddy)

    first = client.post("/devices/device_body_001/pair", json=payload)
    duplicate_payload = pair_payload(buddy)
    duplicate_payload["public_key"] = "changed-device-public-key"
    second = client.post("/devices/device_body_001/pair", json=duplicate_payload)

    assert first.status_code == 201
    assert second.status_code == 201
    assert second.json() == first.json()
    assert store.get_device("device_body_001").public_key == "device-public-key"


def test_desired_state_endpoint_returns_manual_required_state() -> None:
    store = DeviceRegistry()
    store.set_desired_state(
        DeviceDesiredState(
            device_id="device_body_001",
            state="manual_required",
            revision=2,
            display_text="请手动把客厅灯调暗到约 35%。",
            manual_required=True,
            user_instruction="请手动把客厅灯调暗到约 35%。",
            source_trace_id="trace_001",
        )
    )
    client = make_client(store)
    pair_device(client)

    response = client.get("/devices/device_body_001/desired-state", headers=pairing_headers())

    assert response.status_code == 200
    body = response.json()
    assert body["state"] == "manual_required"
    assert body["manual_required"] is True
    assert body["user_instruction"] == "请手动把客厅灯调暗到约 35%。"


def test_desired_state_endpoint_does_not_project_auth_state_memory_into_unauthenticated_read(tmp_path) -> None:
    store = DeviceRegistry()
    app = create_app(device_store=store, db_path=tmp_path / "buddys.sqlite3")
    client = TestClient(app)
    owner_token = register(client, "device-owner@example.com")
    buddy = client.post(
        "/me/buddies",
        headers={"Authorization": f"Bearer {owner_token}"},
        json={"name": "Kitchen Buddy", "space_id": "kitchen"},
    ).json()

    store.pair_device(
        device=Device(
            device_id="device_body_auth_001",
            buddy_id=buddy["buddy_id"],
            space_id=buddy["space_id"],
            public_key="device-public-key",
            pairing_state="paired",
            firmware_version="0.2.0-sim",
        ),
        agent_machine=AgentMachine(
            agent_machine_id="agent_machine_auth_001",
            owner_user_id=buddy["user_id"],
            machine_type="local_mac",
            endpoint="https://agent-machine.example.test",
            public_key="agent-machine-public-key",
            runtime_version="0.2.0-sim",
            status="online",
        ),
        binding=BuddyRuntimeBinding(
            buddy_id=buddy["buddy_id"],
            agent_machine_id="agent_machine_auth_001",
            role="primary",
        ),
        pairing_token="pair-auth-device-001",
        idempotency_key="pair-auth-device-001",
    )

    confirmed_capture = client.post(
        f"/me/buddies/{buddy['buddy_id']}/state-memory/captures/conversation",
        headers={"Authorization": f"Bearer {owner_token}"},
        json={"content": "我买了五个鸡蛋和一盒牛奶"},
    )
    assert confirmed_capture.status_code == 201
    confirmed_proposal_id = confirmed_capture.json()["proposal"]["proposal_id"]
    confirmed = client.post(
        f"/me/buddies/{buddy['buddy_id']}/state-memory/proposals/{confirmed_proposal_id}/confirm",
        headers={"Authorization": f"Bearer {owner_token}"},
    )
    assert confirmed.status_code == 200

    pending_capture = client.post(
        f"/me/buddies/{buddy['buddy_id']}/state-memory/captures/conversation",
        headers={"Authorization": f"Bearer {owner_token}"},
        json={"content": "香料用完了"},
    )
    assert pending_capture.status_code == 201

    query = client.post(
        f"/me/buddies/{buddy['buddy_id']}/state-memory/query",
        headers={"Authorization": f"Bearer {owner_token}"},
        json={"question": "有鸡蛋吗"},
    )
    assert query.status_code == 200

    app.state.device_store.set_desired_state(
        DeviceDesiredState(
            device_id="device_body_auth_001",
            state="manual_required",
            revision=6,
            display_text="Manual action needed",
            manual_required=True,
            user_instruction="Press the physical button after checking the pantry.",
            source_trace_id="trace_sim_002",
            updated_at="2026-06-22T00:00:00+00:00",
        )
    )

    missing = client.get("/devices/device_body_auth_001/desired-state")
    assert missing.status_code == 401
    assert missing.json() == {"detail": {"code": "device_auth_required"}}

    wrong = client.get(
        "/devices/device_body_auth_001/desired-state",
        headers=pairing_headers("wrong-token"),
    )
    assert wrong.status_code == 403
    assert wrong.json() == {"detail": {"code": "device_auth_invalid"}}

    response = client.get("/devices/device_body_auth_001/desired-state", headers=pairing_headers("pair-auth-device-001"))

    assert response.status_code == 200
    body = response.json()
    assert body["revision"] == 6
    assert body["updated_at"] == "2026-06-22T00:00:00+00:00"
    assert body.get("state_memory") is None
    assert body.get("proactive_hint") is None
    assert body["recent_activity"] == []
    serialized = str(body).lower()
    assert "api_key" not in serialized
    assert "capabilities" not in serialized
    assert "token" not in serialized


def test_desired_state_endpoint_returns_only_explicitly_stored_projection_without_live_overlay(tmp_path) -> None:
    store = DeviceRegistry()
    app = create_app(device_store=store, db_path=tmp_path / "buddys.sqlite3")
    client = TestClient(app)
    owner_token = register(client, "device-owner-explicit@example.com")
    buddy = client.post(
        "/me/buddies",
        headers={"Authorization": f"Bearer {owner_token}"},
        json={"name": "Kitchen Buddy", "space_id": "kitchen"},
    ).json()

    store.pair_device(
        device=Device(
            device_id="device_body_auth_explicit_001",
            buddy_id=buddy["buddy_id"],
            space_id=buddy["space_id"],
            public_key="device-public-key",
            pairing_state="paired",
            firmware_version="0.2.0-sim",
        ),
        agent_machine=AgentMachine(
            agent_machine_id="agent_machine_auth_explicit_001",
            owner_user_id=buddy["user_id"],
            machine_type="local_mac",
            endpoint="https://agent-machine.example.test",
            public_key="agent-machine-public-key",
            runtime_version="0.2.0-sim",
            status="online",
        ),
        binding=BuddyRuntimeBinding(
            buddy_id=buddy["buddy_id"],
            agent_machine_id="agent_machine_auth_explicit_001",
            role="primary",
        ),
        pairing_token="pair-auth-device-explicit-001",
        idempotency_key="pair-auth-device-explicit-001",
    )

    app.state.device_store.set_desired_state(
        DeviceDesiredState(
            device_id="device_body_auth_explicit_001",
            state="manual_required",
            revision=9,
            display_text="Stored projection",
            manual_required=True,
            user_instruction="Use stored data only.",
            source_trace_id="trace_stored_projection_001",
            updated_at="2026-06-22T00:05:00+00:00",
            state_memory={
                "confirmed_items": [{"name": "存货", "quantity": 2, "unit": "件"}],
                "pending_proposal_count": 7,
            },
            proactive_hint={
                "kind": "consumption_inference",
                "message": "Stored hint only.",
                "item_names": ["存货"],
            },
            recent_activity=[
                {
                    "kind": "query_answered",
                    "summary": "Stored recent activity.",
                    "created_at": "2026-06-22T00:05:00+00:00",
                }
            ],
        )
    )

    capture = client.post(
        f"/me/buddies/{buddy['buddy_id']}/state-memory/captures/conversation",
        headers={"Authorization": f"Bearer {owner_token}"},
        json={"content": "我买了五个鸡蛋和一盒牛奶"},
    )
    assert capture.status_code == 201
    proposal_id = capture.json()["proposal"]["proposal_id"]
    confirm = client.post(
        f"/me/buddies/{buddy['buddy_id']}/state-memory/proposals/{proposal_id}/confirm",
        headers={"Authorization": f"Bearer {owner_token}"},
    )
    assert confirm.status_code == 200

    query = client.post(
        f"/me/buddies/{buddy['buddy_id']}/state-memory/query",
        headers={"Authorization": f"Bearer {owner_token}"},
        json={"question": "有鸡蛋吗"},
    )
    assert query.status_code == 200

    response = client.get(
        "/devices/device_body_auth_explicit_001/desired-state",
        headers=pairing_headers("pair-auth-device-explicit-001"),
    )

    assert response.status_code == 200
    body = response.json()
    assert body["revision"] == 9
    assert body["updated_at"] == "2026-06-22T00:05:00+00:00"
    assert body["state_memory"]["confirmed_items"] == [{"name": "存货", "quantity": 2.0, "unit": "件"}]
    assert body["state_memory"]["pending_proposal_count"] == 7
    assert body["proactive_hint"]["message"] == "Stored hint only."
    assert body["recent_activity"] == [
        {
            "kind": "query_answered",
            "summary": "Stored recent activity.",
            "created_at": "2026-06-22T00:05:00+00:00",
        }
    ]


def test_device_events_accept_all_p0_button_actions_without_executing_device_action() -> None:
    store = DeviceRegistry()
    client = make_client(store)
    pair_device(client)

    for event_type in ["approve", "reject", "ack", "manual_done"]:
        response = client.post(
            "/devices/device_body_001/events",
            headers=pairing_headers(),
            json={
                "event_type": event_type,
                "idempotency_key": f"event-{event_type}-001",
                "payload": {"source": "button"},
            },
        )
        assert response.status_code == 201
        assert response.json()["event_type"] == event_type

    assert [event.event_type for event in store.list_events("device_body_001")] == [
        "approve",
        "reject",
        "ack",
        "manual_done",
    ]


def test_device_event_duplicate_idempotency_returns_existing_event_without_append() -> None:
    store = DeviceRegistry()
    client = make_client(store)
    pair_device(client)

    first = client.post(
        "/devices/device_body_001/events",
        headers=pairing_headers(),
        json={"event_type": "approve", "idempotency_key": "event-approve-001", "payload": {"source": "button"}},
    )
    second = client.post(
        "/devices/device_body_001/events",
        headers=pairing_headers(),
        json={"event_type": "approve", "idempotency_key": "event-approve-001", "payload": {"source": "touch"}},
    )

    assert first.status_code == 201
    assert second.status_code == 201
    assert second.json() == first.json()
    assert len(store.list_events("device_body_001")) == 1


def test_device_events_reject_unpaired_device_and_secret_like_payload() -> None:
    client = make_client()

    unpaired = client.post(
        "/devices/missing_device/events",
        headers=pairing_headers(),
        json={"event_type": "approve", "idempotency_key": "event-001", "payload": {"source": "button"}},
    )
    assert unpaired.status_code == 404
    assert unpaired.json() == {"detail": {"code": "device_not_found"}}

    pair_device(client)
    missing_auth = client.post(
        "/devices/device_body_001/events",
        json={"event_type": "approve", "idempotency_key": "event-missing-auth-001", "payload": {"source": "button"}},
    )
    assert missing_auth.status_code == 401
    assert missing_auth.json() == {"detail": {"code": "device_auth_required"}}

    wrong_auth = client.post(
        "/devices/device_body_001/events",
        headers=pairing_headers("wrong-token"),
        json={"event_type": "approve", "idempotency_key": "event-wrong-auth-001", "payload": {"source": "button"}},
    )
    assert wrong_auth.status_code == 403
    assert wrong_auth.json() == {"detail": {"code": "device_auth_invalid"}}

    secret_payload = client.post(
        "/devices/device_body_001/events",
        headers=pairing_headers(),
        json={
            "event_type": "approve",
            "idempotency_key": "event-secret-001",
            "payload": {"nested": {"adapter_token": "plain-token"}},
        },
    )
    assert secret_payload.status_code == 422


def test_heartbeat_rejects_invalid_ranges_and_empty_firmware_version() -> None:
    client = make_client()
    pair_device(client)

    missing_auth = client.post(
        "/devices/device_body_001/heartbeat",
        json={
            "firmware_version": "0.1.0",
            "wifi_rssi": -55,
            "uptime_seconds": 300,
            "current_state": "idle",
            "idempotency_key": "hb-missing-auth",
        },
    )
    assert missing_auth.status_code == 401
    assert missing_auth.json() == {"detail": {"code": "device_auth_required"}}

    wrong_auth = client.post(
        "/devices/device_body_001/heartbeat",
        headers=pairing_headers("wrong-token"),
        json={
            "firmware_version": "0.1.0",
            "wifi_rssi": -55,
            "uptime_seconds": 300,
            "current_state": "idle",
            "idempotency_key": "hb-wrong-auth",
        },
    )
    assert wrong_auth.status_code == 403
    assert wrong_auth.json() == {"detail": {"code": "device_auth_invalid"}}

    for payload in [
        {
            "firmware_version": "",
            "wifi_rssi": -55,
            "uptime_seconds": 300,
            "current_state": "idle",
            "idempotency_key": "hb-empty-fw",
        },
        {
            "firmware_version": "0.1.0",
            "wifi_rssi": -128,
            "uptime_seconds": 300,
            "current_state": "idle",
            "idempotency_key": "hb-low-rssi",
        },
        {
            "firmware_version": "0.1.0",
            "wifi_rssi": 1,
            "uptime_seconds": 300,
            "current_state": "idle",
            "idempotency_key": "hb-high-rssi",
        },
        {
            "firmware_version": "0.1.0",
            "wifi_rssi": -55,
            "uptime_seconds": -1,
            "current_state": "idle",
            "idempotency_key": "hb-negative-uptime",
        },
    ]:
        response = client.post("/devices/device_body_001/heartbeat", headers=pairing_headers(), json=payload)
        assert response.status_code == 422


def test_heartbeat_duplicate_idempotency_returns_existing_heartbeat() -> None:
    client = make_client()
    pair_device(client)

    first = client.post(
        "/devices/device_body_001/heartbeat",
        headers=pairing_headers(),
        json={
            "firmware_version": "0.1.0",
            "wifi_rssi": -55,
            "uptime_seconds": 300,
            "current_state": "idle",
            "idempotency_key": "hb-001",
        },
    )
    second = client.post(
        "/devices/device_body_001/heartbeat",
        headers=pairing_headers(),
        json={
            "firmware_version": "0.1.0",
            "wifi_rssi": -10,
            "uptime_seconds": 999,
            "current_state": "error",
            "idempotency_key": "hb-001",
        },
    )

    assert first.status_code == 200
    assert second.status_code == 200
    assert second.json() == first.json()


def test_ota_check_is_read_only_and_reports_no_update_for_p0() -> None:
    client = make_client()
    pair_device(client)

    missing = client.get("/devices/device_body_001/ota/check")
    assert missing.status_code == 401
    assert missing.json() == {"detail": {"code": "device_auth_required"}}

    wrong = client.get("/devices/device_body_001/ota/check", headers=pairing_headers("wrong-token"))
    assert wrong.status_code == 403
    assert wrong.json() == {"detail": {"code": "device_auth_invalid"}}

    response = client.get("/devices/device_body_001/ota/check", headers=pairing_headers())

    assert response.status_code == 200
    assert response.json() == {
        "device_id": "device_body_001",
        "update_available": False,
        "current_version": "0.1.0",
        "target_version": None,
    }


def pair_device(client: TestClient) -> None:
    buddy = create_buddy(client)
    response = client.post(
        "/devices/device_body_001/pair",
        json=pair_payload(buddy),
    )
    assert response.status_code == 201


def create_buddy(client: TestClient, user_id: str = "user_demo") -> dict[str, object]:
    response = client.post("/buddies", json={"user_id": user_id})
    assert response.status_code == 201
    return response.json()


def register(client: TestClient, email: str) -> str:
    response = client.post("/auth/register", json={"email": email, "password": "correct horse battery staple"})
    assert response.status_code == 201
    return response.json()["access_token"]


def pair_payload(
    buddy: dict[str, object],
    owner_user_id: str = "user_demo",
    idempotency_key: str = "pair-001",
    pairing_token: str = "pair-token-001",
) -> dict[str, object]:
    return {
        "buddy_id": buddy["buddy_id"],
        "space_id": buddy["space_id"],
        "public_key": "device-public-key",
        "firmware_version": "0.1.0",
        "pairing_token": pairing_token,
        "agent_machine": {
            "agent_machine_id": "agent_machine_home_mac",
            "owner_user_id": owner_user_id,
            "machine_type": "local_mac",
            "endpoint": "https://agent-machine.example.test",
            "public_key": "agent-machine-public-key",
            "runtime_version": "0.1.0",
        },
        "idempotency_key": idempotency_key,
    }


def pairing_headers(pairing_token: str = "pair-token-001") -> dict[str, str]:
    return {"X-Buddys-Pairing-Token": pairing_token}
