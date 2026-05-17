"""Hard seed export for active prefill admission validation."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from kvrt.eval.active_live_report import known_bulky_active_plan
from kvrt.eval.active_prefill_report import (
    active_prefill_report_rows,
    bulky_active_prefill_scenario,
)
from kvrt.active_live import classify_active_feasibility


def build_active_prefill_seed() -> dict[str, Any]:
    scenario = bulky_active_prefill_scenario()
    active_plan = known_bulky_active_plan()
    feasibility = classify_active_feasibility(
        resident_protected_blocks=60,
        active_plan=active_plan,
        usable_blocks=scenario.capacity_blocks,
    )
    rows = {row.policy: row for row in active_prefill_report_rows(scenario)}
    return {
        "seed_id": "active-prefill-bulky-admission",
        "mode": "active_prefill_cache_admission",
        "capacity_blocks": scenario.capacity_blocks,
        "block_size_tokens": 16,
        "resident_prefixes": [_prefix_row(prefix) for prefix in scenario.resident_prefixes],
        "active_prefill_prefix": _prefix_row(scenario.active_prefix),
        "resident_protected_blocks": feasibility.resident_protected_blocks,
        "active_total_blocks": feasibility.active_total_blocks,
        "active_chunk_sequence": list(feasibility.active_chunk_sequence),
        "active_attention_mode": feasibility.active_attention_mode,
        "active_live_blocks_by_step": feasibility.active_live_blocks_by_step,
        "max_active_live_blocks": feasibility.max_active_live_blocks,
        "usable_blocks": feasibility.usable_blocks,
        "unprotected_headroom_blocks": feasibility.unprotected_headroom_blocks,
        "feasibility": feasibility.feasibility,
        "expected_blocked_step": feasibility.expected_blocked_step,
        "failure_labels": list(feasibility.failure_labels),
        "event_sequence": [
            {"event_type": "resident_claims", "prefix_ids": ["small_hot", "small_warm"]},
            {"event_type": "resident_prefill", "prefix_id": "small_hot"},
            {"event_type": "resident_prefill", "prefix_id": "small_warm"},
            {"event_type": "active_prefill", "prefix_id": "bulky"},
            {"event_type": "return", "prefix_id": "small_hot"},
            {"event_type": "return", "prefix_id": "small_warm"},
            {"event_type": "return", "prefix_id": "bulky"},
        ],
        "expected_live_if_cache_all_active_prefill": _row(rows["native_cache_all_prefill"]),
        "expected_live_if_disposable_active_prefill": _row(
            rows["value_density_no_cache_bulky"]
        ),
        "expected_live_if_density_gated_active_prefill": _row(
            rows["value_density_active_admission"]
        ),
        "pressure_decomposition": {
            "resident_prefill_blocks": 60,
            "active_prefill_blocks": 70,
            "active_prefill_over_headroom_blocks": 50,
            "explicit_filler_pressure_blocks": 0,
        },
        "exact_falsifier": (
            "Falsified if cache-all active prefill does not break the compact "
            "resident thresholds, or if no-cache/density-gated active prefill "
            "fails to preserve small_hot and small_warm at threshold value 17."
        ),
        "research_question": (
            "Can compact resident spans survive if the bulky active prefill is "
            "served but not admitted into reusable KV cache?"
        ),
    }


def write_active_prefill_seed(output_dir: Path) -> tuple[Path, Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    seed = build_active_prefill_seed()
    seed_path = output_dir / "active_prefill_seed.json"
    decision_path = output_dir / "decision.md"
    seed_path.write_text(
        json.dumps(seed, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    decision_path.write_text(_decision_md(seed), encoding="utf-8")
    return seed_path, decision_path


def _prefix_row(prefix) -> dict[str, Any]:
    return {
        "prefix_id": prefix.prefix_id,
        "tenant_id": prefix.tenant_id,
        "block_count": prefix.block_count,
        "token_count": prefix.token_count,
        "threshold_blocks": prefix.threshold_blocks,
        "threshold_tokens": prefix.threshold_blocks * 16,
        "full_reuse_value": prefix.full_reuse_value,
    }


def _row(row) -> dict[str, Any]:
    return {
        "active_prefill_decision": row.active_prefill_decision,
        "resident_threshold_value": row.resident_threshold_value,
        "active_threshold_value": row.active_threshold_value,
        "thresholds_broken": list(row.thresholds_broken),
        "net_value_delta": row.net_value_delta,
    }


def _decision_md(seed: dict[str, Any]) -> str:
    return "\n".join(
        [
            "# Active Prefill Admission Decision",
            "",
            "## Question",
            "",
            seed["research_question"],
            "",
            "## Current Interpretation",
            "",
            "The prior live negative exposed a missing layer: active prefill "
            "materialization competes with resident future-reuse claims. KV "
            "residency is both eviction and admission.",
            "",
            "## Hard Seed",
            "",
            f"- Seed: `{seed['seed_id']}`",
            "- Cache-all active prefill should break `small_hot` and `small_warm`.",
            "- Disposable or density-gated active prefill should preserve resident value 17.",
            "- Scheduled chunking alone does not bound live KV under full attention.",
            "",
            "## Falsifier",
            "",
            seed["exact_falsifier"],
            "",
        ]
    )
