"""Cache ownership and eviction behavior for the MVP runtime."""

from __future__ import annotations

from collections.abc import Iterable
from typing import Protocol

from .model import Block, Prefix, RuntimeState


class EvictionPolicy(Protocol):
    name: str

    def eviction_key(self, state: RuntimeState, block: Block) -> tuple:
        ...


class CacheInvariantError(RuntimeError):
    """Raised when the simulated cache state violates ownership invariants."""


def validate_state(state: RuntimeState) -> None:
    resident_seen: dict[str, set[int]] = {}
    free_seen: set[int] = set()

    for block_id, block in state.blocks.items():
        if block.state == "free":
            free_seen.add(block_id)
            if block.owner_prefix_id is not None or block.protection_claim_ids:
                raise CacheInvariantError(f"free block {block_id} carries ownership")
        elif block.state == "resident":
            if block.owner_prefix_id is None or block.position_in_prefix is None:
                raise CacheInvariantError(f"resident block {block_id} lacks ownership")
            resident_seen.setdefault(block.owner_prefix_id, set()).add(block_id)
        elif block.state == "evicted":
            if block.protection_claim_ids:
                raise CacheInvariantError(f"evicted block {block_id} is protected")
        else:
            raise CacheInvariantError(f"unknown block state {block.state!r}")

    if resident_seen != state.resident_by_prefix:
        raise CacheInvariantError("resident_by_prefix does not match block ownership")

    if free_seen != set(state.free_blocks):
        raise CacheInvariantError("free_blocks does not match block states")

    for claim_id, protected_blocks in state.protected_by_claim.items():
        for block_id in protected_blocks:
            block = state.blocks[block_id]
            if block.state != "resident":
                raise CacheInvariantError(
                    f"claim {claim_id} protects non-resident block {block_id}"
                )
            if claim_id not in block.protection_claim_ids:
                raise CacheInvariantError(
                    f"protected_by_claim missing reciprocal block annotation"
                )

    if state.used_blocks > state.capacity_blocks:
        raise CacheInvariantError("used blocks exceed capacity")


def materialize_prefix(
    state: RuntimeState,
    prefix: Prefix,
    policy: EvictionPolicy,
    *,
    step: int,
    replace_existing: bool = False,
    max_blocks: int | None = None,
    eviction_priority: float = 0.0,
) -> list[dict]:
    """Insert a full prefix into the cache, evicting as needed."""

    events: list[dict] = []
    if replace_existing:
        for block_id in sorted(state.resident_by_prefix.get(prefix.prefix_id, set())):
            free_block(state, block_id, step=step)

    admitted_blocks = prefix.block_count if max_blocks is None else max(0, max_blocks)
    admitted_blocks = min(admitted_blocks, prefix.block_count)
    for position in range(admitted_blocks):
        if _position_is_resident(state, prefix.prefix_id, position):
            continue
        block_id = _allocate_free_block(state, policy, step=step, events=events)
        block = state.blocks[block_id]
        block.owner_prefix_id = prefix.prefix_id
        block.position_in_prefix = position
        block.state = "resident"
        block.last_touched_step = step
        block.hash_key = f"{prefix.prefix_id}:{position}"
        block.protection_claim_ids = _claim_ids_for_position(state, prefix.prefix_id, position)
        if block.protection_claim_ids:
            block.eviction_priority = 1.0
        else:
            block.eviction_priority = eviction_priority
        state.resident_by_prefix.setdefault(prefix.prefix_id, set()).add(block_id)
        state.free_queue.append(block_id)
        for claim_id in block.protection_claim_ids:
            state.protected_by_claim.setdefault(claim_id, set()).add(block_id)
        state.position_ledger[(prefix.prefix_id, position)] = {
            "prefix_id": prefix.prefix_id,
            "position_in_prefix": position,
            "block_id": block_id,
            "accepted_range": _accepted_range_for_position(
                state, prefix.prefix_id, position
            ),
            "protected": bool(block.protection_claim_ids),
            "inserted_step": step,
            "evicted_step": None,
        }
        events.append(
            {
                "event": "insert",
                "block_id": block_id,
                "prefix_id": prefix.prefix_id,
                "position_in_prefix": position,
                "protection_claim_ids": sorted(block.protection_claim_ids),
            }
        )

    validate_state(state)
    return events


def evict_one(
    state: RuntimeState,
    policy: EvictionPolicy,
    *,
    step: int,
    reason: str,
) -> dict:
    resident_blocks = [
        block for block in state.blocks.values() if block.state == "resident"
    ]
    if not resident_blocks:
        raise CacheInvariantError("cannot evict from an empty resident set")

    victim = min(resident_blocks, key=lambda block: policy.eviction_key(state, block))
    event = {
        "event": "evict",
        "block_id": victim.block_id,
        "owner_prefix_id": victim.owner_prefix_id,
        "position_in_prefix": victim.position_in_prefix,
        "protection_claim_ids": sorted(victim.protection_claim_ids),
        "protection_priority": victim.eviction_priority,
        "reason": reason,
        "step": step,
    }
    if victim.owner_prefix_id is not None and victim.position_in_prefix is not None:
        row = state.position_ledger.get(
            (victim.owner_prefix_id, victim.position_in_prefix)
        )
        if row is not None:
            row["evicted_step"] = step
    free_block(state, victim.block_id, step=step)
    return event


def free_block(state: RuntimeState, block_id: int, *, step: int) -> None:
    block = state.blocks[block_id]
    if block.state == "resident" and block.owner_prefix_id is not None:
        resident = state.resident_by_prefix.get(block.owner_prefix_id)
        if resident is not None:
            resident.discard(block_id)
            if not resident:
                del state.resident_by_prefix[block.owner_prefix_id]
    for claim_id in list(block.protection_claim_ids):
        protected = state.protected_by_claim.get(claim_id)
        if protected is not None:
            protected.discard(block_id)
            if not protected:
                del state.protected_by_claim[claim_id]
    try:
        state.free_queue.remove(block_id)
    except ValueError:
        pass
    block.clear(step=step, state="free")
    if block_id not in state.free_blocks:
        state.free_blocks.append(block_id)


def protect_existing_ranges(
    state: RuntimeState,
    claim_id: str,
    prefix_id: str,
    ranges: Iterable[tuple[int, int]],
) -> set[int]:
    protected: set[int] = set()
    for block_id in state.resident_by_prefix.get(prefix_id, set()):
        block = state.blocks[block_id]
        if block.position_in_prefix is None:
            continue
        if any(start <= block.position_in_prefix < end for start, end in ranges):
            block.protection_claim_ids.add(claim_id)
            block.eviction_priority = max(block.eviction_priority, 1.0)
            protected.add(block_id)
    if protected:
        state.protected_by_claim.setdefault(claim_id, set()).update(protected)
    validate_state(state)
    return protected


def contiguous_surviving_blocks(state: RuntimeState, prefix: Prefix) -> int:
    resident_positions = _resident_positions(state, prefix.prefix_id)
    count = 0
    while count in resident_positions:
        count += 1
    return count


def total_surviving_blocks(state: RuntimeState, prefix: Prefix) -> int:
    return len(_resident_positions(state, prefix.prefix_id))


def _allocate_free_block(
    state: RuntimeState,
    policy: EvictionPolicy,
    *,
    step: int,
    events: list[dict],
) -> int:
    while not state.free_blocks:
        events.append(evict_one(state, policy, step=step, reason="capacity_pressure"))
    return state.free_blocks.popleft()


def _claim_ids_for_position(
    state: RuntimeState, prefix_id: str, position: int
) -> set[str]:
    claim_ids: set[str] = set()
    for claim_id, claim in state.active_claims.items():
        if claim.prefix_id != prefix_id:
            continue
        ranges = state.accepted_ranges_by_claim.get(claim_id, [])
        if any(start <= position < end for start, end in ranges):
            claim_ids.add(claim_id)
    return claim_ids


def _accepted_range_for_position(
    state: RuntimeState, prefix_id: str, position: int
) -> list[int] | None:
    for claim in state.active_claims.values():
        if claim.prefix_id != prefix_id:
            continue
        for start, end in state.accepted_ranges_by_claim.get(claim.claim_id, []):
            if start <= position < end:
                return [start, end]
    return None


def _position_is_resident(state: RuntimeState, prefix_id: str, position: int) -> bool:
    return position in _resident_positions(state, prefix_id)


def _resident_positions(state: RuntimeState, prefix_id: str) -> set[int]:
    positions: set[int] = set()
    for block_id in state.resident_by_prefix.get(prefix_id, set()):
        position = state.blocks[block_id].position_in_prefix
        if position is not None:
            positions.add(position)
    return positions
