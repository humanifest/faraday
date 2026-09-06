"""Read-only integrity boundary for local execution handoffs."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from research_machine.addons.execution import (
    _hash_bytes,
    _json_bytes,
    _reject_duplicate_keys,
    _reject_nonfinite,
    _resolve_json_pointer,
    validate_registered_information,
)
from research_machine.domain.errors import ValidationError
from research_machine.application.service import ResearchService


def execution_run_draft(service: ResearchService, directory: Path, expected_receipt_sha256: str,
                        inquiry_id: str | None = None) -> dict[str, Any]:
    verified = verify_execution_output(directory, expected_receipt_sha256)
    receipt = verified["receipt"]
    binding = receipt.get("protocol_design_check")
    if not isinstance(binding, dict) or binding.get("status") != "passed":
        raise ValidationError("run draft requires a protocol-bound execution receipt")
    try:
        specification = (
            binding["executed_analysis_specification"]
            if "analysis_step_contract" in binding
            else binding["executed_analysis_semantics"]
        )
        check = service.validate_analysis_execution(
            binding["protocol_id"], specification,
            binding.get("unit_structure", {}),
            receipt["implementation"]["sha256"], receipt["specification"]["sha256"],
            binding["dataset_id"], receipt["input"]["sha256"], receipt["input"]["size_bytes"],
            receipt["maximum_inference_level"], inquiry_id,
        )
        if check != binding:
            raise ValidationError("execution binding disagrees with canonical records")
        draft = service.run_record_template(binding["protocol_id"], inquiry_id)
        record = draft["record"]
        record.update(started_at=receipt["started_at"], completed_at=receipt["completed_at"],
                      analysis_code_hash=receipt["implementation"]["sha256"],
                      dataset_ids=[binding["dataset_id"]], synthetic=check["synthetic"],
                      output_artifacts=[{**receipt["output"], "media_type": "application/json"}],
                      metadata={"execution_handoff": verified})
    except (KeyError, TypeError, AttributeError) as exc:
        raise ValidationError("execution receipt lacks required handoff fields") from exc
    draft["instructions"].append("Output artifact paths are relative to the execution directory. Receipt timestamps are declarations, not authenticated chronology. Supply observed environment provenance and independently evaluate every scientific gate.")
    protocol = service.get_protocol(binding["protocol_id"], inquiry_id)
    if "analysis_step_contract" in binding or protocol.multiplicity_method == "holm":
        draft["instructions"].append(
            "This is a workflow-component run. It remains ineligible for standalone scientific evidence even if all quality gates pass; synthesize it only through the frozen workflow."
        )
        draft["workflow_component_only"] = True
    return draft


def verify_execution_output(directory: Path, expected_receipt_sha256: str) -> dict[str, Any]:
    """Verify pinned receipt/output bytes; do not trust arbitrary receipt locators."""
    if directory.is_symlink() or not directory.is_dir():
        raise ValidationError("execution directory must be a real directory")
    contents = {}
    for name in ("execution-receipt.json", "analysis-result.json"):
        path = directory / name
        if path.is_symlink() or not path.is_file():
            raise ValidationError(f"execution artifact must be a regular non-symlink file: {name}")
        contents[name] = path.read_bytes()
    digest = hashlib.sha256(contents["execution-receipt.json"]).hexdigest()
    if digest != expected_receipt_sha256:
        raise ValidationError("execution receipt does not match the trusted hash")
    try:
        receipt, result = [json.loads(contents[name], object_pairs_hook=_reject_duplicate_keys,
                                      parse_constant=_reject_nonfinite)
                           for name in ("execution-receipt.json", "analysis-result.json")]
    except (ValueError, UnicodeDecodeError) as exc:
        raise ValidationError(f"invalid execution JSON: {exc}") from exc
    if not isinstance(receipt, dict) or not isinstance(result, dict):
        raise ValidationError("execution receipt and result must be objects")
    if type(receipt.get("receipt_version")) is not int or receipt["receipt_version"] != 1:
        raise ValidationError("unsupported execution receipt version")
    if receipt.get("status") != "completed" or receipt.get("scientific_evidence_eligible") is not False:
        raise ValidationError("expected a completed non-evidence execution receipt")
    output = receipt.get("output")
    if not isinstance(output, dict) or output.get("locator") != "analysis-result.json":
        raise ValidationError("execution output locator must be analysis-result.json")
    raw = contents["analysis-result.json"]
    if (output.get("sha256") != hashlib.sha256(raw).hexdigest()
            or type(output.get("size_bytes")) is not int or output["size_bytes"] != len(raw)):
        raise ValidationError("execution result does not match receipt hash and size")
    addon = receipt.get("addon")
    if (not isinstance(addon, dict) or not isinstance(receipt.get("method"), str)
            or receipt["method"] != result.get("method")
            or receipt.get("maximum_inference_level") != result.get("maximum_inference_level")
            or addon.get("addon_id") != result.get("addon_id")
            or addon.get("version") != result.get("addon_version")):
        raise ValidationError("execution receipt/result method identities disagree")
    binding = receipt.get("protocol_design_check")
    if isinstance(binding, dict):
        contract = binding.get("analysis_contract")
        step = binding.get("analysis_step_contract")
        if isinstance(contract, dict):
            selection = receipt.get("registered_result_selection")
            if not isinstance(selection, dict):
                raise ValidationError("protocol-bound receipt lacks registered result selection")
            try:
                expected_selection = {
                    "effect_estimate_path": contract["effect_estimate_path"],
                    "uncertainty_path": contract["uncertainty_path"],
                    "null_value": contract["null_value"],
                    "support_rule": contract["support_rule"],
                    "confidence_interval_validated": True,
                    "registered_confidence_level": contract.get("confidence_level"),
                    "effect_estimate_sha256": _hash_bytes(_json_bytes(_resolve_json_pointer(
                        result, contract["effect_estimate_path"]
                    ))),
                    "uncertainty_sha256": _hash_bytes(_json_bytes(_resolve_json_pointer(
                        result, contract["uncertainty_path"]
                    ))),
                }
            except KeyError as exc:
                raise ValidationError("analysis contract lacks registered result selectors") from exc
            if selection != expected_selection:
                raise ValidationError("execution receipt registered result selection is invalid")
            if receipt.get("registered_information_check") != validate_registered_information(result, contract):
                raise ValidationError("execution receipt registered information check is invalid")
        elif isinstance(step, dict) and step.get("role") == "confirmatory_test":
            p_value_path = step.get("p_value_path")
            p_value = _resolve_json_pointer(result, p_value_path)
            if (
                isinstance(p_value, bool)
                or not isinstance(p_value, (int, float))
                or not 0 <= float(p_value) <= 1
            ):
                raise ValidationError("registered workflow p-value must be numeric and within [0, 1]")
            expected = {
                "step_id": step.get("step_id"), "p_value_path": p_value_path,
                "p_value": float(p_value),
                "p_value_sha256": _hash_bytes(_json_bytes(p_value)),
            }
            if receipt.get("registered_workflow_selection") != expected:
                raise ValidationError("execution receipt workflow p-value selection is invalid")
        elif isinstance(step, dict) and step.get("role") == "multiplicity":
            body = result.get("result")
            if not isinstance(body, dict):
                raise ValidationError("multiplicity result body must be an object")
            if (
                body.get("family_name") != step.get("family_id")
                or body.get("alpha") != step.get("alpha")
                or body.get("family_hypothesis_ids") != [
                    item.get("member_id") for item in step.get("family_members", [])
                ]
            ):
                raise ValidationError("multiplicity result disagrees with its frozen workflow step")
            if receipt.get("registered_workflow_selection") is not None:
                raise ValidationError("multiplicity receipt cannot claim a source p-value selection")
        else:
            raise ValidationError("protocol-bound receipt lacks a supported frozen execution contract")
    return {"scope": "pinned_receipt_and_output_integrity", "receipt_sha256": digest,
            "receipt": receipt, "result": result, "scientific_evidence_eligible": False,
            "notice": "Does not verify source input/code bytes, environment, chronology, scientific gates, or executor authenticity."}
