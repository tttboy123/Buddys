from fastapi.testclient import TestClient

from buddys_api.main import create_app


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


def register(client: TestClient, email: str) -> str:
    response = client.post("/auth/register", json={"email": email, "password": "correct horse battery staple"})
    assert response.status_code == 201
    return response.json()["access_token"]
