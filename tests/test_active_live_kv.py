from __future__ import annotations

from kvrt.active_live import (
    PHYSICAL_INFEASIBLE,
    ActiveLiveKVPlan,
    classify_active_feasibility,
)
from kvrt.eval.active_live_report import (
    active_live_boundary_feasibilities,
    format_active_live_report,
    known_bulky_active_plan,
)
from kvrt.export import build_active_prefill_seed


def test_full_attention_active_live_blocks_accumulate_across_chunks() -> None:
    plan = known_bulky_active_plan()

    assert plan.active_chunk_sequence == (20, 20, 20, 10)
    assert plan.active_live_blocks_by_step == [20, 40, 60, 70]
    assert plan.max_active_live_blocks == 70


def test_current_seed_is_physically_infeasible_with_protected_residents() -> None:
    feasibility = classify_active_feasibility(
        resident_protected_blocks=60,
        active_plan=known_bulky_active_plan(),
        usable_blocks=80,
    )

    assert feasibility.resident_protected_blocks + feasibility.max_active_live_blocks == 130
    assert feasibility.usable_blocks == 80
    assert feasibility.feasible is False
    assert feasibility.feasibility == PHYSICAL_INFEASIBLE
    assert feasibility.unprotected_headroom_blocks == 20
    assert feasibility.expected_blocked_step == 2
    assert "chunking_not_live_bounding" in feasibility.failure_labels
    assert "protected_resident_headroom_exhausted" in feasibility.failure_labels


def test_bounded_live_chunking_is_different_from_scheduled_chunking() -> None:
    bounded = ActiveLiveKVPlan(
        active_total_blocks=70,
        active_chunk_sequence=(20, 20, 20, 10),
        active_attention_mode="sliding_window",
        active_window_blocks=20,
    )
    feasibility = classify_active_feasibility(
        resident_protected_blocks=60,
        active_plan=bounded,
        usable_blocks=80,
    )

    assert bounded.active_live_blocks_by_step == [20, 20, 20, 20]
    assert feasibility.feasible is True
    assert feasibility.expected_blocked_step is None


def test_capacity_boundary_generator_identifies_130_block_boundary() -> None:
    boundaries = active_live_boundary_feasibilities()

    assert boundaries[80].feasible is False
    assert boundaries[100].feasible is False
    assert boundaries[130].feasible is True
    assert boundaries[150].feasible is True


def test_active_live_report_contains_required_outcome_distinctions() -> None:
    report = format_active_live_report()

    assert "native | no | yes | 70 | yes-by-evicting-residents" in report
    assert "protected+scheduled_chunking | yes | no | 70 | no" in report
    assert "protected+130_cap | yes | yes | 70 | yes" in report
    assert "protected+offload | yes | yes | 20 | yes" in report


def test_active_prefill_seed_exports_active_live_feasibility_fields() -> None:
    seed = build_active_prefill_seed()

    assert seed["resident_protected_blocks"] == 60
    assert seed["active_total_blocks"] == 70
    assert seed["active_chunk_sequence"] == [20, 20, 20, 10]
    assert seed["active_attention_mode"] == "full_attention"
    assert seed["active_live_blocks_by_step"] == [20, 40, 60, 70]
    assert seed["max_active_live_blocks"] == 70
    assert seed["usable_blocks"] == 80
    assert seed["unprotected_headroom_blocks"] == 20
    assert seed["feasibility"] == PHYSICAL_INFEASIBLE
    assert seed["expected_blocked_step"] == 2
