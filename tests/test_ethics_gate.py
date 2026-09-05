from __future__ import annotations

import pytest

from research_machine.application.policies import validate_protocol_freeze
from research_machine.domain.errors import ValidationError
from research_machine.domain.models import AnalysisMode, ExperimentProtocol, ProtocolKind


def _human_protocol(**overrides: object) -> ExperimentProtocol:
    values: dict[str, object] = {
        "protocol_id": "ethics-v1",
        "protocol_family_id": "ethics",
        "version": 1,
        "experiment_id": "human-study",
        "title": "Human study",
        "analysis_mode": AnalysisMode.CONFIRMATORY,
        "hypotheses_tested": ["h1"],
        "primary_outcome": "Registered outcome",
        "created_at": "2026-09-04T00:00:00Z",
        "created_by": "test",
        "protocol_kind": ProtocolKind.EXPERIMENTAL,
        "methodology": "A bounded randomized study.",
        "quality_requirements": ["integrity"],
        "controls": ["Control condition"],
        "expected_outputs": ["Result table"],
        "success_conditions": ["Report all outcomes."],
        "randomization_plan": "Randomize before enrollment.",
        "blinding_plan": "Outcome assessor is blinded.",
        "sampling_unit": "Participant",
        "sample_size_or_stopping_rule": "Fixed sample of 20.",
        "preprocessing_pipeline": "Frozen preprocessing.",
        "statistical_model": "Registered comparison.",
        "multiple_testing_policy": "One primary outcome.",
        "missing_data_policy": "Report and bound missingness.",
        "failure_conditions": ["Any required gate fails."],
        "safety_constraints": ["Do not collect before review."],
        "analysis_code_hash": "a" * 64,
        "human_subjects": True,
    }
    values.update(overrides)
    return ExperimentProtocol(**values)  # type: ignore[arg-type]


def test_human_protocol_cannot_freeze_without_all_ethics_receipts() -> None:
    with pytest.raises(ValidationError, match="consent_plan"):
        validate_protocol_freeze(_human_protocol())


def test_complete_human_protocol_can_pass_the_ethics_gate() -> None:
    protocol = _human_protocol(
        consent_plan="Written informed consent before enrollment.",
        withdrawal_plan="Participants may withdraw without penalty.",
        privacy_plan="Pseudonymous access-controlled records.",
        retention_deletion_plan="Delete identifiers after the registered retention period.",
        risk_assessment="Low-risk questionnaire with distress escalation instructions.",
        independent_review_receipt="IRB-EXAMPLE-001",
    )
    validate_protocol_freeze(protocol)
