from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from pathlib import Path
from typing import Any, Sequence

from research_machine.adapters.filesystem import FileSystemRepository
from research_machine.addons.execution import execute_analysis
from research_machine.addons.registry import default_registry, load_local_addons
from research_machine.application.commands import (
    AddClaim,
    AddQuestion,
    CreateProtocol,
    CreateInquiry,
    ProposeHypothesis,
    RecommendActionPortfolio,
    RecommendNextAction,
    RecordCrossLaneLesson,
    RecordEthicsReviewEvent,
    RecordEvidenceStatusEvent,
    RecordEvidence,
    RecordRun,
    RegisterDataset,
    ReviewClaim,
    RetireHypothesis,
    SetInquiryDecision,
)
from research_machine.application.service import ResearchService
from research_machine.domain.errors import ResearchMachineError
from research_machine.design.scaffold import scaffold_design
from research_machine.design.initializer import initialize_experiment_repository
from research_machine.design.precision import (
    plan_two_group_equivalence_power, plan_two_group_power,
    plan_two_group_practical_power,
    plan_two_group_precision,
)
from research_machine.design.randomization import generate_blocked_assignment
from research_machine.design.causal import audit_causal_identification
from research_machine.measurement.custody import (
    create_measurement_custody_record,
    validate_measurement_custody,
    verify_measurement_custody_record,
)
from research_machine.literature.snapshot import create_snapshot
from research_machine.domain.models import (
    ControlDefinition,
    ActionCandidate,
    ActionLane,
    AnalysisMode,
    AnalysisContract,
    AnalysisFamilyMember,
    AnalysisStepContract,
    CalibrationCriterion,
    ConclusionContract,
    ClaimDisposition,
    ClaimEpistemicLayer,
    ClaimLevel,
    DatasetArtifact,
    DatasetRole,
    EvidenceDirection,
    HypothesisWorkflowState,
    MeasurementDefinition,
    MeasurementValidityCheck,
    MeasurementRole,
    ProtocolKind,
    ProtocolStatus,
    QualityGateResult,
    QualityGateStatus,
    RejectionType,
    SelectionWeights,
    ValidationTag,
)

_PROPOSAL_FIELDS = {
    "statement",
    "generated_by",
    "parent_claims",
    "lineage",
    "source_context",
    "scope",
    "observable_prediction",
    "null_model",
    "competing_models",
    "causal_direction",
    "primary_estimand",
    "contrast_definition",
    "contrast_groups",
    "expected_effect_direction",
    "time_window",
    "covariates",
    "known_confounds",
    "falsification_conditions",
    "support_conditions",
    "boundary_conditions",
    "required_replications",
}

_DATASET_FIELDS = {
    "dataset_id",
    "name",
    "role",
    "artifacts",
    "description",
    "observation_unit",
    "source_dataset_ids",
    "protocol_id",
    "synthetic",
    "quality_attestations",
    "metadata",
}

_PROTOCOL_FIELDS = {
    "control_definitions",
    "experiment_id",
    "title",
    "analysis_mode",
    "hypotheses_tested",
    "primary_outcome",
    "protocol_kind",
    "methodology",
    "inputs_required",
    "quality_requirements",
    "controls",
    "measurement_definitions",
    "measurement_validity_checks",
    "expected_outputs",
    "success_conditions",
    "environment_requirements",
    "secondary_outcomes",
    "confirmatory_outcomes",
    "exploratory_outcomes",
    "multiplicity_method",
    "multiplicity_alpha",
    "independent_variables",
    "randomization_plan",
    "blinding_plan",
    "sampling_unit",
    "independent_unit", "repeated_measures", "analysis_design", "unit_analysis_plan", "unit_id_column",
    "analysis_specification_sha256",
    "analysis_contract",
    "analysis_steps",
    "conclusion_contract",
    "sample_size_or_stopping_rule",
    "sample_size_plan",
    "inclusion_rules",
    "exclusion_rules",
    "sensor_requirements",
    "calibration_requirements",
    "calibration_acceptance_criteria",
    "measurement_custody_requirements",
    "clock_accuracy_requirement",
    "preprocessing_pipeline",
    "statistical_model",
    "control_windows",
    "multiple_testing_policy",
    "missing_data_policy",
    "causal_claim",
    "causal_identification",
    "failure_conditions",
    "safety_constraints",
    "human_subjects",
    "consent_plan",
    "withdrawal_plan",
    "privacy_plan",
    "retention_deletion_plan",
    "risk_assessment",
    "vulnerable_population_plan",
    "data_security_plan",
    "incidental_findings_plan",
    "independent_review_receipt",
    "independent_review_decision",
    "independent_reviewer_role",
    "independent_reviewed_at",
    "independent_review_scope",
    "independent_review_artifact_locator",
    "independent_review_artifact_sha256",
    "independent_review_conditions",
    "analysis_code_hash",
    "external_anchor",
    "random_seed_commitment",
}

_RUN_FIELDS = {
    "run_id",
    "protocol_id",
    "started_at",
    "completed_at",
    "analysis_code_hash",
    "environment_hash",
    "random_seed_reveal",
    "dataset_ids",
    "output_artifacts",
    "quality_gates",
    "summary",
    "synthetic",
    "metadata",
}

_ACTION_SPEC_FIELDS = {"candidates", "weights"}
_ACTION_PORTFOLIO_SPEC_FIELDS = {
    "lanes",
    "candidates",
    "completed_action_ids",
    "weights",
}
_CROSS_LANE_LESSON_SPEC_FIELDS = {
    "origin_lane_id",
    "target_lane_ids",
    "origin_artifact_locator",
    "origin_artifact_sha256",
    "origin_integrity_status",
    "observation",
    "failure_class",
    "strongest_alternative_explanation",
    "challenged_invariant",
    "first_permitted_future_versions",
    "prohibited_retroactive_targets",
    "proposed_repair",
    "repair_falsifier",
    "conclusion_ceiling",
}


def _add_inquiry_option(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--inquiry", help="Inquiry ID; defaults to the active inquiry")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="research",
        description="Operate a headless, provenance-first research workspace.",
    )
    parser.add_argument(
        "--workspace",
        default=os.environ.get("RESEARCH_WORKSPACE", ".research"),
        help="Research workspace directory (default: .research)",
    )
    parser.add_argument(
        "--actor",
        default=os.environ.get("RESEARCH_ACTOR", "codex"),
        help="Identity recorded in provenance events",
    )
    parser.add_argument("--json", action="store_true", help="Emit stable JSON output")
    parser.add_argument(
        "--addon-path",
        action="append",
        type=Path,
        default=[],
        help=(
            "Load an explicit local add-on directory or research_addon.py file; "
            "repeatable and also read from RESEARCH_ADDON_PATH"
        ),
    )
    groups = parser.add_subparsers(dest="group", required=True)

    workspace = groups.add_parser("workspace", help="Create and verify workspaces")
    workspace_commands = workspace.add_subparsers(dest="action", required=True)
    workspace_commands.add_parser("init", help="Initialize the workspace")
    verify = workspace_commands.add_parser(
        "verify", help="Verify the provenance ledger"
    )
    _add_inquiry_option(verify)
    audit = workspace_commands.add_parser(
        "audit", help="Audit epistemic maturity and overclaim safeguards"
    )
    audit.add_argument(
        "--fail-on",
        choices=["never", "error", "warning"],
        default="never",
        help="Return an error when findings reach this severity (default: never)",
    )
    _add_inquiry_option(audit)

    inquiry = groups.add_parser("inquiry", help="Create and inspect inquiries")
    inquiry_commands = inquiry.add_subparsers(dest="action", required=True)
    create = inquiry_commands.add_parser("create", help="Create and select an inquiry")
    create.add_argument("--title", required=True)
    create.add_argument("--statement", required=True)
    create.add_argument("--id", dest="inquiry_id")
    create.add_argument("--decision", default="")
    create.add_argument("--minimum-evidence", default="")
    create.add_argument("--change-criterion", action="append", default=[])
    create.add_argument("--decision-owner", default="")
    select = inquiry_commands.add_parser("select", help="Select the active inquiry")
    select.add_argument("inquiry_id")
    decision = inquiry_commands.add_parser(
        "decision", help="Set the decision context after clarification"
    )
    decision.add_argument("--decision", required=True)
    decision.add_argument("--minimum-evidence", required=True)
    decision.add_argument("--change-criterion", action="append", required=True)
    decision.add_argument("--decision-owner", default="")
    _add_inquiry_option(decision)
    show = inquiry_commands.add_parser("show", help="Show complete structured state")
    _add_inquiry_option(show)

    question = groups.add_parser("question", help="Manage clarifying questions")
    question_commands = question.add_subparsers(dest="action", required=True)
    question_add = question_commands.add_parser("add")
    question_add.add_argument("--text", required=True)
    _add_inquiry_option(question_add)
    question_answer = question_commands.add_parser("answer")
    question_answer.add_argument("question_id")
    question_answer.add_argument("--answer", required=True)
    _add_inquiry_option(question_answer)
    question_list = question_commands.add_parser("list")
    _add_inquiry_option(question_list)

    claim = groups.add_parser("claim", help="Manage the claim hierarchy")
    claim_commands = claim.add_subparsers(dest="action", required=True)
    claim_add = claim_commands.add_parser("add")
    claim_add.add_argument("--statement", required=True)
    claim_add.add_argument(
        "--level", required=True, choices=[value.value for value in ClaimLevel]
    )
    claim_add.add_argument("--parent-claim", action="append", default=[])
    claim_add.add_argument("--scope", default="")
    claim_add.add_argument(
        "--epistemic-layer",
        choices=[value.value for value in ClaimEpistemicLayer],
        default=ClaimEpistemicLayer.UNRESOLVED.value,
    )
    claim_add.add_argument(
        "--disposition",
        choices=[value.value for value in ClaimDisposition],
        default=ClaimDisposition.UNRESOLVED.value,
    )
    claim_add.add_argument("--confidence", type=float)
    claim_add.add_argument("--source-ref", action="append", default=[])
    claim_add.add_argument("--conflicts-with", action="append", default=[])
    claim_add.add_argument("--falsified-by", action="append", default=[])
    claim_add.add_argument("--last-reviewed")
    claim_add.add_argument("--decision-owner", default="")
    _add_inquiry_option(claim_add)
    claim_review = claim_commands.add_parser(
        "review", help="Review epistemic layer, disposition, and provenance"
    )
    claim_review.add_argument("claim_id")
    claim_review.add_argument(
        "--epistemic-layer", choices=[value.value for value in ClaimEpistemicLayer]
    )
    claim_review.add_argument(
        "--disposition", choices=[value.value for value in ClaimDisposition]
    )
    claim_review.add_argument("--confidence", type=float)
    claim_review.add_argument("--source-ref", action="append", default=None)
    claim_review.add_argument("--conflicts-with", action="append", default=None)
    claim_review.add_argument("--falsified-by", action="append", default=None)
    claim_review.add_argument("--reviewed-at")
    claim_review.add_argument("--decision-owner")
    _add_inquiry_option(claim_review)
    claim_list = claim_commands.add_parser("list")
    _add_inquiry_option(claim_list)

    hypothesis = groups.add_parser("hypothesis", help="Manage competing hypotheses")
    hypothesis_commands = hypothesis.add_subparsers(dest="action", required=True)
    propose = hypothesis_commands.add_parser(
        "propose", help="Create an unreviewed structured proposal"
    )
    propose.add_argument("--proposal-file", type=Path)
    propose.add_argument("--statement")
    propose.add_argument("--generated-by", default=None)
    propose.add_argument("--parent-claim", action="append", default=None)
    propose.add_argument("--lineage", action="append", default=None)
    propose.add_argument("--source-context", action="append", default=None)
    propose.add_argument("--scope")
    propose.add_argument("--prediction")
    propose.add_argument("--null-model")
    propose.add_argument("--competing-model", action="append", default=None)
    propose.add_argument("--causal-direction")
    propose.add_argument("--primary-estimand")
    propose.add_argument("--contrast-definition")
    propose.add_argument("--contrast-group", action="append", default=None)
    propose.add_argument("--expected-effect-direction")
    propose.add_argument("--time-window")
    propose.add_argument("--covariate", action="append", default=None)
    propose.add_argument("--known-confound", action="append", default=None)
    propose.add_argument("--falsification", action="append", default=None)
    propose.add_argument("--support-condition", action="append", default=None)
    propose.add_argument("--boundary-condition", action="append", default=None)
    propose.add_argument("--required-replications", type=int)
    _add_inquiry_option(propose)
    activate = hypothesis_commands.add_parser(
        "activate", help="Validate and promote a proposal to the active model set"
    )
    activate.add_argument("hypothesis_id")
    _add_inquiry_option(activate)
    stage = hypothesis_commands.add_parser(
        "stage",
        help=(
            "Stage a complete hypothesis for exploratory work while human review "
            "remains pending"
        ),
    )
    stage.add_argument("hypothesis_id")
    stage.add_argument("--confidence", required=True, choices=["high"])
    stage.add_argument("--rationale", required=True)
    _add_inquiry_option(stage)
    retire = hypothesis_commands.add_parser(
        "retire", help="Preserve a rejected or superseded hypothesis"
    )
    retire.add_argument("hypothesis_id")
    retire.add_argument(
        "--type",
        dest="rejection_type",
        required=True,
        choices=[value.value for value in RejectionType],
    )
    retire.add_argument("--reason", required=True)
    retire.add_argument("--limitations", default="")
    retire.add_argument("--resurrection-condition", action="append", default=[])
    retire.add_argument("--superseded-by")
    _add_inquiry_option(retire)
    hypothesis_list = hypothesis_commands.add_parser("list")
    hypothesis_list.add_argument(
        "--state",
        choices=[value.value for value in HypothesisWorkflowState],
    )
    _add_inquiry_option(hypothesis_list)

    dataset = groups.add_parser("dataset", help="Register immutable dataset roles")
    dataset_commands = dataset.add_subparsers(dest="action", required=True)
    dataset_register = dataset_commands.add_parser("register")
    dataset_register.add_argument("--manifest-file", type=Path)
    dataset_register.add_argument("--id", dest="dataset_id")
    dataset_register.add_argument("--name")
    dataset_register.add_argument(
        "--role", choices=[value.value for value in DatasetRole]
    )
    dataset_register.add_argument(
        "--file",
        action="append",
        default=[],
        type=Path,
        help="Hash and reference a local artifact without copying it",
    )
    dataset_register.add_argument("--description")
    dataset_register.add_argument("--observation-unit")
    dataset_register.add_argument("--source-dataset", action="append", default=None)
    dataset_register.add_argument("--protocol")
    dataset_register.add_argument("--synthetic", action="store_true", default=None)
    dataset_register.add_argument(
        "--quality-attestation", action="append", default=None
    )
    dataset_register.add_argument(
        "--artifact-root",
        type=Path,
        help="Verify registered observation bytes before protected registration",
    )
    dataset_register.add_argument(
        "--custody-artifact-root",
        type=Path,
        help="Verify custody raw-source and supporting-evidence bytes before protected registration",
    )
    dataset_register.add_argument(
        "--ethics-artifact-root",
        type=Path,
        help="Verify evidence discharging conditional independent-review obligations",
    )
    _add_inquiry_option(dataset_register)
    dataset_list = dataset_commands.add_parser("list")
    _add_inquiry_option(dataset_list)

    protocol = groups.add_parser(
        "protocol", help="Draft, freeze, and amend research protocols"
    )
    protocol_commands = protocol.add_subparsers(dest="action", required=True)
    protocol_create = protocol_commands.add_parser("create")
    protocol_create.add_argument("--spec-file", type=Path, required=True)
    _add_inquiry_option(protocol_create)
    protocol_freeze = protocol_commands.add_parser("freeze")
    protocol_freeze.add_argument("protocol_id")
    protocol_freeze.add_argument("--external-anchor")
    protocol_freeze.add_argument("--review-artifact-root", type=Path)
    _add_inquiry_option(protocol_freeze)
    protocol_amend = protocol_commands.add_parser("amend")
    protocol_amend.add_argument("protocol_id")
    protocol_amend.add_argument("--spec-file", type=Path, required=True)
    protocol_amend.add_argument("--reason", required=True)
    protocol_amend.add_argument("--timing", required=True, choices=("before_collection", "during_collection", "after_collection", "after_analysis", "unknown"))
    protocol_amend.add_argument("--evidence-exposure", required=True, choices=("not_seen", "aggregate_seen", "full_data_seen", "unknown"))
    _add_inquiry_option(protocol_amend)
    protocol_show = protocol_commands.add_parser("show")
    protocol_show.add_argument("protocol_id")
    _add_inquiry_option(protocol_show)
    protocol_list = protocol_commands.add_parser("list")
    protocol_list.add_argument(
        "--status", choices=[value.value for value in ProtocolStatus]
    )
    _add_inquiry_option(protocol_list)

    run = groups.add_parser("run", help="Record immutable, quality-gated executions")
    run_commands = run.add_subparsers(dest="action", required=True)
    run_record = run_commands.add_parser("record")
    run_record.add_argument("--record-file", type=Path, required=True)
    run_record.add_argument(
        "--expect-record-sha256",
        help="Reject unless the parsed record bytes match this preflighted digest",
    )
    run_record.add_argument(
        "--artifact-root",
        type=Path,
        help="Re-hash relative output-artifact locators before recording",
    )
    run_record.add_argument(
        "--attestation-schema",
        type=Path,
        help="Validate a replication attestation against this local schema",
    )
    run_record.add_argument(
        "--expect-attestation-schema-sha256",
        help="Reject unless the attestation schema matches this commitment",
    )
    _add_inquiry_option(run_record)
    run_preflight = run_commands.add_parser(
        "preflight",
        help="Validate a run record without appending it to canonical state",
    )
    run_preflight.add_argument("--record-file", type=Path, required=True)
    run_preflight.add_argument(
        "--artifact-root",
        type=Path,
        help="Re-hash relative output-artifact locators during preflight",
    )
    run_preflight.add_argument(
        "--attestation-schema",
        type=Path,
        help="Validate a replication attestation against this local schema",
    )
    run_preflight.add_argument(
        "--expect-attestation-schema-sha256",
        help="Require this SHA-256 for the attestation schema",
    )
    _add_inquiry_option(run_preflight)
    run_template = run_commands.add_parser(
        "template",
        help="Emit a non-submittable run skeleton with exact frozen gate IDs",
    )
    run_template.add_argument("--protocol", required=True)
    _add_inquiry_option(run_template)
    run_show = run_commands.add_parser("show")
    run_show.add_argument("run_id")
    _add_inquiry_option(run_show)
    run_list = run_commands.add_parser("list")
    _add_inquiry_option(run_list)

    next_action = groups.add_parser(
        "next-action", help="Select the safest high-information next research action"
    )
    next_action_commands = next_action.add_subparsers(dest="action", required=True)
    recommend = next_action_commands.add_parser("recommend")
    recommend.add_argument("--spec-file", type=Path, required=True)
    _add_inquiry_option(recommend)
    portfolio = next_action_commands.add_parser(
        "portfolio", help="Select one safe, feasible action per active lane"
    )
    portfolio.add_argument("--spec-file", type=Path, required=True)
    _add_inquiry_option(portfolio)
    recommendation_list = next_action_commands.add_parser("list")
    _add_inquiry_option(recommendation_list)

    lesson = groups.add_parser(
        "cross-lane-lesson",
        help="Record prospective lessons transferred between research lanes",
    )
    lesson_commands = lesson.add_subparsers(dest="action", required=True)
    lesson_record = lesson_commands.add_parser("record")
    lesson_record.add_argument("--spec-file", type=Path, required=True)
    _add_inquiry_option(lesson_record)
    lesson_list = lesson_commands.add_parser("list")
    _add_inquiry_option(lesson_list)

    evidence = groups.add_parser("evidence", help="Record claim-scoped evidence")
    evidence_commands = evidence.add_subparsers(dest="action", required=True)
    record = evidence_commands.add_parser("record")
    record.add_argument("--hypothesis", required=True)
    record.add_argument(
        "--direction",
        required=True,
        choices=[value.value for value in EvidenceDirection],
    )
    record.add_argument("--summary", required=True)
    record.add_argument("--dataset")
    record.add_argument("--run")
    record.add_argument(
        "--analysis",
        default="",
        help="Analysis ID; inferred from --run when supplied",
    )
    record.add_argument("--claim")
    record.add_argument("--effect-estimate", default="")
    record.add_argument("--uncertainty", default="")
    record.add_argument("--analysis-output-sha256", default="")
    record.add_argument("--effect-estimate-path", default="")
    record.add_argument("--uncertainty-path", default="")
    record.add_argument("--scope", required=True)
    record.add_argument("--control-passed", action="append", default=[])
    record.add_argument("--control-failed", action="append", default=[])
    record.add_argument(
        "--higher-conclusion-unsupported", action="append", required=True
    )
    record.add_argument(
        "--validation-tag",
        action="append",
        required=True,
        choices=[tag.value for tag in ValidationTag],
        help="Machine-validated evidence capability; repeat for multiple tags",
    )
    record.add_argument(
        "--confirmatory",
        action="store_true",
        help="Mark as confirmatory; default is exploratory",
    )
    _add_inquiry_option(record)
    evidence_list = evidence_commands.add_parser("list")
    _add_inquiry_option(evidence_list)
    evidence_status = evidence_commands.add_parser(
        "record-status",
        help="Append an artifact-backed correction, withdrawal, or retraction status",
    )
    evidence_status.add_argument("--evidence", required=True)
    evidence_status.add_argument(
        "--status", required=True,
        choices=["active", "qualified", "withdrawn", "retracted"],
    )
    evidence_status.add_argument("--effective-at", required=True)
    evidence_status.add_argument("--reason", required=True)
    evidence_status.add_argument("--review-artifact-locator", required=True)
    evidence_status.add_argument("--review-artifact-sha256", required=True)
    evidence_status.add_argument("--review-artifact-root", type=Path, required=True)
    evidence_status.add_argument("--supersedes-event")
    evidence_status.add_argument("--event-id")
    _add_inquiry_option(evidence_status)
    evidence_status_list = evidence_commands.add_parser("status-history")
    evidence_status_list.add_argument("--evidence")
    _add_inquiry_option(evidence_status_list)

    synthesis = groups.add_parser("synthesis", help="Build deterministic reports")
    synthesis_commands = synthesis.add_subparsers(dest="action", required=True)
    synthesis_build = synthesis_commands.add_parser("build")
    _add_inquiry_option(synthesis_build)

    addon = groups.add_parser(
        "addon", help="Inspect bundled and installed discipline extensions"
    )
    addon_commands = addon.add_subparsers(dest="action", required=True)
    addon_commands.add_parser("list", help="List validated scientific add-ons")
    addon_show = addon_commands.add_parser("show", help="Show one add-on contract")
    addon_show.add_argument("addon_id")

    analysis = groups.add_parser(
        "analysis", help="Execute a declared method through the add-on boundary"
    )
    analysis_commands = analysis.add_subparsers(dest="action", required=True)
    analysis_run = analysis_commands.add_parser(
        "run", help="Run a deterministic analysis without claiming canonical evidence"
    )
    analysis_run.add_argument("--spec-file", type=Path, required=True)
    analysis_run.add_argument("--data-file", type=Path, required=True)
    analysis_run.add_argument("--output", type=Path, required=True)
    analysis_run.add_argument("--protocol", help="Check declared design and implementation against a frozen protocol")
    analysis_run.add_argument("--dataset", help="Registered dataset whose artifact matches the input; required with --protocol")
    _add_inquiry_option(analysis_run)
    analysis_draft = analysis_commands.add_parser("run-draft", help="Build a review-only run draft from pinned execution output")
    analysis_draft.add_argument("--execution-directory", type=Path, required=True)
    analysis_draft.add_argument("--expected-receipt-sha256", required=True)
    _add_inquiry_option(analysis_draft)
    analysis_family = analysis_commands.add_parser(
        "materialize-holm",
        help="Verify frozen confirmatory-test receipts and materialize the exact Holm input family",
    )
    analysis_family.add_argument("--protocol", required=True)
    analysis_family.add_argument("--manifest-file", type=Path, required=True)
    analysis_family.add_argument("--expected-manifest-sha256", required=True)
    analysis_family.add_argument("--output", type=Path, required=True)
    _add_inquiry_option(analysis_family)
    analysis_adjudicate = analysis_commands.add_parser(
        "adjudicate-holm",
        help="Verify the complete canonical Holm workflow and emit bounded study-level decisions",
    )
    analysis_adjudicate.add_argument("--protocol", required=True)
    analysis_adjudicate.add_argument("--manifest-file", type=Path, required=True)
    analysis_adjudicate.add_argument("--expected-manifest-sha256", required=True)
    analysis_adjudicate.add_argument("--output", type=Path, required=True)
    _add_inquiry_option(analysis_adjudicate)
    adjudication_draft = analysis_commands.add_parser(
        "adjudication-run-draft",
        help="Build a reviewed canonical run draft from a verified composite workflow",
    )
    adjudication_draft.add_argument("--adjudication-directory", type=Path, required=True)
    adjudication_draft.add_argument("--expected-receipt-sha256", required=True)
    _add_inquiry_option(adjudication_draft)

    design = groups.add_parser("design", help="Create review-only experiment drafts and audit their structure")
    design_commands = design.add_subparsers(dest="action", required=True)
    design_interview = design_commands.add_parser("interview", help="Answer plain-language questions without JSON or an LLM")
    design_interview.add_argument("--output", type=Path, help="Explicitly create a separate local experiment repository with review-only drafts")
    design_interview.add_argument("--revise-hypothesis", help="Record fresh interview answers as a new proposal descended from this hypothesis")
    design_interview.add_argument("--inquiry", help="Inquiry containing the hypothesis to revise")
    design_scaffold = design_commands.add_parser("scaffold", help="Generate a review-only study scaffold from a plain JSON brief")
    design_scaffold.add_argument("--brief-file", type=Path, required=True)
    design_revise = design_commands.add_parser("revise", help="Create a lineage-linked unreviewed proposal from a revised brief")
    design_revise.add_argument("--brief-file", type=Path, required=True)
    design_revise.add_argument("--hypothesis", required=True)
    design_revise.add_argument("--reason", required=True)
    design_revise.add_argument("--inquiry", help="Inquiry ID; defaults to the active inquiry")
    design_initialize = design_commands.add_parser(
        "initialize", help="Create an isolated local experiment repository from a review-only brief"
    )
    design_initialize.add_argument("--brief-file", type=Path, required=True)
    design_initialize.add_argument("--output", type=Path, required=True)
    design_initialize.add_argument(
        "--no-git",
        action="store_true",
        help="Create the isolated experiment directory without initializing local Git",
    )
    design_precision = design_commands.add_parser(
        "precision", help="Plan a pre-collection two-group precision target"
    )
    design_precision.add_argument("--spec-file", type=Path, required=True)
    design_power = design_commands.add_parser(
        "power", help="Plan a pre-collection two-group power target"
    )
    design_power.add_argument("--spec-file", type=Path, required=True)
    design_practical_power = design_commands.add_parser(
        "practical-power",
        help="Power a confidence bound clearing a practical-effect threshold",
    )
    design_practical_power.add_argument("--spec-file", type=Path, required=True)
    design_equivalence_power = design_commands.add_parser(
        "equivalence-power",
        help="Plan a pre-collection direct two-group equivalence power target",
    )
    design_equivalence_power.add_argument("--spec-file", type=Path, required=True)
    design_randomize = design_commands.add_parser(
        "randomize", help="Generate deterministic balanced block assignments without claiming concealment"
    )
    design_randomize.add_argument("--spec-file", type=Path, required=True)
    design_identify = design_commands.add_parser(
        "identify", help="Audit a supplied causal DAG and proposed adjustment set"
    )
    design_identify.add_argument("--spec-file", type=Path, required=True)

    measurement = groups.add_parser(
        "measurement", help="Validate raw-to-derived custody before data registration"
    )
    measurement_commands = measurement.add_subparsers(dest="action", required=True)
    measurement_template = measurement_commands.add_parser(
        "template", help="Create a review-only custody skeleton from a frozen protocol"
    )
    measurement_template.add_argument("--protocol", required=True)
    measurement_template.add_argument("--inquiry", help="Inquiry ID; defaults to the active inquiry")
    measurement_validate = measurement_commands.add_parser(
        "validate", help="Validate a provider-free measurement custody receipt"
    )
    measurement_validate.add_argument("--receipt-file", type=Path, required=True)
    measurement_validate.add_argument("--require-gate", action="append", default=[])
    measurement_validate.add_argument("--artifact-root", type=Path, help="Verify raw, transformation implementation, derived-output, and supporting-evidence files under this local directory")
    measurement_record = measurement_commands.add_parser(
        "record", help="Publish a write-once, protocol-bound custody verification record"
    )
    measurement_record.add_argument("--protocol", required=True)
    measurement_record.add_argument("--inquiry", help="Inquiry ID; defaults to the active inquiry")
    measurement_record.add_argument("--receipt-file", type=Path, required=True)
    measurement_record.add_argument("--expected-receipt-sha256", required=True)
    measurement_record.add_argument("--artifact-root", type=Path, required=True)
    measurement_record.add_argument("--output", type=Path, required=True)
    measurement_verify_record = measurement_commands.add_parser(
        "verify-record", help="Recompute a custody record from trusted hashes and local bytes"
    )
    measurement_verify_record.add_argument("--protocol", required=True)
    measurement_verify_record.add_argument("--inquiry", help="Inquiry ID; defaults to the active inquiry")
    measurement_verify_record.add_argument("--record-file", type=Path, required=True)
    measurement_verify_record.add_argument("--expected-record-sha256", required=True)
    measurement_verify_record.add_argument("--receipt-file", type=Path, required=True)
    measurement_verify_record.add_argument("--artifact-root", type=Path, required=True)
    measurement_inspect = measurement_commands.add_parser(
        "inspect-source", help="Run a bounded add-on instrument inspector over source bytes"
    )
    measurement_inspect.add_argument("--adapter", required=True)
    measurement_inspect.add_argument("--source-file", type=Path, required=True)
    measurement_inspect.add_argument("--media-type", required=True)
    measurement_inspect.add_argument("--config-file", type=Path, required=True)
    measurement_inspect.add_argument("--output", type=Path, required=True)
    measurement_verify_inspection = measurement_commands.add_parser(
        "verify-source-inspection",
        help="Reproduce an instrument inspection from trusted record and current bytes",
    )
    measurement_verify_inspection.add_argument("--adapter", required=True)
    measurement_verify_inspection.add_argument("--source-file", type=Path, required=True)
    measurement_verify_inspection.add_argument("--media-type", required=True)
    measurement_verify_inspection.add_argument("--config-file", type=Path, required=True)
    measurement_verify_inspection.add_argument("--record-file", type=Path, required=True)
    measurement_verify_inspection.add_argument("--expected-record-sha256", required=True)
    measurement_timing = measurement_commands.add_parser(
        "assess-timing",
        help="Assess stream timing feasibility from a trusted inspection record",
    )
    measurement_timing.add_argument("--inspection-file", type=Path, required=True)
    measurement_timing.add_argument("--expected-inspection-sha256", required=True)
    measurement_timing.add_argument("--spec-file", type=Path, required=True)
    measurement_timing.add_argument("--output", type=Path, required=True)
    measurement_order = measurement_commands.add_parser(
        "assess-temporal-order",
        help="Classify registered event order from a trusted timing assessment",
    )
    measurement_order.add_argument("--timing-assessment-file", type=Path, required=True)
    measurement_order.add_argument("--expected-timing-assessment-sha256", required=True)
    measurement_order.add_argument("--spec-file", type=Path, required=True)
    measurement_order.add_argument("--output", type=Path, required=True)
    measurement_preprocessing = measurement_commands.add_parser(
        "assess-preprocessing",
        help="Compare observed preprocessing against a trusted registered pipeline",
    )
    measurement_preprocessing.add_argument("--registered-pipeline-file", type=Path, required=True)
    measurement_preprocessing.add_argument("--expected-registered-pipeline-sha256", required=True)
    measurement_preprocessing.add_argument("--observed-pipeline-file", type=Path, required=True)
    measurement_preprocessing.add_argument("--expected-observed-pipeline-sha256", required=True)
    measurement_preprocessing.add_argument("--output", type=Path, required=True)

    ethics = groups.add_parser(
        "ethics", help="Record append-only changes to human-subject review clearance"
    )
    ethics_commands = ethics.add_subparsers(dest="action", required=True)
    ethics_status = ethics_commands.add_parser(
        "record-status", help="Record an artifact-backed review status event"
    )
    ethics_status.add_argument("--protocol", required=True)
    ethics_status.add_argument(
        "--status", required=True,
        choices=["active", "suspended", "withdrawn", "expired"],
    )
    ethics_status.add_argument("--effective-at", required=True)
    ethics_status.add_argument("--expires-at")
    ethics_status.add_argument("--reason", required=True)
    ethics_status.add_argument("--review-artifact-locator", required=True)
    ethics_status.add_argument("--review-artifact-sha256", required=True)
    ethics_status.add_argument("--review-artifact-root", type=Path, required=True)
    ethics_status.add_argument("--supersedes-event")
    ethics_status.add_argument("--event-id")
    _add_inquiry_option(ethics_status)

    replication = groups.add_parser(
        "replication", help="Prepare and inspect independent replication material"
    )
    replication_commands = replication.add_subparsers(dest="action", required=True)
    replication_package = replication_commands.add_parser(
        "package", help="Export a metadata-first package from a frozen protocol"
    )
    replication_package.add_argument("--protocol", required=True)
    replication_package.add_argument("--output", type=Path, required=True)
    replication_package.add_argument(
        "--include-locators",
        action="store_true",
        help="Include artifact locator strings; default redacts potentially sensitive local paths",
    )
    _add_inquiry_option(replication_package)
    replication_verify = replication_commands.add_parser(
        "verify", help="Verify package files against an independently trusted manifest hash"
    )
    replication_verify.add_argument("--package", type=Path, required=True)
    replication_verify.add_argument("--expected-manifest-sha256", required=True)

    collaborator = groups.add_parser(
        "collaborator", help="Export read-only, provider-neutral context for an app or model"
    )
    collaborator_commands = collaborator.add_subparsers(dest="action", required=True)
    collaborator_context = collaborator_commands.add_parser(
        "context", help="Emit constraints and inquiry state without calling a model"
    )
    collaborator_context.add_argument("--purpose", default="")
    collaborator_context.add_argument(
        "--output",
        type=Path,
        help="Write a hash-bound, write-once context snapshot directory",
    )
    _add_inquiry_option(collaborator_context)
    collaborator_validate = collaborator_commands.add_parser(
        "validate-proposal",
        help="Validate an untrusted response without applying canonical changes",
    )
    collaborator_validate.add_argument("--context-file", type=Path, required=True)
    collaborator_validate.add_argument("--expected-context-sha256", required=True)
    collaborator_validate.add_argument("--proposal-file", type=Path, required=True)
    collaborator_validate.add_argument("--output", type=Path, required=True)
    collaborator_review = collaborator_commands.add_parser(
        "review-proposal",
        help="Adjudicate every suggestion without applying canonical changes",
    )
    collaborator_review.add_argument("--proposal-record-file", type=Path, required=True)
    collaborator_review.add_argument(
        "--expected-proposal-record-sha256", required=True
    )
    collaborator_review.add_argument("--review-file", type=Path, required=True)
    collaborator_review.add_argument("--output", type=Path, required=True)

    literature = groups.add_parser(
        "literature", help="Create reproducible, hash-bound literature snapshots"
    )
    literature_commands = literature.add_subparsers(dest="action", required=True)
    literature_snapshot = literature_commands.add_parser(
        "snapshot", help="Snapshot a retained local set of discovered sources"
    )
    literature_snapshot.add_argument("--manifest-file", type=Path, required=True)
    literature_snapshot.add_argument("--output", type=Path, required=True)
    literature_screen = literature_commands.add_parser("screen", help="Record source-screening decisions against a pinned snapshot")
    literature_screen.add_argument("--snapshot-file", type=Path, required=True)
    literature_screen.add_argument("--expected-snapshot-sha256", required=True)
    literature_screen.add_argument("--review-file", type=Path, required=True)
    literature_screen.add_argument("--output", type=Path, required=True)
    literature_extract = literature_commands.add_parser("extract", help="Record source-bound claims from a completed screening")
    literature_extract.add_argument("--screening-file", type=Path, required=True)
    literature_extract.add_argument("--expected-screening-sha256", required=True)
    literature_extract.add_argument("--review-file", type=Path, required=True)
    literature_extract.add_argument("--output", type=Path, required=True)
    literature_verify = literature_commands.add_parser("verify-citations", help="Independently review every extracted claim against its cited location")
    literature_verify.add_argument("--extraction-file", type=Path, required=True)
    literature_verify.add_argument("--expected-extraction-sha256", required=True)
    literature_verify.add_argument("--review-file", type=Path, required=True)
    literature_verify.add_argument("--output", type=Path, required=True)
    literature_bias = literature_commands.add_parser("assess-bias", help="Record independent study-level risk-of-bias judgments")
    literature_bias.add_argument("--citation-verification-file", type=Path, required=True)
    literature_bias.add_argument("--expected-citation-verification-sha256", required=True)
    literature_bias.add_argument("--review-file", type=Path, required=True)
    literature_bias.add_argument("--output", type=Path, required=True)
    literature_reconcile = literature_commands.add_parser("reconcile-studies", help="Review whether source reports represent independent studies")
    literature_reconcile.add_argument("--bias-assessment-file", type=Path, required=True)
    literature_reconcile.add_argument("--expected-bias-assessment-sha256", required=True)
    literature_reconcile.add_argument("--review-file", type=Path, required=True)
    literature_reconcile.add_argument("--output", type=Path, required=True)
    literature_map = literature_commands.add_parser("evidence-map", help="Join the verified literature chain under conservative claim ceilings")
    literature_map.add_argument("--extraction-file", type=Path, required=True)
    literature_map.add_argument("--citation-verification-file", type=Path, required=True)
    literature_map.add_argument("--bias-assessment-file", type=Path, required=True)
    literature_map.add_argument("--study-reconciliation-file", type=Path, required=True)
    literature_map.add_argument("--expected-study-reconciliation-sha256", required=True)
    literature_map.add_argument("--output", type=Path, required=True)
    literature_plan = literature_commands.add_parser("plan-synthesis", help="Freeze synthesis choices against completed screening before extraction")
    literature_plan.add_argument("--screening-file", type=Path, required=True)
    literature_plan.add_argument("--expected-screening-sha256", required=True)
    literature_plan.add_argument("--spec-file", type=Path, required=True)
    literature_plan.add_argument("--output", type=Path, required=True)
    literature_synthesize = literature_commands.add_parser("synthesize", help="Execute a bounded deterministic qualitative synthesis")
    literature_synthesize.add_argument("--plan-file", type=Path, required=True)
    literature_synthesize.add_argument("--expected-plan-sha256", required=True)
    literature_synthesize.add_argument("--extraction-file", type=Path, required=True)
    literature_synthesize.add_argument("--evidence-map-file", type=Path, required=True)
    literature_synthesize.add_argument("--expected-evidence-map-sha256", required=True)
    literature_synthesize.add_argument("--deviations-file", type=Path, required=True)
    literature_synthesize.add_argument("--expected-deviations-sha256", required=True)
    literature_synthesize.add_argument("--output", type=Path, required=True)
    literature_effects = literature_commands.add_parser("prepare-effects", help="Record one plan-bound effect and variance per reconciled study")
    literature_effects.add_argument("--plan-file", type=Path, required=True)
    literature_effects.add_argument("--expected-plan-sha256", required=True)
    literature_effects.add_argument("--extraction-file", type=Path, required=True)
    literature_effects.add_argument("--evidence-map-file", type=Path, required=True)
    literature_effects.add_argument("--expected-evidence-map-sha256", required=True)
    literature_effects.add_argument("--review-file", type=Path, required=True)
    literature_effects.add_argument("--output", type=Path, required=True)
    literature_derive = literature_commands.add_parser("derive-effects", help="Recompute supported effects from source-reported arm summaries")
    literature_derive.add_argument("--plan-file", type=Path, required=True)
    literature_derive.add_argument("--expected-plan-sha256", required=True)
    literature_derive.add_argument("--extraction-file", type=Path, required=True)
    literature_derive.add_argument("--evidence-map-file", type=Path, required=True)
    literature_derive.add_argument("--expected-evidence-map-sha256", required=True)
    literature_derive.add_argument("--summaries-file", type=Path, required=True)
    literature_derive.add_argument("--output", type=Path, required=True)
    literature_verify_effects = literature_commands.add_parser("verify-effects", help="Independently check retained source summaries and effect arithmetic")
    literature_verify_effects.add_argument("--effects-file", type=Path, required=True)
    literature_verify_effects.add_argument("--expected-effects-sha256", required=True)
    literature_verify_effects.add_argument("--review-file", type=Path, required=True)
    literature_verify_effects.add_argument("--output", type=Path, required=True)
    literature_pool = literature_commands.add_parser("pool-effects", help="Run plan-bound inverse-variance meta-analysis")
    literature_pool.add_argument("--plan-file", type=Path, required=True)
    literature_pool.add_argument("--expected-plan-sha256", required=True)
    literature_pool.add_argument("--effects-file", type=Path, required=True)
    literature_pool.add_argument("--expected-effects-sha256", required=True)
    literature_pool.add_argument("--effect-verification-file", type=Path, required=True)
    literature_pool.add_argument("--expected-effect-verification-sha256", required=True)
    literature_pool.add_argument("--deviations-file", type=Path, required=True)
    literature_pool.add_argument("--expected-deviations-sha256", required=True)
    literature_pool.add_argument("--output", type=Path, required=True)
    literature_deviations = literature_commands.add_parser("record-deviations", help="Disclose departures without rewriting a frozen synthesis plan")
    literature_deviations.add_argument("--plan-file", type=Path, required=True)
    literature_deviations.add_argument("--expected-plan-sha256", required=True)
    literature_deviations.add_argument("--disclosure-file", type=Path, required=True)
    literature_deviations.add_argument("--output", type=Path, required=True)
    return parser


def _read_json_object_and_hash(
    path: Path | None, *, allowed_fields: set[str], label: str
) -> tuple[dict[str, Any], str | None, int]:
    if path is None:
        return {}, None, 0
    try:
        content = path.read_bytes()
        value = json.loads(
            content,
            parse_constant=_reject_nonfinite_json,
            object_pairs_hook=_reject_duplicate_json_keys,
        )
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
        raise ValueError(f"could not read {label} file {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise ValueError(f"{label} file must contain a JSON object")
    unknown = sorted(set(value) - allowed_fields)
    if unknown:
        raise ValueError(f"unknown {label} fields: " + ", ".join(unknown))
    return value, hashlib.sha256(content).hexdigest(), len(content)


def _reject_nonfinite_json(value: str) -> None:
    raise ValueError(f"non-finite JSON number: {value}")


def _reject_duplicate_json_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate JSON object key: {key}")
        result[key] = value
    return result


def _read_json_object(
    path: Path | None, *, allowed_fields: set[str], label: str
) -> dict[str, Any]:
    value, _, _ = _read_json_object_and_hash(
        path, allowed_fields=allowed_fields, label=label
    )
    return value


def _read_proposal(path: Path | None) -> dict[str, Any]:
    return _read_json_object(path, allowed_fields=_PROPOSAL_FIELDS, label="proposal")


def _choose(cli_value: Any, proposal: dict[str, Any], key: str, default: Any) -> Any:
    if cli_value is not None:
        return cli_value
    return proposal.get(key, default)


def _choose_list(cli_value: Any, proposal: dict[str, Any], key: str) -> list[str]:
    value = _choose(cli_value, proposal, key, [])
    if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
        raise ValueError(f"proposal field {key} must be an array of strings")
    return value


def _choose_optional_nonnegative_int(
    cli_value: Any, proposal: dict[str, Any], key: str
) -> int | None:
    value = _choose(cli_value, proposal, key, None)
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError(f"proposal field {key} must be a non-negative integer or null")
    return value


def _json_text_list(value: Any, field_name: str) -> list[str]:
    if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
        raise ValueError(f"{field_name} must be an array of strings")
    return value


def _hash_file(path: Path) -> DatasetArtifact:
    resolved = path.expanduser().resolve()
    if not resolved.is_file():
        raise ValueError(f"dataset artifact is not a file: {path}")
    digest = hashlib.sha256()
    with resolved.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return DatasetArtifact(
        locator=str(resolved),
        sha256=digest.hexdigest(),
        size_bytes=resolved.stat().st_size,
    )


def _dataset_artifacts(
    manifest: dict[str, Any], files: list[Path]
) -> list[DatasetArtifact]:
    artifacts = [_hash_file(path) for path in files]
    values = manifest.get("artifacts", [])
    if not isinstance(values, list):
        raise ValueError("artifacts must be an array")
    for value in values:
        if not isinstance(value, dict):
            raise ValueError("each artifact must be an object")
        unknown = sorted(
            set(value) - {"locator", "sha256", "size_bytes", "media_type", "metadata"}
        )
        if unknown:
            raise ValueError("unknown artifact fields: " + ", ".join(unknown))
        try:
            artifacts.append(
                DatasetArtifact(
                    locator=value["locator"],
                    sha256=value["sha256"],
                    size_bytes=value.get("size_bytes"),
                    media_type=value.get("media_type", ""),
                    metadata=value.get("metadata", {}),
                )
            )
        except KeyError as exc:
            raise ValueError(f"artifact is missing field {exc.args[0]}") from exc
    return artifacts


def _protocol_command(spec: dict[str, Any]) -> CreateProtocol:
    try:
        analysis_mode = AnalysisMode(spec["analysis_mode"])
    except KeyError as exc:
        raise ValueError("protocol is missing field analysis_mode") from exc
    try:
        protocol_kind = ProtocolKind(
            spec.get("protocol_kind", ProtocolKind.EXPERIMENTAL.value)
        )
    except ValueError as exc:
        raise ValueError(f"invalid protocol_kind: {exc}") from exc
    list_fields = {
        "hypotheses_tested",
        "inputs_required",
        "quality_requirements",
        "controls",
        "expected_outputs",
        "success_conditions",
        "environment_requirements",
        "secondary_outcomes",
        "confirmatory_outcomes",
        "exploratory_outcomes",
        "independent_variables",
        "inclusion_rules",
        "exclusion_rules",
        "sensor_requirements",
        "calibration_requirements",
        "measurement_custody_requirements",
        "control_windows",
        "failure_conditions",
        "safety_constraints",
        "independent_review_conditions",
    }
    lists = {
        field: _json_text_list(spec.get(field, []), field) for field in list_fields
    }
    measurement_values = spec.get("measurement_definitions", [])
    validity_values = spec.get("measurement_validity_checks", [])
    control_values = spec.get("control_definitions", [])
    calibration_values = spec.get("calibration_acceptance_criteria", [])
    if not isinstance(calibration_values, list) or any(not isinstance(item, dict) for item in calibration_values):
        raise ValueError("calibration_acceptance_criteria must be an array of objects")
    try:
        calibration_criteria = [CalibrationCriterion(**item) for item in calibration_values]
    except TypeError as exc:
        raise ValueError(f"invalid calibration criterion: {exc}") from exc
    contract_value = spec.get("analysis_contract")
    if contract_value is not None and not isinstance(contract_value, dict):
        raise ValueError("analysis_contract must be an object")
    try:
        analysis_contract = AnalysisContract(**contract_value) if contract_value is not None else None
    except TypeError as exc:
        raise ValueError(f"invalid analysis contract: {exc}") from exc
    conclusion_value = spec.get("conclusion_contract")
    if conclusion_value is not None and not isinstance(conclusion_value, dict):
        raise ValueError("conclusion_contract must be an object")
    try:
        conclusion_contract = (
            ConclusionContract.from_dict(conclusion_value)
            if conclusion_value is not None else None
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError(f"invalid conclusion contract: {exc}") from exc
    step_values = spec.get("analysis_steps", [])
    if not isinstance(step_values, list) or any(not isinstance(item, dict) for item in step_values):
        raise ValueError("analysis_steps must be an array of objects")
    step_fields = {
        "step_id", "role", "method", "specification_sha256",
        "implementation_sha256", "depends_on", "hypothesis_id", "outcome",
        "measurement_id", "family_id", "family_members", "alpha",
        "p_value_path",
    }
    member_fields = {
        "member_id", "source_step_id", "hypothesis_id", "outcome",
        "measurement_id",
    }
    analysis_steps: list[AnalysisStepContract] = []
    try:
        for value in step_values:
            unknown = sorted(set(value) - step_fields)
            if unknown:
                raise ValueError("unknown analysis step fields: " + ", ".join(unknown))
            members = value.get("family_members", [])
            if not isinstance(members, list) or any(not isinstance(item, dict) for item in members):
                raise ValueError("analysis step family_members must be an array of objects")
            if any(set(item) - member_fields for item in members):
                raise ValueError("analysis family member contains unknown fields")
            analysis_steps.append(AnalysisStepContract(
                step_id=value["step_id"], role=value["role"], method=value["method"],
                specification_sha256=value["specification_sha256"],
                implementation_sha256=value["implementation_sha256"],
                depends_on=value.get("depends_on", []),
                hypothesis_id=value.get("hypothesis_id", ""),
                outcome=value.get("outcome", ""),
                measurement_id=value.get("measurement_id", ""),
                p_value_path=value.get("p_value_path", ""),
                family_id=value.get("family_id", ""),
                family_members=[AnalysisFamilyMember(**item) for item in members],
                alpha=value.get("alpha"),
            ))
    except (KeyError, TypeError) as exc:
        raise ValueError(f"invalid analysis step contract: {exc}") from exc
    if not isinstance(control_values, list) or any(not isinstance(item, dict) for item in control_values):
        raise ValueError("control_definitions must be an array of objects")
    try:
        control_definitions = [ControlDefinition(**item) for item in control_values]
    except TypeError as exc:
        raise ValueError(f"invalid control definition: {exc}") from exc
    if not isinstance(measurement_values, list):
        raise ValueError("measurement_definitions must be an array")
    measurement_fields = {
        "measurement_id",
        "role",
        "registered_target",
        "observable",
        "input_condition",
        "parameter_values",
        "evaluation_point",
        "convention",
        "aggregation",
        "tolerance",
        "expected_behavior",
        "data_column",
        "temporal_role",
        "scale_type",
        "unit",
        "admissible_values",
        "valid_min",
        "valid_max",
        "missing_value_codes",
    }
    measurements: list[MeasurementDefinition] = []
    for value in measurement_values:
        if not isinstance(value, dict):
            raise ValueError("each measurement definition must be an object")
        unknown = sorted(set(value) - measurement_fields)
        if unknown:
            raise ValueError(
                "unknown measurement definition fields: " + ", ".join(unknown)
            )
        try:
            role = MeasurementRole(value["role"])
            measurements.append(
                MeasurementDefinition(
                    measurement_id=value["measurement_id"],
                    role=role,
                    registered_target=value["registered_target"],
                    observable=value["observable"],
                    input_condition=value["input_condition"],
                    parameter_values=value["parameter_values"],
                    evaluation_point=value["evaluation_point"],
                    convention=value["convention"],
                    aggregation=value["aggregation"],
                    tolerance=value["tolerance"],
                    expected_behavior=value["expected_behavior"],
                    data_column=value.get("data_column", ""),
                    temporal_role=value.get("temporal_role", ""),
                    scale_type=value.get("scale_type", ""),
                    unit=value.get("unit", ""),
                    admissible_values=value.get("admissible_values", []),
                    valid_min=value.get("valid_min"),
                    valid_max=value.get("valid_max"),
                    missing_value_codes=value.get("missing_value_codes", []),
                )
            )
        except KeyError as exc:
            raise ValueError(
                f"measurement definition is missing field {exc.args[0]}"
            ) from exc
        except ValueError as exc:
            raise ValueError(f"invalid measurement role: {value.get('role')}") from exc
    if not isinstance(validity_values, list) or any(
        not isinstance(item, dict) for item in validity_values
    ):
        raise ValueError("measurement_validity_checks must be an array of objects")
    try:
        validity_checks = [MeasurementValidityCheck(**item) for item in validity_values]
    except TypeError as exc:
        raise ValueError(f"invalid measurement validity check: {exc}") from exc
    try:
        return CreateProtocol(
            experiment_id=spec["experiment_id"],
            title=spec["title"],
            analysis_mode=analysis_mode,
            hypotheses_tested=lists["hypotheses_tested"],
            primary_outcome=spec.get("primary_outcome", ""),
            protocol_kind=protocol_kind,
            methodology=spec.get("methodology", ""),
            inputs_required=lists["inputs_required"],
            quality_requirements=lists["quality_requirements"],
            controls=lists["controls"],
            control_definitions=control_definitions,
            measurement_definitions=measurements,
            measurement_validity_checks=validity_checks,
            expected_outputs=lists["expected_outputs"],
            success_conditions=lists["success_conditions"],
            environment_requirements=lists["environment_requirements"],
            secondary_outcomes=lists["secondary_outcomes"],
            confirmatory_outcomes=lists["confirmatory_outcomes"],
            exploratory_outcomes=lists["exploratory_outcomes"],
            multiplicity_method=spec.get("multiplicity_method", ""),
            multiplicity_alpha=spec.get("multiplicity_alpha"),
            independent_variables=lists["independent_variables"],
            randomization_plan=spec.get("randomization_plan", ""),
            blinding_plan=spec.get("blinding_plan", ""),
            sampling_unit=spec.get("sampling_unit", ""),
            independent_unit=spec.get("independent_unit", ""),
            repeated_measures=spec.get("repeated_measures"),
            analysis_design=spec.get("analysis_design", ""),
            unit_analysis_plan=spec.get("unit_analysis_plan", ""),
            unit_id_column=spec.get("unit_id_column", ""),
            analysis_specification_sha256=spec.get("analysis_specification_sha256", ""),
            analysis_contract=analysis_contract,
            analysis_steps=analysis_steps,
            conclusion_contract=conclusion_contract,
            sample_size_or_stopping_rule=spec.get("sample_size_or_stopping_rule", ""),
            sample_size_plan=spec.get("sample_size_plan", {}),
            inclusion_rules=lists["inclusion_rules"],
            exclusion_rules=lists["exclusion_rules"],
            sensor_requirements=lists["sensor_requirements"],
            calibration_requirements=lists["calibration_requirements"],
            calibration_acceptance_criteria=calibration_criteria,
            measurement_custody_requirements=lists["measurement_custody_requirements"],
            clock_accuracy_requirement=spec.get("clock_accuracy_requirement", ""),
            preprocessing_pipeline=spec.get("preprocessing_pipeline", ""),
            statistical_model=spec.get("statistical_model", ""),
            control_windows=lists["control_windows"],
            multiple_testing_policy=spec.get("multiple_testing_policy", ""),
            missing_data_policy=spec.get("missing_data_policy", ""),
            causal_claim=spec.get("causal_claim", False),
            causal_identification=spec.get("causal_identification", {}),
            failure_conditions=lists["failure_conditions"],
            safety_constraints=lists["safety_constraints"],
            human_subjects=spec.get("human_subjects", False),
            consent_plan=spec.get("consent_plan", ""),
            withdrawal_plan=spec.get("withdrawal_plan", ""),
            privacy_plan=spec.get("privacy_plan", ""),
            retention_deletion_plan=spec.get("retention_deletion_plan", ""),
            risk_assessment=spec.get("risk_assessment", ""),
            vulnerable_population_plan=spec.get("vulnerable_population_plan", ""),
            data_security_plan=spec.get("data_security_plan", ""),
            incidental_findings_plan=spec.get("incidental_findings_plan", ""),
            independent_review_receipt=spec.get("independent_review_receipt", ""),
            independent_review_decision=spec.get("independent_review_decision", ""),
            independent_reviewer_role=spec.get("independent_reviewer_role", ""),
            independent_reviewed_at=spec.get("independent_reviewed_at", ""),
            independent_review_scope=spec.get("independent_review_scope", ""),
            independent_review_artifact_locator=spec.get("independent_review_artifact_locator", ""),
            independent_review_artifact_sha256=spec.get("independent_review_artifact_sha256", ""),
            independent_review_conditions=lists["independent_review_conditions"],
            analysis_code_hash=spec.get("analysis_code_hash", ""),
            external_anchor=spec.get("external_anchor"),
            random_seed_commitment=spec.get("random_seed_commitment"),
        )
    except KeyError as exc:
        raise ValueError(f"protocol is missing field {exc.args[0]}") from exc


def _run_command(
    spec: dict[str, Any],
    *,
    artifact_root: Path | None = None,
    attestation_schema: Path | None = None,
    expected_attestation_schema_sha256: str | None = None,
) -> RecordRun:
    dataset_ids = _json_text_list(spec.get("dataset_ids", []), "dataset_ids")
    outputs = _dataset_artifacts({"artifacts": spec.get("output_artifacts", [])}, [])
    gate_values = spec.get("quality_gates", [])
    if not isinstance(gate_values, list):
        raise ValueError("quality_gates must be an array")
    gates: list[QualityGateResult] = []
    for value in gate_values:
        if not isinstance(value, dict):
            raise ValueError("each quality gate must be an object")
        unknown = sorted(
            set(value) - {"gate_id", "status", "summary", "required", "details"}
        )
        if unknown:
            raise ValueError("unknown quality gate fields: " + ", ".join(unknown))
        try:
            gates.append(
                QualityGateResult(
                    gate_id=value["gate_id"],
                    status=QualityGateStatus(value["status"]),
                    summary=value["summary"],
                    required=value.get("required", True),
                    details=value.get("details", {}),
                )
            )
        except KeyError as exc:
            raise ValueError(f"quality gate is missing field {exc.args[0]}") from exc
    required = (
        "protocol_id",
        "started_at",
        "completed_at",
        "analysis_code_hash",
        "environment_hash",
    )
    missing = [field for field in required if field not in spec]
    if missing:
        raise ValueError("run is missing fields: " + ", ".join(missing))
    return RecordRun(
        protocol_id=spec["protocol_id"],
        started_at=spec["started_at"],
        completed_at=spec["completed_at"],
        analysis_code_hash=spec["analysis_code_hash"],
        environment_hash=spec["environment_hash"],
        random_seed_reveal=spec.get("random_seed_reveal"),
        dataset_ids=dataset_ids,
        output_artifacts=outputs,
        quality_gates=gates,
        summary=spec.get("summary", ""),
        synthetic=spec.get("synthetic", False),
        metadata=spec.get("metadata", {}),
        run_id=spec.get("run_id"),
        artifact_root=(
            str(artifact_root.resolve()) if artifact_root is not None else None
        ),
        attestation_schema_path=(
            str(attestation_schema.resolve())
            if attestation_schema is not None
            else None
        ),
        expected_attestation_schema_sha256=(expected_attestation_schema_sha256),
    )


def _action_candidates(spec: dict[str, Any]) -> list[ActionCandidate]:
    candidate_values = spec.get("candidates")
    if not isinstance(candidate_values, list):
        raise ValueError("candidates must be an array")
    candidates: list[ActionCandidate] = []
    fields = {
        "action_id",
        "title",
        "distinguishes_hypotheses",
        "expected_discrimination",
        "uncertainty_reduction",
        "cost",
        "burden",
        "safety_risk",
        "ambiguity_risk",
        "rationale",
        "prerequisites_met",
        "safety_approved",
        "lane_id",
        "information_targets",
        "depends_on",
        "manipulated_factors",
        "factorial_or_crossover_design",
        "factor_interpretability_plan",
        "metadata",
    }
    for value in candidate_values:
        if not isinstance(value, dict):
            raise ValueError("each candidate must be an object")
        unknown = sorted(set(value) - fields)
        if unknown:
            raise ValueError("unknown candidate fields: " + ", ".join(unknown))
        try:
            candidates.append(ActionCandidate.from_dict(value))
        except TypeError as exc:
            raise ValueError(f"invalid action candidate: {exc}") from exc
    return candidates


def _selection_weights(spec: dict[str, Any]) -> SelectionWeights:
    weight_value = spec.get("weights", {})
    if not isinstance(weight_value, dict):
        raise ValueError("weights must be an object")
    try:
        return SelectionWeights.from_dict(weight_value)
    except TypeError as exc:
        raise ValueError(f"invalid selection weights: {exc}") from exc


def _recommendation_command(spec: dict[str, Any]) -> RecommendNextAction:
    return RecommendNextAction(
        candidates=_action_candidates(spec), weights=_selection_weights(spec)
    )


def _portfolio_recommendation_command(
    spec: dict[str, Any],
) -> RecommendActionPortfolio:
    lane_values = spec.get("lanes")
    if not isinstance(lane_values, list):
        raise ValueError("lanes must be an array")
    lanes: list[ActionLane] = []
    fields = {"lane_id", "title", "status", "blocked_on"}
    for value in lane_values:
        if not isinstance(value, dict):
            raise ValueError("each lane must be an object")
        unknown = sorted(set(value) - fields)
        if unknown:
            raise ValueError("unknown lane fields: " + ", ".join(unknown))
        try:
            lanes.append(ActionLane.from_dict(value))
        except TypeError as exc:
            raise ValueError(f"invalid action lane: {exc}") from exc
    completed = spec.get("completed_action_ids", [])
    if not isinstance(completed, list):
        raise ValueError("completed_action_ids must be an array")
    return RecommendActionPortfolio(
        lanes=lanes,
        candidates=_action_candidates(spec),
        completed_action_ids=completed,
        weights=_selection_weights(spec),
    )


def _cross_lane_lesson_command(spec: dict[str, Any]) -> RecordCrossLaneLesson:
    try:
        return RecordCrossLaneLesson(**spec)
    except TypeError as exc:
        raise ValueError(f"invalid cross-lane lesson: {exc}") from exc


def _dispatch(args: argparse.Namespace, service: ResearchService) -> Any:
    configured_paths = [
        Path(value)
        for value in os.environ.get("RESEARCH_ADDON_PATH", "").split(os.pathsep)
        if value
    ]
    configured_paths.extend(args.addon_path)
    registry = load_local_addons(default_registry(), configured_paths)
    if args.group == "addon":
        if args.action == "list":
            return [manifest.describe() for manifest in registry.list()]
        return registry.get(args.addon_id).describe()

    if args.group == "analysis" and args.action == "run-draft":
        from research_machine.addons.receipt import execution_run_draft
        return execution_run_draft(service, args.execution_directory, args.expected_receipt_sha256, args.inquiry)

    if args.group == "analysis" and args.action == "materialize-holm":
        from research_machine.addons.workflow import materialize_holm_family
        return materialize_holm_family(
            service, args.protocol, args.manifest_file,
            args.expected_manifest_sha256, args.output, args.inquiry,
        )

    if args.group == "analysis" and args.action == "adjudicate-holm":
        from research_machine.addons.workflow import adjudicate_holm_workflow
        return adjudicate_holm_workflow(
            service, args.protocol, args.manifest_file,
            args.expected_manifest_sha256, args.output, args.inquiry,
        )

    if args.group == "analysis" and args.action == "adjudication-run-draft":
        from research_machine.addons.workflow import workflow_adjudication_run_draft
        return workflow_adjudication_run_draft(
            service, args.adjudication_directory,
            args.expected_receipt_sha256, args.inquiry,
        )

    if args.group == "analysis" and args.action == "run":
        if bool(args.protocol) != bool(args.dataset):
            raise ValueError("analysis --protocol and --dataset must be supplied together")
        design_check = None
        if args.protocol:
            design_check = lambda spec, unit_structure, digest, spec_digest, input_digest, input_size, inference_level: service.validate_analysis_execution(
                args.protocol, spec,
                unit_structure,
                digest, spec_digest, args.dataset, input_digest, input_size,
                inference_level, args.inquiry
            )
        return execute_analysis(
            registry=registry,
            spec_path=args.spec_file,
            data_path=args.data_file,
            output_dir=args.output,
            design_check=design_check,
        )

    if args.group == "design" and args.action == "interview":
        from research_machine.design.interview import interview_design

        if args.output is not None and args.revise_hypothesis:
            raise ValueError("choose either a new experiment --output or --revise-hypothesis")
        if args.inquiry and not args.revise_hypothesis:
            raise ValueError("interview --inquiry requires --revise-hypothesis")
        if args.revise_hypothesis:
            state = service.show_inquiry(args.inquiry)
            if args.revise_hypothesis not in {item["hypothesis_id"] for item in state["hypotheses"]}:
                raise ValueError("revision hypothesis does not exist in the selected inquiry")
            args.inquiry = state["inquiry"]["inquiry_id"]

        def ask(prompt: str) -> str:
            print(prompt, file=sys.stderr, flush=True)
            try:
                return input()
            except (EOFError, KeyboardInterrupt) as exc:
                raise ValueError("design interview cancelled; no experiment or revision was created") from exc

        reason = ""
        if args.revise_hypothesis:
            while not reason:
                reason = ask("Why are you revising this design? Describe any results that informed the change. [required]").strip()
        result = interview_design(ask)
        if args.revise_hypothesis:
            from research_machine.design.revision import revise_design
            result["revision"] = revise_design(
                service, result["brief"], hypothesis_id=args.revise_hypothesis,
                reason=reason, inquiry_id=args.inquiry,
            )
        if args.output is not None:
            result["experiment"] = initialize_experiment_repository(result["brief"], args.output, actor=args.actor)
        return result

    if args.group == "design" and args.action in {"scaffold", "revise"}:
        brief = _read_json_object(
            args.brief_file,
            allowed_fields={
                "title", "question", "decision", "study_type", "population", "setting",
                "intervention", "exposure_definition", "assignment_type",
                "outcome", "outcome_unit", "outcome_scale",
                "outcome_admissible_values", "outcome_valid_min", "outcome_valid_max",
                "outcome_missing_value_codes", "primary_analysis_family",
                "primary_estimand", "contrast_definition", "expected_effect_direction",
                "contrast_groups", "group_data_column",
                "null_value", "support_rule", "confidence_level",
                "measurement_observable", "measurement_input_condition", "measurement_parameter_values",
                "measurement_evaluation_point", "measurement_convention",
                "measurement_aggregation", "measurement_tolerance",
                "measurement_expected_behavior", "measurement_temporal_role",
                "outcome_data_column",
                "measurement_validity_checks",
                "secondary_measurements",
                "control_measurements",
                "causal_measurements",
                "sample_size_plan",
                "unit_of_observation",
                "comparison", "sampling_plan", "randomization_plan", "blinding_plan",
                "controls", "confounds", "calibration_plan", "measurement_validity",
                "analysis_commitment", "stopping_rule", "human_participants", "consent_plan",
                "privacy_plan", "withdrawal_plan", "retention_deletion_plan",
                "vulnerable_population_plan", "data_security_plan", "incidental_findings_plan",
                "independent_review", "independent_review_receipt",
                "independent_review_decision", "independent_reviewer_role",
                "independent_reviewed_at", "independent_review_scope",
                "independent_review_artifact_locator",
                "independent_review_artifact_sha256", "independent_review_conditions",
                "risk_description", "exclusions", "independent_unit", "repeated_measures", "analysis_design",
                "observable_prediction", "null_model", "falsification_conditions",
                "control_definitions", "sample_size_justification", "secondary_outcomes", "unit_analysis_plan",
                "multiple_testing_policy", "minimum_analyzable_units", "maximum_excluded_fraction",
                "maximum_group_excluded_fraction_difference",
                "missingness_assumption", "missingness_assessment_plan",
                "missingness_failure_response", "missingness_assessment_kind",
                "missingness_assessment_gate_id",
                "smallest_effect_size_of_interest", "effect_scale",
                "conclusion_time_window", "non_supporting_direction",
                "higher_level_conclusions_unsupported",
                "unit_id_column",
                "causal_identification",
            },
            label="design brief",
        )
        if args.action == "revise":
            from research_machine.design.revision import revise_design
            return revise_design(service, brief, hypothesis_id=args.hypothesis,
                                 reason=args.reason, inquiry_id=args.inquiry)
        return scaffold_design(brief)

    if args.group == "design" and args.action == "initialize":
        brief = _read_json_object(
            args.brief_file,
            allowed_fields={
                "title", "question", "decision", "study_type", "population", "setting",
                "intervention", "exposure_definition", "assignment_type",
                "outcome", "outcome_unit", "outcome_scale",
                "outcome_admissible_values", "outcome_valid_min", "outcome_valid_max",
                "outcome_missing_value_codes", "primary_analysis_family",
                "primary_estimand", "contrast_definition", "expected_effect_direction",
                "contrast_groups", "group_data_column",
                "null_value", "support_rule", "confidence_level",
                "measurement_observable", "measurement_input_condition", "measurement_parameter_values",
                "measurement_evaluation_point", "measurement_convention",
                "measurement_aggregation", "measurement_tolerance",
                "measurement_expected_behavior", "measurement_temporal_role",
                "outcome_data_column",
                "measurement_validity_checks",
                "secondary_measurements",
                "control_measurements",
                "causal_measurements",
                "sample_size_plan",
                "unit_of_observation",
                "comparison", "sampling_plan", "randomization_plan", "blinding_plan",
                "controls", "confounds", "calibration_plan", "measurement_validity",
                "analysis_commitment", "stopping_rule", "human_participants", "consent_plan",
                "privacy_plan", "withdrawal_plan", "retention_deletion_plan",
                "vulnerable_population_plan", "data_security_plan", "incidental_findings_plan",
                "independent_review", "independent_review_receipt",
                "independent_review_decision", "independent_reviewer_role",
                "independent_reviewed_at", "independent_review_scope",
                "independent_review_artifact_locator",
                "independent_review_artifact_sha256", "independent_review_conditions",
                "risk_description", "exclusions", "independent_unit", "repeated_measures", "analysis_design",
                "observable_prediction", "null_model", "falsification_conditions",
                "control_definitions", "sample_size_justification", "secondary_outcomes", "unit_analysis_plan",
                "multiple_testing_policy", "minimum_analyzable_units", "maximum_excluded_fraction",
                "maximum_group_excluded_fraction_difference",
                "missingness_assumption", "missingness_assessment_plan",
                "missingness_failure_response", "missingness_assessment_kind",
                "missingness_assessment_gate_id",
                "smallest_effect_size_of_interest", "effect_scale",
                "conclusion_time_window", "non_supporting_direction",
                "higher_level_conclusions_unsupported",
                "unit_id_column",
                "causal_identification",
            },
            label="design brief",
        )
        return initialize_experiment_repository(
            brief,
            args.output,
            actor=args.actor,
            initialize_git=not args.no_git,
        )

    if args.group == "design" and args.action == "precision":
        spec, specification_sha256, specification_size = _read_json_object_and_hash(
            args.spec_file,
            allowed_fields={
                "study_design",
                "target_half_width",
                "assumed_standard_deviation",
                "confidence_level",
                "anticipated_attrition_fraction",
                "maximum_observed_to_assumed_sd_ratio",
                "sensitivity_standard_deviations",
            },
            label="precision plan",
        )
        result = plan_two_group_precision(spec)
        result["provenance"] = {
            "scope": "precision_planning_input_snapshot",
            "specification_sha256": specification_sha256,
            "specification_size_bytes": specification_size,
            "specification": spec,
            "scientific_evidence_eligible": False,
            "notice": "Binds the parsed input bytes only; does not preregister a study, validate assumptions, or authenticate a planning date.",
        }
        return result

    if args.group == "design" and args.action == "power":
        spec, specification_sha256, specification_size = _read_json_object_and_hash(
            args.spec_file,
            allowed_fields={
                "study_design",
                "smallest_effect_size_of_interest",
                "assumed_standard_deviation",
                "alpha",
                "target_power",
                "alternative",
                "anticipated_attrition_fraction",
                "maximum_observed_to_assumed_sd_ratio",
                "sensitivity_effect_sizes",
                "sensitivity_standard_deviations",
            },
            label="power plan",
        )
        result = plan_two_group_power(spec)
        result["provenance"] = {
            "scope": "power_planning_input_snapshot",
            "specification_sha256": specification_sha256,
            "specification_size_bytes": specification_size,
            "specification": spec,
            "scientific_evidence_eligible": False,
            "notice": "Binds the parsed input bytes only; does not preregister a study, validate assumptions, authenticate a planning date, or guarantee achieved power.",
        }
        return result

    if args.group == "design" and args.action == "equivalence-power":
        spec, specification_sha256, specification_size = _read_json_object_and_hash(
            args.spec_file,
            allowed_fields={
                "study_design", "equivalence_margin", "assumed_true_difference",
                "assumed_standard_deviation", "alpha", "target_power",
                "anticipated_attrition_fraction",
                "maximum_observed_to_assumed_sd_ratio",
                "sensitivity_true_differences", "sensitivity_standard_deviations",
            },
            label="equivalence power plan",
        )
        result = plan_two_group_equivalence_power(spec)
        result["provenance"] = {
            "scope": "equivalence_power_planning_input_snapshot",
            "specification_sha256": specification_sha256,
            "specification_size_bytes": specification_size,
            "specification": spec,
            "scientific_evidence_eligible": False,
            "notice": "Binds parsed inputs only; does not preregister a study, validate assumptions, authenticate a planning date, or establish equivalence.",
        }
        return result

    if args.group == "design" and args.action == "practical-power":
        spec, specification_sha256, specification_size = _read_json_object_and_hash(
            args.spec_file,
            allowed_fields={
                "study_design", "smallest_effect_size_of_interest",
                "assumed_true_effect", "assumed_standard_deviation", "alpha",
                "confidence_level", "target_power", "alternative",
                "anticipated_attrition_fraction",
                "maximum_observed_to_assumed_sd_ratio",
                "sensitivity_true_effects", "sensitivity_standard_deviations",
            },
            label="practical-significance power plan",
        )
        result = plan_two_group_practical_power(spec)
        result["provenance"] = {
            "scope": "practical_power_planning_input_snapshot",
            "specification_sha256": specification_sha256,
            "specification_size_bytes": specification_size,
            "specification": spec,
            "scientific_evidence_eligible": False,
            "notice": "Binds parsed inputs only; does not preregister a study, validate assumptions, authenticate a planning date, or establish practical significance.",
        }
        return result

    if args.group == "design" and args.action == "identify":
        spec, specification_sha256, specification_size = _read_json_object_and_hash(
            args.spec_file,
            allowed_fields={"nodes", "edges", "exposure", "outcome", "proposed_adjustment_set", "assignment_type", "assumptions", "causal_estimand"},
            label="causal identification specification",
        )
        result = audit_causal_identification(spec)
        result["provenance"] = {
            "scope": "causal_identification_input_snapshot",
            "specification": spec,
            "specification_sha256": specification_sha256,
            "specification_size_bytes": specification_size,
            "scientific_evidence_eligible": False,
            "notice": "Binds the supplied graph and assumption register; does not establish that either is true or register an analysis.",
        }
        return result

    if args.group == "design" and args.action == "randomize":
        spec, specification_sha256, specification_size = _read_json_object_and_hash(
            args.spec_file, allowed_fields={"unit_ids", "groups", "block_size", "seed", "strata"},
            label="randomization plan",
        )
        result = generate_blocked_assignment(spec)
        result["provenance"] = {
            "scope": "randomization_input_snapshot", "specification": spec,
            "specification_sha256": specification_sha256,
            "specification_size_bytes": specification_size,
            "notice": "Binds the supplied specification bytes; it does not authenticate when unit order was fixed or assignments were implemented.",
        }
        return result

    if args.group == "measurement" and args.action == "template":
        return service.measurement_custody_template(args.protocol, args.inquiry)

    if args.group == "measurement" and args.action == "validate":
        receipt = _read_json_object(
            args.receipt_file,
            allowed_fields={
                "receipt_id",
                "raw_sources",
                "transformations",
                "calibrations",
                "quality_gates",
                "derived_observations",
                "evidence_artifacts",
            },
            label="measurement custody receipt",
        )
        validated = validate_measurement_custody(receipt, args.require_gate)
        result = {"status": "passed", "receipt": validated,
                  "verification_scope": "custody_reference_consistency",
                  "scientific_evidence_eligible": False}
        if args.artifact_root is not None:
            from research_machine.application.artifact_integrity import verify_run_artifacts
            from research_machine.application.policies import validate_dataset_artifacts
            artifacts = validate_dataset_artifacts([
                DatasetArtifact(locator=item["locator"], sha256=item["sha256"], size_bytes=item.get("size_bytes"))
                for item in [
                    *validated["raw_sources"], *validated["evidence_artifacts"],
                    *({"locator": item["implementation_locator"], "sha256": item["implementation_sha256"]}
                      for item in validated["transformations"]),
                    *({"locator": item["output_locator"], "sha256": item["output_sha256"]}
                      for item in validated["transformations"]),
                ]
            ])
            report = verify_run_artifacts(
                artifacts, artifact_root=str(args.artifact_root), actor=args.actor,
                analysis_code_hash="", run_metadata={}, attestation_schema_path=None,
                expected_attestation_schema_sha256=None,
            )
            if report.status != "passed":
                raise ValueError("custody artifact verification failed: " + ", ".join(item["code"] for item in report.findings))
            result["verification_scope"] = "custody_references_complete_transformation_chain_bytes"
            result["artifact_integrity"] = report.to_dict()
        return result

    if args.group == "measurement" and args.action == "record":
        # Template generation performs the same frozen-protocol commitment check
        # used by the service before we publish an external write-once artifact.
        service.measurement_custody_template(args.protocol, args.inquiry)
        protocols = {
            item.protocol_id: item for item in service.list_protocols(args.inquiry)
        }
        protocol = protocols.get(args.protocol)
        if protocol is None:
            raise ValueError(f"protocol {args.protocol} does not exist")
        return create_measurement_custody_record(
            args.receipt_file,
            args.expected_receipt_sha256,
            protocol,
            args.artifact_root,
            args.output,
            actor=args.actor,
        )

    if args.group == "measurement" and args.action == "verify-record":
        service.measurement_custody_template(args.protocol, args.inquiry)
        protocols = {
            item.protocol_id: item for item in service.list_protocols(args.inquiry)
        }
        protocol = protocols.get(args.protocol)
        if protocol is None:
            raise ValueError(f"protocol {args.protocol} does not exist")
        return verify_measurement_custody_record(
            args.record_file,
            args.expected_record_sha256,
            args.receipt_file,
            protocol,
            args.artifact_root,
            actor=args.actor,
        )

    if args.group == "measurement" and args.action == "inspect-source":
        from research_machine.measurement.instrument import inspect_instrument_source

        manifest, adapter = registry.resolve_instrument_adapter(args.adapter)
        config = _read_json_object(
            args.config_file,
            allowed_fields=set(adapter.required_config_fields)
            | set(adapter.optional_config_fields),
            label="instrument adapter config",
        )
        return inspect_instrument_source(
            manifest, adapter, args.source_file, args.media_type, config, args.output
        )

    if args.group == "measurement" and args.action == "verify-source-inspection":
        from research_machine.measurement.instrument import verify_instrument_inspection

        manifest, adapter = registry.resolve_instrument_adapter(args.adapter)
        config = _read_json_object(
            args.config_file,
            allowed_fields=set(adapter.required_config_fields)
            | set(adapter.optional_config_fields),
            label="instrument adapter config",
        )
        return verify_instrument_inspection(
            manifest,
            adapter,
            args.source_file,
            args.media_type,
            config,
            args.record_file,
            args.expected_record_sha256,
        )

    if args.group == "measurement" and args.action == "assess-timing":
        from research_machine.measurement.instrument import assess_stream_timing

        return assess_stream_timing(
            args.inspection_file,
            args.expected_inspection_sha256,
            args.spec_file,
            args.output,
        )

    if args.group == "measurement" and args.action == "assess-temporal-order":
        from research_machine.measurement.instrument import assess_temporal_order

        return assess_temporal_order(
            args.timing_assessment_file,
            args.expected_timing_assessment_sha256,
            args.spec_file,
            args.output,
        )

    if args.group == "measurement" and args.action == "assess-preprocessing":
        from research_machine.measurement.preprocessing import (
            assess_preprocessing_conformance,
        )

        return assess_preprocessing_conformance(
            args.registered_pipeline_file,
            args.expected_registered_pipeline_sha256,
            args.observed_pipeline_file,
            args.expected_observed_pipeline_sha256,
            args.output,
        )

    if args.group == "ethics" and args.action == "record-status":
        return service.record_ethics_review_event(
            RecordEthicsReviewEvent(
                protocol_id=args.protocol,
                status=args.status,
                effective_at=args.effective_at,
                expires_at=args.expires_at,
                reason=args.reason,
                review_artifact_locator=args.review_artifact_locator,
                review_artifact_sha256=args.review_artifact_sha256,
                review_artifact_root=str(args.review_artifact_root),
                supersedes_event_id=args.supersedes_event,
                event_id=args.event_id,
            ),
            args.inquiry,
        ).to_dict()

    if args.group == "replication" and args.action == "verify":
        from research_machine.replication.package import verify_replication_package
        return verify_replication_package(args.package, args.expected_manifest_sha256)

    if args.group == "replication" and args.action == "package":
        return service.export_replication_package(
            args.protocol,
            str(args.output),
            args.inquiry,
            include_locators=args.include_locators,
        )

    if args.group == "collaborator" and args.action == "context":
        context = service.collaborator_context(args.inquiry, purpose=args.purpose)
        if args.output is None:
            return context
        from research_machine.collaboration.proposal import create_context_snapshot
        return create_context_snapshot(context, args.output)

    if args.group == "collaborator" and args.action == "validate-proposal":
        from research_machine.collaboration.proposal import validate_collaborator_proposal
        return validate_collaborator_proposal(
            args.context_file,
            args.expected_context_sha256,
            args.proposal_file,
            args.output,
        )

    if args.group == "collaborator" and args.action == "review-proposal":
        from research_machine.collaboration.proposal import adjudicate_collaborator_proposal
        return adjudicate_collaborator_proposal(
            args.proposal_record_file,
            args.expected_proposal_record_sha256,
            args.review_file,
            args.output,
        )

    if args.group == "literature" and args.action == "screen":
        from research_machine.literature.screening import create_screening
        review = _read_json_object(args.review_file, allowed_fields={"reviewer", "decisions"}, label="screening review")
        return create_screening(args.snapshot_file, args.expected_snapshot_sha256, review, args.output)

    if args.group == "literature" and args.action == "extract":
        from research_machine.literature.extraction import create_extraction
        review = _read_json_object(args.review_file, allowed_fields={"reviewer", "source_reviews"}, label="extraction review")
        return create_extraction(args.screening_file, args.expected_screening_sha256, review, args.output)

    if args.group == "literature" and args.action == "verify-citations":
        from research_machine.literature.verification import create_citation_verification
        review = _read_json_object(args.review_file, allowed_fields={"reviewer", "assessments"}, label="citation review")
        return create_citation_verification(
            args.extraction_file, args.expected_extraction_sha256, review, args.output
        )

    if args.group == "literature" and args.action == "assess-bias":
        from research_machine.literature.bias import create_bias_assessment
        review = _read_json_object(args.review_file, allowed_fields={"reviewer", "assessments"}, label="bias review")
        return create_bias_assessment(
            args.citation_verification_file,
            args.expected_citation_verification_sha256,
            review,
            args.output,
        )

    if args.group == "literature" and args.action == "reconcile-studies":
        from research_machine.literature.studies import create_study_reconciliation
        review = _read_json_object(
            args.review_file,
            allowed_fields={"reviewer", "studies", "relationships"},
            label="study reconciliation review",
        )
        return create_study_reconciliation(
            args.bias_assessment_file,
            args.expected_bias_assessment_sha256,
            review,
            args.output,
        )

    if args.group == "literature" and args.action == "evidence-map":
        from research_machine.literature.evidence_map import create_evidence_map
        return create_evidence_map(
            args.extraction_file, args.citation_verification_file,
            args.bias_assessment_file, args.study_reconciliation_file,
            args.expected_study_reconciliation_sha256, args.output,
        )

    if args.group == "literature" and args.action == "plan-synthesis":
        from research_machine.literature.synthesis_plan import create_synthesis_plan
        specification = _read_json_object(
            args.spec_file,
            allowed_fields={
                "plan_id", "reviewer", "research_question", "primary_outcome",
                "synthesis_type", "effect_measure", "contrast_definition", "statistical_model",
                "minimum_independent_studies", "eligibility_policy", "missing_statistics_policy",
                "heterogeneity_policy", "multiplicity_policy", "subgroup_analyses",
                "sensitivity_analyses", "conclusion_rule", "deviation_policy",
            },
            label="synthesis plan",
        )
        return create_synthesis_plan(
            args.screening_file, args.expected_screening_sha256, specification, args.output
        )

    if args.group == "literature" and args.action == "synthesize":
        from research_machine.literature.synthesis import execute_qualitative_synthesis
        return execute_qualitative_synthesis(
            args.plan_file, args.expected_plan_sha256, args.extraction_file,
            args.evidence_map_file, args.expected_evidence_map_sha256,
            args.deviations_file, args.expected_deviations_sha256, args.output,
        )

    if args.group == "literature" and args.action == "prepare-effects":
        from research_machine.literature.effects import create_effect_records
        review = _read_json_object(args.review_file, allowed_fields={"reviewer", "records"}, label="effect review")
        return create_effect_records(
            args.plan_file, args.expected_plan_sha256, args.extraction_file,
            args.evidence_map_file, args.expected_evidence_map_sha256, review, args.output,
        )

    if args.group == "literature" and args.action == "derive-effects":
        from research_machine.literature.effect_derivation import derive_effect_records
        summaries = _read_json_object(args.summaries_file, allowed_fields={"reviewer", "records"}, label="effect summaries")
        return derive_effect_records(
            args.plan_file, args.expected_plan_sha256, args.extraction_file,
            args.evidence_map_file, args.expected_evidence_map_sha256, summaries, args.output,
        )

    if args.group == "literature" and args.action == "verify-effects":
        from research_machine.literature.effect_verification import create_effect_verification
        review = _read_json_object(args.review_file, allowed_fields={"reviewer", "assessments"}, label="effect verification")
        return create_effect_verification(args.effects_file, args.expected_effects_sha256, review, args.output)

    if args.group == "literature" and args.action == "pool-effects":
        from research_machine.literature.meta_analysis import execute_meta_analysis
        return execute_meta_analysis(
            args.plan_file, args.expected_plan_sha256,
            args.effects_file, args.expected_effects_sha256,
            args.effect_verification_file, args.expected_effect_verification_sha256,
            args.deviations_file, args.expected_deviations_sha256, args.output,
        )

    if args.group == "literature" and args.action == "record-deviations":
        from research_machine.literature.deviations import create_synthesis_deviations
        disclosure = _read_json_object(
            args.disclosure_file, allowed_fields={"reviewer", "deviations"},
            label="synthesis deviation disclosure",
        )
        return create_synthesis_deviations(
            args.plan_file, args.expected_plan_sha256, disclosure, args.output
        )

    if args.group == "literature" and args.action == "snapshot":
        manifest = _read_json_object(
            args.manifest_file,
            allowed_fields={
                "snapshot_id", "query", "inclusion_criteria", "exclusion_criteria", "sources"
            },
            label="literature snapshot",
        )
        return create_snapshot(manifest, args.output)

    if args.group == "workspace":
        if args.action == "init":
            return service.init_workspace()
        if args.action == "verify":
            return service.verify_ledger(args.inquiry)
        return service.audit_rigor(args.inquiry, fail_on=args.fail_on).to_dict()

    if args.group == "inquiry":
        if args.action == "create":
            return service.create_inquiry(
                CreateInquiry(
                    title=args.title,
                    initial_statement=args.statement,
                    inquiry_id=args.inquiry_id,
                    decision_to_support=args.decision,
                    minimum_evidence=args.minimum_evidence,
                    decision_change_criteria=args.change_criterion,
                    decision_owner=args.decision_owner,
                )
            ).to_dict()
        if args.action == "select":
            return service.select_inquiry(args.inquiry_id).to_dict()
        if args.action == "decision":
            return service.set_inquiry_decision(
                SetInquiryDecision(
                    decision_to_support=args.decision,
                    minimum_evidence=args.minimum_evidence,
                    decision_change_criteria=args.change_criterion,
                    decision_owner=args.decision_owner,
                ),
                args.inquiry,
            ).to_dict()
        return service.show_inquiry(args.inquiry)

    if args.group == "question":
        if args.action == "add":
            return service.add_question(AddQuestion(args.text), args.inquiry).to_dict()
        if args.action == "answer":
            return service.answer_question(
                args.question_id, args.answer, args.inquiry
            ).to_dict()
        return service.show_inquiry(args.inquiry)["questions"]

    if args.group == "claim":
        if args.action == "add":
            return service.add_claim(
                AddClaim(
                    statement=args.statement,
                    level=ClaimLevel(args.level),
                    parent_claims=args.parent_claim,
                    scope=args.scope,
                    epistemic_layer=ClaimEpistemicLayer(args.epistemic_layer),
                    disposition=ClaimDisposition(args.disposition),
                    confidence=args.confidence,
                    source_refs=args.source_ref,
                    conflicts_with=args.conflicts_with,
                    falsified_by=args.falsified_by,
                    last_reviewed=args.last_reviewed,
                    decision_owner=args.decision_owner,
                ),
                args.inquiry,
            ).to_dict()
        if args.action == "review":
            return service.review_claim(
                ReviewClaim(
                    claim_id=args.claim_id,
                    epistemic_layer=(
                        ClaimEpistemicLayer(args.epistemic_layer)
                        if args.epistemic_layer
                        else None
                    ),
                    disposition=(
                        ClaimDisposition(args.disposition) if args.disposition else None
                    ),
                    confidence=args.confidence,
                    source_refs=args.source_ref,
                    conflicts_with=args.conflicts_with,
                    falsified_by=args.falsified_by,
                    reviewed_at=args.reviewed_at,
                    decision_owner=args.decision_owner,
                ),
                args.inquiry,
            ).to_dict()
        return service.show_inquiry(args.inquiry)["claims"]

    if args.group == "hypothesis":
        if args.action == "propose":
            proposal = _read_proposal(args.proposal_file)
            command = ProposeHypothesis(
                statement=_choose(args.statement, proposal, "statement", ""),
                generated_by=_choose(
                    args.generated_by, proposal, "generated_by", "codex"
                ),
                parent_claims=_choose_list(
                    args.parent_claim, proposal, "parent_claims"
                ),
                lineage=_choose_list(args.lineage, proposal, "lineage"),
                source_context=_choose_list(
                    args.source_context, proposal, "source_context"
                ),
                scope=_choose(args.scope, proposal, "scope", ""),
                observable_prediction=_choose(
                    args.prediction, proposal, "observable_prediction", ""
                ),
                null_model=_choose(args.null_model, proposal, "null_model", ""),
                competing_models=_choose_list(
                    args.competing_model, proposal, "competing_models"
                ),
                causal_direction=_choose(
                    args.causal_direction, proposal, "causal_direction", ""
                ),
                primary_estimand=_choose(
                    args.primary_estimand, proposal, "primary_estimand", ""
                ),
                contrast_definition=_choose(
                    args.contrast_definition, proposal, "contrast_definition", ""
                ),
                contrast_groups=_choose_list(
                    args.contrast_group, proposal, "contrast_groups"
                ),
                expected_effect_direction=_choose(
                    args.expected_effect_direction,
                    proposal,
                    "expected_effect_direction",
                    "",
                ),
                time_window=_choose(args.time_window, proposal, "time_window", ""),
                covariates=_choose_list(args.covariate, proposal, "covariates"),
                known_confounds=_choose_list(
                    args.known_confound, proposal, "known_confounds"
                ),
                falsification_conditions=_choose_list(
                    args.falsification,
                    proposal,
                    "falsification_conditions",
                ),
                support_conditions=_choose_list(
                    args.support_condition,
                    proposal,
                    "support_conditions",
                ),
                boundary_conditions=_choose_list(
                    args.boundary_condition,
                    proposal,
                    "boundary_conditions",
                ),
                required_replications=_choose_optional_nonnegative_int(
                    args.required_replications,
                    proposal,
                    "required_replications",
                ),
            )
            return service.propose_hypothesis(command, args.inquiry).to_dict()
        if args.action == "activate":
            return service.activate_hypothesis(
                args.hypothesis_id, args.inquiry
            ).to_dict()
        if args.action == "stage":
            return service.stage_hypothesis(
                args.hypothesis_id,
                args.rationale,
                args.confidence,
                args.inquiry,
            ).to_dict()
        if args.action == "retire":
            return service.retire_hypothesis(
                RetireHypothesis(
                    hypothesis_id=args.hypothesis_id,
                    rejection_type=RejectionType(args.rejection_type),
                    reason=args.reason,
                    limitations=args.limitations,
                    resurrection_conditions=args.resurrection_condition,
                    superseded_by=args.superseded_by,
                ),
                args.inquiry,
            ).to_dict()
        return [
            hypothesis.to_dict()
            for hypothesis in service.list_hypotheses(args.inquiry, args.state)
        ]

    if args.group == "dataset":
        if args.action == "register":
            manifest = _read_json_object(
                args.manifest_file,
                allowed_fields=_DATASET_FIELDS,
                label="dataset manifest",
            )
            role_value = _choose(args.role, manifest, "role", None)
            if role_value is None:
                raise ValueError("dataset role is required")
            return service.register_dataset(
                RegisterDataset(
                    dataset_id=_choose(args.dataset_id, manifest, "dataset_id", None),
                    name=_choose(args.name, manifest, "name", ""),
                    role=DatasetRole(role_value),
                    artifacts=_dataset_artifacts(manifest, args.file),
                    description=_choose(args.description, manifest, "description", ""),
                    observation_unit=_choose(
                        args.observation_unit, manifest, "observation_unit", ""
                    ),
                    source_dataset_ids=_choose_list(
                        args.source_dataset, manifest, "source_dataset_ids"
                    ),
                    protocol_id=_choose(args.protocol, manifest, "protocol_id", None),
                    synthetic=_choose(args.synthetic, manifest, "synthetic", False),
                    quality_attestations=_choose_list(
                        args.quality_attestation,
                        manifest,
                        "quality_attestations",
                    ),
                    metadata=manifest.get("metadata", {}),
                    artifact_root=(
                        str(args.artifact_root)
                        if args.artifact_root is not None
                        else None
                    ),
                    custody_artifact_root=(
                        str(args.custody_artifact_root)
                        if args.custody_artifact_root is not None
                        else None
                    ),
                    ethics_artifact_root=(
                        str(args.ethics_artifact_root)
                        if args.ethics_artifact_root is not None
                        else None
                    ),
                ),
                args.inquiry,
            ).to_dict()
        return [dataset.to_dict() for dataset in service.list_datasets(args.inquiry)]

    if args.group == "protocol":
        if args.action in {"create", "amend"}:
            spec = _read_json_object(
                args.spec_file, allowed_fields=_PROTOCOL_FIELDS, label="protocol"
            )
            protocol_command = _protocol_command(spec)
            if args.action == "create":
                return service.create_protocol(protocol_command, args.inquiry).to_dict()
            return service.amend_protocol(
                args.protocol_id, protocol_command, args.reason,
                args.timing, args.evidence_exposure, args.inquiry
            ).to_dict()
        if args.action == "freeze":
            return service.freeze_protocol(
                args.protocol_id, args.inquiry, external_anchor=args.external_anchor,
                review_artifact_root=(str(args.review_artifact_root) if args.review_artifact_root else None),
            ).to_dict()
        if args.action == "show":
            return service.get_protocol(args.protocol_id, args.inquiry).to_dict()
        protocols = service.list_protocols(args.inquiry)
        if args.status:
            protocols = [item for item in protocols if item.status.value == args.status]
        return [item.to_dict() for item in protocols]

    if args.group == "run":
        if args.action in {"record", "preflight"}:
            spec, record_file_sha256, record_file_size_bytes = (
                _read_json_object_and_hash(
                    args.record_file, allowed_fields=_RUN_FIELDS, label="run"
                )
            )
            if args.action == "record" and args.expect_record_sha256 is not None:
                expected = args.expect_record_sha256
                if (
                    len(expected) != 64
                    or expected.lower() != expected
                    or any(
                        character not in "0123456789abcdef" for character in expected
                    )
                ):
                    raise ValueError(
                        "expect-record-sha256 must be 64 lowercase hexadecimal characters"
                    )
                if record_file_sha256 != expected:
                    raise ValueError(
                        "run record hash mismatch: "
                        f"expected {expected}, observed {record_file_sha256}"
                    )
            run_command = _run_command(
                spec,
                artifact_root=args.artifact_root,
                attestation_schema=args.attestation_schema,
                expected_attestation_schema_sha256=(
                    args.expect_attestation_schema_sha256
                ),
            )
            if args.action == "record":
                return service.record_run(run_command, args.inquiry).to_dict()
            report = service.preflight_run(run_command, args.inquiry).to_dict()
            report["record_file_sha256"] = record_file_sha256
            report["record_file_size_bytes"] = record_file_size_bytes
            return report
        if args.action == "template":
            return service.run_record_template(args.protocol, args.inquiry)
        if args.action == "show":
            return service.get_run(args.run_id, args.inquiry).to_dict()
        return [run.to_dict() for run in service.list_runs(args.inquiry)]

    if args.group == "next-action":
        if args.action == "recommend":
            spec = _read_json_object(
                args.spec_file,
                allowed_fields=_ACTION_SPEC_FIELDS,
                label="next-action",
            )
            return service.recommend_next_action(
                _recommendation_command(spec), args.inquiry
            ).to_dict()
        if args.action == "portfolio":
            spec = _read_json_object(
                args.spec_file,
                allowed_fields=_ACTION_PORTFOLIO_SPEC_FIELDS,
                label="next-action portfolio",
            )
            return service.recommend_action_portfolio(
                _portfolio_recommendation_command(spec), args.inquiry
            ).to_dict()
        return [item.to_dict() for item in service.list_recommendations(args.inquiry)]

    if args.group == "cross-lane-lesson":
        if args.action == "record":
            spec = _read_json_object(
                args.spec_file,
                allowed_fields=_CROSS_LANE_LESSON_SPEC_FIELDS,
                label="cross-lane lesson",
            )
            return service.record_cross_lane_lesson(
                _cross_lane_lesson_command(spec), args.inquiry
            ).to_dict()
        return [
            item.to_dict()
            for item in service.list_cross_lane_lessons(args.inquiry)
        ]

    if args.group == "evidence":
        if args.action == "record":
            return service.record_evidence(
                RecordEvidence(
                    hypothesis_id=args.hypothesis,
                    claim_id=args.claim,
                    direction=EvidenceDirection(args.direction),
                    summary=args.summary,
                    dataset_id=args.dataset,
                    analysis_id=args.analysis,
                    run_id=args.run,
                    effect_estimate=args.effect_estimate,
                    uncertainty=args.uncertainty,
                    scope=args.scope,
                    controls_passed=args.control_passed,
                    controls_failed=args.control_failed,
                    higher_level_conclusions_unsupported=(
                        args.higher_conclusion_unsupported
                    ),
                    validation_tags=[
                        ValidationTag(value) for value in args.validation_tag
                    ],
                    exploratory=not args.confirmatory,
                    analysis_output_sha256=args.analysis_output_sha256,
                    effect_estimate_path=args.effect_estimate_path,
                    uncertainty_path=args.uncertainty_path,
                ),
                args.inquiry,
            ).to_dict()
        if args.action == "record-status":
            return service.record_evidence_status_event(
                RecordEvidenceStatusEvent(
                    evidence_id=args.evidence,
                    status=args.status,
                    effective_at=args.effective_at,
                    reason=args.reason,
                    review_artifact_locator=args.review_artifact_locator,
                    review_artifact_sha256=args.review_artifact_sha256,
                    review_artifact_root=str(args.review_artifact_root),
                    supersedes_event_id=args.supersedes_event,
                    event_id=args.event_id,
                ),
                args.inquiry,
            ).to_dict()
        if args.action == "status-history":
            return [
                item.to_dict()
                for item in service.list_evidence_status_events(
                    args.inquiry, evidence_id=args.evidence
                )
            ]
        return [record.to_dict() for record in service.list_evidence(args.inquiry)]

    if args.group == "synthesis" and args.action == "build":
        return service.build_synthesis(args.inquiry)
    raise ValueError("unhandled command")


def _render(value: Any, *, json_output: bool) -> None:
    if json_output:
        print(json.dumps({"ok": True, "result": value}, sort_keys=True))
        return
    if isinstance(value, dict) and "content" in value and "path" in value:
        print(value["path"])
        return
    print(json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False))


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    repository = FileSystemRepository(args.workspace)
    service = ResearchService(repository, actor=args.actor)
    try:
        result = _dispatch(args, service)
    except (ResearchMachineError, ValueError) as exc:
        if args.json:
            print(
                json.dumps(
                    {
                        "ok": False,
                        "error": {
                            "type": exc.__class__.__name__,
                            "message": str(exc),
                        },
                    },
                    sort_keys=True,
                ),
                file=sys.stderr,
            )
        else:
            print(f"error: {exc}", file=sys.stderr)
        return 2
    _render(result, json_output=args.json)
    if (
        args.group == "run"
        and args.action == "preflight"
        and isinstance(result, dict)
        and result.get("status") != "ready"
    ):
        return 1
    return 0
