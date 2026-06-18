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
