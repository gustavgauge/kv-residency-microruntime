"""Ablations that isolate prefix position from retained block count."""

from __future__ import annotations

from kvrt import cache
from kvrt.eval.surfaces import MaterializationSurface, score_state
from kvrt.model import Prefix, RuntimeState


def same_retained_count_position_ablation() -> dict[str, dict[str, float]]:
    """Compare equal retained counts at different prefix positions."""

    prefix = Prefix.with_block_count(
        "A",
        60,
        useful_threshold_blocks=40,
        full_reuse_value=10.0,
    )
    leading = _state_with_retained_positions(prefix, range(0, 40))
    tail = _state_with_retained_positions(prefix, range(20, 60))
    return {
        "leading_A_0_40": _score_ablation_state(leading, prefix),
        "tail_A_20_60": _score_ablation_state(tail, prefix),
    }


def _score_ablation_state(
    state: RuntimeState,
    prefix: Prefix,
) -> dict[str, float]:
    return {
        "retained_blocks": float(cache.total_surviving_blocks(state, prefix)),
        "leading_contiguous_blocks": float(
            cache.contiguous_surviving_blocks(state, prefix)
        ),
        "abstract_block_value": score_state(
            state, [prefix], MaterializationSurface.ABSTRACT_BLOCK_VALUE
        ),
        "thresholded_leading_prefix": score_state(
            state, [prefix], MaterializationSurface.THRESHOLDED_LEADING_PREFIX
        ),
    }


def _state_with_retained_positions(prefix: Prefix, positions) -> RuntimeState:
    state = RuntimeState.empty(capacity_blocks=prefix.block_count)
    for block_id, position in enumerate(positions):
        block = state.blocks[block_id]
        block.owner_prefix_id = prefix.prefix_id
        block.position_in_prefix = position
        block.state = "resident"
        block.last_touched_step = 1
        state.resident_by_prefix.setdefault(prefix.prefix_id, set()).add(block_id)
        state.free_queue.append(block_id)
        state.free_blocks.remove(block_id)
        state.position_ledger[(prefix.prefix_id, position)] = {
            "prefix_id": prefix.prefix_id,
            "position_in_prefix": position,
            "block_id": block_id,
            "accepted_range": None,
            "protected": False,
            "inserted_step": 1,
            "evicted_step": None,
        }
    cache.validate_state(state)
    return state
