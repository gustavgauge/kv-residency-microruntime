"""Positive-control policy that accepts every claim."""

from __future__ import annotations

from .base import BasePolicy, accept_leading
from kvrt.model import ClaimDecision, Prefix, ResidencyClaim, RuntimeState


class NoRefusalAllClaimsPolicy(BasePolicy):
    name = "no_refusal_all_claims"
    admissible_fields = {
        "claimed_footprint_blocks",
        "prefix_block_count",
    }

    def plan_claims(
        self,
        state: RuntimeState,
        prefixes: dict[str, Prefix],
        claims: list[ResidencyClaim],
    ) -> list[ClaimDecision]:
        decisions: list[ClaimDecision] = []
        for claim in claims:
            prefix = prefixes[claim.prefix_id]
            accepted = min(claim.claimed_footprint_blocks, prefix.block_count)
            decisions.append(
                accept_leading(
                    claim,
                    policy_name=self.name,
                    state=state,
                    accepted_blocks=accepted,
                    score=float(accepted),
                    reasons=["no_refusal"],
                    used_fields={
                        "claimed_footprint_blocks": "claim_arrival",
                        "prefix_block_count": "prefill_observed",
                    },
                    prefix=prefix,
                )
            )
        return decisions
