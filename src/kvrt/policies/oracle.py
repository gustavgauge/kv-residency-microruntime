"""Offline complete-prefix oracle over the MVP action space."""

from __future__ import annotations

from .base import BasePolicy, accept_leading, refuse
from kvrt.model import ClaimDecision, Prefix, PrefixTruth, ResidencyClaim, RuntimeState


class CompletePrefixOraclePolicy(BasePolicy):
    name = "complete_prefix_oracle"
    admissible_fields = {"offline_truth"}
    is_oracle = True

    def __init__(self, truths: dict[str, PrefixTruth] | None = None) -> None:
        self.truths = truths or {}

    def plan_claims(
        self,
        state: RuntimeState,
        prefixes: dict[str, Prefix],
        claims: list[ResidencyClaim],
    ) -> list[ClaimDecision]:
        candidates: list[tuple[ResidencyClaim, Prefix, int, float]] = []
        for claim in claims:
            prefix = prefixes[claim.prefix_id]
            useful_blocks = prefix.threshold_blocks
            if useful_blocks <= prefix.block_count:
                truth = self.truths.get(prefix.prefix_id)
                value = truth.true_value if truth is not None else prefix.full_reuse_value
                candidates.append((claim, prefix, useful_blocks, value))

        best_value = -1.0
        best_mask = 0
        for mask in range(1 << len(candidates)):
            total_blocks = 0
            total_value = 0.0
            for idx, (_claim, _prefix, useful_blocks, value) in enumerate(candidates):
                if mask & (1 << idx):
                    total_blocks += useful_blocks
                    total_value += value
            if total_blocks <= state.capacity_blocks and total_value > best_value:
                best_value = total_value
                best_mask = mask

        selected = {
            candidates[idx][0].claim_id
            for idx in range(len(candidates))
            if best_mask & (1 << idx)
        }
        useful_by_claim = {
            claim.claim_id: (prefix, useful_blocks, value)
            for claim, prefix, useful_blocks, value in candidates
        }

        decisions: list[ClaimDecision] = []
        for claim in claims:
            if claim.claim_id in selected:
                prefix, useful_blocks, value = useful_by_claim[claim.claim_id]
                decisions.append(
                    accept_leading(
                        claim,
                        policy_name=self.name,
                        state=state,
                        accepted_blocks=useful_blocks,
                        score=value,
                        reasons=["oracle_complete_prefix"],
                        used_fields={"offline_truth": "audit_only"},
                        prefix=prefix,
                    )
                )
            else:
                decisions.append(
                    refuse(
                        claim,
                        policy_name=self.name,
                        state=state,
                        reason="oracle_not_selected",
                        used_fields={"offline_truth": "audit_only"},
                    )
                )
        return decisions


class AbstractBlockOraclePolicy(BasePolicy):
    """Offline oracle for abstract block-value scoring."""

    name = "abstract_block_oracle"
    admissible_fields = {"offline_truth"}
    is_oracle = True

    def plan_claims(
        self,
        state: RuntimeState,
        prefixes: dict[str, Prefix],
        claims: list[ResidencyClaim],
    ) -> list[ClaimDecision]:
        remaining = state.capacity_blocks
        ranked: list[tuple[float, ResidencyClaim, Prefix]] = []
        for claim in claims:
            prefix = prefixes[claim.prefix_id]
            density = prefix.full_reuse_value / max(prefix.block_count, 1)
            ranked.append((density, claim, prefix))

        decisions: dict[str, ClaimDecision] = {}
        for density, claim, prefix in sorted(
            ranked, key=lambda item: (-item[0], item[1].claim_id)
        ):
            accepted = min(prefix.block_count, remaining)
            remaining -= accepted
            if accepted > 0:
                decisions[claim.claim_id] = accept_leading(
                    claim,
                    policy_name=self.name,
                    state=state,
                    accepted_blocks=accepted,
                    score=density,
                    reasons=["oracle_abstract_block_value"],
                    used_fields={"offline_truth": "audit_only"},
                    prefix=prefix,
                )
            else:
                decisions[claim.claim_id] = refuse(
                    claim,
                    policy_name=self.name,
                    state=state,
                    reason="oracle_not_selected",
                    used_fields={"offline_truth": "audit_only"},
                    score=density,
                )

        return [decisions[claim.claim_id] for claim in claims]
