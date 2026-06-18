from fastapi.testclient import TestClient

from buddys_api.adapters.mock_home import MockHomeAdapter
from buddys_api.main import create_app
from buddys_api.runtime import BuddysRuntime


def make_client() -> TestClient:
    return TestClient(create_app())


def test_healthz_returns_ok() -> None:
    client = make_client()

    response = client.get("/healthz")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_create_and_get_buddy() -> None:
    client = make_client()

    create_response = client.post("/buddies", json={"user_id": "user_1"})

    assert create_response.status_code == 201
    created = create_response.json()
    assert created["buddy_id"].startswith("buddy_")
    assert created["user_id"] == "user_1"
    assert created["name"] == "Home Buddy"
    assert created["space_id"] == "home"
    assert created["autonomy_level"] == "A"
    assert created["status"] == "idle"

    get_response = client.get(f"/buddies/{created['buddy_id']}")

    assert get_response.status_code == 200
    assert get_response.json() == created


def test_message_confirm_trace_and_cost_flow() -> None:
    client = make_client()
    buddy = client.post("/buddies", json={"user_id": "user_1"}).json()

    message_response = client.post(
        f"/buddies/{buddy['buddy_id']}/messages",
        json={"user_id": "user_1", "message": "把客厅灯调暗"},
    )

    assert message_response.status_code == 200
    message = message_response.json()
    assert message["trace_id"].startswith("trace_")
    assert message["proposal_id"].startswith("proposal_")
    assert message["requires_confirmation"] is True
    assert message["assistant_message"] == "把客厅灯亮度调到 35%。需要确认后执行。"
    assert len(message["cost_event_ids"]) == 1

    pending_trace_response = client.get(f"/traces/{message['trace_id']}")
    assert pending_trace_response.status_code == 200
    pending_trace = pending_trace_response.json()
    assert pending_trace["permission_decision"]["policy_result"] == "require_confirmation"
    assert pending_trace["tool_call"] is None
    assert pending_trace["tool_result"] is None

    confirm_response = client.post(
        f"/proposals/{message['proposal_id']}/confirm",
        json={"approved": True},
    )

    assert confirm_response.status_code == 200
    confirmed = confirm_response.json()
    assert confirmed["trace_id"] == message["trace_id"]
    assert confirmed["proposal_id"] == message["proposal_id"]
    assert confirmed["permission_decision"]["policy_result"] == "allow"
    assert confirmed["permission_decision"]["confirmation_result"] == "approved"
    assert confirmed["tool_result"]["status"] == "success"
    assert confirmed["tool_result"]["error_code"] is None

    trace_response = client.get(f"/traces/{message['trace_id']}")
    assert trace_response.status_code == 200
    trace = trace_response.json()
    assert trace["trace_id"] == message["trace_id"]
    assert trace["proposal"]["executed"] is True
    assert trace["tool_call"]["adapter_id"] == "mock_home"
    assert trace["tool_call"]["tool_id"] == "mock_home.light"
    assert trace["tool_result"]["status"] == "success"
    assert trace["cost_refs"] == message["cost_event_ids"]

    costs_response = client.get("/cost-events")
    assert costs_response.status_code == 200
    costs = costs_response.json()
    assert len(costs["cost_events"]) == 1
    assert costs["cost_events"][0]["cost_event_id"] == message["cost_event_ids"][0]
    assert costs["cost_events"][0]["trace_id"] == message["trace_id"]
    assert costs["cost_events"][0]["buddy_id"] == buddy["buddy_id"]
    assert costs["cost_events"][0]["provider"] == "mock_deterministic"


def test_missing_resources_return_stable_404_detail_codes() -> None:
    client = make_client()

    missing_buddy = client.get("/buddies/missing_buddy")
    assert missing_buddy.status_code == 404
    assert missing_buddy.json() == {"detail": {"code": "buddy_not_found"}}

    missing_message_buddy = client.post(
        "/buddies/missing_buddy/messages",
        json={"user_id": "user_1", "message": "把客厅灯调暗"},
    )
    assert missing_message_buddy.status_code == 404
    assert missing_message_buddy.json() == {"detail": {"code": "buddy_not_found"}}

    missing_proposal = client.post("/proposals/missing_proposal/confirm", json={"approved": True})
    assert missing_proposal.status_code == 404
    assert missing_proposal.json() == {"detail": {"code": "proposal_not_found"}}

    missing_trace = client.get("/traces/missing_trace")
    assert missing_trace.status_code == 404
    assert missing_trace.json() == {"detail": {"code": "trace_not_found"}}


def test_api_confirm_response_exposes_manual_fallback_instruction() -> None:
    client = TestClient(create_app(BuddysRuntime(adapter=MockHomeAdapter(can_control_devices=False))))
    buddy = client.post("/buddies", json={"user_id": "user_1"}).json()
    message = client.post(
        f"/buddies/{buddy['buddy_id']}/messages",
        json={"user_id": "user_1", "message": "把客厅灯调暗"},
    ).json()

    confirm_response = client.post(
        f"/proposals/{message['proposal_id']}/confirm",
        json={"approved": True},
    )

    assert confirm_response.status_code == 200
    confirmed = confirm_response.json()
    assert confirmed["tool_result"]["status"] == "manual_required"
    assert confirmed["tool_result"]["error_code"] == "adapter_unavailable"
    assert confirmed["tool_result"]["user_instruction"] == "请手动把客厅灯调暗到约 35%。"
    assert confirmed["tool_result"]["voice_prompt"] == "我现在无法直接控制客厅灯。请手动把客厅灯调暗到约 35%，完成后可以告诉我。"

    trace = client.get(f"/traces/{message['trace_id']}").json()
    assert trace["proposal"]["executed"] is False
    assert trace["tool_result"]["status"] == "manual_required"


def test_create_app_can_simulate_unavailable_device_control_from_environment(monkeypatch) -> None:
    monkeypatch.setenv("BUDDYS_MOCK_CAN_CONTROL_DEVICES", "false")
    client = TestClient(create_app())
    buddy = client.post("/buddies", json={"user_id": "user_1"}).json()
    message = client.post(
        f"/buddies/{buddy['buddy_id']}/messages",
        json={"user_id": "user_1", "message": "把客厅灯调暗"},
    ).json()

    confirm_response = client.post(
        f"/proposals/{message['proposal_id']}/confirm",
        json={"approved": True},
    )

    assert confirm_response.status_code == 200
    confirmed = confirm_response.json()
    assert confirmed["tool_result"]["status"] == "manual_required"
    assert confirmed["tool_result"]["user_instruction"] == "请手动把客厅灯调暗到约 35%。"
