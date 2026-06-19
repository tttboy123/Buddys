from __future__ import annotations

import os

import pytest

from buddys_api.providers.openai_compatible_provider import OpenAICompatibleProvider


RUN_REAL_EVALS = os.getenv("BUDDYS_RUN_REAL_MODEL_EVALS", "").strip() == "1"


@pytest.mark.skipif(not RUN_REAL_EVALS, reason="set BUDDYS_RUN_REAL_MODEL_EVALS=1 to run live MiniMax evals")
@pytest.mark.parametrize(
    ("mode", "input_text", "expected"),
    [
        ("capture", "两盒鸡蛋和一斤五花肉", {"item_names": ["鸡蛋", "五花肉"]}),
        ("capture", "一包面粉", {"item_names_any_of": ["面粉"], "unrecognized_contains": "一包面粉"}),
        ("query", "做红烧肉还缺什么", {"answer_type": "missing_for_recipe", "subject_name": "红烧肉"}),
    ],
)
def test_state_memory_real_model_eval_cases(mode: str, input_text: str, expected: dict[str, object]) -> None:
    provider = OpenAICompatibleProvider(
        provider_id="minimax-openai",
        base_url="https://api.minimaxi.com/v1",
        api_key_env_var="OPENAI_API_KEY",
        model="MiniMax-M3",
    )

    if mode == "capture":
        result = provider.parse_state_memory_capture(source="voice", content=input_text)
        if "item_names" in expected:
            assert [delta.item_name for delta in result.deltas] == expected["item_names"]
        if "item_names_any_of" in expected:
            item_names = [delta.item_name for delta in result.deltas]
            if not any(name in item_names for name in expected["item_names_any_of"]):
                assert expected["unrecognized_contains"] in result.unrecognized
                return
        if "unrecognized_contains" in expected and "item_names_any_of" not in expected:
            assert expected["unrecognized_contains"] in result.unrecognized
        return

    result = provider.understand_state_memory_query(question=input_text)
    assert result.answer_type == expected["answer_type"]
    assert result.subject_name == expected["subject_name"]
