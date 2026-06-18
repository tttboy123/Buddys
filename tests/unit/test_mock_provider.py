from buddys_api.providers.mock_provider import MockProvider


def test_mock_provider_generates_light_proposal():
    result = MockProvider().plan("把客厅灯调暗", buddy_id="buddy_home_001", trace_id="trace_001")

    assert result.intent_name == "adjust_light"
    assert result.proposal.tool_id == "mock_home.light"
    assert result.proposal.action == "set_brightness"
    assert result.proposal.args["brightness"] == 35


def test_mock_provider_generates_temperature_proposal():
    result = MockProvider().plan("把温度调到 24 度", buddy_id="buddy_home_001", trace_id="trace_001")

    assert result.intent_name == "set_temperature"
    assert result.proposal.tool_id == "mock_home.climate"
    assert result.proposal.args["temperature_c"] == 24


def test_mock_provider_generates_scene_proposal():
    result = MockProvider().plan("打开观影模式", buddy_id="buddy_home_001", trace_id="trace_001")

    assert result.intent_name == "activate_scene"
    assert result.proposal.tool_id == "mock_home.scene"
    assert result.proposal.args["scene"] == "movie_mode"


def test_unknown_text_returns_reply_only():
    result = MockProvider().plan("你好", buddy_id="buddy_home_001", trace_id="trace_001")

    assert result.intent_name == "chat"
    assert result.proposal.action_type == "reply_only"
