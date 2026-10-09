"""W03 bounded interpretation and unresolved next-experiment guidance."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from research_machine.interfaces.cli import main
from research_machine.adapters.filesystem import FileSystemRepository
from research_machine.application.commands import AddQuestion, CreateInquiry
from research_machine.application.service import ResearchService
from research_machine.collaboration.proposal import (
    create_context_snapshot, validate_collaborator_proposal,
)
from test_guide_prepare import _inputs
from test_guide_models import _proposal


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _journey(tmp_path: Path, capsys, csv_text: str) -> tuple[Path, Path, Path, Path]:
    brief, design, spec, data_spec, _ = _inputs(tmp_path)
    data = tmp_path / "synthetic.csv"
    data.write_text(csv_text, encoding="utf-8")
    workspace = tmp_path / "workspace"
    assert main([
        "--workspace", str(workspace), "--json", "guide", "prepare",
        "--brief-file", str(brief), "--design-brief-file", str(design),
        "--analysis-spec-file", str(spec), "--data-spec-file", str(data_spec),
        "--data-file", str(data), "--expect-data-sha256", _sha(data),
    ]) == 0
    packet = tmp_path / "packet.json"
    packet.write_text(capsys.readouterr().out, encoding="utf-8")
    assert json.loads(packet.read_text())["result"]["status"] == "ready_for_review"
    output = tmp_path / "analysis"
    assert main([
        "--workspace", str(workspace), "--json", "guide", "run",
        "--packet-file", str(packet), "--expect-packet-sha256", _sha(packet),
        "--spec-file", str(spec), "--expect-spec-sha256", _sha(spec),
        "--data-file", str(data), "--expect-input-sha256", _sha(data),
        "--output", str(output),
    ]) == 0
    capsys.readouterr()
    assert not workspace.exists()
    return packet, spec, data, output


def _explain(tmp_path: Path, capsys, packet: Path, spec: Path, data: Path,
             output: Path, *, receipt_hash: str | None = None) -> tuple[int, dict]:
    code = main([
        "--workspace", str(tmp_path / "workspace"), "--json", "guide", "explain",
        "--packet-file", str(packet), "--expect-packet-sha256", _sha(packet),
        "--spec-file", str(spec), "--data-file", str(data),
        "--execution-directory", str(output),
        "--expected-receipt-sha256", receipt_hash or _sha(output / "execution-receipt.json"),
    ])
    captured = capsys.readouterr()
    return code, json.loads(captured.out if code == 0 else captured.err)


@pytest.mark.parametrize("treatment,control,expected_relation", [
    ((5, 6), (2, 3), "above_zero"),
    ((1, 2), (5, 6), "below_zero"),
    ((2, 4), (2, 4), "spans_zero"),
])
def test_explanation_preserves_signed_result_and_no_discrimination_claim(
    tmp_path: Path, capsys, treatment: tuple[int, int],
    control: tuple[int, int], expected_relation: str,
) -> None:
    csv_text = (
        "unit,group,outcome\n"
        f"u01,control,{control[0]}\n"
        f"u02,control,{control[1]}\n"
        f"u03,treatment,{treatment[0]}\n"
        f"u04,treatment,{treatment[1]}\n"
    )
    packet, spec, data, output = _journey(tmp_path, capsys, csv_text)
    code, response = _explain(tmp_path, capsys, packet, spec, data, output)
    assert code == 0 and response["ok"] is True
    explanation = response["result"]
    assert explanation["status"] == "exploratory_computation_only"
    assert explanation["effect_estimate"]["value"] == sum(treatment) / 2 - sum(control) / 2
    assert explanation["uncertainty"]["relation_to_zero"] == expected_relation
    assert explanation["method_claim_ceiling"]
    assert explanation["next_experiment"]["candidate"] is None
    assert explanation["next_experiment"]["discrimination_established"] is False
    assert len(explanation["unresolved_alternatives"]) == 4
    assert explanation["scientific_evidence_eligible"] is False
    assert explanation["canonical_write_performed"] is False
    assert not (tmp_path / "workspace").exists()


def test_changed_input_or_receipt_cannot_be_explained(tmp_path: Path, capsys) -> None:
    packet, spec, data, output = _journey(
        tmp_path, capsys,
        "unit,group,outcome\nu01,control,2\nu02,control,3\nu03,treatment,5\nu04,treatment,6\n",
    )
    code, response = _explain(tmp_path, capsys, packet, spec, data, output,
                              receipt_hash="0" * 64)
    assert code == 2 and "trusted hash" in response["error"]["message"]
    data.write_bytes(data.read_bytes() + b"\n")
    code, response = _explain(tmp_path, capsys, packet, spec, data, output)
    assert code == 2 and "packet" in response["error"]["message"]
    assert not (tmp_path / "workspace").exists()


def _next_fixture(tmp_path: Path, capsys, *, duplicate_prediction: bool = False):
    packet, _, _, output = _journey(
        tmp_path, capsys,
        "unit,group,outcome\nu01,control,2\nu02,control,3\nu03,treatment,5\nu04,treatment,6\n",
    )
    statement = json.loads(packet.read_text())["result"]["original_statement"]
    workspace = tmp_path / "workspace"
    service = ResearchService(FileSystemRepository(workspace), actor="guide-fixture")
    service.init_workspace()
    service.create_inquiry(CreateInquiry("Synthetic next test", statement, inquiry_id="guide-next-v1"))
    purpose = "Design a synthetic next experiment"
    snapshot = create_context_snapshot(service.collaborator_context(purpose=purpose), tmp_path / "context")
    inquiry_ref = "inquiry:guide-next-v1"
    proposal = _proposal(snapshot["context_sha256"], purpose, inquiry_ref)
    if duplicate_prediction:
        proposal["suggestions"][1]["next_test"] = proposal["suggestions"][0]["next_test"]
    proposal["suggestions"].append({
        "suggestion_id": "future-check", "kind": "next_action",
        "statement": "Propose a future independent comparison.",
        "rationale": "Competing models require a prospective discrimination attempt.",
        "uncertainty": "No discriminating power has been established.",
        "evidence_refs": [inquiry_ref],
        "falsification_conditions": ["The proposed check cannot separate the models."],
        "next_test": "Plan a held-out comparison with a blinded reference measure and balance check.",
        "authority": "review_only",
    })
    proposal_file = tmp_path / "proposal.json"
    proposal_file.write_text(json.dumps(proposal))
    validated = validate_collaborator_proposal(
        Path(snapshot["context_file"]), snapshot["context_sha256"],
        proposal_file, tmp_path / "validated",
    )
    candidate = tmp_path / "candidate.json"
    candidate.write_text(json.dumps({
        "candidate_version": 1, "inquiry_ref": inquiry_ref,
        "proposal_id": proposal["proposal_id"],
        "model_roles": {
            "null": "null", "measurement_error": "measurement-error",
            "selection_or_confounding": "selection-confounding",
            "user_explanation": "user-favored",
        },
        "test_suggestion_id": "future-check",
        "discrimination_criterion": "A frozen held-out outcome and reference-measure check would distinguish predictions if their intervals separate under a prespecified rule.",
    }))
    args = [
        "--workspace", str(workspace), "--json", "guide", "next",
        "--inquiry", "guide-next-v1", "--purpose", purpose,
        "--packet-file", str(packet), "--expect-packet-sha256", _sha(packet),
        "--execution-directory", str(output),
        "--expected-receipt-sha256", _sha(output / "execution-receipt.json"),
        "--context-file", snapshot["context_file"],
        "--expected-context-sha256", snapshot["context_sha256"],
        "--proposal-record-file", validated["record_file"],
        "--expected-proposal-record-sha256", validated["record_sha256"],
        "--candidate-file", str(candidate),
    ]
    return service, args, candidate


def test_next_candidate_is_current_inquiry_and_receipt_bound(tmp_path: Path, capsys) -> None:
    service, args, candidate = _next_fixture(tmp_path, capsys)
    before = service.show_inquiry()
    assert main(args) == 0
    result = json.loads(capsys.readouterr().out)["result"]
    assert result["status"] == "review_only_candidate"
    assert {item["role"] for item in result["candidate"]["model_predictions"]} == {
        "null", "measurement_error", "selection_or_confounding", "user_explanation",
    }
    assert result["candidate"]["proposed_discrimination_criterion"]
    assert result["discrimination_established"] is False
    assert result["experiment_authorized"] is False
    assert result["canonical_write_performed"] is False
    assert service.show_inquiry() == before

    forged = json.loads(candidate.read_text())
    forged["inquiry_ref"] = "inquiry:other"
    candidate.write_text(json.dumps(forged))
    assert main(args) == 2
    assert "current inquiry" in capsys.readouterr().err
    candidate.write_text(json.dumps({**forged, "inquiry_ref": "inquiry:guide-next-v1"}))

    changed_hash = list(args)
    position = changed_hash.index("--expected-receipt-sha256") + 1
    changed_hash[position] = "0" * 64
    assert main(changed_hash) == 2
    assert "trusted hash" in capsys.readouterr().err

    service.add_question(AddQuestion("Would a second measure change the result?"))
    assert main(args) == 2
    assert "stale" in capsys.readouterr().err


def test_next_candidate_is_inconclusive_for_identical_predictions(tmp_path: Path, capsys) -> None:
    _, args, _ = _next_fixture(tmp_path, capsys, duplicate_prediction=True)
    assert main(args) == 0
    result = json.loads(capsys.readouterr().out)["result"]
    assert result["status"] == "inconclusive_predictions"
    assert result["candidate"] is None
    assert result["discrimination_established"] is False
