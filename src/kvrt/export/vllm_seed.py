"""Hard seed export for narrow MicroRuntime-to-vLLM replay."""

from __future__ import annotations

import json
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Any

from kvrt.eval import MaterializationSurface, compare_regime
from kvrt.eval.harness import RegimeComparison
from kvrt.regimes import MaterializationRegime, materialization_regimes


SELECTED_HARD_SEED_REGIMES = (
    "fair_share_fragmentation",
    "footprint_pressure_density",
    "fairness_tax_density_wins",
)


@dataclass(frozen=True)
class ExpectedOrdering:
    surface: str
    ordered_policies: list[str]
    scores: dict[str, float]


@dataclass(frozen=True)
class HardSeed:
    seed_id: str
    source_regime: str
    mode: str
    capacity_blocks: int
    block_size_tokens: int
    pressure_blocks: int
    pressure_decomposition: dict[str, int]
    prefixes: list[dict[str, Any]]
    event_sequence: list[dict[str, Any]]
    expected_abstract_block_ordering: ExpectedOrdering
    expected_thresholded_contiguous_ordering: ExpectedOrdering
    expected_live_vllm_ordering_if_blockpool_is_thresholded: list[str]
    required_materialization_surface: str
    export_quality: dict[str, Any]
    exact_falsifier: str
    explanation: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def selected_hard_seed_regimes() -> list[MaterializationRegime]:
    regimes = {regime.name: regime for regime in materialization_regimes()}
    return [regimes[name] for name in SELECTED_HARD_SEED_REGIMES]


def build_hard_seed(regime: MaterializationRegime) -> HardSeed:
    comparison = compare_regime(regime)
    abstract = _ordering(comparison, MaterializationSurface.ABSTRACT_BLOCK_VALUE)
    thresholded = _ordering(
        comparison, MaterializationSurface.THRESHOLDED_CONTIGUOUS_VALUE
    )
    seed_id = f"hard-seed-{regime.name}"
    return HardSeed(
        seed_id=seed_id,
        source_regime=regime.name,
        mode="microruntime_to_vllm_hard_seed",
        capacity_blocks=regime.capacity_blocks,
        block_size_tokens=16,
        pressure_blocks=regime.pressure_blocks,
        pressure_decomposition=_pressure_decomposition(regime),
        prefixes=[_prefix_row(prefix) for prefix in regime.prefixes],
        event_sequence=_event_sequence(regime),
        expected_abstract_block_ordering=abstract,
        expected_thresholded_contiguous_ordering=thresholded,
        expected_live_vllm_ordering_if_blockpool_is_thresholded=(
            thresholded.ordered_policies
        ),
        required_materialization_surface=(
            "direct BlockPool/free-queue ownership hook or telemetry-equivalent "
            "live replay that reports contiguous cached prefix survival"
        ),
        export_quality=_export_quality(regime, abstract, thresholded),
        exact_falsifier=_falsifier(regime.name, abstract, thresholded),
        explanation=regime.explanation,
    )


def build_selected_hard_seeds() -> list[HardSeed]:
    return [build_hard_seed(regime) for regime in selected_hard_seed_regimes()]


def write_hard_seed_exports(output_dir: Path) -> tuple[Path, Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    seeds = build_selected_hard_seeds()
    seeds_path = output_dir / "selected_live_replay_seeds.json"
    decision_path = output_dir / "decision.md"
    seeds_path.write_text(
        json.dumps([seed.to_dict() for seed in seeds], indent=2, sort_keys=True)
        + "\n",
        encoding="utf-8",
    )
    decision_path.write_text(render_decision_md(seeds), encoding="utf-8")
    return seeds_path, decision_path


def render_decision_md(seeds: list[HardSeed]) -> str:
    lines = [
        "# MicroRuntime-to-vLLM Hard Seeds",
        "",
        "## Question",
        "",
        "Does live BlockPool behavior follow abstract protected-block accounting "
        "or thresholded contiguous-prefix survival?",
        "",
        "## Decision",
        "",
        "The materialization-regime suite justifies one narrow direct vLLM hook replay. "
        "The MicroRuntime now explains a live-class inversion mechanism: policy "
        "rankings can change when value is materialized as useful contiguous "
        "prefix survival instead of abstract protected block count.",
        "",
        "This is not distributional evidence and does not justify broader "
        "policy families, deadlines, trust, adversarial metadata, or large "
        "sweeps yet.",
        "",
        "## Selected Seeds",
        "",
        "| seed | abstract-block expectation | thresholded-contiguous expectation | falsifier |",
        "| --- | --- | --- | --- |",
    ]
    for seed in seeds:
        lines.append(
            "| "
            + " | ".join(
                [
                    seed.seed_id,
                    _top_summary(seed.expected_abstract_block_ordering),
                    _top_summary(seed.expected_thresholded_contiguous_ordering),
                    seed.exact_falsifier,
                ]
            )
            + " |"
        )
    lines.extend(
        [
            "",
            "## Next Live Replay",
            "",
            "Replay these seeds through a direct BlockPool/free-queue ownership "
            "hook, or a telemetry-equivalent path that reports leading "
            "contiguous cached prefix survival. The first seed to run is "
            "`hard-seed-fair_share_fragmentation`.",
            "",
            "If live ordering follows thresholded contiguous survival, the "
            "MicroRuntime is useful as a policy-design substrate for this "
            "mechanism. If live ordering follows abstract protected blocks, or "
            "neither exported surface explains the result, stop expanding the "
            "MicroRuntime and repair the live materialization model first.",
            "",
        ]
    )
    return "\n".join(lines)


def _ordering(
    comparison: RegimeComparison,
    surface: MaterializationSurface,
) -> ExpectedOrdering:
    scores = {
        policy_name: run.score(surface)
        for policy_name, run in comparison.runs.items()
    }
    ordered = sorted(scores, key=lambda policy: (-scores[policy], policy))
    return ExpectedOrdering(
        surface=surface.value,
        ordered_policies=ordered,
        scores=scores,
    )


def _prefix_row(prefix) -> dict[str, Any]:
    return {
        "prefix_id": prefix.prefix_id,
        "tenant_id": prefix.tenant_id,
        "block_count": prefix.block_count,
        "token_count": prefix.token_count,
        "useful_threshold_blocks": prefix.useful_threshold_blocks,
        "threshold_blocks": prefix.threshold_blocks,
        "threshold_tokens": prefix.threshold_blocks * 16,
        "threshold_rule": prefix.threshold_rule_label,
        "full_reuse_value": prefix.full_reuse_value,
    }


def _pressure_decomposition(regime: MaterializationRegime) -> dict[str, int]:
    prefill_blocks = sum(prefix.block_count for prefix in regime.prefixes)
    prefill_over_capacity = max(0, prefill_blocks - regime.capacity_blocks)
    total_over_capacity = max(
        0,
        prefill_blocks + regime.pressure_blocks - regime.capacity_blocks,
    )
    return {
        "prefill_blocks": prefill_blocks,
        "prefill_over_capacity_blocks": prefill_over_capacity,
        "explicit_pressure_blocks": regime.pressure_blocks,
        "total_pressure_blocks": total_over_capacity,
        "capacity_headroom_before_return": max(
            0,
            regime.capacity_blocks - min(
                regime.capacity_blocks,
                prefill_blocks + regime.pressure_blocks,
            ),
        ),
    }


def _event_sequence(regime: MaterializationRegime) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    for prefix in regime.prefixes:
        events.append({"event_type": "claim", "prefix_id": prefix.prefix_id})
    for prefix in regime.prefixes:
        events.append({"event_type": "prefill", "prefix_id": prefix.prefix_id})
    if regime.pressure_blocks:
        events.append(
            {
                "event_type": "pressure",
                "pressure_blocks": regime.pressure_blocks,
            }
        )
    for prefix in regime.prefixes:
        events.append({"event_type": "return", "prefix_id": prefix.prefix_id})
    return events


def _falsifier(
    regime_name: str,
    abstract: ExpectedOrdering,
    thresholded: ExpectedOrdering,
) -> str:
    abstract_top = abstract.ordered_policies[0]
    thresholded_top = thresholded.ordered_policies[0]
    if regime_name == "fair_share_fragmentation":
        return (
            "Falsified if live BlockPool replay ranks naive_fair_share with "
            "nonzero useful cached-prefix reuse comparable to complete-prefix "
            "policies; thresholded survival predicts naive_fair_share collapses."
        )
    if regime_name == "footprint_pressure_density":
        return (
            "Falsified if live replay cannot separate compact value-density "
            "claims from the bulky footprint under the same pressure, or if "
            "complete_prefix_fair_share clearly beats value_density."
        )
    if regime_name == "fairness_tax_density_wins":
        return (
            "Falsified if live replay does not show the fair-round allocator "
            "paying value for the low-value tenant when value_density keeps the "
            "two high-value same-tenant prefixes useful."
        )
    return (
        "Falsified if live top policy is neither the abstract-block top "
        f"({abstract_top}) nor the thresholded-contiguous top ({thresholded_top})."
    )


def _export_quality(
    regime: MaterializationRegime,
    abstract: ExpectedOrdering,
    thresholded: ExpectedOrdering,
) -> dict[str, Any]:
    threshold_scores = [
        thresholded.scores[policy] for policy in thresholded.ordered_policies
    ]
    top = threshold_scores[0]
    second = next((score for score in threshold_scores if score < top), top)
    top_disagrees = (
        abstract.ordered_policies[0] != thresholded.ordered_policies[0]
    )
    pressure = _pressure_decomposition(regime)
    native_score = thresholded.scores.get("native", 0.0)
    best_score = max(thresholded.scores.values())
    return {
        "policy_separation_margin": top - second,
        "surface_disagreement_score": 1.0 if top_disagrees else 0.0,
        "threshold_sensitivity": max(
            abs(abstract.scores[policy] - thresholded.scores[policy])
            for policy in abstract.scores
        ),
        "mapping_risk": "medium",
        "pressure_risk": "high"
        if pressure["total_pressure_blocks"] > regime.capacity_blocks
        else "medium",
        "native_saturation_risk": "high"
        if native_score == best_score and best_score > 0
        else "low",
        "expected_live_falsifier": _falsifier(
            regime.name,
            abstract,
            thresholded,
        ),
    }


def _top_summary(ordering: ExpectedOrdering) -> str:
    top_score = ordering.scores[ordering.ordered_policies[0]]
    top = [
        policy
        for policy in ordering.ordered_policies
        if ordering.scores[policy] == top_score
    ]
    return f"{','.join(top)} ({_fmt(top_score)})"


def _fmt(value: float) -> str:
    if value == int(value):
        return str(int(value))
    return f"{value:.2f}"
