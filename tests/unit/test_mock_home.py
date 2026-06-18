from buddys_api.adapters.mock_home import MockHomeAdapter
from buddys_api.schemas import ToolCall


def test_mock_home_sets_light_brightness():
    result = MockHomeAdapter().execute(
        ToolCall(
            tool_call_id="tool_call_001",
            adapter_id="mock_home",
            tool_id="mock_home.light",
            action="set_brightness",
            args={"target": "living_room_light", "brightness": 35},
        )
    )

    assert result.status == "success"
    assert "35%" in result.output_summary


def test_mock_home_rejects_invalid_brightness():
    result = MockHomeAdapter().execute(
        ToolCall(
            tool_call_id="tool_call_001",
            adapter_id="mock_home",
            tool_id="mock_home.light",
            action="set_brightness",
            args={"target": "living_room_light", "brightness": 120},
        )
    )

    assert result.status == "failure"
    assert result.error_code == "invalid_brightness"


def test_mock_home_returns_manual_instruction_when_device_control_is_unavailable():
    result = MockHomeAdapter(can_control_devices=False).execute(
        ToolCall(
            tool_call_id="tool_call_001",
            adapter_id="mock_home",
            tool_id="mock_home.light",
            action="set_brightness",
            args={"target": "living_room_light", "brightness": 35},
        )
    )

    assert result.status == "manual_required"
    assert result.error_code == "adapter_unavailable"
    assert result.user_instruction == "请手动把客厅灯调暗到约 35%。"
    assert result.voice_prompt == "我现在无法直接控制客厅灯。请手动把客厅灯调暗到约 35%，完成后可以告诉我。"
