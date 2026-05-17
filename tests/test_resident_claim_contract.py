import pytest

from kvrt.contract import (
    CacheIdentity,
    ClaimEventType,
    ClaimStateKind,
    MaterializationPredicate,
    ProtectionMode,
    ResidentClaimInput,
    ResidentClaimState,
    predicate_breaking_harm_event,
)


def cache_identity() -> CacheIdentity:
    return CacheIdentity(
        cache_key_domain="vllm-prefix-hash",
        model_id="TinyLlama/TinyLlama-1.1B-Chat-v1.0",
        tokenizer_id="TinyLlama/TinyLlama-1.1B-Chat-v1.0",
        salt_namespace="tenant-a",
        block_size=16,
    )


def resident_claim(
    *,
    protection_mode: ProtectionMode = ProtectionMode.HARD_PROTECTED,
) -> ResidentClaimInput:
    return ResidentClaimInput(
        claim_id="claim:prefix-a",
        owner_scope="session:tenant-a:user-7",
        cache_identity=cache_identity(),
        object_id="prefix-a",
        materialization_predicate=MaterializationPredicate.leading_prefix_at_least(3),
        footprint_blocks=5,
        protection_mode=protection_mode,
        duration_steps=10,
    )


def test_minimal_contract_splits_input_decision_state_and_events() -> None:
    state = ResidentClaimState(resident_claim())

    decision = state.accept(step=4)
    event = predicate_breaking_harm_event(
        state,
        before_positions=[0, 1, 2, 3, 4],
        after_positions=[0, 2, 3, 4],
        step=5,
        cause="active_allocation",
        request_id="active",
    )

    assert decision.decision.value == "accepted"
    assert event is not None
    assert event.to_record()["event"] == "resident_claim_harmed"
    assert event.to_record()["predicate_before"]["materialized"] is True
    assert event.to_record()["predicate_after"]["materialized"] is False
    assert state.state == ClaimStateKind.HARMED


def test_cache_identity_is_required_for_reuse_equivalence() -> None:
    with pytest.raises(ValueError, match="model_id"):
        CacheIdentity(
            cache_key_domain="vllm-prefix-hash",
            model_id="",
            tokenizer_id="tok",
            salt_namespace="tenant-a",
            block_size=16,
        )


def test_block_survival_can_disagree_with_materialized_prefix_value() -> None:
    predicate = MaterializationPredicate.leading_prefix_at_least(4)

    result = predicate.evaluate([1, 2, 3, 4, 5])

    assert result.surviving_blocks == 5
    assert result.leading_blocks == 0
    assert not result.materialized


def test_unaccepted_cache_loss_is_not_claim_harm() -> None:
    state = ResidentClaimState(resident_claim())

    event = predicate_breaking_harm_event(
        state,
        before_positions=[0, 1, 2, 3, 4],
        after_positions=[0, 2, 3, 4],
        step=5,
        cause="ordinary_eviction",
        request_id="active",
    )

    assert event is None
    assert state.state == ClaimStateKind.SUBMITTED


def test_demoted_claim_must_not_emit_later_harm() -> None:
    state = ResidentClaimState(resident_claim())
    state.accept(step=1)
    state.release(step=2, event_type=ClaimEventType.CLAIM_DEMOTED)

    event = predicate_breaking_harm_event(
        state,
        before_positions=[0, 1, 2, 3, 4],
        after_positions=[0, 2, 3, 4],
        step=3,
        cause="post_demotion_eviction",
        request_id="active",
    )

    assert event is None
    assert state.state == ClaimStateKind.DEMOTED


def test_expired_claim_must_not_emit_later_harm() -> None:
    state = ResidentClaimState(resident_claim())
    state.accept(step=1)
    state.release(step=2, event_type=ClaimEventType.CLAIM_EXPIRED)

    event = predicate_breaking_harm_event(
        state,
        before_positions=[0, 1, 2, 3, 4],
        after_positions=[0, 2, 3, 4],
        step=3,
        cause="post_expiry_eviction",
        request_id="active",
    )

    assert event is None
    assert state.state == ClaimStateKind.EXPIRED
