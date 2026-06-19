from __future__ import annotations

import json
import re
import sqlite3
from typing import Any

from buddys_api.agent_models import AgentCreateRequest, AgentHeartbeatRequest, AgentRecord
from buddys_api.schemas import new_id, now_iso


DENIED_AGENT_KEY_PARTS = (
    "secret",
    "token",
    "api_key",
    "apikey",
    "password",
    "public_key",
    "publickey",
    "private_key",
    "privatekey",
    "raw_payload",
    "rawpayload",
    "action_args",
    "actionargs",
    "tool_args",
    "toolargs",
)

_REDACTED = object()


class AgentNotFoundError(KeyError):
    pass


class AgentStore:
    def __init__(self, connection: sqlite3.Connection) -> None:
        self.connection = connection

    def create_agent(self, user_id: str, request: AgentCreateRequest) -> AgentRecord:
        created_at = now_iso()
        agent = AgentRecord(
            agent_id=new_id("agent"),
            user_id=user_id,
            name=request.name,
            role=request.role,
            status=request.status,
            version=request.version,
            metadata=sanitize_agent_payload(request.metadata),
            capabilities=sanitize_agent_payload(request.capabilities),
            created_at=created_at,
            updated_at=created_at,
            last_seen=None,
        )
        with self.connection:
            self.connection.execute(
                """
                INSERT INTO agents (
                    agent_id, user_id, name, role, status, version,
                    metadata_json, capabilities_json, created_at, updated_at, last_seen
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    agent.agent_id,
                    agent.user_id,
                    agent.name,
                    agent.role,
                    agent.status,
                    agent.version,
                    _dump_json(agent.metadata),
                    _dump_json(agent.capabilities),
                    agent.created_at,
                    agent.updated_at,
                    agent.last_seen,
                ),
            )
        return agent

    def list_for_user(self, user_id: str) -> list[AgentRecord]:
        rows = self.connection.execute(
            """
            SELECT agent_id, user_id, name, role, status, version, metadata_json,
                   capabilities_json, created_at, updated_at, last_seen
            FROM agents
            WHERE user_id = ?
            ORDER BY created_at, agent_id
            """,
            (user_id,),
        ).fetchall()
        return [_agent_from_row(row) for row in rows]

    def get_for_user(self, user_id: str, agent_id: str) -> AgentRecord:
        row = self.connection.execute(
            """
            SELECT agent_id, user_id, name, role, status, version, metadata_json,
                   capabilities_json, created_at, updated_at, last_seen
            FROM agents
            WHERE user_id = ? AND agent_id = ?
            """,
            (user_id, agent_id),
        ).fetchone()
        if row is None:
            raise AgentNotFoundError(agent_id)
        return _agent_from_row(row)

    def heartbeat(self, user_id: str, agent_id: str, request: AgentHeartbeatRequest) -> AgentRecord:
        existing = self.get_for_user(user_id=user_id, agent_id=agent_id)
        updated_at = now_iso()
        last_seen = updated_at
        version = request.version if request.version is not None else existing.version
        capabilities = (
            sanitize_agent_payload(request.capabilities)
            if request.capabilities is not None
            else existing.capabilities
        )
        with self.connection:
            self.connection.execute(
                """
                UPDATE agents
                SET status = ?, version = ?, capabilities_json = ?, updated_at = ?, last_seen = ?
                WHERE user_id = ? AND agent_id = ?
                """,
                (
                    request.status,
                    version,
                    _dump_json(capabilities),
                    updated_at,
                    last_seen,
                    user_id,
                    agent_id,
                ),
            )
        return self.get_for_user(user_id=user_id, agent_id=agent_id)


def sanitize_agent_payload(value: dict[str, Any]) -> dict[str, Any]:
    return _sanitize_dict(value)


def is_denied_agent_key(key: Any) -> bool:
    normalized = _normalize_key(key)
    return any(_normalize_key(denied) in normalized for denied in DENIED_AGENT_KEY_PARTS)


def _sanitize_dict(value: dict[str, Any]) -> dict[str, Any]:
    sanitized: dict[str, Any] = {}
    for key, nested_value in value.items():
        if is_denied_agent_key(key):
            continue
        sanitized_value = _sanitize_value(nested_value)
        if sanitized_value is _REDACTED:
            continue
        sanitized[key] = sanitized_value
    return sanitized


def _sanitize_value(value: Any) -> Any:
    if isinstance(value, dict):
        return _sanitize_dict(value)
    if isinstance(value, list):
        sanitized_items = [_sanitize_value(item) for item in value]
        return [item for item in sanitized_items if item is not _REDACTED]
    if isinstance(value, str):
        if _is_denied_agent_value(value):
            return _REDACTED
        return value
    if isinstance(value, int | float | bool) or value is None:
        return value
    stringified = str(value)
    if _is_denied_agent_value(stringified):
        return _REDACTED
    return stringified


def _is_denied_agent_value(value: str) -> bool:
    return _contains_denied_agent_term(value) or _looks_like_key_sentinel(value)


def _contains_denied_agent_term(value: Any) -> bool:
    normalized = _normalize_key(value)
    return any(_normalize_key(denied) in normalized for denied in DENIED_AGENT_KEY_PARTS)


def _looks_like_key_sentinel(value: str) -> bool:
    stripped = value.strip()
    if not stripped:
        return False
    lower = stripped.lower()
    return bool(
        re.match(r"^sk[-_][a-z0-9][a-z0-9_-]{6,}$", lower)
        or re.match(r"^gh[pousr]_[a-z0-9_]{20,}$", lower)
        or re.match(r"^xox[baprs]-[a-z0-9-]{10,}$", lower)
        or re.match(r"^aiza[a-z0-9_-]{20,}$", lower)
        or lower.startswith("bearer ")
        or (lower.startswith("-----begin ") and " key-----" in lower)
    )


def _agent_from_row(row: sqlite3.Row) -> AgentRecord:
    return AgentRecord(
        agent_id=row["agent_id"],
        user_id=row["user_id"],
        name=row["name"],
        role=row["role"],
        status=row["status"],
        version=row["version"],
        metadata=json.loads(row["metadata_json"]),
        capabilities=json.loads(row["capabilities_json"]),
        created_at=row["created_at"],
        updated_at=row["updated_at"],
        last_seen=row["last_seen"],
    )


def _dump_json(value: dict[str, Any]) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


def _normalize_key(value: Any) -> str:
    return re.sub(r"[^a-z0-9]+", "", str(value).lower())
