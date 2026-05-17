"""Materialization/value surfaces for policy explanations."""

from __future__ import annotations

from enum import StrEnum

from kvrt import cache
from kvrt.model import Prefix, RuntimeState


class MaterializationSurface(StrEnum):
    """Ways to translate surviving cache blocks into reuse value."""

    ABSTRACT_BLOCK_VALUE = "abstract_block_value"
    TOTAL_CACHED_TOKENS = "total_cached_tokens"
    LEADING_CONTIGUOUS_TOKENS = "leading_contiguous_tokens"
    THRESHOLDED_LEADING_PREFIX = "thresholded_leading_prefix"
    PRIORITY_ONLY_PROXY = "priority_only_proxy"
    DIRECT_OWNERSHIP_PROXY = "direct_ownership_proxy"
    # Backward-compatible surface names used by early reports.
    CONTIGUOUS_PREFIX_VALUE = "contiguous_prefix_value"
    THRESHOLDED_CONTIGUOUS_VALUE = "thresholded_contiguous_value"
    PRIORITY_ONLY_EVICTION = "priority_only_eviction"


def score_prefix(
    state: RuntimeState,
    prefix: Prefix,
    surface: MaterializationSurface,
) -> float:
    """Score one prefix under a materialization/value surface."""

    total = cache.total_surviving_blocks(state, prefix)
    contiguous = cache.contiguous_surviving_blocks(state, prefix)
    if prefix.block_count == 0:
        return 0.0
    if surface == MaterializationSurface.ABSTRACT_BLOCK_VALUE:
        return prefix.full_reuse_value * (total / prefix.block_count)
    if surface == MaterializationSurface.TOTAL_CACHED_TOKENS:
        return float(total * state.block_size_tokens)
    if surface == MaterializationSurface.LEADING_CONTIGUOUS_TOKENS:
        return float(contiguous * state.block_size_tokens)
    if surface == MaterializationSurface.CONTIGUOUS_PREFIX_VALUE:
        return prefix.full_reuse_value * (contiguous / prefix.block_count)
    if surface in {
        MaterializationSurface.THRESHOLDED_LEADING_PREFIX,
        MaterializationSurface.THRESHOLDED_CONTIGUOUS_VALUE,
        MaterializationSurface.PRIORITY_ONLY_PROXY,
        MaterializationSurface.DIRECT_OWNERSHIP_PROXY,
        MaterializationSurface.PRIORITY_ONLY_EVICTION,
    }:
        return prefix.value_for_contiguous_blocks(contiguous)
    raise ValueError(f"unsupported materialization surface: {surface}")


def score_state(
    state: RuntimeState,
    prefixes: list[Prefix],
    surface: MaterializationSurface,
) -> float:
    return sum(score_prefix(state, prefix, surface) for prefix in prefixes)
