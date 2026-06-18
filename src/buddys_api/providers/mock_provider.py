from __future__ import annotations

import re
from dataclasses import dataclass

from buddys_api.schemas import ActionProposal, new_id


@dataclass(frozen=True)
class ProviderPlanResult:
    intent_name: str
    proposal: ActionProposal


class MockProvider:
    provider = "mock_deterministic"
    model = "mock-home-v0"

    def plan(self, text: str, buddy_id: str, trace_id: str) -> ProviderPlanResult:
        if "客厅灯" in text and ("调暗" in text or "亮度" in text):
            return ProviderPlanResult(
                intent_name="adjust_light",
                proposal=ActionProposal(
                    proposal_id=new_id("proposal"),
                    trace_id=trace_id,
                    buddy_id=buddy_id,
                    action_type="tool_call",
                    summary="把客厅灯亮度调到 35%",
                    requires_confirmation=True,
                    tool_id="mock_home.light",
                    action="set_brightness",
                    args={"target": "living_room_light", "brightness": 35},
                    risk_level="low",
                ),
            )

        if "温度" in text:
            temperature_c = self._extract_first_int(text, default=24)
            return ProviderPlanResult(
                intent_name="set_temperature",
                proposal=ActionProposal(
                    proposal_id=new_id("proposal"),
                    trace_id=trace_id,
                    buddy_id=buddy_id,
                    action_type="tool_call",
                    summary=f"把客厅温度调到 {temperature_c} 度",
                    requires_confirmation=True,
                    tool_id="mock_home.climate",
                    action="set_temperature",
                    args={"target": "living_room_ac", "temperature_c": temperature_c},
                    risk_level="low",
                ),
            )

        if "观影模式" in text:
            return ProviderPlanResult(
                intent_name="activate_scene",
                proposal=ActionProposal(
                    proposal_id=new_id("proposal"),
                    trace_id=trace_id,
                    buddy_id=buddy_id,
                    action_type="tool_call",
                    summary="打开观影模式",
                    requires_confirmation=True,
                    tool_id="mock_home.scene",
                    action="activate",
                    args={"target": "movie_mode", "scene": "movie_mode"},
                    risk_level="low",
                ),
            )

        return ProviderPlanResult(
            intent_name="chat",
            proposal=ActionProposal(
                proposal_id=new_id("proposal"),
                trace_id=trace_id,
                buddy_id=buddy_id,
                action_type="reply_only",
                summary="继续对话，不执行设备动作。",
                requires_confirmation=False,
                tool_id=None,
                action=None,
                args={},
                risk_level="none",
            ),
        )

    def _extract_first_int(self, text: str, default: int) -> int:
        match = re.search(r"\d+", text)
        if match is None:
            return default
        return int(match.group(0))
