# Buddys Manual Fallback Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a manual fallback path so Buddys gives explicit user instructions when a device action cannot be executed directly.

**Architecture:** Extend `ToolResult` with `manual_required`, `user_instruction`, and `voice_prompt`. Keep runtime orchestration unchanged except for execution bookkeeping: only `success` sets `proposal.executed = true`; `manual_required` is recorded in trace and returned through API.

**Tech Stack:** Python, FastAPI, Pydantic, pytest.

---

## Files

- Modify: `/Users/lune/Documents/Codex/2026-06-18/hermes-openclaw/outputs/buddys/src/buddys_api/schemas.py`
- Modify: `/Users/lune/Documents/Codex/2026-06-18/hermes-openclaw/outputs/buddys/src/buddys_api/adapters/mock_home.py`
- Modify: `/Users/lune/Documents/Codex/2026-06-18/hermes-openclaw/outputs/buddys/tests/contract/test_schemas.py`
- Modify: `/Users/lune/Documents/Codex/2026-06-18/hermes-openclaw/outputs/buddys/tests/unit/test_mock_home.py`
- Modify: `/Users/lune/Documents/Codex/2026-06-18/hermes-openclaw/outputs/buddys/tests/integration/test_runtime_flow.py`
- Modify: `/Users/lune/Documents/Codex/2026-06-18/hermes-openclaw/outputs/buddys/tests/integration/test_api_flow.py`
- Modify: `/Users/lune/Documents/Codex/2026-06-18/hermes-openclaw/outputs/buddys/tests/golden/test_golden_trace.py`
- Modify: `/Users/lune/Documents/Codex/2026-06-18/hermes-openclaw/outputs/buddys/PROGRESS.md`

### Task 1: Schema Contract

- [ ] **Step 1: Write the failing schema test**

Add this test to `tests/contract/test_schemas.py`:

```python
def test_tool_result_can_request_manual_user_action():
    result = ToolResult(
        status="manual_required",
        output_summary="Adapter cannot control living room light.",
        error_code="adapter_unavailable",
        user_instruction="请手动把客厅灯调暗到约 35%。",
        voice_prompt="我现在无法直接控制客厅灯。请手动把客厅灯调暗到约 35%，完成后可以告诉我。",
    )

    assert result.status == "manual_required"
    assert "手动" in result.user_instruction
    assert result.voice_prompt.startswith("我现在无法直接控制")
```

- [ ] **Step 2: Verify red**

Run:

```bash
cd /Users/lune/Documents/Codex/2026-06-18/hermes-openclaw/outputs/buddys
.venv/bin/python -m pytest tests/contract/test_schemas.py::test_tool_result_can_request_manual_user_action -q
```

Expected: fail because `ToolResult` is not imported or does not accept `manual_required` / prompt fields.

- [ ] **Step 3: Implement schema**

In `src/buddys_api/schemas.py`, update `ToolResult`:

```python
class ToolResult(BaseModel):
    status: Literal["success", "failure", "skipped", "manual_required"]
    output_summary: str
    error_code: str | None = None
    latency_ms: int | None = None
    user_instruction: str | None = None
    voice_prompt: str | None = None
```

- [ ] **Step 4: Verify green**

Run the same targeted test. Expected: pass.

### Task 2: Adapter Fallback

- [ ] **Step 1: Write failing adapter test**

Add this test to `tests/unit/test_mock_home.py`:

```python
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
```

- [ ] **Step 2: Verify red**

Run:

```bash
.venv/bin/python -m pytest tests/unit/test_mock_home.py::test_mock_home_returns_manual_instruction_when_device_control_is_unavailable -q
```

Expected: fail because `MockHomeAdapter` does not accept `can_control_devices`.

- [ ] **Step 3: Implement adapter fallback**

Add `__init__` to `MockHomeAdapter`, store `can_control_devices`, and return `manual_required` from `_set_brightness` before validating success when device control is disabled.

- [ ] **Step 4: Verify green**

Run the targeted adapter test. Expected: pass.

### Task 3: Runtime And API Trace Behavior

- [ ] **Step 1: Write failing runtime/API/golden tests**

Add tests that instantiate `BuddysRuntime(adapter=MockHomeAdapter(can_control_devices=False))`, approve the proposal, and assert:

```python
assert trace.proposal.executed is False
assert trace.tool_result.status == "manual_required"
assert trace.tool_result.user_instruction == "请手动把客厅灯调暗到约 35%。"
```

In API tests, create the app with that runtime and assert the confirm response returns `manual_required`.

- [ ] **Step 2: Verify red**

Run the targeted runtime/API tests. Expected: fail until schema/adapter changes are wired and imports are fixed.

- [ ] **Step 3: Implement minimal runtime support**

No new runtime branch should be needed if `proposal.executed = tool_result.status == "success"` remains unchanged. Fix only what fails.

- [ ] **Step 4: Verify green**

Run:

```bash
.venv/bin/python -m pytest tests/integration/test_runtime_flow.py tests/integration/test_api_flow.py tests/golden/test_golden_trace.py -q
```

Expected: pass.

### Task 4: Documentation, Verification, Commit

- [ ] **Step 1: Update `PROGRESS.md`**

Add manual fallback to implemented scope and verification notes.

- [ ] **Step 2: Run full verification**

Run:

```bash
.venv/bin/python -m pytest -q
```

Expected: all tests pass, with only the known FastAPI/Starlette TestClient warning.

- [ ] **Step 3: Commit and push**

Run:

```bash
git add src tests PROGRESS.md
git commit -m "feat: add manual fallback for unavailable device control"
git push
```

Expected: remote `main` updates successfully.

## Self-Review

- Spec coverage: schema, adapter, runtime trace, API response, golden path, and docs are covered.
- Placeholder scan: no placeholder task remains.
- Type consistency: the plan uses existing `ToolResult`, `MockHomeAdapter`, `BuddysRuntime`, and pytest patterns.
