from fastapi.testclient import TestClient

from buddys_api.device_models import AgentMachine, BuddyRuntimeBinding, Device, DeviceDesiredState
from buddys_api.device_store import DeviceRegistry
from buddys_api.main import create_app
from tools.device_simulator import cli
from tools.device_simulator.state import build_device_event, build_heartbeat_payload, render_screen


def test_device_simulator_cli_pair_bootstraps_fresh_api_before_heartbeat_poll_and_event() -> None:
    store = DeviceRegistry()
    client = TestClient(create_app(device_store=store))

    def request_json(method: str, url: str, payload: dict[str, object] | None = None) -> dict[str, object]:
        path = url.removeprefix("http://runtime.test")
        response = client.request(method, path, json=payload)
        assert response.status_code < 400, response.text
        return response.json()

    assert (
        cli.main(
            [
                "pair",
                "--device-id",
                "dev_home_001",
                "--base-url",
                "http://runtime.test",
                "--user-id",
                "user_demo",
                "--pairing-token",
                "pair-token-cli-flow-001",
                "--idempotency-key",
                "pair-cli-flow-001",
            ],
            request_json=request_json,
        )
        == 0
    )
    assert store.get_device("dev_home_001").pairing_state == "paired"

    assert (
        cli.main(
            [
                "heartbeat",
                "--device-id",
                "dev_home_001",
                "--base-url",
                "http://runtime.test",
                "--idempotency-key",
                "hb-cli-flow-001",
            ],
            request_json=request_json,
        )
        == 0
    )
    assert store.get_latest_heartbeat("dev_home_001").current_state == "idle"

    assert cli.main(["poll", "--device-id", "dev_home_001", "--base-url", "http://runtime.test"], request_json=request_json) == 0
    assert (
        cli.main(
            [
                "event",
                "--device-id",
                "dev_home_001",
                "--base-url",
                "http://runtime.test",
                "--type",
                "ack",
                "--idempotency-key",
                "event-cli-flow-001",
            ],
            request_json=request_json,
        )
        == 0
    )
    assert [event.event_type for event in store.list_events("dev_home_001")] == ["ack"]


def test_device_simulator_pairs_heartbeats_polls_renders_and_submits_manual_done() -> None:
    store = DeviceRegistry()
    client = TestClient(create_app(device_store=store))
    buddy = create_buddy(client)

    pair_response = client.post("/devices/device_body_sim_001/pair", json=pair_payload(buddy))
    assert pair_response.status_code == 201

    heartbeat_payload = build_heartbeat_payload(
        firmware_version="0.2.0-sim",
        current_state="idle",
        uptime_ms=42_000,
        wifi_rssi=-54,
        idempotency_key="hb-sim-001",
    )
    heartbeat_response = client.post("/devices/device_body_sim_001/heartbeat", json=heartbeat_payload)
    assert heartbeat_response.status_code == 200
    assert heartbeat_response.json()["current_state"] == "idle"
    assert store.get_latest_heartbeat("device_body_sim_001").uptime_seconds == 42

    store.set_desired_state(
        DeviceDesiredState(
            device_id="device_body_sim_001",
            state="manual_required",
            revision=5,
            display_text="Manual action needed",
            manual_required=True,
            user_instruction="Press the physical button after dimming the light.",
            source_trace_id="trace_sim_001",
            updated_at="2024-01-01T00:00:00+00:00",
        )
    )
    desired_response = client.get("/devices/device_body_sim_001/desired-state")
    assert desired_response.status_code == 200

    screen = render_screen(desired_response.json())
    assert "manual_required" in screen
    assert "Press the physical button after dimming the light." in screen
    assert "sync: stale @ 2024-01-01T00:00:00+00:00" in screen
    assert "trace_sim_001" in screen

    event_payload = build_device_event(
        "manual_done",
        idempotency_key="event-manual-done-sim-001",
        payload={"source": "simulator"},
    )
    event_response = client.post("/devices/device_body_sim_001/events", json=event_payload)
    assert event_response.status_code == 201
    assert event_response.json()["event_type"] == "manual_done"
    assert [event.event_type for event in store.list_events("device_body_sim_001")] == ["manual_done"]


def test_device_simulator_renders_hardware_side_state_memory_summary_from_explicit_desired_state(tmp_path) -> None:
    app = create_app(device_store=DeviceRegistry(), db_path=tmp_path / "buddys.sqlite3")
    client = TestClient(app)
    token = register(client, "device-sim@example.com")
    buddy = client.post(
        "/me/buddies",
        headers={"Authorization": f"Bearer {token}"},
        json={"name": "Kitchen Buddy", "space_id": "kitchen"},
    ).json()

    store = app.state.device_store
    store.pair_device(
        device=Device(
            device_id="device_body_sim_001",
            buddy_id=buddy["buddy_id"],
            space_id=buddy["space_id"],
            public_key="device-public-key",
            pairing_state="paired",
            firmware_version="0.2.0-sim",
        ),
        agent_machine=AgentMachine(
            agent_machine_id="agent_machine_home_mac",
            owner_user_id=buddy["user_id"],
            machine_type="local_mac",
            endpoint="https://agent-machine.example.test",
            public_key="agent-machine-public-key",
            runtime_version="0.1.0",
            status="online",
        ),
        binding=BuddyRuntimeBinding(
            buddy_id=buddy["buddy_id"],
            agent_machine_id="agent_machine_home_mac",
            role="primary",
        ),
        pairing_token="pair-token-sim-auth-001",
        idempotency_key="pair-sim-auth-001",
    )

    store.set_desired_state(
        DeviceDesiredState(
            device_id="device_body_sim_001",
            state="manual_required",
            revision=6,
            display_text="Manual action needed",
            manual_required=True,
            user_instruction="Press the physical button after checking the pantry.",
            source_trace_id="trace_sim_002",
            state_memory={
                "confirmed_items": [
                    {"name": "鸡蛋", "quantity": 5, "unit": "个"},
                    {"name": "牛奶", "quantity": 1, "unit": "盒"},
                ],
                "pending_proposal_count": 1,
            },
            proactive_hint={
                "kind": "consumption_inference",
                "message": "Buddy thinks 鸡蛋 might be running low.",
                "item_names": ["鸡蛋"],
            },
            recent_activity=[
                {
                    "kind": "query_answered",
                    "summary": "还有鸡蛋。",
                    "created_at": "2026-06-22T00:00:00+00:00",
                }
            ],
        )
    )
    desired_state = client.get("/devices/device_body_sim_001/desired-state").json()

    screen = render_screen(desired_state)

    assert "manual_required" in screen
    assert "Press the physical button after checking the pantry." in screen
    assert "pantry: 鸡蛋 5个, 牛奶 1盒" in screen
    assert "pending: 1 proposal(s)" in screen
    assert "hint:" in screen
    assert "recent: 还有鸡蛋。" in screen
    assert "trace_sim_002" in screen


def create_buddy(client: TestClient) -> dict[str, object]:
    response = client.post("/buddies", json={"user_id": "user_demo"})
    assert response.status_code == 201
    return response.json()


def pair_payload(buddy: dict[str, object]) -> dict[str, object]:
    return owned_pair_payload(buddy, owner_user_id="user_demo")


def owned_pair_payload(buddy: dict[str, object], owner_user_id: str) -> dict[str, object]:
    return {
        "buddy_id": buddy["buddy_id"],
        "space_id": buddy["space_id"],
        "public_key": "device-public-key",
        "firmware_version": "0.2.0-sim",
        "pairing_token": "pair-token-sim-001",
        "agent_machine": {
            "agent_machine_id": "agent_machine_home_mac",
            "owner_user_id": owner_user_id,
            "machine_type": "local_mac",
            "endpoint": "https://agent-machine.example.test",
            "public_key": "agent-machine-public-key",
            "runtime_version": "0.1.0",
        },
        "idempotency_key": "pair-sim-001",
    }


def register(client: TestClient, email: str) -> str:
    response = client.post("/auth/register", json={"email": email, "password": "correct horse battery staple"})
    assert response.status_code == 201
    return response.json()["access_token"]
