from fastapi.testclient import TestClient

from buddys_api.main import create_app


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
        "summary_by_buddy": {},
        "latest_query_by_buddy": {},
    }
    assert unauth_snapshot["state_memory"] == {
        "items_by_buddy": {},
        "pending_proposals_by_buddy": {},
        "summary_by_buddy": {},
        "latest_query_by_buddy": {},
    }
    assert buddy_id not in str(other_snapshot)
    assert buddy_id not in str(unauth_snapshot)


def register(client: TestClient, email: str) -> str:
    response = client.post("/auth/register", json={"email": email, "password": "correct horse battery staple"})
    assert response.status_code == 201
    return response.json()["access_token"]
