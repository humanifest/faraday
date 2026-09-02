from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any, Sequence

from research_machine.adapters.filesystem import FileSystemRepository
from research_machine.application.commands import (
    AddClaim,
    AddQuestion,
    CreateInquiry,
    ProposeHypothesis,
    RecordEvidence,
    RetireHypothesis,
)
from research_machine.application.service import ResearchService
from research_machine.domain.errors import ResearchMachineError
from research_machine.domain.models import (
    ClaimLevel,
    EvidenceDirection,
    RejectionType,
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
        choices=["unreviewed", "active", "parked", "retired"],
    )
    _add_inquiry_option(hypothesis_list)

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
    record.add_argument("--dataset", required=True)
    record.add_argument("--analysis", required=True)
    record.add_argument("--claim")
    record.add_argument("--effect-estimate", default="")
    record.add_argument("--uncertainty", default="")
    record.add_argument("--scope", default="")
    record.add_argument("--control-passed", action="append", default=[])
    record.add_argument("--control-failed", action="append", default=[])
    record.add_argument("--higher-conclusion-unsupported", action="append", default=[])
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


def _read_proposal(path: Path | None) -> dict[str, Any]:
    if path is None:
        return {}
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"could not read proposal file {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise ValueError("proposal file must contain a JSON object")
    unknown = sorted(set(value) - _PROPOSAL_FIELDS)
    if unknown:
        raise ValueError("unknown proposal fields: " + ", ".join(unknown))
    return value


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


def _dispatch(args: argparse.Namespace, service: ResearchService) -> Any:
    if args.group == "workspace":
        if args.action == "init":
            return service.init_workspace()
        return service.verify_ledger(args.inquiry)

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
                    effect_estimate=args.effect_estimate,
                    uncertainty=args.uncertainty,
                    scope=args.scope,
                    controls_passed=args.control_passed,
                    controls_failed=args.control_failed,
                    higher_level_conclusions_unsupported=(
                        args.higher_conclusion_unsupported
                    ),
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
    return 0
