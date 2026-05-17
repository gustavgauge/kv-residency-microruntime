#!/usr/bin/env python
"""Print the active live KV feasibility report."""

from __future__ import annotations

from kvrt.eval.active_live_report import format_active_live_report


def main() -> None:
    print(format_active_live_report())


if __name__ == "__main__":
    main()
