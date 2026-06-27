from fastapi.testclient import TestClient

from buddys_api.device_models import AgentMachine, BuddyRuntimeBinding, Device, DeviceHeartbeat
from buddys_api.main import create_app
from buddys_api.providers.openai_compatible_provider import ProviderUsage, StateMemoryQueryUnderstanding
from buddys_api.state_memory_models import StateMemoryDelta


def test_console_experience_flow_contract_matches_auth_state_memory_path(tmp_path) -> None:
    app = create_app(db_path=tmp_path / "buddys.sqlite3")
    client = TestClient(app)
    token = register(client, "experience@example.com")
    buddy = client.post(
        "/me/buddies",
        headers={"Authorization": f"Bearer {token}"},
        json={"name": "Kitchen Buddy", "space_id": "kitchen"},
    ).json()

    capture = client.post(
        f"/me/buddies/{buddy['buddy_id']}/state-memory/captures/conversation",
        headers={"Authorization": f"Bearer {token}"},
        json={"content": "我买了五个鸡蛋和一包面粉"},
    )
    assert capture.status_code == 201
    proposal = capture.json()["proposal"]
    assert proposal["content"] == "我买了五个鸡蛋和一包面粉"
    assert proposal["deltas"][0]["item_name"] == "鸡蛋"
    assert proposal["unrecognized"] == ["一包面粉"]

    confirmed = client.post(
        f"/me/buddies/{buddy['buddy_id']}/state-memory/proposals/{proposal['proposal_id']}/confirm",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert confirmed.status_code == 200

    query = client.post(
        f"/me/buddies/{buddy['buddy_id']}/state-memory/query",
        headers={"Authorization": f"Bearer {token}"},
        json={"question": "有鸡蛋吗"},
    )
    assert query.status_code == 200

    snapshot = client.get("/sync/snapshot", headers={"Authorization": f"Bearer {token}"}).json()
    state_memory = snapshot["state_memory"]
    buddy_id = buddy["buddy_id"]

    assert [item["name"] for item in state_memory["items_by_buddy"][buddy_id]] == ["鸡蛋"]
    assert state_memory["pending_proposals_by_buddy"].get(buddy_id) is None
    assert state_memory["summary_by_buddy"][buddy_id]["confirmed_item_count"] == 1
    assert state_memory["latest_query_by_buddy"][buddy_id]["question"] == "有鸡蛋吗"
    assert state_memory["latest_query_by_buddy"][buddy_id]["evidence_items"][0]["name"] == "鸡蛋"
    assert state_memory["latest_query_by_buddy"][buddy_id]["evidence_items"][0]["source"] == "conversation"
    assert state_memory["latest_query_by_buddy"][buddy_id]["evidence_items"][0]["last_seen_at"]
    assert "proactive_hint_by_buddy" in state_memory


def test_console_experience_flow_saved_recipe_changes_missing_for_recipe_answer_and_snapshot(tmp_path) -> None:
    app = create_app(db_path=tmp_path / "buddys.sqlite3")
    client = TestClient(app)
    token = register(client, "recipe-console@example.com")
    buddy = client.post(
        "/me/buddies",
        headers={"Authorization": f"Bearer {token}"},
        json={"name": "Kitchen Buddy", "space_id": "kitchen"},
    ).json()

    for name in ("五花肉", "老抽"):
        app.state.state_memory_store.create_item(
            user_id=buddy["user_id"],
            buddy_id=buddy["buddy_id"],
            name=name,
            category="ingredient",
            quantity=1,
            unit="份",
            source="manual",
            confidence=1.0,
        )

    create_recipe = client.post(
        f"/me/buddies/{buddy['buddy_id']}/state-memory/recipes",
        headers={"Authorization": f"Bearer {token}"},
        json={"name": "红烧肉", "ingredients": ["五花肉", "老抽"]},
    )
    assert create_recipe.status_code == 201

    query = client.post(
        f"/me/buddies/{buddy['buddy_id']}/state-memory/query",
        headers={"Authorization": f"Bearer {token}"},
        json={"question": "能做红烧肉吗"},
    )
    assert query.status_code == 200

    snapshot = client.get("/sync/snapshot", headers={"Authorization": f"Bearer {token}"}).json()
    state_memory = snapshot["state_memory"]
    buddy_id = buddy["buddy_id"]

    assert state_memory["recipes_by_buddy"][buddy_id][0]["name"] == "红烧肉"
    assert [ingredient["name"] for ingredient in state_memory["recipes_by_buddy"][buddy_id][0]["ingredients"]] == [
        "五花肉",
        "老抽",
    ]
    assert state_memory["latest_query_by_buddy"][buddy_id]["summary"] == "做红烧肉的材料目前齐了。"
    assert state_memory["latest_query_by_buddy"][buddy_id]["missing_items"] == []


def test_console_experience_flow_supports_login_photo_capture_and_traceable_hint(
    tmp_path,
    monkeypatch,
) -> None:
    monkeypatch.setenv("BUDDYS_DEFAULT_OPENAI_API_KEY", "sk-system-default")
    app = create_app(db_path=tmp_path / "buddys.sqlite3")
    client = TestClient(app)
    register_response = client.post(
        "/auth/register",
        json={"email": "photo-experience@example.com", "password": "correct horse battery staple"},
    )
    assert register_response.status_code == 201

    login_response = client.post(
        "/auth/login",
        json={"email": "photo-experience@example.com", "password": "correct horse battery staple"},
    )
    assert login_response.status_code == 200
    token = login_response.json()["access_token"]

    buddy = client.post(
        "/me/buddies",
        headers={"Authorization": f"Bearer {token}"},
        json={"name": "Kitchen Buddy", "space_id": "kitchen"},
    ).json()

    class FakePhotoProvider:
        provider = "system-minimax-default"
        model = "MiniMax-M3"

        def parse_state_memory_capture(self, *, source, content, image_base64=None, image_media_type=None):
            return (
                [
                    StateMemoryDelta(
                        item_name="牛奶",
                        operation="upsert",
                        quantity=2,
                        unit="盒",
                        category="ingredient",
                        source=source,
                    )
                ],
                [],
            )

        def understand_state_memory_query(self, *, question):
            return StateMemoryQueryUnderstanding(
                answer_type="have_item",
                subject_name="牛奶",
                usage=ProviderUsage(input_tokens=9, output_tokens=7, estimated=False),
            )

    app.state.state_memory_service.provider_factory = lambda config: FakePhotoProvider()

    capture = client.post(
        f"/me/buddies/{buddy['buddy_id']}/state-memory/captures/photo",
        headers={"Authorization": f"Bearer {token}"},
        json={"content": "冰箱照片", "image_base64": "aGVsbG8=", "image_media_type": "image/png"},
    )
    assert capture.status_code == 201

    proposal_id = capture.json()["proposal"]["proposal_id"]
    confirm = client.post(
        f"/me/buddies/{buddy['buddy_id']}/state-memory/proposals/{proposal_id}/confirm",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert confirm.status_code == 200

    query = client.post(
        f"/me/buddies/{buddy['buddy_id']}/state-memory/query",
        headers={"Authorization": f"Bearer {token}"},
        json={"question": "有牛奶吗"},
    )
    assert query.status_code == 200

    snapshot = client.get("/sync/snapshot", headers={"Authorization": f"Bearer {token}"}).json()
    state_memory = snapshot["state_memory"]
    buddy_id = buddy["buddy_id"]
    latest_query = state_memory["latest_query_by_buddy"][buddy_id]
    hint = state_memory["proactive_hint_by_buddy"][buddy_id]
    recent_activity = state_memory["recent_activity_by_buddy"][buddy_id]

    assert latest_query["question"] == "有牛奶吗"
    assert latest_query["evidence_items"][0]["name"] == "牛奶"
    assert latest_query["evidence_items"][0]["source"] == "photo"
    assert latest_query["evidence_items"][0]["last_seen_at"]
    assert hint["kind"] == "consumption_inference"
    assert hint["basis"]["item_names"] == ["牛奶"]
    assert recent_activity
    assert recent_activity[-1]["kind"] == "query_answered"
    assert recent_activity[-1]["summary"] == "Buddy answered whether 牛奶 is still at home."
    assert recent_activity[-1]["basis"]["item_names"] == ["牛奶"]
    assert "api_key" not in str(recent_activity).lower()
    assert "capabilities" not in str(recent_activity).lower()


def test_console_experience_flow_founder_metrics_endpoints_succeed_for_founder_path(
    tmp_path,
    monkeypatch,
) -> None:
    monkeypatch.setenv("BUDDYS_FOUNDER_METRICS_EMAIL_ALLOWLIST", "founder@example.com")
    app = create_app(db_path=tmp_path / "buddys.sqlite3")
    client = TestClient(app)
    founder_token = register(client, "founder@example.com")
    buddy = client.post(
        "/me/buddies",
        headers={"Authorization": f"Bearer {founder_token}"},
        json={"name": "Kitchen Buddy", "space_id": "kitchen"},
    ).json()

    _complete_state_memory_cycle(client, token=founder_token, buddy_id=buddy["buddy_id"])

    engagement = client.get("/metrics/engagement", headers={"Authorization": f"Bearer {founder_token}"})
    retention = client.get("/metrics/retention-summary", headers={"Authorization": f"Bearer {founder_token}"})

    assert engagement.status_code == 200
    assert engagement.json()["activation"]["completed_first_capture_confirm_query"] is True
    assert retention.status_code == 200
    assert retention.json()["activated_users"] == 1


def test_console_experience_flow_non_founder_retention_path_stays_hidden_via_403_contract(
    tmp_path,
    monkeypatch,
) -> None:
    monkeypatch.setenv("BUDDYS_FOUNDER_METRICS_EMAIL_ALLOWLIST", "founder@example.com")
    client = TestClient(create_app(db_path=tmp_path / "buddys.sqlite3"))
    member_token = register(client, "member@example.com")

    response = client.get("/metrics/retention-summary", headers={"Authorization": f"Bearer {member_token}"})

    assert response.status_code == 403
    assert response.json() == {"detail": {"code": "founder_metrics_forbidden"}}


def test_console_experience_flow_owner_can_publish_device_desired_state_and_console_snapshot_sees_device_workspace(
    tmp_path,
) -> None:
    app = create_app(db_path=tmp_path / "buddys.sqlite3")
    client = TestClient(app)
    token = register(client, "device-console@example.com")
    buddy = client.post(
        "/me/buddies",
        headers={"Authorization": f"Bearer {token}"},
        json={"name": "Kitchen Buddy", "space_id": "kitchen"},
    ).json()

    app.state.device_store.pair_device(
        device=Device(
            device_id="device_body_console_001",
            buddy_id=buddy["buddy_id"],
            space_id=buddy["space_id"],
            public_key="device-public-key",
            pairing_state="paired",
            firmware_version="0.2.0-sim",
        ),
        agent_machine=AgentMachine(
            agent_machine_id="agent_machine_console_001",
            owner_user_id=buddy["user_id"],
            machine_type="local_mac",
            endpoint="https://agent-machine.example.test",
            public_key="agent-machine-public-key",
            runtime_version="0.2.0-sim",
            status="online",
        ),
        binding=BuddyRuntimeBinding(
            buddy_id=buddy["buddy_id"],
            agent_machine_id="agent_machine_console_001",
            role="primary",
        ),
        pairing_token="pair-console-001",
        idempotency_key="pair-console-001",
    )
    app.state.device_store.save_heartbeat(
        DeviceHeartbeat(
            device_id="device_body_console_001",
            firmware_version="0.2.0-sim",
            wifi_rssi=-58,
            uptime_seconds=600,
            current_state="idle",
            idempotency_key="hb-console-001",
        )
    )

    publish = client.post(
        f"/me/buddies/{buddy['buddy_id']}/devices/device_body_console_001/desired-state",
        headers={"Authorization": f"Bearer {token}"},
        json={"reminder_text": "Please confirm the pantry reminder."},
    )
    assert publish.status_code == 200

    snapshot = client.get("/sync/snapshot", headers={"Authorization": f"Bearer {token}"}).json()

    assert snapshot["devices"][0]["device_id"] == "device_body_console_001"
    assert snapshot["agent_machines"][0]["agent_machine_id"] == "agent_machine_console_001"
    assert snapshot["bindings"][0]["buddy_id"] == buddy["buddy_id"]
    assert snapshot["latest_heartbeats"]["device_body_console_001"]["wifi_rssi"] == -58
    assert snapshot["desired_states"]["device_body_console_001"]["state"] == "manual_required"
    assert snapshot["desired_states"]["device_body_console_001"]["display_text"] == "Please confirm the pantry reminder."
    assert snapshot["device_events"] == []


def _complete_state_memory_cycle(client: TestClient, *, token: str, buddy_id: str) -> None:
    capture = client.post(
        f"/me/buddies/{buddy_id}/state-memory/captures/voice",
        headers={"Authorization": f"Bearer {token}"},
        json={"content": "我买了五个鸡蛋"},
    )
    assert capture.status_code == 201
    proposal_id = capture.json()["proposal"]["proposal_id"]

    confirm = client.post(
        f"/me/buddies/{buddy_id}/state-memory/proposals/{proposal_id}/confirm",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert confirm.status_code == 200

    query = client.post(
        f"/me/buddies/{buddy_id}/state-memory/query",
        headers={"Authorization": f"Bearer {token}"},
        json={"question": "有鸡蛋吗"},
    )
    assert query.status_code == 200


def register(client: TestClient, email: str) -> str:
    response = client.post("/auth/register", json={"email": email, "password": "correct horse battery staple"})
    assert response.status_code == 201
    return response.json()["access_token"]
