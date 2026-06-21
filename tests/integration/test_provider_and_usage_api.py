from fastapi.testclient import TestClient
import pytest

from buddys_api.main import create_app


def test_plans_and_usage_require_auth_for_user_usage(tmp_path) -> None:
    client = TestClient(create_app(db_path=tmp_path / "buddys.sqlite3"))

    plans_response = client.get("/plans")
    unauth_usage = client.get("/usage")
    token = register(client, "owner@example.com")
    usage_response = client.get("/usage", headers={"Authorization": f"Bearer {token}"})

    assert plans_response.status_code == 200
    plans = plans_response.json()["plans"]
    assert {plan["plan_id"] for plan in plans}.issuperset({"free", "basic", "plus", "pro", "byok"})
    assert next(plan for plan in plans if plan["plan_id"] == "free")["monthly_token_limit"] > 0
    assert unauth_usage.status_code == 401
    assert usage_response.status_code == 200
    usage = usage_response.json()
    assert usage["user_id"].startswith("user_")
    assert usage["plan_id"] == "free"
    assert usage["used_tokens"] == 0
    assert usage["remaining_tokens"] == usage["monthly_token_limit"]


@pytest.mark.parametrize("secret_field", ["api_key", "apiKey", "token", "secret", "password", "private_key"])
def test_provider_create_rejects_raw_secret_like_fields(tmp_path, secret_field: str) -> None:
    client = TestClient(create_app(db_path=tmp_path / "buddys.sqlite3"))
    token = register(client, "owner@example.com")
    payload = valid_provider_payload() | {secret_field: "must-not-be-accepted"}

    response = client.post("/providers", headers={"Authorization": f"Bearer {token}"}, json=payload)

    assert response.status_code == 422
    assert response.json() == {"detail": {"code": "raw_secret_fields_rejected", "fields": [secret_field]}}


def test_provider_config_metadata_is_redacted_and_test_is_local_only(tmp_path, monkeypatch) -> None:
    client = TestClient(create_app(db_path=tmp_path / "buddys.sqlite3"))
    token = register(client, "owner@example.com")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-raw-value-should-never-leak")

    create_response = client.post(
        "/providers",
        headers={"Authorization": f"Bearer {token}"},
        json=valid_provider_payload(),
    )
    list_response = client.get("/providers", headers={"Authorization": f"Bearer {token}"})
    test_response = client.post(
        "/providers/minimax-openai/test",
        headers={"Authorization": f"Bearer {token}"},
    )

    assert create_response.status_code == 200
    assert list_response.status_code == 200
    assert test_response.status_code == 200
    assert create_response.json()["api_key_env_var"] == "OPENAI_API_KEY"
    assert test_response.json() == {
        "provider_id": "minimax-openai",
        "status": "configured",
        "api_key_env_var": "OPENAI_API_KEY",
        "external_network_called": False,
    }

    serialized = str([create_response.json(), list_response.json(), test_response.json()])
    assert "sk-raw-value-should-never-leak" not in serialized
    assert "api_key':" not in serialized
    assert "api_key\"" not in serialized
    assert "password" not in serialized.lower()
    assert "private_key" not in serialized.lower()


def test_system_managed_default_provider_does_not_appear_in_provider_listing(tmp_path, monkeypatch) -> None:
    client = TestClient(create_app(db_path=tmp_path / "buddys.sqlite3"))
    token = register(client, "owner@example.com")
    monkeypatch.setenv("BUDDYS_DEFAULT_OPENAI_API_KEY", "sk-system-default")
    monkeypatch.setenv("BUDDYS_DEFAULT_TOKEN_PLAN_KEY", "sk-cp-system-default")

    list_response = client.get("/providers", headers={"Authorization": f"Bearer {token}"})

    assert list_response.status_code == 200
    payload = list_response.json()
    assert payload["configs"] == []
    assert "BUDDYS_DEFAULT_OPENAI_API_KEY" not in str(payload)
    assert "BUDDYS_DEFAULT_TOKEN_PLAN_KEY" not in str(payload)
    assert "system-minimax-default" not in str(payload)


def test_provider_and_snapshot_surfaces_never_echo_default_or_runtime_secret_values(tmp_path, monkeypatch) -> None:
    secret_value = "sk-secret-should-never-leak"
    client = TestClient(create_app(db_path=tmp_path / "buddys.sqlite3"))
    token = register(client, "owner@example.com")
    monkeypatch.setenv("OPENAI_API_KEY", secret_value)
    monkeypatch.setenv("BUDDYS_DEFAULT_OPENAI_API_KEY", "sk-system-default")
    monkeypatch.setenv("BUDDYS_DEFAULT_TOKEN_PLAN_KEY", "sk-cp-system-default")

    create_response = client.post(
        "/providers",
        headers={"Authorization": f"Bearer {token}"},
        json=valid_provider_payload(),
    )
    providers_response = client.get("/providers", headers={"Authorization": f"Bearer {token}"})
    snapshot_response = client.get("/sync/snapshot", headers={"Authorization": f"Bearer {token}"})

    assert create_response.status_code == 200
    assert providers_response.status_code == 200
    assert snapshot_response.status_code == 200

    serialized = str([create_response.json(), providers_response.json(), snapshot_response.json()])
    assert secret_value not in serialized
    assert "BUDDYS_DEFAULT_OPENAI_API_KEY" not in serialized
    assert "BUDDYS_DEFAULT_TOKEN_PLAN_KEY" not in serialized
    assert "api_key':" not in serialized
    assert 'api_key"' not in serialized
    assert "secret" not in serialized.lower()
    assert "password" not in serialized.lower()


def test_provider_config_rejects_raw_key_in_env_var_field_without_echoing_it(tmp_path) -> None:
    client = TestClient(create_app(db_path=tmp_path / "buddys.sqlite3"))
    token = register(client, "owner@example.com")
    raw_key = "sk-raw-value-should-not-be-echoed"

    response = client.post(
        "/providers",
        headers={"Authorization": f"Bearer {token}"},
        json=valid_provider_payload() | {"api_key_env_var": raw_key},
    )

    assert response.status_code == 422
    assert response.json() == {"detail": {"code": "invalid_provider_config"}}
    assert raw_key not in str(response.json())


def test_provider_config_accepts_token_plan_env_var_for_real_provider(tmp_path) -> None:
    client = TestClient(create_app(db_path=tmp_path / "buddys.sqlite3"))
    token = register(client, "owner@example.com")

    response = client.post(
        "/providers",
        headers={"Authorization": f"Bearer {token}"},
        json=valid_provider_payload() | {"api_key_env_var": "MINIMAX_TOKEN_PLAN_KEY"},
    )

    assert response.status_code == 200
    assert response.json()["api_key_env_var"] == "MINIMAX_TOKEN_PLAN_KEY"


def test_provider_config_rejects_non_minimax_base_url_for_real_provider(tmp_path) -> None:
    client = TestClient(create_app(db_path=tmp_path / "buddys.sqlite3"))
    token = register(client, "owner@example.com")

    response = client.post(
        "/providers",
        headers={"Authorization": f"Bearer {token}"},
        json=valid_provider_payload() | {"base_url": "https://evil.example.com/v1"},
    )

    assert response.status_code == 422
    assert response.json() == {"detail": {"code": "invalid_provider_config"}}


def test_legacy_message_records_demo_usage_and_sync_snapshot_plan_usage_without_secret_leak(
    tmp_path,
    monkeypatch,
) -> None:
    client = TestClient(create_app(db_path=tmp_path / "buddys.sqlite3"))
    monkeypatch.setenv("OPENAI_API_KEY", "sk-sync-secret-value")
    buddy = client.post("/buddies", json={"user_id": "user_demo"}).json()

    message_response = client.post(
        f"/buddies/{buddy['buddy_id']}/messages",
        json={"user_id": "user_demo", "message": "把客厅灯调暗"},
    )
    usage_summary = client.app.state.usage_store.usage_summary("user_demo")
    snapshot_response = client.get("/sync/snapshot")

    assert message_response.status_code == 200
    assert usage_summary.used_tokens > 0
    snapshot = snapshot_response.json()
    assert snapshot["plan_usage"]["user_id"] == "user_demo"
    assert snapshot["plan_usage"]["used_tokens"] == usage_summary.used_tokens
    assert snapshot["plan_usage"]["remaining_tokens"] == usage_summary.remaining_tokens
    assert "sk-sync-secret-value" not in str(snapshot)
    assert "api_key" not in str(snapshot).lower()


def test_legacy_message_hard_limit_returns_safe_error_before_cost_or_usage_record(tmp_path) -> None:
    client = TestClient(create_app(db_path=tmp_path / "buddys.sqlite3"))
    buddy = client.post("/buddies", json={"user_id": "user_demo"}).json()
    usage_store = client.app.state.usage_store
    limit = usage_store.usage_summary("user_demo").monthly_token_limit
    assert limit is not None
    usage_store.record_usage(
        user_id="user_demo",
        trace_id="trace_at_limit",
        buddy_id=buddy["buddy_id"],
        provider_id="mock_deterministic",
        model_id="mock-home-v0",
        input_tokens=limit,
        output_tokens=0,
        source="test_seed",
    )

    response = client.post(
        f"/buddies/{buddy['buddy_id']}/messages",
        json={"user_id": "user_demo", "message": "把客厅灯调暗"},
    )

    assert response.status_code == 429
    assert response.json()["detail"]["code"] == "token_plan_limit_exceeded"
    assert usage_store.usage_summary("user_demo").used_tokens == limit
    assert client.get("/cost-events").json() == {"cost_events": []}


def valid_provider_payload() -> dict[str, str]:
    return {
        "provider_id": "minimax-openai",
        "display_name": "MiniMax OpenAI Compatible",
        "provider_type": "openai_compatible",
        "base_url": "https://api.minimaxi.com/v1",
        "api_key_env_var": "OPENAI_API_KEY",
        "default_model": "MiniMax-M3",
    }


def register(client: TestClient, email: str) -> str:
    response = client.post("/auth/register", json={"email": email, "password": "correct horse battery staple"})
    assert response.status_code == 201
    return response.json()["access_token"]
