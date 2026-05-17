"""Native/default policy: no active residency claims."""

from __future__ import annotations

from .base import BasePolicy, fallback_native
from kvrt.model import ClaimDecision, Prefix, ResidencyClaim, RuntimeState


class NativePolicy(BasePolicy):
    name = "native"
    admissible_fields: set[str] = set()

    def plan_claims(
        self,
        state: RuntimeState,
        prefixes: dict[str, Prefix],
        claims: list[ResidencyClaim],
    ) -> list[ClaimDecision]:
        return [
            fallback_native(claim, policy_name=self.name, state=state)
            for claim in claims
        ]
