"""Materialization reports for comparing retained count with useful position."""

from __future__ import annotations

from dataclasses import dataclass

from kvrt import MicroRuntime, ResidencyClaim, cache
from kvrt.eval.surfaces import MaterializationSurface, score_state
from kvrt.policies import (
    AbstractBlockOraclePolicy,
    CompletePrefixFairSharePolicy,
    CompletePrefixOraclePolicy,
    NaiveFairSharePolicy,
    NativePolicy,
    ResidencyPolicy,
    ValueDensityPolicy,
)
from kvrt.regimes import MaterializationRegime


@dataclass(frozen=True)
class ReportPolicySpec:
    name: str
    policy: ResidencyPolicy


@dataclass(frozen=True)
class MaterializationReportRow:
    policy: str
    abstract_blocks: float
    total_cached_tokens: int
    leading_contiguous_tokens: dict[str, int]
    threshold_value: float


def report_policy_specs() -> list[ReportPolicySpec]:
    return [
        ReportPolicySpec("native", NativePolicy()),
        ReportPolicySpec("naive_fair_share", NaiveFairSharePolicy()),
        ReportPolicySpec("complete_prefix_fair_share", CompletePrefixFairSharePolicy()),
        ReportPolicySpec("value_density", ValueDensityPolicy()),
        ReportPolicySpec("abstract_block_oracle", AbstractBlockOraclePolicy()),
        ReportPolicySpec("thresholded_prefix_oracle", CompletePrefixOraclePolicy()),
    ]


def materialization_report_rows(
    regime: MaterializationRegime,
    *,
    policies: list[ReportPolicySpec] | None = None,
) -> list[MaterializationReportRow]:
    policies = policies or report_policy_specs()
    rows: list[MaterializationReportRow] = []
    for spec in policies:
        runtime = run_regime_runtime(regime, spec.policy)
        prefixes = list(regime.prefixes)
        rows.append(
            MaterializationReportRow(
                policy=spec.name,
                abstract_blocks=score_state(
                    runtime.state,
                    prefixes,
                    MaterializationSurface.ABSTRACT_BLOCK_VALUE,
                ),
                total_cached_tokens=int(
                    score_state(
                        runtime.state,
                        prefixes,
                        MaterializationSurface.TOTAL_CACHED_TOKENS,
                    )
                ),
                leading_contiguous_tokens={
                    prefix.prefix_id: cache.contiguous_surviving_blocks(
                        runtime.state, prefix
                    )
                    * runtime.state.block_size_tokens
                    for prefix in prefixes
                },
                threshold_value=score_state(
                    runtime.state,
                    prefixes,
                    MaterializationSurface.THRESHOLDED_LEADING_PREFIX,
                ),
            )
        )
    return rows


def format_materialization_report(regime: MaterializationRegime) -> str:
    rows = [
        f"Trace: {regime.name}",
        "Policy | abstract_blocks | total_cached | leading_contig | threshold_value",
        "--- | ---: | ---: | --- | ---:",
    ]
    for row in materialization_report_rows(regime):
        rows.append(
            " | ".join(
                [
                    row.policy,
                    _fmt(row.abstract_blocks),
                    str(row.total_cached_tokens),
                    _format_leading(row.leading_contiguous_tokens),
                    _fmt(row.threshold_value),
                ]
            )
        )
    return "\n".join(rows)


def winner_summary(regime: MaterializationRegime) -> dict[str, str]:
    rows = [
        row
        for row in materialization_report_rows(regime)
        if not row.policy.endswith("_oracle")
    ]
    return {
        "winner_by_abstract_block_value": _winner(
            rows, lambda row: row.abstract_blocks
        ),
        "winner_by_thresholded_prefix_value": _winner(
            rows, lambda row: row.threshold_value
        ),
        "winner_by_total_cached_tokens": _winner(
            rows, lambda row: float(row.total_cached_tokens)
        ),
    }


def run_regime_runtime(regime: MaterializationRegime, policy: ResidencyPolicy) -> MicroRuntime:
    runtime = MicroRuntime(capacity_blocks=regime.capacity_blocks, policy=policy)
    prefixes = list(regime.prefixes)
    runtime.register_prefixes(prefixes)
    runtime.admit_claims([ResidencyClaim.for_prefix(prefix) for prefix in prefixes])
    runtime.prefill_many(prefix.prefix_id for prefix in prefixes)
    if regime.pressure_blocks:
        runtime.pressure(regime.pressure_blocks)
    return runtime


def _winner(rows: list[MaterializationReportRow], score_fn) -> str:
    best = max(score_fn(row) for row in rows)
    return ",".join(row.policy for row in rows if score_fn(row) == best)


def _format_leading(tokens_by_prefix: dict[str, int]) -> str:
    return ",".join(
        f"{prefix_id}={tokens}"
        for prefix_id, tokens in tokens_by_prefix.items()
        if tokens > 0
    ) or "none"


def _fmt(value: float) -> str:
    if value == int(value):
        return str(int(value))
    return f"{value:.2f}"
