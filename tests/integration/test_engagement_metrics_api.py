from datetime import datetime, timedelta, timezone

from fastapi.testclient import TestClient

from buddys_api.main import create_app


def test_retention_summary_requires_founder_allowlist_email(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("BUDDYS_FOUNDER_METRICS_EMAIL_ALLOWLIST", "founder@example.com")
    app = create_app(db_path=tmp_path / "buddys.sqlite3")
    client = TestClient(app)

    founder = _register(client, "founder@example.com")
    ordinary = _register(client, "member@example.com")

    founder_response = client.get(
        "/metrics/retention-summary",
        headers={"Authorization": f"Bearer {founder['token']}"},
    )
    ordinary_response = client.get(
        "/metrics/retention-summary",
        headers={"Authorization": f"Bearer {ordinary['token']}"},
    )

    assert founder_response.status_code == 200
    assert ordinary_response.status_code == 403
    assert ordinary_response.json() == {"detail": {"code": "founder_metrics_forbidden"}}


def test_retention_summary_counts_post_activation_maintenance_windows_without_raw_memory_payloads(
    tmp_path,
    monkeypatch,
) -> None:
    monkeypatch.setenv("BUDDYS_FOUNDER_METRICS_EMAIL_ALLOWLIST", "founder@example.com")
    app = create_app(db_path=tmp_path / "buddys.sqlite3")
    client = TestClient(app)
    founder = _register(client, "founder@example.com")

    d1_user = _register(client, "d1@example.com")
    d1_buddy = client.post(
        "/me/buddies",
        headers={"Authorization": f"Bearer {d1_user['token']}"},
        json={"name": "Kitchen Buddy", "space_id": "kitchen"},
    ).json()
    _seed_activation_sequence(
        app,
        user_id=d1_user["user_id"],
        buddy_id=d1_buddy["buddy_id"],
        base_time=datetime.now(timezone.utc) - timedelta(days=2),
    )
    _seed_maintenance_event(
        app,
        user_id=d1_user["user_id"],
        buddy_id=d1_buddy["buddy_id"],
        event_time=datetime.now(timezone.utc) - timedelta(hours=12),
    )

    d7_user = _register(client, "d7@example.com")
    d7_buddy = client.post(
        "/me/buddies",
        headers={"Authorization": f"Bearer {d7_user['token']}"},
        json={"name": "Pantry Buddy", "space_id": "pantry"},
    ).json()
    _seed_activation_sequence(
        app,
        user_id=d7_user["user_id"],
        buddy_id=d7_buddy["buddy_id"],
        base_time=datetime.now(timezone.utc) - timedelta(days=8),
    )
    _seed_maintenance_event(
        app,
        user_id=d7_user["user_id"],
        buddy_id=d7_buddy["buddy_id"],
        event_time=datetime.now(timezone.utc) - timedelta(hours=12),
    )

    loose_user = _register(client, "loose@example.com")
    loose_buddy = client.post(
        "/me/buddies",
        headers={"Authorization": f"Bearer {loose_user['token']}"},
        json={"name": "Loose Buddy", "space_id": "hall"},
    ).json()
    _seed_unordered_events(
        app,
        user_id=loose_user["user_id"],
        buddy_id=loose_buddy["buddy_id"],
        base_time=datetime.now(timezone.utc) - timedelta(days=5),
    )

    response = client.get(
        "/metrics/retention-summary",
        headers={"Authorization": f"Bearer {founder['token']}"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["d1_active_users"] == 1
    assert body["d3_active_users"] == 0
    assert body["d7_active_users"] == 1
    assert body["activated_users"] == 2
    assert body["capture_by_source"]["voice"] == 2
    assert "我买了五个鸡蛋" not in str(body)
    assert "有鸡蛋吗" not in str(body)
    assert "content" not in str(body).lower()


def _register(client: TestClient, email: str) -> dict[str, str]:
    response = client.post("/auth/register", json={"email": email, "password": "correct horse battery staple"})
    assert response.status_code == 201
    body = response.json()
    return {
        "token": body["access_token"],
        "user_id": body["user"]["user_id"],
    }


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


def _seed_activation_sequence(app, *, user_id: str, buddy_id: str, base_time: datetime) -> None:
    store = app.state.engagement_metrics_store
    capture = store.record_event(
        user_id=user_id,
        buddy_id=buddy_id,
        event_type="capture_submitted",
        capture_source="voice",
    )
    confirm = store.record_event(
        user_id=user_id,
        buddy_id=buddy_id,
        event_type="proposal_confirmed",
    )
    query = store.record_event(
        user_id=user_id,
        buddy_id=buddy_id,
        event_type="query_answered",
        answer_type="have_item",
    )
    _set_event_time(app, capture.event_id, base_time)
    _set_event_time(app, confirm.event_id, base_time + timedelta(minutes=1))
    _set_event_time(app, query.event_id, base_time + timedelta(minutes=2))


def _seed_maintenance_event(app, *, user_id: str, buddy_id: str, event_time: datetime) -> None:
    event = app.state.engagement_metrics_store.record_event(
        user_id=user_id,
        buddy_id=buddy_id,
        event_type="capture_submitted",
        capture_source="voice",
    )
    _set_event_time(app, event.event_id, event_time)


def _seed_unordered_events(app, *, user_id: str, buddy_id: str, base_time: datetime) -> None:
    store = app.state.engagement_metrics_store
    query = store.record_event(
        user_id=user_id,
        buddy_id=buddy_id,
        event_type="query_answered",
        answer_type="have_item",
    )
    capture = store.record_event(
        user_id=user_id,
        buddy_id=buddy_id,
        event_type="capture_submitted",
        capture_source="voice",
    )
    confirm = store.record_event(
        user_id=user_id,
        buddy_id=buddy_id,
        event_type="proposal_confirmed",
    )
    _set_event_time(app, query.event_id, base_time)
    _set_event_time(app, capture.event_id, base_time + timedelta(minutes=1))
    _set_event_time(app, confirm.event_id, base_time + timedelta(minutes=2))


def _set_event_time(app, event_id: str, event_time: datetime) -> None:
    app.state.db.execute(
        "UPDATE engagement_events SET created_at = ? WHERE event_id = ?",
        (event_time.isoformat(), event_id),
    )
    app.state.db.commit()
