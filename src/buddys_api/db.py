from __future__ import annotations

import sqlite3
from pathlib import Path


DbPath = str | Path


def connect_db(path: DbPath) -> sqlite3.Connection:
    connection = sqlite3.connect(path, check_same_thread=False)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    return connection


def initialize_database(connection: sqlite3.Connection) -> None:
    connection.executescript(
        """
        CREATE TABLE IF NOT EXISTS users (
            user_id TEXT PRIMARY KEY,
            email TEXT NOT NULL UNIQUE,
            display_name TEXT,
            password_hash TEXT NOT NULL,
            created_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS sessions (
            session_id TEXT PRIMARY KEY,
            user_id TEXT NOT NULL,
            token_hash TEXT NOT NULL,
            created_at TEXT NOT NULL,
            revoked_at TEXT,
            FOREIGN KEY (user_id) REFERENCES users(user_id)
        );

        CREATE INDEX IF NOT EXISTS idx_sessions_active
            ON sessions(revoked_at, created_at);

        CREATE TABLE IF NOT EXISTS buddies (
            buddy_id TEXT PRIMARY KEY,
            user_id TEXT NOT NULL,
            name TEXT NOT NULL,
            space_id TEXT NOT NULL,
            device_id TEXT,
            autonomy_level TEXT NOT NULL,
            status TEXT NOT NULL,
            created_at TEXT NOT NULL,
            created_via TEXT NOT NULL DEFAULT 'auth'
        );

        CREATE INDEX IF NOT EXISTS idx_buddies_user_id
            ON buddies(user_id, created_at);

        CREATE TABLE IF NOT EXISTS sync_events (
            revision INTEGER PRIMARY KEY AUTOINCREMENT,
            event_id TEXT NOT NULL UNIQUE,
            event_type TEXT NOT NULL,
            entity_type TEXT NOT NULL,
            entity_id TEXT NOT NULL,
            actor_user_id TEXT,
            visibility TEXT NOT NULL CHECK (visibility IN ('legacy', 'auth')),
            payload_summary TEXT NOT NULL,
            created_at TEXT NOT NULL
        );

        CREATE INDEX IF NOT EXISTS idx_sync_events_revision
            ON sync_events(revision);

        CREATE INDEX IF NOT EXISTS idx_sync_events_visibility_revision
            ON sync_events(visibility, actor_user_id, revision);
        """
    )
    buddy_columns = {
        row["name"] for row in connection.execute("PRAGMA table_info(buddies)").fetchall()
    }
    if "created_via" not in buddy_columns:
        connection.execute("ALTER TABLE buddies ADD COLUMN created_via TEXT NOT NULL DEFAULT 'auth'")
        connection.execute(
            """
            UPDATE buddies
            SET created_via = 'legacy'
            WHERE user_id NOT IN (SELECT user_id FROM users)
            """
        )
    connection.commit()
