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

        CREATE TABLE IF NOT EXISTS provider_configs (
            user_id TEXT NOT NULL,
            provider_id TEXT NOT NULL,
            display_name TEXT NOT NULL,
            provider_type TEXT NOT NULL CHECK (provider_type IN ('mock', 'openai_compatible')),
            base_url TEXT,
            api_key_env_var TEXT,
            default_model TEXT NOT NULL,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            PRIMARY KEY (user_id, provider_id),
            FOREIGN KEY (user_id) REFERENCES users(user_id)
        );

        CREATE INDEX IF NOT EXISTS idx_provider_configs_user_id
            ON provider_configs(user_id, provider_id);

        CREATE TABLE IF NOT EXISTS token_plan_assignments (
            user_id TEXT PRIMARY KEY,
            plan_id TEXT NOT NULL,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            FOREIGN KEY (user_id) REFERENCES users(user_id)
        );

        CREATE TABLE IF NOT EXISTS usage_ledger (
            usage_event_id TEXT PRIMARY KEY,
            user_id TEXT NOT NULL,
            trace_id TEXT,
            buddy_id TEXT,
            provider_id TEXT NOT NULL,
            model_id TEXT NOT NULL,
            input_tokens INTEGER NOT NULL CHECK (input_tokens >= 0),
            output_tokens INTEGER NOT NULL CHECK (output_tokens >= 0),
            total_tokens INTEGER NOT NULL CHECK (total_tokens >= 0),
            source TEXT NOT NULL,
            usage_month TEXT NOT NULL,
            created_at TEXT NOT NULL
        );

        CREATE INDEX IF NOT EXISTS idx_usage_ledger_user_month
            ON usage_ledger(user_id, usage_month, created_at);

        CREATE INDEX IF NOT EXISTS idx_usage_ledger_provider_model
            ON usage_ledger(user_id, usage_month, provider_id, model_id);

        CREATE TABLE IF NOT EXISTS agents (
            agent_id TEXT PRIMARY KEY,
            user_id TEXT NOT NULL,
            name TEXT NOT NULL,
            role TEXT NOT NULL CHECK (role IN (
                'runtime',
                'hardware_simulator',
                'cost_agent',
                'verifier',
                'doc_progress',
                'adapter'
            )),
            status TEXT NOT NULL CHECK (status IN (
                'starting',
                'online',
                'degraded',
                'offline',
                'error'
            )),
            version TEXT,
            metadata_json TEXT NOT NULL,
            capabilities_json TEXT NOT NULL,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            last_seen TEXT,
            FOREIGN KEY (user_id) REFERENCES users(user_id)
        );

        CREATE INDEX IF NOT EXISTS idx_agents_user_id
            ON agents(user_id, created_at);

        CREATE TABLE IF NOT EXISTS state_memory_items (
            item_id TEXT PRIMARY KEY,
            user_id TEXT NOT NULL,
            buddy_id TEXT NOT NULL,
            name TEXT NOT NULL,
            normalized_name TEXT NOT NULL,
            category TEXT,
            quantity REAL,
            unit TEXT,
            source TEXT NOT NULL CHECK (source IN (
                'voice',
                'photo',
                'scan',
                'conversation',
                'inference',
                'manual'
            )),
            confidence REAL,
            status TEXT NOT NULL CHECK (status IN ('active', 'consumed', 'removed')),
            captured_at TEXT NOT NULL,
            last_seen_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            FOREIGN KEY (user_id) REFERENCES users(user_id),
            FOREIGN KEY (buddy_id) REFERENCES buddies(buddy_id)
        );

        CREATE INDEX IF NOT EXISTS idx_state_memory_items_owner
            ON state_memory_items(user_id, buddy_id, normalized_name);

        CREATE TABLE IF NOT EXISTS state_memory_history (
            history_id TEXT PRIMARY KEY,
            item_id TEXT NOT NULL,
            user_id TEXT NOT NULL,
            buddy_id TEXT NOT NULL,
            item_name TEXT NOT NULL,
            change_type TEXT NOT NULL,
            change_source TEXT NOT NULL CHECK (change_source IN (
                'voice',
                'photo',
                'scan',
                'conversation',
                'inference',
                'manual'
            )),
            quantity_before REAL,
            quantity_after REAL,
            unit_before TEXT,
            unit_after TEXT,
            proposal_id TEXT,
            created_at TEXT NOT NULL,
            FOREIGN KEY (item_id) REFERENCES state_memory_items(item_id),
            FOREIGN KEY (user_id) REFERENCES users(user_id),
            FOREIGN KEY (buddy_id) REFERENCES buddies(buddy_id)
        );

        CREATE INDEX IF NOT EXISTS idx_state_memory_history_owner
            ON state_memory_history(user_id, buddy_id, created_at);

        CREATE TABLE IF NOT EXISTS state_memory_pending_proposals (
            proposal_id TEXT PRIMARY KEY,
            user_id TEXT NOT NULL,
            buddy_id TEXT NOT NULL,
            source TEXT NOT NULL CHECK (source IN (
                'voice',
                'photo',
                'scan',
                'conversation',
                'inference',
                'manual'
            )),
            content TEXT NOT NULL,
            deltas_json TEXT NOT NULL,
            status TEXT NOT NULL CHECK (status IN ('pending', 'confirmed', 'rejected')),
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            FOREIGN KEY (user_id) REFERENCES users(user_id),
            FOREIGN KEY (buddy_id) REFERENCES buddies(buddy_id)
        );

        CREATE INDEX IF NOT EXISTS idx_state_memory_pending_owner
            ON state_memory_pending_proposals(user_id, buddy_id, status, created_at);
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
