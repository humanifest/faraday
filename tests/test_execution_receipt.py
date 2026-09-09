"""Synthetic fixtures for integrity, not scientific validation."""
import hashlib
import json

import pytest

from research_machine.addons.execution import execute_analysis
from research_machine.addons.receipt import verify_execution_output
from research_machine.addons.registry import default_registry
from research_machine.domain.errors import ValidationError


@pytest.mark.parametrize("mutation", [None, "receipt", "result", "locator", "symlink"])
def test_pinned_execution_output(tmp_path, mutation):
    data = tmp_path / "synthetic.csv"
    data.write_text("x\n1\n2\n")
    spec = tmp_path / "spec.json"
    spec.write_text(json.dumps({"method": "descriptive_summary", "columns": ["x"], "claim_ceiling": "Fixture"}))
    directory = tmp_path / "output"
    execute_analysis(registry=default_registry(), spec_path=spec, data_path=data, output_dir=directory)
    receipt_path = directory / "execution-receipt.json"
    digest = hashlib.sha256(receipt_path.read_bytes()).hexdigest()
    if mutation == "receipt":
        receipt_path.write_bytes(receipt_path.read_bytes() + b" ")
    elif mutation == "result":
        (directory / "analysis-result.json").write_text("{}")
    elif mutation == "locator":
        receipt = json.loads(receipt_path.read_text())
        receipt["output"]["locator"] = "../spec.json"
        receipt_path.write_text(json.dumps(receipt))
        digest = hashlib.sha256(receipt_path.read_bytes()).hexdigest()
    elif mutation == "symlink":
        output = directory / "analysis-result.json"
        output.unlink()
        output.symlink_to(spec)
    if mutation:
        with pytest.raises(ValidationError):
            verify_execution_output(directory, digest)
    else:
        verified = verify_execution_output(directory, digest)
        assert verified["scope"] == "pinned_receipt_and_output_integrity"
        assert verified["scientific_evidence_eligible"] is False
        assert verified["result"]["missing_data_policy"] is None
        assert "Declared specification" in verified["result"]["missing_data_policy_scope"]


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        ("extra_authority", "contract fields"),
        ("unsupported_inference", "maximum_inference_level"),
        ("claim_ceiling_status", "claim_ceiling_status"),
        ("missing_scope", "missing_data_policy_scope"),
    ],
)
def test_pinned_execution_output_replays_result_authority_contract(
    tmp_path, mutation, message
):
    data = tmp_path / "synthetic.csv"
    data.write_text("x\n1\n2\n")
    spec = tmp_path / "spec.json"
    spec.write_text(
        json.dumps(
            {
                "method": "descriptive_summary",
                "columns": ["x"],
                "claim_ceiling": "Fixture",
            }
        )
    )
    directory = tmp_path / "output"
    execute_analysis(
        registry=default_registry(),
        spec_path=spec,
        data_path=data,
        output_dir=directory,
    )
    receipt_path = directory / "execution-receipt.json"
    result_path = directory / "analysis-result.json"
    receipt = json.loads(receipt_path.read_text())
    result = json.loads(result_path.read_text())
    if mutation == "extra_authority":
        result["scientific_evidence_eligible"] = True
    elif mutation == "unsupported_inference":
        result["maximum_inference_level"] = "causal_proof"
        receipt["maximum_inference_level"] = "causal_proof"
    elif mutation == "claim_ceiling_status":
        result["claim_ceiling_status"] = "researcher_declaration_controls"
    elif mutation == "missing_scope":
        result["missing_data_policy_scope"] = "Verified complete-case handling."
    result_path.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    result_bytes = result_path.read_bytes()
    receipt["output"]["sha256"] = hashlib.sha256(result_bytes).hexdigest()
    receipt["output"]["size_bytes"] = len(result_bytes)
    receipt_path.write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n")
    digest = hashlib.sha256(receipt_path.read_bytes()).hexdigest()

    with pytest.raises(ValidationError, match=message):
        verify_execution_output(directory, digest)
