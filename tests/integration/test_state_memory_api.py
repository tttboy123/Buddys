from fastapi.testclient import TestClient

from buddys_api.main import create_app
from buddys_api.state_memory_models import StateMemoryDelta


def test_state_memory_api_requires_auth_and_scopes_reads_to_buddy_owner(tmp_path) -> None:
    app = create_app(db_path=tmp_path / "buddys.sqlite3")
    client = TestClient(app)
    owner_token = register(client, "owner@example.com")
    other_token = register(client, "other@example.com")
    buddy = client.post(
        "/me/buddies",
        headers={"Authorization": f"Bearer {owner_token}"},
        json={"name": "Kitchen Buddy", "space_id": "kitchen"},
    ).json()
    state_memory_store = app.state.state_memory_store
    item = state_memory_store.create_item(
        user_id=buddy["user_id"],
        buddy_id=buddy["buddy_id"],
        name="鸡蛋",
        category="ingredient",
        quantity=5,
        unit="个",
        source="manual",
        confidence=1.0,
    )
    state_memory_store.append_history(
        user_id=buddy["user_id"],
        buddy_id=buddy["buddy_id"],
        item_id=item.item_id,
        item_name=item.name,
        change_type="observed",
        change_source="manual",
        quantity_before=None,
        quantity_after=5,
        unit_before=None,
        unit_after="个",
    )
    state_memory_store.save_pending_proposal(
        user_id=buddy["user_id"],
        buddy_id=buddy["buddy_id"],
        source="voice",
        content="香料用完了",
        deltas=[StateMemoryDelta(item_name="八角", operation="remove", source="voice")],
    )

    unauth_items = client.get(f"/me/buddies/{buddy['buddy_id']}/state-memory/items")
    owner_items = client.get(
        f"/me/buddies/{buddy['buddy_id']}/state-memory/items",
        headers={"Authorization": f"Bearer {owner_token}"},
    )
    owner_history = client.get(
        f"/me/buddies/{buddy['buddy_id']}/state-memory/history",
        headers={"Authorization": f"Bearer {owner_token}"},
    )
    owner_pending = client.get(
        f"/me/buddies/{buddy['buddy_id']}/state-memory/pending-proposals",
        headers={"Authorization": f"Bearer {owner_token}"},
    )
    cross_user_items = client.get(
        f"/me/buddies/{buddy['buddy_id']}/state-memory/items",
        headers={"Authorization": f"Bearer {other_token}"},
    )

    assert unauth_items.status_code == 401
    assert unauth_items.json() == {"detail": {"code": "missing_bearer_token"}}
    assert owner_items.status_code == 200
    assert [record["name"] for record in owner_items.json()["items"]] == ["鸡蛋"]
    assert owner_history.status_code == 200
    assert [record["item_name"] for record in owner_history.json()["history"]] == ["鸡蛋"]
    assert owner_pending.status_code == 200
    assert [record["content"] for record in owner_pending.json()["pending_proposals"]] == ["香料用完了"]
    assert cross_user_items.status_code == 404
    assert cross_user_items.json() == {"detail": {"code": "buddy_not_found"}}


def test_state_memory_api_returns_empty_lists_for_new_auth_owned_buddy(tmp_path) -> None:
    client = TestClient(create_app(db_path=tmp_path / "buddys.sqlite3"))
    token = register(client, "owner@example.com")
    buddy = client.post(
        "/me/buddies",
        headers={"Authorization": f"Bearer {token}"},
        json={"name": "Empty Buddy", "space_id": "pantry"},
    ).json()

    items = client.get(
        f"/me/buddies/{buddy['buddy_id']}/state-memory/items",
        headers={"Authorization": f"Bearer {token}"},
    )
    history = client.get(
        f"/me/buddies/{buddy['buddy_id']}/state-memory/history",
        headers={"Authorization": f"Bearer {token}"},
    )
    pending = client.get(
        f"/me/buddies/{buddy['buddy_id']}/state-memory/pending-proposals",
        headers={"Authorization": f"Bearer {token}"},
    )

    assert items.status_code == 200
    assert items.json() == {"items": []}
    assert history.status_code == 200
    assert history.json() == {"history": []}
    assert pending.status_code == 200
    assert pending.json() == {"pending_proposals": []}


def register(client: TestClient, email: str) -> str:
    response = client.post("/auth/register", json={"email": email, "password": "correct horse battery staple"})
    assert response.status_code == 201
    return response.json()["access_token"]
