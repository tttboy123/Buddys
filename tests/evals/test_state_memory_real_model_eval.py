from __future__ import annotations

import base64
import os
import struct
import zlib
from dataclasses import dataclass

import pytest
from fastapi.testclient import TestClient

from buddys_api.main import create_app
from buddys_api.providers.openai_compatible_provider import OpenAICompatibleProvider


RUN_REAL_EVALS = os.getenv("BUDDYS_RUN_REAL_MODEL_EVALS", "").strip() == "1"


@dataclass(frozen=True)
class CaptureEvalCase:
    input_text: str
    expected_item_alias_groups: tuple[tuple[str, ...], ...]
    fallback_unrecognized_contains: str | None = None


@dataclass(frozen=True)
class QueryUnderstandingEvalCase:
    input_text: str
    expected_answer_type: str
    subject_aliases: tuple[str, ...]
    required_item_alias_groups: tuple[tuple[str, ...], ...] = ()


@dataclass(frozen=True)
class ServiceQueryEvalCase:
    case_id: str
    inventory_items: tuple[str, ...]
    question: str
    expected_answer_type: str
    expected_has_item: bool | None = None
    expected_evidence_alias_groups: tuple[tuple[str, ...], ...] = ()
    forbidden_missing_alias_groups: tuple[tuple[str, ...], ...] = ()
    expected_missing_alias_groups: tuple[tuple[str, ...], ...] = ()


def _sample_eval_png_base64() -> str:
    def chunk(tag: bytes, data: bytes) -> bytes:
        return (
            struct.pack("!I", len(data))
            + tag
            + data
            + struct.pack("!I", zlib.crc32(tag + data) & 0xFFFFFFFF)
        )

    width = 64
    height = 64
    rows: list[bytes] = []
    for y in range(height):
        row = bytearray([0])
        for x in range(width):
            row.extend(((x * 4) % 256, (y * 4) % 256, 128))
        rows.append(bytes(row))
    image = (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack("!IIBBBBB", width, height, 8, 2, 0, 0, 0))
        + chunk(b"IDAT", zlib.compress(b"".join(rows), 9))
        + chunk(b"IEND", b"")
    )
    return base64.b64encode(image).decode("ascii")


SAMPLE_PNG_BASE64 = _sample_eval_png_base64()


CAPTURE_EVAL_CASES: tuple[CaptureEvalCase, ...] = (
    CaptureEvalCase("两盒鸡蛋和一斤五花肉", (("鸡蛋",), ("五花肉", "猪肉"))),
    CaptureEvalCase("3瓶可乐和2袋薯片", (("可乐",), ("薯片",))),
    CaptureEvalCase("一箱牛奶", (("牛奶",),)),
    CaptureEvalCase("一包面粉", (("面粉",),), fallback_unrecognized_contains="一包面粉"),
    CaptureEvalCase("一袋大米和半瓶生抽", (("大米",), ("生抽",))),
    CaptureEvalCase("两个番茄和六个鸡蛋", (("番茄", "西红柿"), ("鸡蛋",))),
    CaptureEvalCase("一盒豆腐一把小葱", (("豆腐",), ("小葱",))),
    CaptureEvalCase("一瓶橄榄油和一袋盐", (("橄榄油",), ("盐",))),
    CaptureEvalCase("一包意面和一罐番茄酱", (("意面",), ("番茄酱",))),
    CaptureEvalCase("买了苹果和香蕉", (("苹果",), ("香蕉",))),
    CaptureEvalCase("冰箱里还有酸奶和黄油", (("酸奶",), ("黄油",))),
    CaptureEvalCase("一盒培根和一袋芝士碎", (("培根",), ("芝士碎", "奶酪碎"))),
)

QUERY_UNDERSTANDING_EVAL_CASES: tuple[QueryUnderstandingEvalCase, ...] = (
    QueryUnderstandingEvalCase(
        "做红烧肉还缺什么",
        "missing_for_recipe",
        ("红烧肉",),
        required_item_alias_groups=(("五花肉", "猪肉"), ("老抽", "酱油"), ("冰糖",)),
    ),
    QueryUnderstandingEvalCase(
        "做西红柿炒蛋还缺什么",
        "missing_for_recipe",
        ("西红柿炒蛋", "番茄炒蛋"),
        required_item_alias_groups=(("鸡蛋",), ("番茄", "西红柿")),
    ),
    QueryUnderstandingEvalCase(
        "做番茄炒蛋还差什么",
        "missing_for_recipe",
        ("番茄炒蛋", "西红柿炒蛋"),
        required_item_alias_groups=(("鸡蛋",), ("番茄", "西红柿")),
    ),
    QueryUnderstandingEvalCase("家里还有鸡蛋吗", "have_item", ("鸡蛋",)),
    QueryUnderstandingEvalCase("还有猪肉吗", "have_item", ("猪肉", "五花肉")),
    QueryUnderstandingEvalCase("还有番茄吗", "have_item", ("番茄", "西红柿")),
    QueryUnderstandingEvalCase(
        "做土豆炖牛肉还少什么",
        "missing_for_recipe",
        ("土豆炖牛肉", "马铃薯炖牛肉"),
        required_item_alias_groups=(("土豆", "马铃薯"), ("牛肉",)),
    ),
    QueryUnderstandingEvalCase("我还有牛奶吗", "have_item", ("牛奶",)),
)

SERVICE_QUERY_EVAL_CASES: tuple[ServiceQueryEvalCase, ...] = (
    ServiceQueryEvalCase(
        case_id="pork_recipe_present",
        inventory_items=("五花肉", "老抽", "冰糖"),
        question="做红烧肉还缺什么",
        expected_answer_type="missing_for_recipe",
        expected_evidence_alias_groups=(("五花肉",), ("老抽",), ("冰糖",)),
        forbidden_missing_alias_groups=(("猪肉", "五花肉"),),
    ),
    ServiceQueryEvalCase(
        case_id="generic_pork_have_item",
        inventory_items=("五花肉",),
        question="还有猪肉吗",
        expected_answer_type="have_item",
        expected_has_item=True,
        expected_evidence_alias_groups=(("五花肉",),),
        forbidden_missing_alias_groups=(("猪肉", "五花肉"),),
    ),
    ServiceQueryEvalCase(
        case_id="tomato_recipe_present",
        inventory_items=("番茄", "鸡蛋"),
        question="做西红柿炒蛋还缺什么",
        expected_answer_type="missing_for_recipe",
        expected_evidence_alias_groups=(("番茄", "西红柿"), ("鸡蛋",)),
        forbidden_missing_alias_groups=(("番茄", "西红柿"), ("鸡蛋",)),
    ),
    ServiceQueryEvalCase(
        case_id="tomato_have_item_alias",
        inventory_items=("西红柿",),
        question="还有番茄吗",
        expected_answer_type="have_item",
        expected_has_item=True,
        expected_evidence_alias_groups=(("番茄", "西红柿"),),
        forbidden_missing_alias_groups=(("番茄", "西红柿"),),
    ),
    ServiceQueryEvalCase(
        case_id="potato_have_item_alias",
        inventory_items=("马铃薯",),
        question="还有土豆吗",
        expected_answer_type="have_item",
        expected_has_item=True,
        expected_evidence_alias_groups=(("土豆", "马铃薯"),),
        forbidden_missing_alias_groups=(("土豆", "马铃薯"),),
    ),
    ServiceQueryEvalCase(
        case_id="potato_beef_recipe_present",
        inventory_items=("土豆", "牛肉"),
        question="做土豆炖牛肉还缺什么",
        expected_answer_type="missing_for_recipe",
        expected_evidence_alias_groups=(("土豆", "马铃薯"), ("牛肉",)),
        forbidden_missing_alias_groups=(("土豆", "马铃薯"), ("牛肉",)),
    ),
    ServiceQueryEvalCase(
        case_id="exact_have_item_present",
        inventory_items=("鸡蛋",),
        question="家里还有鸡蛋吗",
        expected_answer_type="have_item",
        expected_has_item=True,
        expected_evidence_alias_groups=(("鸡蛋",),),
        forbidden_missing_alias_groups=(("鸡蛋",),),
    ),
    ServiceQueryEvalCase(
        case_id="exact_have_item_absent",
        inventory_items=(),
        question="家里还有鸡蛋吗",
        expected_answer_type="have_item",
        expected_has_item=False,
        expected_missing_alias_groups=(("鸡蛋",),),
    ),
    ServiceQueryEvalCase(
        case_id="tomato_recipe_cross_alias",
        inventory_items=("西红柿", "鸡蛋"),
        question="做番茄炒蛋还缺什么",
        expected_answer_type="missing_for_recipe",
        expected_evidence_alias_groups=(("番茄", "西红柿"), ("鸡蛋",)),
        forbidden_missing_alias_groups=(("番茄", "西红柿"), ("鸡蛋",)),
    ),
    ServiceQueryEvalCase(
        case_id="tomato_have_item_cross_alias",
        inventory_items=("番茄",),
        question="还有西红柿吗",
        expected_answer_type="have_item",
        expected_has_item=True,
        expected_evidence_alias_groups=(("番茄", "西红柿"),),
        forbidden_missing_alias_groups=(("番茄", "西红柿"),),
    ),
)


@pytest.fixture
def real_provider() -> OpenAICompatibleProvider:
    return OpenAICompatibleProvider(
        provider_id="minimax-openai",
        base_url="https://api.minimaxi.com/v1",
        api_key_env_var="OPENAI_API_KEY",
        model="MiniMax-M3",
    )


@pytest.mark.skipif(not RUN_REAL_EVALS, reason="set BUDDYS_RUN_REAL_MODEL_EVALS=1 to run live MiniMax evals")
@pytest.mark.parametrize("case", CAPTURE_EVAL_CASES, ids=lambda case: case.input_text)
def test_state_memory_real_model_capture_eval_cases(real_provider: OpenAICompatibleProvider, case: CaptureEvalCase) -> None:
    result = real_provider.parse_state_memory_capture(source="voice", content=case.input_text)
    actual_names = [delta.item_name for delta in result.deltas]
    if case.fallback_unrecognized_contains and not _actual_names_cover_groups(actual_names, case.expected_item_alias_groups):
        assert case.fallback_unrecognized_contains in result.unrecognized
        return
    _assert_alias_groups_present(actual_names, case.expected_item_alias_groups)


@pytest.mark.skipif(not RUN_REAL_EVALS, reason="set BUDDYS_RUN_REAL_MODEL_EVALS=1 to run live MiniMax evals")
def test_state_memory_real_model_photo_capture_eval_case(real_provider: OpenAICompatibleProvider) -> None:
    result = real_provider.parse_state_memory_capture(
        source="photo",
        content="冰箱照片",
        image_base64=SAMPLE_PNG_BASE64,
        image_media_type="image/png",
    )

    assert result.usage.input_tokens > 0
    assert result.usage.output_tokens > 0


@pytest.mark.skipif(not RUN_REAL_EVALS, reason="set BUDDYS_RUN_REAL_MODEL_EVALS=1 to run live MiniMax evals")
@pytest.mark.parametrize("case", QUERY_UNDERSTANDING_EVAL_CASES, ids=lambda case: case.input_text)
def test_state_memory_real_model_query_understanding_eval_cases(
    real_provider: OpenAICompatibleProvider,
    case: QueryUnderstandingEvalCase,
) -> None:
    result = real_provider.understand_state_memory_query(question=case.input_text)
    assert result.answer_type == case.expected_answer_type
    assert result.subject_name in case.subject_aliases
    _assert_alias_groups_present(result.required_items, case.required_item_alias_groups)


@pytest.mark.skipif(not RUN_REAL_EVALS, reason="set BUDDYS_RUN_REAL_MODEL_EVALS=1 to run live MiniMax evals")
@pytest.mark.parametrize("case", SERVICE_QUERY_EVAL_CASES, ids=lambda case: case.case_id)
def test_state_memory_real_model_service_query_eval_cases(tmp_path, case: ServiceQueryEvalCase) -> None:
    app = create_app(db_path=tmp_path / f"{case.case_id}.sqlite3")
    client = TestClient(app)
    token = _register(client, email=f"{case.case_id}@example.com")
    buddy = client.post(
        "/me/buddies",
        headers={"Authorization": f"Bearer {token}"},
        json={"name": "Kitchen Buddy", "space_id": "kitchen"},
    ).json()
    provider_response = client.post(
        "/providers",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "provider_id": "minimax-openai",
            "display_name": "MiniMax OpenAI Compatible",
            "provider_type": "openai_compatible",
            "base_url": "https://api.minimaxi.com/v1",
            "api_key_env_var": "OPENAI_API_KEY",
            "default_model": "MiniMax-M3",
        },
    )
    assert provider_response.status_code == 200

    for item_name in case.inventory_items:
        app.state.state_memory_store.create_item(
            user_id=buddy["user_id"],
            buddy_id=buddy["buddy_id"],
            name=item_name,
            category="ingredient",
            quantity=1,
            unit="份",
            source="manual",
            confidence=1.0,
        )

    response = client.post(
        f"/me/buddies/{buddy['buddy_id']}/state-memory/query",
        headers={"Authorization": f"Bearer {token}"},
        json={"question": case.question},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["answer_type"] == case.expected_answer_type
    if case.expected_has_item is not None:
        assert body["has_item"] is case.expected_has_item
    evidence_names = [item["name"] for item in body["evidence_items"]]
    _assert_alias_groups_present(evidence_names, case.expected_evidence_alias_groups)
    _assert_no_alias_groups_present(body["missing_items"], case.forbidden_missing_alias_groups)
    _assert_alias_groups_present(body["missing_items"], case.expected_missing_alias_groups)


def _register(client: TestClient, *, email: str) -> str:
    response = client.post(
        "/auth/register",
        json={
            "email": email,
            "password": "test-password-123",
            "display_name": "Eval User",
        },
    )
    assert response.status_code == 201
    return response.json()["access_token"]


def _actual_names_cover_groups(actual_names: list[str], expected_groups: tuple[tuple[str, ...], ...]) -> bool:
    return all(any(name in actual_names for name in group) for group in expected_groups)


def _assert_alias_groups_present(actual_names: list[str], expected_groups: tuple[tuple[str, ...], ...]) -> None:
    for group in expected_groups:
        assert any(name in actual_names for name in group), f"expected one of {group} in {actual_names}"


def _assert_no_alias_groups_present(actual_names: list[str], forbidden_groups: tuple[tuple[str, ...], ...]) -> None:
    for group in forbidden_groups:
        assert not any(name in group for name in actual_names), f"did not expect any of {group} in {actual_names}"
