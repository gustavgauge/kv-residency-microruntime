#!/usr/bin/env python
"""Print a materialization report for a hand-authored regime."""

from __future__ import annotations

import argparse

from kvrt.eval.materialization_report import (
    format_materialization_report,
    winner_summary,
)
from kvrt.regimes import materialization_regimes


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("regime", nargs="?", default="fair_share_fragmentation")
    args = parser.parse_args()
    regimes = {regime.name: regime for regime in materialization_regimes()}
    regime = regimes[args.regime]
    print(format_materialization_report(regime))
    print()
    for key, value in winner_summary(regime).items():
        print(f"{key}: {value}")


if __name__ == "__main__":
    main()
