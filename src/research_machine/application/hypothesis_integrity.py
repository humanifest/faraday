"""Prospective commitments for the scientific content of tested hypotheses."""

from __future__ import annotations

import hashlib
import json
from typing import Mapping, Sequence

from research_machine.domain.errors import ValidationError
from research_machine.domain.models import ExperimentProtocol, Hypothesis


_LIFECYCLE_FIELDS = {
    "scientific_content_sha256",
    "workflow_state",
    "evidence_assessment",
    "replication_state",
    "pending_review_at",
    "pending_review_by",
    "pending_review_confidence",
    "pending_review_rationale",
    "activated_at",
    "retirement",
}


def hypothesis_scientific_sha256(hypothesis: Hypothesis) -> str:
    payload = {
        key: value
        for key, value in hypothesis.to_dict().items()
        if key not in _LIFECYCLE_FIELDS
    }
    return hashlib.sha256(
        json.dumps(
            payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False
        ).encode("utf-8")
    ).hexdigest()


def validate_hypothesis_scientific_commitment(hypothesis: Hypothesis) -> str:
    expected = hypothesis_scientific_sha256(hypothesis)
    if hypothesis.scientific_content_sha256 != expected:
        raise ValidationError(
            f"hypothesis {hypothesis.hypothesis_id} scientific content no longer matches its service-generated commitment"
        )
    return expected


def build_hypothesis_commitments(
    hypotheses: Sequence[Hypothesis],
) -> dict[str, str]:
    return {
        hypothesis.hypothesis_id: hypothesis_scientific_sha256(hypothesis)
        for hypothesis in hypotheses
    }


def validate_protocol_hypothesis_commitments(
    protocol: ExperimentProtocol, hypotheses: Mapping[str, Hypothesis]
) -> None:
    expected_ids = list(protocol.hypotheses_tested)
    if set(protocol.hypothesis_commitments) != set(expected_ids):
        raise ValidationError(
            f"protocol {protocol.protocol_id} does not commit exactly its tested hypotheses"
        )
    for hypothesis_id in expected_ids:
        hypothesis = hypotheses.get(hypothesis_id)
        if hypothesis is None:
            raise ValidationError(
                f"protocol {protocol.protocol_id} references unknown hypothesis {hypothesis_id}"
            )
        if protocol.hypothesis_commitments[hypothesis_id] != (
            hypothesis_scientific_sha256(hypothesis)
        ):
            raise ValidationError(
                f"protocol {protocol.protocol_id} hypothesis {hypothesis_id} scientific content no longer matches its freeze commitment"
            )
