"""Regret helpers for MVP policy/oracle comparisons."""

from __future__ import annotations


def normalized_regret(policy_value: float, oracle_value: float, *, epsilon: float = 1e-9) -> float:
    """Return normalized regret, raising a quarantine flag for negative regret."""

    if policy_value > oracle_value:
        raise ValueError(
            "negative regret quarantine: policy value exceeds oracle value "
            f"({policy_value} > {oracle_value})"
        )
    return (oracle_value - policy_value) / max(epsilon, oracle_value)
