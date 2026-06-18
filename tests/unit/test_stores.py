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
