from __future__ import annotations

import hashlib
import secrets
import sqlite3

from buddys_api.auth_models import AuthResult, SessionPublic, UserPublic
from buddys_api.schemas import new_id, now_iso


PASSWORD_ITERATIONS = 200_000
PASSWORD_ALGORITHM = "pbkdf2_sha256"


class DuplicateEmailError(ValueError):
    pass


class InvalidCredentialsError(ValueError):
    pass


class AuthStore:
    def __init__(self, connection: sqlite3.Connection) -> None:
        self.connection = connection

    def register_user(self, email: str, password: str, display_name: str | None = None) -> UserPublic:
        normalized_email = _normalize_email(email)
        user = UserPublic(
            user_id=new_id("user"),
            email=normalized_email,
            display_name=display_name,
            created_at=now_iso(),
        )
        try:
            with self.connection:
                self.connection.execute(
                    """
                    INSERT INTO users (user_id, email, display_name, password_hash, created_at)
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    (
                        user.user_id,
                        user.email,
                        user.display_name,
                        hash_password(password),
                        user.created_at,
                    ),
                )
        except sqlite3.IntegrityError as exc:
            raise DuplicateEmailError(f"email already registered: {normalized_email}") from exc
        return user

    def login(self, email: str, password: str) -> AuthResult:
        row = self.connection.execute(
            "SELECT user_id, email, display_name, password_hash, created_at FROM users WHERE email = ?",
            (_normalize_email(email),),
        ).fetchone()
        if row is None or not verify_password(password, row["password_hash"]):
            raise InvalidCredentialsError("invalid credentials")
        user = _user_from_row(row)
        return self.issue_session(user)

    def issue_session(self, user: UserPublic) -> AuthResult:
        access_token = secrets.token_urlsafe(32)
        session = SessionPublic(session_id=new_id("sess"), user_id=user.user_id, created_at=now_iso())
        with self.connection:
            self.connection.execute(
                """
                INSERT INTO sessions (session_id, user_id, token_hash, created_at, revoked_at)
                VALUES (?, ?, ?, ?, NULL)
                """,
                (session.session_id, session.user_id, hash_session_token(access_token), session.created_at),
            )
        return AuthResult(user=user, session=session, access_token=access_token)

    def authenticate_token(self, access_token: str) -> UserPublic | None:
        token_hash = hash_session_token(access_token)
        rows = self.connection.execute(
            """
            SELECT sessions.session_id, sessions.token_hash, users.user_id, users.email, users.display_name, users.created_at
            FROM sessions
            JOIN users ON users.user_id = sessions.user_id
            WHERE sessions.revoked_at IS NULL
            ORDER BY sessions.created_at DESC
            """
        ).fetchall()
        for row in rows:
            if secrets.compare_digest(token_hash, row["token_hash"]):
                return _user_from_row(row)
        return None

    def logout(self, access_token: str) -> bool:
        token_hash = hash_session_token(access_token)
        rows = self.connection.execute(
            "SELECT session_id, token_hash FROM sessions WHERE revoked_at IS NULL"
        ).fetchall()
        for row in rows:
            if secrets.compare_digest(token_hash, row["token_hash"]):
                with self.connection:
                    self.connection.execute(
                        "UPDATE sessions SET revoked_at = ? WHERE session_id = ?",
                        (now_iso(), row["session_id"]),
                    )
                return True
        return False


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, PASSWORD_ITERATIONS)
    return f"{PASSWORD_ALGORITHM}${PASSWORD_ITERATIONS}${salt.hex()}${digest.hex()}"


def verify_password(password: str, stored_hash: str) -> bool:
    try:
        algorithm, iterations_text, salt_hex, digest_hex = stored_hash.split("$", 3)
        if algorithm != PASSWORD_ALGORITHM:
            return False
        salt = bytes.fromhex(salt_hex)
        expected = bytes.fromhex(digest_hex)
        iterations = int(iterations_text)
    except (ValueError, TypeError):
        return False

    actual = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iterations)
    return secrets.compare_digest(actual, expected)


def hash_session_token(access_token: str) -> str:
    return hashlib.sha256(access_token.encode("utf-8")).hexdigest()


def _normalize_email(email: str) -> str:
    return email.strip().lower()


def _user_from_row(row: sqlite3.Row) -> UserPublic:
    return UserPublic(
        user_id=row["user_id"],
        email=row["email"],
        display_name=row["display_name"],
        created_at=row["created_at"],
    )
