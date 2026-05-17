"""Evaluation helpers for regret, telemetry, and failure taxonomy."""

from .ablation import same_retained_count_position_ablation
from .active_prefill_report import (
    active_prefill_report_rows,
    format_active_prefill_report,
)
from .active_live_report import (
    active_live_boundary_feasibilities,
    active_live_report_rows,
    format_active_live_report,
)
from .arbiter_report import arbiter_report_rows, format_arbiter_report
from .harness import compare_regime, compare_regimes, format_regime_table
from .materialization_report import (
    format_materialization_report,
    materialization_report_rows,
    winner_summary,
)
from .surfaces import MaterializationSurface

__all__ = [
    "MaterializationSurface",
    "active_prefill_report_rows",
    "active_live_boundary_feasibilities",
    "active_live_report_rows",
    "arbiter_report_rows",
    "compare_regime",
    "compare_regimes",
    "format_materialization_report",
    "format_active_prefill_report",
    "format_active_live_report",
    "format_arbiter_report",
    "format_regime_table",
    "materialization_report_rows",
    "same_retained_count_position_ablation",
    "winner_summary",
]
