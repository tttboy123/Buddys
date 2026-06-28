from buddys_api.db import connect_db, initialize_database
from buddys_api.cost_meter import CostMeter
from buddys_api.schemas import ActionProposal, ActionTrace, Intent, PermissionDecision
from buddys_api.trace_store import TraceStore


def test_trace_store_saves_and_gets_trace():
    store = TraceStore()
    trace = ActionTrace.minimal_pending(
        trace_id="trace_001",
        user_id="user_demo",
        buddy_id="buddy_home_001",
        space_id="space_home",
        device_id="device_mock_home_001",
        turn_id="turn_001",
        intent_name="adjust_light",
        summary="把客厅灯调暗",
    )

    store.save(trace)

    assert store.get("trace_001").trace_id == "trace_001"


def test_cost_meter_writes_zero_cost_mock_event():
    event = CostMeter().record_model_call(
        trace_id="trace_001",
        buddy_id="buddy_home_001",
        provider="mock_deterministic",
        model="mock-home-v1",
        input_tokens=32,
        output_tokens=18,
    )

    assert event.model_cost_usd == 0.0
    assert event.trace_id == "trace_001"


def test_trace_store_persists_traces_in_sqlite_after_reopen(tmp_path) -> None:
    db_path = tmp_path / "buddys.sqlite3"
    first_connection = connect_db(db_path)
    initialize_database(first_connection)
    first_store = TraceStore(first_connection)
    trace = ActionTrace.minimal_pending(
        trace_id="trace_sqlite_001",
        user_id="user_demo",
        buddy_id="buddy_home_001",
        space_id="space_home",
        device_id="device_mock_home_001",
        turn_id="turn_001",
        intent_name="adjust_light",
        summary="把客厅灯调暗",
    )

    first_store.save(trace)
    first_connection.close()

    second_connection = connect_db(db_path)
    initialize_database(second_connection)
    second_store = TraceStore(second_connection)

    reopened = second_store.get("trace_sqlite_001")

    assert reopened.trace_id == "trace_sqlite_001"
    assert reopened.intent.summary == "把客厅灯调暗"
    assert [saved.trace_id for saved in second_store.list()] == ["trace_sqlite_001"]


def test_cost_meter_persists_events_in_sqlite_after_reopen(tmp_path) -> None:
    db_path = tmp_path / "buddys.sqlite3"
    first_connection = connect_db(db_path)
    initialize_database(first_connection)
    first_meter = CostMeter(first_connection)

    first_meter.record_model_call(
        trace_id="trace_sqlite_001",
        buddy_id="buddy_home_001",
        provider="mock_deterministic",
        model="mock-home-v1",
        input_tokens=32,
        output_tokens=18,
    )
    first_connection.close()

    second_connection = connect_db(db_path)
    initialize_database(second_connection)
    second_meter = CostMeter(second_connection)

    events = second_meter.list()

    assert len(events) == 1
    assert events[0].trace_id == "trace_sqlite_001"
    assert events[0].provider == "mock_deterministic"
    assert events[0].input_tokens == 32
    assert events[0].output_tokens == 18


def test_trace_store_get_by_proposal_id_in_sqlite(tmp_path) -> None:
    db_path = tmp_path / "buddys.sqlite3"
    connection = connect_db(db_path)
    initialize_database(connection)
    first_store = TraceStore(connection)

    proposal_a = ActionProposal(
        proposal_id="proposal_a",
        trace_id="trace_a",
        buddy_id="buddy_home_001",
        action_type="tool_call",
        summary="先把灯调暗",
        requires_confirmation=True,
        tool_id="mock_home.light",
        action="set_brightness",
        args={"target": "living_room_light", "brightness": 35},
    )
    proposal_b = ActionProposal(
        proposal_id="proposal_b",
        trace_id="trace_b",
        buddy_id="buddy_home_001",
        action_type="tool_call",
        summary="再把灯打开",
        requires_confirmation=True,
        tool_id="mock_home.light",
        action="set_brightness",
        args={"target": "living_room_light", "brightness": 80},
    )

    first_store.save(
        ActionTrace(
            trace_id="trace_a",
            user_id="user_demo",
            buddy_id="buddy_home_001",
            space_id="space_home",
            device_id="device_mock_home_001",
            turn_id="turn_a",
            intent=Intent(name="adjust_light", summary="调整灯光"),
            proposal=proposal_a,
            permission_decision=PermissionDecision(
                policy_result="allow",
                confirmation_result="not_requested",
                decided_by="policy",
                reason="runtime_test",
            ),
        )
    )
    first_store.save(
        ActionTrace(
            trace_id="trace_b",
            user_id="user_demo",
            buddy_id="buddy_home_001",
            space_id="space_home",
            device_id="device_mock_home_001",
            turn_id="turn_b",
            intent=Intent(name="adjust_light", summary="调整灯光"),
            proposal=proposal_b,
            permission_decision=PermissionDecision(
                policy_result="allow",
                confirmation_result="not_requested",
                decided_by="policy",
                reason="runtime_test",
            ),
        )
    )

    restored_trace = first_store.get_by_proposal_id("proposal_b")
    assert restored_trace is not None
    assert restored_trace.trace_id == "trace_b"
    assert restored_trace.proposal is not None
    assert restored_trace.proposal.proposal_id == "proposal_b"
    connection.close()

    reopen_connection = connect_db(db_path)
    initialize_database(reopen_connection)
    reopen_store = TraceStore(reopen_connection)

    reopened_trace = reopen_store.get_by_proposal_id("proposal_b")
    assert reopened_trace is not None
    assert reopened_trace.trace_id == "trace_b"
    assert reopened_trace.proposal is not None
    assert reopened_trace.proposal.proposal_id == "proposal_b"
    assert reopen_store.get_by_proposal_id("proposal_missing") is None

    reopen_connection.close()
