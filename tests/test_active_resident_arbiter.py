from __future__ import annotations

from kvrt.arbiter import (
    ArbiterAction,
    ArbiterMechanism,
    decide_active_resident,
    default_arbiter_scenario,
)
from kvrt.eval.arbiter_report import arbiter_report_rows, format_arbiter_report
from kvrt.eval.materialization_report import materialization_report_rows
from kvrt.regimes import materialization_regimes


def regime(name: str):
    return {regime.name: regime for regime in materialization_regimes()}[name]


def test_arbiter_action_set_names_missing_active_resident_choices() -> None:
    assert {action.value for action in ArbiterAction} >= {
        "serve",
        "evict_resident",
        "defer_active",
        "no_admit_active_reuse",
        "offload_resident",
        "offload_active",
        "bound_active_live",
        "recompute_split",
        "route_elsewhere",
        "refuse_residency_claim",
        "relax_resident_protection",
    }


def test_retention_alone_is_insufficient_when_active_and_resident_exceed_budget() -> None:
    resident, active, usable_blocks = default_arbiter_scenario()

    decision = decide_active_resident(
        ArbiterMechanism.RESIDENT_VICTIM_EXCLUSION,
        resident=resident,
        active=active,
        usable_blocks=usable_blocks,
    )

    assert resident.protected_blocks + active.max_active_live_blocks == 130
    assert decision.feasibility.feasible is False
    assert decision.outcome.resident_survives is True
    assert decision.outcome.active_served is False
    assert decision.outcome.refusal_reason == "active_live_exceeds_resident_headroom"


def test_no_admit_only_does_not_remove_active_live_kv_pressure() -> None:
    resident, active, usable_blocks = default_arbiter_scenario()

    decision = decide_active_resident(
        ArbiterMechanism.WRITE_NO_ADMIT_ONLY,
        resident=resident,
        active=active,
        usable_blocks=usable_blocks,
    )

    assert ArbiterAction.NO_ADMIT_ACTIVE_REUSE in decision.actions
    assert decision.outcome.active_served is True
    assert decision.outcome.active_reusable_admitted is False
    assert decision.outcome.resident_survives is False
    assert decision.outcome.victim_harm == 17.0
    assert decision.reasons == ("active_live_still_consumes_kv",)


def test_ordinary_chunking_is_not_live_kv_bounding() -> None:
    resident, active, usable_blocks = default_arbiter_scenario()

    decision = decide_active_resident(
        ArbiterMechanism.ORDINARY_CHUNKING,
        resident=resident,
        active=active,
        usable_blocks=usable_blocks,
    )

    assert active.live_plan.active_live_blocks_by_step == [20, 40, 60, 70]
    assert decision.feasibility.expected_blocked_step == 2
    assert "chunking_not_live_bounding" in decision.outcome.failure_labels
    assert decision.outcome.resident_survives is False


def test_offload_deferral_and_recompute_are_explicit_costed_actions() -> None:
    resident, active, usable_blocks = default_arbiter_scenario()

    offload = decide_active_resident(
        ArbiterMechanism.OFFLOAD_RESIDENT,
        resident=resident,
        active=active,
        usable_blocks=usable_blocks,
    )
    defer = decide_active_resident(
        ArbiterMechanism.ACTIVE_DEFERRAL,
        resident=resident,
        active=active,
        usable_blocks=usable_blocks,
    )
    recompute = decide_active_resident(
        ArbiterMechanism.RECOMPUTE_SPLIT,
        resident=resident,
        active=active,
        usable_blocks=usable_blocks,
    )

    assert offload.outcome.resident_survives is True
    assert offload.outcome.active_served is True
    assert offload.outcome.offload_cost > 0
    assert defer.outcome.active_delay_steps > 0
    assert defer.outcome.refusal_reason == "deferred_until_headroom"
    assert recompute.outcome.recompute_cost > 0
    assert recompute.feasibility.max_active_live_blocks == 20


def test_leading_prefix_threshold_value_beats_raw_retained_count() -> None:
    rows = {
        row.policy: row
        for row in materialization_report_rows(regime("fair_share_fragmentation"))
    }

    assert rows["naive_fair_share"].total_cached_tokens > rows[
        "complete_prefix_fair_share"
    ].total_cached_tokens
    assert rows["naive_fair_share"].threshold_value < rows[
        "complete_prefix_fair_share"
    ].threshold_value


def test_arbiter_report_is_the_mechanism_map() -> None:
    rows = {row.mechanism: row for row in arbiter_report_rows()}
    report = format_arbiter_report()

    assert rows["native_eviction"].resident_survives == "no"
    assert rows["resident_victim_exclusion"].active_served == "no"
    assert rows["write_no_admit_only"].active_reusable_admitted == "no"
    assert rows["offload_resident"].offload_cost > 0
    assert rows["capacity_scaling"].feasible_without_extra_capacity == "no"
    assert "mechanism | resident_survives | resident_value | active_served" in report
