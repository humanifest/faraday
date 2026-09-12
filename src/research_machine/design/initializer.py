from __future__ import annotations

import hashlib
import json
import os
import subprocess
import tempfile
from pathlib import Path
from typing import Any

from research_machine.adapters.filesystem import FileSystemRepository
from research_machine.application.commands import (
    AddClaim,
    AddQuestion,
    CreateInquiry,
    ProposeHypothesis,
)
from research_machine.application.service import ResearchService
from research_machine.domain.errors import ValidationError
from research_machine.domain.models import ClaimLevel
from research_machine.design.scaffold import (
    inquiry_decision_commitments,
    scaffold_design,
    validate_brief,
)


def _write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


def _read_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValidationError(f"invalid initialized scaffold artifact JSON: {path.name}") from exc
    except OSError as exc:
        raise ValidationError(f"could not read initialized scaffold artifact: {path.name}") from exc


def _sha256_file(path: Path) -> str:
    try:
        return hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError as exc:
        raise ValidationError(f"could not hash initialized scaffold artifact: {path.name}") from exc


def _safe_draft_path(root: Path, name: str) -> Path:
    relative = Path(name)
    if relative.is_absolute() or ".." in relative.parts:
        raise ValidationError(f"invalid scaffold artifact name in manifest: {name}")
    return root / "drafts" / relative


def _verify_initialized_scaffold(
    staging: Path, scaffold: dict[str, Any], brief: dict[str, Any]
) -> dict[str, Any]:
    """Replay staged review-artifact hashes before publishing the experiment tree."""
    manifest_path = staging / "drafts" / "design-scaffold-provenance.json"
    manifest = _read_json(manifest_path)
    provenance = scaffold["provenance"]
    if (
        manifest.get("artifact_manifest_sha256")
        != provenance.get("artifact_manifest_sha256")
    ):
        raise ValidationError("initialized scaffold provenance manifest hash mismatch")
    entries = manifest.get("artifact_manifest")
    if not isinstance(entries, list):
        raise ValidationError("initialized scaffold provenance artifact_manifest must be a list")
    expected_names = set(scaffold["artifacts"]) - {"design-scaffold-provenance.json"}
    seen_names: set[str] = set()
    review_artifacts: list[dict[str, Any]] = []
    for entry in entries:
        if not isinstance(entry, dict):
            raise ValidationError("initialized scaffold provenance artifact entries must be objects")
        name = entry.get("name")
        digest = entry.get("content_sha256")
        media_type = entry.get("media_type")
        if not isinstance(name, str) or not name.strip():
            raise ValidationError("initialized scaffold provenance artifact entry is missing a name")
        if name in seen_names:
            raise ValidationError(f"duplicate initialized scaffold artifact entry: {name}")
        seen_names.add(name)
        if name not in expected_names:
            raise ValidationError(f"unexpected initialized scaffold artifact entry: {name}")
        if not isinstance(digest, str) or len(digest) != 64:
            raise ValidationError(f"initialized scaffold artifact {name} has an invalid digest")
        artifact_path = _safe_draft_path(staging, name)
        if not artifact_path.is_file():
            raise ValidationError(f"initialized scaffold artifact is missing: {name}")
        actual_digest = _sha256_file(artifact_path)
        if actual_digest != digest:
            raise ValidationError(f"initialized scaffold artifact hash mismatch: {name}")
        review_artifacts.append(
            {"name": name, "media_type": media_type, "content_sha256": digest}
        )
    if seen_names != expected_names:
        missing = sorted(expected_names - seen_names)
        raise ValidationError(
            "initialized scaffold provenance manifest is missing artifacts: "
            + ", ".join(missing)
        )

    claim_boundaries = _read_json(staging / "drafts" / "claim-boundaries-draft.json")
    if claim_boundaries.get("status") != "review_required":
        raise ValidationError("initialized claim boundaries draft must require review")
    if claim_boundaries.get("claims") != brief.get("claim_boundaries", []):
        raise ValidationError("initialized claim boundaries draft does not match brief")

    protocol = _read_json(staging / "drafts" / "protocol-draft.json")
    canary = _read_json(staging / "drafts" / "canary-target-plan-draft.json")
    protocol_plan = protocol.get("canary_target_plan")
    canary_plan = canary.get("canary_target_plan")
    if protocol_plan is None:
        if canary.get("status") != "unresolved":
            raise ValidationError("initialized canary target draft must be unresolved when no plan is supplied")
        canary_status = "absent"
    else:
        if canary.get("status") != "review_required":
            raise ValidationError("initialized canary target draft must require review")
        if canary_plan != protocol_plan:
            raise ValidationError("initialized canary target draft does not match protocol draft")
        required = canary.get("required_run_assessment")
        if not isinstance(required, dict):
            raise ValidationError("initialized canary target draft is missing required assessment metadata")
        if required.get("gate_id") != protocol_plan.get("assessment_gate_id"):
            raise ValidationError("initialized canary target assessment gate does not match protocol draft")
        shape = required.get("result_shape")
        if not isinstance(shape, dict):
            raise ValidationError("initialized canary target draft is missing result shape")
        if shape.get("plan_id") != protocol_plan.get("plan_id"):
            raise ValidationError("initialized canary target result shape has the wrong plan ID")
        if (
            shape.get("assignment_artifact_sha256")
            != protocol_plan.get("assignment_artifact_sha256")
        ):
            raise ValidationError(
                "initialized canary target result shape has the wrong assignment artifact hash"
            )
        canary_status = "review_required"

    preprocessing = _read_json(staging / "drafts" / "preprocessing-conformance-plan-draft.json")
    preprocessing_pipeline = protocol.get("preprocessing_pipeline")
    if not preprocessing_pipeline:
        if preprocessing.get("status") != "unresolved":
            raise ValidationError(
                "initialized preprocessing conformance draft must be unresolved when no pipeline is supplied"
            )
        preprocessing_status = "absent"
    else:
        if preprocessing.get("status") != "review_required":
            raise ValidationError("initialized preprocessing conformance draft must require review")
        if preprocessing.get("registered_pipeline_sha256") != preprocessing_pipeline:
            raise ValidationError(
                "initialized preprocessing conformance draft does not match protocol draft"
            )
        required_gate_id = preprocessing.get("required_gate_id")
        if required_gate_id not in protocol.get("quality_requirements", []):
            raise ValidationError(
                "initialized preprocessing conformance gate does not match protocol draft"
            )
        required = preprocessing.get("required_run_assessment")
        if not isinstance(required, dict):
            raise ValidationError(
                "initialized preprocessing conformance draft is missing required assessment metadata"
            )
        if required.get("details_key") != "preprocessing_conformance":
            raise ValidationError(
                "initialized preprocessing conformance draft uses the wrong assessment details key"
            )
        shape = required.get("result_shape")
        if not isinstance(shape, dict):
            raise ValidationError(
                "initialized preprocessing conformance draft is missing result shape"
            )
        if shape.get("registered_pipeline_sha256") != preprocessing_pipeline:
            raise ValidationError(
                "initialized preprocessing conformance result shape has the wrong registered pipeline hash"
            )
        preprocessing_status = "review_required"

    return {
        "review_artifacts": review_artifacts,
        "canary_target_plan_status": canary_status,
        "canary_target_plan_artifact": "drafts/canary-target-plan-draft.json",
        "preprocessing_conformance_plan_status": preprocessing_status,
        "preprocessing_conformance_plan_artifact": "drafts/preprocessing-conformance-plan-draft.json",
    }


def initialize_experiment_repository(
    brief: dict[str, Any], output: Path, *, actor: str, initialize_git: bool = True
) -> dict[str, Any]:
    """Create an isolated local experiment repository without approving a study."""
    validate_brief(brief)
    root = output.expanduser().resolve()
    if root.exists():
        raise ValidationError(f"experiment repository path already exists: {root}")
    root.parent.mkdir(parents=True, exist_ok=True)
    scaffold = scaffold_design(brief)
    with tempfile.TemporaryDirectory(prefix=f".{root.name}-", dir=root.parent) as temporary:
        staging = Path(temporary) / root.name
        staging.mkdir()
        (staging / ".gitignore").write_text(
            ".research/artifacts/\nraw/\n*.key\n.env\n__pycache__/\n",
            encoding="utf-8",
        )
        (staging / "README.md").write_text(
            "# " + brief["title"] + "\n\n"
            "This is an isolated Research Machine experiment repository. Its draft "
            "artifacts are review material, not evidence or approval. Do not collect "
            "protected data until the canonical protocol is reviewed and frozen.\n",
            encoding="utf-8",
        )
        _write_json(staging / "inputs" / "design-brief.json", brief)
        for name, content in scaffold["artifacts"].items():
            path = staging / "drafts" / name
            path.parent.mkdir(parents=True, exist_ok=True)
            if isinstance(content, str):
                path.write_text(content, encoding="utf-8")
            else:
                _write_json(path, content)

        service = ResearchService(FileSystemRepository(staging / ".research"), actor=actor)
        service.init_workspace()
        inquiry_commitments = inquiry_decision_commitments(brief)
        inquiry = service.create_inquiry(
            CreateInquiry(
                title=brief["title"],
                initial_statement=brief["question"],
                decision_to_support=inquiry_commitments["decision_to_support"],
                minimum_evidence=inquiry_commitments["minimum_evidence"],
                decision_change_criteria=inquiry_commitments[
                    "decision_change_criteria"
                ],
                decision_owner=inquiry_commitments["decision_owner"],
            )
        )
        for question in brief.get("ambiguity_questions", []):
            service.add_question(
                AddQuestion("[Guided ambiguity] " + question),
                inquiry.inquiry_id,
            )
        for claim in brief.get("claim_boundaries", []):
            service.add_claim(
                AddClaim(
                    statement=claim["statement"],
                    level=ClaimLevel(claim["level"]),
                    scope=claim["scope"],
                ),
                inquiry.inquiry_id,
            )
        for finding in scaffold["findings"]:
            service.add_question(
                AddQuestion(
                    "[Design audit: "
                    + finding["severity"].upper()
                    + "] "
                    + finding["message"]
                    + " Next: "
                    + finding["remediation"]
                ),
                inquiry.inquiry_id,
            )
        proposal = scaffold["artifacts"]["hypothesis-proposal.json"]
        hypothesis = service.propose_hypothesis(
            ProposeHypothesis(
                statement=proposal["statement"],
                generated_by="guided_experiment_scaffold",
                scope=proposal["scope"],
                observable_prediction=proposal["observable_prediction"],
                null_model=proposal["null_model"],
                competing_models=proposal["competing_models"],
                primary_estimand=proposal["primary_estimand"],
                contrast_definition=proposal["contrast_definition"],
                contrast_groups=proposal["contrast_groups"],
                expected_effect_direction=proposal["expected_effect_direction"],
                falsification_conditions=proposal["falsification_conditions"],
            ),
            inquiry.inquiry_id,
        )
        _write_json(
            staging / "experiment-machine.json",
            {
                "status": scaffold["status"],
                "inquiry_id": inquiry.inquiry_id,
                "hypothesis_id": hypothesis.hypothesis_id,
                "hypothesis_state": hypothesis.workflow_state.value,
                "scaffold_provenance": scaffold["provenance"],
                "scaffold_provenance_artifact": "drafts/design-scaffold-provenance.json",
                "git_initialized": initialize_git,
                "notice": "The hypothesis remains unreviewed. No protocol is frozen and no data are registered.",
            },
        )
        initialized_scaffold = _verify_initialized_scaffold(staging, scaffold, brief)
        state = _read_json(staging / "experiment-machine.json")
        state.update(initialized_scaffold)
        _write_json(staging / "experiment-machine.json", state)
        if initialize_git:
            try:
                completed = subprocess.run(
                    ["git", "init", "--quiet", "--initial-branch=main", str(staging)],
                    check=False,
                    capture_output=True,
                    text=True,
                )
            except OSError as exc:
                raise ValidationError(
                    "could not initialize local experiment Git repository: "
                    + str(exc)
                ) from exc
            if completed.returncode != 0:
                raise ValidationError(
                    "could not initialize local experiment Git repository: "
                    + completed.stderr.strip()
                )
        try:
            os.replace(staging, root)
        except OSError as exc:
            raise ValidationError(f"could not create experiment repository atomically: {exc}") from exc
    return {
        "path": str(root),
        "status": scaffold["status"],
        "inquiry_id": inquiry.inquiry_id,
        "hypothesis_id": hypothesis.hypothesis_id,
        "hypothesis_state": hypothesis.workflow_state.value,
        "scaffold_provenance": scaffold["provenance"],
        **initialized_scaffold,
        "git_initialized": initialize_git,
        "notice": "Created locally without a network service or LLM. Review drafts before activation, protocol freeze, or collection.",
    }
