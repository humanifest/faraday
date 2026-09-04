"""Freeze the physical protocol and create a no-observations-yet collection kit."""

from __future__ import annotations

import argparse
import csv
import hashlib
import itertools
import json
import random
from collections.abc import Callable
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from campaigns.newtonian_pendulum.physical.executor import analysis_code_hash
from research_machine.adapters.filesystem import FileSystemRepository
from research_machine.application.commands import (
    AddClaim,
    AddQuestion,
    CreateInquiry,
    CreateProtocol,
    ProposeHypothesis,
)
from research_machine.application.service import ResearchService
from research_machine.domain.models import (
    AnalysisMode,
    ClaimLevel,
    MeasurementDefinition,
    MeasurementRole,
    ProtocolKind,
)


PHYSICAL_ROOT = Path(__file__).resolve().parent
SPEC_PATH = PHYSICAL_ROOT / "physical-spec.json"
OBSERVATION_FIELDS = [
    "trial_id",
    "block",
    "sequence",
    "length_target_m",
    "length_measured_m",
    "angle_start_deg",
    "oscillation_count",
    "start_time_s",
    "end_time_s",
    "timing_audit",
    "audit_start_time_s",
    "audit_end_time_s",
    "clock_id",
    "amplitude_end_deg",
    "quality_flag",
    "source_id",
    "notes",
]


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _seed(seed_reveal: str) -> int:
    return int.from_bytes(hashlib.sha256(seed_reveal.encode()).digest()[:8], "big")


def _write_csv(path: Path, fields: list[str], rows: list[dict[str, object]]) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def _hypotheses(parent_claim: str) -> list[ProposeHypothesis]:
    common = {
        "parent_claims": [parent_claim],
        "generated_by": "physical-pendulum-design-v1",
        "source_context": [
            "Prospective physical experiment; no observations existed at proposal time."
        ],
        "scope": (
            "One pendulum apparatus, lengths 0.20-1.25 m, starting angle at most 7 "
            "degrees, and the registered timing and damping limits."
        ),
        "primary_estimand": (
            "Winning candidate law by leave-one-target-length-out RMSE."
        ),
        "time_window": "Twenty complete oscillations per scheduled trial.",
        "covariates": [
            "measured length",
            "starting angle",
            "clock identity",
            "randomized block",
        ],
        "known_confounds": [
            "timing scale error",
            "length measurement error",
            "large starting angle",
            "damping",
            "pivot slip",
            "cycle-count error",
            "selective exclusions",
        ],
        "required_replications": 1,
    }
    return [
        ProposeHypothesis(
            statement="Physical pendulum period is independent of length in scope.",
            observable_prediction=(
                "The constant model has the lowest leave-one-length-out RMSE and the "
                "independent log-log slope is closest to zero."
            ),
            null_model="The linear or square-root candidate law fits better.",
            competing_models=["T proportional to L", "T proportional to square root of L"],
            expected_effect_direction="Log-log slope near 0.",
            falsification_conditions=[
                "Another candidate wins with runner-up/best RMSE ratio at least 1.5."
            ],
            support_conditions=[
                "Both analysis implementations select the constant model."
            ],
            boundary_conditions=["All execution-quality gates pass."],
            **common,
        ),
        ProposeHypothesis(
            statement="Physical pendulum period is directly proportional to length in scope.",
            observable_prediction=(
                "The linear model has the lowest leave-one-length-out RMSE and the "
                "independent log-log slope is closest to one."
            ),
            null_model="The constant or square-root candidate law fits better.",
            competing_models=["T is constant", "T proportional to square root of L"],
            expected_effect_direction="Log-log slope near 1.",
            falsification_conditions=[
                "Another candidate wins with runner-up/best RMSE ratio at least 1.5."
            ],
            support_conditions=["Both analysis implementations select the linear model."],
            boundary_conditions=["All execution-quality gates pass."],
            **common,
        ),
        ProposeHypothesis(
            statement=(
                "Physical pendulum period is proportional to the square root of length "
                "in the registered small-angle regime."
            ),
            observable_prediction=(
                "The square-root model wins with RMSE ratio at least 1.5, the independent "
                "log-log exponent is 0.4-0.6, and implied g is 9.5-10.1 m/s^2."
            ),
            null_model="The constant or directly proportional candidate law fits better.",
            competing_models=["T is constant", "T proportional to L"],
            expected_effect_direction="Log-log slope near 0.5.",
            falsification_conditions=[
                "The constant or linear model wins with RMSE ratio at least 1.5.",
                "The independent exponent is closer to 0 or 1 than to 0.5.",
            ],
            support_conditions=[
                "Both implementations select square-root after every quality gate passes.",
                "The exponent and implied-g measurements satisfy their frozen intervals.",
            ],
            boundary_conditions=[
                "Starting angle is at most 7 degrees.",
                "All six lengths retain at least seven included trials.",
                "Clock, length, damping, source, and exclusion gates pass.",
            ],
            **common,
        ),
    ]


def _measurements(primary: str, secondary: list[str], controls: list[str]) -> list[MeasurementDefinition]:
    common_parameters = {
        "lengths": "0.20, 0.35, 0.50, 0.75, 1.00, 1.25 m",
        "blocks": "8 randomized complete blocks",
        "oscillations": "20 per trial",
    }
    return [
        MeasurementDefinition(
            measurement_id="primary-model",
            role=MeasurementRole.PRIMARY,
            registered_target=primary,
            observable="Cross-validated prediction error for T=a, T=aL, and T=a*sqrt(L)",
            input_condition="Included physical trials after frozen quality checks",
            parameter_values=common_parameters,
            evaluation_point="After all 48 scheduled trials and before evidence recording",
            convention="Lowest RMSE wins; all models have one fitted coefficient and zero intercept",
            aggregation="Leave one target-length level out, pool squared held-out residuals, take square root",
            tolerance="Report exact winner; decisive only if runner-up/best RMSE ratio >= 1.5",
            expected_behavior="Square-root model wins in the registered small-angle regime",
        ),
        MeasurementDefinition(
            measurement_id="secondary-rmse-ratio",
            role=MeasurementRole.SECONDARY,
            registered_target=secondary[0],
            observable="Second-lowest divided by lowest leave-one-length-out RMSE",
            input_condition="The same three candidate-model fits as the primary outcome",
            parameter_values={"decisive threshold": "1.5 dimensionless"},
            evaluation_point="After candidate-model scoring",
            convention="Ratios above one favor the selected model",
            aggregation="Runner-up RMSE divided by winning RMSE",
            tolerance=">= 1.5 for a directional model verdict",
            expected_behavior="At least 1.5 for the square-root model",
        ),
        MeasurementDefinition(
            measurement_id="secondary-log-slope",
            role=MeasurementRole.SECONDARY,
            registered_target=secondary[1],
            observable="Slope of log median period versus log median measured length",
            input_condition="Included trials grouped by the six target-length strata",
            parameter_values={"candidate exponents": "0, 0.5, 1"},
            evaluation_point="After clock correction and frozen exclusions",
            convention="Natural logarithms; positive length and period",
            aggregation="OLS slope across six stratum medians",
            tolerance="0.4 <= slope <= 0.6 for square-root support",
            expected_behavior="Slope nearest 0.5",
        ),
        MeasurementDefinition(
            measurement_id="secondary-gravity",
            role=MeasurementRole.SECONDARY,
            registered_target=secondary[2],
            observable="g=(2*pi/a)^2 from the all-data T=a*sqrt(L) coefficient",
            input_condition="Included, clock-corrected physical trials",
            parameter_values={"period": "seconds", "length": "meters"},
            evaluation_point="After fitting the square-root candidate",
            convention="Length is pivot to bob center of mass; zero intercept",
            aggregation="Single coefficient fit over all included trials",
            tolerance="9.5 <= g <= 10.1 m/s^2",
            expected_behavior="Consistent with local terrestrial gravity at coarse apparatus precision",
        ),
        MeasurementDefinition(
            measurement_id="control-clock",
            role=MeasurementRole.CONTROL,
            registered_target=controls[0],
            observable="Absolute observed/reference duration ratio minus one",
            input_condition="One 60.000 s check before and after collection for every used clock",
            parameter_values={"reference interval": "60.000 s"},
            evaluation_point="Before first trial and after final trial",
            convention="Positive error means the study clock runs long",
            aggregation="Maximum absolute relative error over checks",
            tolerance="<= 0.0025",
            expected_behavior="Every used clock passes before and after checks",
        ),
        MeasurementDefinition(
            measurement_id="control-length",
            role=MeasurementRole.CONTROL,
            registered_target=controls[1],
            observable="Absolute measured-target length divided by target length",
            input_condition="Each scheduled trial, pivot to bob center of mass",
            parameter_values={"length resolution": "<= 0.001 m"},
            evaluation_point="Immediately before each timing trial",
            convention="SI meters; target values define randomized strata",
            aggregation="Maximum relative error over all trials",
            tolerance="<= 0.005",
            expected_behavior="Every measured length remains within 0.5 percent of target",
        ),
        MeasurementDefinition(
            measurement_id="control-schedule",
            role=MeasurementRole.CONTROL,
            registered_target=controls[2],
            observable="Presence and exact fixed-field match for each scheduled trial ID",
            input_condition="Eight blocks containing all six target lengths once",
            parameter_values=common_parameters,
            evaluation_point="At dataset lock before analysis",
            convention="Sequence and source IDs must equal the generated schedule",
            aggregation="Exact set and field equality over 48 rows",
            tolerance="Zero missing, duplicate, unexpected, or altered fixed rows",
            expected_behavior="All randomized blocks are complete",
        ),
        MeasurementDefinition(
            measurement_id="control-timing-repeatability",
            role=MeasurementRole.CONTROL,
            registered_target=controls[3],
            observable="Absolute difference between first and blinded repeat period extraction",
            input_condition="The first scheduled trial in each of eight randomized blocks",
            parameter_values={
                "audit trials": "8 prespecified trials",
                "oscillations": "20 per extraction",
            },
            evaluation_point="Repeat extraction after all primary timestamps are locked",
            convention="Same-direction center crossings; repeat scorer does not inspect first values",
            aggregation="Maximum absolute per-oscillation period difference",
            tolerance="<= 0.01 s",
            expected_behavior="All eight audit trials satisfy the repeatability tolerance",
        ),
    ]


def _collection_rows(spec: dict[str, Any]) -> list[dict[str, object]]:
    rng = random.Random(_seed(str(spec["seed_reveal"])))
    lengths = [float(value) for value in spec["lengths_m"]]
    rows: list[dict[str, object]] = []
    sequence = 0
    for block_number in range(1, int(spec["blocks"]) + 1):
        block_lengths = list(lengths)
        rng.shuffle(block_lengths)
        for length in block_lengths:
            sequence += 1
            rows.append(
                {
                    "trial_id": f"b{block_number:02d}-t{sequence:03d}",
                    "block": block_number,
                    "sequence": sequence,
                    "length_target_m": f"{length:.3f}",
                    "length_measured_m": "",
                    "angle_start_deg": "",
                    "oscillation_count": int(spec["oscillations_per_trial"]),
                    "start_time_s": "",
                    "end_time_s": "",
                    "timing_audit": "yes" if len(rows) % len(lengths) == 0 else "no",
                    "audit_start_time_s": "",
                    "audit_end_time_s": "",
                    "clock_id": "clock-a",
                    "amplitude_end_deg": "",
                    "quality_flag": "ok",
                    "source_id": f"block-{block_number:02d}",
                    "notes": "",
                }
            )
    return rows


def _write_collection_guide(
    path: Path, output_root: Path, protocol_id: str, dataset_id: str
) -> None:
    absolute_output = output_root.resolve()
    content = f"""# Physical pendulum collection guide

This kit contains a frozen protocol but **no observations**. Do not edit
`schedule.csv` or `protocol-summary.json`.

## Apparatus and recording

1. Use one stable support, one string, and one compact bob. Measure length from
   the pivot to the bob's center of mass with resolution no worse than 1 mm.
2. Record one continuous raw video for each randomized block. Keep the camera
   fixed and make the center crossing and angle scale visible.
3. Calibrate `clock-a` against a 60.000 s reference immediately before block 1
   and after block 8; fill both rows in `clock-calibration.csv`.
4. Follow `schedule.csv` in sequence. Do not inspect interim model fits.
5. Release from rest without a push at approximately 5 degrees and never above
   7 degrees. Time 20 full oscillations from a same-direction center crossing to
   the next same-direction center crossing after the twentieth cycle.
6. Copy timing and measurement values into `observations.csv`. Never delete a
   row. For a contemporaneously observed defect, keep the row and replace `ok`
   with one allowed flag: `occlusion`, `count_uncertain`, `pivot_slip`, or
   `external_contact`.
7. After all primary timestamps are locked, independently re-score the eight
   rows marked `timing_audit=yes` without looking at the first values. Fill
   `audit_start_time_s` and `audit_end_time_s`; leave those fields blank for
   other rows.
8. Fill `source-files.csv` with each block video's relative or absolute path,
   SHA-256, and byte count. Every observation already names its block source.
9. Fill `session.json`, including timezone-aware collection timestamps. The
   analysis completion timestamp is optional and defaults to execution time.
   Preserve every raw video unchanged.

## Register and analyze

After collection, register the filled CSV/JSON files and every raw video as one
non-synthetic confirmatory dataset bound to `{protocol_id}`. From the repository
root, the base command is:

```bash
./research --workspace {absolute_output}/.research dataset register \\
  --id {dataset_id} \\
  --name "Physical pendulum observations v1" \\
  --role confirmatory \\
  --protocol {protocol_id} \\
  --observation-unit "One scheduled twenty-oscillation timing trial" \\
  --file {absolute_output}/collection-kit/observations.csv \\
  --file {absolute_output}/collection-kit/clock-calibration.csv \\
  --file {absolute_output}/collection-kit/source-files.csv \\
  --file {absolute_output}/collection-kit/session.json \\
  --file {absolute_output}/collection-kit/schedule.csv \\
  --file {absolute_output}/collection-kit/protocol-summary.json
```

Add one `--file` argument for every raw video. Then run:

```bash
./campaigns/newtonian_pendulum/physical/run analyze \\
  --kit {absolute_output}/collection-kit \\
  --dataset-id {dataset_id} \\
  --output {absolute_output}/analysis

./research --workspace {absolute_output}/.research run preflight \\
  --record-file {absolute_output}/analysis/run-record.json \\
  --artifact-root {absolute_output}/analysis
```

Inspect the preflight and analysis report before recording anything. A
scientifically adverse or inconclusive outcome is not an execution failure. If
preflight is ready, record the exact preflighted bytes using its reported
record-file SHA-256:

```bash
./research --workspace {absolute_output}/.research run record \\
  --record-file {absolute_output}/analysis/run-record.json \\
  --expect-record-sha256 <SHA256_FROM_PREFLIGHT> \\
  --artifact-root {absolute_output}/analysis
```

Only after a successful record should its apparatus-scoped outcome be attached
to the appropriate hypothesis and measurement-validity or association claim.
Use the `empirical_test` validation tag, state uncertainty, and explicitly say
that the result does not validate or refute Universal Theory as a whole.
"""
    path.write_text(content, encoding="utf-8")


def prepare_field_workspace(
    output_root: Path,
    *,
    human_reviewed: bool = False,
    spec_path: Path = SPEC_PATH,
    clock: Callable[[], str] = _utc_now,
) -> dict[str, Any]:
    if not human_reviewed:
        raise ValueError(
            "physical confirmatory protocol requires explicit human review of the "
            "candidate laws, measurements, boundaries, and decision rules"
        )
    if output_root.exists() and any(output_root.iterdir()):
        raise FileExistsError(f"refusing to overwrite non-empty output: {output_root}")
    output_root.mkdir(parents=True, exist_ok=True)
    workspace_root = output_root / ".research"
    kit_root = output_root / "collection-kit"
    kit_root.mkdir(parents=True, exist_ok=True)
    spec = json.loads(spec_path.read_text(encoding="utf-8"))

    tokens = (f"physical{index:04d}" for index in itertools.count(1))
    service = ResearchService(
        FileSystemRepository(workspace_root),
        actor="human-authorized-physical-pendulum",
        clock=clock,
        token=lambda: next(tokens),
    )
    service.init_workspace()
    inquiry = service.create_inquiry(
        CreateInquiry(
            title="Physical pendulum falsification run",
            initial_statement=(
                "Can a preregistered physical measurement distinguish constant, linear, "
                "and square-root period-length laws without hiding adverse outcomes?"
            ),
            inquiry_id="newtonian-pendulum-physical",
            decision_to_support=(
                "Whether Research Machine is ready to move from known-result calibration "
                "to harder theory-facing experiments."
            ),
            minimum_evidence=(
                "One raw-source-backed physical run with all execution gates evaluated, "
                "regardless of its scientific direction."
            ),
            decision_change_criteria=[
                "Proceed if the full protocol can be executed, audited, and interpreted without post-hoc rule changes.",
                "Repair the machine or protocol if provenance, measurement, or adverse-outcome handling fails.",
            ],
            decision_owner="project owner",
        )
    )
    question = service.add_question(
        AddQuestion(
            "What outcome would count as a valid challenge rather than a broken execution?"
        )
    )
    service.answer_question(
        question.question_id,
        "Any quality-valid constant, linear, weakly separated, or analyzer-discordant "
        "result remains a scientific outcome; only execution-contract failures invalidate it.",
    )
    measurement_claim = service.add_claim(
        AddClaim(
            statement=(
                "Raw-source, timing, length, angle, damping, schedule, and exclusion "
                "measurements satisfy the frozen physical protocol."
            ),
            level=ClaimLevel.MEASUREMENT_VALIDITY,
            scope="One registered apparatus and collection session.",
            decision_owner="project owner",
        )
    )
    relationship_claim = service.add_claim(
        AddClaim(
            statement=(
                "Within the registered apparatus regime, the observed period-length "
                "relationship discriminates among the three candidate laws."
            ),
            level=ClaimLevel.STATISTICAL_ASSOCIATION,
            parent_claims=[measurement_claim.claim_id],
            scope="Lengths 0.20-1.25 m and starting angle at most 7 degrees.",
            decision_owner="project owner",
        )
    )
    hypotheses = [
        service.propose_hypothesis(item)
        for item in _hypotheses(relationship_claim.claim_id)
    ]
    for hypothesis in hypotheses:
        service.activate_hypothesis(hypothesis.hypothesis_id)

    primary = "Winning candidate period-length law by leave-one-length-out RMSE"
    secondary = [
        "Runner-up-to-best leave-one-length-out RMSE ratio",
        "Median-period log-log exponent",
        "Implied gravitational acceleration under the square-root model",
    ]
    controls = [
        "Clock scale error against a 60.000 s reference interval",
        "Reported-to-measured pendulum-length relative error",
        "Acquisition-schedule completion by randomized block",
        "Timing extraction repeatability on prespecified audit trials",
    ]
    seed_reveal = str(spec["seed_reveal"])
    draft = service.create_protocol(
        CreateProtocol(
            experiment_id=str(spec["campaign_id"]),
            title="Prospective physical pendulum model discrimination",
            analysis_mode=AnalysisMode.CONFIRMATORY,
            hypotheses_tested=[item.hypothesis_id for item in hypotheses],
            primary_outcome=primary,
            protocol_kind=ProtocolKind.EXPERIMENTAL,
            methodology=(
                "Collect eight randomized complete blocks at six target lengths, time "
                "twenty oscillations from raw video, apply only contemporaneous frozen "
                "exclusions, and compare three one-parameter laws with two implementations."
            ),
            inputs_required=[
                "Immutable raw video for every randomized block",
                "Filled observations.csv, clock-calibration.csv, source-files.csv, and session.json",
            ],
            quality_requirements=list(spec["required_quality_gates"]),
            controls=controls,
            measurement_definitions=_measurements(primary, secondary, controls),
            expected_outputs=[
                "Machine-readable analysis report",
                "Preflightable immutable run record",
            ],
            success_conditions=[
                "Square-root law wins with runner-up/best RMSE ratio at least 1.5.",
                "Independent log-log exponent lies from 0.4 through 0.6.",
                "Implied g lies from 9.5 through 10.1 m/s^2.",
            ],
            environment_requirements=[
                "Python 3.11 or newer using the committed standard-library executor"
            ],
            secondary_outcomes=secondary,
            independent_variables=["Target pendulum length in meters"],
            randomization_plan=(
                "Eight complete blocks; independently shuffle all six lengths once per "
                "block using the SHA-256-committed seed. Follow global sequence exactly."
            ),
            blinding_plan=(
                "The collector cannot be blinded to physical length. Do not expose model "
                "expectations in the collection sheet or inspect interim fits; analysis "
                "is automated by hash-frozen code after dataset lock."
            ),
            sampling_unit=(
                "One scheduled timing of twenty full oscillations from same-direction "
                "center crossing to same-direction center crossing."
            ),
            sample_size_or_stopping_rule=(
                "Exactly 48 scheduled attempts: six lengths once in each of eight blocks. "
                "Never replace or delete a failed attempt."
            ),
            inclusion_rules=[
                "Use every row whose contemporaneous quality_flag is ok.",
                "Retain all excluded rows in the raw dataset.",
            ],
            exclusion_rules=[
                "Exclude only occlusion, count_uncertain, pivot_slip, or external_contact flagged during collection.",
                "At most four exclusions total, at most one per length, leaving at least seven per length.",
                "Do not exclude a trial from its period value or model residual.",
            ],
            sensor_requirements=[
                "Raw video retained and content-hashed for each block.",
                "Length resolution no worse than 0.001 m from pivot to bob center.",
                "Angle resolution no worse than 0.5 degrees.",
                "Blind repeat timing extraction for one prespecified trial per block.",
            ],
            calibration_requirements=[
                "One 60.000 s clock check before and after collection for every used clock.",
                "Measure pivot-to-center length immediately before every trial.",
            ],
            clock_accuracy_requirement="Maximum absolute relative clock error 0.0025.",
            preprocessing_pipeline=(
                "Verify source hashes and schedule; correct each duration by the mean "
                "observed/reference scale of its clock; divide by 20; apply only frozen "
                "flags; retain target strata while fitting with measured lengths."
            ),
            statistical_model=(
                "Fit T=a, T=aL, and T=a*sqrt(L), each through its registered origin form. "
                "Select by pooled leave-one-target-length-out RMSE; independently estimate "
                "the log-log slope from stratum medians."
            ),
            control_windows=["Clock calibration immediately before block 1 and after block 8"],
            multiple_testing_policy=(
                "One primary three-model comparison. Secondary intervals are conjunctive "
                "decision checks, not separately claimed discoveries."
            ),
            missing_data_policy=(
                "No row deletion or replacement. Frozen flagged exclusions are allowed only "
                "within total and per-length limits; otherwise interpretation is withheld."
            ),
            failure_conditions=[
                "Any execution-quality gate fails: outcome becomes not_interpretable.",
                "A constant or linear winner with ratio at least 1.5 weakens the square-root hypothesis in scope.",
                "Low separation or analyzer disagreement yields an inconclusive valid outcome.",
            ],
            safety_constraints=[
                "Use a lightweight bob and secure support away from faces, glass, pets, and walkways.",
                "Stop immediately if the support, pivot, string, or bob becomes unstable.",
                "No human or animal subject intervention is part of the experiment.",
            ],
            analysis_code_hash=analysis_code_hash(spec_path),
            random_seed_commitment=hashlib.sha256(seed_reveal.encode()).hexdigest(),
        )
    )
    protocol = service.freeze_protocol(draft.protocol_id)

    rows = _collection_rows(spec)
    fixed_fields = [
        "trial_id",
        "block",
        "sequence",
        "length_target_m",
        "oscillation_count",
        "source_id",
        "timing_audit",
    ]
    _write_csv(
        kit_root / "schedule.csv",
        fixed_fields,
        [{field: row[field] for field in fixed_fields} for row in rows],
    )
    _write_csv(kit_root / "observations.csv", OBSERVATION_FIELDS, rows)
    _write_csv(
        kit_root / "clock-calibration.csv",
        [
            "calibration_id",
            "clock_id",
            "phase",
            "reference_duration_s",
            "observed_duration_s",
            "performed_at_utc",
        ],
        [
            {
                "calibration_id": "clock-a-before",
                "clock_id": "clock-a",
                "phase": "before",
                "reference_duration_s": "60.000",
                "observed_duration_s": "",
                "performed_at_utc": "",
            },
            {
                "calibration_id": "clock-a-after",
                "clock_id": "clock-a",
                "phase": "after",
                "reference_duration_s": "60.000",
                "observed_duration_s": "",
                "performed_at_utc": "",
            },
        ],
    )
    _write_csv(
        kit_root / "source-files.csv",
        ["source_id", "block", "locator", "sha256", "size_bytes"],
        [
            {
                "source_id": f"block-{block:02d}",
                "block": block,
                "locator": "",
                "sha256": "",
                "size_bytes": "",
            }
            for block in range(1, int(spec["blocks"]) + 1)
        ],
    )
    (kit_root / "session.json").write_text(
        json.dumps(
            {
                "session_id": "pendulum-physical-session-01",
                "protocol_id": protocol.protocol_id,
                "protocol_hash": protocol.protocol_hash,
                "collection_started_at_utc": "",
                "collection_completed_at_utc": "",
                "analysis_completed_at_utc": "",
                "collector_id": "",
                "location_description": "",
                "apparatus_id": "",
                "timer_method": "raw video timestamps",
                "deviations": [],
                "notes": "",
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    protocol_summary = {
        "campaign_id": spec["campaign_id"],
        "protocol_id": protocol.protocol_id,
        "protocol_hash": protocol.protocol_hash,
        "registration_timestamp": protocol.registration_timestamp,
        "analysis_code_hash": protocol.analysis_code_hash,
        "physical_spec_sha256": hashlib.sha256(spec_path.read_bytes()).hexdigest(),
        "random_seed_commitment": protocol.random_seed_commitment,
        "random_seed_reveal": seed_reveal,
        "synthetic": False,
        "observations_present_at_freeze": False,
    }
    (kit_root / "protocol-summary.json").write_text(
        json.dumps(protocol_summary, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    dataset_id = "ds-newtonian-pendulum-physical-v1"
    _write_collection_guide(
        kit_root / "COLLECTION-GUIDE.md",
        output_root,
        protocol.protocol_id,
        dataset_id,
    )
    synthesis = service.build_synthesis()
    audit = service.audit_rigor(fail_on="error")
    ledger = service.verify_ledger()
    summary: dict[str, Any] = {
        **protocol_summary,
        "inquiry_id": inquiry.inquiry_id,
        "dataset_id_reserved": dataset_id,
        "dataset_count": len(service.list_datasets()),
        "run_count": len(service.list_runs()),
        "ready_for_collection": audit.structurally_valid and ledger["valid"],
        "rigor_audit": audit.to_dict(),
        "ledger_verification": ledger,
        "collection_guide": str((kit_root / "COLLECTION-GUIDE.md").resolve()),
        "synthesis_path": synthesis["path"],
    }
    (output_root / "preparation-summary.json").write_text(
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
        help="Attest that a person approved the hypotheses and frozen decision rules",
    )
    args = parser.parse_args()
    if not args.human_reviewed:
        parser.error("--human-reviewed is required; generated hypotheses cannot self-activate")
    result = prepare_field_workspace(
        args.output.resolve(),
        human_reviewed=True,
        spec_path=args.spec.resolve(),
    )
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
