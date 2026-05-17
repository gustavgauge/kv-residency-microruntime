"""Hand-authored materialization regimes for inversion/explanation tests."""

from __future__ import annotations

from dataclasses import dataclass

from kvrt.model import Prefix


@dataclass(frozen=True)
class MaterializationRegime:
    name: str
    capacity_blocks: int
    prefixes: tuple[Prefix, ...]
    pressure_blocks: int = 0
    pressure_level: str = "tight"
    explanation: str = ""

    @property
    def return_prefix_ids(self) -> list[str]:
        return [prefix.prefix_id for prefix in self.prefixes]


def p(
    prefix_id: str,
    block_count: int,
    threshold: int,
    value: float,
    tenant: str,
) -> Prefix:
    return Prefix.with_block_count(
        prefix_id,
        block_count,
        tenant_id=tenant,
        useful_threshold_blocks=threshold,
        full_reuse_value=value,
    )


def materialization_regimes() -> list[MaterializationRegime]:
    """Return the compact, intentional regime set for the next decision gate."""

    return [
        MaterializationRegime(
            name="fair_share_fragmentation",
            capacity_blocks=100,
            prefixes=(
                p("A", 60, 40, 10.0, "t1"),
                p("B", 60, 40, 8.0, "t2"),
                p("C", 20, 40, 4.0, "t3"),
            ),
            pressure_blocks=20,
            explanation=(
                "Naive fair-share protects below-threshold fragments; abstract "
                "block scoring likes that, thresholded contiguous scoring does not."
            ),
        ),
        MaterializationRegime(
            name="footprint_pressure_density",
            capacity_blocks=80,
            prefixes=(
                p("small_hot", 30, 30, 9.0, "t2"),
                p("small_warm", 30, 30, 8.0, "t3"),
                p("bulky", 70, 70, 13.0, "t1"),
            ),
            pressure_blocks=20,
            explanation=(
                "Value-density spends scarce useful-prefix budget on compact "
                "claims instead of one bulky lower-density footprint."
            ),
        ),
        MaterializationRegime(
            name="complete_beats_naive",
            capacity_blocks=90,
            prefixes=(
                p("A", 50, 35, 8.0, "t1"),
                p("B", 50, 35, 7.0, "t2"),
                p("C", 30, 35, 4.0, "t3"),
            ),
            pressure_blocks=20,
            explanation=(
                "Complete-prefix fair-share refuses impossible fragments and "
                "keeps useful leading spans where naive equal shares do not."
            ),
        ),
        MaterializationRegime(
            name="fairness_tax_density_wins",
            capacity_blocks=100,
            prefixes=(
                p("low_value_tenant", 40, 40, 4.0, "t1"),
                p("hot_same_tenant", 40, 40, 20.0, "t2"),
                p("warm_same_tenant", 40, 40, 18.0, "t2"),
            ),
            pressure_blocks=20,
            explanation=(
                "Complete-prefix fair-share reserves a fair round for the "
                "low-value tenant; value-density uses both useful spans on the "
                "high-value tenant."
            ),
        ),
        MaterializationRegime(
            name="native_loose_pressure",
            capacity_blocks=180,
            prefixes=(
                p("A", 50, 35, 8.0, "t1"),
                p("B", 50, 35, 7.0, "t2"),
                p("C", 30, 20, 4.0, "t3"),
            ),
            pressure_blocks=0,
            pressure_level="loose",
            explanation=(
                "When pressure is loose, native/default already preserves the "
                "useful prefixes and active allocation has no upside."
            ),
        ),
        MaterializationRegime(
            name="priority_only_not_pin",
            capacity_blocks=80,
            prefixes=(
                p("A", 80, 80, 10.0, "t1"),
                p("B", 80, 80, 9.0, "t2"),
            ),
            pressure_blocks=10,
            explanation=(
                "Accepted protection is eviction priority over resident blocks; "
                "under hard pressure, protected blocks can still lose."
            ),
        ),
    ]
