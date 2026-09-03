from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from pathlib import Path
from typing import Any, Sequence

from research_machine.adapters.filesystem import FileSystemRepository
from research_machine.application.commands import (
    AddClaim,
    AddQuestion,
    CreateProtocol,
    CreateInquiry,
    ProposeHypothesis,
    RecommendNextAction,
    RecordEvidence,
    RecordRun,
    RegisterDataset,
    RetireHypothesis,
)
from research_machine.application.service import ResearchService
from research_machine.domain.errors import ResearchMachineError
from research_machine.domain.models import (
    ActionCandidate,
    AnalysisMode,
    ClaimLevel,
    DatasetArtifact,
    DatasetRole,
    EvidenceDirection,
    HypothesisWorkflowState,
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
    "expected_outputs",
    "success_conditions",
    "environment_requirements",
    "secondary_outcomes",
    "independent_variables",
    "randomization_plan",
    "blinding_plan",
    "sampling_unit",
    "sample_size_or_stopping_rule",
    "inclusion_rules",
    "exclusion_rules",
    "sensor_requirements",
    "calibration_requirements",
    "clock_accuracy_requirement",
    "preprocessing_pipeline",
    "statistical_model",
    "control_windows",
    "multiple_testing_policy",
    "missing_data_policy",
    "failure_conditions",
    "safety_constraints",
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
    select = inquiry_commands.add_parser("select", help="Select the active inquiry")
    select.add_argument("inquiry_id")
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
    _add_inquiry_option(claim_add)
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
    _add_inquiry_option(protocol_freeze)
    protocol_amend = protocol_commands.add_parser("amend")
    protocol_amend.add_argument("protocol_id")
    protocol_amend.add_argument("--spec-file", type=Path, required=True)
    protocol_amend.add_argument("--reason", required=True)
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
    recommendation_list = next_action_commands.add_parser("list")
    _add_inquiry_option(recommendation_list)

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
    record.add_argument("--uncertainty", required=True)
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

    synthesis = groups.add_parser("synthesis", help="Build deterministic reports")
    synthesis_commands = synthesis.add_subparsers(dest="action", required=True)
    synthesis_build = synthesis_commands.add_parser("build")
    _add_inquiry_option(synthesis_build)
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
        "independent_variables",
        "inclusion_rules",
        "exclusion_rules",
        "sensor_requirements",
        "calibration_requirements",
        "control_windows",
        "failure_conditions",
        "safety_constraints",
    }
    lists = {
        field: _json_text_list(spec.get(field, []), field) for field in list_fields
    }
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
            expected_outputs=lists["expected_outputs"],
            success_conditions=lists["success_conditions"],
            environment_requirements=lists["environment_requirements"],
            secondary_outcomes=lists["secondary_outcomes"],
            independent_variables=lists["independent_variables"],
            randomization_plan=spec.get("randomization_plan", ""),
            blinding_plan=spec.get("blinding_plan", ""),
            sampling_unit=spec.get("sampling_unit", ""),
            sample_size_or_stopping_rule=spec.get("sample_size_or_stopping_rule", ""),
            inclusion_rules=lists["inclusion_rules"],
            exclusion_rules=lists["exclusion_rules"],
            sensor_requirements=lists["sensor_requirements"],
            calibration_requirements=lists["calibration_requirements"],
            clock_accuracy_requirement=spec.get("clock_accuracy_requirement", ""),
            preprocessing_pipeline=spec.get("preprocessing_pipeline", ""),
            statistical_model=spec.get("statistical_model", ""),
            control_windows=lists["control_windows"],
            multiple_testing_policy=spec.get("multiple_testing_policy", ""),
            missing_data_policy=spec.get("missing_data_policy", ""),
            failure_conditions=lists["failure_conditions"],
            safety_constraints=lists["safety_constraints"],
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
        expected_attestation_schema_sha256=(
            expected_attestation_schema_sha256
        ),
    )


def _recommendation_command(spec: dict[str, Any]) -> RecommendNextAction:
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
    weight_value = spec.get("weights", {})
    if not isinstance(weight_value, dict):
        raise ValueError("weights must be an object")
    try:
        weights = SelectionWeights.from_dict(weight_value)
    except TypeError as exc:
        raise ValueError(f"invalid selection weights: {exc}") from exc
    return RecommendNextAction(candidates=candidates, weights=weights)


def _dispatch(args: argparse.Namespace, service: ResearchService) -> Any:
    if args.group == "workspace":
        if args.action == "init":
            return service.init_workspace()
        if args.action == "verify":
            return service.verify_ledger(args.inquiry)
        return service.audit_rigor(
            args.inquiry, fail_on=args.fail_on
        ).to_dict()

    if args.group == "inquiry":
        if args.action == "create":
            return service.create_inquiry(
                CreateInquiry(args.title, args.statement, args.inquiry_id)
            ).to_dict()
        if args.action == "select":
            return service.select_inquiry(args.inquiry_id).to_dict()
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
                args.protocol_id, protocol_command, args.reason, args.inquiry
            ).to_dict()
        if args.action == "freeze":
            return service.freeze_protocol(
                args.protocol_id, args.inquiry, external_anchor=args.external_anchor
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
                        character not in "0123456789abcdef"
                        for character in expected
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
            command = _run_command(
                spec,
                artifact_root=args.artifact_root,
                attestation_schema=args.attestation_schema,
                expected_attestation_schema_sha256=(
                    args.expect_attestation_schema_sha256
                ),
            )
            if args.action == "record":
                return service.record_run(command, args.inquiry).to_dict()
            report = service.preflight_run(command, args.inquiry).to_dict()
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
        return [item.to_dict() for item in service.list_recommendations(args.inquiry)]

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
                ),
                args.inquiry,
            ).to_dict()
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
