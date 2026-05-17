"""Execution loop for the contiguous-prefix MicroRuntime MVP."""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from . import cache
from .model import (
    ActivePrefillClaim,
    ActivePrefillDecision,
    ClaimDecision,
    Prefix,
    ResidencyClaim,
    RuntimeState,
)
from .prefill import ActivePrefillAdmissionPolicy, CacheAllPrefillPolicy
from .policies import NativePolicy, ResidencyPolicy


class MicroRuntime:
    """Small ownership-level simulator for prefix residency policies."""

    def __init__(
        self,
        *,
        capacity_blocks: int,
        block_size_tokens: int = 16,
        policy: ResidencyPolicy | None = None,
        active_prefill_policy: ActivePrefillAdmissionPolicy | None = None,
    ) -> None:
        self.state = RuntimeState.empty(
            capacity_blocks=capacity_blocks,
            block_size_tokens=block_size_tokens,
        )
        self.policy = policy or NativePolicy()
        self.active_prefill_policy = active_prefill_policy or CacheAllPrefillPolicy()
        self.prefixes: dict[str, Prefix] = {}
        self.claims: dict[str, ResidencyClaim] = {}

    def register_prefixes(self, prefixes: Iterable[Prefix]) -> None:
        for prefix in prefixes:
            self.prefixes[prefix.prefix_id] = prefix

    def admit_claims(self, claims: Iterable[ResidencyClaim]) -> list[ClaimDecision]:
        claim_list = list(claims)
        for claim in claim_list:
            if claim.prefix_id not in self.prefixes:
                raise KeyError(f"claim references unknown prefix {claim.prefix_id!r}")

        decisions = self.policy.plan_claims(self.state, self.prefixes, claim_list)
        if len(decisions) != len(claim_list):
            raise RuntimeError("policy returned a mismatched number of decisions")

        claim_by_id = {claim.claim_id: claim for claim in claim_list}
        for decision in decisions:
            claim = claim_by_id[decision.claim_id]
            self._audit_decision(decision)
            self.claims[claim.claim_id] = claim
            self.state.decisions.append(decision)
            if decision.accepted_prefix_ranges:
                self.state.active_claims[claim.claim_id] = claim
                self.state.accepted_ranges_by_claim[claim.claim_id] = list(
                    decision.accepted_prefix_ranges
                )
                protected = cache.protect_existing_ranges(
                    self.state,
                    claim.claim_id,
                    claim.prefix_id,
                    decision.accepted_prefix_ranges,
                )
                decision.accepted_physical_blocks.update(protected)
            self._emit_claim_decision(decision)
        return decisions

    def prefill(
        self,
        prefix_id: str,
        *,
        active: bool = False,
        active_claim: ActivePrefillClaim | None = None,
    ) -> list[dict[str, Any]]:
        prefix = self.prefixes[prefix_id]
        self.state.step += 1
        pre_harm = self._threshold_status()
        prefill_decision: ActivePrefillDecision | None = None
        if active:
            active_claim = active_claim or ActivePrefillClaim.for_prefix(
                prefix,
                created_step=self.state.step,
            )
            prefill_decision = self.active_prefill_policy.decide(
                self.state,
                prefix,
                active_claim,
                self.prefixes,
            )
            self.state.active_prefill_decisions.append(prefill_decision)
            self._emit_active_prefill_decision(prefill_decision)
            if prefill_decision.decision == "cache_no_admit":
                self._emit_prefill_harm(prefix, prefill_decision, pre_harm)
                return []

        events = cache.materialize_prefix(
            self.state,
            prefix,
            self.policy,
            step=self.state.step,
            max_blocks=(
                prefill_decision.blocks_admitted
                if prefill_decision is not None
                else None
            ),
            eviction_priority=(
                prefill_decision.eviction_priority
                if prefill_decision is not None
                else 0.0
            ),
        )
        for event in events:
            event["step"] = self.state.step
            event["event_type"] = "prefill" if event["event"] == "insert" else event["event"]
            self.state.runtime_events.append(event)
        self._refresh_decision_physical_blocks()
        if prefill_decision is not None:
            self._emit_prefill_harm(prefix, prefill_decision, pre_harm)
        return events

    def prefill_many(self, prefix_ids: Iterable[str]) -> None:
        for prefix_id in prefix_ids:
            self.prefill(prefix_id)

    def pressure(self, pressure_blocks: int, *, prefix_id: str = "__pressure__") -> None:
        pressure_prefix = Prefix.with_block_count(
            prefix_id=f"{prefix_id}-{self.state.step + 1}",
            block_count=pressure_blocks,
            session_id=prefix_id,
            tenant_id=None,
            block_size_tokens=self.state.block_size_tokens,
            useful_threshold_blocks=pressure_blocks + 1,
            full_reuse_value=0.0,
        )
        self.register_prefixes([pressure_prefix])
        self.prefill(pressure_prefix.prefix_id, active=False)

    def return_prefix(self, prefix_id: str, *, recompute: bool = False) -> dict[str, Any]:
        prefix = self.prefixes[prefix_id]
        self.state.step += 1
        contiguous = cache.contiguous_surviving_blocks(self.state, prefix)
        total = cache.total_surviving_blocks(self.state, prefix)
        scattered = max(0, total - contiguous)
        cached_tokens = contiguous * self.state.block_size_tokens
        realized_value = prefix.value_for_contiguous_blocks(contiguous)
        threshold_blocks = prefix.threshold_blocks
        threshold_tokens = threshold_blocks * self.state.block_size_tokens
        threshold_crossed = contiguous >= threshold_blocks
        first_missing = None
        if contiguous < prefix.block_count:
            first_missing = contiguous
        event = {
            "event": "return",
            "event_type": "return",
            "step": self.state.step,
            "prefix_id": prefix_id,
            "total_surviving_blocks": total,
            "contiguous_survived_blocks": contiguous,
            "scattered_surviving_blocks": scattered,
            "cached_token_equivalent": cached_tokens,
            "realized_value": realized_value,
            "first_missing_block": first_missing,
            "threshold_blocks": threshold_blocks,
            "threshold_tokens": threshold_tokens,
            "threshold_rule": prefix.threshold_rule_label,
            "threshold_crossed": threshold_crossed,
        }
        self.state.runtime_events.append(event)
        if not threshold_crossed:
            self.state.audit_events.append(
                {
                    "event": "failure_label",
                    "step": self.state.step,
                    "prefix_id": prefix_id,
                    "failure_mode": "partial_prefix_waste"
                    if total > 0
                    else "underprotection",
                }
            )
        if recompute:
            cache.materialize_prefix(
                self.state,
                prefix,
                self.policy,
                step=self.state.step,
                replace_existing=True,
            )
            self._refresh_decision_physical_blocks()
        return event

    def prefix_position_ledger(self, prefix_id: str) -> list[dict[str, Any]]:
        prefix = self.prefixes[prefix_id]
        contiguous = cache.contiguous_surviving_blocks(self.state, prefix)
        threshold_blocks = prefix.threshold_blocks
        threshold_crossed = contiguous >= threshold_blocks
        rows: list[dict[str, Any]] = []
        for position in range(prefix.block_count):
            ledger_row = self.state.position_ledger.get((prefix_id, position), {})
            survived = position < contiguous or _position_survived(
                self.state, prefix_id, position
            )
            rows.append(
                {
                    "policy": self.policy.name,
                    "prefix_id": prefix_id,
                    "position_in_prefix": position,
                    "block_id": ledger_row.get("block_id"),
                    "accepted_range": ledger_row.get("accepted_range"),
                    "protected": bool(ledger_row.get("protected", False)),
                    "evicted_step": ledger_row.get("evicted_step"),
                    "survived_to_return": survived,
                    "leading_contiguous_blocks_at_return": contiguous,
                    "threshold_blocks": threshold_blocks,
                    "threshold_tokens": threshold_blocks * self.state.block_size_tokens,
                    "threshold_rule": prefix.threshold_rule_label,
                    "threshold_crossed": threshold_crossed,
                }
            )
        return rows

    def reset(self) -> None:
        next_step = self.state.step + 1
        self.state = RuntimeState.empty(
            capacity_blocks=self.state.capacity_blocks,
            block_size_tokens=self.state.block_size_tokens,
        )
        self.state.step = next_step
        self.claims.clear()
        self.state.runtime_events.append(
            {"event": "reset", "event_type": "reset", "step": self.state.step}
        )

    def realized_value(self, prefix_ids: Iterable[str]) -> float:
        return sum(
            self.prefixes[prefix_id].value_for_contiguous_blocks(
                cache.contiguous_surviving_blocks(self.state, self.prefixes[prefix_id])
            )
            for prefix_id in prefix_ids
        )

    def _audit_decision(self, decision: ClaimDecision) -> None:
        if getattr(self.policy, "is_oracle", False):
            decision.forbidden_fields_used = []
            return
        forbidden = sorted(
            field
            for field in decision.used_fields
            if field not in self.policy.admissible_fields
        )
        decision.forbidden_fields_used = forbidden
        if forbidden:
            self.state.audit_events.append(
                {
                    "event": "failure_label",
                    "failure_mode": "oracle_leakage",
                    "claim_id": decision.claim_id,
                    "forbidden_fields_used": forbidden,
                }
            )

    def _emit_claim_decision(self, decision: ClaimDecision) -> None:
        self.state.runtime_events.append(
            {
                "event": "claim_decision",
                "event_type": "claim",
                "step": self.state.step,
                "claim_id": decision.claim_id,
                "policy": decision.policy_name,
                "decision": decision.decision,
                "accepted_prefix_ranges": decision.accepted_prefix_ranges,
                "accepted_contiguous_prefix_blocks": (
                    decision.accepted_contiguous_prefix_blocks
                ),
                "reasons": decision.reasons,
                "cap_snapshot": decision.cap_snapshot,
                "pressure_snapshot": decision.pressure_snapshot,
                "used_fields": decision.used_fields,
                "forbidden_fields_used": decision.forbidden_fields_used,
            }
        )

    def _emit_active_prefill_decision(
        self, decision: ActivePrefillDecision
    ) -> None:
        self.state.runtime_events.append(
            {
                "event": "active_prefill_decision",
                "event_type": "prefill",
                "step": self.state.step,
                "claim_id": decision.claim_id,
                "prefix_id": decision.prefix_id,
                "decision": decision.decision,
                "admitted_prefix_range": decision.admitted_prefix_range,
                "blocks_admitted": decision.blocks_admitted,
                "eviction_priority": decision.eviction_priority,
                "reasons": decision.reasons,
                "used_fields": decision.used_fields,
            }
        )

    def _emit_prefill_harm(
        self,
        active_prefix: Prefix,
        decision: ActivePrefillDecision,
        before: dict[str, dict[str, Any]],
    ) -> None:
        after = self._threshold_status()
        evicted_ranges: dict[str, list[int]] = {}
        resident_thresholds_broken: list[str] = []
        cached_tokens_lost = 0
        value_lost = 0.0
        first_missing_moved: dict[str, dict[str, int | None]] = {}
        for prefix_id, before_row in before.items():
            if prefix_id == active_prefix.prefix_id:
                continue
            after_row = after.get(prefix_id)
            if after_row is None:
                continue
            if before_row["contiguous"] > after_row["contiguous"]:
                first_missing_moved[prefix_id] = {
                    "before": _first_missing_from_contiguous(
                        before_row["contiguous"],
                        before_row["block_count"],
                    ),
                    "after": _first_missing_from_contiguous(
                        after_row["contiguous"],
                        after_row["block_count"],
                    ),
                }
            if before_row["threshold_crossed"] and not after_row["threshold_crossed"]:
                resident_thresholds_broken.append(prefix_id)
            token_loss = max(0, before_row["contiguous"] - after_row["contiguous"])
            cached_tokens_lost += token_loss * self.state.block_size_tokens
            value_lost += max(0.0, before_row["value"] - after_row["value"])
            evicted_positions = [
                position
                for (ledger_prefix, position), row in self.state.position_ledger.items()
                if ledger_prefix == prefix_id and row.get("evicted_step") == self.state.step
            ]
            if evicted_positions:
                evicted_ranges[prefix_id] = evicted_positions

        active_value = 0.0
        self.state.audit_events.append(
            {
                "event": "prefill_harm",
                "step": self.state.step,
                "active_prefill_prefix": active_prefix.prefix_id,
                "active_prefill_decision": decision.decision,
                "blocks_admitted": decision.blocks_admitted,
                "resident_blocks_evicted": _compact_evicted_ranges(evicted_ranges),
                "resident_thresholds_broken": resident_thresholds_broken,
                "first_missing_moved": first_missing_moved,
                "cached_tokens_lost": cached_tokens_lost,
                "victim_value_lost": value_lost,
                "active_prefill_later_reused": False,
                "active_prefill_value_realized": active_value,
                "net_value_delta": active_value - value_lost,
            }
        )

    def _threshold_status(self) -> dict[str, dict[str, Any]]:
        status: dict[str, dict[str, Any]] = {}
        for prefix_id, prefix in self.prefixes.items():
            contiguous = cache.contiguous_surviving_blocks(self.state, prefix)
            value = prefix.value_for_contiguous_blocks(contiguous)
            status[prefix_id] = {
                "block_count": prefix.block_count,
                "contiguous": contiguous,
                "threshold_crossed": contiguous >= prefix.threshold_blocks,
                "value": value,
            }
        return status

    def _refresh_decision_physical_blocks(self) -> None:
        decision_by_claim = {decision.claim_id: decision for decision in self.state.decisions}
        for decision in decision_by_claim.values():
            decision.accepted_physical_blocks.clear()
        for claim_id, protected_blocks in self.state.protected_by_claim.items():
            decision = decision_by_claim.get(claim_id)
            if decision is not None:
                decision.accepted_physical_blocks.update(protected_blocks)


def _position_survived(state: RuntimeState, prefix_id: str, position: int) -> bool:
    for block_id in state.resident_by_prefix.get(prefix_id, set()):
        if state.blocks[block_id].position_in_prefix == position:
            return True
    return False


def _first_missing_from_contiguous(contiguous: int, block_count: int) -> int | None:
    if contiguous >= block_count:
        return None
    return contiguous


def _compact_evicted_ranges(evicted: dict[str, list[int]]) -> list[str]:
    rows: list[str] = []
    for prefix_id, positions in evicted.items():
        if not positions:
            continue
        sorted_positions = sorted(positions)
        start = prev = sorted_positions[0]
        for position in sorted_positions[1:]:
            if position == prev + 1:
                prev = position
                continue
            rows.append(f"{prefix_id}[{start}:{prev + 1}]")
            start = prev = position
        rows.append(f"{prefix_id}[{start}:{prev + 1}]")
    return rows
