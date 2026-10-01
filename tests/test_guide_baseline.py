from __future__ import annotations

import hashlib
import json
from pathlib import Path

from research_machine.adapters.filesystem import FileSystemRepository
from research_machine.application.commands import AddQuestion, CreateInquiry
from research_machine.application.service import ResearchService
from research_machine.interfaces.cli import main


FIXTURES = Path(__file__).parent / "fixtures" / "guide"


def _cli_json(capsys, args: list[str]) -> dict:
    assert main(args) == 0
    captured = capsys.readouterr()
    assert captured.err == ""
    payload = json.loads(captured.out)
    assert payload["ok"] is True
    return payload["result"]


def test_existing_synthetic_guide_seams_and_adverse_identity(tmp_path: Path, capsys) -> None:
    plan = json.loads((FIXTURES / "inquiry-plan.json").read_text(encoding="utf-8"))
    data = FIXTURES / "independent-two-group.csv"
    original_bytes = data.read_bytes()
    workspace = tmp_path / "workspace"
    service = ResearchService(FileSystemRepository(workspace), actor="guide-fixture")
    service.init_workspace()
    service.create_inquiry(CreateInquiry(
        "Synthetic two-group guide baseline",
        plan["original_question"],
        inquiry_id="guide-independent-v1",
        decision_to_support=plan["decision"],
    ))
    service.add_question(AddQuestion("What evidence would justify a later study?"))

    context = service.collaborator_context(purpose="Characterize existing read-only seam")
    assert context["inquiry"]["initial_statement"] == plan["original_question"]
    assert len(context["open_questions"]) == 1
    assert context["dataset_inventory"]["registered_dataset_count"] == 0
    assert service.verify_ledger()["valid"] is True

    execution = _cli_json(capsys, [
        "--workspace", str(workspace), "--json", "analysis", "run",
        "--spec-file", str(FIXTURES / "independent-analysis.json"),
        "--data-file", str(data), "--output", str(tmp_path / "analysis"),
    ])
    assert execution["result"]["method"] == plan["method_id"]
    assert execution["result"]["result"]["groups"] == ["treatment", "control"]
    assert execution["result"]["result"]["mean_difference_first_minus_second"] == 3.0
    assert execution["result"]["result"]["independent_unit_check"]["status"] == "unique_identifiers"
    assert execution["receipt"]["input"]["sha256"] == hashlib.sha256(original_bytes).hexdigest()
    assert execution["receipt"]["scientific_evidence_eligible"] is False
    assert data.read_bytes() == original_bytes
    assert service.dataset_inventory()["registered_dataset_count"] == 0

    invalid_data = tmp_path / "duplicate-unit.csv"
    invalid_data.write_bytes(original_bytes.replace(b"u04,treatment", b"u01,treatment"))
    failed_output = tmp_path / "invalid-analysis"
    assert main([
        "--workspace", str(workspace), "--json", "analysis", "run",
        "--spec-file", str(FIXTURES / "independent-analysis.json"),
        "--data-file", str(invalid_data), "--output", str(failed_output),
    ]) == 2
    failure = json.loads(capsys.readouterr().err)
    assert failure["ok"] is False
    assert "independent-unit identifier" in failure["error"]["message"]
    assert not failed_output.exists()
