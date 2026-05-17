#!/usr/bin/env python
"""Print the compact materialization-regime table."""

from __future__ import annotations

from kvrt.eval import MaterializationSurface, compare_regimes, format_regime_table
from kvrt.regimes import materialization_regimes


def main() -> None:
    comparisons = compare_regimes(materialization_regimes())
    print(
        format_regime_table(
            comparisons,
            surface=MaterializationSurface.THRESHOLDED_CONTIGUOUS_VALUE,
        )
    )


if __name__ == "__main__":
    main()
