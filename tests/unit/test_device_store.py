import json

from buddys_api.device_models import (
    AgentMachine,
    BuddyRuntimeBinding,
    Device,
    DeviceDesiredState,
    DeviceEvent,
    DeviceHeartbeat,
)
from buddys_api.db import connect_db, initialize_database
from buddys_api.device_store import DeviceRegistry, DuplicatePairingError


def test_device_registry_saves_and_reads_device_agent_machine_and_binding() -> None:
    store = DeviceRegistry()
    device = Device(
        device_id="device_body_001",
        buddy_id="buddy_home_001",
        space_id="space_home",
        public_key="device-public-key",
        pairing_state="paired",
        firmware_version="0.1.0",
    )
    machine = AgentMachine(
        agent_machine_id="agent_machine_home_mac",
        owner_user_id="user_demo",
        machine_type="local_mac",
        endpoint="https://agent-machine.example.test",
        public_key="agent-machine-public-key",
        runtime_version="0.1.0",
        status="online",
    )
    binding = BuddyRuntimeBinding(
        buddy_id="buddy_home_001",
        agent_machine_id="agent_machine_home_mac",
        role="primary",
        authority_epoch=1,
        state_revision=0,
    )

    store.save_device(device)
    store.save_agent_machine(machine)
    store.save_binding(binding)

    assert store.get_device("device_body_001") == device
    assert store.get_agent_machine("agent_machine_home_mac") == machine
    assert store.get_binding("buddy_home_001").agent_machine_id == "agent_machine_home_mac"


def test_device_registry_tracks_latest_heartbeat_and_manual_required_desired_state() -> None:
    store = DeviceRegistry()
    heartbeat = DeviceHeartbeat(
        device_id="device_body_001",
        firmware_version="0.1.0",
        wifi_rssi=-62,
        uptime_seconds=180,
        current_state="thinking",
        idempotency_key="hb-001",
    )
    desired_state = DeviceDesiredState(
        device_id="device_body_001",
        state="manual_required",
        revision=4,
        display_text="请手动把客厅灯调暗到约 35%。",
        manual_required=True,
        user_instruction="请手动把客厅灯调暗到约 35%。",
        source_trace_id="trace_001",
    )

    store.save_heartbeat(heartbeat)
    store.set_desired_state(desired_state)

    assert store.get_latest_heartbeat("device_body_001") == heartbeat
    assert store.get_desired_state("device_body_001").manual_required is True
    assert store.get_desired_state("device_body_001").state == "manual_required"


def test_device_registry_appends_device_events_without_overwriting_history() -> None:
    store = DeviceRegistry()
    first = DeviceEvent(
        device_id="device_body_001",
        event_type="approve",
        idempotency_key="event-approve-001",
    )
    second = DeviceEvent(
        device_id="device_body_001",
        event_type="manual_done",
        idempotency_key="event-manual-done-001",
    )

    store.append_event(first)
    store.append_event(second)

    events = store.list_events("device_body_001")
    assert [event.event_type for event in events] == ["approve", "manual_done"]
    assert store.list_events("other_device") == []


def test_device_registry_deduplicates_events_by_device_and_idempotency_key() -> None:
    store = DeviceRegistry()
    first = DeviceEvent(
        device_id="device_body_001",
        event_type="approve",
        idempotency_key="event-approve-001",
        payload={"source": "button"},
    )
    duplicate = DeviceEvent(
        device_id="device_body_001",
        event_type="approve",
        idempotency_key="event-approve-001",
        payload={"source": "touch"},
    )

    saved_first = store.append_event(first)
    saved_duplicate = store.append_event(duplicate)

    assert saved_duplicate == saved_first
    assert len(store.list_events("device_body_001")) == 1
    assert store.list_events("device_body_001")[0].payload == {"source": "button"}


def test_device_registry_deduplicates_latest_heartbeat_by_device_and_idempotency_key() -> None:
    store = DeviceRegistry()
    first = DeviceHeartbeat(
        device_id="device_body_001",
        firmware_version="0.1.0",
        wifi_rssi=-62,
        uptime_seconds=180,
        current_state="thinking",
        idempotency_key="hb-001",
    )
    duplicate = DeviceHeartbeat(
        device_id="device_body_001",
        firmware_version="0.1.0",
        wifi_rssi=-10,
        uptime_seconds=999,
        current_state="error",
        idempotency_key="hb-001",
    )

    saved_first = store.save_heartbeat(first)
    saved_duplicate = store.save_heartbeat(duplicate)

    assert saved_duplicate == saved_first
    assert store.get_latest_heartbeat("device_body_001").wifi_rssi == -62


def test_device_registry_requires_matching_pairing_token_for_device_auth() -> None:
    store = DeviceRegistry()
    device = Device(
        device_id="device_body_001",
        buddy_id="buddy_home_001",
        space_id="space_home",
        public_key="device-public-key",
        pairing_state="paired",
        firmware_version="0.1.0",
    )
    machine = AgentMachine(
        agent_machine_id="agent_machine_home_mac",
        owner_user_id="user_demo",
        machine_type="local_mac",
        endpoint="https://agent-machine.example.test",
        public_key="agent-machine-public-key",
        runtime_version="0.1.0",
        status="online",
    )
    binding = BuddyRuntimeBinding(
        buddy_id="buddy_home_001",
        agent_machine_id="agent_machine_home_mac",
        role="primary",
        authority_epoch=1,
        state_revision=0,
    )

    pairing = store.pair_device(
        device=device,
        agent_machine=machine,
        binding=binding,
        pairing_token="pair-token-001",
        idempotency_key="pair-001",
    )

    assert store.require_device_pairing_token("device_body_001", "pair-token-001") == pairing

    try:
        store.require_device_pairing_token("device_body_001", "wrong-token")
    except KeyError:
        pass
    else:
        raise AssertionError("expected wrong pairing token to fail")

    try:
        store.require_device_pairing_token("other-device", "pair-token-001")
    except KeyError:
        pass
    else:
        raise AssertionError("expected mismatched device pairing token to fail")


def test_device_registry_repair_invalidates_older_pairing_token_for_same_device() -> None:
    store = DeviceRegistry()
    device = Device(
        device_id="device_body_001",
        buddy_id="buddy_home_001",
        space_id="space_home",
        public_key="device-public-key",
        pairing_state="paired",
        firmware_version="0.1.0",
    )
    machine = AgentMachine(
        agent_machine_id="agent_machine_home_mac",
        owner_user_id="user_demo",
        machine_type="local_mac",
        endpoint="https://agent-machine.example.test",
        public_key="agent-machine-public-key",
        runtime_version="0.1.0",
        status="online",
    )
    binding = BuddyRuntimeBinding(
        buddy_id="buddy_home_001",
        agent_machine_id="agent_machine_home_mac",
        role="primary",
        authority_epoch=1,
        state_revision=0,
    )

    store.pair_device(
        device=device,
        agent_machine=machine,
        binding=binding,
        pairing_token="pair-token-old",
        idempotency_key="pair-001",
    )
    rotated = store.pair_device(
        device=device.model_copy(update={"firmware_version": "0.2.0"}),
        agent_machine=machine.model_copy(update={"runtime_version": "0.2.0"}),
        binding=binding,
        pairing_token="pair-token-new",
        idempotency_key="pair-002",
    )

    try:
        store.require_device_pairing_token("device_body_001", "pair-token-old")
    except KeyError:
        pass
    else:
        raise AssertionError("expected old pairing token to be invalidated after re-pair")

    assert store.require_device_pairing_token("device_body_001", "pair-token-new") == rotated


def test_device_registry_repair_tombstones_older_pairing_token_for_future_pair_attempts() -> None:
    store = DeviceRegistry()
    machine = AgentMachine(
        agent_machine_id="agent_machine_home_mac",
        owner_user_id="user_demo",
        machine_type="local_mac",
        endpoint="https://agent-machine.example.test",
        public_key="agent-machine-public-key",
        runtime_version="0.1.0",
        status="online",
    )
    binding = BuddyRuntimeBinding(
        buddy_id="buddy_home_001",
        agent_machine_id="agent_machine_home_mac",
        role="primary",
        authority_epoch=1,
        state_revision=0,
    )
    store.pair_device(
        device=Device(
            device_id="device_body_001",
            buddy_id="buddy_home_001",
            space_id="space_home",
            public_key="device-public-key",
            pairing_state="paired",
            firmware_version="0.1.0",
        ),
        agent_machine=machine,
        binding=binding,
        pairing_token="pair-token-old",
        idempotency_key="pair-001",
    )
    store.pair_device(
        device=Device(
            device_id="device_body_001",
            buddy_id="buddy_home_001",
            space_id="space_home",
            public_key="device-public-key",
            pairing_state="paired",
            firmware_version="0.2.0",
        ),
        agent_machine=machine.model_copy(update={"runtime_version": "0.2.0"}),
        binding=binding,
        pairing_token="pair-token-new",
        idempotency_key="pair-002",
    )

    try:
        store.pair_device(
            device=Device(
                device_id="device_body_002",
                buddy_id="buddy_home_002",
                space_id="space_home",
                public_key="device-public-key-2",
                pairing_state="paired",
                firmware_version="0.2.0",
            ),
            agent_machine=machine.model_copy(update={"agent_machine_id": "agent_machine_home_mac_2"}),
            binding=binding.model_copy(update={"buddy_id": "buddy_home_002", "agent_machine_id": "agent_machine_home_mac_2"}),
            pairing_token="pair-token-old",
            idempotency_key="pair-003",
        )
    except DuplicatePairingError:
        pass
    else:
        raise AssertionError("expected revoked pairing token to remain unusable for future pair attempts")


def test_sqlite_backed_device_registry_persists_pair_auth_across_reinstantiation(tmp_path) -> None:
    db_path = tmp_path / "buddys.sqlite3"
    connection = connect_db(db_path)
    initialize_database(connection)
    store = DeviceRegistry(connection)
    device = Device(
        device_id="device_body_001",
        buddy_id="buddy_home_001",
        space_id="space_home",
        public_key="device-public-key",
        pairing_state="paired",
        firmware_version="0.1.0",
    )
    machine = AgentMachine(
        agent_machine_id="agent_machine_home_mac",
        owner_user_id="user_demo",
        machine_type="local_mac",
        endpoint="https://agent-machine.example.test",
        public_key="agent-machine-public-key",
        runtime_version="0.1.0",
        status="online",
    )
    binding = BuddyRuntimeBinding(
        buddy_id="buddy_home_001",
        agent_machine_id="agent_machine_home_mac",
        role="primary",
        authority_epoch=1,
        state_revision=0,
    )
    store.pair_device(
        device=device,
        agent_machine=machine,
        binding=binding,
        pairing_token="pair-token-001",
        idempotency_key="pair-001",
    )
    connection.close()

    reopened = DeviceRegistry(connect_db(db_path))

    pairing = reopened.require_device_pairing_token("device_body_001", "pair-token-001")
    assert pairing.device.device_id == "device_body_001"
    assert reopened.get_device("device_body_001").firmware_version == "0.1.0"
    assert reopened.get_agent_machine("agent_machine_home_mac").owner_user_id == "user_demo"
    assert reopened.get_binding("buddy_home_001").agent_machine_id == "agent_machine_home_mac"


def test_sqlite_backed_device_registry_persists_repair_tombstones_across_reinstantiation(tmp_path) -> None:
    db_path = tmp_path / "buddys.sqlite3"
    connection = connect_db(db_path)
    initialize_database(connection)
    store = DeviceRegistry(connection)
    machine = AgentMachine(
        agent_machine_id="agent_machine_home_mac",
        owner_user_id="user_demo",
        machine_type="local_mac",
        endpoint="https://agent-machine.example.test",
        public_key="agent-machine-public-key",
        runtime_version="0.1.0",
        status="online",
    )
    binding = BuddyRuntimeBinding(
        buddy_id="buddy_home_001",
        agent_machine_id="agent_machine_home_mac",
        role="primary",
        authority_epoch=1,
        state_revision=0,
    )
    store.pair_device(
        device=Device(
            device_id="device_body_001",
            buddy_id="buddy_home_001",
            space_id="space_home",
            public_key="device-public-key",
            pairing_state="paired",
            firmware_version="0.1.0",
        ),
        agent_machine=machine,
        binding=binding,
        pairing_token="pair-token-old",
        idempotency_key="pair-001",
    )
    store.pair_device(
        device=Device(
            device_id="device_body_001",
            buddy_id="buddy_home_001",
            space_id="space_home",
            public_key="device-public-key",
            pairing_state="paired",
            firmware_version="0.2.0",
        ),
        agent_machine=machine.model_copy(update={"runtime_version": "0.2.0"}),
        binding=binding,
        pairing_token="pair-token-new",
        idempotency_key="pair-002",
    )
    connection.close()

    reopened = DeviceRegistry(connect_db(db_path))

    try:
        reopened.require_device_pairing_token("device_body_001", "pair-token-old")
    except KeyError:
        pass
    else:
        raise AssertionError("expected old pairing token to stay invalid after restart")
    assert reopened.require_device_pairing_token("device_body_001", "pair-token-new").device.device_id == "device_body_001"

    try:
        reopened.pair_device(
            device=Device(
                device_id="device_body_002",
                buddy_id="buddy_home_002",
                space_id="space_home",
                public_key="device-public-key-2",
                pairing_state="paired",
                firmware_version="0.2.0",
            ),
            agent_machine=machine.model_copy(update={"agent_machine_id": "agent_machine_home_mac_2"}),
            binding=binding.model_copy(update={"buddy_id": "buddy_home_002", "agent_machine_id": "agent_machine_home_mac_2"}),
            pairing_token="pair-token-old",
            idempotency_key="pair-003",
        )
    except DuplicatePairingError:
        pass
    else:
        raise AssertionError("expected revoked pairing token to remain unusable after restart")


def test_sqlite_backed_device_registry_does_not_persist_plaintext_pairing_tokens(tmp_path) -> None:
    db_path = tmp_path / "buddys.sqlite3"
    connection = connect_db(db_path)
    initialize_database(connection)
    store = DeviceRegistry(connection)
    machine = AgentMachine(
        agent_machine_id="agent_machine_home_mac",
        owner_user_id="user_demo",
        machine_type="local_mac",
        endpoint="https://agent-machine.example.test",
        public_key="agent-machine-public-key",
        runtime_version="0.1.0",
        status="online",
    )
    binding = BuddyRuntimeBinding(
        buddy_id="buddy_home_001",
        agent_machine_id="agent_machine_home_mac",
        role="primary",
        authority_epoch=1,
        state_revision=0,
    )
    store.pair_device(
        device=Device(
            device_id="device_body_001",
            buddy_id="buddy_home_001",
            space_id="space_home",
            public_key="device-public-key",
            pairing_state="paired",
            firmware_version="0.1.0",
        ),
        agent_machine=machine,
        binding=binding,
        pairing_token="pair-token-old",
        idempotency_key="pair-001",
    )
    store.pair_device(
        device=Device(
            device_id="device_body_001",
            buddy_id="buddy_home_001",
            space_id="space_home",
            public_key="device-public-key",
            pairing_state="paired",
            firmware_version="0.2.0",
        ),
        agent_machine=machine.model_copy(update={"runtime_version": "0.2.0"}),
        binding=binding,
        pairing_token="pair-token-new",
        idempotency_key="pair-002",
    )

    serialized_pairings = str(
        connection.execute("SELECT * FROM device_pairings_runtime ORDER BY device_id, idempotency_key").fetchall()
    )
    serialized_revoked = str(
        connection.execute("SELECT * FROM device_revoked_pairing_tokens_runtime ORDER BY pairing_token").fetchall()
    )
    assert "pair-token-old" not in serialized_pairings
    assert "pair-token-new" not in serialized_pairings
    assert "pair-token-old" not in serialized_revoked
    assert "pair-token-new" not in serialized_revoked


def test_sqlite_backed_device_registry_repair_write_failure_preserves_old_auth_and_restart_state(tmp_path) -> None:
    db_path = tmp_path / "buddys.sqlite3"
    connection = connect_db(db_path)
    initialize_database(connection)
    store = DeviceRegistry(connection)
    machine = AgentMachine(
        agent_machine_id="agent_machine_home_mac",
        owner_user_id="user_demo",
        machine_type="local_mac",
        endpoint="https://agent-machine.example.test",
        public_key="agent-machine-public-key",
        runtime_version="0.1.0",
        status="online",
    )
    binding = BuddyRuntimeBinding(
        buddy_id="buddy_home_001",
        agent_machine_id="agent_machine_home_mac",
        role="primary",
        authority_epoch=1,
        state_revision=0,
    )
    store.pair_device(
        device=Device(
            device_id="device_body_001",
            buddy_id="buddy_home_001",
            space_id="space_home",
            public_key="device-public-key",
            pairing_state="paired",
            firmware_version="0.1.0",
        ),
        agent_machine=machine,
        binding=binding,
        pairing_token="pair-token-old",
        idempotency_key="pair-001",
    )

    original_persist_pairing = store._persist_pairing

    def failing_persist_pairing(*args, **kwargs):  # noqa: ANN002, ANN003
        raise RuntimeError("boom")

    store._persist_pairing = failing_persist_pairing
    try:
        try:
            store.pair_device(
                device=Device(
                    device_id="device_body_001",
                    buddy_id="buddy_home_001",
                    space_id="space_home",
                    public_key="device-public-key",
                    pairing_state="paired",
                    firmware_version="0.2.0",
                ),
                agent_machine=machine.model_copy(update={"runtime_version": "0.2.0"}),
                binding=binding,
                pairing_token="pair-token-new",
                idempotency_key="pair-002",
            )
        except RuntimeError as exc:
            assert str(exc) == "boom"
        else:
            raise AssertionError("expected persist failure to abort repair")
    finally:
        store._persist_pairing = original_persist_pairing

    assert store.require_device_pairing_token("device_body_001", "pair-token-old").device.device_id == "device_body_001"
    connection.close()

    reopened = DeviceRegistry(connect_db(db_path))
    assert reopened.require_device_pairing_token("device_body_001", "pair-token-old").device.device_id == "device_body_001"
    try:
        reopened.require_device_pairing_token("device_body_001", "pair-token-new")
    except KeyError:
        pass
    else:
        raise AssertionError("expected failed repair token to be absent after restart")


def test_sqlite_backed_device_registry_migrates_legacy_plaintext_pairing_storage(tmp_path) -> None:
    db_path = tmp_path / "buddys.sqlite3"
    connection = connect_db(db_path)
    initialize_database(connection)
    legacy_payload = json.dumps(
        {
            "agent_machine": {
                "agent_machine_id": "agent_machine_home_mac",
                "endpoint": "https://agent-machine.example.test",
                "machine_type": "local_mac",
                "owner_user_id": "user_demo",
                "public_key": "agent-machine-public-key",
                "runtime_version": "0.1.0",
                "status": "online",
            },
            "binding": {
                "agent_machine_id": "agent_machine_home_mac",
                "authority_epoch": 1,
                "buddy_id": "buddy_home_001",
                "role": "primary",
                "state_revision": 0,
            },
            "device": {
                "buddy_id": "buddy_home_001",
                "device_id": "device_body_001",
                "firmware_version": "0.1.0",
                "pairing_state": "paired",
                "public_key": "device-public-key",
                "space_id": "space_home",
            },
            "idempotency_key": "pair-001",
            "pairing_token": "legacy-plaintext-token",
        },
        ensure_ascii=False,
        sort_keys=True,
    )
    with connection:
        connection.execute(
            """
            INSERT INTO device_pairings_runtime (
                device_id, idempotency_key, pairing_token, buddy_id, agent_machine_id, created_at, payload_json
            )
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "device_body_001",
                "pair-001",
                "legacy-plaintext-token",
                "buddy_home_001",
                "agent_machine_home_mac",
                "2026-06-22T00:00:00+00:00",
                legacy_payload,
            ),
        )
        connection.execute(
            """
            INSERT INTO device_revoked_pairing_tokens_runtime (pairing_token, device_id, revoked_at)
            VALUES (?, ?, ?)
            """,
            ("legacy-revoked-token", "device_body_002", "2026-06-22T00:00:00+00:00"),
        )
    connection.close()

    reopened_connection = connect_db(db_path)
    reopened = DeviceRegistry(reopened_connection)

    assert reopened.require_device_pairing_token("device_body_001", "legacy-plaintext-token").device.device_id == "device_body_001"
    serialized_pairings = str(
        reopened_connection.execute("SELECT * FROM device_pairings_runtime").fetchall()
    )
    serialized_revoked = str(
        reopened_connection.execute("SELECT * FROM device_revoked_pairing_tokens_runtime").fetchall()
    )
    assert "legacy-plaintext-token" not in serialized_pairings
    assert "legacy-revoked-token" not in serialized_revoked
