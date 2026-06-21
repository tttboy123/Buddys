from fastapi.testclient import TestClient

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
    assert recent_activity[-1]["basis"]["item_names"] == ["牛奶"]
    assert "api_key" not in str(recent_activity).lower()
    assert "capabilities" not in str(recent_activity).lower()


def register(client: TestClient, email: str) -> str:
    response = client.post("/auth/register", json={"email": email, "password": "correct horse battery staple"})
    assert response.status_code == 201
    return response.json()["access_token"]
