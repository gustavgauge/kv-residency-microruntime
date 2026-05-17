from __future__ import annotations

import pytest

from kvrt import MicroRuntime, Prefix, ResidencyClaim
from kvrt.eval.regret import normalized_regret
from kvrt.policies import (
    CompletePrefixFairSharePolicy,
    CompletePrefixOraclePolicy,
    NaiveFairSharePolicy,
    ValueDensityPolicy,
)


def golden_prefixes() -> list[Prefix]:
    return [
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
        Prefix.with_block_count(
            "C",
            20,
            tenant_id="t3",
            useful_threshold_blocks=40,
            full_reuse_value=4.0,
        ),
    ]


def claims_for(prefixes: list[Prefix]) -> list[ResidencyClaim]:
    return [ResidencyClaim.for_prefix(prefix) for prefix in prefixes]


def run_golden(policy) -> MicroRuntime:
    prefixes = golden_prefixes()
    runtime = MicroRuntime(capacity_blocks=100, policy=policy)
    runtime.register_prefixes(prefixes)
    runtime.admit_claims(claims_for(prefixes))
    runtime.prefill_many(prefix.prefix_id for prefix in prefixes)
    runtime.pressure(pressure_blocks=20)
    return runtime


def test_threshold_value_requires_leading_contiguous_survival() -> None:
    prefix = Prefix.with_block_count(
        "A",
        60,
        useful_threshold_blocks=40,
        full_reuse_value=10.0,
    )

    assert prefix.value_for_contiguous_blocks(39) == 0.0
    assert prefix.value_for_contiguous_blocks(40) == 10.0
    assert prefix.value_for_contiguous_blocks(60) == 10.0


def test_naive_fair_share_spreads_budget_below_useful_threshold() -> None:
    runtime = run_golden(NaiveFairSharePolicy())

    decisions = {decision.claim_id: decision for decision in runtime.state.decisions}
    assert decisions["claim-A"].accepted_contiguous_prefix_blocks == 33
    assert decisions["claim-B"].accepted_contiguous_prefix_blocks == 33
    assert decisions["claim-C"].accepted_contiguous_prefix_blocks == 20

    returns = {
        prefix_id: runtime.return_prefix(prefix_id, recompute=False)
        for prefix_id in ["A", "B", "C"]
    }
    assert returns["A"]["contiguous_survived_blocks"] == 33
    assert returns["B"]["contiguous_survived_blocks"] == 33
    assert returns["C"]["contiguous_survived_blocks"] == 20
    assert sum(event["realized_value"] for event in returns.values()) == 0.0
    assert any(
        event.get("failure_mode") == "partial_prefix_waste"
        for event in runtime.state.audit_events
    )


def test_complete_prefix_fair_share_refuses_below_threshold_fragments() -> None:
    runtime = run_golden(CompletePrefixFairSharePolicy())

    decisions = {decision.claim_id: decision for decision in runtime.state.decisions}
    assert decisions["claim-A"].accepted_contiguous_prefix_blocks == 40
    assert decisions["claim-B"].accepted_contiguous_prefix_blocks == 40
    assert decisions["claim-C"].decision == "refuse"
    assert decisions["claim-C"].reasons == ["below_minimum_viable_footprint"]

    returns = {
        prefix_id: runtime.return_prefix(prefix_id, recompute=False)
        for prefix_id in ["A", "B", "C"]
    }
    assert returns["A"]["contiguous_survived_blocks"] == 40
    assert returns["B"]["contiguous_survived_blocks"] == 40
    assert returns["C"]["realized_value"] == 0.0
    assert sum(event["realized_value"] for event in returns.values()) == 18.0


def test_value_density_uses_complete_prefix_action_space() -> None:
    runtime = run_golden(ValueDensityPolicy())

    decisions = {decision.claim_id: decision for decision in runtime.state.decisions}
    assert decisions["claim-A"].accepted_prefix_ranges == [(0, 40)]
    assert decisions["claim-B"].accepted_prefix_ranges == [(0, 40)]
    assert decisions["claim-C"].decision == "refuse"
    assert all(not decision.forbidden_fields_used for decision in decisions.values())


def test_oracle_regret_quarantines_negative_regret() -> None:
    oracle_runtime = run_golden(CompletePrefixOraclePolicy())
    policy_runtime = run_golden(CompletePrefixFairSharePolicy())

    oracle_value = oracle_runtime.realized_value(["A", "B", "C"])
    policy_value = policy_runtime.realized_value(["A", "B", "C"])

    assert oracle_value == 18.0
    assert policy_value == 18.0
    assert normalized_regret(policy_value, oracle_value) == 0.0
    with pytest.raises(ValueError, match="negative regret quarantine"):
        normalized_regret(oracle_value + 1.0, oracle_value)
