# Buddys Manual Fallback Design

Date: 2026-06-18
Status: approved for implementation

## Goal

When Buddys cannot directly operate a device, it must tell the user how to complete the action manually instead of silently failing or pretending success.

## Product Rule

Manual fallback is part of the safety model:

```text
confirmed action
 -> adapter cannot perform it
 -> trace records manual_required
 -> user_instruction and voice_prompt are generated
 -> proposal.executed remains false
```

The user-facing wording must be explicit. For the first light-control fallback:

```text
我现在无法直接控制客厅灯。请手动把客厅灯调暗到约 35%，完成后可以告诉我。
```

## Runtime Contract

`ToolResult.status` gains a fourth value:

```text
success | failure | skipped | manual_required
```

`ToolResult` gains two optional fields:

```text
user_instruction: str | None
voice_prompt: str | None
```

`manual_required` means:

- The requested action was understood.
- User approval was received if the action required confirmation.
- The adapter could not safely execute the action.
- Buddys has given the user a concrete manual action.
- The action is not considered executed by the system.

## Adapter Behavior

The P0 mock adapter remains the default success adapter. To test fallback without real hardware, `MockHomeAdapter` accepts a flag:

```python
MockHomeAdapter(can_control_devices=False)
```

When `can_control_devices=False`, light brightness actions return `manual_required` with both `user_instruction` and `voice_prompt`. The adapter does not mutate device state.

## API Behavior

`POST /proposals/{proposal_id}/confirm` returns the `ToolResult` as before. A fallback result is visible to the Console through:

```json
{
  "tool_result": {
    "status": "manual_required",
    "user_instruction": "...",
    "voice_prompt": "..."
  }
}
```

The trace endpoint must preserve the same data for review and later regression cases.

## Testing

Tests must prove:

- `ToolResult` accepts `manual_required` and prompt fields.
- Offline/uncontrollable adapter returns `manual_required`.
- Runtime does not mark the proposal as executed for manual fallback.
- API response exposes the manual instruction.
- A golden trace covers the manual fallback path.

## Out Of Scope

- Real TTS audio generation.
- Device speaker playback.
- Home Assistant adapter implementation.
- User confirmation of whether the manual action was actually completed.
