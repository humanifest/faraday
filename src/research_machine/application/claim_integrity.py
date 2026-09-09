"""Stable commitments for claim propositions across epistemic review changes."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping

from research_machine.domain.models import Claim, ClaimLevel


_SCIENTIFIC_FIELDS = (
    "claim_id",
    "statement",
    "level",
    "created_at",
    "parent_claims",
    "scope",
)

_CLAIM_LEVEL_ORDER = {
    ClaimLevel.MEASUREMENT_VALIDITY: 1,
    ClaimLevel.STATISTICAL_ASSOCIATION: 2,
    ClaimLevel.CAUSAL_DIRECTION: 3,
    ClaimLevel.ROBUSTNESS: 4,
    ClaimLevel.MECHANISM: 5,
    ClaimLevel.ADAPTATION: 6,
    ClaimLevel.ATTRIBUTION_INTENT: 7,
}


def claim_scientific_sha256(claim: Claim) -> str:
    value = claim.to_dict()
    payload = {field: value[field] for field in _SCIENTIFIC_FIELDS}
    return hashlib.sha256(
        json.dumps(
            payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False
        ).encode("utf-8")
    ).hexdigest()


def validate_claim_scientific_commitment(claim: Claim) -> str:
    expected = claim_scientific_sha256(claim)
    if claim.scientific_content_sha256 != expected:
        from research_machine.domain.errors import ValidationError

        raise ValidationError(
            f"claim {claim.claim_id} scientific content no longer matches its service-generated commitment"
        )
    return expected


def claim_level_rank(level: ClaimLevel) -> int | None:
    return _CLAIM_LEVEL_ORDER.get(level)


def validate_claim_dependency_levels(
    claim: Claim, claims_by_id: Mapping[str, Claim]
) -> None:
    claim_rank = claim_level_rank(claim.level)
    if claim_rank is None:
        return
    for parent_id in claim.parent_claims:
        parent = claims_by_id.get(parent_id)
        if parent is None:
            continue
        parent_rank = claim_level_rank(parent.level)
        if parent_rank is None:
            continue
        if parent_rank > claim_rank:
            from research_machine.domain.errors import ValidationError

            raise ValidationError(
                f"claim {claim.claim_id} cannot depend on higher-inference "
                f"parent claim {parent_id}: {parent.level.value} exceeds "
                f"{claim.level.value}"
            )
