"""Reports for active prefill cache-admission experiments."""

from __future__ import annotations

from dataclasses import dataclass

from kvrt import MicroRuntime, Prefix, ResidencyClaim
from kvrt.prefill import (
    ActivePrefillAdmissionPolicy,
    CacheAllPrefillPolicy,
    NoCachePrefillPolicy,
    ValueDensityPrefillAdmissionPolicy,
)
from kvrt.policies import (
    CompletePrefixFairSharePolicy,
    ResidencyPolicy,
    ValueDensityPolicy,
)


@dataclass(frozen=True)
class ActivePrefillScenario:
    capacity_blocks: int
    resident_prefixes: tuple[Prefix, ...]
    active_prefix: Prefix


@dataclass(frozen=True)
class ActivePrefillReportRow:
    policy: str
    active_prefill_decision: str
    resident_threshold_value: float
    active_threshold_value: float
    thresholds_broken: tuple[str, ...]
    net_value_delta: float


def bulky_active_prefill_scenario() -> ActivePrefillScenario:
    return ActivePrefillScenario(
        capacity_blocks=80,
        resident_prefixes=(
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
        ),
        active_prefix=Prefix.with_block_count(
            "bulky",
            70,
            tenant_id="t3",
            useful_threshold_blocks=70,
            full_reuse_value=13.0,
        ),
    )


def active_prefill_report_rows(
    scenario: ActivePrefillScenario | None = None,
) -> list[ActivePrefillReportRow]:
    scenario = scenario or bulky_active_prefill_scenario()
    specs: list[tuple[str, ResidencyPolicy, ActivePrefillAdmissionPolicy]] = [
        ("native_cache_all_prefill", ValueDensityPolicy(), CacheAllPrefillPolicy()),
        (
            "value_density_no_cache_bulky",
            ValueDensityPolicy(),
            NoCachePrefillPolicy({"bulky"}),
        ),
        (
            "value_density_active_admission",
            ValueDensityPolicy(),
            ValueDensityPrefillAdmissionPolicy(),
        ),
        (
            "complete_prefix_no_cache_bulky",
            CompletePrefixFairSharePolicy(),
            NoCachePrefillPolicy({"bulky"}),
        ),
    ]
    return [
        _run_active_prefill_row(scenario, name, policy, active_policy)
        for name, policy, active_policy in specs
    ]


def format_active_prefill_report(
    scenario: ActivePrefillScenario | None = None,
) -> str:
    rows = [
        "Active prefill admission: bulky_active_prefill",
        "Policy | active_prefill_decision | resident_threshold_value | active_threshold_value | thresholds_broken | net_value_delta",
        "--- | --- | ---: | ---: | --- | ---:",
    ]
    for row in active_prefill_report_rows(scenario):
        rows.append(
            " | ".join(
                [
                    row.policy,
                    row.active_prefill_decision,
                    _fmt(row.resident_threshold_value),
                    _fmt(row.active_threshold_value),
                    ",".join(row.thresholds_broken) or "none",
                    _fmt(row.net_value_delta),
                ]
            )
        )
    return "\n".join(rows)


def _run_active_prefill_row(
    scenario: ActivePrefillScenario,
    name: str,
    policy: ResidencyPolicy,
    active_policy: ActivePrefillAdmissionPolicy,
) -> ActivePrefillReportRow:
    prefixes = [*scenario.resident_prefixes, scenario.active_prefix]
    runtime = MicroRuntime(
        capacity_blocks=scenario.capacity_blocks,
        policy=policy,
        active_prefill_policy=active_policy,
    )
    runtime.register_prefixes(prefixes)
    runtime.admit_claims(
        [ResidencyClaim.for_prefix(prefix) for prefix in prefixes]
    )
    for prefix in scenario.resident_prefixes:
        runtime.prefill(prefix.prefix_id, active=False)
    runtime.prefill(scenario.active_prefix.prefix_id, active=True)

    resident_value = 0.0
    for prefix in scenario.resident_prefixes:
        event = runtime.return_prefix(prefix.prefix_id)
        resident_value += event["realized_value"]
    active_event = runtime.return_prefix(scenario.active_prefix.prefix_id)
    harm = [
        event
        for event in runtime.state.audit_events
        if event.get("event") == "prefill_harm"
        and event.get("active_prefill_prefix") == scenario.active_prefix.prefix_id
    ][-1]
    decision = runtime.state.active_prefill_decisions[-1]
    return ActivePrefillReportRow(
        policy=name,
        active_prefill_decision=decision.decision,
        resident_threshold_value=resident_value,
        active_threshold_value=active_event["realized_value"],
        thresholds_broken=tuple(harm["resident_thresholds_broken"]),
        net_value_delta=harm["net_value_delta"],
    )


def _fmt(value: float) -> str:
    if value == int(value):
        return str(int(value))
    return f"{value:.2f}"
