from __future__ import annotations

import json

from kvrt import MicroRuntime, Prefix, ResidencyClaim
from kvrt.eval.active_prefill_report import active_prefill_report_rows
from kvrt.export import build_active_prefill_seed, write_active_prefill_seed
from kvrt.policies import ValueDensityPolicy
from kvrt.prefill import CacheAllPrefillPolicy, NoCachePrefillPolicy


def active_prefill_prefixes() -> list[Prefix]:
    return [
        Prefix.with_block_count(
            "small_hot",
            30,
            tenant_id="t1",
            useful_threshold_blocks=30,
            full_reuse_value=9.0,
        ),
        Prefix.with_block_count(
            "small_warm",
            30,
            tenant_id="t2",
            useful_threshold_blocks=30,
            full_reuse_value=8.0,
        ),
        Prefix.with_block_count(
            "bulky",
            70,
            tenant_id="t3",
            useful_threshold_blocks=70,
            full_reuse_value=13.0,
        ),
    ]


def test_cache_all_active_prefill_breaks_resident_thresholds() -> None:
    prefixes = active_prefill_prefixes()
    runtime = MicroRuntime(
        capacity_blocks=80,
        policy=ValueDensityPolicy(),
        active_prefill_policy=CacheAllPrefillPolicy(),
    )
    runtime.register_prefixes(prefixes)
    runtime.admit_claims([ResidencyClaim.for_prefix(prefix) for prefix in prefixes])
    runtime.prefill("small_hot", active=False)
    runtime.prefill("small_warm", active=False)
    runtime.prefill("bulky", active=True)

    harm = [
        event for event in runtime.state.audit_events if event.get("event") == "prefill_harm"
    ][-1]

    assert harm["blocks_admitted"] == 70
    assert harm["resident_thresholds_broken"] == ["small_hot", "small_warm"]
    assert harm["victim_value_lost"] == 17.0
    assert harm["net_value_delta"] == -17.0
    assert runtime.return_prefix("small_hot")["threshold_crossed"] is False


def test_no_cache_active_prefill_preserves_compact_resident_spans() -> None:
    prefixes = active_prefill_prefixes()
    runtime = MicroRuntime(
        capacity_blocks=80,
        policy=ValueDensityPolicy(),
        active_prefill_policy=NoCachePrefillPolicy({"bulky"}),
    )
    runtime.register_prefixes(prefixes)
    runtime.admit_claims([ResidencyClaim.for_prefix(prefix) for prefix in prefixes])
    runtime.prefill("small_hot", active=False)
    runtime.prefill("small_warm", active=False)
    runtime.prefill("bulky", active=True)

    assert runtime.return_prefix("small_hot")["realized_value"] == 9.0
    assert runtime.return_prefix("small_warm")["realized_value"] == 8.0
    assert runtime.return_prefix("bulky")["realized_value"] == 0.0


def test_active_prefill_report_separates_cache_all_from_disposable() -> None:
    rows = {row.policy: row for row in active_prefill_report_rows()}

    assert rows["native_cache_all_prefill"].thresholds_broken == (
        "small_hot",
        "small_warm",
    )
    assert rows["native_cache_all_prefill"].resident_threshold_value == 0.0
    assert rows["value_density_no_cache_bulky"].resident_threshold_value == 17.0
    assert rows["value_density_active_admission"].active_prefill_decision == (
        "cache_no_admit"
    )


def test_active_prefill_seed_exports_falsifier(tmp_path) -> None:
    seed = build_active_prefill_seed()
    seed_path, decision_path = write_active_prefill_seed(tmp_path)
    exported = json.loads(seed_path.read_text(encoding="utf-8"))
    decision = decision_path.read_text(encoding="utf-8")

    assert seed["seed_id"] == "active-prefill-bulky-admission"
    assert seed["expected_live_if_cache_all_active_prefill"]["net_value_delta"] == -17.0
    assert exported["expected_live_if_disposable_active_prefill"][
        "resident_threshold_value"
    ] == 17.0
    assert "KV residency is both eviction and admission" in decision
