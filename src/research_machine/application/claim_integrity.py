"""Stable commitments for claim propositions across epistemic review changes."""

from __future__ import annotations

import hashlib
import json

from research_machine.domain.models import Claim


_SCIENTIFIC_FIELDS = (
    "claim_id",
    "statement",
    "level",
    "created_at",
    "parent_claims",
    "scope",
)


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
