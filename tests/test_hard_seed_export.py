from __future__ import annotations

import json

from kvrt.export import build_selected_hard_seeds, write_hard_seed_exports


def test_selected_hard_seeds_include_required_exports() -> None:
    seeds = build_selected_hard_seeds()

    assert [seed.seed_id for seed in seeds] == [
        "hard-seed-fair_share_fragmentation",
        "hard-seed-footprint_pressure_density",
        "hard-seed-fairness_tax_density_wins",
    ]
    for seed in seeds:
        assert seed.expected_abstract_block_ordering.ordered_policies
        assert seed.expected_thresholded_contiguous_ordering.ordered_policies
        assert (
            seed.expected_live_vllm_ordering_if_blockpool_is_thresholded
            == seed.expected_thresholded_contiguous_ordering.ordered_policies
        )
        assert "Falsified if" in seed.exact_falsifier
        assert "BlockPool" in seed.required_materialization_surface
        assert any(event["event_type"] == "pressure" for event in seed.event_sequence)
        assert seed.pressure_decomposition["explicit_pressure_blocks"] > 0
        assert "policy_separation_margin" in seed.export_quality
        assert "surface_disagreement_score" in seed.export_quality
        assert "expected_live_falsifier" in seed.export_quality


def test_fragmentation_seed_is_the_abstract_to_thresholded_inversion() -> None:
    seed = build_selected_hard_seeds()[0]

    assert seed.seed_id == "hard-seed-fair_share_fragmentation"
    assert seed.expected_abstract_block_ordering.ordered_policies[0] == (
        "naive_fair_share"
    )
    assert seed.expected_thresholded_contiguous_ordering.scores[
        "naive_fair_share"
    ] == 0.0
    assert (
        seed.expected_thresholded_contiguous_ordering.scores[
            "complete_prefix_fair_share"
        ]
        == 18.0
    )
    assert "thresholded survival predicts naive_fair_share collapses" in (
        seed.exact_falsifier
    )
    assert seed.prefixes[0]["threshold_blocks"] == 40
    assert seed.prefixes[0]["threshold_tokens"] == 640
    assert seed.prefixes[0]["threshold_rule"] == "fixed_blocks:40"


def test_hard_seed_export_writes_json_and_decision_note(tmp_path) -> None:
    seeds_path, decision_path = write_hard_seed_exports(tmp_path)

    exported = json.loads(seeds_path.read_text(encoding="utf-8"))
    decision = decision_path.read_text(encoding="utf-8")

    assert len(exported) == 3
    assert exported[0]["seed_id"] == "hard-seed-fair_share_fragmentation"
    assert "Does live BlockPool behavior follow" in decision
    assert "does not justify broader policy families" in decision
