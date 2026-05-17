"""Minimal ResidentClaim contract model for conformance tests.

This module intentionally sits beside the broader MicroRuntime research model.
Paper 1 needs a small semantic surface: what was claimed, what the runtime
accepted, what predicate defines useful materialization, and when loss becomes
claim harm.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Iterable


class ProtectionMode(str, Enum):
    SOFT_PRIORITY = "soft_priority"
    HARD_PROTECTED = "hard_protected"
    DEMOTABLE = "demotable"
    OFFLOADABLE = "offloadable"
    EXPIRING = "expiring"
    BEST_EFFORT = "best_effort"


class ClaimDecisionKind(str, Enum):
    ACCEPTED = "accepted"
    REJECTED = "rejected"
    CONDITIONALLY_ACCEPTED = "conditionally_accepted"


class ClaimStateKind(str, Enum):
    SUBMITTED = "submitted"
    ACCEPTED = "accepted"
    MATERIALIZED = "materialized"
    DEMOTED = "demoted"
    EXPIRED = "expired"
    REFUSED = "refused"
    HARMED = "harmed"


class ClaimEventType(str, Enum):
    CLAIM_SUBMITTED = "resident_claim_submitted"
    CLAIM_ACCEPTED = "resident_claim_accepted"
    CLAIM_REJECTED = "resident_claim_rejected"
    CLAIM_MATERIALIZED = "resident_claim_materialized"
    CLAIM_DEMOTED = "resident_claim_demoted"
    CLAIM_EXPIRED = "resident_claim_expired"
    CLAIM_HARMED = "resident_claim_harmed"
    ACTIVE_REFUSED = "active_request_refused"
    ACTIVE_DEFERRED = "active_request_deferred"


@dataclass(frozen=True)
class CacheIdentity:
    """Cache equivalence domain for a resident claim."""

    cache_key_domain: str
    model_id: str
    tokenizer_id: str
    salt_namespace: str
    block_size: int
    adapter_id: str | None = None
    prompt_embedding_id: str | None = None
    kv_format: str = "opaque"

    def __post_init__(self) -> None:
        required_strings = {
            "cache_key_domain": self.cache_key_domain,
            "model_id": self.model_id,
            "tokenizer_id": self.tokenizer_id,
            "salt_namespace": self.salt_namespace,
            "kv_format": self.kv_format,
        }
        for field_name, value in required_strings.items():
            if not value:
                raise ValueError(f"{field_name} must be non-empty")
        if self.block_size <= 0:
            raise ValueError("block_size must be positive")


@dataclass(frozen=True)
class PredicateResult:
    materialized: bool
    surviving_blocks: int
    leading_blocks: int
    required_blocks: int

    def to_record(self) -> dict[str, int | bool]:
        return {
            "materialized": self.materialized,
            "surviving_blocks": self.surviving_blocks,
            "leading_blocks": self.leading_blocks,
            "required_blocks": self.required_blocks,
        }


@dataclass(frozen=True)
class MaterializationPredicate:
    """Executable predicate over surviving logical block positions."""

    predicate_type: str
    required_blocks: int
    start_block: int = 0

    @classmethod
    def leading_prefix_at_least(cls, required_blocks: int) -> "MaterializationPredicate":
        return cls("leading_prefix_at_least", required_blocks=required_blocks)

    @classmethod
    def contiguous_range(
        cls, start_block: int, required_blocks: int
    ) -> "MaterializationPredicate":
        return cls(
            "contiguous_range",
            required_blocks=required_blocks,
            start_block=start_block,
        )

    def __post_init__(self) -> None:
        if self.required_blocks < 0:
            raise ValueError("required_blocks must be non-negative")
        if self.start_block < 0:
            raise ValueError("start_block must be non-negative")
        if self.predicate_type not in {
            "leading_prefix_at_least",
            "contiguous_range",
        }:
            raise ValueError(f"unsupported predicate_type: {self.predicate_type}")

    def evaluate(self, surviving_positions: Iterable[int]) -> PredicateResult:
        surviving = {int(position) for position in surviving_positions}
        leading = 0
        while leading in surviving:
            leading += 1

        if self.predicate_type == "leading_prefix_at_least":
            materialized = leading >= self.required_blocks
        else:
            end = self.start_block + self.required_blocks
            materialized = all(position in surviving for position in range(self.start_block, end))

        return PredicateResult(
            materialized=materialized,
            surviving_blocks=len(surviving),
            leading_blocks=leading,
            required_blocks=self.required_blocks,
        )

    def to_record(self) -> dict[str, int | str]:
        return {
            "predicate_type": self.predicate_type,
            "required_blocks": self.required_blocks,
            "start_block": self.start_block,
        }


@dataclass(frozen=True)
class ResidentClaimInput:
    claim_id: str
    owner_scope: str
    cache_identity: CacheIdentity
    object_id: str
    materialization_predicate: MaterializationPredicate
    footprint_blocks: int
    protection_mode: ProtectionMode
    duration_steps: int | None = None

    def __post_init__(self) -> None:
        if not self.claim_id:
            raise ValueError("claim_id must be non-empty")
        if not self.owner_scope:
            raise ValueError("owner_scope must be non-empty")
        if not self.object_id:
            raise ValueError("object_id must be non-empty")
        if self.footprint_blocks <= 0:
            raise ValueError("footprint_blocks must be positive")
        if self.duration_steps is not None and self.duration_steps <= 0:
            raise ValueError("duration_steps must be positive when provided")


@dataclass(frozen=True)
class ResidentClaimDecision:
    claim_id: str
    decision: ClaimDecisionKind
    step: int
    reason: str


@dataclass
class ResidentClaimState:
    claim: ResidentClaimInput
    state: ClaimStateKind = ClaimStateKind.SUBMITTED
    accepted_step: int | None = None
    release_step: int | None = None
    release_reason: ClaimEventType | None = None

    def accept(self, step: int) -> ResidentClaimDecision:
        self.state = ClaimStateKind.ACCEPTED
        self.accepted_step = step
        return ResidentClaimDecision(
            claim_id=self.claim.claim_id,
            decision=ClaimDecisionKind.ACCEPTED,
            step=step,
            reason="accepted",
        )

    def release(self, step: int, event_type: ClaimEventType) -> None:
        if event_type == ClaimEventType.CLAIM_DEMOTED:
            self.state = ClaimStateKind.DEMOTED
        elif event_type == ClaimEventType.CLAIM_EXPIRED:
            self.state = ClaimStateKind.EXPIRED
        elif event_type == ClaimEventType.CLAIM_REJECTED:
            self.state = ClaimStateKind.REFUSED
        else:
            raise ValueError(f"unsupported release event: {event_type}")
        self.release_step = step
        self.release_reason = event_type

    @property
    def under_runtime_responsibility(self) -> bool:
        return (
            self.state in {ClaimStateKind.ACCEPTED, ClaimStateKind.MATERIALIZED}
            and self.accepted_step is not None
            and self.release_step is None
        )


@dataclass(frozen=True)
class ClaimEvent:
    event_type: ClaimEventType
    claim_id: str
    step: int
    request_id: str | None = None
    fields: dict[str, Any] = field(default_factory=dict)

    def to_record(self) -> dict[str, Any]:
        record = {
            "event": self.event_type.value,
            "claim_id": self.claim_id,
            "step": self.step,
            "request_id": self.request_id,
        }
        record.update(self.fields)
        return record


def predicate_breaking_harm_event(
    state: ResidentClaimState,
    *,
    before_positions: Iterable[int],
    after_positions: Iterable[int],
    step: int,
    cause: str,
    request_id: str | None = None,
) -> ClaimEvent | None:
    """Return a claim-harm event only for accepted, unreleased claims."""

    if not state.under_runtime_responsibility:
        return None

    before = state.claim.materialization_predicate.evaluate(before_positions)
    after = state.claim.materialization_predicate.evaluate(after_positions)
    if not before.materialized or after.materialized:
        return None

    state.state = ClaimStateKind.HARMED
    return ClaimEvent(
        event_type=ClaimEventType.CLAIM_HARMED,
        claim_id=state.claim.claim_id,
        step=step,
        request_id=request_id,
        fields={
            "cause": cause,
            "predicate_before": before.to_record(),
            "predicate_after": after.to_record(),
        },
    )
