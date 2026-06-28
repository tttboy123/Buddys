from buddys_api.adapters.mock_home import MockHomeAdapter
from buddys_api.cost_meter import CostMeter
from buddys_api.policy import PermissionPolicy
from buddys_api.providers.mock_provider import MockProvider
from buddys_api.runtime import BuddysRuntime
from buddys_api.trace_store import TraceStore
from buddys_api.db import connect_db, initialize_database


def make_runtime() -> BuddysRuntime:
    return BuddysRuntime(
        provider=MockProvider(),
        adapter=MockHomeAdapter(),
        policy=PermissionPolicy(),
        trace_store=TraceStore(),
        cost_meter=CostMeter(),
    )


def test_create_home_buddy_returns_a_level_home_buddy() -> None:
    runtime = make_runtime()

    buddy = runtime.create_home_buddy(user_id="user_1")

    assert buddy.user_id == "user_1"
    assert buddy.name == "Home Buddy"
    assert buddy.space_id == "home"
    assert buddy.autonomy_level == "A"
    assert buddy.status == "idle"
    assert buddy.device_id is None
    assert buddy.buddy_id.startswith("buddy_")


def test_submit_message_creates_unexecuted_confirmation_proposal() -> None:
    runtime = make_runtime()
    buddy = runtime.create_home_buddy(user_id="user_1")

    proposal = runtime.submit_message(
        buddy_id=buddy.buddy_id,
        user_id="user_1",
        text="把客厅灯调暗",
    )

    assert proposal.buddy_id == buddy.buddy_id
    assert proposal.action_type == "tool_call"
    assert proposal.requires_confirmation is True
    assert proposal.tool_id == "mock_home.light"
    assert proposal.action == "set_brightness"
    assert proposal.args == {"target": "living_room_light", "brightness": 35}
    assert proposal.executed is False

    trace = runtime.trace_store.get(proposal.trace_id)
    assert trace.proposal == proposal
    assert trace.permission_decision.policy_result == "require_confirmation"
    assert trace.permission_decision.confirmation_result == "not_requested"
    assert trace.tool_call is None
    assert trace.tool_result is None


def test_confirm_proposal_approved_executes_adapter_and_links_trace_cost() -> None:
    runtime = make_runtime()
    buddy = runtime.create_home_buddy(user_id="user_1")
    proposal = runtime.submit_message(
        buddy_id=buddy.buddy_id,
        user_id="user_1",
        text="把客厅灯调暗",
    )

    trace = runtime.confirm_proposal(proposal.proposal_id, approved=True)

    assert trace.trace_id == proposal.trace_id
    assert trace.permission_decision.policy_result == "allow"
    assert trace.permission_decision.confirmation_result == "approved"
    assert trace.proposal is not None
    assert trace.proposal.executed is True
    assert trace.tool_call is not None
    assert trace.tool_call.adapter_id == "mock_home"
    assert trace.tool_call.tool_id == "mock_home.light"
    assert trace.tool_call.action == "set_brightness"
    assert trace.tool_result is not None
    assert trace.tool_result.status == "success"
    assert trace.tool_result.error_code is None
    assert len(trace.cost_refs) == 1

    cost_events = runtime.cost_meter.list()
    assert [event.cost_event_id for event in cost_events] == trace.cost_refs
    assert cost_events[0].trace_id == trace.trace_id
    assert cost_events[0].buddy_id == buddy.buddy_id
    assert cost_events[0].provider == "mock_deterministic"


def test_confirm_proposal_rejected_denies_execution_without_tool_result() -> None:
    runtime = make_runtime()
    buddy = runtime.create_home_buddy(user_id="user_1")
    proposal = runtime.submit_message(
        buddy_id=buddy.buddy_id,
        user_id="user_1",
        text="把客厅灯调暗",
    )

    trace = runtime.confirm_proposal(proposal.proposal_id, approved=False)

    assert trace.trace_id == proposal.trace_id
    assert trace.permission_decision.policy_result == "deny"
    assert trace.permission_decision.confirmation_result == "rejected"
    assert trace.proposal is not None
    assert trace.proposal.executed is False
    assert trace.tool_call is None
    assert trace.tool_result is None


def test_confirm_proposal_records_manual_fallback_without_marking_executed() -> None:
    runtime = BuddysRuntime(
        provider=MockProvider(),
        adapter=MockHomeAdapter(can_control_devices=False),
        policy=PermissionPolicy(),
        trace_store=TraceStore(),
        cost_meter=CostMeter(),
    )
    buddy = runtime.create_home_buddy(user_id="user_1")
    proposal = runtime.submit_message(
        buddy_id=buddy.buddy_id,
        user_id="user_1",
        text="把客厅灯调暗",
    )

    trace = runtime.confirm_proposal(proposal.proposal_id, approved=True)

    assert trace.permission_decision.policy_result == "allow"
    assert trace.proposal is not None
    assert trace.proposal.executed is False
    assert trace.tool_result is not None
    assert trace.tool_result.status == "manual_required"
    assert trace.tool_result.error_code == "adapter_unavailable"
    assert trace.tool_result.user_instruction == "请手动把客厅灯调暗到约 35%。"
    assert trace.tool_result.voice_prompt == "我现在无法直接控制客厅灯。请手动把客厅灯调暗到约 35%，完成后可以告诉我。"


def test_confirm_proposal_survives_runtime_restart_when_proposal_stored_in_trace_store(tmp_path) -> None:
    db_path = tmp_path / "buddys.sqlite3"

    first_connection = connect_db(db_path)
    initialize_database(first_connection)
    first_runtime = BuddysRuntime(
        provider=MockProvider(),
        adapter=MockHomeAdapter(),
        policy=PermissionPolicy(),
        trace_store=TraceStore(first_connection),
        cost_meter=CostMeter(),
    )

    first_buddy = first_runtime.create_home_buddy(user_id="user_restart")
    proposal = first_runtime.submit_message(
        buddy_id=first_buddy.buddy_id,
        user_id="user_restart",
        text="把客厅灯调暗",
    )

    first_connection.close()

    second_connection = connect_db(db_path)
    initialize_database(second_connection)
    second_runtime = BuddysRuntime(
        provider=MockProvider(),
        adapter=MockHomeAdapter(),
        policy=PermissionPolicy(),
        trace_store=TraceStore(second_connection),
        cost_meter=CostMeter(second_connection),
    )

    trace = second_runtime.confirm_proposal(proposal.proposal_id, approved=True)

    assert trace.trace_id == proposal.trace_id
    assert trace.proposal is not None
    assert trace.proposal.proposal_id == proposal.proposal_id
    assert trace.permission_decision.policy_result == "allow"
    assert trace.permission_decision.confirmation_result == "approved"
    assert trace.tool_call is not None
    assert trace.tool_result is not None
    assert trace.tool_result.status == "success"
