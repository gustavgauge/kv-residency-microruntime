"""Mechanism report for active/resident KV arbitration."""

from __future__ import annotations

from dataclasses import dataclass

from kvrt.arbiter import (
    ActiveRequest,
    ArbiterCostModel,
    ArbiterDecision,
    ArbiterMechanism,
    ResidentSetSnapshot,
    decide_active_resident,
    default_arbiter_mechanisms,
    default_arbiter_scenario,
)


@dataclass(frozen=True)
class ArbiterReportRow:
    mechanism: str
    resident_survives: str
    resident_value: float
    active_served: str
    active_delay: int
    active_reusable_admitted: str
    offload_cost: float
    recompute_cost: float
    victim_harm: float
    total_utility: float
    refusal_reason: str
    feasible_without_extra_capacity: str
    why: str


def arbiter_report_rows(
    *,
    resident: ResidentSetSnapshot | None = None,
    active: ActiveRequest | None = None,
    usable_blocks: int | None = None,
    mechanisms: tuple[ArbiterMechanism, ...] | None = None,
    cost_model: ArbiterCostModel | None = None,
) -> list[ArbiterReportRow]:
    if resident is None or active is None or usable_blocks is None:
        default_resident, default_active, default_usable = default_arbiter_scenario()
        resident = resident or default_resident
        active = active or default_active
        usable_blocks = usable_blocks or default_usable

    decisions = [
        decide_active_resident(
            mechanism,
            resident=resident,
            active=active,
            usable_blocks=usable_blocks,
            cost_model=cost_model,
        )
        for mechanism in (mechanisms or default_arbiter_mechanisms())
    ]
    return [_row_from_decision(decision) for decision in decisions]


def format_arbiter_report(
    *,
    resident: ResidentSetSnapshot | None = None,
    active: ActiveRequest | None = None,
    usable_blocks: int | None = None,
    mechanisms: tuple[ArbiterMechanism, ...] | None = None,
    cost_model: ArbiterCostModel | None = None,
) -> str:
    if resident is None or active is None or usable_blocks is None:
        default_resident, default_active, default_usable = default_arbiter_scenario()
        resident = resident or default_resident
        active = active or default_active
        usable_blocks = usable_blocks or default_usable

    rows = [
        "Active/resident arbiter mechanism map",
        (
            f"Scenario: resident={resident.protected_blocks}, "
            f"active_live_max={active.max_active_live_blocks}, usable={usable_blocks}"
        ),
        (
            "mechanism | resident_survives | resident_value | active_served | "
            "active_delay | active_reusable_admitted | offload_cost | "
            "recompute_cost | victim_harm | total_utility | refusal_reason | "
            "feasible_without_extra_capacity | why"
        ),
        "--- | --- | ---: | --- | ---: | --- | ---: | ---: | ---: | ---: | --- | --- | ---",
    ]
    for row in arbiter_report_rows(
        resident=resident,
        active=active,
        usable_blocks=usable_blocks,
        mechanisms=mechanisms,
        cost_model=cost_model,
    ):
        rows.append(
            " | ".join(
                [
                    row.mechanism,
                    row.resident_survives,
                    _fmt(row.resident_value),
                    row.active_served,
                    str(row.active_delay),
                    row.active_reusable_admitted,
                    _fmt(row.offload_cost),
                    _fmt(row.recompute_cost),
                    _fmt(row.victim_harm),
                    _fmt(row.total_utility),
                    row.refusal_reason,
                    row.feasible_without_extra_capacity,
                    row.why,
                ]
            )
        )
    return "\n".join(rows)


def _row_from_decision(decision: ArbiterDecision) -> ArbiterReportRow:
    outcome = decision.outcome
    return ArbiterReportRow(
        mechanism=decision.mechanism.value,
        resident_survives=_yes_no(outcome.resident_survives),
        resident_value=outcome.resident_value,
        active_served=_active_served_label(outcome.active_served, outcome.active_delay_steps),
        active_delay=outcome.active_delay_steps,
        active_reusable_admitted=_yes_no(outcome.active_reusable_admitted),
        offload_cost=outcome.offload_cost,
        recompute_cost=outcome.recompute_cost,
        victim_harm=outcome.victim_harm,
        total_utility=outcome.total_utility,
        refusal_reason=outcome.refusal_reason or "none",
        feasible_without_extra_capacity=_yes_no(outcome.feasible_without_extra_capacity),
        why=",".join(decision.reasons),
    )


def _active_served_label(active_served: bool, active_delay: int) -> str:
    if active_served and active_delay:
        return "delayed"
    return _yes_no(active_served)


def _yes_no(value: bool) -> str:
    return "yes" if value else "no"


def _fmt(value: float) -> str:
    if value == int(value):
        return str(int(value))
    return f"{value:.2f}"
