from fastapi.testclient import TestClient

from buddys_api.main import create_app


def test_register_login_me_and_logout_flow_hides_secret_hashes(tmp_path) -> None:
    client = TestClient(create_app(db_path=tmp_path / "buddys.sqlite3"))

    register_response = client.post(
        "/auth/register",
        json={"email": "Owner@Example.COM", "password": "correct horse battery staple", "display_name": "Owner"},
    )

    assert register_response.status_code == 201
    registered = register_response.json()
    assert registered["user"]["email"] == "owner@example.com"
    assert registered["user"]["display_name"] == "Owner"
    assert registered["access_token"]
    assert "password_hash" not in str(registered)
    assert "token_hash" not in str(registered)

    duplicate = client.post(
        "/auth/register",
        json={"email": "owner@example.com", "password": "correct horse battery staple"},
    )
    assert duplicate.status_code == 409
    assert duplicate.json() == {"detail": {"code": "email_already_registered"}}

    login_response = client.post(
        "/auth/login",
        json={"email": "owner@example.com", "password": "correct horse battery staple"},
    )
    assert login_response.status_code == 200
    token = login_response.json()["access_token"]

    me_response = client.get("/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert me_response.status_code == 200
    assert me_response.json()["email"] == "owner@example.com"

    logout_response = client.post("/auth/logout", headers={"Authorization": f"Bearer {token}"})
    assert logout_response.status_code == 204

    after_logout = client.get("/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert after_logout.status_code == 401
    assert after_logout.json() == {"detail": {"code": "invalid_or_expired_token"}}


def test_login_rejects_invalid_credentials_without_revealing_which_field_failed(tmp_path) -> None:
    client = TestClient(create_app(db_path=tmp_path / "buddys.sqlite3"))
    client.post("/auth/register", json={"email": "owner@example.com", "password": "correct horse battery staple"})

    wrong_password = client.post("/auth/login", json={"email": "owner@example.com", "password": "wrong password"})
    missing_user = client.post("/auth/login", json={"email": "missing@example.com", "password": "wrong password"})

    assert wrong_password.status_code == 401
    assert missing_user.status_code == 401
    assert wrong_password.json() == {"detail": {"code": "invalid_credentials"}}
    assert missing_user.json() == {"detail": {"code": "invalid_credentials"}}


def test_auth_buddy_routes_are_user_scoped(tmp_path) -> None:
    client = TestClient(create_app(db_path=tmp_path / "buddys.sqlite3"))
    owner_token = register(client, "owner@example.com")
    other_token = register(client, "other@example.com")

    create_response = client.post(
        "/me/buddies",
        headers={"Authorization": f"Bearer {owner_token}"},
        json={"name": "Kitchen Buddy", "space_id": "kitchen"},
    )
    assert create_response.status_code == 201
    created = create_response.json()
    assert created["name"] == "Kitchen Buddy"

    owner_list = client.get("/me/buddies", headers={"Authorization": f"Bearer {owner_token}"})
    assert owner_list.status_code == 200
    assert [buddy["buddy_id"] for buddy in owner_list.json()["buddies"]] == [created["buddy_id"]]

    owner_get = client.get(f"/me/buddies/{created['buddy_id']}", headers={"Authorization": f"Bearer {owner_token}"})
    assert owner_get.status_code == 200
    assert owner_get.json()["buddy_id"] == created["buddy_id"]

    other_list = client.get("/me/buddies", headers={"Authorization": f"Bearer {other_token}"})
    assert other_list.status_code == 200
    assert other_list.json() == {"buddies": []}

    cross_get = client.get(f"/me/buddies/{created['buddy_id']}", headers={"Authorization": f"Bearer {other_token}"})
    assert cross_get.status_code == 404
    assert cross_get.json() == {"detail": {"code": "buddy_not_found"}}


def test_auth_owned_buddies_are_hidden_from_legacy_unauthenticated_routes(tmp_path) -> None:
    client = TestClient(create_app(db_path=tmp_path / "buddys.sqlite3"))
    owner_token = register(client, "owner@example.com")

    create_response = client.post(
        "/me/buddies",
        headers={"Authorization": f"Bearer {owner_token}"},
        json={"name": "Private Buddy", "space_id": "study"},
    )
    assert create_response.status_code == 201
    created = create_response.json()

    legacy_get = client.get(f"/buddies/{created['buddy_id']}")
    legacy_message = client.post(
        f"/buddies/{created['buddy_id']}/messages",
        json={"user_id": created["user_id"], "message": "把客厅灯调暗"},
    )

    assert legacy_get.status_code == 404
    assert legacy_get.json() == {"detail": {"code": "buddy_not_found"}}
    assert legacy_message.status_code == 404
    assert legacy_message.json() == {"detail": {"code": "buddy_not_found"}}
    assert client.get("/cost-events").json() == {"cost_events": []}


def test_auth_required_for_me_routes(tmp_path) -> None:
    client = TestClient(create_app(db_path=tmp_path / "buddys.sqlite3"))

    response = client.get("/me/buddies")

    assert response.status_code == 401
    assert response.json() == {"detail": {"code": "missing_bearer_token"}}


def register(client: TestClient, email: str) -> str:
    response = client.post("/auth/register", json={"email": email, "password": "correct horse battery staple"})
    assert response.status_code == 201
    return response.json()["access_token"]
