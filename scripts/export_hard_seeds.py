#!/usr/bin/env python
"""Export hard seeds and their decision note."""

from __future__ import annotations

from pathlib import Path

from kvrt.export import write_hard_seed_exports


def main() -> None:
    output_dir = Path("docs/hard-seeds")
    seeds_path, decision_path = write_hard_seed_exports(output_dir)
    print(f"wrote {seeds_path}")
    print(f"wrote {decision_path}")


if __name__ == "__main__":
    main()
