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


def test_state_memory_capture_routes_require_auth_and_scope_writes_to_buddy_owner(tmp_path) -> None:
    client = TestClient(create_app(db_path=tmp_path / "buddys.sqlite3"))
    owner_token = register(client, "owner@example.com")
    other_token = register(client, "other@example.com")
    buddy = client.post(
        "/me/buddies",
        headers={"Authorization": f"Bearer {owner_token}"},
        json={"name": "Kitchen Buddy", "space_id": "kitchen"},
    ).json()

    unauth_capture = client.post(
        f"/me/buddies/{buddy['buddy_id']}/state-memory/captures/voice",
        json={"content": "我买了五个鸡蛋"},
    )
    cross_user_capture = client.post(
        f"/me/buddies/{buddy['buddy_id']}/state-memory/captures/voice",
        headers={"Authorization": f"Bearer {other_token}"},
        json={"content": "我买了五个鸡蛋"},
    )

    owner_capture = client.post(
        f"/me/buddies/{buddy['buddy_id']}/state-memory/captures/voice",
        headers={"Authorization": f"Bearer {owner_token}"},
        json={"content": "我买了五个鸡蛋"},
    )
    proposal_id = owner_capture.json()["proposal"]["proposal_id"]
    cross_user_confirm = client.post(
        f"/me/buddies/{buddy['buddy_id']}/state-memory/proposals/{proposal_id}/confirm",
        headers={"Authorization": f"Bearer {other_token}"},
    )

    assert unauth_capture.status_code == 401
    assert unauth_capture.json() == {"detail": {"code": "missing_bearer_token"}}
    assert cross_user_capture.status_code == 404
    assert cross_user_capture.json() == {"detail": {"code": "buddy_not_found"}}
    assert owner_capture.status_code == 201
    assert cross_user_confirm.status_code == 404
    assert cross_user_confirm.json() == {"detail": {"code": "buddy_not_found"}}


def test_state_memory_capture_proposals_cover_all_supported_sources_without_silent_writes(tmp_path) -> None:
    client = TestClient(create_app(db_path=tmp_path / "buddys.sqlite3"))
    token = register(client, "owner@example.com")
    buddy = client.post(
        "/me/buddies",
        headers={"Authorization": f"Bearer {token}"},
        json={"name": "Kitchen Buddy", "space_id": "kitchen"},
    ).json()

    captures = [
        ("voice", "我买了五个鸡蛋和一袋土豆", ["鸡蛋", "土豆"]),
        ("photo", "照片里有两盒牛奶", ["牛奶"]),
        ("scan", "扫码记录：可乐 2 瓶", ["可乐"]),
        ("conversation", "香料用完了", ["香料"]),
        ("inference", "我用了2个鸡蛋", ["鸡蛋"]),
    ]

    for source, content, expected_names in captures:
        response = client.post(
            f"/me/buddies/{buddy['buddy_id']}/state-memory/captures/{source}",
            headers={"Authorization": f"Bearer {token}"},
            json={"content": content},
        )
        body = response.json()
        assert response.status_code == 201
        assert body["proposal"]["source"] == source
        assert [delta["item_name"] for delta in body["proposal"]["deltas"]] == expected_names
        assert body["state_revision"] >= 2

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

    assert items.json() == {"items": []}
    assert history.json() == {"history": []}
    assert len(pending.json()["pending_proposals"]) == 5


def test_state_memory_proposal_lifecycle_writes_state_only_on_confirm_and_emits_sync_events(tmp_path) -> None:
    client = TestClient(create_app(db_path=tmp_path / "buddys.sqlite3"))
    owner_token = register(client, "owner@example.com")
    other_token = register(client, "other@example.com")
    buddy = client.post(
        "/me/buddies",
        headers={"Authorization": f"Bearer {owner_token}"},
        json={"name": "Kitchen Buddy", "space_id": "kitchen"},
    ).json()

    voice_capture = client.post(
        f"/me/buddies/{buddy['buddy_id']}/state-memory/captures/voice",
        headers={"Authorization": f"Bearer {owner_token}"},
        json={"content": "我买了五个鸡蛋"},
    )
    voice_proposal_id = voice_capture.json()["proposal"]["proposal_id"]
    confirm = client.post(
        f"/me/buddies/{buddy['buddy_id']}/state-memory/proposals/{voice_proposal_id}/confirm",
        headers={"Authorization": f"Bearer {owner_token}"},
    )

    reject_capture = client.post(
        f"/me/buddies/{buddy['buddy_id']}/state-memory/captures/conversation",
        headers={"Authorization": f"Bearer {owner_token}"},
        json={"content": "香料用完了"},
    )
    reject_proposal_id = reject_capture.json()["proposal"]["proposal_id"]
    reject = client.post(
        f"/me/buddies/{buddy['buddy_id']}/state-memory/proposals/{reject_proposal_id}/reject",
        headers={"Authorization": f"Bearer {owner_token}"},
    )

    correct_capture = client.post(
        f"/me/buddies/{buddy['buddy_id']}/state-memory/captures/photo",
        headers={"Authorization": f"Bearer {owner_token}"},
        json={"content": "照片里有两盒牛奶"},
    )
    correct_proposal_id = correct_capture.json()["proposal"]["proposal_id"]
    correct = client.post(
        f"/me/buddies/{buddy['buddy_id']}/state-memory/proposals/{correct_proposal_id}/correct",
        headers={"Authorization": f"Bearer {owner_token}"},
        json={
            "deltas": [
                {
                    "item_name": "牛奶",
                    "operation": "upsert",
                    "quantity": 1,
                    "unit": "盒",
                    "confidence": 1.0,
                    "source": "manual",
                }
            ]
        },
    )

    duplicate_confirm = client.post(
        f"/me/buddies/{buddy['buddy_id']}/state-memory/proposals/{voice_proposal_id}/confirm",
        headers={"Authorization": f"Bearer {owner_token}"},
    )
    other_events = client.get(
        "/sync/events",
        params={"since_revision": 0},
        headers={"Authorization": f"Bearer {other_token}"},
    )

    items = client.get(
        f"/me/buddies/{buddy['buddy_id']}/state-memory/items",
        headers={"Authorization": f"Bearer {owner_token}"},
    ).json()["items"]
    history = client.get(
        f"/me/buddies/{buddy['buddy_id']}/state-memory/history",
        headers={"Authorization": f"Bearer {owner_token}"},
    ).json()["history"]
    pending = client.get(
        f"/me/buddies/{buddy['buddy_id']}/state-memory/pending-proposals",
        headers={"Authorization": f"Bearer {owner_token}"},
    ).json()["pending_proposals"]
    owner_events = client.get(
        "/sync/events",
        params={"since_revision": 0},
        headers={"Authorization": f"Bearer {owner_token}"},
    ).json()

    assert confirm.status_code == 200
    assert confirm.json()["applied_delta_count"] == 1
    assert confirm.json()["proposal"]["status"] == "confirmed"
    assert reject.status_code == 200
    assert reject.json()["proposal"]["status"] == "rejected"
    assert correct.status_code == 200
    assert correct.json()["applied_delta_count"] == 1
    assert correct.json()["proposal"]["status"] == "confirmed"
    assert duplicate_confirm.status_code == 409
    assert duplicate_confirm.json() == {"detail": {"code": "proposal_not_pending"}}

    assert [(item["name"], item["quantity"], item["status"]) for item in items] == [
        ("牛奶", 1.0, "active"),
        ("鸡蛋", 5.0, "active"),
    ]
    assert [entry["item_name"] for entry in history] == ["鸡蛋", "牛奶"]
    assert history[1]["quantity_after"] == 1.0
    assert pending == []

    event_types = [event["event_type"] for event in owner_events["events"]]
    assert "state_memory.proposal_created" in event_types
    assert "state_memory.proposal_confirmed" in event_types
    assert "state_memory.proposal_rejected" in event_types
    assert "state_memory.proposal_corrected" in event_types
    assert owner_events["state_revision"] == correct.json()["state_revision"]
    assert other_events.status_code == 200
    assert all(
        not event["event_type"].startswith("state_memory.")
        for event in other_events.json()["events"]
    )


def register(client: TestClient, email: str) -> str:
    response = client.post("/auth/register", json={"email": email, "password": "correct horse battery staple"})
    assert response.status_code == 201
    return response.json()["access_token"]
