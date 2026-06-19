from __future__ import annotations

import re
from dataclasses import dataclass

from buddys_api.schemas import ActionProposal, new_id
from buddys_api.state_memory_models import StateMemoryCaptureSource, StateMemoryDelta


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

    def parse_state_memory_capture(self, *, source: StateMemoryCaptureSource, content: str) -> list[StateMemoryDelta]:
        deltas: list[StateMemoryDelta] = []
        for segment in re.split(r"[，,；;和]\s*", content):
            item_name = _extract_known_item_name(segment)
            if item_name is None:
                continue
            operation = _detect_state_memory_operation(segment)
            quantity, unit = _extract_quantity_and_unit(segment, item_name)
            deltas.append(
                StateMemoryDelta(
                    item_name=item_name,
                    operation=operation,
                    quantity=quantity,
                    unit=unit,
                    category=_item_category(item_name),
                    confidence=_confidence_for_source(source),
                    source=source,
                )
            )
        return deltas


_KNOWN_ITEMS = (
    "鸡蛋",
    "土豆",
    "牛奶",
    "可乐",
    "香料",
    "八角",
    "生抽",
)

_KNOWN_UNITS = ("个", "袋", "盒", "瓶", "包", "罐")

_CHINESE_DIGITS = {
    "零": 0,
    "一": 1,
    "二": 2,
    "两": 2,
    "三": 3,
    "四": 4,
    "五": 5,
    "六": 6,
    "七": 7,
    "八": 8,
    "九": 9,
    "十": 10,
}

_SOURCE_CONFIDENCE = {
    "voice": 0.92,
    "photo": 0.81,
    "scan": 0.99,
    "conversation": 0.88,
    "inference": 0.74,
}


def _extract_known_item_name(text: str) -> str | None:
    for item_name in _KNOWN_ITEMS:
        if item_name in text:
            return item_name
    return None


def _detect_state_memory_operation(text: str) -> str:
    if any(marker in text for marker in ("用完", "没了", "没有了", "用光")):
        return "remove"
    if any(marker in text for marker in ("用掉", "用了", "吃了")):
        return "consume"
    return "upsert"


def _extract_quantity_and_unit(text: str, item_name: str) -> tuple[float | None, str | None]:
    pattern = re.compile(
        rf"(?P<quantity>\d+(?:\.\d+)?|[零一二两三四五六七八九十]+)\s*(?P<unit>{'|'.join(_KNOWN_UNITS)})?\s*{re.escape(item_name)}"
    )
    match = pattern.search(text)
    if match is not None:
        return _parse_quantity(match.group("quantity")), match.group("unit")

    reverse_pattern = re.compile(
        rf"{re.escape(item_name)}\s*(?P<quantity>\d+(?:\.\d+)?|[零一二两三四五六七八九十]+)\s*(?P<unit>{'|'.join(_KNOWN_UNITS)})?"
    )
    reverse_match = reverse_pattern.search(text)
    if reverse_match is not None:
        return _parse_quantity(reverse_match.group("quantity")), reverse_match.group("unit")
    return None, None


def _parse_quantity(raw: str | None) -> float | None:
    if raw is None:
        return None
    if re.fullmatch(r"\d+(?:\.\d+)?", raw):
        return float(raw)
    if raw == "十":
        return 10.0
    if len(raw) == 2 and raw[0] == "十":
        return float(10 + _CHINESE_DIGITS.get(raw[1], 0))
    if len(raw) == 2 and raw[1] == "十":
        return float((_CHINESE_DIGITS.get(raw[0], 0) or 1) * 10)
    if len(raw) == 3 and raw[1] == "十":
        return float((_CHINESE_DIGITS.get(raw[0], 0) or 1) * 10 + _CHINESE_DIGITS.get(raw[2], 0))
    return float(_CHINESE_DIGITS.get(raw, 0))


def _item_category(item_name: str) -> str:
    if item_name == "可乐":
        return "beverage"
    return "ingredient"


def _confidence_for_source(source: StateMemoryCaptureSource) -> float:
    return _SOURCE_CONFIDENCE[source]
