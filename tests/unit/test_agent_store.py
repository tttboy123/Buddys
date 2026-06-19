from buddys_api.agent_models import AgentCreateRequest, AgentHeartbeatRequest
from buddys_api.agent_store import AgentNotFoundError, AgentStore
from buddys_api.auth_store import AuthStore
from buddys_api.db import connect_db, initialize_database

import pytest


def make_store() -> tuple[AgentStore, str, str]:
    connection = connect_db(":memory:")
    initialize_database(connection)
    auth_store = AuthStore(connection)
    owner = auth_store.register_user(email="owner@example.com", password="correct horse battery staple")
    other = auth_store.register_user(email="other@example.com", password="correct horse battery staple")
    return AgentStore(connection), owner.user_id, other.user_id


def test_create_agent_persists_only_safe_metadata_and_capabilities() -> None:
    store, owner_id, _ = make_store()

    agent = store.create_agent(
        user_id=owner_id,
        request=AgentCreateRequest(
            name="Home Runtime",
            role="runtime",
            status="starting",
            version="0.4.0",
            metadata={
                "space_id": "home",
                "raw_payload": {"debug": "not allowed"},
                "nested": {
                    "region": "local",
                    "api_key": "sk-should-not-store",
                    "private_key": "private-key-should-not-store",
                },
            },
            capabilities={
                "actions": ["message", "confirm"],
                "tool_args": {"token": "not allowed"},
                "nested": [{"name": "sync"}, {"public_key": "public-key-should-not-store"}],
            },
        ),
    )

    assert agent.agent_id.startswith("agent_")
    assert agent.user_id == owner_id
    assert agent.role == "runtime"
    assert agent.status == "starting"
    assert agent.metadata == {"space_id": "home", "nested": {"region": "local"}}
    assert agent.capabilities == {"actions": ["message", "confirm"], "nested": [{"name": "sync"}, {}]}

    stored = store.get_for_user(user_id=owner_id, agent_id=agent.agent_id)
    serialized = str(stored.model_dump(mode="json")).lower()
    row = store.connection.execute(
        "SELECT metadata_json, capabilities_json FROM agents WHERE agent_id = ?",
        (agent.agent_id,),
    ).fetchone()
    raw_stored_json = f"{row['metadata_json']} {row['capabilities_json']}".lower()
    for forbidden in ("raw_payload", "api_key", "private_key", "tool_args", "public_key", "sk-should-not-store"):
        assert forbidden not in serialized
        assert forbidden not in raw_stored_json


def test_create_agent_omits_secret_like_values_from_payloads_and_db_json() -> None:
    store, owner_id, _ = make_store()

    agent = store.create_agent(
        user_id=owner_id,
        request=AgentCreateRequest(
            name="Runtime Agent",
            role="runtime",
            metadata={
                "notes": "sk-safe-key-secret-sentinel",
                "debug_id": "sk-safe-key-sentinel-123456",
                "region": "local",
                "health": "ok",
                "enabled": True,
                "priority": 2,
                "nested": {
                    "label": "safe-label",
                    "debug": "contains raw_payload data",
                },
            },
            capabilities={
                "labels": [
                    "safe-label",
                    "sk-safe-key-secret-sentinel",
                    "sk-safe-key-sentinel-123456",
                    "token sentinel",
                ],
                "modes": ["sync", "confirm"],
                "flags": [True, 7],
                "nested": [{"name": "sync"}, {"value": "private_key sentinel"}],
            },
        ),
    )

    assert agent.metadata == {
        "region": "local",
        "health": "ok",
        "enabled": True,
        "priority": 2,
        "nested": {"label": "safe-label"},
    }
    assert agent.capabilities == {
        "labels": ["safe-label"],
        "modes": ["sync", "confirm"],
        "flags": [True, 7],
        "nested": [{"name": "sync"}, {}],
    }

    stored = store.get_for_user(user_id=owner_id, agent_id=agent.agent_id)
    row = store.connection.execute(
        "SELECT metadata_json, capabilities_json FROM agents WHERE agent_id = ?",
        (agent.agent_id,),
    ).fetchone()
    serialized = f"{stored.model_dump(mode='json')} {row['metadata_json']} {row['capabilities_json']}".lower()
    for forbidden in (
        "sk-safe-key-secret-sentinel",
        "sk-safe-key-sentinel-123456",
        "token sentinel",
        "raw_payload data",
        "private_key sentinel",
    ):
        assert forbidden not in serialized


def test_list_and_get_are_scoped_to_owner() -> None:
    store, owner_id, other_id = make_store()
    agent = store.create_agent(
        user_id=owner_id,
        request=AgentCreateRequest(name="Verifier", role="verifier"),
    )

    assert [item.agent_id for item in store.list_for_user(owner_id)] == [agent.agent_id]
    assert store.list_for_user(other_id) == []

    with pytest.raises(AgentNotFoundError):
        store.get_for_user(user_id=other_id, agent_id=agent.agent_id)


def test_heartbeat_updates_status_last_seen_version_and_safe_capabilities() -> None:
    store, owner_id, other_id = make_store()
    agent = store.create_agent(
        user_id=owner_id,
        request=AgentCreateRequest(name="Cost Agent", role="cost_agent"),
    )

    updated = store.heartbeat(
        user_id=owner_id,
        agent_id=agent.agent_id,
        request=AgentHeartbeatRequest(
            status="online",
            version="0.4.1",
            capabilities={
                "jobs": ["usage_rollup"],
                "credentials": {"token": "not allowed"},
                "raw_payload": {"password": "not allowed"},
            },
        ),
    )

    assert updated.status == "online"
    assert updated.version == "0.4.1"
    assert updated.last_seen is not None
    assert updated.updated_at >= agent.updated_at
    assert updated.capabilities == {"jobs": ["usage_rollup"], "credentials": {}}

    with pytest.raises(AgentNotFoundError):
        store.heartbeat(
            user_id=other_id,
            agent_id=agent.agent_id,
            request=AgentHeartbeatRequest(status="offline"),
        )
