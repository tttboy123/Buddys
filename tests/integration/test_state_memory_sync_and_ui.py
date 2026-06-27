from fastapi.testclient import TestClient
from datetime import datetime, timedelta, timezone

from buddys_api.main import create_app
from buddys_api.providers.openai_compatible_provider import ProviderUsage, StateMemoryQueryUnderstanding
from buddys_api.state_memory_models import StateMemoryDelta


def test_sync_snapshot_exposes_owner_only_state_memory_projection_and_keeps_existing_revision_model(
    tmp_path,
) -> None:
    app = create_app(db_path=tmp_path / "buddys.sqlite3")
    client = TestClient(app)
    owner_token = register(client, "owner@example.com")
    other_token = register(client, "other@example.com")
    buddy = client.post(
        "/me/buddies",
        headers={"Authorization": f"Bearer {owner_token}"},
        json={"name": "Kitchen Buddy", "space_id": "kitchen"},
    ).json()

    confirmed_capture = client.post(
        f"/me/buddies/{buddy['buddy_id']}/state-memory/captures/voice",
        headers={"Authorization": f"Bearer {owner_token}"},
        json={"content": "我买了五个鸡蛋"},
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

    owner_snapshot = client.get("/sync/snapshot", headers={"Authorization": f"Bearer {owner_token}"}).json()
    other_snapshot = client.get("/sync/snapshot", headers={"Authorization": f"Bearer {other_token}"}).json()
    unauth_snapshot = client.get("/sync/snapshot").json()

    owner_state_memory = owner_snapshot["state_memory"]
    buddy_id = buddy["buddy_id"]
    assert owner_snapshot["state_revision"] == pending_capture.json()["state_revision"]
    assert [item["name"] for item in owner_state_memory["items_by_buddy"][buddy_id]] == ["鸡蛋"]
    assert [proposal["content"] for proposal in owner_state_memory["pending_proposals_by_buddy"][buddy_id]] == [
        "香料用完了"
    ]
    assert owner_state_memory["summary_by_buddy"][buddy_id]["confirmed_item_count"] == 1
    assert owner_state_memory["summary_by_buddy"][buddy_id]["pending_proposal_count"] == 1
    assert owner_state_memory["latest_query_by_buddy"][buddy_id]["summary"] == "还有鸡蛋。"
    assert owner_state_memory["latest_query_by_buddy"][buddy_id]["question"] == "有鸡蛋吗"
    assert owner_state_memory["latest_query_by_buddy"][buddy_id]["evidence_item_ids"]
    assert owner_state_memory["latest_query_by_buddy"][buddy_id]["evidence_items"][0]["name"] == "鸡蛋"

    assert other_snapshot["state_memory"] == {
        "items_by_buddy": {},
        "pending_proposals_by_buddy": {},
        "recipes_by_buddy": {},
        "summary_by_buddy": {},
        "latest_query_by_buddy": {},
        "proactive_hint_by_buddy": {},
        "recent_activity_by_buddy": {},
    }
    assert unauth_snapshot["state_memory"] == {
        "items_by_buddy": {},
        "pending_proposals_by_buddy": {},
        "recipes_by_buddy": {},
        "summary_by_buddy": {},
        "latest_query_by_buddy": {},
        "proactive_hint_by_buddy": {},
        "recent_activity_by_buddy": {},
    }
    assert buddy_id not in str(other_snapshot)
    assert buddy_id not in str(unauth_snapshot)


def register(client: TestClient, email: str) -> str:
    response = client.post("/auth/register", json={"email": email, "password": "correct horse battery staple"})
    assert response.status_code == 201
    return response.json()["access_token"]


def test_sync_snapshot_projects_single_traceable_proactive_memory_hint(tmp_path) -> None:
    app = create_app(db_path=tmp_path / "buddys.sqlite3")
    client = TestClient(app)
    token = register(client, "owner@example.com")
    buddy = client.post(
        "/me/buddies",
        headers={"Authorization": f"Bearer {token}"},
        json={"name": "Kitchen Buddy", "space_id": "kitchen"},
    ).json()

    app.state.state_memory_store.create_item(
        user_id=buddy["user_id"],
        buddy_id=buddy["buddy_id"],
        name="鸡蛋",
        category="ingredient",
        quantity=1,
        unit="个",
        source="manual",
        confidence=1.0,
    )

    snapshot = client.get("/sync/snapshot", headers={"Authorization": f"Bearer {token}"}).json()
    hint = snapshot["state_memory"]["proactive_hint_by_buddy"][buddy["buddy_id"]]

    assert hint["message"]
    assert hint["basis"]["item_names"] == ["鸡蛋"]
    assert hint["kind"] == "consumption_inference"


def test_sync_snapshot_projects_unknown_quantity_without_fake_placeholder(tmp_path) -> None:
    app = create_app(db_path=tmp_path / "buddys.sqlite3")
    client = TestClient(app)
    token = register(client, "snapshot-unknown@example.com")
    buddy = client.post(
        "/me/buddies",
        headers={"Authorization": f"Bearer {token}"},
        json={"name": "Kitchen Buddy", "space_id": "kitchen"},
    ).json()

    capture = client.post(
        f"/me/buddies/{buddy['buddy_id']}/state-memory/captures/conversation",
        headers={"Authorization": f"Bearer {token}"},
        json={"content": "我买了牛奶"},
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
    item = snapshot["state_memory"]["items_by_buddy"][buddy["buddy_id"]][0]
    latest_query = snapshot["state_memory"]["latest_query_by_buddy"][buddy["buddy_id"]]

    assert item["quantity"] is None
    assert latest_query["summary"] == "还有牛奶，但数量未输入。"


def test_sync_snapshot_projects_photo_evidence_details_for_auth_workspace(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("BUDDYS_DEFAULT_OPENAI_API_KEY", "sk-system-default")
    app = create_app(db_path=tmp_path / "buddys.sqlite3")
    client = TestClient(app)
    token = register(client, "photo-owner@example.com")
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
                usage=ProviderUsage(input_tokens=8, output_tokens=6, estimated=False),
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
    latest_query = snapshot["state_memory"]["latest_query_by_buddy"][buddy["buddy_id"]]
    hint = snapshot["state_memory"]["proactive_hint_by_buddy"][buddy["buddy_id"]]
    recent_activity = snapshot["state_memory"]["recent_activity_by_buddy"][buddy["buddy_id"]]

    assert latest_query["summary"] == "还有牛奶。"
    assert latest_query["question"] == "有牛奶吗"
    assert latest_query["evidence_item_ids"]
    assert latest_query["evidence_items"][0]["name"] == "牛奶"
    assert latest_query["evidence_items"][0]["source"] == "photo"
    assert latest_query["evidence_items"][0]["last_seen_at"]
    assert hint["kind"] == "consumption_inference"
    assert hint["basis"]["item_names"] == ["牛奶"]
    assert recent_activity[0]["kind"] in {"capture_confirmed", "proposal_waiting", "query_answered"}
    assert any(activity["kind"] == "query_answered" for activity in recent_activity)
    assert "api_key" not in str(recent_activity).lower()
    assert "capabilities" not in str(recent_activity).lower()


def test_sync_snapshot_projects_saved_recipes_for_auth_workspace_only(tmp_path) -> None:
    app = create_app(db_path=tmp_path / "buddys.sqlite3")
    client = TestClient(app)
    owner_token = register(client, "recipe-sync-owner@example.com")
    other_token = register(client, "recipe-sync-other@example.com")
    buddy = client.post(
        "/me/buddies",
        headers={"Authorization": f"Bearer {owner_token}"},
        json={"name": "Kitchen Buddy", "space_id": "kitchen"},
    ).json()

    create_recipe = client.post(
        f"/me/buddies/{buddy['buddy_id']}/state-memory/recipes",
        headers={"Authorization": f"Bearer {owner_token}"},
        json={"name": "番茄炒蛋", "ingredients": ["鸡蛋", "番茄", "盐"]},
    )
    assert create_recipe.status_code == 201

    owner_snapshot = client.get("/sync/snapshot", headers={"Authorization": f"Bearer {owner_token}"}).json()
    other_snapshot = client.get("/sync/snapshot", headers={"Authorization": f"Bearer {other_token}"}).json()
    unauth_snapshot = client.get("/sync/snapshot").json()

    buddy_id = buddy["buddy_id"]
    owner_recipes = owner_snapshot["state_memory"]["recipes_by_buddy"][buddy_id]
    assert [recipe["name"] for recipe in owner_recipes] == ["番茄炒蛋"]
    assert [ingredient["name"] for ingredient in owner_recipes[0]["ingredients"]] == ["鸡蛋", "番茄", "盐"]
    assert other_snapshot["state_memory"]["recipes_by_buddy"] == {}
    assert unauth_snapshot["state_memory"]["recipes_by_buddy"] == {}


def test_sync_snapshot_uses_recent_consumption_history_for_hint_and_summary(tmp_path) -> None:
    app = create_app(db_path=tmp_path / "buddys.sqlite3")
    client = TestClient(app)
    token = register(client, "consume-owner@example.com")
    buddy = client.post(
        "/me/buddies",
        headers={"Authorization": f"Bearer {token}"},
        json={"name": "Kitchen Buddy", "space_id": "kitchen"},
    ).json()

    capture = client.post(
        f"/me/buddies/{buddy['buddy_id']}/state-memory/captures/voice",
        headers={"Authorization": f"Bearer {token}"},
        json={"content": "我买了鸡蛋"},
    )
    assert capture.status_code == 201
    capture_proposal_id = capture.json()["proposal"]["proposal_id"]
    confirm_capture = client.post(
        f"/me/buddies/{buddy['buddy_id']}/state-memory/proposals/{capture_proposal_id}/confirm",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert confirm_capture.status_code == 200

    consume = client.post(
        f"/me/buddies/{buddy['buddy_id']}/state-memory/captures/inference",
        headers={"Authorization": f"Bearer {token}"},
        json={"content": "我用了鸡蛋"},
    )
    assert consume.status_code == 201
    consume_proposal_id = consume.json()["proposal"]["proposal_id"]
    confirm_consume = client.post(
        f"/me/buddies/{buddy['buddy_id']}/state-memory/proposals/{consume_proposal_id}/confirm",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert confirm_consume.status_code == 200

    snapshot = client.get("/sync/snapshot", headers={"Authorization": f"Bearer {token}"}).json()
    state_memory = snapshot["state_memory"]
    summary = state_memory["summary_by_buddy"][buddy["buddy_id"]]
    item = state_memory["items_by_buddy"][buddy["buddy_id"]][0]
    hint = state_memory["proactive_hint_by_buddy"][buddy["buddy_id"]]

    assert item["name"] == "鸡蛋"
    assert item["quantity"] in {None, 0, 0.0}
    assert summary["recently_consumed_count"] == 1
    assert hint["kind"] == "consumption_inference"
    assert hint["basis"]["item_names"] == ["鸡蛋"]
    assert hint["basis"]["recent_change_type"] == "consume"


def test_sync_snapshot_stale_consumption_does_not_override_low_stock_hint(tmp_path) -> None:
    app = create_app(db_path=tmp_path / "buddys.sqlite3")
    client = TestClient(app)
    token = register(client, "stale-consume-owner@example.com")
    buddy = client.post(
        "/me/buddies",
        headers={"Authorization": f"Bearer {token}"},
        json={"name": "Kitchen Buddy", "space_id": "kitchen"},
    ).json()

    app.state.state_memory_store.create_item(
        user_id=buddy["user_id"],
        buddy_id=buddy["buddy_id"],
        name="鸡蛋",
        category="ingredient",
        quantity=1,
        unit="个",
        source="manual",
        confidence=1.0,
    )
    app.state.state_memory_store.create_item(
        user_id=buddy["user_id"],
        buddy_id=buddy["buddy_id"],
        name="牛奶",
        category="ingredient",
        quantity=5,
        unit="盒",
        source="manual",
        confidence=1.0,
    )
    app.state.state_memory_store.confirm_proposal(
        user_id=buddy["user_id"],
        buddy_id=buddy["buddy_id"],
        proposal_id=app.state.state_memory_store.save_pending_proposal(
            user_id=buddy["user_id"],
            buddy_id=buddy["buddy_id"],
            source="inference",
            content="我用了牛奶",
            deltas=[StateMemoryDelta(item_name="牛奶", operation="consume", quantity=1, unit="盒", source="inference")],
        ).proposal_id,
    )
    stale_time = (datetime.now(timezone.utc) - timedelta(days=10)).isoformat()
    app.state.db.execute(
        "UPDATE state_memory_history SET created_at = ? WHERE buddy_id = ? AND item_name = '牛奶' AND change_type = 'consume'",
        (stale_time, buddy["buddy_id"]),
    )
    app.state.db.commit()

    snapshot = client.get("/sync/snapshot", headers={"Authorization": f"Bearer {token}"}).json()
    summary = snapshot["state_memory"]["summary_by_buddy"][buddy["buddy_id"]]
    hint = snapshot["state_memory"]["proactive_hint_by_buddy"][buddy["buddy_id"]]

    assert summary["recently_consumed_count"] == 0
    assert hint["kind"] == "consumption_inference"
    assert hint["basis"]["item_names"] == ["鸡蛋"]
    assert "recent_change_type" not in hint["basis"]


def test_sync_snapshot_keeps_latest_auth_state_memory_query_after_restart(tmp_path) -> None:
    db_path = tmp_path / "buddys.sqlite3"
    first_app = create_app(db_path=db_path)
    first_client = TestClient(first_app)
    token = register(first_client, "restart-owner@example.com")
    buddy = first_client.post(
        "/me/buddies",
        headers={"Authorization": f"Bearer {token}"},
        json={"name": "Kitchen Buddy", "space_id": "kitchen"},
    ).json()
    first_app.state.state_memory_store.create_item(
        user_id=buddy["user_id"],
        buddy_id=buddy["buddy_id"],
        name="鸡蛋",
        category="ingredient",
        quantity=5,
        unit="个",
        source="manual",
        confidence=1.0,
    )

    query = first_client.post(
        f"/me/buddies/{buddy['buddy_id']}/state-memory/query",
        headers={"Authorization": f"Bearer {token}"},
        json={"question": "有鸡蛋吗"},
    )
    assert query.status_code == 200
    first_client.close()

    second_client = TestClient(create_app(db_path=db_path))

    snapshot = second_client.get("/sync/snapshot", headers={"Authorization": f"Bearer {token}"}).json()
    latest_query = snapshot["state_memory"]["latest_query_by_buddy"][buddy["buddy_id"]]

    assert latest_query["trace_id"] == query.json()["trace_id"]
    assert latest_query["question"] == "有鸡蛋吗"
    assert latest_query["summary"] == "还有鸡蛋。"
    assert latest_query["evidence_items"][0]["name"] == "鸡蛋"
    assert latest_query["evidence_items"][0]["source"] == "manual"
