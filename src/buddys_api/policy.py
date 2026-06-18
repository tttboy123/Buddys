from __future__ import annotations

from typing import Literal

from buddys_api.schemas import ActionProposal, PermissionDecision


Confirmation = Literal["approved", "rejected"] | None


class PermissionPolicy:
    policy_version = "p0-a-level-v1"

    def evaluate(self, proposal: ActionProposal, user_confirmation: Confirmation) -> PermissionDecision:
        if proposal.action_type != "tool_call":
            return PermissionDecision(
                policy_result="not_required",
                confirmation_result="not_requested",
                decided_by="policy",
                reason="No device action requires confirmation.",
                policy_version=self.policy_version,
            )

        if proposal.risk_level == "high":
            return PermissionDecision(
                policy_result="deny",
                confirmation_result=user_confirmation or "not_requested",
                decided_by="policy",
                reason="High-risk actions are disabled in Alpha.",
                policy_version=self.policy_version,
            )

        if proposal.executed:
            return PermissionDecision(
                policy_result="deny",
                confirmation_result=user_confirmation or "not_requested",
                decided_by="policy",
                reason="Proposal already executed.",
                policy_version=self.policy_version,
            )

        if user_confirmation == "rejected":
            return PermissionDecision(
                policy_result="deny",
                confirmation_result="rejected",
                decided_by="user",
                reason="User rejected the action.",
                policy_version=self.policy_version,
            )

        if user_confirmation == "approved":
            return PermissionDecision(
                policy_result="allow",
                confirmation_result="approved",
                decided_by="user",
                reason="User approved the A-level device action.",
                policy_version=self.policy_version,
            )

        return PermissionDecision(
            policy_result="require_confirmation",
            confirmation_result="not_requested",
            decided_by="policy",
            reason="A-level device action requires confirmation.",
            policy_version=self.policy_version,
        )
