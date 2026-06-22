from fastapi.testclient import TestClient
from types import SimpleNamespace

from buddys_api.device_models import AgentMachine, BuddyRuntimeBinding, Device, DeviceDesiredState
from buddys_api.main import create_app


def test_sync_snapshot_and_events_do_not_leak_sensitive_trace_or_pairing_payloads(tmp_path) -> None:
    client = TestClient(create_app(db_path=tmp_path / "buddys.sqlite3"))

    buddy = client.post("/buddies", json={"user_id": "user_demo"}).json()
    message_response = client.post(
        f"/buddies/{buddy['buddy_id']}/messages",
        json={
            "user_id": "user_demo",
            "message": "SECRET_TOKEN=abc123 raw private message 把客厅灯调暗",
        },
    )
    assert message_response.status_code == 200

    pair_response = client.post(
        "/devices/device_body_sensitive/pair",
        json={
            "buddy_id": buddy["buddy_id"],
            "space_id": buddy["space_id"],
            "public_key": "public-key-should-not-sync",
            "firmware_version": "0.1.0",
            "pairing_token": "pairing-token-should-not-sync",
            "agent_machine": {
                "agent_machine_id": "agent_machine_sensitive",
                "owner_user_id": "user_demo",
                "machine_type": "local_mac",
                "endpoint": "https://agent-machine.example.test",
                "public_key": "public-key-should-not-sync",
                "runtime_version": "0.1.0",
            },
            "idempotency_key": "pair-sensitive-sync-001",
        },
    )
    assert pair_response.status_code == 201

    snapshot_response = client.get("/sync/snapshot")
    events_response = client.get("/sync/events", params={"since_revision": 0})
    assert snapshot_response.status_code == 200
    assert events_response.status_code == 200

    snapshot = snapshot_response.json()
    events = events_response.json()
    trace_summary = snapshot["traces"][0]
    assert trace_summary["trace_id"] == message_response.json()["trace_id"]
    assert trace_summary["proposal_id"] == message_response.json()["proposal_id"]
    assert set(trace_summary) == {
        "trace_id",
        "buddy_id",
        "space_id",
        "device_id",
        "turn_id",
        "proposal_id",
        "requires_confirmation",
        "permission_policy_result",
        "tool_result_status",
        "cost_refs",
        "created_at",
        "updated_at",
    }

    for sync_payload in (snapshot, events):
        serialized = str(sync_payload)
        for forbidden in (
            "SECRET_TOKEN",
            "abc123",
            "raw private message",
            "pairing-token-should-not-sync",
            "public-key-should-not-sync",
        ):
            assert forbidden not in serialized


def test_sync_snapshot_and_events_include_legacy_runtime_device_trace_and_cost_state(tmp_path) -> None:
    client = TestClient(create_app(db_path=tmp_path / "buddys.sqlite3"))

    initial_snapshot = client.get("/sync/snapshot")
    assert initial_snapshot.status_code == 200
    assert initial_snapshot.json()["state_revision"] == 0

    buddy = client.post("/buddies", json={"user_id": "user_demo"}).json()
    message = client.post(
        f"/buddies/{buddy['buddy_id']}/messages",
        json={"user_id": "user_demo", "message": "把客厅灯调暗"},
    ).json()
    confirm = client.post(f"/proposals/{message['proposal_id']}/confirm", json={"approved": True}).json()
    pair_response = client.post("/devices/device_body_001/pair", json=pair_payload(buddy))
    assert pair_response.status_code == 201
    heartbeat_response = client.post(
        "/devices/device_body_001/heartbeat",
        headers=pairing_headers("pair-token-sync-001"),
        json={
            "firmware_version": "0.1.0",
            "wifi_rssi": -55,
            "uptime_seconds": 300,
            "current_state": "idle",
            "idempotency_key": "hb-sync-001",
        },
    )
    assert heartbeat_response.status_code == 200
    event_response = client.post(
        "/devices/device_body_001/events",
        headers=pairing_headers("pair-token-sync-001"),
        json={"event_type": "ack", "idempotency_key": "event-sync-001", "payload": {"source": "button"}},
    )
    assert event_response.status_code == 201

    snapshot_response = client.get("/sync/snapshot")
    assert snapshot_response.status_code == 200
    snapshot = snapshot_response.json()
    assert snapshot["state_revision"] >= 6
    assert snapshot["buddies"][0]["buddy_id"] == buddy["buddy_id"]
    assert snapshot["devices"][0]["device_id"] == "device_body_001"
    assert snapshot["agent_machines"][0]["agent_machine_id"] == "agent_machine_home_mac"
    assert snapshot["bindings"][0]["buddy_id"] == buddy["buddy_id"]
    assert snapshot["latest_heartbeats"]["device_body_001"]["current_state"] == "idle"
    assert snapshot["desired_states"]["device_body_001"]["state"] == "idle"
    assert snapshot["device_events"][0]["event_type"] == "ack"
    assert snapshot["traces"][0]["trace_id"] == confirm["trace_id"]
    assert snapshot["cost_summary"]["event_count"] == 1
    assert snapshot["cost_summary"]["total_tokens"] > 0
    assert snapshot["plan_usage"]["user_id"] == "user_demo"
    assert snapshot["plan_usage"]["plan_id"] == "free"
    assert snapshot["plan_usage"]["used_tokens"] == snapshot["cost_summary"]["total_tokens"]
    assert "api_key" not in str(snapshot["plan_usage"]).lower()
    assert snapshot["agents"] == []

    events_response = client.get("/sync/events", params={"since_revision": 0})
    assert events_response.status_code == 200
    event_feed = events_response.json()
    revisions = [event["revision"] for event in event_feed["events"]]
    assert revisions == sorted(revisions)
    assert len(revisions) == len(set(revisions))
    assert event_feed["state_revision"] == revisions[-1]
    assert {
        "buddy.created",
        "message.proposal_created",
        "proposal.confirmed",
        "device.paired",
        "device.heartbeat",
        "device.event",
    }.issubset({event["event_type"] for event in event_feed["events"]})

    later_events = client.get("/sync/events", params={"since_revision": revisions[-2]}).json()["events"]
    assert [event["revision"] for event in later_events] == [revisions[-1]]
    assert "pairing_token" not in str(event_feed).lower()
    assert "public_key" not in str(event_feed).lower()


def test_sync_snapshot_device_runtime_state_survives_restart_without_leaking_pairing_token(tmp_path) -> None:
    db_path = tmp_path / "buddys.sqlite3"
    app = create_app(db_path=db_path)
    client = TestClient(app)

    buddy = client.post("/buddies", json={"user_id": "user_demo"}).json()
    pair_response = client.post("/devices/device_body_restart_sync_001/pair", json={
        "buddy_id": buddy["buddy_id"],
        "space_id": buddy["space_id"],
        "public_key": "device-public-key",
        "firmware_version": "0.1.0",
        "pairing_token": "pair-token-restart-sync-001",
        "agent_machine": {
            "agent_machine_id": "agent_machine_restart_sync_001",
            "owner_user_id": "user_demo",
            "machine_type": "local_mac",
            "endpoint": "https://agent-machine.example.test",
            "public_key": "agent-machine-public-key",
            "runtime_version": "0.1.0",
        },
        "idempotency_key": "pair-restart-sync-001",
    })
    assert pair_response.status_code == 201
    heartbeat_response = client.post(
        "/devices/device_body_restart_sync_001/heartbeat",
        headers=pairing_headers("pair-token-restart-sync-001"),
        json={
            "firmware_version": "0.1.0",
            "wifi_rssi": -55,
            "uptime_seconds": 300,
            "current_state": "idle",
            "idempotency_key": "hb-restart-sync-001",
        },
    )
    assert heartbeat_response.status_code == 200
    event_response = client.post(
        "/devices/device_body_restart_sync_001/events",
        headers=pairing_headers("pair-token-restart-sync-001"),
        json={"event_type": "ack", "idempotency_key": "event-restart-sync-001", "payload": {"source": "button"}},
    )
    assert event_response.status_code == 201
    app.state.device_store.set_desired_state(
        DeviceDesiredState(
            device_id="device_body_restart_sync_001",
            state="manual_required",
            revision=8,
            display_text="Restart snapshot state",
            manual_required=True,
            user_instruction="Persisted for sync snapshot.",
            source_trace_id="trace_restart_sync_001",
            updated_at="2026-06-22T01:20:00+00:00",
        )
    )
    app.state.db.close()

    reopened = create_app(db_path=db_path)
    reopened_client = TestClient(reopened)

    snapshot_response = reopened_client.get("/sync/snapshot")
    events_response = reopened_client.get("/sync/events", params={"since_revision": 0})
    assert snapshot_response.status_code == 200
    assert events_response.status_code == 200

    snapshot = snapshot_response.json()
    event_feed = events_response.json()
    assert snapshot["devices"][0]["device_id"] == "device_body_restart_sync_001"
    assert snapshot["agent_machines"][0]["agent_machine_id"] == "agent_machine_restart_sync_001"
    assert snapshot["bindings"][0]["buddy_id"] == buddy["buddy_id"]
    assert snapshot["latest_heartbeats"]["device_body_restart_sync_001"]["current_state"] == "idle"
    assert snapshot["desired_states"]["device_body_restart_sync_001"]["revision"] == 8
    assert snapshot["device_events"][0]["event_type"] == "ack"
    assert "pairing_token" not in str(snapshot).lower()
    assert "pairing_token" not in str(event_feed).lower()


def test_sync_snapshot_and_events_do_not_leak_auth_owned_buddies_to_unauthenticated_clients(tmp_path) -> None:
    client = TestClient(create_app(db_path=tmp_path / "buddys.sqlite3"))
    owner_token = register(client, "owner@example.com")
    other_token = register(client, "other@example.com")

    auth_buddy_response = client.post(
        "/me/buddies",
        headers={"Authorization": f"Bearer {owner_token}"},
        json={"name": "Private Buddy", "space_id": "study"},
    )
    assert auth_buddy_response.status_code == 201
    private_buddy = auth_buddy_response.json()
    legacy_buddy = client.post("/buddies", json={"user_id": "legacy_user"}).json()

    unauth_snapshot = client.get("/sync/snapshot").json()
    assert [buddy["buddy_id"] for buddy in unauth_snapshot["buddies"]] == [legacy_buddy["buddy_id"]]
    assert private_buddy["buddy_id"] not in str(unauth_snapshot)

    owner_snapshot = client.get("/sync/snapshot", headers={"Authorization": f"Bearer {owner_token}"}).json()
    assert [buddy["buddy_id"] for buddy in owner_snapshot["buddies"]] == [private_buddy["buddy_id"]]
    assert legacy_buddy["buddy_id"] not in str(owner_snapshot)

    other_snapshot = client.get("/sync/snapshot", headers={"Authorization": f"Bearer {other_token}"}).json()
    assert other_snapshot["buddies"] == []
    assert private_buddy["buddy_id"] not in str(other_snapshot)

    unauth_events = client.get("/sync/events", params={"since_revision": 0}).json()["events"]
    assert [event["event_type"] for event in unauth_events] == ["buddy.created"]
    assert private_buddy["buddy_id"] not in str(unauth_events)

    owner_events = client.get(
        "/sync/events",
        params={"since_revision": 0},
        headers={"Authorization": f"Bearer {owner_token}"},
    ).json()["events"]
    assert [event["event_type"] for event in owner_events] == ["buddy.created"]
    assert owner_events[0]["entity_id"] == private_buddy["buddy_id"]
    assert legacy_buddy["buddy_id"] not in str(owner_events)


def test_sync_snapshot_with_null_session_token_hash_degrades_to_401_not_500(tmp_path) -> None:
    app = create_app(db_path=tmp_path / "buddys.sqlite3")
    client = TestClient(app)
    app.state.auth_store.connection = SimpleNamespace(
        execute=lambda *_args, **_kwargs: SimpleNamespace(
            fetchall=lambda: [
                {
                    "session_id": "sess_legacy_null_hash",
                    "token_hash": None,
                    "user_id": "user_legacy",
                    "email": "legacy@example.com",
                    "display_name": None,
                    "created_at": "2026-06-22T00:00:00+00:00",
                }
            ]
        )
    )

    response = client.get("/sync/snapshot", headers={"Authorization": "Bearer stale-browser-token"})

    assert response.status_code == 401
    assert response.json() == {"detail": {"code": "invalid_or_expired_token"}}


def test_auth_desired_state_write_advances_sync_revision_and_keeps_event_summary_structural_only(tmp_path) -> None:
    app = create_app(db_path=tmp_path / "buddys.sqlite3")
    client = TestClient(app)
    owner_token = register(client, "owner-device-sync@example.com")
    buddy = client.post(
        "/me/buddies",
        headers={"Authorization": f"Bearer {owner_token}"},
        json={"name": "Kitchen Buddy", "space_id": "kitchen"},
    ).json()

    app.state.device_store.pair_device(
        device=Device(
            device_id="device_body_auth_sync_001",
            buddy_id=buddy["buddy_id"],
            space_id=buddy["space_id"],
            public_key="device-public-key",
            pairing_state="paired",
            firmware_version="0.2.0-sim",
        ),
        agent_machine=AgentMachine(
            agent_machine_id="agent_machine_auth_sync_001",
            owner_user_id=buddy["user_id"],
            machine_type="local_mac",
            endpoint="https://agent-machine.example.test",
            public_key="agent-machine-public-key",
            runtime_version="0.2.0-sim",
            status="online",
        ),
        binding=BuddyRuntimeBinding(
            buddy_id=buddy["buddy_id"],
            agent_machine_id="agent_machine_auth_sync_001",
            role="primary",
        ),
        pairing_token="pair-auth-sync-001",
        idempotency_key="pair-auth-sync-001",
    )

    before_snapshot = client.get("/sync/snapshot", headers={"Authorization": f"Bearer {owner_token}"}).json()
    response = client.post(
        f"/me/buddies/{buddy['buddy_id']}/devices/device_body_auth_sync_001/desired-state",
        headers={"Authorization": f"Bearer {owner_token}"},
        json={"reminder_text": "Please close the freezer door."},
    )
    assert response.status_code == 200

    snapshot = client.get("/sync/snapshot", headers={"Authorization": f"Bearer {owner_token}"}).json()
    event_feed = client.get(
        "/sync/events",
        params={"since_revision": before_snapshot["state_revision"]},
        headers={"Authorization": f"Bearer {owner_token}"},
    ).json()

    assert snapshot["state_revision"] > before_snapshot["state_revision"]
    assert snapshot["desired_states"]["device_body_auth_sync_001"]["state"] == "manual_required"
    assert snapshot["desired_states"]["device_body_auth_sync_001"]["revision"] == 1
    assert snapshot["desired_states"]["device_body_auth_sync_001"]["display_text"] == "Please close the freezer door."
    assert snapshot["desired_states"]["device_body_auth_sync_001"]["source_trace_id"] is None
    assert snapshot["desired_states"]["device_body_auth_sync_001"]["state_memory"] is None
    assert snapshot["desired_states"]["device_body_auth_sync_001"]["proactive_hint"] is None
    assert snapshot["desired_states"]["device_body_auth_sync_001"]["recent_activity"] == []
    assert event_feed["events"][-1]["event_type"] == "device.desired_state_updated"
    assert event_feed["events"][-1]["entity_id"] == "device_body_auth_sync_001"
    assert event_feed["events"][-1]["payload_summary"] == {
        "buddy_id": buddy["buddy_id"],
        "device_id": "device_body_auth_sync_001",
        "has_display_text": True,
        "has_user_instruction": True,
        "manual_required": True,
        "revision": 1,
        "state": "manual_required",
    }
    assert "Please close the freezer door." not in str(event_feed)


def test_sync_snapshot_rehydrates_legacy_runtime_trace_and_cost_after_restart(tmp_path) -> None:
    db_path = tmp_path / "buddys.sqlite3"
    first_client = TestClient(create_app(db_path=db_path))

    buddy = first_client.post("/buddies", json={"user_id": "user_demo"}).json()
    message = first_client.post(
        f"/buddies/{buddy['buddy_id']}/messages",
        json={"user_id": "user_demo", "message": "把客厅灯调暗"},
    ).json()
    confirm = first_client.post(f"/proposals/{message['proposal_id']}/confirm", json={"approved": True}).json()

    assert first_client.get(f"/traces/{confirm['trace_id']}").status_code == 200
    assert len(first_client.get("/cost-events").json()["cost_events"]) == 1
    first_client.close()

    second_client = TestClient(create_app(db_path=db_path))

    trace_response = second_client.get(f"/traces/{confirm['trace_id']}")
    cost_events = second_client.get("/cost-events").json()["cost_events"]
    snapshot = second_client.get("/sync/snapshot").json()

    assert trace_response.status_code == 200
    assert trace_response.json()["trace_id"] == confirm["trace_id"]
    assert len(cost_events) == 1
    assert cost_events[0]["trace_id"] == confirm["trace_id"]
    assert snapshot["traces"][0]["trace_id"] == confirm["trace_id"]
    assert snapshot["cost_summary"]["event_count"] == 1
    assert snapshot["cost_summary"]["total_tokens"] > 0


def test_sync_snapshot_includes_owner_agents_but_not_for_unauthenticated_or_other_users(tmp_path) -> None:
    client = TestClient(create_app(db_path=tmp_path / "buddys.sqlite3"))
    owner_token = register(client, "owner@example.com")
    other_token = register(client, "other@example.com")
    agent_response = client.post(
        "/agents",
        headers={"Authorization": f"Bearer {owner_token}"},
        json={
            "name": "Verifier Agent",
            "role": "verifier",
            "status": "online",
            "version": "0.4.0",
            "metadata": {"suite": "phase4", "api_key": "sk-should-not-sync"},
            "capabilities": {"checks": ["isolation"], "public_key": "public-key-should-not-sync"},
        },
    )
    assert agent_response.status_code == 201
    agent = agent_response.json()

    unauth_snapshot = client.get("/sync/snapshot").json()
    owner_snapshot = client.get("/sync/snapshot", headers={"Authorization": f"Bearer {owner_token}"}).json()
    other_snapshot = client.get("/sync/snapshot", headers={"Authorization": f"Bearer {other_token}"}).json()

    assert unauth_snapshot["agents"] == []
    assert other_snapshot["agents"] == []
    assert len(owner_snapshot["agents"]) == 1
    assert owner_snapshot["agents"][0]["agent_id"] == agent["agent_id"]
    assert owner_snapshot["agents"][0]["metadata"] == {"suite": "phase4"}
    assert owner_snapshot["agents"][0]["capabilities"] == {"checks": ["isolation"]}

    for snapshot in (unauth_snapshot, owner_snapshot, other_snapshot):
        serialized = str(snapshot)
        assert "sk-should-not-sync" not in serialized
        assert "public-key-should-not-sync" not in serialized
        assert "api_key" not in serialized.lower()
        assert "public_key" not in serialized.lower()


def test_sync_snapshot_and_events_omit_agent_secret_like_values(tmp_path) -> None:
    client = TestClient(create_app(db_path=tmp_path / "buddys.sqlite3"))
    owner_token = register(client, "owner@example.com")
    agent_response = client.post(
        "/agents",
        headers={"Authorization": f"Bearer {owner_token}"},
        json={
            "name": "Verifier Agent",
            "role": "verifier",
            "status": "online",
            "version": "0.4.0",
            "metadata": {
                "notes": "sk-safe-key-secret-sentinel",
                "debug_id": "sk-safe-key-sentinel-123456",
                "region": "local",
                "health": "ok",
            },
            "capabilities": {
                "labels": [
                    "safe-label",
                    "sk-safe-key-secret-sentinel",
                    "sk-safe-key-sentinel-123456",
                    "password sentinel",
                ],
                "flags": [True, 7],
            },
        },
    )
    assert agent_response.status_code == 201

    snapshot = client.get("/sync/snapshot", headers={"Authorization": f"Bearer {owner_token}"}).json()
    events = client.get(
        "/sync/events",
        headers={"Authorization": f"Bearer {owner_token}"},
        params={"since_revision": 0},
    ).json()

    assert snapshot["agents"][0]["metadata"] == {"region": "local", "health": "ok"}
    assert snapshot["agents"][0]["capabilities"] == {"labels": ["safe-label"], "flags": [True, 7]}
    for payload in (snapshot, events):
        serialized = str(payload)
        assert "sk-safe-key-secret-sentinel" not in serialized
        assert "sk-safe-key-sentinel-123456" not in serialized
        assert "password sentinel" not in serialized


def register(client: TestClient, email: str) -> str:
    response = client.post("/auth/register", json={"email": email, "password": "correct horse battery staple"})
    assert response.status_code == 201
    return response.json()["access_token"]


def pairing_headers(pairing_token: str = "pair-token-001") -> dict[str, str]:
    return {"X-Buddys-Pairing-Token": pairing_token}


def pair_payload(buddy: dict[str, object]) -> dict[str, object]:
    return {
        "buddy_id": buddy["buddy_id"],
        "space_id": buddy["space_id"],
        "public_key": "device-public-key",
        "firmware_version": "0.1.0",
        "pairing_token": "pair-token-sync-001",
        "agent_machine": {
            "agent_machine_id": "agent_machine_home_mac",
            "owner_user_id": "user_demo",
            "machine_type": "local_mac",
            "endpoint": "https://agent-machine.example.test",
            "public_key": "agent-machine-public-key",
            "runtime_version": "0.1.0",
        },
        "idempotency_key": "pair-sync-001",
    }
