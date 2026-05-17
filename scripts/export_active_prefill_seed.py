#!/usr/bin/env python
"""Export the active-prefill admission hard seed."""

from __future__ import annotations

from pathlib import Path

from kvrt.export import write_active_prefill_seed


def main() -> None:
    seed_path, decision_path = write_active_prefill_seed(
        Path("docs/active-prefill-admission")
    )
    print(f"wrote {seed_path}")
    print(f"wrote {decision_path}")


if __name__ == "__main__":
    main()
