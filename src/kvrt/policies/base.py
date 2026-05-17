"""Policy interface and shared decision helpers."""

from __future__ import annotations

from typing import Protocol

from kvrt.model import Block, ClaimDecision, Prefix, ResidencyClaim, RuntimeState


class ResidencyPolicy(Protocol):
    name: str
    admissible_fields: set[str]
    is_oracle: bool = False

    def plan_claims(
        self,
        state: RuntimeState,
        prefixes: dict[str, Prefix],
        claims: list[ResidencyClaim],
    ) -> list[ClaimDecision]:
        ...

    def eviction_key(self, state: RuntimeState, block: Block) -> tuple:
        ...


class BasePolicy:
    name = "base"
    admissible_fields: set[str] = set()
    is_oracle = False

    def plan_claims(
        self,
        state: RuntimeState,
        prefixes: dict[str, Prefix],
        claims: list[ResidencyClaim],
    ) -> list[ClaimDecision]:
        return [
            refuse(
                claim,
                policy_name=self.name,
                state=state,
                reason="native_fallback",
                used_fields={},
            )
            for claim in claims
        ]

    def eviction_key(self, state: RuntimeState, block: Block) -> tuple:
        protected_rank = block.eviction_priority
        return (protected_rank, block.last_touched_step, block.block_id)


def accept_leading(
    claim: ResidencyClaim,
    *,
    policy_name: str,
    state: RuntimeState,
    accepted_blocks: int,
    score: float,
    reasons: list[str],
    used_fields: dict[str, str],
    prefix: Prefix | None = None,
) -> ClaimDecision:
    accepted_blocks = max(0, accepted_blocks)
    if prefix is not None:
        accepted_blocks = min(accepted_blocks, prefix.block_count)
    claimed = claim.claimed_footprint_blocks
    decision = "accept" if accepted_blocks >= claimed else "partial_accept"
    if accepted_blocks == 0:
        decision = "refuse"
    ranges = [(0, accepted_blocks)] if accepted_blocks > 0 else []
    return ClaimDecision(
        claim_id=claim.claim_id,
        decision=decision,
        accepted_prefix_ranges=ranges,
        accepted_contiguous_prefix_blocks=accepted_blocks,
        accepted_physical_blocks=set(),
        score=score,
        reasons=reasons,
        policy_name=policy_name,
        pressure_snapshot=state.pressure_snapshot,
        cap_snapshot=state.capacity_blocks,
        used_fields=used_fields,
    )


def refuse(
    claim: ResidencyClaim,
    *,
    policy_name: str,
    state: RuntimeState,
    reason: str,
    used_fields: dict[str, str],
    score: float = 0.0,
) -> ClaimDecision:
    return ClaimDecision(
        claim_id=claim.claim_id,
        decision="refuse",
        accepted_prefix_ranges=[],
        accepted_contiguous_prefix_blocks=0,
        accepted_physical_blocks=set(),
        score=score,
        reasons=[reason],
        policy_name=policy_name,
        pressure_snapshot=state.pressure_snapshot,
        cap_snapshot=state.capacity_blocks,
        used_fields=used_fields,
    )


def fallback_native(
    claim: ResidencyClaim,
    *,
    policy_name: str,
    state: RuntimeState,
) -> ClaimDecision:
    decision = refuse(
        claim,
        policy_name=policy_name,
        state=state,
        reason="native_fallback",
        used_fields={},
    )
    decision.decision = "fallback_native"
    return decision
