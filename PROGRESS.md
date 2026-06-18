# Buddys Runtime MVP Progress

Date: 2026-06-18
Status: P0 runtime MVP verified locally, with manual fallback, and backed up to GitHub

## Summary

The first Buddys runtime code workspace is implemented in this repository. It proves the P0 "Home Buddy dims living room light" loop:

```text
Create Home Buddy
 -> submit "把客厅灯调暗"
 -> mock provider creates an ActionProposal
 -> A-level policy requires confirmation
 -> user approves proposal
 -> mock_home adapter executes set_brightness or returns manual_required when control is unavailable
 -> runtime records ActionTrace and CostEvent
 -> FastAPI exposes trace and cost data
```

## Implemented

- Pydantic schemas for Buddy, ActionProposal, PermissionDecision, ToolCall, ToolResult, ActionTrace, and CostEvent.
- A-level confirm-before-action policy.
- Deterministic mock provider for light, climate, scene, and reply-only flows.
- Mock Home adapter for light brightness, climate temperature, and scene activation.
- Manual fallback for unavailable device control:
  - `ToolResult.status = manual_required`
  - `user_instruction` for Console/device display
  - `voice_prompt` for future TTS/device speaker output
  - `proposal.executed` remains `false`
- In-memory TraceStore and CostMeter.
- Runtime orchestration for creating buddies, submitting messages, and confirming proposals.
- FastAPI API surface:
  - `GET /healthz`
  - `POST /buddies`
  - `GET /buddies/{buddy_id}`
  - `POST /buddies/{buddy_id}/messages`
  - `POST /proposals/{proposal_id}/confirm`
  - `GET /traces/{trace_id}`
  - `GET /cost-events`
- Runtime config:
  - `BUDDYS_MOCK_CAN_CONTROL_DEVICES=false` makes the default API app simulate unavailable device control.
- Golden trace verification for approved dim-light flow.

## Verification

Latest local verification:

```bash
.venv/bin/python -m pytest -q
```

Result:

```text
32 passed, 1 warning in 0.17s
```

HTTP smoke result:

```text
health={"status":"ok"}
trace_intent=adjust_light
trace_tool_result=success
trace_cost_refs=1
cost_count=1
```

The remaining warning is a FastAPI/Starlette TestClient upstream deprecation warning for `httpx`.

Manual fallback verified path:

```text
approved action
 -> MockHomeAdapter(can_control_devices=False)
 -> ToolResult.status=manual_required
 -> user_instruction="请手动把客厅灯调暗到约 35%。"
 -> voice_prompt="我现在无法直接控制客厅灯。请手动把客厅灯调暗到约 35%，完成后可以告诉我。"
 -> proposal.executed=false
```

Manual fallback HTTP smoke:

```text
BUDDYS_MOCK_CAN_CONTROL_DEVICES=false
health={"status":"ok"}
confirm_tool_status=manual_required
confirm_instruction=请手动把客厅灯调暗到约 35%。
trace_executed=False
trace_voice_prompt=我现在无法直接控制客厅灯。请手动把客厅灯调暗到约 35%，完成后可以告诉我。
```

## Current Limitations

- No real Home Assistant, Matter, Mijia, Apple Home, Google Home, or vehicle adapter yet.
- No real TTS playback yet; `voice_prompt` is data-level output only.
- No auth, billing, BYOK, subscriptions, or production key storage.
- No B/C autonomy.
- No durable database yet.
- No TypeScript console yet.

## GitHub

Remote repository:

```text
git@github.com:tttboy123/Buddys.git
https://github.com/tttboy123/Buddys
```

The remote includes the GitHub-created MIT `LICENSE`, merged into the local history before push.

## Next Steps

1. Replace in-memory stores with SQLite-backed repositories.
2. Add a minimal Console UI for the same dim-light demo flow.
3. Add Home Assistant adapter spike behind the existing ToolCall boundary.
4. Add auth/BYOK/cost guardrails after the local trace/cost contract stabilizes.
