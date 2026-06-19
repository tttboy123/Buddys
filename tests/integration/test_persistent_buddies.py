import sqlite3

from fastapi.testclient import TestClient

from buddys_api.main import create_app


def test_users_sessions_and_buddies_persist_across_app_instances(tmp_path) -> None:
    db_path = tmp_path / "buddys.sqlite3"
    first_client = TestClient(create_app(db_path=db_path))

    register_response = first_client.post(
        "/auth/register",
        json={"email": "owner@example.com", "password": "correct horse battery staple"},
    )
    assert register_response.status_code == 201
    token = register_response.json()["access_token"]

    create_response = first_client.post(
        "/me/buddies",
        headers={"Authorization": f"Bearer {token}"},
        json={"name": "Studio Buddy", "space_id": "studio"},
    )
    assert create_response.status_code == 201
    buddy_id = create_response.json()["buddy_id"]

    second_client = TestClient(create_app(db_path=db_path))

    me_response = second_client.get("/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert me_response.status_code == 200
    assert me_response.json()["email"] == "owner@example.com"

    list_response = second_client.get("/me/buddies", headers={"Authorization": f"Bearer {token}"})
    assert list_response.status_code == 200
    assert [buddy["buddy_id"] for buddy in list_response.json()["buddies"]] == [buddy_id]

    get_response = second_client.get(f"/me/buddies/{buddy_id}", headers={"Authorization": f"Bearer {token}"})
    assert get_response.status_code == 200
    assert get_response.json()["name"] == "Studio Buddy"


def test_legacy_buddy_endpoint_works_with_sqlite_backing(tmp_path) -> None:
    db_path = tmp_path / "buddys.sqlite3"
    first_client = TestClient(create_app(db_path=db_path))

    create_response = first_client.post("/buddies", json={"user_id": "legacy_user"})
    assert create_response.status_code == 201
    created = create_response.json()

    second_client = TestClient(create_app(db_path=db_path))
    get_response = second_client.get(f"/buddies/{created['buddy_id']}")

    assert get_response.status_code == 200
    assert get_response.json() == created


def test_buddy_origin_migration_preserves_old_legacy_rows_without_exposing_auth_rows(tmp_path) -> None:
    db_path = tmp_path / "old_buddys.sqlite3"
    connection = sqlite3.connect(db_path)
    connection.executescript(
        """
        CREATE TABLE users (
            user_id TEXT PRIMARY KEY,
            email TEXT NOT NULL UNIQUE,
            display_name TEXT,
            password_hash TEXT NOT NULL,
            created_at TEXT NOT NULL
        );

        CREATE TABLE buddies (
            buddy_id TEXT PRIMARY KEY,
            user_id TEXT NOT NULL,
            name TEXT NOT NULL,
            space_id TEXT NOT NULL,
            device_id TEXT,
            autonomy_level TEXT NOT NULL,
            status TEXT NOT NULL,
            created_at TEXT NOT NULL
        );
        """
    )
    connection.execute(
        """
        INSERT INTO users (user_id, email, display_name, password_hash, created_at)
        VALUES (?, ?, ?, ?, ?)
        """,
        ("user_auth_001", "owner@example.com", None, "pbkdf2_sha256$placeholder", "2026-06-19T00:00:00Z"),
    )
    connection.executemany(
        """
        INSERT INTO buddies (buddy_id, user_id, name, space_id, device_id, autonomy_level, status, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        [
            (
                "buddy_legacy_001",
                "legacy_user",
                "Home Buddy",
                "home",
                None,
                "A",
                "idle",
                "2026-06-19T00:00:00Z",
            ),
            (
                "buddy_auth_001",
                "user_auth_001",
                "Private Buddy",
                "study",
                None,
                "A",
                "idle",
                "2026-06-19T00:00:01Z",
            ),
        ],
    )
    connection.commit()
    connection.close()

    client = TestClient(create_app(db_path=db_path))

    legacy_get = client.get("/buddies/buddy_legacy_001")
    auth_get = client.get("/buddies/buddy_auth_001")

    assert legacy_get.status_code == 200
    assert legacy_get.json()["buddy_id"] == "buddy_legacy_001"
    assert auth_get.status_code == 404
    assert auth_get.json() == {"detail": {"code": "buddy_not_found"}}
