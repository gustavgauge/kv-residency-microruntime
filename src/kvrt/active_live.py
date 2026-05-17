"""Active live KV lifetime and feasibility modeling."""

from __future__ import annotations

from dataclasses import dataclass, field
from itertools import accumulate
from typing import Literal


ActiveAttentionMode = Literal[
    "full_attention",
    "sliding_window",
    "recompute_free_between_chunks",
]

ActiveOutcome = Literal[
    "served",
    "deferred",
    "failed",
    "preempted",
    "offloaded",
    "recomputed",
    "chunk_admitted",
    "chunk_blocked",
    "resident_evicted",
]


PHYSICAL_INFEASIBLE = (
    "physically_infeasible_without_scratch_offload_recompute_or_eviction"
)


@dataclass(frozen=True)
class ActiveLiveKVPlan:
    active_total_blocks: int
    active_chunk_sequence: tuple[int, ...]
    active_attention_mode: ActiveAttentionMode = "full_attention"
    active_window_blocks: int | None = None

    @classmethod
    def single_prefill(
        cls,
        active_total_blocks: int,
        *,
        active_attention_mode: ActiveAttentionMode = "full_attention",
    ) -> "ActiveLiveKVPlan":
        return cls(
            active_total_blocks=active_total_blocks,
            active_chunk_sequence=(active_total_blocks,),
            active_attention_mode=active_attention_mode,
        )

    @property
    def active_live_blocks_by_step(self) -> list[int]:
        if self.active_attention_mode == "full_attention":
            return [
                min(self.active_total_blocks, live)
                for live in accumulate(self.active_chunk_sequence)
            ]
        if self.active_attention_mode == "sliding_window":
            window = self.active_window_blocks or self.active_total_blocks
            return [
                min(window, self.active_total_blocks, live)
                for live in accumulate(self.active_chunk_sequence)
            ]
        if self.active_attention_mode == "recompute_free_between_chunks":
            return [min(chunk, self.active_total_blocks) for chunk in self.active_chunk_sequence]
        raise ValueError(f"unsupported active attention mode: {self.active_attention_mode}")

    @property
    def max_active_live_blocks(self) -> int:
        live = self.active_live_blocks_by_step
        return max(live) if live else 0


@dataclass(frozen=True)
class ActiveFeasibility:
    resident_protected_blocks: int
    active_total_blocks: int
    active_chunk_sequence: tuple[int, ...]
    active_attention_mode: ActiveAttentionMode
    active_live_blocks_by_step: list[int]
    max_active_live_blocks: int
    usable_blocks: int
    unprotected_headroom_blocks: int
    feasible: bool
    feasibility: str
    expected_blocked_step: int | None
    failure_labels: tuple[str, ...] = field(default_factory=tuple)


def classify_active_feasibility(
    *,
    resident_protected_blocks: int,
    active_plan: ActiveLiveKVPlan,
    usable_blocks: int,
) -> ActiveFeasibility:
    """Classify whether protected resident KV and active live KV can coexist."""

    unprotected_headroom = usable_blocks - resident_protected_blocks
    live_by_step = active_plan.active_live_blocks_by_step
    max_active = active_plan.max_active_live_blocks
    expected_blocked_step = _first_blocked_step(live_by_step, unprotected_headroom)
    feasible = resident_protected_blocks + max_active <= usable_blocks
    labels: list[str] = []
    if active_plan.active_attention_mode == "full_attention" and len(live_by_step) > 1:
        labels.append("active_live_kv_accumulation")
    if expected_blocked_step is not None:
        labels.extend(
            [
                "protected_resident_headroom_exhausted",
                "active_admission_blocked",
                "resident_protection_requires_deferral",
            ]
        )
        if active_plan.active_attention_mode == "full_attention":
            labels.append("chunking_not_live_bounding")
    if not feasible:
        labels.append("physical_capacity_infeasible")

    return ActiveFeasibility(
        resident_protected_blocks=resident_protected_blocks,
        active_total_blocks=active_plan.active_total_blocks,
        active_chunk_sequence=active_plan.active_chunk_sequence,
        active_attention_mode=active_plan.active_attention_mode,
        active_live_blocks_by_step=live_by_step,
        max_active_live_blocks=max_active,
        usable_blocks=usable_blocks,
        unprotected_headroom_blocks=unprotected_headroom,
        feasible=feasible,
        feasibility=(
            "feasible"
            if feasible
            else PHYSICAL_INFEASIBLE
        ),
        expected_blocked_step=expected_blocked_step,
        failure_labels=tuple(dict.fromkeys(labels)),
    )


def active_outcome_for_protected_residents(feasibility: ActiveFeasibility) -> ActiveOutcome:
    if feasibility.feasible:
        return "served"
    if feasibility.expected_blocked_step is not None:
        return "chunk_blocked"
    return "failed"


def _first_blocked_step(
    active_live_blocks_by_step: list[int],
    unprotected_headroom_blocks: int,
) -> int | None:
    for index, live_blocks in enumerate(active_live_blocks_by_step, start=1):
        if live_blocks > unprotected_headroom_blocks:
            return index
    return None
