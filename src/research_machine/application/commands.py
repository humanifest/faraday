from __future__ import annotations

from dataclasses import dataclass, field

from research_machine.domain.models import ClaimLevel, EvidenceDirection, RejectionType


@dataclass(frozen=True)
class CreateInquiry:
    title: str
    initial_statement: str
    inquiry_id: str | None = None


@dataclass(frozen=True)
class AddQuestion:
    text: str


@dataclass(frozen=True)
class AddClaim:
    statement: str
    level: ClaimLevel
    parent_claims: list[str] = field(default_factory=list)
    scope: str = ""


@dataclass(frozen=True)
class ProposeHypothesis:
    statement: str
    generated_by: str = "codex"
    parent_claims: list[str] = field(default_factory=list)
    lineage: list[str] = field(default_factory=list)
    source_context: list[str] = field(default_factory=list)
    scope: str = ""
    observable_prediction: str = ""
    null_model: str = ""
    competing_models: list[str] = field(default_factory=list)
    causal_direction: str = ""
    primary_estimand: str = ""
    expected_effect_direction: str = ""
    time_window: str = ""
    covariates: list[str] = field(default_factory=list)
    known_confounds: list[str] = field(default_factory=list)
    falsification_conditions: list[str] = field(default_factory=list)
    support_conditions: list[str] = field(default_factory=list)
    boundary_conditions: list[str] = field(default_factory=list)
    required_replications: int | None = None


@dataclass(frozen=True)
class RetireHypothesis:
    hypothesis_id: str
    rejection_type: RejectionType
    reason: str
    limitations: str = ""
    resurrection_conditions: list[str] = field(default_factory=list)
    superseded_by: str | None = None


@dataclass(frozen=True)
class RecordEvidence:
    hypothesis_id: str
    direction: EvidenceDirection
    summary: str
    dataset_id: str
    analysis_id: str
    claim_id: str | None = None
    effect_estimate: str = ""
    uncertainty: str = ""
    scope: str = ""
    controls_passed: list[str] = field(default_factory=list)
    controls_failed: list[str] = field(default_factory=list)
    higher_level_conclusions_unsupported: list[str] = field(default_factory=list)
    exploratory: bool = True
