import sqlite3
from types import SimpleNamespace

import pytest

from buddys_api.auth_store import AuthStore, DuplicateEmailError, InvalidCredentialsError
from buddys_api.db import connect_db, initialize_database


def make_store() -> AuthStore:
    connection = connect_db(":memory:")
    initialize_database(connection)
    return AuthStore(connection)


def test_register_user_hashes_password_and_rejects_duplicate_email() -> None:
    store = make_store()

    user = store.register_user(email="Owner@Example.COM", password="correct horse battery staple", display_name="Owner")

    assert user.user_id.startswith("user_")
    assert user.email == "owner@example.com"
    assert user.display_name == "Owner"

    stored = store.connection.execute("SELECT password_hash FROM users WHERE user_id = ?", (user.user_id,)).fetchone()
    assert stored is not None
    assert "correct horse battery staple" not in stored["password_hash"]
    assert stored["password_hash"].startswith("pbkdf2_sha256$")

    with pytest.raises(DuplicateEmailError):
        store.register_user(email="owner@example.com", password="another password")


def test_login_verifies_password_and_returns_session_without_raw_hashes() -> None:
    store = make_store()
    user = store.register_user(email="owner@example.com", password="correct horse battery staple")

    login = store.login(email="OWNER@example.com", password="correct horse battery staple")

    assert login.user == user
    assert login.access_token
    assert login.session.session_id.startswith("sess_")
    assert not hasattr(login, "password_hash")
    assert not hasattr(login.session, "session_token_hash")

    session_row = store.connection.execute(
        "SELECT token_hash FROM sessions WHERE session_id = ?",
        (login.session.session_id,),
    ).fetchone()
    assert session_row is not None
    assert login.access_token not in session_row["token_hash"]

    with pytest.raises(InvalidCredentialsError):
        store.login(email="owner@example.com", password="wrong password")


def test_authenticate_token_and_logout_revokes_session() -> None:
    store = make_store()
    store.register_user(email="owner@example.com", password="correct horse battery staple")
    login = store.login(email="owner@example.com", password="correct horse battery staple")

    assert store.authenticate_token(login.access_token).email == "owner@example.com"

    store.logout(login.access_token)

    assert store.authenticate_token(login.access_token) is None


def test_authenticate_token_and_logout_ignore_null_token_hash_rows() -> None:
    store = make_store()
    store.connection = SimpleNamespace(
        execute=lambda *_args, **_kwargs: SimpleNamespace(
            fetchall=lambda: [
                {
                    "session_id": "sess_legacy_null_hash",
                    "token_hash": None,
                    "user_id": "user_legacy",
                    "email": "legacy@example.com",
                    "display_name": None,
                    "created_at": "2026-06-22T00:00:00+00:00",
                }
            ]
        )
    )

    assert store.authenticate_token("stale-browser-token") is None
    assert store.logout("stale-browser-token") is False


def test_database_file_persists_users_and_sessions(tmp_path) -> None:
    db_path = tmp_path / "buddys.sqlite3"
    first_connection = connect_db(db_path)
    initialize_database(first_connection)
    first_store = AuthStore(first_connection)
    user = first_store.register_user(email="owner@example.com", password="correct horse battery staple")
    login = first_store.login(email="owner@example.com", password="correct horse battery staple")
    first_connection.close()

    second_connection = connect_db(db_path)
    initialize_database(second_connection)
    second_store = AuthStore(second_connection)

    assert second_store.authenticate_token(login.access_token).user_id == user.user_id

    second_connection.close()


def test_register_rolls_back_cleanly_on_duplicate_email() -> None:
    store = make_store()
    store.register_user(email="owner@example.com", password="correct horse battery staple")

    with pytest.raises(DuplicateEmailError):
        store.register_user(email="owner@example.com", password="correct horse battery staple")

    count = store.connection.execute("SELECT COUNT(*) AS count FROM users").fetchone()["count"]
    assert count == 1


def test_connect_db_uses_row_objects() -> None:
    connection = connect_db(":memory:")
    assert connection.row_factory is sqlite3.Row
    connection.close()
