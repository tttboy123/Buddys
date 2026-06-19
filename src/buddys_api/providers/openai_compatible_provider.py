from __future__ import annotations

import json
import os
import re
from collections.abc import Sequence
from typing import Any, Literal

import httpx
from pydantic import BaseModel, Field

from buddys_api.provider_models import MINIMAX_OPENAI_BASE_URL
from buddys_api.state_memory_models import StateMemoryCaptureSource, StateMemoryDelta


class StateMemoryProviderError(RuntimeError):
    def __init__(self, code: str, *, usage: ProviderUsage | None = None) -> None:
        super().__init__(code)
        self.code = code
        self.usage = usage


class ProviderConfigurationError(StateMemoryProviderError):
    pass


class ModelUnavailableError(StateMemoryProviderError):
    pass


class ModelResponseError(StateMemoryProviderError):
    pass


class ProviderUsage(BaseModel):
    input_tokens: int
    output_tokens: int
    estimated: bool = False


class ParsedStateMemoryCapture(BaseModel):
    deltas: list[StateMemoryDelta] = Field(default_factory=list)
    unrecognized: list[str] = Field(default_factory=list)
    usage: ProviderUsage


class StateMemoryQueryUnderstanding(BaseModel):
    answer_type: Literal["have_item", "missing_for_recipe", "unsupported"]
    subject_name: str | None = None
    required_items: list[str] = Field(default_factory=list)
    usage: ProviderUsage


class OpenAICompatibleProvider:
    requires_preflight_hard_limit = True
    preflight_token_reserve = 16

    def __init__(
        self,
        *,
        provider_id: str,
        base_url: str,
        api_key_env_var: str,
        model: str,
        transport: httpx.BaseTransport | None = None,
        timeout_s: float = 30.0,
    ) -> None:
        self.provider = provider_id
        normalized_base_url = base_url.rstrip("/")
        if normalized_base_url != MINIMAX_OPENAI_BASE_URL:
            raise ProviderConfigurationError("provider_base_url_not_allowed")
        self.base_url = normalized_base_url
        self.api_key_env_var = api_key_env_var
        self.model = model
        self.transport = transport
        self.timeout_s = timeout_s

    def parse_state_memory_capture(
        self,
        *,
        source: StateMemoryCaptureSource,
        content: str,
    ) -> ParsedStateMemoryCapture:
        payload, usage = self._complete_json(
            system_prompt=(
                "你是状态记忆解析器。只输出 JSON。"
                "把用户输入解析成 `deltas` 和 `unrecognized`。"
                "deltas 内每项必须包含 item_name, operation, quantity, unit, category, confidence, source。"
                "operation 只能是 upsert/consume/remove。"
                "无法可靠结构化的原文片段必须放进 unrecognized。"
            ),
            user_prompt=f"source={source}\ncontent={content}",
        )
        try:
            deltas = [
                StateMemoryDelta.model_validate({**delta, "source": source})
                for delta in payload.get("deltas", [])
            ]
        except Exception as exc:  # pragma: no cover - exercised by malformed model output tests
            raise ModelResponseError("model_response_invalid", usage=usage) from exc
        unrecognized = [str(value).strip() for value in payload.get("unrecognized", []) if str(value).strip()]
        return ParsedStateMemoryCapture(deltas=deltas, unrecognized=unrecognized, usage=usage)

    def understand_state_memory_query(self, *, question: str) -> StateMemoryQueryUnderstanding:
        payload, usage = self._complete_json(
            system_prompt=(
                "你是状态记忆查询理解器。只输出 JSON。"
                "把问题分类成 have_item / missing_for_recipe / unsupported。"
                "如果是 have_item，subject_name 填物品名。"
                "如果是 missing_for_recipe，subject_name 填菜名，required_items 填所需材料数组。"
                "不要使用 category、recipe_name、ingredients 之类别名字段；"
                "必须输出 answer_type、subject_name、required_items。"
                "不要输出解释性 prose。"
            ),
            user_prompt=question,
        )
        try:
            normalized_payload = _normalize_query_understanding_payload(payload)
            return StateMemoryQueryUnderstanding.model_validate(
                {**normalized_payload, "usage": usage.model_dump(mode="json")}
            )
        except Exception as exc:  # pragma: no cover - exercised by malformed model output tests
            raise ModelResponseError("model_response_invalid", usage=usage) from exc

    def _complete_json(self, *, system_prompt: str, user_prompt: str) -> tuple[dict[str, Any], ProviderUsage]:
        response = self._post_chat_completions(
            {
                "model": self.model,
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                "response_format": {"type": "json_object"},
            }
        )
        try:
            body = response.json()
        except Exception as exc:
            raise ModelResponseError("model_response_invalid") from exc
        usage = _usage_from_body(body)
        try:
            content = _message_content(body["choices"][0]["message"]["content"])
        except Exception as exc:
            raise ModelResponseError(
                "model_response_invalid",
                usage=usage or _estimated_usage(fallback_input=user_prompt, fallback_output=""),
            ) from exc
        try:
            payload = json.loads(_extract_json_object_text(content))
        except Exception as exc:
            raise ModelResponseError(
                "model_response_invalid",
                usage=usage or _estimated_usage(fallback_input=user_prompt, fallback_output=content),
            ) from exc
        return payload, usage or _estimated_usage(fallback_input=user_prompt, fallback_output=content)

    def _post_chat_completions(self, payload: dict[str, Any]) -> httpx.Response:
        api_key = os.getenv(self.api_key_env_var, "").strip()
        if not api_key:
            raise ProviderConfigurationError("provider_not_configured")
        try:
            with httpx.Client(
                base_url=self.base_url,
                headers={"Authorization": f"Bearer {api_key}"},
                timeout=self.timeout_s,
                transport=self.transport,
            ) as client:
                response = client.post("/chat/completions", json=payload)
                response.raise_for_status()
                return response
        except ProviderConfigurationError:
            raise
        except httpx.HTTPError as exc:
            raise ModelUnavailableError("model_unavailable") from exc


def _message_content(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, Sequence):
        parts: list[str] = []
        for item in content:
            if isinstance(item, dict) and item.get("type") == "text" and isinstance(item.get("text"), str):
                parts.append(item["text"])
        if parts:
            return "".join(parts)
    raise ModelResponseError("model_response_invalid")


def _usage_from_response(body: dict[str, Any], *, fallback_input: str, fallback_output: str) -> ProviderUsage:
    usage = _usage_from_body(body)
    if usage is not None:
        return usage
    return _estimated_usage(fallback_input=fallback_input, fallback_output=fallback_output)


def _usage_from_body(body: dict[str, Any]) -> ProviderUsage | None:
    usage = body.get("usage") or {}
    prompt_tokens = usage.get("prompt_tokens")
    completion_tokens = usage.get("completion_tokens")
    if isinstance(prompt_tokens, int) and isinstance(completion_tokens, int):
        return ProviderUsage(input_tokens=prompt_tokens, output_tokens=completion_tokens, estimated=False)
    return None


def _estimated_usage(*, fallback_input: str, fallback_output: str) -> ProviderUsage:
    return ProviderUsage(
        input_tokens=max(len(fallback_input), 1),
        output_tokens=max(len(fallback_output), 1),
        estimated=True,
    )


def _extract_json_object_text(content: str) -> str:
    candidates: list[str] = []
    cleaned = re.sub(r"<think\b[^>]*>.*?</think>", "", content, flags=re.IGNORECASE | re.DOTALL).strip()
    if cleaned:
        candidates.append(cleaned)
    for match in re.finditer(r"```(?:json)?\s*(.*?)```", cleaned, flags=re.IGNORECASE | re.DOTALL):
        fenced = match.group(1).strip()
        if fenced:
            candidates.append(fenced)
    for candidate in candidates:
        direct = candidate.strip()
        if direct.startswith("{") and direct.endswith("}"):
            return direct
        extracted = _first_json_object(direct)
        if extracted is not None:
            return extracted
    raise ModelResponseError("model_response_invalid")


def _first_json_object(text: str) -> str | None:
    start = text.find("{")
    while start != -1:
        depth = 0
        in_string = False
        escape = False
        for index in range(start, len(text)):
            char = text[index]
            if in_string:
                if escape:
                    escape = False
                elif char == "\\":
                    escape = True
                elif char == '"':
                    in_string = False
                continue
            if char == '"':
                in_string = True
            elif char == "{":
                depth += 1
            elif char == "}":
                depth -= 1
                if depth == 0:
                    return text[start : index + 1]
        start = text.find("{", start + 1)
    return None


def _normalize_query_understanding_payload(payload: dict[str, Any]) -> dict[str, Any]:
    normalized = dict(payload)
    if "answer_type" not in normalized and isinstance(normalized.get("category"), str):
        normalized["answer_type"] = normalized["category"].strip()
    if "subject_name" not in normalized:
        for key in ("recipe_name", "item_name", "subject"):
            value = normalized.get(key)
            if isinstance(value, str) and value.strip():
                normalized["subject_name"] = value.strip()
                break
    if "required_items" not in normalized:
        for key in ("ingredients", "materials", "items"):
            value = normalized.get(key)
            if isinstance(value, list):
                normalized["required_items"] = value
                break
    return normalized
