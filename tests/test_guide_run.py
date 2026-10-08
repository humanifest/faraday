"""W02 exact-byte exploratory execution through existing add-on receipts."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from research_machine.addons.receipt import verify_execution_output
from research_machine.interfaces.cli import main
from test_guide_prepare import _inputs


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _prepare(tmp_path: Path, capsys) -> tuple[Path, Path, Path, Path]:
    brief, design, spec, data_spec, data = _inputs(tmp_path)
    workspace = tmp_path / "workspace"
    assert main([
        "--workspace", str(workspace), "--json", "guide", "prepare",
        "--brief-file", str(brief), "--design-brief-file", str(design),
        "--analysis-spec-file", str(spec), "--data-spec-file", str(data_spec),
        "--data-file", str(data), "--expect-data-sha256", _sha(data),
    ]) == 0
    packet_file = tmp_path / "packet.json"
    packet_file.write_text(capsys.readouterr().out, encoding="utf-8")
    assert json.loads(packet_file.read_text())["result"]["status"] == "ready_for_review"
    assert not workspace.exists()
    return packet_file, spec, data, workspace


def _run(capsys, workspace: Path, packet: Path, spec: Path, data: Path,
         output: Path, *, packet_hash: str | None = None,
         spec_hash: str | None = None, input_hash: str | None = None) -> tuple[int, dict]:
    code = main([
        "--workspace", str(workspace), "--json", "guide", "run",
        "--packet-file", str(packet), "--expect-packet-sha256", packet_hash or _sha(packet),
        "--spec-file", str(spec), "--expect-spec-sha256", spec_hash or _sha(spec),
        "--data-file", str(data), "--expect-input-sha256", input_hash or _sha(data),
        "--output", str(output),
    ])
    captured = capsys.readouterr()
    return code, json.loads(captured.out if code == 0 else captured.err)


def test_exact_packet_executes_only_exploratory_analysis(tmp_path: Path, capsys) -> None:
    packet, spec, data, workspace = _prepare(tmp_path, capsys)
    output = tmp_path / "analysis"
    code, response = _run(capsys, workspace, packet, spec, data, output)
    assert code == 0 and response["ok"] is True
    result = response["result"]
    assert result["guide_run_version"] == 1
    assert result["status"] == "exploratory_computation_only"
    assert result["packet_sha256"] == _sha(packet)
    assert result["execution"]["result"]["method"] == "independent_mean_difference_ci"
    assert result["execution"]["result"]["result"]["mean_difference_first_minus_second"] == 3.0
    assert result["scientific_evidence_eligible"] is False
    assert result["canonical_write_performed"] is False
    assert result["confirmatory_plan_verified"] is False
    verified = verify_execution_output(output, _sha(output / "execution-receipt.json"))
    assert verified["scientific_evidence_eligible"] is False
    assert verified["result"] == result["execution"]["result"]
    assert not workspace.exists()


def test_tampered_packet_changed_bytes_and_post_result_method_fail_before_output(
    tmp_path: Path, capsys
) -> None:
    packet, spec, data, workspace = _prepare(tmp_path, capsys)
    trusted_packet, trusted_spec, trusted_data = _sha(packet), _sha(spec), _sha(data)
    original_packet = packet.read_bytes()

    code, response = _run(capsys, workspace, packet, spec, data, tmp_path / "wrong-packet",
                          packet_hash="0" * 64)
    assert code == 2 and "packet" in response["error"]["message"]
    assert not (tmp_path / "wrong-packet").exists()

    forged = json.loads(packet.read_text())
    forged["result"]["authority"] = "approved"
    packet.write_text(json.dumps(forged), encoding="utf-8")
    code, response = _run(capsys, workspace, packet, spec, data, tmp_path / "forged")
    assert code == 2 and "claims authority" in response["error"]["message"]
    assert not (tmp_path / "forged").exists()
    packet.write_bytes(original_packet)
    assert _sha(packet) == trusted_packet

    changed = tmp_path / "changed.csv"
    changed.write_bytes(data.read_bytes() + b"\n")
    code, response = _run(capsys, workspace, packet, spec, changed, tmp_path / "changed-run",
                          input_hash=trusted_data)
    assert code == 2 and "input bytes do not match" in response["error"]["message"]
    assert not (tmp_path / "changed-run").exists()

    switched = json.loads(spec.read_text())
    switched["method"] = "permutation_mean_difference"
    switched["permutations"] = 1000
    spec.write_text(json.dumps(switched), encoding="utf-8")
    code, response = _run(capsys, workspace, packet, spec, data, tmp_path / "switched",
                          spec_hash=trusted_spec)
    assert code == 2 and "trusted SHA-256" in response["error"]["message"]
    assert not (tmp_path / "switched").exists()
    assert not workspace.exists()
