from fastapi.testclient import TestClient

from buddys_api.main import create_app
from buddys_api.providers.openai_compatible_provider import (
    OpenAICompatibleProvider,
    ProviderUsage,
    StateMemoryProviderError,
    StateMemoryQueryUnderstanding,
)
from buddys_api.state_memory_models import StateMemoryDelta

SAMPLE_PHOTO_CAPTURE_PAYLOAD = {
    "content": "冰箱照片",
    "image_base64": "aGVsbG8=",
    "image_media_type": "image/png",
}


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


def test_state_memory_capture_surfaces_provider_auth_failed_details(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("BUDDYS_DEFAULT_OPENAI_API_KEY", "sk-system-default")
    app = create_app(db_path=tmp_path / "buddys.sqlite3")
    client = TestClient(app)
    token = register(client, "owner@example.com")
    buddy = client.post(
        "/me/buddies",
        headers={"Authorization": f"Bearer {token}"},
        json={"name": "Kitchen Buddy", "space_id": "kitchen"},
    ).json()

    class FailingProvider:
        provider = "system-minimax-default"
        model = "MiniMax-M3"

        def parse_state_memory_capture(self, *, source, content, image_base64=None, image_media_type=None):
            raise StateMemoryProviderError(
                "provider_auth_failed",
                details={"upstream_status": 401},
            )

    app.state.state_memory_service.provider_factory = lambda config: FailingProvider()

    response = client.post(
        f"/me/buddies/{buddy['buddy_id']}/state-memory/captures/voice",
        headers={"Authorization": f"Bearer {token}"},
        json={"content": "我买了五个鸡蛋"},
    )

    assert response.status_code == 503
    assert response.json() == {
        "detail": {
            "code": "provider_auth_failed",
            "upstream_status": 401,
        }
    }


def test_state_memory_capture_proposals_cover_all_supported_sources_without_silent_writes(tmp_path) -> None:
    client = TestClient(create_app(db_path=tmp_path / "buddys.sqlite3"))
    token = register(client, "owner@example.com")
    buddy = client.post(
        "/me/buddies",
        headers={"Authorization": f"Bearer {token}"},
        json={"name": "Kitchen Buddy", "space_id": "kitchen"},
    ).json()

    captures = [
        ("voice", "我买了五个鸡蛋和一包面粉", ["鸡蛋"], ["一包面粉"]),
        ("voice", "一包面粉", [], ["一包面粉"]),
        ("photo", "照片里有两盒牛奶", ["牛奶"]),
        ("scan", "扫码记录：可乐 2 瓶", ["可乐"]),
        ("conversation", "香料用完了", ["香料"]),
        ("inference", "我用了2个鸡蛋", ["鸡蛋"]),
    ]

    for source, content, expected_names, *rest in captures:
        payload = {"content": content}
        if source == "photo":
            payload = {**SAMPLE_PHOTO_CAPTURE_PAYLOAD, "content": content}
        response = client.post(
            f"/me/buddies/{buddy['buddy_id']}/state-memory/captures/{source}",
            headers={"Authorization": f"Bearer {token}"},
            json=payload,
        )
        body = response.json()
        assert response.status_code == 201
        assert body["proposal"]["source"] == source
        assert [delta["item_name"] for delta in body["proposal"]["deltas"]] == expected_names
        assert body["proposal"]["unrecognized"] == (rest[0] if rest else [])
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
    assert len(pending.json()["pending_proposals"]) == 6


def test_state_memory_capture_rejects_oversized_content_with_422(tmp_path) -> None:
    client = TestClient(create_app(db_path=tmp_path / "buddys.sqlite3"))
    token = register(client, "owner@example.com")
    buddy = client.post(
        "/me/buddies",
        headers={"Authorization": f"Bearer {token}"},
        json={"name": "Kitchen Buddy", "space_id": "kitchen"},
    ).json()

    response = client.post(
        f"/me/buddies/{buddy['buddy_id']}/state-memory/captures/voice",
        headers={"Authorization": f"Bearer {token}"},
        json={"content": "鸡" * 2001},
    )

    assert response.status_code == 422
    detail = response.json()["detail"]
    assert detail[0]["loc"] == ["body", "content"]
    assert detail[0]["type"] == "string_too_long"


def test_state_memory_photo_capture_requires_supported_image_payload(tmp_path) -> None:
    client = TestClient(create_app(db_path=tmp_path / "buddys.sqlite3"))
    token = register(client, "owner@example.com")
    buddy = client.post(
        "/me/buddies",
        headers={"Authorization": f"Bearer {token}"},
        json={"name": "Kitchen Buddy", "space_id": "kitchen"},
    ).json()

    missing_image = client.post(
        f"/me/buddies/{buddy['buddy_id']}/state-memory/captures/photo",
        headers={"Authorization": f"Bearer {token}"},
        json={"content": "冰箱照片"},
    )
    bad_media = client.post(
        f"/me/buddies/{buddy['buddy_id']}/state-memory/captures/photo",
        headers={"Authorization": f"Bearer {token}"},
        json={"content": "冰箱照片", "image_base64": "aGVsbG8=", "image_media_type": "application/pdf"},
    )
    bad_base64 = client.post(
        f"/me/buddies/{buddy['buddy_id']}/state-memory/captures/photo",
        headers={"Authorization": f"Bearer {token}"},
        json={"content": "冰箱照片", "image_base64": "!!!", "image_media_type": "image/png"},
    )

    assert missing_image.status_code == 422
    assert bad_media.status_code == 422
    assert bad_base64.status_code == 422


def test_state_memory_photo_capture_accepts_image_payload_and_returns_pending_proposal(
    tmp_path,
    monkeypatch,
) -> None:
    monkeypatch.setenv("BUDDYS_DEFAULT_OPENAI_API_KEY", "sk-system-default")
    app = create_app(db_path=tmp_path / "buddys.sqlite3")
    client = TestClient(app)
    token = register(client, "owner@example.com")
    buddy = client.post(
        "/me/buddies",
        headers={"Authorization": f"Bearer {token}"},
        json={"name": "Kitchen Buddy", "space_id": "kitchen"},
    ).json()

    seen = {}

    class FakePhotoProvider:
        provider = "system-minimax-default"
        model = "MiniMax-M3"

        def parse_state_memory_capture(self, *, source, content, image_base64=None, image_media_type=None):
            seen["source"] = source
            seen["content"] = content
            seen["image_base64"] = image_base64
            seen["image_media_type"] = image_media_type
            return ([StateMemoryDelta(item_name="牛奶", operation="upsert", source=source)], [])

    app.state.state_memory_service.provider_factory = lambda config: FakePhotoProvider()

    response = client.post(
        f"/me/buddies/{buddy['buddy_id']}/state-memory/captures/photo",
        headers={"Authorization": f"Bearer {token}"},
        json={"content": "冰箱照片", "image_base64": "aGVsbG8=", "image_media_type": "image/png"},
    )

    assert response.status_code == 201
    assert response.json()["proposal"]["source"] == "photo"
    assert response.json()["proposal"]["deltas"][0]["item_name"] == "牛奶"
    assert seen == {
        "source": "photo",
        "content": "冰箱照片",
        "image_base64": "aGVsbG8=",
        "image_media_type": "image/png",
    }


def test_state_memory_photo_capture_confirm_then_query_returns_evidence(
    tmp_path,
    monkeypatch,
) -> None:
    monkeypatch.setenv("BUDDYS_DEFAULT_OPENAI_API_KEY", "sk-system-default")
    app = create_app(db_path=tmp_path / "buddys.sqlite3")
    client = TestClient(app)
    token = register(client, "owner@example.com")
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
    body = query.json()
    assert body["answer_type"] == "have_item"
    assert body["has_item"] is True
    assert body["evidence_items"][0]["name"] == "牛奶"
    assert body["evidence_items"][0]["source"] == "photo"


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
        json={**SAMPLE_PHOTO_CAPTURE_PAYLOAD, "content": "照片里有两盒牛奶"},
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


def test_state_memory_duplicate_reject_returns_409_without_mutating_state_twice(tmp_path) -> None:
    client = TestClient(create_app(db_path=tmp_path / "buddys.sqlite3"))
    token = register(client, "owner@example.com")
    buddy = client.post(
        "/me/buddies",
        headers={"Authorization": f"Bearer {token}"},
        json={"name": "Kitchen Buddy", "space_id": "kitchen"},
    ).json()

    capture = client.post(
        f"/me/buddies/{buddy['buddy_id']}/state-memory/captures/conversation",
        headers={"Authorization": f"Bearer {token}"},
        json={"content": "香料用完了"},
    )
    proposal_id = capture.json()["proposal"]["proposal_id"]

    first_reject = client.post(
        f"/me/buddies/{buddy['buddy_id']}/state-memory/proposals/{proposal_id}/reject",
        headers={"Authorization": f"Bearer {token}"},
    )
    duplicate_reject = client.post(
        f"/me/buddies/{buddy['buddy_id']}/state-memory/proposals/{proposal_id}/reject",
        headers={"Authorization": f"Bearer {token}"},
    )

    pending = client.get(
        f"/me/buddies/{buddy['buddy_id']}/state-memory/pending-proposals",
        headers={"Authorization": f"Bearer {token}"},
    )
    items = client.get(
        f"/me/buddies/{buddy['buddy_id']}/state-memory/items",
        headers={"Authorization": f"Bearer {token}"},
    )
    history = client.get(
        f"/me/buddies/{buddy['buddy_id']}/state-memory/history",
        headers={"Authorization": f"Bearer {token}"},
    )

    assert first_reject.status_code == 200
    assert first_reject.json()["proposal"]["status"] == "rejected"
    assert duplicate_reject.status_code == 409
    assert duplicate_reject.json() == {"detail": {"code": "proposal_not_pending"}}
    assert pending.json() == {"pending_proposals": []}
    assert items.json() == {"items": []}
    assert history.json() == {"history": []}


def test_state_memory_confirmed_consume_reduces_known_quantity_and_records_history_via_api(tmp_path) -> None:
    client = TestClient(create_app(db_path=tmp_path / "buddys.sqlite3"))
    token = register(client, "consume-owner@example.com")
    buddy = client.post(
        "/me/buddies",
        headers={"Authorization": f"Bearer {token}"},
        json={"name": "Kitchen Buddy", "space_id": "kitchen"},
    ).json()

    capture = client.post(
        f"/me/buddies/{buddy['buddy_id']}/state-memory/captures/voice",
        headers={"Authorization": f"Bearer {token}"},
        json={"content": "我买了五个鸡蛋"},
    )
    assert capture.status_code == 201
    proposal_id = capture.json()["proposal"]["proposal_id"]
    confirm = client.post(
        f"/me/buddies/{buddy['buddy_id']}/state-memory/proposals/{proposal_id}/confirm",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert confirm.status_code == 200

    consume = client.post(
        f"/me/buddies/{buddy['buddy_id']}/state-memory/captures/inference",
        headers={"Authorization": f"Bearer {token}"},
        json={"content": "我用了2个鸡蛋"},
    )
    assert consume.status_code == 201
    consume_proposal_id = consume.json()["proposal"]["proposal_id"]
    consume_confirm = client.post(
        f"/me/buddies/{buddy['buddy_id']}/state-memory/proposals/{consume_proposal_id}/confirm",
        headers={"Authorization": f"Bearer {token}"},
    )

    items = client.get(
        f"/me/buddies/{buddy['buddy_id']}/state-memory/items",
        headers={"Authorization": f"Bearer {token}"},
    ).json()["items"]
    history = client.get(
        f"/me/buddies/{buddy['buddy_id']}/state-memory/history",
        headers={"Authorization": f"Bearer {token}"},
    ).json()["history"]

    assert consume_confirm.status_code == 200
    assert [(item["name"], item["quantity"], item["status"]) for item in items] == [("鸡蛋", 3.0, "active")]
    assert history[-1]["change_type"] == "consume"
    assert history[-1]["quantity_before"] == 5.0
    assert history[-1]["quantity_after"] == 3.0


def test_state_memory_actions_record_safe_engagement_metrics(tmp_path) -> None:
    client = TestClient(create_app(db_path=tmp_path / "buddys.sqlite3"))
    token = register(client, "metrics-owner@example.com")
    buddy = client.post(
        "/me/buddies",
        headers={"Authorization": f"Bearer {token}"},
        json={"name": "Kitchen Buddy", "space_id": "kitchen"},
    ).json()

    capture = client.post(
        f"/me/buddies/{buddy['buddy_id']}/state-memory/captures/voice",
        headers={"Authorization": f"Bearer {token}"},
        json={"content": "我买了五个鸡蛋"},
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
        json={"question": "有鸡蛋吗"},
    )
    assert query.status_code == 200

    metrics = client.get("/metrics/engagement", headers={"Authorization": f"Bearer {token}"})

    assert metrics.status_code == 200
    body = metrics.json()
    assert body["activation"]["completed_first_capture_confirm_query"] is True
    assert body["capture_by_source"]["voice"] == 1
    assert body["query_by_answer_type"]["have_item"] == 1
    assert "我买了五个鸡蛋" not in str(body)
    assert "有鸡蛋吗" not in str(body)


def test_state_memory_activation_requires_ordered_capture_confirm_query_cycle(tmp_path) -> None:
    app = create_app(db_path=tmp_path / "buddys.sqlite3")
    client = TestClient(app)
    token = register(client, "unordered-owner@example.com")
    buddy = client.post(
        "/me/buddies",
        headers={"Authorization": f"Bearer {token}"},
        json={"name": "Kitchen Buddy", "space_id": "kitchen"},
    ).json()

    app.state.engagement_metrics_store.record_event(
        user_id=buddy["user_id"],
        buddy_id=buddy["buddy_id"],
        event_type="query_answered",
        answer_type="have_item",
    )
    app.state.engagement_metrics_store.record_event(
        user_id=buddy["user_id"],
        buddy_id=buddy["buddy_id"],
        event_type="capture_submitted",
        capture_source="voice",
    )
    app.state.engagement_metrics_store.record_event(
        user_id=buddy["user_id"],
        buddy_id=buddy["buddy_id"],
        event_type="proposal_confirmed",
    )

    metrics = client.get("/metrics/engagement", headers={"Authorization": f"Bearer {token}"})

    assert metrics.status_code == 200
    assert metrics.json()["activation"]["completed_first_capture_confirm_query"] is False


def test_state_memory_correct_rejects_negative_quantity_with_422(tmp_path) -> None:
    client = TestClient(create_app(db_path=tmp_path / "buddys.sqlite3"))
    token = register(client, "owner@example.com")
    buddy = client.post(
        "/me/buddies",
        headers={"Authorization": f"Bearer {token}"},
        json={"name": "Kitchen Buddy", "space_id": "kitchen"},
    ).json()
    capture = client.post(
        f"/me/buddies/{buddy['buddy_id']}/state-memory/captures/photo",
        headers={"Authorization": f"Bearer {token}"},
        json={**SAMPLE_PHOTO_CAPTURE_PAYLOAD, "content": "照片里有两盒牛奶"},
    )
    proposal_id = capture.json()["proposal"]["proposal_id"]

    response = client.post(
        f"/me/buddies/{buddy['buddy_id']}/state-memory/proposals/{proposal_id}/correct",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "deltas": [
                {
                    "item_name": "牛奶",
                    "operation": "upsert",
                    "quantity": -1,
                    "unit": "盒",
                    "confidence": 1.0,
                    "source": "manual",
                }
            ]
        },
    )

    assert response.status_code == 422
    detail = response.json()["detail"]
    assert detail[0]["loc"] == ["body", "deltas", 0, "quantity"]
    assert detail[0]["type"] == "greater_than_equal"


def test_state_memory_duplicate_correct_returns_409_without_double_apply(tmp_path) -> None:
    client = TestClient(create_app(db_path=tmp_path / "buddys.sqlite3"))
    token = register(client, "owner@example.com")
    buddy = client.post(
        "/me/buddies",
        headers={"Authorization": f"Bearer {token}"},
        json={"name": "Kitchen Buddy", "space_id": "kitchen"},
    ).json()
    capture = client.post(
        f"/me/buddies/{buddy['buddy_id']}/state-memory/captures/photo",
        headers={"Authorization": f"Bearer {token}"},
        json={**SAMPLE_PHOTO_CAPTURE_PAYLOAD, "content": "照片里有两盒牛奶"},
    )
    proposal_id = capture.json()["proposal"]["proposal_id"]

    first_correct = client.post(
        f"/me/buddies/{buddy['buddy_id']}/state-memory/proposals/{proposal_id}/correct",
        headers={"Authorization": f"Bearer {token}"},
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
    duplicate_correct = client.post(
        f"/me/buddies/{buddy['buddy_id']}/state-memory/proposals/{proposal_id}/correct",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "deltas": [
                {
                    "item_name": "牛奶",
                    "operation": "upsert",
                    "quantity": 3,
                    "unit": "盒",
                    "confidence": 1.0,
                    "source": "manual",
                }
            ]
        },
    )

    items = client.get(
        f"/me/buddies/{buddy['buddy_id']}/state-memory/items",
        headers={"Authorization": f"Bearer {token}"},
    )
    history = client.get(
        f"/me/buddies/{buddy['buddy_id']}/state-memory/history",
        headers={"Authorization": f"Bearer {token}"},
    )

    assert first_correct.status_code == 200
    assert first_correct.json()["proposal"]["status"] == "confirmed"
    assert first_correct.json()["applied_delta_count"] == 1
    assert duplicate_correct.status_code == 409
    assert duplicate_correct.json() == {"detail": {"code": "proposal_not_pending"}}
    assert [(item["name"], item["quantity"]) for item in items.json()["items"]] == [("牛奶", 1.0)]
    assert [entry["item_name"] for entry in history.json()["history"]] == ["牛奶"]


def test_state_memory_query_requires_auth_and_scopes_reads_to_buddy_owner(tmp_path) -> None:
    app = create_app(db_path=tmp_path / "buddys.sqlite3")
    client = TestClient(app)
    owner_token = register(client, "owner@example.com")
    other_token = register(client, "other@example.com")
    buddy = client.post(
        "/me/buddies",
        headers={"Authorization": f"Bearer {owner_token}"},
        json={"name": "Kitchen Buddy", "space_id": "kitchen"},
    ).json()
    app.state.state_memory_store.create_item(
        user_id=buddy["user_id"],
        buddy_id=buddy["buddy_id"],
        name="鸡蛋",
        category="ingredient",
        quantity=5,
        unit="个",
        source="manual",
        confidence=1.0,
    )

    unauth_query = client.post(
        f"/me/buddies/{buddy['buddy_id']}/state-memory/query",
        json={"question": "有鸡蛋吗"},
    )
    owner_query = client.post(
        f"/me/buddies/{buddy['buddy_id']}/state-memory/query",
        headers={"Authorization": f"Bearer {owner_token}"},
        json={"question": "有鸡蛋吗"},
    )
    cross_user_query = client.post(
        f"/me/buddies/{buddy['buddy_id']}/state-memory/query",
        headers={"Authorization": f"Bearer {other_token}"},
        json={"question": "有鸡蛋吗"},
    )

    assert unauth_query.status_code == 401
    assert unauth_query.json() == {"detail": {"code": "missing_bearer_token"}}
    assert owner_query.status_code == 200
    assert owner_query.json()["answer_type"] == "have_item"
    assert owner_query.json()["has_item"] is True
    assert owner_query.json()["evidence_item_ids"]
    assert cross_user_query.status_code == 404
    assert cross_user_query.json() == {"detail": {"code": "buddy_not_found"}}


def test_state_memory_query_returns_evidence_and_missing_items_for_inventory_and_recipe_questions(tmp_path) -> None:
    app = create_app(db_path=tmp_path / "buddys.sqlite3")
    client = TestClient(app)
    token = register(client, "owner@example.com")
    buddy = client.post(
        "/me/buddies",
        headers={"Authorization": f"Bearer {token}"},
        json={"name": "Kitchen Buddy", "space_id": "kitchen"},
    ).json()
    store = app.state.state_memory_store
    for name, quantity, unit in (
        ("五花肉", 1.0, "份"),
        ("土豆", 2.0, "个"),
        ("鸡蛋", 5.0, "个"),
        ("老抽", 1.0, "瓶"),
    ):
        store.create_item(
            user_id=buddy["user_id"],
            buddy_id=buddy["buddy_id"],
            name=name,
            category="ingredient",
            quantity=quantity,
            unit=unit,
            source="manual",
            confidence=1.0,
        )

    have_item = client.post(
        f"/me/buddies/{buddy['buddy_id']}/state-memory/query",
        headers={"Authorization": f"Bearer {token}"},
        json={"question": "有鸡蛋吗"},
    )
    missing_for_recipe = client.post(
        f"/me/buddies/{buddy['buddy_id']}/state-memory/query",
        headers={"Authorization": f"Bearer {token}"},
        json={"question": "能做红烧肉吗"},
    )

    assert have_item.status_code == 200
    assert have_item.json()["answer_type"] == "have_item"
    assert have_item.json()["subject_name"] == "鸡蛋"
    assert have_item.json()["has_item"] is True
    assert have_item.json()["missing_items"] == []
    assert [item["name"] for item in have_item.json()["evidence_items"]] == ["鸡蛋"]

    assert missing_for_recipe.status_code == 200
    assert missing_for_recipe.json()["answer_type"] == "missing_for_recipe"
    assert missing_for_recipe.json()["subject_name"] == "红烧肉"
    assert missing_for_recipe.json()["missing_items"] == ["生抽", "八角", "冰糖"]
    assert set(missing_for_recipe.json()["evidence_item_ids"]) == {
        item["item_id"] for item in missing_for_recipe.json()["evidence_items"]
    }
    assert {item["name"] for item in missing_for_recipe.json()["evidence_items"]} == {"五花肉", "老抽"}
    assert missing_for_recipe.json()["trace_id"].startswith("trace_")


def test_state_memory_query_have_item_with_unknown_quantity_is_honest(tmp_path) -> None:
    app = create_app(db_path=tmp_path / "buddys.sqlite3")
    client = TestClient(app)
    token = register(client, "unknown-quantity@example.com")
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

    response = client.post(
        f"/me/buddies/{buddy['buddy_id']}/state-memory/query",
        headers={"Authorization": f"Bearer {token}"},
        json={"question": "有牛奶吗"},
    )

    assert response.status_code == 200
    assert response.json()["answer_type"] == "have_item"
    assert response.json()["summary"] == "还有牛奶，但数量不确定。"
    assert response.json()["evidence_items"][0]["quantity"] is None


def test_state_memory_query_trace_and_cost_artifacts_are_owner_scoped(tmp_path) -> None:
    app = create_app(db_path=tmp_path / "buddys.sqlite3")
    client = TestClient(app)
    owner_token = register(client, "owner@example.com")
    other_token = register(client, "other@example.com")
    buddy = client.post(
        "/me/buddies",
        headers={"Authorization": f"Bearer {owner_token}"},
        json={"name": "Kitchen Buddy", "space_id": "kitchen"},
    ).json()
    app.state.state_memory_store.create_item(
        user_id=buddy["user_id"],
        buddy_id=buddy["buddy_id"],
        name="鸡蛋",
        category="ingredient",
        quantity=5,
        unit="个",
        source="manual",
        confidence=1.0,
    )

    legacy_buddy = client.post("/buddies", json={"user_id": "legacy_user"}).json()
    legacy_message = client.post(
        f"/buddies/{legacy_buddy['buddy_id']}/messages",
        json={"user_id": "legacy_user", "message": "把客厅灯调暗"},
    ).json()

    query = client.post(
        f"/me/buddies/{buddy['buddy_id']}/state-memory/query",
        headers={"Authorization": f"Bearer {owner_token}"},
        json={"question": "有鸡蛋吗"},
    )
    assert query.status_code == 200
    trace_id = query.json()["trace_id"]

    owner_trace = client.get(
        f"/traces/{trace_id}",
        headers={"Authorization": f"Bearer {owner_token}"},
    )
    unauth_trace = client.get(f"/traces/{trace_id}")
    cross_user_trace = client.get(
        f"/traces/{trace_id}",
        headers={"Authorization": f"Bearer {other_token}"},
    )
    legacy_trace = client.get(f"/traces/{legacy_message['trace_id']}")

    owner_costs = client.get("/cost-events", headers={"Authorization": f"Bearer {owner_token}"}).json()
    other_costs = client.get("/cost-events", headers={"Authorization": f"Bearer {other_token}"}).json()
    unauth_costs = client.get("/cost-events").json()

    assert owner_trace.status_code == 200
    query_cost_event_id = owner_trace.json()["cost_refs"][0]
    assert unauth_trace.status_code == 404
    assert unauth_trace.json() == {"detail": {"code": "trace_not_found"}}
    assert cross_user_trace.status_code == 404
    assert cross_user_trace.json() == {"detail": {"code": "trace_not_found"}}
    assert legacy_trace.status_code == 200
    assert legacy_trace.json()["trace_id"] == legacy_message["trace_id"]

    assert query_cost_event_id in {event["cost_event_id"] for event in owner_costs["cost_events"]}
    assert query_cost_event_id not in {event["cost_event_id"] for event in other_costs["cost_events"]}
    assert query_cost_event_id not in {event["cost_event_id"] for event in unauth_costs["cost_events"]}
    assert legacy_message["cost_event_ids"][0] in {event["cost_event_id"] for event in unauth_costs["cost_events"]}


def test_missing_buddy_row_fails_closed_for_persisted_auth_trace_and_cost_visibility(tmp_path) -> None:
    app = create_app(db_path=tmp_path / "buddys.sqlite3")
    client = TestClient(app)
    owner_token = register(client, "owner@example.com")
    buddy = client.post(
        "/me/buddies",
        headers={"Authorization": f"Bearer {owner_token}"},
        json={"name": "Kitchen Buddy", "space_id": "kitchen"},
    ).json()
    app.state.state_memory_store.create_item(
        user_id=buddy["user_id"],
        buddy_id=buddy["buddy_id"],
        name="鸡蛋",
        category="ingredient",
        quantity=5,
        unit="个",
        source="manual",
        confidence=1.0,
    )

    query = client.post(
        f"/me/buddies/{buddy['buddy_id']}/state-memory/query",
        headers={"Authorization": f"Bearer {owner_token}"},
        json={"question": "有鸡蛋吗"},
    )
    assert query.status_code == 200
    trace_id = query.json()["trace_id"]
    cost_event_id = client.get(
        f"/traces/{trace_id}",
        headers={"Authorization": f"Bearer {owner_token}"},
    ).json()["cost_refs"][0]

    original_origin_for_buddy = app.state.buddy_store.origin_for_buddy
    original_get = app.state.buddy_store.get

    def missing_origin_for_buddy(buddy_id: str):
        if buddy_id == buddy["buddy_id"]:
            raise KeyError(f"buddy not found: {buddy_id}")
        return original_origin_for_buddy(buddy_id)

    def missing_get(buddy_id: str):
        if buddy_id == buddy["buddy_id"]:
            raise KeyError(f"buddy not found: {buddy_id}")
        return original_get(buddy_id)

    app.state.buddy_store.origin_for_buddy = missing_origin_for_buddy
    app.state.buddy_store.get = missing_get

    unauth_trace = client.get(f"/traces/{trace_id}")
    owner_trace = client.get(
        f"/traces/{trace_id}",
        headers={"Authorization": f"Bearer {owner_token}"},
    )
    unauth_costs = client.get("/cost-events").json()["cost_events"]
    owner_costs = client.get("/cost-events", headers={"Authorization": f"Bearer {owner_token}"}).json()["cost_events"]

    assert unauth_trace.status_code == 404
    assert unauth_trace.json() == {"detail": {"code": "trace_not_found"}}
    assert owner_trace.status_code == 404
    assert owner_trace.json() == {"detail": {"code": "trace_not_found"}}
    assert cost_event_id not in {event["cost_event_id"] for event in unauth_costs}
    assert cost_event_id not in {event["cost_event_id"] for event in owner_costs}


def test_state_memory_real_capture_preflight_blocks_over_limit_before_provider_call(tmp_path, monkeypatch) -> None:
    import httpx

    app = create_app(db_path=tmp_path / "buddys.sqlite3")
    client = TestClient(app)
    token = register(client, "owner@example.com")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-real-provider-test")
    buddy = client.post(
        "/me/buddies",
        headers={"Authorization": f"Bearer {token}"},
        json={"name": "Kitchen Buddy", "space_id": "kitchen"},
    ).json()
    provider_response = client.post(
        "/providers",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "provider_id": "minimax-openai",
            "display_name": "MiniMax OpenAI Compatible",
            "provider_type": "openai_compatible",
            "base_url": "https://api.minimaxi.com/v1",
            "api_key_env_var": "OPENAI_API_KEY",
            "default_model": "MiniMax-M3",
        },
    )
    assert provider_response.status_code == 200

    call_count = {"value": 0}

    def handler(_: httpx.Request) -> httpx.Response:
        call_count["value"] += 1
        return httpx.Response(500, json={"error": "should-not-be-called"})

    app.state.state_memory_service.provider_factory = lambda config: OpenAICompatibleProvider(
        provider_id=config.provider_id,
        base_url=config.base_url or "https://api.minimaxi.com/v1",
        api_key_env_var=config.api_key_env_var or "OPENAI_API_KEY",
        model=config.default_model,
        transport=httpx.MockTransport(handler),
    )

    usage_store = app.state.usage_store
    limit = usage_store.usage_summary(buddy["user_id"]).monthly_token_limit
    assert limit is not None
    usage_store.record_usage(
        user_id=buddy["user_id"],
        trace_id="trace_at_limit",
        buddy_id=buddy["buddy_id"],
        provider_id="seed_provider",
        model_id="seed_model",
        input_tokens=limit,
        output_tokens=0,
        source="test_seed",
    )

    response = client.post(
        f"/me/buddies/{buddy['buddy_id']}/state-memory/captures/voice",
        headers={"Authorization": f"Bearer {token}"},
        json={"content": "我买了两盒鸡蛋"},
    )

    assert response.status_code == 429
    assert response.json()["detail"]["code"] == "token_plan_limit_exceeded"
    assert call_count["value"] == 0
    assert app.state.usage_store.usage_summary(buddy["user_id"]).used_tokens == limit
    assert client.get("/cost-events", headers={"Authorization": f"Bearer {token}"}).json() == {"cost_events": []}
    pending = client.get(
        f"/me/buddies/{buddy['buddy_id']}/state-memory/pending-proposals",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert pending.json() == {"pending_proposals": []}


def test_state_memory_real_capture_records_provider_usage_and_unrecognized(tmp_path, monkeypatch) -> None:
    import httpx
    import json

    app = create_app(db_path=tmp_path / "buddys.sqlite3")
    client = TestClient(app)
    token = register(client, "owner@example.com")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-real-provider-test")
    buddy = client.post(
        "/me/buddies",
        headers={"Authorization": f"Bearer {token}"},
        json={"name": "Kitchen Buddy", "space_id": "kitchen"},
    ).json()
    provider_response = client.post(
        "/providers",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "provider_id": "minimax-openai",
            "display_name": "MiniMax OpenAI Compatible",
            "provider_type": "openai_compatible",
            "base_url": "https://api.minimaxi.com/v1",
            "api_key_env_var": "OPENAI_API_KEY",
            "default_model": "MiniMax-M3",
        },
    )
    assert provider_response.status_code == 200

    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "message": {
                            "content": json.dumps(
                                {
                                    "deltas": [
                                        {
                                            "item_name": "鸡蛋",
                                            "operation": "upsert",
                                            "quantity": 2,
                                            "unit": "盒",
                                            "category": "ingredient",
                                            "confidence": 0.93,
                                            "source": "voice",
                                        }
                                    ],
                                    "unrecognized": ["一包面粉"],
                                },
                                ensure_ascii=False,
                            )
                        }
                    }
                ],
                "usage": {"prompt_tokens": 17, "completion_tokens": 21},
            },
        )

    app.state.state_memory_service.provider_factory = lambda config: OpenAICompatibleProvider(
        provider_id=config.provider_id,
        base_url=config.base_url or "https://api.minimaxi.com/v1",
        api_key_env_var=config.api_key_env_var or "OPENAI_API_KEY",
        model=config.default_model,
        transport=httpx.MockTransport(handler),
    )

    response = client.post(
        f"/me/buddies/{buddy['buddy_id']}/state-memory/captures/voice",
        headers={"Authorization": f"Bearer {token}"},
        json={"content": "我买了两盒鸡蛋和一包面粉"},
    )

    assert response.status_code == 201
    body = response.json()
    assert [delta["item_name"] for delta in body["proposal"]["deltas"]] == ["鸡蛋"]
    assert body["proposal"]["unrecognized"] == ["一包面粉"]

    usage_entries = app.state.usage_store.list_usage(buddy["user_id"])
    assert len(usage_entries) == 1
    assert usage_entries[0].provider_id == "minimax-openai"
    assert usage_entries[0].model_id == "MiniMax-M3"
    assert usage_entries[0].input_tokens == 17
    assert usage_entries[0].output_tokens == 21
    cost_events = client.get("/cost-events", headers={"Authorization": f"Bearer {token}"}).json()["cost_events"]
    assert len(cost_events) == 1
    assert cost_events[0]["provider"] == "minimax-openai"
    assert cost_events[0]["model"] == "MiniMax-M3"
    assert cost_events[0]["input_tokens"] == 17
    assert cost_events[0]["output_tokens"] == 21


def test_state_memory_real_capture_persists_trace_for_cost_event(tmp_path, monkeypatch) -> None:
    import httpx
    import json

    app = create_app(db_path=tmp_path / "buddys.sqlite3")
    client = TestClient(app)
    token = register(client, "owner@example.com")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-real-provider-test")
    buddy = client.post(
        "/me/buddies",
        headers={"Authorization": f"Bearer {token}"},
        json={"name": "Kitchen Buddy", "space_id": "kitchen"},
    ).json()
    app.state.buddy_store.save(
        app.state.buddy_store.get_for_user(
            buddy_id=buddy["buddy_id"],
            user_id=buddy["user_id"],
            created_via="auth",
        ).model_copy(update={"space_id": "kitchen-edge", "device_id": "device_kitchen_001"}),
        created_via="auth",
    )
    provider_response = client.post(
        "/providers",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "provider_id": "minimax-openai",
            "display_name": "MiniMax OpenAI Compatible",
            "provider_type": "openai_compatible",
            "base_url": "https://api.minimaxi.com/v1",
            "api_key_env_var": "OPENAI_API_KEY",
            "default_model": "MiniMax-M3",
        },
    )
    assert provider_response.status_code == 200

    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "message": {
                            "content": json.dumps(
                                {
                                    "deltas": [
                                        {
                                            "item_name": "鸡蛋",
                                            "operation": "upsert",
                                            "quantity": 2,
                                            "unit": "盒",
                                            "category": "ingredient",
                                            "confidence": 0.93,
                                            "source": "voice",
                                        }
                                    ],
                                    "unrecognized": [],
                                },
                                ensure_ascii=False,
                            )
                        }
                    }
                ],
                "usage": {"prompt_tokens": 17, "completion_tokens": 21},
            },
        )

    app.state.state_memory_service.provider_factory = lambda config: OpenAICompatibleProvider(
        provider_id=config.provider_id,
        base_url=config.base_url or "https://api.minimaxi.com/v1",
        api_key_env_var=config.api_key_env_var or "OPENAI_API_KEY",
        model=config.default_model,
        transport=httpx.MockTransport(handler),
    )

    response = client.post(
        f"/me/buddies/{buddy['buddy_id']}/state-memory/captures/voice",
        headers={"Authorization": f"Bearer {token}"},
        json={"content": "我买了两盒鸡蛋"},
    )

    assert response.status_code == 201
    cost_events = client.get("/cost-events", headers={"Authorization": f"Bearer {token}"}).json()["cost_events"]
    assert len(cost_events) == 1
    trace_id = cost_events[0]["trace_id"]

    trace_response = client.get(
        f"/traces/{trace_id}",
        headers={"Authorization": f"Bearer {token}"},
    )

    assert trace_response.status_code == 200
    trace = trace_response.json()
    assert trace["intent"]["name"] == "state_memory_capture"
    assert trace["proposal"]["action_type"] == "memory_proposal"
    assert trace["space_id"] == "kitchen-edge"
    assert trace["device_id"] == "device_kitchen_001"
    assert trace["model_usage"]["provider"] == "minimax-openai"
    assert trace["model_usage"]["model"] == "MiniMax-M3"
    assert trace["cost_refs"] == [cost_events[0]["cost_event_id"]]


def test_state_memory_real_query_uses_model_understanding_and_records_real_usage(tmp_path, monkeypatch) -> None:
    import httpx
    import json

    app = create_app(db_path=tmp_path / "buddys.sqlite3")
    client = TestClient(app)
    token = register(client, "owner@example.com")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-real-provider-test")
    buddy = client.post(
        "/me/buddies",
        headers={"Authorization": f"Bearer {token}"},
        json={"name": "Kitchen Buddy", "space_id": "kitchen"},
    ).json()
    provider_response = client.post(
        "/providers",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "provider_id": "minimax-openai",
            "display_name": "MiniMax OpenAI Compatible",
            "provider_type": "openai_compatible",
            "base_url": "https://api.minimaxi.com/v1",
            "api_key_env_var": "OPENAI_API_KEY",
            "default_model": "MiniMax-M3",
        },
    )
    assert provider_response.status_code == 200

    app.state.state_memory_store.create_item(
        user_id=buddy["user_id"],
        buddy_id=buddy["buddy_id"],
        name="鸡蛋",
        category="ingredient",
        quantity=6,
        unit="个",
        source="manual",
        confidence=1.0,
    )

    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "message": {
                            "content": json.dumps(
                                {
                                    "answer_type": "missing_for_recipe",
                                    "subject_name": "西红柿炒蛋",
                                    "required_items": ["鸡蛋", "西红柿", "盐"],
                                },
                                ensure_ascii=False,
                            )
                        }
                    }
                ],
                "usage": {"prompt_tokens": 13, "completion_tokens": 15},
            },
        )

    app.state.state_memory_service.provider_factory = lambda config: OpenAICompatibleProvider(
        provider_id=config.provider_id,
        base_url=config.base_url or "https://api.minimaxi.com/v1",
        api_key_env_var=config.api_key_env_var or "OPENAI_API_KEY",
        model=config.default_model,
        transport=httpx.MockTransport(handler),
    )

    response = client.post(
        f"/me/buddies/{buddy['buddy_id']}/state-memory/query",
        headers={"Authorization": f"Bearer {token}"},
        json={"question": "做西红柿炒蛋还缺什么"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["answer_type"] == "missing_for_recipe"
    assert body["subject_name"] == "西红柿炒蛋"
    assert body["missing_items"] == ["西红柿", "盐"]
    assert [item["name"] for item in body["evidence_items"]] == ["鸡蛋"]
    assert body["summary"] == "做西红柿炒蛋还缺西红柿、盐。"

    usage_entries = app.state.usage_store.list_usage(buddy["user_id"])
    assert len(usage_entries) == 1
    assert usage_entries[0].provider_id == "minimax-openai"
    assert usage_entries[0].model_id == "MiniMax-M3"
    assert usage_entries[0].input_tokens == 13
    assert usage_entries[0].output_tokens == 15
    cost_events = client.get("/cost-events", headers={"Authorization": f"Bearer {token}"}).json()["cost_events"]
    assert len(cost_events) == 1
    assert cost_events[0]["provider"] == "minimax-openai"
    assert cost_events[0]["model"] == "MiniMax-M3"


def test_state_memory_real_query_recipe_synonym_matches_available_inventory(tmp_path, monkeypatch) -> None:
    import httpx
    import json

    app = create_app(db_path=tmp_path / "buddys.sqlite3")
    client = TestClient(app)
    token = register(client, "owner@example.com")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-real-provider-test")
    buddy = client.post(
        "/me/buddies",
        headers={"Authorization": f"Bearer {token}"},
        json={"name": "Kitchen Buddy", "space_id": "kitchen"},
    ).json()
    provider_response = client.post(
        "/providers",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "provider_id": "minimax-openai",
            "display_name": "MiniMax OpenAI Compatible",
            "provider_type": "openai_compatible",
            "base_url": "https://api.minimaxi.com/v1",
            "api_key_env_var": "OPENAI_API_KEY",
            "default_model": "MiniMax-M3",
        },
    )
    assert provider_response.status_code == 200

    for name in ("五花肉", "老抽", "冰糖"):
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

    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "message": {
                            "content": json.dumps(
                                {
                                    "answer_type": "missing_for_recipe",
                                    "subject_name": "红烧肉",
                                    "required_items": ["猪肉", "老抽", "冰糖"],
                                },
                                ensure_ascii=False,
                            )
                        }
                    }
                ],
                "usage": {"prompt_tokens": 11, "completion_tokens": 13},
            },
        )

    app.state.state_memory_service.provider_factory = lambda config: OpenAICompatibleProvider(
        provider_id=config.provider_id,
        base_url=config.base_url or "https://api.minimaxi.com/v1",
        api_key_env_var=config.api_key_env_var or "OPENAI_API_KEY",
        model=config.default_model,
        transport=httpx.MockTransport(handler),
    )

    response = client.post(
        f"/me/buddies/{buddy['buddy_id']}/state-memory/query",
        headers={"Authorization": f"Bearer {token}"},
        json={"question": "做红烧肉还缺什么"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["answer_type"] == "missing_for_recipe"
    assert body["subject_name"] == "红烧肉"
    assert body["missing_items"] == []
    assert [item["name"] for item in body["evidence_items"]] == ["五花肉", "冰糖", "老抽"]
    assert body["summary"] == "做红烧肉的材料目前齐了。"


def test_state_memory_real_have_item_synonym_matches_available_inventory(tmp_path, monkeypatch) -> None:
    import httpx
    import json

    app = create_app(db_path=tmp_path / "buddys.sqlite3")
    client = TestClient(app)
    token = register(client, "owner@example.com")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-real-provider-test")
    buddy = client.post(
        "/me/buddies",
        headers={"Authorization": f"Bearer {token}"},
        json={"name": "Kitchen Buddy", "space_id": "kitchen"},
    ).json()
    provider_response = client.post(
        "/providers",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "provider_id": "minimax-openai",
            "display_name": "MiniMax OpenAI Compatible",
            "provider_type": "openai_compatible",
            "base_url": "https://api.minimaxi.com/v1",
            "api_key_env_var": "OPENAI_API_KEY",
            "default_model": "MiniMax-M3",
        },
    )
    assert provider_response.status_code == 200

    app.state.state_memory_store.create_item(
        user_id=buddy["user_id"],
        buddy_id=buddy["buddy_id"],
        name="五花肉",
        category="ingredient",
        quantity=1,
        unit="斤",
        source="manual",
        confidence=1.0,
    )

    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "message": {
                            "content": json.dumps(
                                {
                                    "answer_type": "have_item",
                                    "subject_name": "猪肉",
                                    "required_items": [],
                                },
                                ensure_ascii=False,
                            )
                        }
                    }
                ],
                "usage": {"prompt_tokens": 8, "completion_tokens": 10},
            },
        )

    app.state.state_memory_service.provider_factory = lambda config: OpenAICompatibleProvider(
        provider_id=config.provider_id,
        base_url=config.base_url or "https://api.minimaxi.com/v1",
        api_key_env_var=config.api_key_env_var or "OPENAI_API_KEY",
        model=config.default_model,
        transport=httpx.MockTransport(handler),
    )

    response = client.post(
        f"/me/buddies/{buddy['buddy_id']}/state-memory/query",
        headers={"Authorization": f"Bearer {token}"},
        json={"question": "还有猪肉吗"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["answer_type"] == "have_item"
    assert body["subject_name"] == "猪肉"
    assert body["has_item"] is True
    assert body["missing_items"] == []
    assert [item["name"] for item in body["evidence_items"]] == ["五花肉"]
    assert body["summary"] == "还有猪肉。"


def test_state_memory_real_query_rejects_semantically_empty_recipe_understanding(tmp_path, monkeypatch) -> None:
    import httpx
    import json

    app = create_app(db_path=tmp_path / "buddys.sqlite3")
    client = TestClient(app)
    token = register(client, "owner@example.com")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-real-provider-test")
    buddy = client.post(
        "/me/buddies",
        headers={"Authorization": f"Bearer {token}"},
        json={"name": "Kitchen Buddy", "space_id": "kitchen"},
    ).json()
    provider_response = client.post(
        "/providers",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "provider_id": "minimax-openai",
            "display_name": "MiniMax OpenAI Compatible",
            "provider_type": "openai_compatible",
            "base_url": "https://api.minimaxi.com/v1",
            "api_key_env_var": "OPENAI_API_KEY",
            "default_model": "MiniMax-M3",
        },
    )
    assert provider_response.status_code == 200

    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "message": {
                            "content": json.dumps(
                                {
                                    "answer_type": "missing_for_recipe",
                                    "subject_name": "红烧肉",
                                    "required_items": [],
                                },
                                ensure_ascii=False,
                            )
                        }
                    }
                ],
                "usage": {"prompt_tokens": 13, "completion_tokens": 15},
            },
        )

    app.state.state_memory_service.provider_factory = lambda config: OpenAICompatibleProvider(
        provider_id=config.provider_id,
        base_url=config.base_url or "https://api.minimaxi.com/v1",
        api_key_env_var=config.api_key_env_var or "OPENAI_API_KEY",
        model=config.default_model,
        transport=httpx.MockTransport(handler),
    )

    response = client.post(
        f"/me/buddies/{buddy['buddy_id']}/state-memory/query",
        headers={"Authorization": f"Bearer {token}"},
        json={"question": "做红烧肉还缺什么"},
    )

    assert response.status_code == 503
    assert response.json() == {"detail": {"code": "model_response_invalid"}}


def test_state_memory_real_capture_failed_parse_still_records_usage_cost_and_trace(tmp_path, monkeypatch) -> None:
    import httpx

    app = create_app(db_path=tmp_path / "buddys.sqlite3")
    client = TestClient(app)
    token = register(client, "owner@example.com")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-real-provider-test")
    buddy = client.post(
        "/me/buddies",
        headers={"Authorization": f"Bearer {token}"},
        json={"name": "Kitchen Buddy", "space_id": "kitchen"},
    ).json()
    provider_response = client.post(
        "/providers",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "provider_id": "minimax-openai",
            "display_name": "MiniMax OpenAI Compatible",
            "provider_type": "openai_compatible",
            "base_url": "https://api.minimaxi.com/v1",
            "api_key_env_var": "OPENAI_API_KEY",
            "default_model": "MiniMax-M3",
        },
    )
    assert provider_response.status_code == 200

    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "choices": [{"message": {"content": "not-json"}}],
                "usage": {"prompt_tokens": 7, "completion_tokens": 9},
            },
        )

    app.state.state_memory_service.provider_factory = lambda config: OpenAICompatibleProvider(
        provider_id=config.provider_id,
        base_url=config.base_url or "https://api.minimaxi.com/v1",
        api_key_env_var=config.api_key_env_var or "OPENAI_API_KEY",
        model=config.default_model,
        transport=httpx.MockTransport(handler),
    )

    response = client.post(
        f"/me/buddies/{buddy['buddy_id']}/state-memory/captures/voice",
        headers={"Authorization": f"Bearer {token}"},
        json={"content": "我买了鸡蛋"},
    )

    assert response.status_code == 503
    assert response.json() == {"detail": {"code": "model_response_invalid"}}
    assert client.get(
        f"/me/buddies/{buddy['buddy_id']}/state-memory/pending-proposals",
        headers={"Authorization": f"Bearer {token}"},
    ).json() == {"pending_proposals": []}

    usage_entries = app.state.usage_store.list_usage(buddy["user_id"])
    assert len(usage_entries) == 1
    assert usage_entries[0].provider_id == "minimax-openai"
    assert usage_entries[0].model_id == "MiniMax-M3"
    assert usage_entries[0].source == "state_memory_capture"
    assert usage_entries[0].input_tokens == 7
    assert usage_entries[0].output_tokens == 9
    cost_events = client.get("/cost-events", headers={"Authorization": f"Bearer {token}"}).json()["cost_events"]
    assert len(cost_events) == 1
    trace_id = cost_events[0]["trace_id"]
    trace_response = client.get(
        f"/traces/{trace_id}",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert trace_response.status_code == 200
    trace = trace_response.json()
    assert trace["failure_class"] == "model_response_invalid"
    assert trace["intent"]["name"] == "state_memory_capture"
    assert trace["proposal"] is None
    assert trace["model_usage"]["provider"] == "minimax-openai"
    assert trace["model_usage"]["model"] == "MiniMax-M3"
    assert trace["model_usage"]["input_tokens"] == 7
    assert trace["model_usage"]["output_tokens"] == 9
    assert trace["cost_refs"] == [cost_events[0]["cost_event_id"]]


def test_state_memory_real_query_invalid_understanding_still_records_usage_cost_and_trace(
    tmp_path,
    monkeypatch,
) -> None:
    import httpx
    import json

    app = create_app(db_path=tmp_path / "buddys.sqlite3")
    client = TestClient(app)
    token = register(client, "owner@example.com")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-real-provider-test")
    buddy = client.post(
        "/me/buddies",
        headers={"Authorization": f"Bearer {token}"},
        json={"name": "Kitchen Buddy", "space_id": "kitchen"},
    ).json()
    provider_response = client.post(
        "/providers",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "provider_id": "minimax-openai",
            "display_name": "MiniMax OpenAI Compatible",
            "provider_type": "openai_compatible",
            "base_url": "https://api.minimaxi.com/v1",
            "api_key_env_var": "OPENAI_API_KEY",
            "default_model": "MiniMax-M3",
        },
    )
    assert provider_response.status_code == 200

    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "message": {
                            "content": json.dumps(
                                {
                                    "answer_type": "missing_for_recipe",
                                    "subject_name": "红烧肉",
                                    "required_items": [],
                                },
                                ensure_ascii=False,
                            )
                        }
                    }
                ],
                "usage": {"prompt_tokens": 13, "completion_tokens": 15},
            },
        )

    app.state.state_memory_service.provider_factory = lambda config: OpenAICompatibleProvider(
        provider_id=config.provider_id,
        base_url=config.base_url or "https://api.minimaxi.com/v1",
        api_key_env_var=config.api_key_env_var or "OPENAI_API_KEY",
        model=config.default_model,
        transport=httpx.MockTransport(handler),
    )

    response = client.post(
        f"/me/buddies/{buddy['buddy_id']}/state-memory/query",
        headers={"Authorization": f"Bearer {token}"},
        json={"question": "做红烧肉还缺什么"},
    )

    assert response.status_code == 503
    assert response.json() == {"detail": {"code": "model_response_invalid"}}

    usage_entries = app.state.usage_store.list_usage(buddy["user_id"])
    assert len(usage_entries) == 1
    assert usage_entries[0].provider_id == "minimax-openai"
    assert usage_entries[0].model_id == "MiniMax-M3"
    assert usage_entries[0].source == "state_memory_query"
    assert usage_entries[0].input_tokens == 13
    assert usage_entries[0].output_tokens == 15
    cost_events = client.get("/cost-events", headers={"Authorization": f"Bearer {token}"}).json()["cost_events"]
    assert len(cost_events) == 1
    trace_id = cost_events[0]["trace_id"]
    trace_response = client.get(
        f"/traces/{trace_id}",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert trace_response.status_code == 200
    trace = trace_response.json()
    assert trace["failure_class"] == "model_response_invalid"
    assert trace["intent"]["name"] == "state_memory_query"
    assert trace["proposal"] is None
    assert trace["model_usage"]["provider"] == "minimax-openai"
    assert trace["model_usage"]["model"] == "MiniMax-M3"
    assert trace["model_usage"]["input_tokens"] == 13
    assert trace["model_usage"]["output_tokens"] == 15
    assert trace["cost_refs"] == [cost_events[0]["cost_event_id"]]


def test_state_memory_real_query_unsupported_still_records_usage_cost_and_trace(
    tmp_path,
    monkeypatch,
) -> None:
    import httpx
    import json

    app = create_app(db_path=tmp_path / "buddys.sqlite3")
    client = TestClient(app)
    token = register(client, "owner@example.com")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-real-provider-test")
    buddy = client.post(
        "/me/buddies",
        headers={"Authorization": f"Bearer {token}"},
        json={"name": "Kitchen Buddy", "space_id": "kitchen"},
    ).json()
    provider_response = client.post(
        "/providers",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "provider_id": "minimax-openai",
            "display_name": "MiniMax OpenAI Compatible",
            "provider_type": "openai_compatible",
            "base_url": "https://api.minimaxi.com/v1",
            "api_key_env_var": "OPENAI_API_KEY",
            "default_model": "MiniMax-M3",
        },
    )
    assert provider_response.status_code == 200

    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "message": {
                            "content": json.dumps(
                                {
                                    "answer_type": "unsupported",
                                    "subject_name": None,
                                    "required_items": [],
                                },
                                ensure_ascii=False,
                            )
                        }
                    }
                ],
                "usage": {"prompt_tokens": 8, "completion_tokens": 10},
            },
        )

    app.state.state_memory_service.provider_factory = lambda config: OpenAICompatibleProvider(
        provider_id=config.provider_id,
        base_url=config.base_url or "https://api.minimaxi.com/v1",
        api_key_env_var=config.api_key_env_var or "OPENAI_API_KEY",
        model=config.default_model,
        transport=httpx.MockTransport(handler),
    )

    response = client.post(
        f"/me/buddies/{buddy['buddy_id']}/state-memory/query",
        headers={"Authorization": f"Bearer {token}"},
        json={"question": "帮我决定明天吃什么"},
    )

    assert response.status_code == 422
    assert response.json() == {"detail": {"code": "state_memory_query_unsupported"}}

    usage_entries = app.state.usage_store.list_usage(buddy["user_id"])
    assert len(usage_entries) == 1
    assert usage_entries[0].source == "state_memory_query"
    assert usage_entries[0].input_tokens == 8
    assert usage_entries[0].output_tokens == 10
    cost_events = client.get("/cost-events", headers={"Authorization": f"Bearer {token}"}).json()["cost_events"]
    assert len(cost_events) == 1
    trace_response = client.get(
        f"/traces/{cost_events[0]['trace_id']}",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert trace_response.status_code == 200
    trace = trace_response.json()
    assert trace["failure_class"] == "state_memory_query_unsupported"
    assert trace["intent"]["name"] == "state_memory_query"
    assert trace["proposal"] is None


def test_state_memory_real_provider_missing_env_key_fails_instead_of_falling_back_to_mock(tmp_path) -> None:
    app = create_app(db_path=tmp_path / "buddys.sqlite3")
    client = TestClient(app)
    token = register(client, "owner@example.com")
    buddy = client.post(
        "/me/buddies",
        headers={"Authorization": f"Bearer {token}"},
        json={"name": "Kitchen Buddy", "space_id": "kitchen"},
    ).json()
    provider_response = client.post(
        "/providers",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "provider_id": "minimax-openai",
            "display_name": "MiniMax OpenAI Compatible",
            "provider_type": "openai_compatible",
            "base_url": "https://api.minimaxi.com/v1",
            "api_key_env_var": "OPENAI_API_KEY",
            "default_model": "MiniMax-M3",
        },
    )
    assert provider_response.status_code == 200
    assert provider_response.json()["configured"] is False

    response = client.post(
        f"/me/buddies/{buddy['buddy_id']}/state-memory/captures/voice",
        headers={"Authorization": f"Bearer {token}"},
        json={"content": "我买了五个鸡蛋"},
    )

    assert response.status_code == 503
    assert response.json() == {"detail": {"code": "provider_not_configured"}}
    assert app.state.usage_store.list_usage(buddy["user_id"]) == []
    assert client.get("/cost-events", headers={"Authorization": f"Bearer {token}"}).json() == {"cost_events": []}
    assert app.state.runtime.trace_store.list() == []
    assert client.get(
        f"/me/buddies/{buddy['buddy_id']}/state-memory/pending-proposals",
        headers={"Authorization": f"Bearer {token}"},
    ).json() == {"pending_proposals": []}


def test_state_memory_zero_config_default_provider_uses_system_managed_env_without_listing_it(
    tmp_path,
    monkeypatch,
) -> None:
    app = create_app(db_path=tmp_path / "buddys.sqlite3")
    client = TestClient(app)
    token = register(client, "owner@example.com")
    monkeypatch.setenv("BUDDYS_DEFAULT_OPENAI_API_KEY", "sk-system-default")
    monkeypatch.setenv("BUDDYS_DEFAULT_TOKEN_PLAN_KEY", "sk-cp-system-default")
    buddy = client.post(
        "/me/buddies",
        headers={"Authorization": f"Bearer {token}"},
        json={"name": "Kitchen Buddy", "space_id": "kitchen"},
    ).json()

    seen = {}

    class FakeDefaultProvider:
        provider = "system-minimax-default"
        model = "MiniMax-M3"

        def parse_state_memory_capture(self, *, source, content):
            seen["source"] = source
            seen["content"] = content
            return (
                [
                    StateMemoryDelta(
                        item_name="鸡蛋",
                        operation="upsert",
                        quantity=5,
                        unit="个",
                        category="ingredient",
                        source=source,
                    )
                ],
                [],
            )

    def provider_factory(config):
        seen["provider_id"] = config.provider_id
        seen["api_key_env_var"] = config.api_key_env_var
        return FakeDefaultProvider()

    app.state.state_memory_service.provider_factory = provider_factory

    response = client.post(
        f"/me/buddies/{buddy['buddy_id']}/state-memory/captures/voice",
        headers={"Authorization": f"Bearer {token}"},
        json={"content": "我买了五个鸡蛋"},
    )
    providers = client.get("/providers", headers={"Authorization": f"Bearer {token}"}).json()

    assert response.status_code == 201
    assert response.json()["proposal"]["deltas"][0]["item_name"] == "鸡蛋"
    assert seen == {
        "provider_id": "system-minimax-default",
        "api_key_env_var": "BUDDYS_DEFAULT_OPENAI_API_KEY",
        "source": "voice",
        "content": "我买了五个鸡蛋",
    }
    assert providers["configs"] == []
    assert "BUDDYS_DEFAULT_OPENAI_API_KEY" not in str(providers)
    assert "BUDDYS_DEFAULT_TOKEN_PLAN_KEY" not in str(providers)
    assert "system-minimax-default" not in str(providers)


def test_state_memory_zero_config_token_plan_default_provider_is_used_when_api_key_default_absent(
    tmp_path,
    monkeypatch,
) -> None:
    monkeypatch.delenv("BUDDYS_DEFAULT_OPENAI_API_KEY", raising=False)
    monkeypatch.setenv("BUDDYS_DEFAULT_TOKEN_PLAN_KEY", "sk-cp-system-default")
    app = create_app(db_path=tmp_path / "buddys.sqlite3")
    client = TestClient(app)
    token = register(client, "owner@example.com")
    buddy = client.post(
        "/me/buddies",
        headers={"Authorization": f"Bearer {token}"},
        json={"name": "Kitchen Buddy", "space_id": "kitchen"},
    ).json()

    seen = {}

    class FakeDefaultProvider:
        provider = "system-minimax-default"
        model = "MiniMax-M3"

        def parse_state_memory_capture(self, *, source, content):
            seen["source"] = source
            seen["content"] = content
            return ([StateMemoryDelta(item_name="牛奶", operation="upsert", source=source)], [])

    def provider_factory(config):
        seen["provider_id"] = config.provider_id
        seen["api_key_env_var"] = config.api_key_env_var
        return FakeDefaultProvider()

    app.state.state_memory_service.provider_factory = provider_factory

    response = client.post(
        f"/me/buddies/{buddy['buddy_id']}/state-memory/captures/voice",
        headers={"Authorization": f"Bearer {token}"},
        json={"content": "我买了牛奶"},
    )

    assert response.status_code == 201
    assert seen["provider_id"] == "system-minimax-default"
    assert seen["api_key_env_var"] == "BUDDYS_DEFAULT_TOKEN_PLAN_KEY"


def test_state_memory_without_any_default_env_still_falls_back_to_mock_provider(tmp_path, monkeypatch) -> None:
    monkeypatch.delenv("BUDDYS_DEFAULT_OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("BUDDYS_DEFAULT_TOKEN_PLAN_KEY", raising=False)
    app = create_app(db_path=tmp_path / "buddys.sqlite3")
    client = TestClient(app)
    token = register(client, "owner@example.com")
    buddy = client.post(
        "/me/buddies",
        headers={"Authorization": f"Bearer {token}"},
        json={"name": "Kitchen Buddy", "space_id": "kitchen"},
    ).json()

    response = client.post(
        f"/me/buddies/{buddy['buddy_id']}/state-memory/captures/voice",
        headers={"Authorization": f"Bearer {token}"},
        json={"content": "我买了五个鸡蛋和一包面粉"},
    )

    assert response.status_code == 201
    assert [delta["item_name"] for delta in response.json()["proposal"]["deltas"]] == ["鸡蛋"]
    assert response.json()["proposal"]["unrecognized"] == ["一包面粉"]


def test_state_memory_user_configured_real_provider_wins_over_system_default_provider(
    tmp_path,
    monkeypatch,
) -> None:
    monkeypatch.setenv("BUDDYS_DEFAULT_OPENAI_API_KEY", "sk-system-default")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-user-managed")
    app = create_app(db_path=tmp_path / "buddys.sqlite3")
    client = TestClient(app)
    token = register(client, "owner@example.com")
    buddy = client.post(
        "/me/buddies",
        headers={"Authorization": f"Bearer {token}"},
        json={"name": "Kitchen Buddy", "space_id": "kitchen"},
    ).json()
    provider_response = client.post(
        "/providers",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "provider_id": "user-minimax-openai",
            "display_name": "MiniMax OpenAI Compatible",
            "provider_type": "openai_compatible",
            "base_url": "https://api.minimaxi.com/v1",
            "api_key_env_var": "OPENAI_API_KEY",
            "default_model": "MiniMax-M3",
        },
    )
    assert provider_response.status_code == 200

    seen = {}

    class FakeUserProvider:
        provider = "user-minimax-openai"
        model = "MiniMax-M3"

        def parse_state_memory_capture(self, *, source, content):
            seen["source"] = source
            seen["content"] = content
            return ([StateMemoryDelta(item_name="牛奶", operation="upsert", source=source)], [])

    def provider_factory(config):
        seen["provider_id"] = config.provider_id
        seen["api_key_env_var"] = config.api_key_env_var
        return FakeUserProvider()

    app.state.state_memory_service.provider_factory = provider_factory

    response = client.post(
        f"/me/buddies/{buddy['buddy_id']}/state-memory/captures/voice",
        headers={"Authorization": f"Bearer {token}"},
        json={"content": "我买了牛奶"},
    )

    assert response.status_code == 201
    assert response.json()["proposal"]["deltas"][0]["item_name"] == "牛奶"
    assert seen["provider_id"] == "user-minimax-openai"
    assert seen["api_key_env_var"] == "OPENAI_API_KEY"


def test_state_memory_multiple_real_provider_configs_fail_fast_instead_of_lexicographic_routing(
    tmp_path,
    monkeypatch,
) -> None:
    app = create_app(db_path=tmp_path / "buddys.sqlite3")
    client = TestClient(app)
    token = register(client, "owner@example.com")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-real-provider-test")
    buddy = client.post(
        "/me/buddies",
        headers={"Authorization": f"Bearer {token}"},
        json={"name": "Kitchen Buddy", "space_id": "kitchen"},
    ).json()
    for provider_id in ("a-provider", "z-provider"):
        provider_response = client.post(
            "/providers",
            headers={"Authorization": f"Bearer {token}"},
            json={
                "provider_id": provider_id,
                "display_name": f"Provider {provider_id}",
                "provider_type": "openai_compatible",
                "base_url": "https://api.minimaxi.com/v1",
                "api_key_env_var": "OPENAI_API_KEY",
                "default_model": "MiniMax-M3",
            },
        )
        assert provider_response.status_code == 200

    call_count = {"value": 0}

    def provider_factory(_config):
        call_count["value"] += 1
        raise AssertionError("provider factory should not run when selection is ambiguous")

    app.state.state_memory_service.provider_factory = provider_factory

    response = client.post(
        f"/me/buddies/{buddy['buddy_id']}/state-memory/query",
        headers={"Authorization": f"Bearer {token}"},
        json={"question": "有鸡蛋吗"},
    )

    assert response.status_code == 503
    assert response.json() == {"detail": {"code": "provider_selection_ambiguous"}}
    assert call_count["value"] == 0
    assert app.state.usage_store.list_usage(buddy["user_id"]) == []
    assert client.get("/cost-events", headers={"Authorization": f"Bearer {token}"}).json() == {"cost_events": []}
    assert app.state.runtime.trace_store.list() == []


def test_state_memory_real_capture_preflight_blocks_near_limit_before_provider_call_and_persistence(
    tmp_path,
    monkeypatch,
) -> None:
    import httpx

    app = create_app(db_path=tmp_path / "buddys.sqlite3")
    client = TestClient(app)
    token = register(client, "owner@example.com")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-real-provider-test")
    buddy = client.post(
        "/me/buddies",
        headers={"Authorization": f"Bearer {token}"},
        json={"name": "Kitchen Buddy", "space_id": "kitchen"},
    ).json()
    provider_response = client.post(
        "/providers",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "provider_id": "minimax-openai",
            "display_name": "MiniMax OpenAI Compatible",
            "provider_type": "openai_compatible",
            "base_url": "https://api.minimaxi.com/v1",
            "api_key_env_var": "OPENAI_API_KEY",
            "default_model": "MiniMax-M3",
        },
    )
    assert provider_response.status_code == 200
    call_count = {"value": 0}

    def handler(_: httpx.Request) -> httpx.Response:
        call_count["value"] += 1
        return httpx.Response(500, json={"error": "should-not-be-called"})

    app.state.state_memory_service.provider_factory = lambda config: OpenAICompatibleProvider(
        provider_id=config.provider_id,
        base_url=config.base_url or "https://api.minimaxi.com/v1",
        api_key_env_var=config.api_key_env_var or "OPENAI_API_KEY",
        model=config.default_model,
        transport=httpx.MockTransport(handler),
    )

    usage_store = app.state.usage_store
    limit = usage_store.usage_summary(buddy["user_id"]).monthly_token_limit
    assert limit is not None
    usage_store.record_usage(
        user_id=buddy["user_id"],
        trace_id="trace_near_limit",
        buddy_id=buddy["buddy_id"],
        provider_id="seed_provider",
        model_id="seed_model",
        input_tokens=limit - 8,
        output_tokens=0,
        source="test_seed",
    )

    response = client.post(
        f"/me/buddies/{buddy['buddy_id']}/state-memory/captures/voice",
        headers={"Authorization": f"Bearer {token}"},
        json={"content": "蛋"},
    )

    assert response.status_code == 429
    assert response.json()["detail"]["code"] == "token_plan_limit_exceeded"
    assert call_count["value"] == 0
    assert app.state.usage_store.usage_summary(buddy["user_id"]).used_tokens == limit - 8
    assert client.get("/cost-events", headers={"Authorization": f"Bearer {token}"}).json() == {"cost_events": []}
    pending = client.get(
        f"/me/buddies/{buddy['buddy_id']}/state-memory/pending-proposals",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert pending.json() == {"pending_proposals": []}


def test_state_memory_real_photo_capture_preflight_blocks_near_limit_before_provider_call(
    tmp_path,
    monkeypatch,
) -> None:
    import base64
    import httpx

    app = create_app(db_path=tmp_path / "buddys.sqlite3")
    client = TestClient(app)
    token = register(client, "owner@example.com")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-real-provider-test")
    buddy = client.post(
        "/me/buddies",
        headers={"Authorization": f"Bearer {token}"},
        json={"name": "Kitchen Buddy", "space_id": "kitchen"},
    ).json()
    provider_response = client.post(
        "/providers",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "provider_id": "minimax-openai",
            "display_name": "MiniMax OpenAI Compatible",
            "provider_type": "openai_compatible",
            "base_url": "https://api.minimaxi.com/v1",
            "api_key_env_var": "OPENAI_API_KEY",
            "default_model": "MiniMax-M3",
        },
    )
    assert provider_response.status_code == 200
    call_count = {"value": 0}

    def handler(_: httpx.Request) -> httpx.Response:
        call_count["value"] += 1
        return httpx.Response(500, json={"error": "should-not-be-called"})

    app.state.state_memory_service.provider_factory = lambda config: OpenAICompatibleProvider(
        provider_id=config.provider_id,
        base_url=config.base_url or "https://api.minimaxi.com/v1",
        api_key_env_var=config.api_key_env_var or "OPENAI_API_KEY",
        model=config.default_model,
        transport=httpx.MockTransport(handler),
    )

    usage_store = app.state.usage_store
    limit = usage_store.usage_summary(buddy["user_id"]).monthly_token_limit
    assert limit is not None
    usage_store.record_usage(
        user_id=buddy["user_id"],
        trace_id="trace_near_photo_limit",
        buddy_id=buddy["buddy_id"],
        provider_id="seed_provider",
        model_id="seed_model",
        input_tokens=limit - 120,
        output_tokens=0,
        source="test_seed",
    )
    image_base64 = base64.b64encode(b"x" * 512).decode("ascii")

    response = client.post(
        f"/me/buddies/{buddy['buddy_id']}/state-memory/captures/photo",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "content": "冰箱照片",
            "image_base64": image_base64,
            "image_media_type": "image/png",
        },
    )

    assert response.status_code == 429
    assert response.json()["detail"]["code"] == "token_plan_limit_exceeded"
    assert call_count["value"] == 0
    assert app.state.usage_store.usage_summary(buddy["user_id"]).used_tokens == limit - 120
    assert client.get("/cost-events", headers={"Authorization": f"Bearer {token}"}).json() == {"cost_events": []}


def test_state_memory_real_capture_post_call_over_limit_returns_429_without_persistence(tmp_path, monkeypatch) -> None:
    import httpx
    import json

    app = create_app(db_path=tmp_path / "buddys.sqlite3")
    client = TestClient(app)
    token = register(client, "owner@example.com")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-real-provider-test")
    buddy = client.post(
        "/me/buddies",
        headers={"Authorization": f"Bearer {token}"},
        json={"name": "Kitchen Buddy", "space_id": "kitchen"},
    ).json()
    provider_response = client.post(
        "/providers",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "provider_id": "minimax-openai",
            "display_name": "MiniMax OpenAI Compatible",
            "provider_type": "openai_compatible",
            "base_url": "https://api.minimaxi.com/v1",
            "api_key_env_var": "OPENAI_API_KEY",
            "default_model": "MiniMax-M3",
        },
    )
    assert provider_response.status_code == 200
    call_count = {"value": 0}

    def handler(_: httpx.Request) -> httpx.Response:
        call_count["value"] += 1
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "message": {
                            "content": json.dumps(
                                {
                                    "deltas": [
                                        {
                                            "item_name": "鸡蛋",
                                            "operation": "upsert",
                                            "quantity": 2,
                                            "unit": "盒",
                                            "category": "ingredient",
                                            "confidence": 0.93,
                                            "source": "voice",
                                        }
                                    ],
                                    "unrecognized": [],
                                },
                                ensure_ascii=False,
                            )
                        }
                    }
                ],
                "usage": {"prompt_tokens": 20, "completion_tokens": 20},
            },
        )

    app.state.state_memory_service.provider_factory = lambda config: OpenAICompatibleProvider(
        provider_id=config.provider_id,
        base_url=config.base_url or "https://api.minimaxi.com/v1",
        api_key_env_var=config.api_key_env_var or "OPENAI_API_KEY",
        model=config.default_model,
        transport=httpx.MockTransport(handler),
    )

    usage_store = app.state.usage_store
    limit = usage_store.usage_summary(buddy["user_id"]).monthly_token_limit
    assert limit is not None
    usage_store.record_usage(
        user_id=buddy["user_id"],
        trace_id="trace_near_limit",
        buddy_id=buddy["buddy_id"],
        provider_id="seed_provider",
        model_id="seed_model",
        input_tokens=limit - 20,
        output_tokens=0,
        source="test_seed",
    )

    response = client.post(
        f"/me/buddies/{buddy['buddy_id']}/state-memory/captures/voice",
        headers={"Authorization": f"Bearer {token}"},
        json={"content": "蛋"},
    )

    assert response.status_code == 429
    assert response.json()["detail"]["code"] == "token_plan_limit_exceeded"
    assert call_count["value"] == 1
    usage_entries = app.state.usage_store.list_usage(buddy["user_id"])
    assert [entry.trace_id for entry in usage_entries] == ["trace_near_limit", usage_entries[1].trace_id]
    assert usage_entries[1].source == "state_memory_capture"
    assert usage_entries[1].input_tokens == 20
    assert usage_entries[1].output_tokens == 20
    cost_events = client.get("/cost-events", headers={"Authorization": f"Bearer {token}"}).json()["cost_events"]
    assert len(cost_events) == 1
    trace_response = client.get(
        f"/traces/{cost_events[0]['trace_id']}",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert trace_response.status_code == 200
    trace = trace_response.json()
    assert trace["failure_class"] == "token_plan_limit_exceeded"
    assert trace["intent"]["name"] == "state_memory_capture"
    assert trace["proposal"] is None
    pending = client.get(
        f"/me/buddies/{buddy['buddy_id']}/state-memory/pending-proposals",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert pending.json() == {"pending_proposals": []}


def test_state_memory_real_query_preflight_blocks_near_limit_before_provider_call(tmp_path, monkeypatch) -> None:
    import httpx

    app = create_app(db_path=tmp_path / "buddys.sqlite3")
    client = TestClient(app)
    token = register(client, "owner@example.com")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-real-provider-test")
    buddy = client.post(
        "/me/buddies",
        headers={"Authorization": f"Bearer {token}"},
        json={"name": "Kitchen Buddy", "space_id": "kitchen"},
    ).json()
    provider_response = client.post(
        "/providers",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "provider_id": "minimax-openai",
            "display_name": "MiniMax OpenAI Compatible",
            "provider_type": "openai_compatible",
            "base_url": "https://api.minimaxi.com/v1",
            "api_key_env_var": "OPENAI_API_KEY",
            "default_model": "MiniMax-M3",
        },
    )
    assert provider_response.status_code == 200
    call_count = {"value": 0}

    def handler(_: httpx.Request) -> httpx.Response:
        call_count["value"] += 1
        return httpx.Response(500, json={"error": "should-not-be-called"})

    app.state.state_memory_service.provider_factory = lambda config: OpenAICompatibleProvider(
        provider_id=config.provider_id,
        base_url=config.base_url or "https://api.minimaxi.com/v1",
        api_key_env_var=config.api_key_env_var or "OPENAI_API_KEY",
        model=config.default_model,
        transport=httpx.MockTransport(handler),
    )

    usage_store = app.state.usage_store
    limit = usage_store.usage_summary(buddy["user_id"]).monthly_token_limit
    assert limit is not None
    usage_store.record_usage(
        user_id=buddy["user_id"],
        trace_id="trace_near_limit",
        buddy_id=buddy["buddy_id"],
        provider_id="seed_provider",
        model_id="seed_model",
        input_tokens=limit - 8,
        output_tokens=0,
        source="test_seed",
    )

    response = client.post(
        f"/me/buddies/{buddy['buddy_id']}/state-memory/query",
        headers={"Authorization": f"Bearer {token}"},
        json={"question": "鸡蛋?"},
    )

    assert response.status_code == 429
    assert response.json()["detail"]["code"] == "token_plan_limit_exceeded"
    assert call_count["value"] == 0
    assert app.state.usage_store.usage_summary(buddy["user_id"]).used_tokens == limit - 8
    assert client.get("/cost-events", headers={"Authorization": f"Bearer {token}"}).json() == {"cost_events": []}


def test_state_memory_real_query_post_call_over_limit_records_usage_cost_and_trace(tmp_path, monkeypatch) -> None:
    import httpx
    import json

    app = create_app(db_path=tmp_path / "buddys.sqlite3")
    client = TestClient(app)
    token = register(client, "owner@example.com")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-real-provider-test")
    buddy = client.post(
        "/me/buddies",
        headers={"Authorization": f"Bearer {token}"},
        json={"name": "Kitchen Buddy", "space_id": "kitchen"},
    ).json()
    provider_response = client.post(
        "/providers",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "provider_id": "minimax-openai",
            "display_name": "MiniMax OpenAI Compatible",
            "provider_type": "openai_compatible",
            "base_url": "https://api.minimaxi.com/v1",
            "api_key_env_var": "OPENAI_API_KEY",
            "default_model": "MiniMax-M3",
        },
    )
    assert provider_response.status_code == 200

    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "message": {
                            "content": json.dumps(
                                {
                                    "answer_type": "have_item",
                                    "subject_name": "鸡蛋",
                                    "required_items": [],
                                },
                                ensure_ascii=False,
                            )
                        }
                    }
                ],
                "usage": {"prompt_tokens": 20, "completion_tokens": 20},
            },
        )

    app.state.state_memory_service.provider_factory = lambda config: OpenAICompatibleProvider(
        provider_id=config.provider_id,
        base_url=config.base_url or "https://api.minimaxi.com/v1",
        api_key_env_var=config.api_key_env_var or "OPENAI_API_KEY",
        model=config.default_model,
        transport=httpx.MockTransport(handler),
    )

    usage_store = app.state.usage_store
    limit = usage_store.usage_summary(buddy["user_id"]).monthly_token_limit
    assert limit is not None
    usage_store.record_usage(
        user_id=buddy["user_id"],
        trace_id="trace_near_limit",
        buddy_id=buddy["buddy_id"],
        provider_id="seed_provider",
        model_id="seed_model",
        input_tokens=limit - 21,
        output_tokens=0,
        source="test_seed",
    )

    response = client.post(
        f"/me/buddies/{buddy['buddy_id']}/state-memory/query",
        headers={"Authorization": f"Bearer {token}"},
        json={"question": "有鸡蛋吗"},
    )

    assert response.status_code == 429
    assert response.json()["detail"]["code"] == "token_plan_limit_exceeded"
    usage_entries = app.state.usage_store.list_usage(buddy["user_id"])
    assert [entry.trace_id for entry in usage_entries] == ["trace_near_limit", usage_entries[1].trace_id]
    assert usage_entries[1].source == "state_memory_query"
    assert usage_entries[1].input_tokens == 20
    assert usage_entries[1].output_tokens == 20
    cost_events = client.get("/cost-events", headers={"Authorization": f"Bearer {token}"}).json()["cost_events"]
    assert len(cost_events) == 1
    trace_response = client.get(
        f"/traces/{cost_events[0]['trace_id']}",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert trace_response.status_code == 200
    trace = trace_response.json()
    assert trace["failure_class"] == "token_plan_limit_exceeded"
    assert trace["intent"]["name"] == "state_memory_query"
    assert trace["proposal"] is None


def test_state_memory_real_query_late_quota_race_keeps_success_and_accounting(tmp_path, monkeypatch) -> None:
    import httpx
    import json

    app = create_app(db_path=tmp_path / "buddys.sqlite3")
    client = TestClient(app)
    token = register(client, "owner@example.com")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-real-provider-test")
    buddy = client.post(
        "/me/buddies",
        headers={"Authorization": f"Bearer {token}"},
        json={"name": "Kitchen Buddy", "space_id": "kitchen"},
    ).json()
    provider_response = client.post(
        "/providers",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "provider_id": "minimax-openai",
            "display_name": "MiniMax OpenAI Compatible",
            "provider_type": "openai_compatible",
            "base_url": "https://api.minimaxi.com/v1",
            "api_key_env_var": "OPENAI_API_KEY",
            "default_model": "MiniMax-M3",
        },
    )
    assert provider_response.status_code == 200

    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "message": {
                            "content": json.dumps(
                                {
                                    "answer_type": "have_item",
                                    "subject_name": "鸡蛋",
                                    "required_items": [],
                                },
                                ensure_ascii=False,
                            )
                        }
                    }
                ],
                "usage": {"prompt_tokens": 20, "completion_tokens": 20},
            },
        )

    app.state.state_memory_service.provider_factory = lambda config: OpenAICompatibleProvider(
        provider_id=config.provider_id,
        base_url=config.base_url or "https://api.minimaxi.com/v1",
        api_key_env_var=config.api_key_env_var or "OPENAI_API_KEY",
        model=config.default_model,
        transport=httpx.MockTransport(handler),
    )

    usage_store = app.state.usage_store
    limit = usage_store.usage_summary(buddy["user_id"]).monthly_token_limit
    assert limit is not None
    usage_store.record_usage(
        user_id=buddy["user_id"],
        trace_id="trace_seed",
        buddy_id=buddy["buddy_id"],
        provider_id="seed_provider",
        model_id="seed_model",
        input_tokens=limit - 70,
        output_tokens=0,
        source="test_seed",
    )

    original_record_usage = usage_store.record_usage
    injected = {"done": False}

    def record_usage_with_race(**kwargs):
        if kwargs["source"] == "state_memory_query" and not injected["done"]:
            injected["done"] = True
            original_record_usage(
                user_id=buddy["user_id"],
                trace_id="trace_rival",
                buddy_id=buddy["buddy_id"],
                provider_id="rival_provider",
                model_id="rival_model",
                input_tokens=35,
                output_tokens=0,
                source="test_rival",
                enforce_hard_limit=False,
            )
        return original_record_usage(**kwargs)

    usage_store.record_usage = record_usage_with_race

    response = client.post(
        f"/me/buddies/{buddy['buddy_id']}/state-memory/query",
        headers={"Authorization": f"Bearer {token}"},
        json={"question": "有鸡蛋吗"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["answer_type"] == "have_item"
    usage_entries = app.state.usage_store.list_usage(buddy["user_id"])
    assert [entry.trace_id for entry in usage_entries] == ["trace_seed", "trace_rival", usage_entries[2].trace_id]
    assert usage_entries[2].source == "state_memory_query"
    assert usage_entries[2].input_tokens == 20
    assert usage_entries[2].output_tokens == 20
    cost_events = client.get("/cost-events", headers={"Authorization": f"Bearer {token}"}).json()["cost_events"]
    assert len(cost_events) == 1
    trace_response = client.get(
        f"/traces/{body['trace_id']}",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert trace_response.status_code == 200
    trace = trace_response.json()
    assert trace["failure_class"] is None
    assert trace["proposal"]["summary"] == body["summary"]


def test_state_memory_real_capture_late_quota_race_keeps_success_and_accounting(tmp_path, monkeypatch) -> None:
    import httpx
    import json

    app = create_app(db_path=tmp_path / "buddys.sqlite3")
    client = TestClient(app)
    token = register(client, "owner@example.com")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-real-provider-test")
    buddy = client.post(
        "/me/buddies",
        headers={"Authorization": f"Bearer {token}"},
        json={"name": "Kitchen Buddy", "space_id": "kitchen"},
    ).json()
    provider_response = client.post(
        "/providers",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "provider_id": "minimax-openai",
            "display_name": "MiniMax OpenAI Compatible",
            "provider_type": "openai_compatible",
            "base_url": "https://api.minimaxi.com/v1",
            "api_key_env_var": "OPENAI_API_KEY",
            "default_model": "MiniMax-M3",
        },
    )
    assert provider_response.status_code == 200

    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "message": {
                            "content": json.dumps(
                                {
                                    "deltas": [
                                        {
                                            "item_name": "鸡蛋",
                                            "operation": "upsert",
                                            "quantity": 2,
                                            "unit": "盒",
                                            "category": "ingredient",
                                            "confidence": 0.93,
                                            "source": "voice",
                                        }
                                    ],
                                    "unrecognized": [],
                                },
                                ensure_ascii=False,
                            )
                        }
                    }
                ],
                "usage": {"prompt_tokens": 20, "completion_tokens": 20},
            },
        )

    app.state.state_memory_service.provider_factory = lambda config: OpenAICompatibleProvider(
        provider_id=config.provider_id,
        base_url=config.base_url or "https://api.minimaxi.com/v1",
        api_key_env_var=config.api_key_env_var or "OPENAI_API_KEY",
        model=config.default_model,
        transport=httpx.MockTransport(handler),
    )

    usage_store = app.state.usage_store
    limit = usage_store.usage_summary(buddy["user_id"]).monthly_token_limit
    assert limit is not None
    usage_store.record_usage(
        user_id=buddy["user_id"],
        trace_id="trace_seed",
        buddy_id=buddy["buddy_id"],
        provider_id="seed_provider",
        model_id="seed_model",
        input_tokens=limit - 70,
        output_tokens=0,
        source="test_seed",
    )

    original_record_usage = usage_store.record_usage
    injected = {"done": False}

    def record_usage_with_race(**kwargs):
        if kwargs["source"] == "state_memory_capture" and not injected["done"]:
            injected["done"] = True
            original_record_usage(
                user_id=buddy["user_id"],
                trace_id="trace_rival",
                buddy_id=buddy["buddy_id"],
                provider_id="rival_provider",
                model_id="rival_model",
                input_tokens=35,
                output_tokens=0,
                source="test_rival",
                enforce_hard_limit=False,
            )
        return original_record_usage(**kwargs)

    usage_store.record_usage = record_usage_with_race

    response = client.post(
        f"/me/buddies/{buddy['buddy_id']}/state-memory/captures/voice",
        headers={"Authorization": f"Bearer {token}"},
        json={"content": "我买了两盒鸡蛋"},
    )

    assert response.status_code == 201
    body = response.json()
    assert [delta["item_name"] for delta in body["proposal"]["deltas"]] == ["鸡蛋"]
    usage_entries = app.state.usage_store.list_usage(buddy["user_id"])
    assert [entry.trace_id for entry in usage_entries] == ["trace_seed", "trace_rival", usage_entries[2].trace_id]
    assert usage_entries[2].source == "state_memory_capture"
    assert usage_entries[2].input_tokens == 20
    assert usage_entries[2].output_tokens == 20
    pending = client.get(
        f"/me/buddies/{buddy['buddy_id']}/state-memory/pending-proposals",
        headers={"Authorization": f"Bearer {token}"},
    ).json()["pending_proposals"]
    assert len(pending) == 1
    assert pending[0]["proposal_id"] == body["proposal"]["proposal_id"]
    cost_events = client.get("/cost-events", headers={"Authorization": f"Bearer {token}"}).json()["cost_events"]
    assert len(cost_events) == 1
    trace_response = client.get(
        f"/traces/{cost_events[0]['trace_id']}",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert trace_response.status_code == 200
    trace = trace_response.json()
    assert trace["failure_class"] is None
    assert trace["proposal"]["proposal_id"] == body["proposal"]["proposal_id"]


def test_state_memory_real_capture_failed_parse_near_limit_still_records_usage(tmp_path, monkeypatch) -> None:
    import httpx

    app = create_app(db_path=tmp_path / "buddys.sqlite3")
    client = TestClient(app)
    token = register(client, "owner@example.com")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-real-provider-test")
    buddy = client.post(
        "/me/buddies",
        headers={"Authorization": f"Bearer {token}"},
        json={"name": "Kitchen Buddy", "space_id": "kitchen"},
    ).json()
    provider_response = client.post(
        "/providers",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "provider_id": "minimax-openai",
            "display_name": "MiniMax OpenAI Compatible",
            "provider_type": "openai_compatible",
            "base_url": "https://api.minimaxi.com/v1",
            "api_key_env_var": "OPENAI_API_KEY",
            "default_model": "MiniMax-M3",
        },
    )
    assert provider_response.status_code == 200

    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "choices": [{"message": {"content": "not-json"}}],
                "usage": {"prompt_tokens": 20, "completion_tokens": 20},
            },
        )

    app.state.state_memory_service.provider_factory = lambda config: OpenAICompatibleProvider(
        provider_id=config.provider_id,
        base_url=config.base_url or "https://api.minimaxi.com/v1",
        api_key_env_var=config.api_key_env_var or "OPENAI_API_KEY",
        model=config.default_model,
        transport=httpx.MockTransport(handler),
    )

    usage_store = app.state.usage_store
    limit = usage_store.usage_summary(buddy["user_id"]).monthly_token_limit
    assert limit is not None
    usage_store.record_usage(
        user_id=buddy["user_id"],
        trace_id="trace_near_limit",
        buddy_id=buddy["buddy_id"],
        provider_id="seed_provider",
        model_id="seed_model",
        input_tokens=limit - 21,
        output_tokens=0,
        source="test_seed",
    )

    response = client.post(
        f"/me/buddies/{buddy['buddy_id']}/state-memory/captures/voice",
        headers={"Authorization": f"Bearer {token}"},
        json={"content": "我买了鸡蛋"},
    )

    assert response.status_code == 503
    assert response.json() == {"detail": {"code": "model_response_invalid"}}
    usage_entries = app.state.usage_store.list_usage(buddy["user_id"])
    assert [entry.trace_id for entry in usage_entries] == ["trace_near_limit", usage_entries[1].trace_id]
    assert usage_entries[1].source == "state_memory_capture"
    assert usage_entries[1].input_tokens == 20
    assert usage_entries[1].output_tokens == 20


def register(client: TestClient, email: str) -> str:
    response = client.post("/auth/register", json={"email": email, "password": "correct horse battery staple"})
    assert response.status_code == 201
    return response.json()["access_token"]
