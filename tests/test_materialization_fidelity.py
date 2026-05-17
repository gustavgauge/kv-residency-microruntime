from __future__ import annotations

from kvrt import MicroRuntime, Prefix, ResidencyClaim
from kvrt.eval import (
    format_materialization_report,
    same_retained_count_position_ablation,
    winner_summary,
)
from kvrt.eval.materialization_report import materialization_report_rows
from kvrt.model import ThresholdRule
from kvrt.policies import (
    AbstractBlockOraclePolicy,
    CompletePrefixOraclePolicy,
    NaiveFairSharePolicy,
)
from kvrt.regimes import materialization_regimes


def regime(name: str):
    return {regime.name: regime for regime in materialization_regimes()}[name]


def test_threshold_rules_emit_blocks_tokens_and_crossing() -> None:
    prefix = Prefix.with_block_count(
        "A",
        100,
        useful_threshold_blocks=40,
        full_reuse_value=10.0,
        threshold_rule=ThresholdRule("fraction", 0.5),
    )
    runtime = MicroRuntime(capacity_blocks=100)
    runtime.register_prefixes([prefix])
    runtime.prefill("A")

    event = runtime.return_prefix("A")

    assert event["threshold_blocks"] == 50
    assert event["threshold_tokens"] == 800
    assert event["threshold_rule"] == "fraction:0.5"
    assert event["threshold_crossed"] is True


def test_prefix_position_survival_ledger_records_threshold_context() -> None:
    prefixes = [
        Prefix.with_block_count(
            "A",
            60,
            tenant_id="t1",
            useful_threshold_blocks=40,
            full_reuse_value=10.0,
        ),
        Prefix.with_block_count(
            "B",
            60,
            tenant_id="t2",
            useful_threshold_blocks=40,
            full_reuse_value=8.0,
        ),
    ]
    runtime = MicroRuntime(capacity_blocks=80, policy=NaiveFairSharePolicy())
    runtime.register_prefixes(prefixes)
    runtime.admit_claims([ResidencyClaim.for_prefix(prefix) for prefix in prefixes])
    runtime.prefill_many(["A", "B"])
    runtime.pressure(20)

    ledger = runtime.prefix_position_ledger("A")
    protected = [row for row in ledger if row["protected"]]

    assert protected[17]["position_in_prefix"] == 17
    assert protected[17]["accepted_range"] == [0, 40]
    assert protected[17]["threshold_blocks"] == 40
    assert protected[17]["threshold_tokens"] == 640
    assert "threshold_crossed" in protected[17]
    assert any(row["evicted_step"] is not None for row in ledger)


def test_materialization_report_shows_surface_disagreement() -> None:
    rows = {
        row.policy: row
        for row in materialization_report_rows(regime("fair_share_fragmentation"))
    }
    winners = winner_summary(regime("fair_share_fragmentation"))

    assert rows["naive_fair_share"].abstract_blocks > rows[
        "complete_prefix_fair_share"
    ].abstract_blocks
    assert rows["naive_fair_share"].threshold_value == 0.0
    assert rows["complete_prefix_fair_share"].threshold_value == 18.0
    assert winners["winner_by_abstract_block_value"] == "naive_fair_share"
    assert "complete_prefix_fair_share" in winners[
        "winner_by_thresholded_prefix_value"
    ]


def test_same_retained_count_different_positions_ablation() -> None:
    result = same_retained_count_position_ablation()

    leading = result["leading_A_0_40"]
    tail = result["tail_A_20_60"]
    assert leading["retained_blocks"] == tail["retained_blocks"] == 40.0
    assert leading["abstract_block_value"] == tail["abstract_block_value"]
    assert leading["thresholded_leading_prefix"] == 10.0
    assert tail["thresholded_leading_prefix"] == 0.0


def test_abstract_and_thresholded_oracles_are_distinct() -> None:
    trace = regime("fair_share_fragmentation")
    abstract = materialization_report_rows(
        trace,
        policies=[
            type("Spec", (), {"name": "abstract", "policy": AbstractBlockOraclePolicy()})(),
            type(
                "Spec",
                (),
                {"name": "thresholded", "policy": CompletePrefixOraclePolicy()},
            )(),
        ],
    )

    by_policy = {row.policy: row for row in abstract}
    assert by_policy["abstract"].abstract_blocks > by_policy[
        "thresholded"
    ].abstract_blocks
    assert by_policy["abstract"].threshold_value < by_policy[
        "thresholded"
    ].threshold_value


def test_materialization_report_format_contains_required_columns() -> None:
    report = format_materialization_report(regime("fair_share_fragmentation"))

    assert "Policy | abstract_blocks | total_cached | leading_contig" in report
    assert "threshold_value" in report
    assert "abstract_block_oracle" in report
    assert "thresholded_prefix_oracle" in report
