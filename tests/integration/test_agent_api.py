from fastapi.testclient import TestClient

from buddys_api.main import create_app


def test_agent_api_requires_auth_and_scopes_agents_to_current_user(tmp_path) -> None:
    client = TestClient(create_app(db_path=tmp_path / "buddys.sqlite3"))
    owner_token = register(client, "owner@example.com")
    other_token = register(client, "other@example.com")

    unauth_create = client.post("/agents", json=valid_agent_payload())
    create_response = client.post(
        "/agents",
        headers={"Authorization": f"Bearer {owner_token}"},
        json=valid_agent_payload(),
    )
    assert unauth_create.status_code == 401
    assert create_response.status_code == 201

    agent = create_response.json()
    assert agent["agent_id"].startswith("agent_")
    assert agent["user_id"].startswith("user_")
    assert agent["role"] == "runtime"
    assert agent["status"] == "starting"
    assert agent["metadata"] == {"space_id": "home", "nested": {"safe": "yes"}}
    assert agent["capabilities"] == {"modes": ["sync"], "nested": [{}]}
    assert "sk-should-not-leak" not in str(agent)

    owner_list = client.get("/agents", headers={"Authorization": f"Bearer {owner_token}"})
    other_list = client.get("/agents", headers={"Authorization": f"Bearer {other_token}"})
    other_detail = client.get(
        f"/agents/{agent['agent_id']}",
        headers={"Authorization": f"Bearer {other_token}"},
    )

    assert owner_list.status_code == 200
    assert [item["agent_id"] for item in owner_list.json()["agents"]] == [agent["agent_id"]]
    assert other_list.status_code == 200
    assert other_list.json() == {"agents": []}
    assert other_detail.status_code == 404


def test_agent_api_omits_secret_like_values_from_http_responses(tmp_path) -> None:
    client = TestClient(create_app(db_path=tmp_path / "buddys.sqlite3"))
    token = register(client, "owner@example.com")

    create_response = client.post(
        "/agents",
        headers={"Authorization": f"Bearer {token}"},
        json=valid_agent_payload()
        | {
            "metadata": {
                "notes": "sk-safe-key-secret-sentinel",
                "debug_id": "sk-safe-key-sentinel-123456",
                "region": "local",
                "health": "ok",
                "enabled": True,
                "priority": 2,
            },
            "capabilities": {
                "labels": [
                    "safe-label",
                    "sk-safe-key-secret-sentinel",
                    "sk-safe-key-sentinel-123456",
                    "api_key sentinel",
                ],
                "modes": ["sync", "confirm"],
                "flags": [True, 7],
            },
        },
    )

    assert create_response.status_code == 201
    created = create_response.json()
    assert created["metadata"] == {"region": "local", "health": "ok", "enabled": True, "priority": 2}
    assert created["capabilities"] == {
        "labels": ["safe-label"],
        "modes": ["sync", "confirm"],
        "flags": [True, 7],
    }

    detail = client.get(
        f"/agents/{created['agent_id']}",
        headers={"Authorization": f"Bearer {token}"},
    ).json()
    listing = client.get("/agents", headers={"Authorization": f"Bearer {token}"}).json()
    for payload in (created, detail, listing):
        serialized = str(payload)
        assert "sk-safe-key-secret-sentinel" not in serialized
        assert "sk-safe-key-sentinel-123456" not in serialized
        assert "api_key sentinel" not in serialized


def test_agent_heartbeat_updates_only_owner_agent_and_emits_safe_sync_event(tmp_path) -> None:
    client = TestClient(create_app(db_path=tmp_path / "buddys.sqlite3"))
    owner_token = register(client, "owner@example.com")
    other_token = register(client, "other@example.com")
    agent = client.post(
        "/agents",
        headers={"Authorization": f"Bearer {owner_token}"},
        json=valid_agent_payload() | {"role": "hardware_simulator"},
    ).json()

    cross_user_heartbeat = client.post(
        f"/agents/{agent['agent_id']}/heartbeat",
        headers={"Authorization": f"Bearer {other_token}"},
        json={"status": "online"},
    )
    owner_heartbeat = client.post(
        f"/agents/{agent['agent_id']}/heartbeat",
        headers={"Authorization": f"Bearer {owner_token}"},
        json={
            "status": "degraded",
            "version": "0.4.1",
            "capabilities": {
                "simulates": ["heartbeat", "event"],
                "token": "token-should-not-leak",
                "nested": {"password": "password-should-not-leak", "safe": True},
            },
        },
    )

    assert cross_user_heartbeat.status_code == 404
    assert owner_heartbeat.status_code == 200
    updated = owner_heartbeat.json()
    assert updated["status"] == "degraded"
    assert updated["version"] == "0.4.1"
    assert updated["last_seen"] is not None
    assert updated["capabilities"] == {"simulates": ["heartbeat", "event"], "nested": {"safe": True}}

    events = client.get(
        "/sync/events",
        headers={"Authorization": f"Bearer {owner_token}"},
        params={"since_revision": 0},
    ).json()["events"]
    assert [event["event_type"] for event in events] == ["agent.created", "agent.heartbeat"]
    serialized = str(events).lower()
    assert "token-should-not-leak" not in serialized
    assert "password-should-not-leak" not in serialized
    assert "token" not in serialized
    assert "password" not in serialized


def test_agent_api_rejects_invalid_roles_statuses_and_raw_secret_fields(tmp_path) -> None:
    client = TestClient(create_app(db_path=tmp_path / "buddys.sqlite3"))
    token = register(client, "owner@example.com")

    invalid_role = client.post(
        "/agents",
        headers={"Authorization": f"Bearer {token}"},
        json=valid_agent_payload() | {"role": "super_admin"},
    )
    invalid_status = client.post(
        "/agents",
        headers={"Authorization": f"Bearer {token}"},
        json=valid_agent_payload() | {"status": "ready"},
    )
    raw_secret = client.post(
        "/agents",
        headers={"Authorization": f"Bearer {token}"},
        json=valid_agent_payload() | {"api_key": "sk-should-not-be-accepted"},
    )

    assert invalid_role.status_code == 422
    assert invalid_status.status_code == 422
    assert raw_secret.status_code == 422
    assert raw_secret.json() == {"detail": {"code": "raw_secret_fields_rejected", "fields": ["api_key"]}}
    assert "sk-should-not-be-accepted" not in str(raw_secret.json())


def valid_agent_payload() -> dict[str, object]:
    return {
        "name": "Runtime Agent",
        "role": "runtime",
        "status": "starting",
        "version": "0.4.0",
        "metadata": {
            "space_id": "home",
            "api_key": "sk-should-not-leak",
            "nested": {"safe": "yes", "private_key": "private-key-should-not-leak"},
        },
        "capabilities": {
            "modes": ["sync"],
            "nested": [{"public_key": "public-key-should-not-leak"}],
        },
    }


def register(client: TestClient, email: str) -> str:
    response = client.post("/auth/register", json={"email": email, "password": "correct horse battery staple"})
    assert response.status_code == 201
    return response.json()["access_token"]
