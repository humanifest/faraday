"""Build an end-to-end Research Machine workspace for the pendulum benchmark."""

from __future__ import annotations

import argparse
import hashlib
import itertools
import json
import platform
from pathlib import Path
from typing import Any

from campaigns.newtonian_pendulum.executor import execute_suite
from campaigns.newtonian_pendulum.fixtures import generate_fixtures
from research_machine.adapters.filesystem import FileSystemRepository
from research_machine.application.commands import (
    AddClaim,
    AddQuestion,
    CreateInquiry,
    CreateProtocol,
    ProposeHypothesis,
    RecordRun,
    RegisterDataset,
)
from research_machine.application.service import ResearchService
from research_machine.domain.models import (
    AnalysisMode,
    ClaimLevel,
    DatasetArtifact,
    DatasetRole,
    ProtocolKind,
    QualityGateResult,
    QualityGateStatus,
)


CAMPAIGN_ROOT = Path(__file__).resolve().parent
SPEC_PATH = CAMPAIGN_ROOT / "campaign-spec.json"
RUN_TIMESTAMP = "2026-09-03T12:00:00Z"


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _analysis_code_hash() -> str:
    digest = hashlib.sha256()
    for path in (
        CAMPAIGN_ROOT / "analyzer.py",
        CAMPAIGN_ROOT / "independent_checker.py",
        CAMPAIGN_ROOT / "executor.py",
    ):
        digest.update(path.name.encode("utf-8"))
        digest.update(b"\0")
        digest.update(path.read_bytes())
        digest.update(b"\0")
    return digest.hexdigest()


def _environment_hash() -> str:
    value = {
        "campaign_id": "newtonian-pendulum-v1",
        "implementation": "python-standard-library",
        "python": platform.python_version(),
        "python_implementation": platform.python_implementation(),
        "system": platform.system(),
        "machine": platform.machine(),
    }
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()


def _artifact(path: Path, media_type: str, **metadata: object) -> DatasetArtifact:
    return DatasetArtifact(
        locator=str(path.resolve()),
        sha256=_sha256(path),
        size_bytes=path.stat().st_size,
        media_type=media_type,
        metadata=metadata,
    )


def _hypothesis_commands(parent_claim: str) -> list[ProposeHypothesis]:
    common = {
        "parent_claims": [parent_claim],
        "generated_by": "pendulum-calibration-design-v1",
        "source_context": [
            "Synthetic known-result benchmark; not a physical observation."
        ],
        "scope": (
            "Idealized pendula in the sealed synthetic suite, at or below 10 degrees "
            "and within registered clock, length, and damping tolerances."
        ),
        "primary_estimand": (
            "Winning one-parameter length-period law and runner-up/best RMSE ratio."
        ),
        "time_window": "Twenty oscillations per synthetic trial.",
        "covariates": ["starting angle", "clock identity", "acquisition sequence"],
        "known_confounds": [
            "clock drift",
            "length mislabeling",
            "large-angle behavior",
            "damping",
            "sensor dropouts",
            "unregistered outliers",
            "incomplete acquisition",
        ],
        "required_replications": 1,
    }
    return [
        ProposeHypothesis(
            statement="Pendulum period is independent of pendulum length.",
            observable_prediction=(
                "The constant-period model has the lowest frozen-analysis RMSE."
            ),
            null_model=(
                "Either T proportional to L or T proportional to square root of L."
            ),
            competing_models=[
                "T proportional to L",
                "T proportional to square root of L",
            ],
            expected_effect_direction="Log-log slope near 0.",
            falsification_conditions=[
                "Either nonconstant model wins by an RMSE ratio of at least 3."
            ],
            support_conditions=[
                "Both independent analyzers select the constant model on a valid case."
            ],
            boundary_conditions=["All registered measurement-quality gates pass."],
            **common,
        ),
        ProposeHypothesis(
            statement="Pendulum period is directly proportional to pendulum length.",
            observable_prediction=(
                "The linear-through-origin model has the lowest frozen-analysis RMSE."
            ),
            null_model=(
                "Either T is constant or T is proportional to square root of L."
            ),
            competing_models=["T is constant", "T proportional to square root of L"],
            expected_effect_direction="Log-log slope near 1.",
            falsification_conditions=[
                "Either competing model wins by an RMSE ratio of at least 3."
            ],
            support_conditions=[
                "Both independent analyzers select the linear model on a valid case."
            ],
            boundary_conditions=["All registered measurement-quality gates pass."],
            **common,
        ),
        ProposeHypothesis(
            statement="Pendulum period is proportional to the square root of length.",
            observable_prediction=(
                "The square-root-through-origin model has the lowest frozen-analysis "
                "RMSE and the independent log-log exponent is closest to 0.5."
            ),
            null_model="Either T is constant or T is directly proportional to L.",
            competing_models=["T is constant", "T proportional to L"],
            expected_effect_direction="Log-log slope near 0.5.",
            falsification_conditions=[
                "A competing model wins by an RMSE ratio of at least 3.",
                "The two independent analyzers disagree on the winning model.",
                "Any required measurement or boundary gate fails.",
            ],
            support_conditions=[
                "Both independent analyzers select the square-root model on the clean fixture.",
                "Constant and linear negative controls select their own generating laws.",
            ],
            boundary_conditions=[
                "Starting angle is at most 10 degrees.",
                "Absolute clock drift is at most 100 ppm.",
                "Relative reported-length error is at most 0.5 percent.",
                "Amplitude loss is at most 12 percent per trial.",
            ],
            **common,
        ),
    ]


def _suite_quality_gates(report: dict[str, object]) -> list[QualityGateResult]:
    statuses = {value.value: value for value in QualityGateStatus}
    gates = report["quality_gates"]
    if not isinstance(gates, list):
        raise ValueError("executor report quality_gates must be a list")
    return [
        QualityGateResult(
            gate_id=str(gate["gate_id"]),
            status=statuses[str(gate["status"])],
            summary=str(gate["summary"]),
            required=bool(gate["required"]),
            details=dict(gate["details"]),
        )
        for gate in gates
        if isinstance(gate, dict)
    ]


def build_workspace(
    output_root: Path,
    spec_path: Path = SPEC_PATH,
    *,
    human_reviewed: bool = False,
) -> dict[str, Any]:
    if not human_reviewed:
        raise ValueError(
            "confirmatory campaign creation requires explicit human review of the "
            "three hypotheses and frozen comparison"
        )
    if output_root.exists() and any(output_root.iterdir()):
        raise FileExistsError(f"refusing to overwrite non-empty output: {output_root}")
    output_root.mkdir(parents=True, exist_ok=True)
    workspace_root = output_root / ".research"
    fixtures_root = output_root / "fixtures"
    artifacts_root = output_root / "artifacts"
    artifacts_root.mkdir(parents=True, exist_ok=True)

    tokens = (f"pendulum{index:04d}" for index in itertools.count(1))
    service = ResearchService(
        FileSystemRepository(workspace_root),
        actor="human-authorized-pendulum-calibration",
        clock=lambda: RUN_TIMESTAMP,
        token=lambda: next(tokens),
    )
    service.init_workspace()
    inquiry = service.create_inquiry(
        CreateInquiry(
            title="Newtonian pendulum calibration",
            initial_statement=(
                "Can Research Machine recover a known bounded relationship, reject "
                "competing laws, and fail closed on planted defects?"
            ),
            inquiry_id="newtonian-pendulum-calibration",
        )
    )
    first_question = service.add_question(
        AddQuestion(
            "Can two independently implemented analyses recover the known "
            "relationship without hard-coding it?"
        )
    )
    service.answer_question(
        first_question.question_id,
        "Test against constant and linear generated controls as well as the "
        "square-root fixture.",
    )
    second_question = service.add_question(
        AddQuestion(
            "Will measurement defects and boundary violations invalidate "
            "attractive-looking fits?"
        )
    )
    service.answer_question(
        second_question.question_id,
        "Require each planted defect to fail its preregistered gate before model "
        "interpretation.",
    )

    measurement_claim = service.add_claim(
        AddClaim(
            statement=(
                "The benchmark's timing, length, boundary, exclusion, and "
                "completeness checks distinguish usable from invalid synthetic cases."
            ),
            level=ClaimLevel.MEASUREMENT_VALIDITY,
            scope="The sealed newtonian-pendulum-v1 synthetic fixtures only.",
        )
    )
    relationship_claim = service.add_claim(
        AddClaim(
            statement=(
                "Inside the valid small-angle synthetic regime, period is best "
                "described as proportional to the square root of length."
            ),
            level=ClaimLevel.STATISTICAL_ASSOCIATION,
            parent_claims=[measurement_claim.claim_id],
            scope="The sealed newtonian-pendulum-v1 synthetic fixtures only.",
        )
    )
    hypotheses = [
        service.propose_hypothesis(command)
        for command in _hypothesis_commands(relationship_claim.claim_id)
    ]
    for hypothesis in hypotheses:
        service.activate_hypothesis(hypothesis.hypothesis_id)

    spec_hash = _sha256(spec_path)
    spec = json.loads(spec_path.read_text(encoding="utf-8"))
    seed_reveal = str(spec["seed_reveal"])
    seed_commitment = hashlib.sha256(seed_reveal.encode("utf-8")).hexdigest()
    code_hash = _analysis_code_hash()
    required_gates = [
        "fixture-integrity",
        "randomization-check",
        "clean-known-result",
        "alternative-model-controls",
        "registered-exclusion-control",
        "adversarial-fail-closed",
        "analyzer-agreement",
        "known-result-reproduction",
    ]
    draft = service.create_protocol(
        CreateProtocol(
            experiment_id="newtonian-pendulum-v1",
            title="Frozen synthetic pendulum known-result benchmark",
            analysis_mode=AnalysisMode.CONFIRMATORY,
            hypotheses_tested=[item.hypothesis_id for item in hypotheses],
            primary_outcome="Required suite quality-gate vector.",
            protocol_kind=ProtocolKind.COMPUTATIONAL,
            methodology=(
                "Generate deterministic sealed fixtures, run a proportional-template "
                "analyzer and an independently implemented log-log analyzer, then score "
                "the registered valid controls and planted invalid cases."
            ),
            inputs_required=[
                "campaign-spec.json",
                "observations.csv and calibration.csv for each registered case",
            ],
            quality_requirements=required_gates,
            controls=[
                "Constant-law synthetic negative control",
                "Linear-law synthetic negative control",
                "Registered sensor-dropout exclusion control",
                "Six planted fail-closed cases",
            ],
            expected_outputs=[
                "Machine-readable suite report with per-case fits and gate details"
            ],
            success_conditions=[
                "Both analyzers recover square-root, constant, and linear valid fixtures.",
                "Every planted defect fails its preregistered gate.",
                "All required suite gates pass.",
            ],
            environment_requirements=[
                "Python 3.11 or newer using only the standard library"
            ],
            sample_size_or_stopping_rule=(
                "Exactly ten sealed cases; 48 trials per case before registered "
                "exclusions, with six lengths and eight repetitions per length."
            ),
            failure_conditions=[
                "Any required suite gate fails.",
                "Either analyzer selects the wrong registered law on a valid case.",
                "A planted defect remains valid or fails only for an unregistered reason.",
            ],
            safety_constraints=[
                "Synthetic-only execution; no human, animal, or physical intervention."
            ],
            analysis_code_hash=code_hash,
            external_anchor=f"sha256:{spec_hash}",
            random_seed_commitment=seed_commitment,
        )
    )
    protocol = service.freeze_protocol(
        draft.protocol_id, external_anchor=f"sha256:{spec_hash}"
    )

    generate_fixtures(spec_path, fixtures_root)
    fixture_artifacts: list[DatasetArtifact] = []
    for path in sorted(fixtures_root.glob("*/*")):
        if path.name.endswith(".csv"):
            media_type = "text/csv"
        elif path.name.endswith(".json"):
            media_type = "application/json"
        else:
            continue
        fixture_artifacts.append(
            _artifact(path, media_type, artifact_role="synthetic_fixture")
        )
    dataset = service.register_dataset(
        RegisterDataset(
            dataset_id="ds-newtonian-pendulum-synthetic-v1",
            name="Sealed synthetic pendulum calibration suite",
            role=DatasetRole.CALIBRATION,
            artifacts=fixture_artifacts,
            description=(
                "Deterministic known-result fixtures and planted failure cases. "
                "These are software calibration inputs, not physical observations."
            ),
            observation_unit="One timed block of twenty simulated oscillations.",
            synthetic=True,
            quality_attestations=[
                "Generated only after the protocol was hash-frozen.",
                "Every case has a content-hashed manifest.",
            ],
            metadata={
                "campaign_spec_sha256": spec_hash,
                "protocol_id": protocol.protocol_id,
            },
        )
    )

    report_path = artifacts_root / "suite-report.json"
    report = execute_suite(fixtures_root, spec_path, report_path)
    run = service.record_run(
        RecordRun(
            run_id="run-newtonian-pendulum-synthetic-v1",
            protocol_id=protocol.protocol_id,
            started_at="2026-09-03T12:01:00Z",
            completed_at="2026-09-03T12:02:00Z",
            analysis_code_hash=code_hash,
            environment_hash=_environment_hash(),
            random_seed_reveal=seed_reveal,
            dataset_ids=[dataset.dataset_id],
            output_artifacts=[
                _artifact(
                    report_path,
                    "application/json",
                    artifact_role="controlled_benchmark_report",
                )
            ],
            quality_gates=_suite_quality_gates(report),
            summary=(
                "Synthetic calibration recovered all registered laws and rejected all "
                "planted defects. It is intentionally ineligible as scientific evidence."
            ),
            synthetic=True,
            metadata={
                "campaign_id": "newtonian-pendulum-v1",
                "claim_ceiling": "software and workflow calibration only",
            },
        )
    )
    synthesis = service.build_synthesis()
    audit = service.audit_rigor(fail_on="error")
    ledger = service.verify_ledger()
    summary: dict[str, Any] = {
        "inquiry_id": inquiry.inquiry_id,
        "protocol_id": protocol.protocol_id,
        "protocol_hash": protocol.protocol_hash,
        "dataset_id": dataset.dataset_id,
        "run_id": run.run_id,
        "run_status": run.status.value,
        "synthetic": run.synthetic,
        "scientific_evidence_eligible": run.scientific_evidence_eligible,
        "suite_quality_gates": {
            gate.gate_id: gate.status.value for gate in run.quality_gates
        },
        "rigor_audit": audit.to_dict(),
        "ledger_verification": ledger,
        "synthesis_path": synthesis["path"],
        "suite_report_path": str(report_path.resolve()),
    }
    (output_root / "run-summary.json").write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return summary


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--spec", type=Path, default=SPEC_PATH)
    parser.add_argument(
        "--human-reviewed",
        action="store_true",
        help=(
            "Attest that a person reviewed the three candidate laws and authorized "
            "the frozen confirmatory comparison"
        ),
    )
    args = parser.parse_args()
    if not args.human_reviewed:
        parser.error(
            "--human-reviewed is required; generated hypotheses cannot self-activate"
        )
    summary = build_workspace(
        args.output.resolve(),
        args.spec.resolve(),
        human_reviewed=True,
    )
    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
