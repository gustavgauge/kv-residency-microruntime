"""Fair-share policy variants for the contiguous-prefix MVP."""

from __future__ import annotations

from .base import BasePolicy, accept_leading, refuse
from kvrt.model import ClaimDecision, Prefix, ResidencyClaim, RuntimeState


class NaiveFairSharePolicy(BasePolicy):
    """Divide the cap evenly, even when the share is below useful threshold."""

    name = "naive_fair_share"
    admissible_fields = {
        "tenant_id",
        "claimed_footprint_blocks",
        "capacity_blocks",
        "prefix_block_count",
    }

    def plan_claims(
        self,
        state: RuntimeState,
        prefixes: dict[str, Prefix],
        claims: list[ResidencyClaim],
    ) -> list[ClaimDecision]:
        if not claims:
            return []
        share = state.capacity_blocks // len(claims)
        decisions: list[ClaimDecision] = []
        for claim in claims:
            prefix = prefixes[claim.prefix_id]
            accepted = min(share, claim.claimed_footprint_blocks, prefix.block_count)
            decisions.append(
                accept_leading(
                    claim,
                    policy_name=self.name,
                    state=state,
                    accepted_blocks=accepted,
                    score=float(accepted),
                    reasons=["equal_share"],
                    used_fields={
                        "tenant_id": "claim_arrival",
                        "claimed_footprint_blocks": "claim_arrival",
                        "capacity_blocks": "runtime_observed",
                        "prefix_block_count": "prefill_observed",
                    },
                    prefix=prefix,
                )
            )
        return decisions


class CompletePrefixFairSharePolicy(BasePolicy):
    """Allocate useful complete prefixes across tenants in fair rounds."""

    name = "complete_prefix_fair_share"
    admissible_fields = {
        "tenant_id",
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
        decisions_by_id: dict[str, ClaimDecision] = {}
        feasible_by_tenant: dict[str, list[tuple[float, ResidencyClaim, Prefix, int]]] = {}

        for claim in claims:
            prefix = prefixes[claim.prefix_id]
            useful_blocks = prefix.threshold_blocks
            if useful_blocks > prefix.block_count:
                decisions_by_id[claim.claim_id] = refuse(
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
            tenant_key = claim.tenant_id or claim.claim_id
            feasible_by_tenant.setdefault(tenant_key, []).append(
                (density, claim, prefix, useful_blocks)
            )

        for tenant_claims in feasible_by_tenant.values():
            tenant_claims.sort(
                key=lambda item: (-item[0], item[1].created_step, item[1].claim_id)
            )

        tenant_keys = sorted(feasible_by_tenant)
        while tenant_keys:
            progressed = False
            next_tenants: list[str] = []
            for tenant_key in tenant_keys:
                tenant_claims = feasible_by_tenant[tenant_key]
                if not tenant_claims:
                    continue
                density, claim, prefix, useful_blocks = tenant_claims.pop(0)
                if useful_blocks <= remaining:
                    remaining -= useful_blocks
                    progressed = True
                    decisions_by_id[claim.claim_id] = accept_leading(
                        claim,
                        policy_name=self.name,
                        state=state,
                        accepted_blocks=useful_blocks,
                        score=density,
                        reasons=["complete_prefix_fair_round"],
                        used_fields={
                            "tenant_id": "claim_arrival",
                            "declared_value": "claim_arrival",
                            "claimed_footprint_blocks": "claim_arrival",
                            "capacity_blocks": "runtime_observed",
                            "prefix_block_count": "prefill_observed",
                            "useful_threshold_blocks": "prefill_observed",
                        },
                        prefix=prefix,
                    )
                    if tenant_claims:
                        next_tenants.append(tenant_key)
                else:
                    decisions_by_id[claim.claim_id] = refuse(
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
                    for later_density, later_claim, _later_prefix, _later_blocks in (
                        tenant_claims
                    ):
                        decisions_by_id[later_claim.claim_id] = refuse(
                            later_claim,
                            policy_name=self.name,
                            state=state,
                            reason="budget_full",
                            used_fields={
                                "declared_value": "claim_arrival",
                                "capacity_blocks": "runtime_observed",
                                "useful_threshold_blocks": "prefill_observed",
                            },
                            score=later_density,
                        )
            if not progressed:
                break
            tenant_keys = next_tenants

        for tenant_claims in feasible_by_tenant.values():
            for density, claim, _prefix, _useful_blocks in tenant_claims:
                decisions_by_id.setdefault(
                    claim.claim_id,
                    refuse(
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
                    ),
                )

        return [decisions_by_id[claim.claim_id] for claim in claims]
