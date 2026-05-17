"""Reports for active live KV feasibility boundaries."""

from __future__ import annotations

from dataclasses import dataclass

from kvrt.active_live import (
    ActiveFeasibility,
    ActiveLiveKVPlan,
    active_outcome_for_protected_residents,
    classify_active_feasibility,
)


@dataclass(frozen=True)
class ActiveLiveReportRow:
    mechanism: str
    resident_survives: str
    active_served: str
    active_live_max: int
    feasible: str
    why: str


def known_bulky_active_plan() -> ActiveLiveKVPlan:
    return ActiveLiveKVPlan(
        active_total_blocks=70,
        active_chunk_sequence=(20, 20, 20, 10),
        active_attention_mode="full_attention",
    )


def active_live_boundary_feasibilities(
    *,
    resident_protected_blocks: int = 60,
    usable_blocks_values: tuple[int, ...] = (80, 100, 130, 150),
    active_plan: ActiveLiveKVPlan | None = None,
) -> dict[int, ActiveFeasibility]:
    plan = active_plan or known_bulky_active_plan()
    return {
        usable_blocks: classify_active_feasibility(
            resident_protected_blocks=resident_protected_blocks,
            active_plan=plan,
            usable_blocks=usable_blocks,
        )
        for usable_blocks in usable_blocks_values
    }


def active_live_report_rows() -> list[ActiveLiveReportRow]:
    protected_80 = classify_active_feasibility(
        resident_protected_blocks=60,
        active_plan=ActiveLiveKVPlan.single_prefill(70),
        usable_blocks=80,
    )
    chunked_80 = classify_active_feasibility(
        resident_protected_blocks=60,
        active_plan=known_bulky_active_plan(),
        usable_blocks=80,
    )
    protected_130 = classify_active_feasibility(
        resident_protected_blocks=60,
        active_plan=known_bulky_active_plan(),
        usable_blocks=130,
    )
    offload_80 = classify_active_feasibility(
        resident_protected_blocks=60,
        active_plan=ActiveLiveKVPlan(
            active_total_blocks=70,
            active_chunk_sequence=(20, 20, 20, 10),
            active_attention_mode="sliding_window",
            active_window_blocks=20,
        ),
        usable_blocks=80,
    )
    return [
        ActiveLiveReportRow(
            mechanism="native",
            resident_survives="no",
            active_served="yes",
            active_live_max=70,
            feasible="yes-by-evicting-residents",
            why="residents remain allocation victims",
        ),
        _row_from_feasibility(
            "protected",
            protected_80,
            why="headroom exhausted",
        ),
        _row_from_feasibility(
            "protected+scheduled_chunking",
            chunked_80,
            why="chunking not live bounding",
        ),
        _row_from_feasibility(
            "protected+130_cap",
            protected_130,
            why="resident+active fits",
        ),
        _row_from_feasibility(
            "protected+offload",
            offload_80,
            why="yes-if-offload-valid",
        ),
    ]


def format_active_live_report() -> str:
    rows = [
        "Policy / Mechanism | Resident survives | Active served | Active live max | Feasible? | Why",
        "--- | --- | --- | ---: | --- | ---",
    ]
    for row in active_live_report_rows():
        rows.append(
            " | ".join(
                [
                    row.mechanism,
                    row.resident_survives,
                    row.active_served,
                    str(row.active_live_max),
                    row.feasible,
                    row.why,
                ]
            )
        )
    return "\n".join(rows)


def _row_from_feasibility(
    mechanism: str,
    feasibility: ActiveFeasibility,
    *,
    why: str,
) -> ActiveLiveReportRow:
    outcome = active_outcome_for_protected_residents(feasibility)
    return ActiveLiveReportRow(
        mechanism=mechanism,
        resident_survives="yes" if feasibility.resident_protected_blocks > 0 else "no",
        active_served="yes" if outcome == "served" else "no",
        active_live_max=feasibility.max_active_live_blocks,
        feasible="yes" if feasibility.feasible else "no",
        why=why,
    )
