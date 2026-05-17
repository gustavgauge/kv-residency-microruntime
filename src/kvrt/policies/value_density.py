"""Value-density allocation over complete leading prefix spans."""

from __future__ import annotations

from .base import BasePolicy, accept_leading, refuse
from kvrt.model import ClaimDecision, Prefix, ResidencyClaim, RuntimeState


class ValueDensityPolicy(BasePolicy):
    name = "value_density"
    admissible_fields = {
        "declared_value",
        "claimed_footprint_blocks",
        "capacity_blocks",
        "prefix_block_count",
        "useful_threshold_blocks",
    }

    def plan_claims(
        self,
        state: RuntimeState,
        prefixes: dict[str, Prefix],
        claims: list[ResidencyClaim],
    ) -> list[ClaimDecision]:
        remaining = state.capacity_blocks
        ranked: list[tuple[float, ResidencyClaim, Prefix, int]] = []
        decisions: dict[str, ClaimDecision] = {}

        for claim in claims:
            prefix = prefixes[claim.prefix_id]
            useful_blocks = prefix.threshold_blocks
            if useful_blocks > prefix.block_count:
                decisions[claim.claim_id] = refuse(
                    claim,
                    policy_name=self.name,
                    state=state,
                    reason="below_minimum_viable_footprint",
                    used_fields={
                        "claimed_footprint_blocks": "claim_arrival",
                        "prefix_block_count": "prefill_observed",
                        "useful_threshold_blocks": "prefill_observed",
                    },
                )
                continue
            density = claim.declared_value / max(useful_blocks, 1)
            ranked.append((density, claim, prefix, useful_blocks))

        ranked.sort(key=lambda item: (-item[0], item[1].claim_id))
        for density, claim, prefix, useful_blocks in ranked:
            if useful_blocks <= remaining:
                remaining -= useful_blocks
                decisions[claim.claim_id] = accept_leading(
                    claim,
                    policy_name=self.name,
                    state=state,
                    accepted_blocks=useful_blocks,
                    score=density,
                    reasons=["value_density"],
                    used_fields={
                        "declared_value": "claim_arrival",
                        "claimed_footprint_blocks": "claim_arrival",
                        "capacity_blocks": "runtime_observed",
                        "prefix_block_count": "prefill_observed",
                        "useful_threshold_blocks": "prefill_observed",
                    },
                    prefix=prefix,
                )
            else:
                decisions[claim.claim_id] = refuse(
                    claim,
                    policy_name=self.name,
                    state=state,
                    reason="budget_full",
                    used_fields={
                        "declared_value": "claim_arrival",
                        "capacity_blocks": "runtime_observed",
                        "useful_threshold_blocks": "prefill_observed",
                    },
                    score=density,
                )

        return [decisions[claim.claim_id] for claim in claims]
