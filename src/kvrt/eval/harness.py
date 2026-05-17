"""Materialization inversion/explanation harness."""

from __future__ import annotations

from dataclasses import dataclass, field

from kvrt import MicroRuntime, ResidencyClaim
from kvrt.eval.surfaces import MaterializationSurface, score_state
from kvrt.policies import (
    CompletePrefixFairSharePolicy,
    CompletePrefixOraclePolicy,
    NaiveFairSharePolicy,
    NativePolicy,
    ResidencyPolicy,
    ValueDensityPolicy,
)
from kvrt.regimes import MaterializationRegime


@dataclass(frozen=True)
class PolicySpec:
    name: str
    policy: ResidencyPolicy


@dataclass
class PolicyRun:
    regime: str
    policy: str
    scores: dict[str, float]
    decisions: dict[str, str]
    labels: set[str] = field(default_factory=set)

    def score(self, surface: MaterializationSurface) -> float:
        return self.scores[surface.value]


@dataclass
class RegimeComparison:
    regime: MaterializationRegime
    runs: dict[str, PolicyRun]
    explanation: str

    def winner(self, surface: MaterializationSurface) -> str:
        best_score = max(run.score(surface) for run in self.runs.values())
        winners = [
            policy_name
            for policy_name, run in self.runs.items()
            if run.score(surface) == best_score
        ]
        return ",".join(winners)


def default_policy_specs() -> list[PolicySpec]:
    return [
        PolicySpec("native", NativePolicy()),
        PolicySpec("value_density", ValueDensityPolicy()),
        PolicySpec("naive_fair_share", NaiveFairSharePolicy()),
        PolicySpec("complete_prefix_fair_share", CompletePrefixFairSharePolicy()),
        PolicySpec("oracle", CompletePrefixOraclePolicy()),
    ]


def compare_regime(
    regime: MaterializationRegime,
    *,
    policies: list[PolicySpec] | None = None,
    surfaces: list[MaterializationSurface] | None = None,
) -> RegimeComparison:
    policies = policies or default_policy_specs()
    surfaces = surfaces or list(MaterializationSurface)
    runs = {
        spec.name: _run_policy(regime, spec, surfaces=surfaces)
        for spec in policies
    }
    _add_cross_policy_labels(regime, runs)
    return RegimeComparison(regime=regime, runs=runs, explanation=regime.explanation)


def compare_regimes(regimes: list[MaterializationRegime]) -> list[RegimeComparison]:
    return [compare_regime(regime) for regime in regimes]


def format_regime_table(
    comparisons: list[RegimeComparison],
    *,
    surface: MaterializationSurface = MaterializationSurface.THRESHOLDED_CONTIGUOUS_VALUE,
) -> str:
    columns = [
        "regime",
        "native",
        "value_density",
        "naive_fair_share",
        "complete_prefix_fair_share",
        "oracle",
        "explanation",
    ]
    rows = [" | ".join(columns)]
    rows.append(" | ".join("---" for _ in columns))
    for comparison in comparisons:
        row = [comparison.regime.name]
        for policy_name in columns[1:-1]:
            run = comparison.runs[policy_name]
            labels = ",".join(sorted(run.labels))
            score = _fmt_score(run.score(surface))
            row.append(f"{score} {labels}".strip())
        row.append(comparison.explanation)
        rows.append(" | ".join(row))
    return "\n".join(rows)


def _run_policy(
    regime: MaterializationRegime,
    spec: PolicySpec,
    *,
    surfaces: list[MaterializationSurface],
) -> PolicyRun:
    runtime = MicroRuntime(capacity_blocks=regime.capacity_blocks, policy=spec.policy)
    prefixes = list(regime.prefixes)
    runtime.register_prefixes(prefixes)
    runtime.admit_claims([ResidencyClaim.for_prefix(prefix) for prefix in prefixes])
    runtime.prefill_many(prefix.prefix_id for prefix in prefixes)
    if regime.pressure_blocks:
        runtime.pressure(regime.pressure_blocks)
    scores = {
        surface.value: score_state(runtime.state, prefixes, surface)
        for surface in surfaces
    }
    decisions = {
        decision.claim_id: decision.decision
        for decision in runtime.state.decisions
    }
    labels = _labels_for_run(runtime, spec.name, regime)
    return PolicyRun(
        regime=regime.name,
        policy=spec.name,
        scores=scores,
        decisions=decisions,
        labels=labels,
    )


def _labels_for_run(runtime: MicroRuntime, policy_name: str, regime: MaterializationRegime) -> set[str]:
    labels: set[str] = set()
    prefix_by_id = {prefix.prefix_id: prefix for prefix in regime.prefixes}
    claim_by_id = {f"claim-{prefix.prefix_id}": prefix for prefix in regime.prefixes}
    for decision in runtime.state.decisions:
        prefix = claim_by_id.get(decision.claim_id)
        if prefix is None:
            continue
        if (
            0
            < decision.accepted_contiguous_prefix_blocks
            < prefix.threshold_blocks
        ):
            labels.add("below_threshold")
        if decision.decision == "refuse" and decision.reasons == [
            "below_minimum_viable_footprint"
        ]:
            labels.add("below_threshold")
        if policy_name == "value_density" and decision.decision == "refuse":
            labels.add("density_starvation")

    for prefix in prefix_by_id.values():
        from kvrt import cache

        total = cache.total_surviving_blocks(runtime.state, prefix)
        contiguous = cache.contiguous_surviving_blocks(runtime.state, prefix)
        if total > 0 and contiguous < prefix.threshold_blocks:
            labels.add("partial_prefix_waste")
    return labels


def _add_cross_policy_labels(
    regime: MaterializationRegime,
    runs: dict[str, PolicyRun],
) -> None:
    surface = MaterializationSurface.THRESHOLDED_CONTIGUOUS_VALUE
    value_density = runs["value_density"].score(surface)
    complete_fair = runs["complete_prefix_fair_share"].score(surface)
    native = runs["native"].score(surface)
    best = max(run.score(surface) for run in runs.values())
    if complete_fair < value_density:
        runs["complete_prefix_fair_share"].labels.add("fairness_tax")
    if regime.pressure_level == "loose" and native == best:
        runs["native"].labels.add("native_preferred")


def _fmt_score(value: float) -> str:
    if value == int(value):
        return str(int(value))
    return f"{value:.2f}"
