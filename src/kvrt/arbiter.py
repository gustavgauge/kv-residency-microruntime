"""Runtime-independent active/resident KV arbitration model."""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from enum import StrEnum

from kvrt.active_live import (
    ActiveFeasibility,
    ActiveLiveKVPlan,
    classify_active_feasibility,
)


class ArbiterAction(StrEnum):
    SERVE = "serve"
    EVICT_RESIDENT = "evict_resident"
    DEFER_ACTIVE = "defer_active"
    NO_ADMIT_ACTIVE_REUSE = "no_admit_active_reuse"
    OFFLOAD_RESIDENT = "offload_resident"
    OFFLOAD_ACTIVE = "offload_active"
    BOUND_ACTIVE_LIVE = "bound_active_live"
    RECOMPUTE_SPLIT = "recompute_split"
    ROUTE_ELSEWHERE = "route_elsewhere"
    REFUSE_RESIDENCY_CLAIM = "refuse_residency_claim"
    RELAX_RESIDENT_PROTECTION = "relax_resident_protection"
    INCREASE_CAPACITY = "increase_capacity"


class ArbiterMechanism(StrEnum):
    NATIVE_EVICTION = "native_eviction"
    RESIDENT_VICTIM_EXCLUSION = "resident_victim_exclusion"
    WRITE_NO_ADMIT_ONLY = "write_no_admit_only"
    ORDINARY_CHUNKING = "ordinary_chunking"
    ACTIVE_DEFERRAL = "active_deferral"
    RESIDENT_RESERVE = "resident_reserve"
    OFFLOAD_RESIDENT = "offload_resident"
    OFFLOAD_ACTIVE = "offload_active"
    BOUNDED_ACTIVE_LIVE = "bounded_active_live"
    RECOMPUTE_SPLIT = "recompute_split"
    ROUTE_ELSEWHERE = "route_elsewhere"
    RELAX_RESIDENT_PROTECTION = "relax_resident_protection"
    CAPACITY_SCALING = "capacity_scaling"
    ORACLE_ARBITER = "oracle_arbiter"


@dataclass(frozen=True)
class ResidentSetSnapshot:
    protected_blocks: int
    threshold_value: float
    prefix_ids: tuple[str, ...] = field(default_factory=tuple)
    useful_spans: tuple[tuple[str, int], ...] = field(default_factory=tuple)


@dataclass(frozen=True)
class ActiveRequest:
    request_id: str
    live_plan: ActiveLiveKVPlan
    future_reuse_value: float = 0.0
    reusable_footprint_blocks: int | None = None
    service_value: float = 0.0
    tenant_id: str | None = None
    deadline_steps: int | None = None

    @property
    def active_total_blocks(self) -> int:
        return self.live_plan.active_total_blocks

    @property
    def max_active_live_blocks(self) -> int:
        return self.live_plan.max_active_live_blocks

    @property
    def reuse_blocks(self) -> int:
        return (
            self.live_plan.active_total_blocks
            if self.reusable_footprint_blocks is None
            else self.reusable_footprint_blocks
        )


@dataclass(frozen=True)
class ArbiterCostModel:
    defer_cost_per_step: float = 1.0
    default_defer_steps: int = 1
    resident_offload_cost_per_block: float = 0.05
    active_offload_cost_per_block: float = 0.05
    recompute_cost_per_block: float = 0.10
    route_cost: float = 4.0
    extra_capacity_cost_per_block: float = 0.20


@dataclass(frozen=True)
class ArbiterOutcome:
    resident_survives: bool
    active_served: bool
    active_reusable_admitted: bool
    resident_value: float
    active_service_value: float
    active_reuse_value: float
    active_delay_steps: int = 0
    delay_cost: float = 0.0
    offload_cost: float = 0.0
    recompute_cost: float = 0.0
    route_cost: float = 0.0
    capacity_cost: float = 0.0
    victim_harm: float = 0.0
    relaxed_resident_blocks: int = 0
    extra_capacity_blocks: int = 0
    feasible_without_extra_capacity: bool = True
    refusal_reason: str | None = None
    failure_labels: tuple[str, ...] = field(default_factory=tuple)

    @property
    def total_cost(self) -> float:
        return (
            self.delay_cost
            + self.offload_cost
            + self.recompute_cost
            + self.route_cost
            + self.capacity_cost
        )

    @property
    def total_utility(self) -> float:
        return (
            self.resident_value
            + self.active_service_value
            + self.active_reuse_value
            - self.total_cost
        )


@dataclass(frozen=True)
class ArbiterDecision:
    mechanism: ArbiterMechanism
    actions: tuple[ArbiterAction, ...]
    resident: ResidentSetSnapshot
    active: ActiveRequest
    usable_blocks: int
    feasibility: ActiveFeasibility
    outcome: ArbiterOutcome
    reasons: tuple[str, ...]
    used_fields: dict[str, str] = field(default_factory=dict)

    @property
    def primary_action(self) -> ArbiterAction:
        return self.actions[0]


def default_arbiter_scenario() -> tuple[ResidentSetSnapshot, ActiveRequest, int]:
    """Return the compact active/resident boundary scenario used in reports."""

    resident = ResidentSetSnapshot(
        protected_blocks=60,
        threshold_value=17.0,
        prefix_ids=("small_hot", "small_warm"),
        useful_spans=(("small_hot", 30), ("small_warm", 30)),
    )
    active = ActiveRequest(
        request_id="bulky",
        live_plan=ActiveLiveKVPlan(
            active_total_blocks=70,
            active_chunk_sequence=(20, 20, 20, 10),
            active_attention_mode="full_attention",
        ),
        future_reuse_value=13.0,
        reusable_footprint_blocks=70,
        tenant_id="t3",
    )
    return resident, active, 80


def default_arbiter_mechanisms() -> tuple[ArbiterMechanism, ...]:
    return (
        ArbiterMechanism.NATIVE_EVICTION,
        ArbiterMechanism.RESIDENT_VICTIM_EXCLUSION,
        ArbiterMechanism.WRITE_NO_ADMIT_ONLY,
        ArbiterMechanism.ORDINARY_CHUNKING,
        ArbiterMechanism.ACTIVE_DEFERRAL,
        ArbiterMechanism.RESIDENT_RESERVE,
        ArbiterMechanism.OFFLOAD_RESIDENT,
        ArbiterMechanism.OFFLOAD_ACTIVE,
        ArbiterMechanism.BOUNDED_ACTIVE_LIVE,
        ArbiterMechanism.RECOMPUTE_SPLIT,
        ArbiterMechanism.ROUTE_ELSEWHERE,
        ArbiterMechanism.RELAX_RESIDENT_PROTECTION,
        ArbiterMechanism.CAPACITY_SCALING,
        ArbiterMechanism.ORACLE_ARBITER,
    )


def decide_active_resident(
    mechanism: ArbiterMechanism | str,
    *,
    resident: ResidentSetSnapshot,
    active: ActiveRequest,
    usable_blocks: int,
    cost_model: ArbiterCostModel | None = None,
) -> ArbiterDecision:
    """Evaluate one active/resident arbitration mechanism."""

    mechanism = ArbiterMechanism(mechanism)
    cost_model = cost_model or ArbiterCostModel()
    if mechanism == ArbiterMechanism.ORACLE_ARBITER:
        return _oracle_decision(
            resident=resident,
            active=active,
            usable_blocks=usable_blocks,
            cost_model=cost_model,
        )

    feasibility = classify_active_feasibility(
        resident_protected_blocks=resident.protected_blocks,
        active_plan=active.live_plan,
        usable_blocks=usable_blocks,
    )
    headroom = usable_blocks - resident.protected_blocks
    needed_relaxation = max(0, active.max_active_live_blocks - headroom)

    if mechanism == ArbiterMechanism.NATIVE_EVICTION:
        return _decision(
            mechanism,
            actions=(ArbiterAction.EVICT_RESIDENT, ArbiterAction.SERVE),
            resident=resident,
            active=active,
            usable_blocks=usable_blocks,
            feasibility=feasibility,
            resident_survives=False,
            active_served=active.max_active_live_blocks <= usable_blocks,
            active_reusable_admitted=True,
            victim_harm=resident.threshold_value,
            reasons=("residents_remain_allocation_victims",),
        )

    if mechanism == ArbiterMechanism.RESIDENT_VICTIM_EXCLUSION:
        return _decision(
            mechanism,
            actions=(ArbiterAction.DEFER_ACTIVE,),
            resident=resident,
            active=active,
            usable_blocks=usable_blocks,
            feasibility=feasibility,
            resident_survives=True,
            active_served=feasibility.feasible,
            active_reusable_admitted=False,
            feasible_without_extra_capacity=feasibility.feasible,
            refusal_reason=(
                None if feasibility.feasible else "active_live_exceeds_resident_headroom"
            ),
            reasons=("resident_victims_excluded_without_alternate_action",),
        )

    if mechanism == ArbiterMechanism.WRITE_NO_ADMIT_ONLY:
        return _decision(
            mechanism,
            actions=(
                ArbiterAction.NO_ADMIT_ACTIVE_REUSE,
                ArbiterAction.EVICT_RESIDENT,
                ArbiterAction.SERVE,
            ),
            resident=resident,
            active=active,
            usable_blocks=usable_blocks,
            feasibility=feasibility,
            resident_survives=False,
            active_served=active.max_active_live_blocks <= usable_blocks,
            active_reusable_admitted=False,
            victim_harm=resident.threshold_value,
            reasons=("active_live_still_consumes_kv",),
        )

    if mechanism == ArbiterMechanism.ORDINARY_CHUNKING:
        return _decision(
            mechanism,
            actions=(ArbiterAction.SERVE,),
            resident=resident,
            active=active,
            usable_blocks=usable_blocks,
            feasibility=feasibility,
            resident_survives=False,
            active_served=active.max_active_live_blocks <= usable_blocks,
            active_reusable_admitted=True,
            victim_harm=resident.threshold_value,
            reasons=("scheduled_chunks_do_not_bound_full_attention_live_kv",),
        )

    if mechanism == ArbiterMechanism.ACTIVE_DEFERRAL:
        delay = cost_model.default_defer_steps
        return _decision(
            mechanism,
            actions=(ArbiterAction.DEFER_ACTIVE,),
            resident=resident,
            active=active,
            usable_blocks=usable_blocks,
            feasibility=feasibility,
            resident_survives=True,
            active_served=True,
            active_reusable_admitted=False,
            active_delay_steps=delay,
            delay_cost=delay * cost_model.defer_cost_per_step,
            refusal_reason="deferred_until_headroom",
            reasons=("active_service_moved_out_of_conflict_window",),
        )

    if mechanism == ArbiterMechanism.RESIDENT_RESERVE:
        return _decision(
            mechanism,
            actions=(ArbiterAction.REFUSE_RESIDENCY_CLAIM,),
            resident=resident,
            active=active,
            usable_blocks=usable_blocks,
            feasibility=feasibility,
            resident_survives=True,
            active_served=feasibility.feasible,
            active_reusable_admitted=False,
            feasible_without_extra_capacity=feasibility.feasible,
            refusal_reason=None if feasibility.feasible else "resident_reserve_full",
            reasons=("resident_reserve_blocks_active_when_headroom_is_insufficient",),
        )

    if mechanism == ArbiterMechanism.OFFLOAD_RESIDENT:
        offload_cost = resident.protected_blocks * cost_model.resident_offload_cost_per_block
        offloaded_feasibility = classify_active_feasibility(
            resident_protected_blocks=0,
            active_plan=active.live_plan,
            usable_blocks=usable_blocks,
        )
        return _decision(
            mechanism,
            actions=(ArbiterAction.OFFLOAD_RESIDENT, ArbiterAction.SERVE),
            resident=resident,
            active=active,
            usable_blocks=usable_blocks,
            feasibility=offloaded_feasibility,
            resident_survives=True,
            active_served=offloaded_feasibility.feasible,
            active_reusable_admitted=True,
            offload_cost=offload_cost,
            reasons=("resident_state_moved_out_of_gpu_kv_budget",),
        )

    if mechanism == ArbiterMechanism.OFFLOAD_ACTIVE:
        offloaded_blocks = max(0, active.max_active_live_blocks - max(0, headroom))
        offload_cost = offloaded_blocks * cost_model.active_offload_cost_per_block
        bounded_plan = _bounded_active_plan(active, max(0, headroom))
        bounded_feasibility = classify_active_feasibility(
            resident_protected_blocks=resident.protected_blocks,
            active_plan=bounded_plan,
            usable_blocks=usable_blocks,
        )
        return _decision(
            mechanism,
            actions=(
                ArbiterAction.OFFLOAD_ACTIVE,
                ArbiterAction.NO_ADMIT_ACTIVE_REUSE,
                ArbiterAction.SERVE,
            ),
            resident=resident,
            active=replace(active, live_plan=bounded_plan),
            usable_blocks=usable_blocks,
            feasibility=bounded_feasibility,
            resident_survives=True,
            active_served=bounded_feasibility.feasible,
            active_reusable_admitted=False,
            offload_cost=offload_cost,
            reasons=("active_state_moved_out_of_gpu_kv_budget",),
        )

    if mechanism == ArbiterMechanism.BOUNDED_ACTIVE_LIVE:
        bounded_plan = _bounded_active_plan(active, max(0, headroom))
        bounded_feasibility = classify_active_feasibility(
            resident_protected_blocks=resident.protected_blocks,
            active_plan=bounded_plan,
            usable_blocks=usable_blocks,
        )
        recompute_cost = max(
            0,
            active.max_active_live_blocks - bounded_plan.max_active_live_blocks,
        ) * cost_model.recompute_cost_per_block
        return _decision(
            mechanism,
            actions=(ArbiterAction.BOUND_ACTIVE_LIVE, ArbiterAction.SERVE),
            resident=resident,
            active=replace(active, live_plan=bounded_plan),
            usable_blocks=usable_blocks,
            feasibility=bounded_feasibility,
            resident_survives=True,
            active_served=bounded_feasibility.feasible,
            active_reusable_admitted=False,
            recompute_cost=recompute_cost,
            reasons=("active_live_kv_is_bounded_not_merely_scheduled",),
        )

    if mechanism == ArbiterMechanism.RECOMPUTE_SPLIT:
        split_plan = ActiveLiveKVPlan(
            active_total_blocks=active.active_total_blocks,
            active_chunk_sequence=active.live_plan.active_chunk_sequence,
            active_attention_mode="recompute_free_between_chunks",
        )
        split_feasibility = classify_active_feasibility(
            resident_protected_blocks=resident.protected_blocks,
            active_plan=split_plan,
            usable_blocks=usable_blocks,
        )
        recompute_cost = active.active_total_blocks * cost_model.recompute_cost_per_block
        return _decision(
            mechanism,
            actions=(ArbiterAction.RECOMPUTE_SPLIT, ArbiterAction.SERVE),
            resident=resident,
            active=replace(active, live_plan=split_plan),
            usable_blocks=usable_blocks,
            feasibility=split_feasibility,
            resident_survives=True,
            active_served=split_feasibility.feasible,
            active_reusable_admitted=False,
            recompute_cost=recompute_cost,
            reasons=("previous_active_chunks_are_recomputed_or_freed",),
        )

    if mechanism == ArbiterMechanism.ROUTE_ELSEWHERE:
        return _decision(
            mechanism,
            actions=(ArbiterAction.ROUTE_ELSEWHERE,),
            resident=resident,
            active=active,
            usable_blocks=usable_blocks,
            feasibility=feasibility,
            resident_survives=True,
            active_served=True,
            active_reusable_admitted=False,
            route_cost=cost_model.route_cost,
            refusal_reason="routed_to_other_kv_budget",
            reasons=("active_request_uses_a_different_kv_budget",),
        )

    if mechanism == ArbiterMechanism.RELAX_RESIDENT_PROTECTION:
        return _decision(
            mechanism,
            actions=(ArbiterAction.RELAX_RESIDENT_PROTECTION, ArbiterAction.SERVE),
            resident=resident,
            active=active,
            usable_blocks=usable_blocks,
            feasibility=feasibility,
            resident_survives=False,
            active_served=active.max_active_live_blocks <= usable_blocks,
            active_reusable_admitted=True,
            victim_harm=resident.threshold_value,
            relaxed_resident_blocks=needed_relaxation,
            reasons=("resident_claim_loses_under_active_pressure",),
        )

    if mechanism == ArbiterMechanism.CAPACITY_SCALING:
        extra_blocks = max(
            0,
            resident.protected_blocks + active.max_active_live_blocks - usable_blocks,
        )
        scaled_feasibility = classify_active_feasibility(
            resident_protected_blocks=resident.protected_blocks,
            active_plan=active.live_plan,
            usable_blocks=usable_blocks + extra_blocks,
        )
        return _decision(
            mechanism,
            actions=(ArbiterAction.INCREASE_CAPACITY, ArbiterAction.SERVE),
            resident=resident,
            active=active,
            usable_blocks=usable_blocks + extra_blocks,
            feasibility=scaled_feasibility,
            resident_survives=True,
            active_served=scaled_feasibility.feasible,
            active_reusable_admitted=True,
            capacity_cost=extra_blocks * cost_model.extra_capacity_cost_per_block,
            extra_capacity_blocks=extra_blocks,
            feasible_without_extra_capacity=extra_blocks == 0,
            reasons=("usable_kv_budget_increased_until_resident_and_active_fit",),
        )

    raise ValueError(f"unsupported arbiter mechanism: {mechanism}")


def _oracle_decision(
    *,
    resident: ResidentSetSnapshot,
    active: ActiveRequest,
    usable_blocks: int,
    cost_model: ArbiterCostModel,
) -> ArbiterDecision:
    candidates = [
        decide_active_resident(
            mechanism,
            resident=resident,
            active=active,
            usable_blocks=usable_blocks,
            cost_model=cost_model,
        )
        for mechanism in default_arbiter_mechanisms()
        if mechanism != ArbiterMechanism.ORACLE_ARBITER
    ]
    best = max(
        candidates,
        key=lambda decision: (
            decision.outcome.total_utility,
            decision.outcome.resident_survives,
            decision.outcome.active_served,
        ),
    )
    return replace(
        best,
        mechanism=ArbiterMechanism.ORACLE_ARBITER,
        reasons=(f"oracle_selected_{best.mechanism.value}", *best.reasons),
    )


def _decision(
    mechanism: ArbiterMechanism,
    *,
    actions: tuple[ArbiterAction, ...],
    resident: ResidentSetSnapshot,
    active: ActiveRequest,
    usable_blocks: int,
    feasibility: ActiveFeasibility,
    resident_survives: bool,
    active_served: bool,
    active_reusable_admitted: bool,
    active_delay_steps: int = 0,
    delay_cost: float = 0.0,
    offload_cost: float = 0.0,
    recompute_cost: float = 0.0,
    route_cost: float = 0.0,
    capacity_cost: float = 0.0,
    victim_harm: float = 0.0,
    relaxed_resident_blocks: int = 0,
    extra_capacity_blocks: int = 0,
    feasible_without_extra_capacity: bool = True,
    refusal_reason: str | None = None,
    reasons: tuple[str, ...],
) -> ArbiterDecision:
    outcome = ArbiterOutcome(
        resident_survives=resident_survives,
        active_served=active_served,
        active_reusable_admitted=active_reusable_admitted,
        resident_value=resident.threshold_value if resident_survives else 0.0,
        active_service_value=active.service_value if active_served else 0.0,
        active_reuse_value=(
            active.future_reuse_value if active_reusable_admitted else 0.0
        ),
        active_delay_steps=active_delay_steps,
        delay_cost=delay_cost,
        offload_cost=offload_cost,
        recompute_cost=recompute_cost,
        route_cost=route_cost,
        capacity_cost=capacity_cost,
        victim_harm=victim_harm,
        relaxed_resident_blocks=relaxed_resident_blocks,
        extra_capacity_blocks=extra_capacity_blocks,
        feasible_without_extra_capacity=feasible_without_extra_capacity,
        refusal_reason=refusal_reason,
        failure_labels=feasibility.failure_labels,
    )
    return ArbiterDecision(
        mechanism=mechanism,
        actions=actions,
        resident=resident,
        active=active,
        usable_blocks=usable_blocks,
        feasibility=feasibility,
        outcome=outcome,
        reasons=reasons,
        used_fields={
            "resident_protected_blocks": "runtime_observed",
            "resident_threshold_value": "runtime_or_policy_value_model",
            "active_live_blocks_by_step": "runtime_observed",
            "usable_blocks": "runtime_observed",
        },
    )


def _bounded_active_plan(active: ActiveRequest, active_window_blocks: int) -> ActiveLiveKVPlan:
    return ActiveLiveKVPlan(
        active_total_blocks=active.active_total_blocks,
        active_chunk_sequence=active.live_plan.active_chunk_sequence,
        active_attention_mode="sliding_window",
        active_window_blocks=max(0, active_window_blocks),
    )
