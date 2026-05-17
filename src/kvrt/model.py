"""Core data model for the KV Residency MicroRuntime MVP."""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from math import ceil
from typing import Any, Literal


BlockState = Literal["free", "resident", "evicted"]
ClaimDecisionKind = Literal["accept", "partial_accept", "refuse", "fallback_native"]
EventType = Literal["prefill", "return", "pressure", "claim", "expire", "reset"]
PartialReuseCurve = Literal["threshold", "linear", "vllm_cached_tokens"]
ActivePrefillDecisionKind = Literal[
    "cache_admit",
    "cache_no_admit",
    "cache_partial",
    "cache_demote",
    "cache_if_value_density",
]
ThresholdRuleName = Literal[
    "fixed_blocks",
    "fraction",
    "full_prefix",
    "latency_value",
    "tenant_sla",
]


@dataclass(frozen=True)
class ThresholdRule:
    """Rule for converting prefix metadata into a usefulness threshold."""

    rule: ThresholdRuleName = "fixed_blocks"
    value: float | int | None = None
    tenant_thresholds: dict[str, int] = field(default_factory=dict)

    def blocks_for(self, prefix: "Prefix", fallback_blocks: int) -> int:
        if self.rule == "fixed_blocks":
            threshold = fallback_blocks if self.value is None else int(self.value)
        elif self.rule == "fraction":
            fraction = 1.0 if self.value is None else float(self.value)
            threshold = ceil(prefix.block_count * fraction)
        elif self.rule == "full_prefix":
            threshold = prefix.block_count
        elif self.rule == "latency_value":
            threshold = fallback_blocks if self.value is None else int(self.value)
        elif self.rule == "tenant_sla":
            if prefix.tenant_id is not None and prefix.tenant_id in self.tenant_thresholds:
                threshold = self.tenant_thresholds[prefix.tenant_id]
            else:
                threshold = fallback_blocks if self.value is None else int(self.value)
        else:
            raise ValueError(f"unsupported threshold rule: {self.rule}")
        return max(0, threshold)

    def label(self) -> str:
        if self.rule == "fixed_blocks" and self.value is None:
            return "fixed_blocks"
        if self.rule == "tenant_sla" and self.tenant_thresholds:
            return "tenant_sla"
        return f"{self.rule}:{self.value}"


@dataclass(frozen=True)
class Prefix:
    """A logical, ordered reusable KV prefix."""

    prefix_id: str
    session_id: str
    tenant_id: str | None
    blocks: tuple[int, ...]
    token_count: int
    useful_threshold_blocks: int
    full_reuse_value: float
    partial_reuse_curve: PartialReuseCurve = "threshold"
    threshold_rule: ThresholdRule | None = None

    @classmethod
    def with_block_count(
        cls,
        prefix_id: str,
        block_count: int,
        *,
        session_id: str | None = None,
        tenant_id: str | None = None,
        block_size_tokens: int = 16,
        useful_threshold_blocks: int,
        full_reuse_value: float,
        partial_reuse_curve: PartialReuseCurve = "threshold",
        threshold_rule: ThresholdRule | None = None,
    ) -> "Prefix":
        return cls(
            prefix_id=prefix_id,
            session_id=session_id or prefix_id,
            tenant_id=tenant_id,
            blocks=tuple(range(block_count)),
            token_count=block_count * block_size_tokens,
            useful_threshold_blocks=useful_threshold_blocks,
            full_reuse_value=full_reuse_value,
            partial_reuse_curve=partial_reuse_curve,
            threshold_rule=threshold_rule,
        )

    @property
    def block_count(self) -> int:
        return len(self.blocks)

    @property
    def threshold_blocks(self) -> int:
        rule = self.threshold_rule or ThresholdRule(
            "fixed_blocks", self.useful_threshold_blocks
        )
        return rule.blocks_for(self, self.useful_threshold_blocks)

    @property
    def threshold_rule_label(self) -> str:
        rule = self.threshold_rule or ThresholdRule(
            "fixed_blocks", self.useful_threshold_blocks
        )
        return rule.label()

    def value_for_contiguous_blocks(self, contiguous_blocks: int) -> float:
        """Return realized reuse value from a leading contiguous surviving span."""

        contiguous_blocks = max(0, min(contiguous_blocks, self.block_count))
        if self.partial_reuse_curve == "threshold":
            return (
                self.full_reuse_value
                if contiguous_blocks >= self.threshold_blocks
                else 0.0
            )
        if self.partial_reuse_curve == "linear":
            if self.block_count == 0:
                return 0.0
            return self.full_reuse_value * (contiguous_blocks / self.block_count)
        if self.partial_reuse_curve == "vllm_cached_tokens":
            return float(contiguous_blocks)
        raise ValueError(f"unsupported partial reuse curve: {self.partial_reuse_curve}")


@dataclass(frozen=True)
class PrefixSegment:
    prefix_id: str
    start_pos: int
    end_pos: int
    physical_blocks: tuple[int, ...]
    useful: bool


@dataclass
class Block:
    block_id: int
    owner_prefix_id: str | None = None
    position_in_prefix: int | None = None
    state: BlockState = "free"
    last_touched_step: int = 0
    protection_claim_ids: set[str] = field(default_factory=set)
    eviction_priority: float = 0.0
    hash_key: str | None = None

    def clear(self, *, step: int, state: BlockState = "free") -> None:
        self.owner_prefix_id = None
        self.position_in_prefix = None
        self.state = state
        self.last_touched_step = step
        self.protection_claim_ids.clear()
        self.eviction_priority = 0.0
        self.hash_key = None


@dataclass(frozen=True)
class ResidencyClaim:
    claim_id: str
    prefix_id: str
    session_id: str
    tenant_id: str | None
    declared_value: float
    declared_deadline: int | None
    expected_return_step: int | None
    confidence: float
    trust_score: float
    claimed_footprint_blocks: int
    max_budget_blocks: int | None
    priority: float | None
    duration_steps: int | None
    source: str
    created_step: int

    @classmethod
    def for_prefix(
        cls,
        prefix: Prefix,
        *,
        declared_value: float | None = None,
        claimed_footprint_blocks: int | None = None,
        claim_id: str | None = None,
        created_step: int = 0,
        source: str = "synthetic",
    ) -> "ResidencyClaim":
        return cls(
            claim_id=claim_id or f"claim-{prefix.prefix_id}",
            prefix_id=prefix.prefix_id,
            session_id=prefix.session_id,
            tenant_id=prefix.tenant_id,
            declared_value=(
                prefix.full_reuse_value if declared_value is None else declared_value
            ),
            declared_deadline=None,
            expected_return_step=None,
            confidence=1.0,
            trust_score=1.0,
            claimed_footprint_blocks=(
                prefix.block_count
                if claimed_footprint_blocks is None
                else claimed_footprint_blocks
            ),
            max_budget_blocks=None,
            priority=None,
            duration_steps=None,
            source=source,
            created_step=created_step,
        )


@dataclass(frozen=True)
class ActivePrefillClaim:
    """Claim to admit newly computed active-request KV into reusable cache."""

    claim_id: str
    prefix_id: str
    declared_value: float
    expected_return_step: int | None
    claimed_footprint_blocks: int
    source: str
    created_step: int

    @classmethod
    def for_prefix(
        cls,
        prefix: Prefix,
        *,
        claim_id: str | None = None,
        declared_value: float | None = None,
        expected_return_step: int | None = None,
        created_step: int = 0,
        source: str = "active_prefill",
    ) -> "ActivePrefillClaim":
        return cls(
            claim_id=claim_id or f"active-prefill-{prefix.prefix_id}",
            prefix_id=prefix.prefix_id,
            declared_value=(
                prefix.full_reuse_value if declared_value is None else declared_value
            ),
            expected_return_step=expected_return_step,
            claimed_footprint_blocks=prefix.block_count,
            source=source,
            created_step=created_step,
        )


@dataclass
class ActivePrefillDecision:
    claim_id: str
    prefix_id: str
    decision: ActivePrefillDecisionKind
    admitted_prefix_range: tuple[int, int] | None
    blocks_admitted: int
    eviction_priority: float
    score: float
    reasons: list[str]
    used_fields: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class PrefixTruth:
    prefix_id: str
    true_return_step: int | None
    true_value: float
    true_reuse_probability: float
    true_required_blocks: int


@dataclass
class ClaimDecision:
    claim_id: str
    decision: ClaimDecisionKind
    accepted_prefix_ranges: list[tuple[int, int]]
    accepted_contiguous_prefix_blocks: int
    accepted_physical_blocks: set[int]
    score: float
    reasons: list[str]
    policy_name: str
    pressure_snapshot: float
    cap_snapshot: int
    used_fields: dict[str, str] = field(default_factory=dict)
    forbidden_fields_used: list[str] = field(default_factory=list)

    @property
    def accepted_blocks(self) -> int:
        return sum(end - start for start, end in self.accepted_prefix_ranges)


@dataclass
class TraceEvent:
    step: int
    event_type: EventType
    prefix_id: str | None
    session_id: str | None
    pressure_blocks: int = 0
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class RuntimeState:
    capacity_blocks: int
    block_size_tokens: int
    blocks: dict[int, Block]
    free_blocks: deque[int]
    free_queue: deque[int]
    resident_by_prefix: dict[str, set[int]] = field(default_factory=dict)
    protected_by_claim: dict[str, set[int]] = field(default_factory=dict)
    active_claims: dict[str, ResidencyClaim] = field(default_factory=dict)
    active_prefill_decisions: list[ActivePrefillDecision] = field(default_factory=list)
    decisions: list[ClaimDecision] = field(default_factory=list)
    accepted_ranges_by_claim: dict[str, list[tuple[int, int]]] = field(
        default_factory=dict
    )
    position_ledger: dict[tuple[str, int], dict[str, Any]] = field(default_factory=dict)
    step: int = 0
    runtime_events: list[dict[str, Any]] = field(default_factory=list)
    audit_events: list[dict[str, Any]] = field(default_factory=list)

    @classmethod
    def empty(cls, capacity_blocks: int, block_size_tokens: int = 16) -> "RuntimeState":
        blocks = {block_id: Block(block_id=block_id) for block_id in range(capacity_blocks)}
        return cls(
            capacity_blocks=capacity_blocks,
            block_size_tokens=block_size_tokens,
            blocks=blocks,
            free_blocks=deque(blocks),
            free_queue=deque(),
        )

    @property
    def used_blocks(self) -> int:
        return sum(1 for block in self.blocks.values() if block.state == "resident")

    @property
    def pressure_snapshot(self) -> float:
        if self.capacity_blocks == 0:
            return 1.0
        return self.used_blocks / self.capacity_blocks
