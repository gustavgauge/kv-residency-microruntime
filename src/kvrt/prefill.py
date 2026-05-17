"""Active prefill cache-admission policies."""

from __future__ import annotations

from typing import Protocol

from . import cache
from .model import (
    ActivePrefillClaim,
    ActivePrefillDecision,
    Prefix,
    RuntimeState,
)


class ActivePrefillAdmissionPolicy(Protocol):
    name: str

    def decide(
        self,
        state: RuntimeState,
        prefix: Prefix,
        claim: ActivePrefillClaim,
        prefixes: dict[str, Prefix],
    ) -> ActivePrefillDecision:
        ...


class CacheAllPrefillPolicy:
    name = "native_cache_all_prefill"

    def decide(
        self,
        state: RuntimeState,
        prefix: Prefix,
        claim: ActivePrefillClaim,
        prefixes: dict[str, Prefix],
    ) -> ActivePrefillDecision:
        return ActivePrefillDecision(
            claim_id=claim.claim_id,
            prefix_id=prefix.prefix_id,
            decision="cache_admit",
            admitted_prefix_range=(0, prefix.block_count),
            blocks_admitted=prefix.block_count,
            eviction_priority=2.0,
            score=0.0,
            reasons=["native_cache_all"],
            used_fields={"claimed_footprint_blocks": "active_prefill"},
        )


class NoCachePrefillPolicy:
    name = "no_cache_active_prefill"

    def __init__(self, prefix_ids: set[str] | None = None) -> None:
        self.prefix_ids = prefix_ids

    def decide(
        self,
        state: RuntimeState,
        prefix: Prefix,
        claim: ActivePrefillClaim,
        prefixes: dict[str, Prefix],
    ) -> ActivePrefillDecision:
        if self.prefix_ids is None or prefix.prefix_id in self.prefix_ids:
            return ActivePrefillDecision(
                claim_id=claim.claim_id,
                prefix_id=prefix.prefix_id,
                decision="cache_no_admit",
                admitted_prefix_range=None,
                blocks_admitted=0,
                eviction_priority=0.0,
                score=0.0,
                reasons=["active_prefill_disposable"],
                used_fields={"prefix_id": "active_prefill"},
            )
        return CacheAllPrefillPolicy().decide(state, prefix, claim, prefixes)


class PartialCachePrefillPolicy:
    name = "partial_cache_active_prefill"

    def __init__(self, blocks: int) -> None:
        self.blocks = blocks

    def decide(
        self,
        state: RuntimeState,
        prefix: Prefix,
        claim: ActivePrefillClaim,
        prefixes: dict[str, Prefix],
    ) -> ActivePrefillDecision:
        blocks = min(max(0, self.blocks), prefix.block_count)
        return ActivePrefillDecision(
            claim_id=claim.claim_id,
            prefix_id=prefix.prefix_id,
            decision="cache_partial",
            admitted_prefix_range=(0, blocks) if blocks else None,
            blocks_admitted=blocks,
            eviction_priority=2.0,
            score=float(blocks),
            reasons=["active_prefill_partial"],
            used_fields={"claimed_footprint_blocks": "active_prefill"},
        )


class DemotePrefillPolicy:
    name = "demote_active_prefill"

    def decide(
        self,
        state: RuntimeState,
        prefix: Prefix,
        claim: ActivePrefillClaim,
        prefixes: dict[str, Prefix],
    ) -> ActivePrefillDecision:
        return ActivePrefillDecision(
            claim_id=claim.claim_id,
            prefix_id=prefix.prefix_id,
            decision="cache_demote",
            admitted_prefix_range=(0, prefix.block_count),
            blocks_admitted=prefix.block_count,
            eviction_priority=-1.0,
            score=0.0,
            reasons=["active_prefill_demoted"],
            used_fields={"claimed_footprint_blocks": "active_prefill"},
        )


class ValueDensityPrefillAdmissionPolicy:
    """Admit active prefill only when it beats likely resident victim density."""

    name = "value_density_active_prefill"

    def decide(
        self,
        state: RuntimeState,
        prefix: Prefix,
        claim: ActivePrefillClaim,
        prefixes: dict[str, Prefix],
    ) -> ActivePrefillDecision:
        active_density = claim.declared_value / max(prefix.threshold_blocks, 1)
        victim_density = _lowest_threshold_crossed_resident_density(state, prefixes)
        if victim_density is None or active_density >= victim_density:
            return ActivePrefillDecision(
                claim_id=claim.claim_id,
                prefix_id=prefix.prefix_id,
                decision="cache_if_value_density",
                admitted_prefix_range=(0, prefix.block_count),
                blocks_admitted=prefix.block_count,
                eviction_priority=2.0,
                score=active_density,
                reasons=["active_density_beats_resident_victims"],
                used_fields={
                    "declared_value": "active_prefill",
                    "threshold_blocks": "prefill_observed",
                },
            )
        return ActivePrefillDecision(
            claim_id=claim.claim_id,
            prefix_id=prefix.prefix_id,
            decision="cache_no_admit",
            admitted_prefix_range=None,
            blocks_admitted=0,
            eviction_priority=0.0,
            score=active_density,
            reasons=["active_density_below_resident_victims"],
            used_fields={
                "declared_value": "active_prefill",
                "threshold_blocks": "prefill_observed",
            },
        )


def _lowest_threshold_crossed_resident_density(
    state: RuntimeState,
    prefixes: dict[str, Prefix],
) -> float | None:
    densities: list[float] = []
    for prefix_id in state.resident_by_prefix:
        prefix = prefixes.get(prefix_id)
        if prefix is None:
            continue
        contiguous = cache.contiguous_surviving_blocks(state, prefix)
        if contiguous >= prefix.threshold_blocks:
            densities.append(prefix.full_reuse_value / max(prefix.threshold_blocks, 1))
    if not densities:
        return None
    return min(densities)
