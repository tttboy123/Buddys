import json

import httpx
import pytest

from buddys_api.providers.openai_compatible_provider import (
    ModelResponseError,
    ModelUnavailableError,
    OpenAICompatibleProvider,
    ProviderConfigurationError,
)


def test_openai_compatible_provider_parses_capture_and_returns_usage(monkeypatch) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test-value")
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "message": {
                            "content": json.dumps(
                                {
                                    "deltas": [
                                        {
                                            "item_name": "鸡蛋",
                                            "operation": "upsert",
                                            "quantity": 2,
                                            "unit": "盒",
                                            "category": "ingredient",
                                            "confidence": 0.93,
                                            "source": "voice",
                                        }
                                    ],
                                    "unrecognized": ["一包面粉"],
                                },
                                ensure_ascii=False,
                            )
                        }
                    }
                ],
                "usage": {"prompt_tokens": 12, "completion_tokens": 18},
            },
        )

    provider = OpenAICompatibleProvider(
        provider_id="minimax-openai",
        base_url="https://api.minimaxi.com/v1",
        api_key_env_var="OPENAI_API_KEY",
        model="MiniMax-M3",
        transport=httpx.MockTransport(handler),
    )

    result = provider.parse_state_memory_capture(source="voice", content="我买了两盒鸡蛋和一包面粉")

    assert [delta.item_name for delta in result.deltas] == ["鸡蛋"]
    assert result.unrecognized == ["一包面粉"]
    assert result.usage.input_tokens == 12
    assert result.usage.output_tokens == 18
    assert requests[0].url == httpx.URL("https://api.minimaxi.com/v1/chat/completions")
    assert requests[0].headers["Authorization"] == "Bearer sk-test-value"


def test_openai_compatible_provider_sends_multimodal_photo_capture_payload(monkeypatch) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test-value")
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "message": {
                            "content": json.dumps(
                                {
                                    "deltas": [
                                        {
                                            "item_name": "牛奶",
                                            "operation": "upsert",
                                            "quantity": 2,
                                            "unit": "盒",
                                            "category": "ingredient",
                                            "confidence": 0.9,
                                            "source": "photo",
                                        }
                                    ],
                                    "unrecognized": [],
                                },
                                ensure_ascii=False,
                            )
                        }
                    }
                ],
                "usage": {"prompt_tokens": 18, "completion_tokens": 12},
            },
        )

    provider = OpenAICompatibleProvider(
        provider_id="minimax-openai",
        base_url="https://api.minimaxi.com/v1",
        api_key_env_var="OPENAI_API_KEY",
        model="MiniMax-M3",
        transport=httpx.MockTransport(handler),
    )

    result = provider.parse_state_memory_capture(
        source="photo",
        content="冰箱照片",
        image_base64="aGVsbG8=",
        image_media_type="image/png",
    )
    payload = json.loads(requests[0].content.decode("utf-8"))

    assert [delta.item_name for delta in result.deltas] == ["牛奶"]
    assert payload["messages"][1]["content"][0]["type"] == "text"
    assert "source=photo" in payload["messages"][1]["content"][0]["text"]
    assert payload["messages"][1]["content"][1] == {
        "type": "image_url",
        "image_url": {"url": "data:image/png;base64,aGVsbG8=", "detail": "default"},
    }


def test_openai_compatible_provider_understands_recipe_query(monkeypatch) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test-value")

    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "message": {
                            "content": json.dumps(
                                {
                                    "answer_type": "missing_for_recipe",
                                    "subject_name": "红烧肉",
                                    "required_items": ["五花肉", "老抽", "冰糖"],
                                },
                                ensure_ascii=False,
                            )
                        }
                    }
                ],
                "usage": {"prompt_tokens": 9, "completion_tokens": 11},
            },
        )

    provider = OpenAICompatibleProvider(
        provider_id="minimax-openai",
        base_url="https://api.minimaxi.com/v1",
        api_key_env_var="OPENAI_API_KEY",
        model="MiniMax-M3",
        transport=httpx.MockTransport(handler),
    )

    result = provider.understand_state_memory_query(question="做红烧肉还缺什么")

    assert result.answer_type == "missing_for_recipe"
    assert result.subject_name == "红烧肉"
    assert result.required_items == ["五花肉", "老抽", "冰糖"]
    assert result.usage.input_tokens == 9
    assert result.usage.output_tokens == 11


def test_openai_compatible_provider_normalizes_query_alias_fields(monkeypatch) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test-value")

    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "message": {
                            "content": json.dumps(
                                {
                                    "category": "missing_for_recipe",
                                    "recipe_name": "红烧肉",
                                    "ingredients": ["五花肉", "老抽", "冰糖"],
                                },
                                ensure_ascii=False,
                            )
                        }
                    }
                ],
                "usage": {"prompt_tokens": 9, "completion_tokens": 11},
            },
        )

    provider = OpenAICompatibleProvider(
        provider_id="minimax-openai",
        base_url="https://api.minimaxi.com/v1",
        api_key_env_var="OPENAI_API_KEY",
        model="MiniMax-M3",
        transport=httpx.MockTransport(handler),
    )

    result = provider.understand_state_memory_query(question="做红烧肉还缺什么")

    assert result.answer_type == "missing_for_recipe"
    assert result.subject_name == "红烧肉"
    assert result.required_items == ["五花肉", "老抽", "冰糖"]


def test_openai_compatible_provider_extracts_json_from_think_and_fenced_output(monkeypatch) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test-value")

    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "message": {
                            "content": (
                                "<think>先思考一下怎么抽取结构化结果</think>\n"
                                "```json\n"
                                '{"deltas":[{"item_name":"鸡蛋","operation":"upsert","quantity":2,"unit":"盒","category":"ingredient","confidence":0.93,"source":"voice"}],"unrecognized":["一包面粉"]}\n'
                                "```"
                            )
                        }
                    }
                ],
                "usage": {"prompt_tokens": 12, "completion_tokens": 18},
            },
        )

    provider = OpenAICompatibleProvider(
        provider_id="minimax-openai",
        base_url="https://api.minimaxi.com/v1",
        api_key_env_var="OPENAI_API_KEY",
        model="MiniMax-M3",
        transport=httpx.MockTransport(handler),
    )

    result = provider.parse_state_memory_capture(source="voice", content="我买了两盒鸡蛋和一包面粉")

    assert [delta.item_name for delta in result.deltas] == ["鸡蛋"]
    assert result.unrecognized == ["一包面粉"]


def test_openai_compatible_provider_overrides_model_generated_capture_source(monkeypatch) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test-value")

    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "message": {
                            "content": json.dumps(
                                {
                                    "deltas": [
                                        {
                                            "item_name": "鸡蛋",
                                            "operation": "upsert",
                                            "quantity": 2,
                                            "unit": "盒",
                                            "category": "ingredient",
                                            "confidence": 0.93,
                                            "source": "两盒鸡蛋",
                                        }
                                    ],
                                    "unrecognized": [],
                                },
                                ensure_ascii=False,
                            )
                        }
                    }
                ],
                "usage": {"prompt_tokens": 12, "completion_tokens": 18},
            },
        )

    provider = OpenAICompatibleProvider(
        provider_id="minimax-openai",
        base_url="https://api.minimaxi.com/v1",
        api_key_env_var="OPENAI_API_KEY",
        model="MiniMax-M3",
        transport=httpx.MockTransport(handler),
    )

    result = provider.parse_state_memory_capture(source="voice", content="两盒鸡蛋和一斤五花肉")

    assert [delta.source for delta in result.deltas] == ["voice"]


def test_openai_compatible_provider_normalizes_empty_unit_to_none(monkeypatch) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test-value")

    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "message": {
                            "content": json.dumps(
                                {
                                    "deltas": [
                                        {
                                            "item_name": "鸡蛋",
                                            "operation": "upsert",
                                            "quantity": 2,
                                            "unit": "",
                                            "category": "ingredient",
                                            "confidence": 0.93,
                                            "source": "voice",
                                        }
                                    ],
                                    "unrecognized": [],
                                },
                                ensure_ascii=False,
                            )
                        }
                    }
                ],
                "usage": {"prompt_tokens": 12, "completion_tokens": 18},
            },
        )

    provider = OpenAICompatibleProvider(
        provider_id="minimax-openai",
        base_url="https://api.minimaxi.com/v1",
        api_key_env_var="OPENAI_API_KEY",
        model="MiniMax-M3",
        transport=httpx.MockTransport(handler),
    )

    result = provider.parse_state_memory_capture(source="voice", content="我买了两盒鸡蛋")

    assert result.deltas[0].unit is None


def test_openai_compatible_provider_normalizes_null_required_items_to_empty_list(monkeypatch) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test-value")

    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "message": {
                            "content": json.dumps(
                                {
                                    "answer_type": "have_item",
                                    "subject_name": "鸡蛋",
                                    "required_items": None,
                                },
                                ensure_ascii=False,
                            )
                        }
                    }
                ],
                "usage": {"prompt_tokens": 9, "completion_tokens": 11},
            },
        )

    provider = OpenAICompatibleProvider(
        provider_id="minimax-openai",
        base_url="https://api.minimaxi.com/v1",
        api_key_env_var="OPENAI_API_KEY",
        model="MiniMax-M3",
        transport=httpx.MockTransport(handler),
    )

    result = provider.understand_state_memory_query(question="家里还有鸡蛋吗")

    assert result.required_items == []


def test_openai_compatible_provider_raises_typed_error_for_malformed_json(monkeypatch) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test-value")

    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={"choices": [{"message": {"content": "not-json"}}], "usage": {"prompt_tokens": 1, "completion_tokens": 1}},
        )

    provider = OpenAICompatibleProvider(
        provider_id="minimax-openai",
        base_url="https://api.minimaxi.com/v1",
        api_key_env_var="OPENAI_API_KEY",
        model="MiniMax-M3",
        transport=httpx.MockTransport(handler),
    )

    with pytest.raises(ModelResponseError, match="model_response_invalid"):
        provider.parse_state_memory_capture(source="voice", content="我买了鸡蛋")


def test_openai_compatible_provider_malformed_json_error_keeps_usage(monkeypatch) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test-value")

    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={"choices": [{"message": {"content": "not-json"}}], "usage": {"prompt_tokens": 7, "completion_tokens": 9}},
        )

    provider = OpenAICompatibleProvider(
        provider_id="minimax-openai",
        base_url="https://api.minimaxi.com/v1",
        api_key_env_var="OPENAI_API_KEY",
        model="MiniMax-M3",
        transport=httpx.MockTransport(handler),
    )

    with pytest.raises(ModelResponseError) as exc_info:
        provider.parse_state_memory_capture(source="voice", content="我买了鸡蛋")

    assert exc_info.value.code == "model_response_invalid"
    assert exc_info.value.usage is not None
    assert exc_info.value.usage.input_tokens == 7
    assert exc_info.value.usage.output_tokens == 9


def test_openai_compatible_provider_raises_typed_error_for_transport_failure(monkeypatch) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test-value")

    def handler(_: httpx.Request) -> httpx.Response:
        raise httpx.ConnectTimeout("timeout")

    provider = OpenAICompatibleProvider(
        provider_id="minimax-openai",
        base_url="https://api.minimaxi.com/v1",
        api_key_env_var="OPENAI_API_KEY",
        model="MiniMax-M3",
        transport=httpx.MockTransport(handler),
    )

    with pytest.raises(ModelUnavailableError, match="model_unavailable"):
        provider.understand_state_memory_query(question="有鸡蛋吗")


def test_openai_compatible_provider_requires_non_empty_api_key_env_var(monkeypatch) -> None:
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    provider = OpenAICompatibleProvider(
        provider_id="minimax-openai",
        base_url="https://api.minimaxi.com/v1",
        api_key_env_var="OPENAI_API_KEY",
        model="MiniMax-M3",
    )

    with pytest.raises(ProviderConfigurationError, match="provider_not_configured"):
        provider.parse_state_memory_capture(source="voice", content="我买了鸡蛋")
