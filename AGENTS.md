# Buddys Runtime Workspace Rules

This folder is the code workspace for Buddys runtime implementation.

## Mandatory Preflight

Before any development, implementation planning, schema work, adapter work, API work, test work, or agent dispatch, read these files in order:

1. `../space-agent-startup-docs/README.md`
2. `../space-agent-startup-docs/17-agent-context-map.md`
3. `../space-agent-startup-docs/RD-LOOP.md`
4. `../space-agent-startup-docs/RD-STATE.md`
5. `../space-agent-startup-docs/buddys-loop-registry.yaml`
6. `../space-agent-startup-docs/rd-loop-budget.md`
7. `../space-agent-startup-docs/rd-loop-run-log.md`
8. The task-specific design/plan document under `../space-agent-startup-docs/docs/superpowers/`

## Execution Rules

- Use `dispatching-parallel-agents` when there are two or more independent tasks.
- Use `subagent-driven-development` for implementation plans with multiple steps.
- Use `writing-plans` before any code implementation if no plan exists.
- Use `test-driven-development` before writing runtime, schema, policy, adapter, provider, or API code.
- Use `verification-before-completion` before claiming completion.

## Agent Boundaries

- The main agent acts as coordinator, not as the default implementer.
- Each independent task gets a fresh implementer subagent.
- Spec review happens before code quality review.
- Do not let one subagent broaden scope into unrelated tasks.
- Do not let the main agent directly consume the whole implementation chain when subagents are appropriate.

## Loop Rules

- Follow the Buddys RD Loop contract.
- Append to `../space-agent-startup-docs/rd-loop-run-log.md` after meaningful planning or implementation runs.
- Update `../space-agent-startup-docs/RD-STATE.md` when priorities or blockers change.
- Respect `loop_pause_all` and all human gates.

## Repository Rules

- Keep implementation focused on the current task.
- Do not revert unrelated user changes.
- Do not use destructive git commands unless explicitly requested.
- Do not claim implementation is done without fresh verification.
