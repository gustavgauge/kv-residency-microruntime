#!/usr/bin/env python
"""Print the active-prefill admission report."""

from __future__ import annotations

from kvrt.eval.active_prefill_report import format_active_prefill_report


def main() -> None:
    print(format_active_prefill_report())


if __name__ == "__main__":
    main()
