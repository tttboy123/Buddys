from fastapi.testclient import TestClient

from buddys_api.main import create_app


def test_state_memory_query_emits_golden_trace_with_evidence_fields() -> None:
    app = create_app()
    client = TestClient(app)
    token = register(client, "owner@example.com")
    buddy = client.post(
        "/me/buddies",
        headers={"Authorization": f"Bearer {token}"},
        json={"name": "Kitchen Buddy", "space_id": "kitchen"},
    ).json()
    store = app.state.state_memory_store
    for name, quantity in (
        ("五花肉", 1.0),
        ("土豆", 2.0),
        ("鸡蛋", 5.0),
    ):
        store.create_item(
            user_id=buddy["user_id"],
            buddy_id=buddy["buddy_id"],
            name=name,
            category="ingredient",
            quantity=quantity,
            unit="个",
            source="manual",
            confidence=1.0,
        )

    query_response = client.post(
        f"/me/buddies/{buddy['buddy_id']}/state-memory/query",
        headers={"Authorization": f"Bearer {token}"},
        json={"question": "能做红烧肉吗"},
    )
    assert query_response.status_code == 200
    answer = query_response.json()

    trace_response = client.get(
        f"/traces/{answer['trace_id']}",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert trace_response.status_code == 200
    trace = trace_response.json()

    assert trace["intent"]["name"] == "state_memory_query"
    assert trace["proposal"]["action_type"] == "reply_only"
    assert trace["proposal"]["summary"] == answer["summary"]
    assert trace["proposal"]["args"]["question"] == "能做红烧肉吗"
    assert trace["proposal"]["args"]["answer_type"] == "missing_for_recipe"
    assert trace["proposal"]["args"]["evidence_item_ids"] == answer["evidence_item_ids"]
    assert trace["proposal"]["args"]["missing_items"] == answer["missing_items"]
    assert trace["permission_decision"]["policy_result"] == "not_required"
    assert trace["model_usage"]["provider"] == "mock_deterministic"
    assert len(trace["cost_refs"]) == 1


def register(client: TestClient, email: str) -> str:
    response = client.post("/auth/register", json={"email": email, "password": "correct horse battery staple"})
    assert response.status_code == 201
    return response.json()["access_token"]
