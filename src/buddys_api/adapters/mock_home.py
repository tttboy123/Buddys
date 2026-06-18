from __future__ import annotations

from typing import Any

from buddys_api.schemas import ToolCall, ToolResult


class MockHomeAdapter:
    adapter_id = "mock_home"

    def execute(self, tool_call: ToolCall) -> ToolResult:
        if tool_call.tool_id == "mock_home.light" and tool_call.action == "set_brightness":
            return self._set_brightness(tool_call.args)

        if tool_call.tool_id == "mock_home.climate" and tool_call.action == "set_temperature":
            return self._set_temperature(tool_call.args)

        if tool_call.tool_id == "mock_home.scene" and tool_call.action == "activate":
            return self._activate_scene(tool_call.args)

        return ToolResult(
            status="failure",
            output_summary="Unknown mock home tool action.",
            error_code="unknown_tool_action",
            latency_ms=0,
        )

    def _set_brightness(self, args: dict[str, Any]) -> ToolResult:
        brightness = args.get("brightness")
        if not isinstance(brightness, int) or not 0 <= brightness <= 100:
            return ToolResult(
                status="failure",
                output_summary="Brightness must be an integer from 0 to 100.",
                error_code="invalid_brightness",
                latency_ms=0,
            )

        target = args.get("target", "light")
        return ToolResult(
            status="success",
            output_summary=f"{target} brightness set to {brightness}%.",
            latency_ms=0,
        )

    def _set_temperature(self, args: dict[str, Any]) -> ToolResult:
        temperature_c = args.get("temperature_c")
        if not isinstance(temperature_c, int) or not 16 <= temperature_c <= 30:
            return ToolResult(
                status="failure",
                output_summary="Temperature must be an integer from 16 to 30 C.",
                error_code="invalid_temperature",
                latency_ms=0,
            )

        target = args.get("target", "climate")
        return ToolResult(
            status="success",
            output_summary=f"{target} temperature set to {temperature_c} C.",
            latency_ms=0,
        )

    def _activate_scene(self, args: dict[str, Any]) -> ToolResult:
        scene = args.get("scene") or args.get("target")
        if scene != "movie_mode":
            return ToolResult(
                status="failure",
                output_summary="Unknown mock scene.",
                error_code="unknown_scene",
                latency_ms=0,
            )

        return ToolResult(
            status="success",
            output_summary="Movie mode activated.",
            latency_ms=0,
        )
