from buddys_api.schemas import (
    ActionProposal,
    ActionTrace,
    Buddy,
    CostEvent,
    PermissionDecision,
)


def test_buddy_requires_core_identity_fields():
    buddy = Buddy(
        buddy_id="buddy_home_001",
        user_id="user_demo",
        name="家 Buddy",
        space_id="space_home",
        device_id="device_mock_home_001",
        autonomy_level="A",
        status="idle",
    )

    assert buddy.buddy_id == "buddy_home_001"
    assert buddy.autonomy_level == "A"


def test_action_proposal_is_not_executed_by_default():
    proposal = ActionProposal(
        proposal_id="proposal_001",
        trace_id="trace_001",
        buddy_id="buddy_home_001",
        action_type="tool_call",
        summary="把客厅灯亮度调到 35%",
        requires_confirmation=True,
        tool_id="mock_home.light",
        action="set_brightness",
        args={"target": "living_room_light", "brightness": 35},
        risk_level="low",
    )

    assert proposal.executed is False
    assert proposal.requires_confirmation is True


def test_permission_decision_export_shape():
    decision = PermissionDecision(
        policy_result="require_confirmation",
        confirmation_result="not_requested",
        decided_by="policy",
        reason="A-level device action requires confirmation.",
        policy_version="p0-a-level-v1",
    )

    assert decision.model_dump()["policy_result"] == "require_confirmation"


def test_action_trace_and_cost_event_link_by_trace_id():
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
    cost = CostEvent(
        cost_event_id="cost_001",
        trace_id="trace_001",
        buddy_id="buddy_home_001",
        provider="mock_deterministic",
        model="mock-home-v1",
        input_tokens=32,
        output_tokens=18,
        model_cost_usd=0.0,
        tool_cost_usd=0.0,
        log_cost_usd=0.0,
    )

    assert cost.trace_id == trace.trace_id
    assert trace.review_status == "unreviewed"
