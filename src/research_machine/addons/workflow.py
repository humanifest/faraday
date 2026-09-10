"""Provider-free materialization of downstream analysis workflow inputs."""
from __future__ import annotations

import csv
import copy
import hashlib
import io
import json
import os
from pathlib import Path
import tempfile
from typing import Any

from research_machine.addons.execution import _reject_duplicate_keys, _reject_nonfinite
from research_machine.addons.receipt import verify_execution_output
from research_machine.application.service import ResearchService, _protocol_commitment
from research_machine.application.policies import adjudicate_conclusion_contract
from research_machine.domain.errors import ValidationError
from research_machine.domain.models import ProtocolStatus, RunStatus, QualityGateStatus


def _pointer_token(value: str) -> str:
    return value.replace("~", "~0").replace("/", "~1")


def _require_canonical_manifest_id(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip() or value != value.strip():
        raise ValidationError(f"workflow {field} must be a canonical non-blank string")
    return value


def _require_sha256(value: Any, field: str) -> str:
    if (
        not isinstance(value, str)
        or len(value) != 64
        or any(character not in "0123456789abcdef" for character in value)
    ):
        raise ValidationError(f"workflow {field} must be a lowercase SHA-256 digest")
    return value


def _selected_json_value_sha256(value: Any) -> str:
    try:
        content = (json.dumps(
            value, sort_keys=True, indent=2, ensure_ascii=False, allow_nan=False
        ) + "\n").encode()
    except (TypeError, ValueError) as exc:
        raise ValidationError("workflow selected JSON value is not finite") from exc
    return hashlib.sha256(content).hexdigest()


def _gate_semantics(gate: Any) -> dict[str, Any]:
    details = gate.details
    return {
        "status": gate.status.value,
        "controls": {
            key: value.get("matches_expected")
            for key, value in details.get("control_results", {}).items()
            if isinstance(value, dict)
        },
        "missingness": {
            key: details.get("missingness_assessment_result", {}).get(key)
            for key in ("assessment_kind", "assessment_status")
        } if isinstance(details.get("missingness_assessment_result"), dict) else None,
        "causal_assumptions": {
            key: {
                field: value.get(field)
                for field in ("assessment_kind", "assessment_status")
            }
            for key, value in details.get("causal_assumption_results", {}).items()
            if isinstance(value, dict)
        },
    }


def composite_quality_gates(adjudication: dict[str, Any], output_sha256: str) -> list[dict[str, Any]]:
    """Create immutable composite gates from embedded canonical gate receipts."""
    inherited = adjudication.get("quality_gate_adjudication")
    if not isinstance(inherited, list):
        raise ValidationError("workflow adjudication lacks inherited quality gates")
    gates: list[dict[str, Any]] = []
    for gate_index, item in enumerate(inherited):
        source_results = item.get("source_gate_results") if isinstance(item, dict) else None
        if not isinstance(source_results, list) or not source_results:
            raise ValidationError("inherited quality gate lacks source gate results")
        source_gate = source_results[0].get("gate")
        if not isinstance(source_gate, dict) or source_gate.get("status") != "passed":
            raise ValidationError("composite quality gates require a passed authoritative source gate")
        details = copy.deepcopy(source_gate.get("details", {}))
        if not isinstance(details, dict):
            raise ValidationError("authoritative source gate details must be an object")
        details["evidence_sha256"] = output_sha256
        details["evidence_location"] = f"/quality_gate_adjudication/{gate_index}"
        details["inherited_source_gate_results"] = copy.deepcopy(source_results)
        base = f"/quality_gate_adjudication/{gate_index}/source_gate_results/0/gate/details"
        controls = details.get("control_results")
        if isinstance(controls, dict):
            source_control_results = source_gate.get("details", {}).get("control_results")
            if not isinstance(source_control_results, dict):
                raise ValidationError("authoritative source gate lacks control results")
            for control_id, result in controls.items():
                if control_id not in source_control_results:
                    raise ValidationError("authoritative source gate lacks inherited control result")
                result["evidence_sha256"] = output_sha256
                result["evidence_location"] = (
                    f"{base}/control_results/{_pointer_token(control_id)}"
                )
                result["selected_value_sha256"] = _selected_json_value_sha256(
                    source_control_results[control_id]
                )
        missingness = details.get("missingness_assessment_result")
        if isinstance(missingness, dict):
            missingness["evidence_sha256"] = output_sha256
            missingness["evidence_location"] = f"{base}/missingness_assessment_result"
        causal = details.get("causal_assumption_results")
        if isinstance(causal, dict):
            for category, result in causal.items():
                result["evidence_sha256"] = output_sha256
                result["evidence_location"] = (
                    f"{base}/causal_assumption_results/{_pointer_token(category)}"
                )
        gates.append({
            "gate_id": source_gate["gate_id"], "status": "passed",
            "summary": "Inherited from byte-verified completed workflow components; inspect embedded source gate receipts.",
            "required": source_gate.get("required", True), "details": details,
        })
    return gates


def _read_pinned_json(path: Path, expected_sha256: str, label: str) -> tuple[dict[str, Any], bytes]:
    if path.is_symlink() or not path.is_file():
        raise ValidationError(f"{label} must be a regular non-symlink file")
    expected_sha256 = _require_sha256(expected_sha256, f"{label} expected_sha256")
    raw = path.read_bytes()
    if hashlib.sha256(raw).hexdigest() != expected_sha256:
        raise ValidationError(f"{label} does not match the trusted hash")
    try:
        value = json.loads(raw, object_pairs_hook=_reject_duplicate_keys, parse_constant=_reject_nonfinite)
    except (ValueError, UnicodeDecodeError) as exc:
        raise ValidationError(f"invalid {label}: {exc}") from exc
    if not isinstance(value, dict):
        raise ValidationError(f"{label} must contain a JSON object")
    return value, raw


def _absolute_from(manifest_path: Path, value: Any, label: str) -> Path:
    if not isinstance(value, str) or not value.strip():
        raise ValidationError(f"{label} must be non-blank")
    path = Path(value)
    return path if path.is_absolute() else manifest_path.parent / path


def _verify_component(
    service: ResearchService, protocol: Any, manifest_path: Path,
    component: Any, expected_role: str, expected_step_id: str,
    inquiry_id: str | None,
) -> tuple[dict[str, Any], Any]:
    required = {"step_id", "run_id", "execution_directory", "receipt_sha256"}
    if not isinstance(component, dict) or set(component) != required:
        raise ValidationError("workflow components require exactly step_id, run_id, execution_directory, and receipt_sha256")
    _require_canonical_manifest_id(component["step_id"], "component step_id")
    _require_sha256(component["receipt_sha256"], "component receipt_sha256")
    if component["step_id"] != expected_step_id:
        raise ValidationError(f"workflow component must identify frozen step {expected_step_id}")
    directory = _absolute_from(manifest_path, component["execution_directory"], "execution_directory")
    verified = verify_execution_output(directory, component["receipt_sha256"])
    receipt = verified["receipt"]
    binding = receipt.get("protocol_design_check")
    step = binding.get("analysis_step_contract") if isinstance(binding, dict) else None
    frozen_steps = [item for item in protocol.analysis_steps if item.step_id == expected_step_id]
    primary_binding_matches = bool(
        expected_role == "primary_estimate"
        and isinstance(binding, dict)
        and not isinstance(step, dict)
        and binding.get("analysis_contract") == (
            protocol.analysis_contract.to_dict() if protocol.analysis_contract else None
        )
        and receipt.get("method") == frozen_steps[0].method
        and receipt.get("specification", {}).get("sha256") == frozen_steps[0].specification_sha256
        and receipt.get("implementation", {}).get("sha256") == frozen_steps[0].implementation_sha256
    ) if len(frozen_steps) == 1 else False
    step_binding_matches = bool(
        isinstance(step, dict) and len(frozen_steps) == 1
        and step == frozen_steps[0].to_dict() and step.get("role") == expected_role
    )
    if (
        len(frozen_steps) != 1 or not (primary_binding_matches or step_binding_matches)
        or not isinstance(binding, dict)
        or binding.get("protocol_id") != protocol.protocol_id
        or binding.get("protocol_hash") != protocol.protocol_hash
    ):
        raise ValidationError(f"workflow component {expected_step_id} does not match its frozen contract")
    run = service.get_run(component["run_id"], inquiry_id)
    handoff = run.metadata.get("execution_handoff")
    if (
        run.protocol_id != protocol.protocol_id or run.protocol_hash != protocol.protocol_hash
        or run.status is not RunStatus.COMPLETED
        or run.metadata.get("workflow_component_only") is not True
        or handoff != verified
    ):
        raise ValidationError(f"workflow component {expected_step_id} lacks its exact completed canonical run")
    failed_gates = [
        gate.gate_id for gate in run.quality_gates
        if gate.required and gate.status is not QualityGateStatus.PASSED
    ]
    if failed_gates:
        raise ValidationError(
            f"workflow component {expected_step_id} has unpassed required quality gates: {failed_gates}"
        )
    return verified, run


def adjudicate_holm_workflow(
    service: ResearchService, protocol_id: str, manifest_path: Path,
    expected_manifest_sha256: str, output_dir: Path,
    inquiry_id: str | None = None,
) -> dict[str, Any]:
    """Verify a complete frozen Holm workflow and emit bounded study decisions.

    This is deliberately a pre-canonical artifact: successful adjudication proves
    a connected local byte/run chain, but cannot itself create scientific evidence.
    """
    manifest, raw_manifest = _read_pinned_json(
        manifest_path, expected_manifest_sha256, "workflow adjudication manifest"
    )
    required = {"primary_estimate", "confirmatory_tests", "materialization", "multiplicity"}
    if set(manifest) != required:
        raise ValidationError("workflow adjudication manifest has an unexpected field set")
    protocol = service.get_protocol(protocol_id, inquiry_id)
    if protocol.status is not ProtocolStatus.FROZEN or not protocol.protocol_hash:
        raise ValidationError("workflow adjudication requires a frozen protocol")
    if _protocol_commitment(protocol) != protocol.protocol_hash:
        raise ValidationError("frozen protocol content no longer matches its hash commitment")
    primary_steps = [step for step in protocol.analysis_steps if step.role == "primary_estimate"]
    family_steps = [step for step in protocol.analysis_steps if step.role == "multiplicity" and step.method == "holm_adjustment"]
    if len(primary_steps) != 1 or len(family_steps) != 1:
        raise ValidationError("workflow adjudication requires one frozen primary estimate and one Holm step")
    primary_verified, primary_run = _verify_component(
        service, protocol, manifest_path, manifest["primary_estimate"],
        "primary_estimate", primary_steps[0].step_id, inquiry_id,
    )
    family_step = family_steps[0]
    tests = manifest["confirmatory_tests"]
    if not isinstance(tests, list):
        raise ValidationError("confirmatory_tests must be an array")
    tests_by_id: dict[str, Any] = {}
    for item in tests:
        if not isinstance(item, dict):
            raise ValidationError("confirmatory_tests require unique step_id values")
        step_id = _require_canonical_manifest_id(item.get("step_id"), "confirmatory test step_id")
        if step_id in tests_by_id:
            raise ValidationError("confirmatory_tests require unique step_id values")
        tests_by_id[step_id] = item
    expected_test_ids = [member.source_step_id for member in family_step.family_members]
    if set(tests_by_id) != set(expected_test_ids):
        raise ValidationError("confirmatory_tests must exactly cover the frozen Holm family")
    verified_tests: dict[str, tuple[dict[str, Any], Any]] = {
        step_id: _verify_component(
            service, protocol, manifest_path, tests_by_id[step_id],
            "confirmatory_test", step_id, inquiry_id,
        ) for step_id in expected_test_ids
    }
    source_runs = [primary_run, *[verified_tests[item][1] for item in expected_test_ids]]
    source_dataset_ids = {tuple(run.dataset_ids) for run in source_runs}
    if len(source_dataset_ids) != 1 or len(next(iter(source_dataset_ids))) != 1:
        raise ValidationError("primary estimate and confirmatory tests must use the same sole registered dataset")
    if any(run.synthetic for run in source_runs):
        raise ValidationError("workflow adjudication cannot promote synthetic source runs")

    materialization_ref = manifest["materialization"]
    if not isinstance(materialization_ref, dict) or set(materialization_ref) != {"directory", "receipt_sha256"}:
        raise ValidationError("materialization requires exactly directory and receipt_sha256")
    materialization_dir = _absolute_from(manifest_path, materialization_ref["directory"], "materialization.directory")
    materialization, materialization_raw = _read_pinned_json(
        materialization_dir / "family-materialization.json",
        materialization_ref["receipt_sha256"], "family materialization receipt",
    )
    family_csv = materialization_dir / "holm-family.csv"
    if family_csv.is_symlink() or not family_csv.is_file():
        raise ValidationError("materialized Holm family must be a regular non-symlink file")
    family_bytes = family_csv.read_bytes()
    materialized_output = materialization.get("output")
    expected_sources = [
        {
            "source_step_id": step_id,
            "receipt_sha256": verified_tests[step_id][0]["receipt_sha256"],
            "result_sha256": verified_tests[step_id][0]["receipt"]["output"]["sha256"],
            "p_value_path": verified_tests[step_id][0]["receipt"]["registered_workflow_selection"]["p_value_path"],
            "p_value_sha256": verified_tests[step_id][0]["receipt"]["registered_workflow_selection"]["p_value_sha256"],
        } for step_id in expected_test_ids
    ]
    if (
        materialization.get("materialization_version") != 1
        or materialization.get("status") != "completed"
        or materialization.get("scientific_evidence_eligible") is not False
        or materialization.get("protocol_id") != protocol.protocol_id
        or materialization.get("protocol_hash") != protocol.protocol_hash
        or materialization.get("family_step_contract") != family_step.to_dict()
        or materialization.get("verified_sources") != expected_sources
        or not isinstance(materialized_output, dict)
        or materialized_output.get("locator") != "holm-family.csv"
        or materialized_output.get("sha256") != hashlib.sha256(family_bytes).hexdigest()
        or materialized_output.get("size_bytes") != len(family_bytes)
        or materialized_output.get("row_count") != len(family_step.family_members)
    ):
        raise ValidationError("family materialization does not match the verified workflow sources")

    multiplicity_verified, multiplicity_run = _verify_component(
        service, protocol, manifest_path, manifest["multiplicity"],
        "multiplicity", family_step.step_id, inquiry_id,
    )
    multiplicity_receipt = multiplicity_verified["receipt"]
    if (
        multiplicity_receipt.get("input", {}).get("sha256") != hashlib.sha256(family_bytes).hexdigest()
        or multiplicity_receipt.get("input", {}).get("size_bytes") != len(family_bytes)
    ):
        raise ValidationError("multiplicity execution did not consume the verified materialized family")
    body = multiplicity_verified["result"].get("result")
    results = body.get("results") if isinstance(body, dict) else None
    if not isinstance(results, list):
        raise ValidationError("multiplicity result lacks structured family decisions")
    results_by_id = {item.get("hypothesis_id"): item for item in results if isinstance(item, dict)}
    if set(results_by_id) != {member.member_id for member in family_step.family_members}:
        raise ValidationError("multiplicity decisions do not exactly cover the frozen family")
    raw_family = [
        (
            index,
            member.member_id,
            float(verified_tests[member.source_step_id][0]["receipt"]["registered_workflow_selection"]["p_value"]),
        )
        for index, member in enumerate(family_step.family_members)
    ]
    running = 0.0
    adjusted_by_index: dict[int, float] = {}
    for rank, (index, _, p_value) in enumerate(
        sorted(raw_family, key=lambda item: (item[2], item[1])), start=1
    ):
        running = max(running, min(1.0, (len(raw_family) - rank + 1) * p_value))
        adjusted_by_index[index] = running
    contract = protocol.analysis_contract
    conclusion_contract = protocol.conclusion_contract
    selection = primary_verified["receipt"].get("registered_result_selection")
    if contract is None or conclusion_contract is None or not isinstance(selection, dict):
        raise ValidationError("primary estimate lacks its frozen registered selection or conclusion contract")
    from research_machine.addons.execution import _resolve_json_pointer
    estimate = _resolve_json_pointer(primary_verified["result"], contract.effect_estimate_path)
    uncertainty = _resolve_json_pointer(primary_verified["result"], contract.uncertainty_path)
    decisions = []
    for index, member in enumerate(family_step.family_members):
        adjusted = results_by_id[member.member_id]
        raw = verified_tests[member.source_step_id][0]["receipt"]["registered_workflow_selection"]["p_value"]
        expected_adjusted = adjusted_by_index[index]
        expected_reject = expected_adjusted <= float(family_step.alpha)
        if adjusted != {
            "hypothesis_id": member.member_id,
            "raw_p_value": raw,
            "holm_adjusted_p_value": expected_adjusted,
            "reject_at_alpha": expected_reject,
        }:
            raise ValidationError("multiplicity decision disagrees with independently recomputed Holm adjustment")
        decisions.append({
            **member.to_dict(), "raw_p_value": raw,
            "holm_adjusted_p_value": adjusted.get("holm_adjusted_p_value"),
            "reject_at_alpha": adjusted.get("reject_at_alpha"),
            "decision": "reject_null_at_registered_alpha" if adjusted.get("reject_at_alpha") is True else "do_not_reject_null_at_registered_alpha",
        })
    hypothesis = service.get_hypothesis(
        conclusion_contract.primary_hypothesis_id, inquiry_id
    )
    primary_family_decisions = [
        item for item in decisions
        if item["hypothesis_id"] == conclusion_contract.primary_hypothesis_id
        and item["measurement_id"] == contract.primary_measurement_id
        and item["outcome"] == protocol.primary_outcome
    ]
    if len(primary_family_decisions) != 1:
        raise ValidationError("frozen workflow lacks one exact primary family decision")
    adjusted_primary_rejects = primary_family_decisions[0]["reject_at_alpha"] is True
    conclusion_adjudication = adjudicate_conclusion_contract(
        conclusion=conclusion_contract, analysis=contract, hypothesis=hypothesis,
        effect=estimate, uncertainty=uncertainty,
        adjusted_primary_rejects=adjusted_primary_rejects,
    )
    quality_gate_adjudication = []
    all_component_runs = [*source_runs, multiplicity_run]
    for gate_id in protocol.quality_requirements:
        source_gate_results = []
        semantics = []
        for run in all_component_runs:
            matching = [gate for gate in run.quality_gates if gate.gate_id == gate_id]
            if len(matching) != 1 or matching[0].status is not QualityGateStatus.PASSED:
                raise ValidationError(
                    f"workflow component {run.run_id} lacks one passed required gate {gate_id}"
                )
            source_gate_results.append({
                "run_id": run.run_id, "gate": matching[0].to_dict(),
            })
            semantics.append(_gate_semantics(matching[0]))
        if any(item != semantics[0] for item in semantics[1:]):
            raise ValidationError(
                f"workflow components disagree on scientific disposition for gate {gate_id}"
            )
        quality_gate_adjudication.append({
            "gate_id": gate_id, "consensus_status": "passed",
            "source_gate_results": source_gate_results,
        })
    adjudication = {
        "adjudication_version": 1, "status": "passed",
        "protocol_id": protocol.protocol_id, "protocol_hash": protocol.protocol_hash,
        "observation_dataset_id": source_runs[0].dataset_ids[0],
        "primary_estimate": {
            "step_id": primary_steps[0].step_id, "run_id": primary_run.run_id,
            "effect_estimate": estimate, "uncertainty": uncertainty,
            "effect_estimate_path": contract.effect_estimate_path,
            "uncertainty_path": contract.uncertainty_path,
            "receipt_sha256": primary_verified["receipt_sha256"],
            "registered_information_check": primary_verified["receipt"].get(
                "registered_information_check"
            ),
            "observed_pooled_standard_deviation": primary_verified[
                "result"
            ].get("result", {}).get(
                "pooled_within_group_standard_deviation"
            ),
        },
        "confirmatory_family": {
            "family_id": family_step.family_id, "alpha": family_step.alpha,
            "decisions": decisions,
        },
        "conclusion": conclusion_adjudication,
        "quality_gate_adjudication": quality_gate_adjudication,
        "provenance": {
            "manifest_sha256": hashlib.sha256(raw_manifest).hexdigest(),
            "materialization_receipt_sha256": hashlib.sha256(materialization_raw).hexdigest(),
            "multiplicity_run_id": multiplicity_run.run_id,
            "multiplicity_receipt_sha256": multiplicity_verified["receipt_sha256"],
            "component_run_ids": [run.run_id for run in source_runs],
        },
        "scientific_evidence_eligible": False,
        "canonical_status": "reviewed_composite_run_required",
        "claim_ceiling": "Study-level estimate and multiplicity-adjusted decisions under the frozen protocol and passed recorded gates; no proof, mechanism, unrestricted causality, or external validity.",
    }
    output_bytes = (json.dumps(adjudication, sort_keys=True, indent=2, ensure_ascii=False, allow_nan=False) + "\n").encode()
    receipt = {
        "adjudication_receipt_version": 1, "status": "completed",
        "manifest": {"locator": str(manifest_path.resolve()), "sha256": hashlib.sha256(raw_manifest).hexdigest(), "size_bytes": len(raw_manifest)},
        "output": {"locator": "workflow-adjudication.json", "sha256": hashlib.sha256(output_bytes).hexdigest(), "size_bytes": len(output_bytes)},
        "scientific_evidence_eligible": False,
        "notice": "Local composite verification only. Record and review a dedicated canonical composite run before creating evidence.",
    }
    receipt_bytes = (json.dumps(receipt, sort_keys=True, indent=2, ensure_ascii=False, allow_nan=False) + "\n").encode()
    if output_dir.exists():
        raise ValidationError("workflow adjudication output directory already exists")
    output_dir.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=f".{output_dir.name}-", dir=output_dir.parent) as temporary:
        staging = Path(temporary)
        (staging / "workflow-adjudication.json").write_bytes(output_bytes)
        (staging / "workflow-adjudication-receipt.json").write_bytes(receipt_bytes)
        os.replace(staging, output_dir)
    return {"output_directory": str(output_dir), "adjudication": adjudication, "receipt": receipt}


def verify_holm_adjudication(
    service: ResearchService, directory: Path, expected_receipt_sha256: str,
    inquiry_id: str | None = None,
) -> dict[str, Any]:
    """Recompute and byte-verify a completed local workflow adjudication."""
    receipt, receipt_raw = _read_pinned_json(
        directory / "workflow-adjudication-receipt.json",
        expected_receipt_sha256, "workflow adjudication receipt",
    )
    if set(receipt) != {
        "adjudication_receipt_version", "status", "manifest", "output",
        "scientific_evidence_eligible", "notice",
    }:
        raise ValidationError("workflow adjudication receipt has an unexpected field set")
    output = receipt.get("output")
    manifest_ref = receipt.get("manifest")
    if (
        receipt.get("adjudication_receipt_version") != 1
        or receipt.get("status") != "completed"
        or receipt.get("scientific_evidence_eligible") is not False
        or not isinstance(output, dict)
        or output.get("locator") != "workflow-adjudication.json"
        or not isinstance(manifest_ref, dict)
    ):
        raise ValidationError("workflow adjudication receipt semantics are invalid")
    adjudication, adjudication_raw = _read_pinned_json(
        directory / "workflow-adjudication.json", output.get("sha256"),
        "workflow adjudication output",
    )
    if output.get("size_bytes") != len(adjudication_raw):
        raise ValidationError("workflow adjudication output size disagrees with its receipt")
    manifest_path = Path(manifest_ref.get("locator", ""))
    if (
        not manifest_path.is_absolute()
        or manifest_ref.get("size_bytes") is None
        or not isinstance(adjudication.get("protocol_id"), str)
    ):
        raise ValidationError("workflow adjudication receipt has an invalid manifest reference")
    manifest_raw = manifest_path.read_bytes() if manifest_path.is_file() and not manifest_path.is_symlink() else None
    if manifest_raw is None or len(manifest_raw) != manifest_ref["size_bytes"]:
        raise ValidationError("workflow adjudication manifest is unavailable or has changed size")
    import tempfile as _tempfile
    with _tempfile.TemporaryDirectory(prefix="faraday-adjudication-verify-") as temporary:
        recomputed_dir = Path(temporary) / "recomputed"
        recomputed = adjudicate_holm_workflow(
            service, adjudication["protocol_id"], manifest_path,
            manifest_ref.get("sha256"), recomputed_dir, inquiry_id,
        )
        recomputed_raw = (recomputed_dir / "workflow-adjudication.json").read_bytes()
    if recomputed_raw != adjudication_raw or recomputed["adjudication"] != adjudication:
        raise ValidationError("workflow adjudication disagrees with recomputed canonical state")
    return {
        "scope": "recomputed_composite_workflow_and_canonical_components",
        "receipt_sha256": hashlib.sha256(receipt_raw).hexdigest(),
        "receipt": receipt, "adjudication": adjudication,
        "scientific_evidence_eligible": False,
        "notice": "Integrity and canonical component verification only; eligibility is determined by reviewed canonical run intake.",
    }


def workflow_adjudication_run_draft(
    service: ResearchService, directory: Path, expected_receipt_sha256: str,
    inquiry_id: str | None = None,
) -> dict[str, Any]:
    """Build a review-only canonical run draft for a verified composite workflow."""
    verified = verify_holm_adjudication(service, directory, expected_receipt_sha256, inquiry_id)
    adjudication = verified["adjudication"]
    protocol = service.get_protocol(adjudication["protocol_id"], inquiry_id)
    draft = service.run_record_template(protocol.protocol_id, inquiry_id)
    component_runs = [
        service.get_run(run_id, inquiry_id)
        for run_id in adjudication["provenance"]["component_run_ids"]
    ]
    started_at = min(run.started_at for run in component_runs)
    multiplicity_run = service.get_run(
        adjudication["provenance"]["multiplicity_run_id"], inquiry_id
    )
    record = draft["record"]
    record.update(
        started_at=started_at,
        completed_at=multiplicity_run.completed_at,
        analysis_code_hash=protocol.analysis_code_hash,
        dataset_ids=[adjudication["observation_dataset_id"]],
        synthetic=False,
        output_artifacts=[{
            **verified["receipt"]["output"], "media_type": "application/json",
        }],
        metadata={
            "workflow_adjudication_handoff": verified,
            "protocol_deviation_disclosure": {
                "status": "no_deviations_declared",
                "deviations": [],
            },
        },
        quality_gates=composite_quality_gates(
            adjudication, verified["receipt"]["output"]["sha256"]
        ),
    )
    draft["instructions"].append(
        "This is a reviewed composite-run draft. Its passed gates are immutable derivations of embedded canonical component gate receipts; review those inherited results and the bounded family decisions before recording. The adjudication and gate derivation are recomputed during canonical intake."
    )
    draft["composite_workflow"] = True
    return draft


def materialize_holm_family(
    service: ResearchService, protocol_id: str, manifest_path: Path,
    expected_manifest_sha256: str, output_dir: Path,
    inquiry_id: str | None = None,
) -> dict[str, Any]:
    """Verify source executions and write an exact Holm-family CSV plus receipt."""
    if manifest_path.is_symlink() or not manifest_path.is_file():
        raise ValidationError("workflow dependency manifest must be a regular non-symlink file")
    expected_manifest_sha256 = _require_sha256(
        expected_manifest_sha256, "dependency manifest expected_manifest_sha256"
    )
    raw_manifest = manifest_path.read_bytes()
    manifest_sha256 = hashlib.sha256(raw_manifest).hexdigest()
    if manifest_sha256 != expected_manifest_sha256:
        raise ValidationError("workflow dependency manifest does not match the trusted hash")
    try:
        manifest = json.loads(
            raw_manifest, object_pairs_hook=_reject_duplicate_keys,
            parse_constant=_reject_nonfinite,
        )
    except (ValueError, UnicodeDecodeError) as exc:
        raise ValidationError(f"invalid workflow dependency manifest: {exc}") from exc
    if not isinstance(manifest, dict) or set(manifest) != {"family_step_id", "sources"}:
        raise ValidationError("workflow dependency manifest requires only family_step_id and sources")
    family_step_id = _require_canonical_manifest_id(manifest["family_step_id"], "family_step_id")
    sources = manifest["sources"]
    if not isinstance(sources, list) or not sources:
        raise ValidationError("workflow dependency sources must be a non-empty array")
    allowed_source_fields = {"source_step_id", "execution_directory", "receipt_sha256"}
    if any(not isinstance(item, dict) or set(item) != allowed_source_fields for item in sources):
        raise ValidationError("each workflow source requires exactly source_step_id, execution_directory, and receipt_sha256")

    protocol = service.get_protocol(protocol_id, inquiry_id)
    if protocol.status is not ProtocolStatus.FROZEN or not protocol.protocol_hash:
        raise ValidationError("workflow materialization requires a frozen protocol")
    if _protocol_commitment(protocol) != protocol.protocol_hash:
        raise ValidationError("frozen protocol content no longer matches its hash commitment")
    family_steps = [
        step for step in protocol.analysis_steps
        if step.step_id == family_step_id and step.role == "multiplicity"
        and step.method == "holm_adjustment"
    ]
    if len(family_steps) != 1:
        raise ValidationError("family_step_id does not name one frozen Holm step")
    family_step = family_steps[0]
    sources_by_id: dict[str, dict[str, Any]] = {}
    for source in sources:
        source_step_id = _require_canonical_manifest_id(source["source_step_id"], "source_step_id")
        if source_step_id in sources_by_id:
            raise ValidationError("workflow source_step_id values must be unique non-blank strings")
        directory_value = source["execution_directory"]
        receipt_sha256 = _require_sha256(source["receipt_sha256"], "receipt_sha256")
        if not isinstance(directory_value, str) or not directory_value.strip():
            raise ValidationError("workflow execution_directory must be non-blank")
        directory = Path(directory_value)
        if not directory.is_absolute():
            directory = manifest_path.parent / directory
        sources_by_id[source_step_id] = verify_execution_output(directory, receipt_sha256)
    expected_sources = {member.source_step_id for member in family_step.family_members}
    if set(sources_by_id) != expected_sources:
        raise ValidationError("workflow sources must exactly cover the frozen Holm dependencies")

    rows: list[dict[str, Any]] = []
    verified_sources: list[dict[str, Any]] = []
    for member in family_step.family_members:
        verified = sources_by_id[member.source_step_id]
        receipt = verified["receipt"]
        binding = receipt.get("protocol_design_check")
        selection = receipt.get("registered_workflow_selection")
        source_steps = [
            step for step in protocol.analysis_steps if step.step_id == member.source_step_id
        ]
        if len(source_steps) != 1:
            raise ValidationError("frozen Holm member references an unavailable source step")
        source_step = source_steps[0]
        if (
            not isinstance(binding, dict)
            or binding.get("protocol_id") != protocol.protocol_id
            or binding.get("protocol_hash") != protocol.protocol_hash
            or binding.get("analysis_step_contract") != source_step.to_dict()
        ):
            raise ValidationError("workflow source receipt does not match its frozen source step")
        if (
            not isinstance(selection, dict)
            or selection.get("step_id") != source_step.step_id
            or isinstance(selection.get("p_value"), bool)
            or not isinstance(selection.get("p_value"), (int, float))
        ):
            raise ValidationError("workflow source receipt lacks its registered p-value selection")
        rows.append({"member_id": member.member_id, "p_value": selection["p_value"]})
        verified_sources.append({
            "source_step_id": source_step.step_id,
            "receipt_sha256": verified["receipt_sha256"],
            "result_sha256": receipt["output"]["sha256"],
            "p_value_path": selection["p_value_path"],
            "p_value_sha256": selection["p_value_sha256"],
        })

    buffer = io.StringIO(newline="")
    writer = csv.DictWriter(buffer, fieldnames=["member_id", "p_value"], lineterminator="\n")
    writer.writeheader()
    writer.writerows(rows)
    csv_bytes = buffer.getvalue().encode("utf-8")
    materialization = {
        "materialization_version": 1,
        "status": "completed",
        "protocol_id": protocol.protocol_id,
        "protocol_hash": protocol.protocol_hash,
        "family_step_contract": family_step.to_dict(),
        "dependency_manifest": {
            "locator": str(manifest_path.resolve()), "sha256": manifest_sha256,
            "size_bytes": len(raw_manifest),
        },
        "verified_sources": verified_sources,
        "output": {
            "locator": "holm-family.csv", "sha256": hashlib.sha256(csv_bytes).hexdigest(),
            "size_bytes": len(csv_bytes), "row_count": len(rows), "media_type": "text/csv",
        },
        "scientific_evidence_eligible": False,
        "notice": "Verifies local source receipt/result bytes and registered p-value selectors; it does not authenticate chronology, executors, scientific gates, or source data truth.",
    }
    receipt_bytes = (json.dumps(
        materialization, sort_keys=True, indent=2, ensure_ascii=False, allow_nan=False,
    ) + "\n").encode()
    if output_dir.exists():
        raise ValidationError("workflow materialization output directory already exists")
    output_dir.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=f".{output_dir.name}-", dir=output_dir.parent) as temporary:
        staging = Path(temporary)
        (staging / "holm-family.csv").write_bytes(csv_bytes)
        (staging / "family-materialization.json").write_bytes(receipt_bytes)
        os.replace(staging, output_dir)
    return {"output_directory": str(output_dir), "materialization": materialization}
