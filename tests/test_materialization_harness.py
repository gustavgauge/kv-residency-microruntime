from __future__ import annotations

from kvrt.eval import MaterializationSurface, compare_regime, compare_regimes
from kvrt.eval.harness import format_regime_table
from kvrt.regimes import materialization_regimes


def regimes_by_name():
    return {regime.name: regime for regime in materialization_regimes()}


def test_same_trace_flips_across_materialization_surfaces() -> None:
    comparison = compare_regime(regimes_by_name()["fair_share_fragmentation"])

    abstract = MaterializationSurface.ABSTRACT_BLOCK_VALUE
    thresholded = MaterializationSurface.THRESHOLDED_CONTIGUOUS_VALUE

    assert comparison.winner(abstract) == "naive_fair_share"
    assert "complete_prefix_fair_share" in comparison.winner(thresholded)
    assert (
        comparison.runs["naive_fair_share"].score(abstract)
        > comparison.runs["complete_prefix_fair_share"].score(abstract)
    )
    assert (
        comparison.runs["complete_prefix_fair_share"].score(thresholded)
        > comparison.runs["naive_fair_share"].score(thresholded)
    )


def test_value_density_wins_under_footprint_pressure() -> None:
    comparison = compare_regime(regimes_by_name()["footprint_pressure_density"])
    surface = MaterializationSurface.THRESHOLDED_CONTIGUOUS_VALUE

    assert comparison.runs["value_density"].score(surface) == 17.0
    assert comparison.runs["complete_prefix_fair_share"].score(surface) == 13.0
    assert comparison.runs["naive_fair_share"].score(surface) == 0.0
    assert "fairness_tax" in comparison.runs["complete_prefix_fair_share"].labels


def test_complete_prefix_fair_share_beats_naive_when_fragments_are_useless() -> None:
    comparison = compare_regime(regimes_by_name()["complete_beats_naive"])
    surface = MaterializationSurface.THRESHOLDED_CONTIGUOUS_VALUE

    assert comparison.runs["complete_prefix_fair_share"].score(surface) == 15.0
    assert comparison.runs["naive_fair_share"].score(surface) == 0.0
    assert "below_threshold" in comparison.runs["naive_fair_share"].labels


def test_complete_prefix_fair_share_can_pay_fairness_tax() -> None:
    comparison = compare_regime(regimes_by_name()["fairness_tax_density_wins"])
    surface = MaterializationSurface.THRESHOLDED_CONTIGUOUS_VALUE

    assert comparison.runs["value_density"].score(surface) == 38.0
    assert comparison.runs["complete_prefix_fair_share"].score(surface) == 24.0
    assert "fairness_tax" in comparison.runs["complete_prefix_fair_share"].labels


def test_native_is_preferred_when_pressure_is_loose() -> None:
    comparison = compare_regime(regimes_by_name()["native_loose_pressure"])
    surface = MaterializationSurface.THRESHOLDED_CONTIGUOUS_VALUE

    native_score = comparison.runs["native"].score(surface)
    assert native_score == max(run.score(surface) for run in comparison.runs.values())
    assert "native_preferred" in comparison.runs["native"].labels


def test_priority_only_protection_is_not_absolute_pinning() -> None:
    comparison = compare_regime(regimes_by_name()["priority_only_not_pin"])
    surface = MaterializationSurface.PRIORITY_ONLY_EVICTION

    assert comparison.runs["value_density"].score(surface) == 0.0
    assert "partial_prefix_waste" in comparison.runs["value_density"].labels


def test_compact_regime_table_has_decision_gate_columns() -> None:
    table = format_regime_table(compare_regimes(materialization_regimes()))

    assert "regime | native | value_density | naive_fair_share" in table
    assert "complete_prefix_fair_share | oracle | explanation" in table
    assert "fairness_tax_density_wins" in table
    assert "native_preferred" in table
