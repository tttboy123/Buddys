from buddys_api.db import connect_db, initialize_database
from buddys_api.cost_meter import CostMeter
from buddys_api.schemas import ActionTrace
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
