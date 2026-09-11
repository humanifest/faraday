import hashlib
import json
import os
from pathlib import Path

import pytest

from research_machine.executors.runtime_preflight import (
    KernelProbeObservation,
    main,
    preflight_notebook_runtime,
    verify_runtime_preflight_report,
)


def _successful_observation(working_directory: Path) -> KernelProbeObservation:
    return KernelProbeObservation(
        dependency_versions={
            "jupyter-client": "8.6.3",
            "nbclient": "0.10.2",
            "nbformat": "5.10.4",
        },
        kernel_spec_found=True,
        kernel_started=True,
        kernel_ready=True,
        smoke_cell_executed=True,
        marker_observed="RESEARCH_MACHINE_RUNTIME_PREFLIGHT_V1",
        observed_working_directory=str(working_directory),
        kernel_shutdown=True,
        findings=[],
    )


def test_success_persists_bounded_no_analysis_report(tmp_path: Path) -> None:
    result = tmp_path / "runtime-preflight.json"
    times = iter(["2026-09-03T07:00:00Z", "2026-09-03T07:00:01Z"])

    report = preflight_notebook_runtime(
        result,
        working_directory=tmp_path,
        timeout_seconds=17,
        probe=lambda **_: _successful_observation(tmp_path),
        clock=lambda: next(times),
    )

    assert report.status == "passed"
    assert report.kernel_started
    assert report.kernel_ready
    assert report.smoke_cell_executed
    assert report.marker_verified
    assert report.working_directory_verified
    assert report.kernel_shutdown
    assert report.analysis_source_loaded is False
    assert report.analysis_code_executed is False
    assert report.network_access_requested is False
    assert report.smoke_code_sha256 == (
        "1f0900de193cc176b34d27d8121b985b08fb39a44c4cb8193cf779282682ae92"
    )
    assert json.loads(result.read_text()) == json.loads(
        json.dumps(report, default=lambda value: value.__dict__)
    )


def test_passed_receipt_verification_binds_exact_bytes(tmp_path: Path) -> None:
    result = tmp_path / "runtime-preflight.json"
    preflight_notebook_runtime(
        result,
        working_directory=tmp_path,
        probe=lambda **_: _successful_observation(tmp_path),
    )
    expected_sha256 = hashlib.sha256(result.read_bytes()).hexdigest()

    verification = verify_runtime_preflight_report(
        result,
        expected_sha256=expected_sha256,
    )

    assert verification.status == "passed"
    assert verification.receipt_sha256 == expected_sha256
    assert verification.receipt_size_bytes == result.stat().st_size
    assert verification.analysis_source_loaded is False
    assert verification.analysis_code_executed is False

    with pytest.raises(ValueError, match="hash mismatch"):
        verify_runtime_preflight_report(result, expected_sha256="0" * 64)


def test_failed_receipt_cannot_satisfy_readiness_binding(tmp_path: Path) -> None:
    result = tmp_path / "failed-runtime-preflight.json"
    observation = _successful_observation(tmp_path)
    observation = KernelProbeObservation(
        **{
            **observation.__dict__,
            "kernel_started": False,
            "kernel_ready": False,
            "kernel_shutdown": False,
            "findings": [
                {"code": "KERNEL_START_FAILED", "message": "planted"}
            ],
        }
    )
    preflight_notebook_runtime(
        result,
        working_directory=tmp_path,
        probe=lambda **_: observation,
    )

    with pytest.raises(ValueError, match="did not pass"):
        verify_runtime_preflight_report(result)


@pytest.mark.parametrize(
    ("finding_code", "kernel_started", "kernel_ready"),
    [
        ("RUNTIME_DEPENDENCY_UNAVAILABLE", False, False),
        ("KERNEL_SPEC_UNAVAILABLE", False, False),
        ("KERNEL_START_FAILED", False, False),
        ("KERNEL_NOT_READY", True, False),
        ("SMOKE_CELL_FAILED", True, True),
        ("SMOKE_OUTPUT_INVALID", True, True),
        ("WORKING_DIRECTORY_MISMATCH", True, True),
        ("KERNEL_SHUTDOWN_FAILED", True, True),
    ],
)
def test_operational_failures_fail_closed_with_stable_diagnostic(
    tmp_path: Path,
    finding_code: str,
    kernel_started: bool,
    kernel_ready: bool,
) -> None:
    observation = _successful_observation(tmp_path)
    observation = KernelProbeObservation(
        **{
            **observation.__dict__,
            "kernel_started": kernel_started,
            "kernel_ready": kernel_ready,
            "kernel_shutdown": kernel_started,
            "findings": [{"code": finding_code, "message": "planted"}],
        }
    )

    report = preflight_notebook_runtime(
        tmp_path / f"{finding_code}.json",
        working_directory=tmp_path,
        probe=lambda **_: observation,
    )

    assert report.status == "failed"
    assert [item["code"] for item in report.findings] == [finding_code]
    assert report.analysis_source_loaded is False
    assert report.analysis_code_executed is False


def test_working_directory_alias_is_normalized(tmp_path: Path) -> None:
    result = tmp_path / "normalized.json"
    alias = tmp_path / "subdir" / ".."
    (tmp_path / "subdir").mkdir()

    report = preflight_notebook_runtime(
        result,
        working_directory=alias,
        probe=lambda **_: _successful_observation(tmp_path),
    )

    assert report.status == "passed"
    assert report.working_directory == str(tmp_path.resolve())


def test_invalid_input_is_rejected_before_probe(tmp_path: Path) -> None:
    calls = []

    with pytest.raises(ValueError, match="timeout_seconds"):
        preflight_notebook_runtime(
            tmp_path / "invalid.json",
            working_directory=tmp_path,
            timeout_seconds=0,
            probe=lambda **kwargs: calls.append(kwargs),
        )

    assert calls == []


def test_existing_report_is_never_overwritten_or_reprobed(tmp_path: Path) -> None:
    result = tmp_path / "immutable.json"
    result.write_text("immutable")
    calls = []

    with pytest.raises(FileExistsError, match="refusing to overwrite"):
        preflight_notebook_runtime(
            result,
            working_directory=tmp_path,
            probe=lambda **kwargs: calls.append(kwargs),
        )

    assert calls == []
    assert result.read_text() == "immutable"


def test_cli_persists_input_error_without_kernel(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    result = tmp_path / "invalid-input.json"

    exit_code = main(
        [
            "--result-json",
            str(result),
            "--working-directory",
            str(tmp_path),
            "--timeout",
            "0",
        ]
    )

    assert exit_code == 2
    payload = json.loads(result.read_text())
    assert payload["code"] == "RUNTIME_PREFLIGHT_INPUT_INVALID"
    assert payload["kernel_started"] is False
    assert payload["analysis_source_loaded"] is False
    assert json.loads(capsys.readouterr().out) == payload


def test_cli_refuses_to_overwrite_existing_report(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    result = tmp_path / "existing.json"
    result.write_text("immutable")

    exit_code = main(
        [
            "--result-json",
            str(result),
            "--working-directory",
            str(tmp_path),
        ]
    )

    assert exit_code == 2
    assert result.read_text() == "immutable"
    payload = json.loads(capsys.readouterr().out)
    assert payload["code"] == "REPORT_ALREADY_EXISTS"
    assert payload["kernel_started"] is False


def test_live_kernel_probe_when_explicitly_enabled(tmp_path: Path) -> None:
    if os.environ.get("RESEARCH_MACHINE_NOTEBOOK_INTEGRATION") != "1":
        pytest.skip("set RESEARCH_MACHINE_NOTEBOOK_INTEGRATION=1 for kernel test")

    report = preflight_notebook_runtime(
        tmp_path / "live-runtime-preflight.json",
        working_directory=tmp_path,
        timeout_seconds=30,
    )

    assert report.status == "passed"
    assert report.kernel_started
    assert report.marker_verified
    assert report.analysis_code_executed is False
