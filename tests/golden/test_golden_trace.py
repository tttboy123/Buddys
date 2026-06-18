from fastapi.testclient import TestClient

from buddys_api.adapters.mock_home import MockHomeAdapter
from buddys_api.main import create_app
from buddys_api.runtime import BuddysRuntime


def test_approved_dim_light_flow_emits_golden_trace() -> None:
    client = TestClient(create_app())
    buddy = client.post("/buddies", json={"user_id": "user_1"}).json()

    message_response = client.post(
        f"/buddies/{buddy['buddy_id']}/messages",
        json={"user_id": "user_1", "message": "把客厅灯调暗"},
    )
    assert message_response.status_code == 200
    message = message_response.json()

    confirm_response = client.post(
        f"/proposals/{message['proposal_id']}/confirm",
        json={"decision": "approved"},
    )
    assert confirm_response.status_code == 200

    trace_response = client.get(f"/traces/{message['trace_id']}")
    assert trace_response.status_code == 200
    trace = trace_response.json()

    assert trace["intent"]["name"] == "adjust_light"
    assert trace["proposal"]["tool_id"] == "mock_home.light"
    assert trace["proposal"]["action"] == "set_brightness"
    assert trace["permission_decision"]["policy_result"] == "allow"
    assert trace["permission_decision"]["confirmation_result"] == "approved"
    assert trace["tool_call"]["adapter_id"] == "mock_home"
    assert trace["tool_result"]["status"] == "success"
    assert trace["model_usage"]["provider"] == "mock_deterministic"
    assert len(trace["cost_refs"]) == 1


def test_manual_fallback_dim_light_flow_emits_golden_trace() -> None:
    client = TestClient(create_app(BuddysRuntime(adapter=MockHomeAdapter(can_control_devices=False))))
    buddy = client.post("/buddies", json={"user_id": "user_1"}).json()

    message_response = client.post(
        f"/buddies/{buddy['buddy_id']}/messages",
        json={"user_id": "user_1", "message": "把客厅灯调暗"},
    )
    assert message_response.status_code == 200
    message = message_response.json()

    confirm_response = client.post(
        f"/proposals/{message['proposal_id']}/confirm",
        json={"decision": "approved"},
    )
    assert confirm_response.status_code == 200

    trace_response = client.get(f"/traces/{message['trace_id']}")
    assert trace_response.status_code == 200
    trace = trace_response.json()

    assert trace["intent"]["name"] == "adjust_light"
    assert trace["proposal"]["executed"] is False
    assert trace["permission_decision"]["policy_result"] == "allow"
    assert trace["tool_call"]["tool_id"] == "mock_home.light"
    assert trace["tool_result"]["status"] == "manual_required"
    assert trace["tool_result"]["error_code"] == "adapter_unavailable"
    assert trace["tool_result"]["user_instruction"] == "请手动把客厅灯调暗到约 35%。"
    assert trace["tool_result"]["voice_prompt"] == "我现在无法直接控制客厅灯。请手动把客厅灯调暗到约 35%，完成后可以告诉我。"
