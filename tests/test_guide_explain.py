"""W03 bounded interpretation and unresolved next-experiment guidance."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from research_machine.interfaces.cli import main
from test_guide_prepare import _inputs


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
