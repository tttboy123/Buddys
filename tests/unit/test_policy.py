from buddys_api.policy import PermissionPolicy
from buddys_api.schemas import ActionProposal


def make_proposal(**overrides):
    data = {
        "proposal_id": "proposal_001",
        "trace_id": "trace_001",
        "buddy_id": "buddy_home_001",
        "action_type": "tool_call",
        "summary": "把客厅灯亮度调到 35%",
        "requires_confirmation": True,
        "tool_id": "mock_home.light",
        "action": "set_brightness",
        "args": {"target": "living_room_light", "brightness": 35},
        "risk_level": "low",
    }
    data.update(overrides)
    return ActionProposal(**data)


def test_a_level_tool_call_requires_confirmation_before_user_approval():
    decision = PermissionPolicy().evaluate(make_proposal(), user_confirmation=None)

    assert decision.policy_result == "require_confirmation"
    assert decision.confirmation_result == "not_requested"


def test_a_level_tool_call_allows_execute_after_approval():
    decision = PermissionPolicy().evaluate(make_proposal(), user_confirmation="approved")

    assert decision.policy_result == "allow"
    assert decision.confirmation_result == "approved"


def test_rejected_confirmation_denies_execution():
    decision = PermissionPolicy().evaluate(make_proposal(), user_confirmation="rejected")

    assert decision.policy_result == "deny"
    assert decision.confirmation_result == "rejected"


def test_high_risk_action_is_denied_in_alpha():
    decision = PermissionPolicy().evaluate(make_proposal(risk_level="high"), user_confirmation="approved")

    assert decision.policy_result == "deny"
    assert "disabled" in decision.reason


def test_reply_only_does_not_require_confirmation():
    decision = PermissionPolicy().evaluate(
        make_proposal(action_type="reply_only", requires_confirmation=False, tool_id=None, action=None),
        user_confirmation=None,
    )

    assert decision.policy_result == "not_required"
