from __future__ import annotations

from dataclasses import replace
from dataclasses import fields
import hashlib
import json
from datetime import datetime

import pytest

from research_machine.application.policies import validate_protocol_freeze
from research_machine.application.ethics import validate_original_review_artifact
from research_machine.application.service import _protocol_commitment
from research_machine.domain.errors import ValidationError
from research_machine.domain.models import AnalysisMode, ExperimentProtocol, ProtocolKind, ControlDefinition
from research_machine.application.commands import CreateProtocol, RecordEthicsReviewEvent


def _frozen_reviewed_human_protocol(tmp_path):
    from test_execution import prepared_service

    workspace = tmp_path / "workspace"
    service, hypothesis_id = prepared_service(workspace)
    review_root = tmp_path / "review-root"
    artifact = review_root / "review" / "decision.pdf"
    artifact.parent.mkdir(parents=True)
    review_bytes = b"synthetic independent review fixture\n"
    artifact.write_bytes(review_bytes)
    base = _human_protocol(
        hypotheses_tested=[hypothesis_id],
        independent_reviewed_at="2026-09-02T11:00:00Z",
        independent_review_artifact_sha256=hashlib.sha256(review_bytes).hexdigest(),
    )
    values = {field.name: getattr(base, field.name) for field in fields(CreateProtocol)}
    draft = service.create_protocol(CreateProtocol(**values))
    frozen = service.freeze_protocol(draft.protocol_id, review_artifact_root=str(review_root))
    return workspace, service, frozen


def _ethics_status_command(
    protocol_id: str, root, name: str, status: str, **overrides
) -> RecordEthicsReviewEvent:
    artifact = root / name
    artifact.write_text(f"{status} review for {protocol_id}", encoding="utf-8")
    values = {
        "protocol_id": protocol_id,
        "status": status,
        "effective_at": "2026-09-02T12:00:00Z",
        "reason": f"Independent review classified this protocol as {status}.",
        "review_artifact_locator": name,
        "review_artifact_sha256": hashlib.sha256(artifact.read_bytes()).hexdigest(),
        "review_artifact_root": str(root),
    }
    values.update(overrides)
    return RecordEthicsReviewEvent(**values)


def _refresh_packaged_file(package, name: str) -> str:
    manifest_path = package / "package-manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["files"][name] = hashlib.sha256((package / name).read_bytes()).hexdigest()
    manifest_path.write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return hashlib.sha256(manifest_path.read_bytes()).hexdigest()


def _human_protocol(**overrides: object) -> ExperimentProtocol:
    values: dict[str, object] = {
        "protocol_id": "ethics-v1",
        "protocol_family_id": "ethics",
        "version": 1,
        "experiment_id": "human-study",
        "title": "Human study",
        "analysis_mode": AnalysisMode.CONFIRMATORY,
        "hypotheses_tested": ["h1"],
        "primary_outcome": "Registered outcome",
        "created_at": "2026-09-04T00:00:00Z",
        "created_by": "test",
        "protocol_kind": ProtocolKind.EXPERIMENTAL,
        "methodology": "A bounded randomized study.",
        "quality_requirements": ["integrity"],
        "controls": ["Control condition"],
        "control_definitions": [ControlDefinition("reference-1", "Control condition", "reference",
            "Bound the registered comparison", "Registered reference response", "integrity")],
        "expected_outputs": ["Result table"],
        "success_conditions": ["Report all outcomes."],
        "randomization_plan": "Randomize before enrollment.",
        "blinding_plan": "Outcome assessor is blinded.",
        "sampling_unit": "Participant",
        "independent_unit": "Participant",
        "repeated_measures": False,
        "analysis_design": "independent_groups",
        "sample_size_or_stopping_rule": "Fixed sample of 20.",
        "preprocessing_pipeline": "Frozen preprocessing.",
        "statistical_model": "Registered comparison.",
        "multiple_testing_policy": "One primary outcome.",
        "missing_data_policy": "Report and bound missingness.",
        "failure_conditions": ["Any required gate fails."],
        "safety_constraints": ["Do not collect before review."],
        "analysis_code_hash": "a" * 64,
        "human_subjects": True,
        "consent_plan": "Written informed consent before enrollment.",
        "withdrawal_plan": "Participants may withdraw without penalty.",
        "privacy_plan": "Pseudonymous access-controlled records.",
        "retention_deletion_plan": "Delete identifiers after the registered retention period.",
        "risk_assessment": "Low-risk questionnaire with distress escalation instructions.",
        "vulnerable_population_plan": "Exclude people unable to consent independently; document and review any exception before enrollment.",
        "data_security_plan": "Encrypt records at rest and in transit; restrict access by named role and audit access.",
        "incidental_findings_plan": "No clinical interpretation is offered; unexpected safety-relevant findings follow the reviewed escalation plan.",
        "independent_review_receipt": "IRB-EXAMPLE-001",
        "independent_review_decision": "approved",
        "independent_reviewer_role": "Institutional review board",
        "independent_reviewed_at": "2026-09-04T01:00:00Z",
        "independent_review_scope": "Protocol, consent materials, recruitment, and data handling.",
        "independent_review_artifact_locator": "review/decision.pdf",
        "independent_review_artifact_sha256": "b" * 64,
    }
    values.update(overrides)
    return ExperimentProtocol(**values)  # type: ignore[arg-type]


def test_human_protocol_cannot_freeze_without_all_ethics_receipts() -> None:
    with pytest.raises(ValidationError, match="consent_plan"):
        validate_protocol_freeze(_human_protocol(consent_plan=""))


def test_complete_human_protocol_can_pass_the_ethics_gate() -> None:
    protocol = _human_protocol()
    validate_protocol_freeze(protocol)


@pytest.mark.parametrize("field", [
    "vulnerable_population_plan", "data_security_plan", "incidental_findings_plan",
])
def test_human_protocol_requires_each_specialized_safeguard(field) -> None:
    with pytest.raises(ValidationError, match=field):
        validate_protocol_freeze(_human_protocol(**{field: ""}))


@pytest.mark.parametrize(
    ("overrides", "message"),
    [
        ({"independent_review_decision": "pending"}, "independent_review_decision"),
        ({"independent_reviewed_at": "2026-09-04"}, "timezone offset"),
        ({"independent_review_artifact_sha256": "not-a-digest"}, "64 lowercase hex"),
        ({"independent_review_decision": "approved_with_conditions"}, "independent_review_conditions"),
    ],
)
def test_human_protocol_rejects_unresolved_or_unverifiable_review(overrides, message) -> None:
    with pytest.raises(ValidationError, match=message):
        validate_protocol_freeze(_human_protocol(**overrides))


def test_conditional_independent_review_preserves_conditions() -> None:
    validate_protocol_freeze(_human_protocol(
        independent_review_decision="approved_with_conditions",
        independent_review_conditions=["No enrollment of minors."],
    ))


def test_independent_review_artifact_and_decision_are_bound_to_protocol_commitment() -> None:
    protocol = _human_protocol()
    baseline = _protocol_commitment(protocol)
    assert _protocol_commitment(replace(
        protocol, independent_review_artifact_sha256="c" * 64
    )) != baseline
    assert _protocol_commitment(replace(
        protocol, independent_review_decision="approved_with_conditions",
        independent_review_conditions=["No enrollment of minors."],
    )) != baseline
    for field in ("vulnerable_population_plan", "data_security_plan", "incidental_findings_plan"):
        assert _protocol_commitment(replace(protocol, **{field: "A materially revised reviewed plan."})) != baseline


def test_human_protocol_freeze_verifies_review_artifact_bytes_without_writing_on_failure(tmp_path) -> None:
    from test_execution import prepared_service

    service, hypothesis_id = prepared_service(tmp_path / "workspace")
    review_root = tmp_path / "review-root"
    artifact = review_root / "review" / "decision.pdf"
    artifact.parent.mkdir(parents=True)
    original = b"synthetic independent review fixture\n"
    artifact.write_bytes(original)
    base = _human_protocol(
        hypotheses_tested=[hypothesis_id],
        independent_reviewed_at="2026-09-02T11:00:00Z",
        independent_review_artifact_sha256=hashlib.sha256(original).hexdigest(),
    )
    values = {field.name: getattr(base, field.name) for field in fields(CreateProtocol)}
    draft = service.create_protocol(CreateProtocol(**values))
    assert service.show_inquiry()["protocols"][0]["status"] == "draft"
    ledger = next((tmp_path / "workspace").rglob("ledger.jsonl"))
    before = ledger.read_bytes()
    with pytest.raises(ValidationError, match="review_artifact_root"):
        service.freeze_protocol(draft.protocol_id)
    assert ledger.read_bytes() == before
    with pytest.raises(ValidationError, match="review_artifact_root.*canonical"):
        service.freeze_protocol(
            draft.protocol_id, review_artifact_root=f" {review_root} "
        )
    assert ledger.read_bytes() == before
    artifact.write_bytes(b"tampered")
    with pytest.raises(ValidationError, match="artifact verification failed"):
        service.freeze_protocol(draft.protocol_id, review_artifact_root=str(review_root))
    assert ledger.read_bytes() == before
    artifact.write_bytes(original)
    frozen = service.freeze_protocol(draft.protocol_id, review_artifact_root=str(review_root))
    verification = frozen.independent_review_verification
    assert verification["artifact_integrity"]["all_artifacts_match"] is True
    assert verification["review_artifact_root"] == str(review_root.resolve())
    assert verification["reviewer_identity_authenticated"] is False
    assert verification["substantive_adequacy_verified"] is False
    for field, message in (
        ("verified_by", "independent-review verified_by.*canonical"),
        ("review_artifact_root", "independent-review artifact root.*canonical"),
        ("scope", "independent-review verification scope.*canonical"),
    ):
        tampered_verification = dict(verification)
        tampered_verification[field] = f" {tampered_verification[field]} "
        with pytest.raises(ValidationError, match=message):
            validate_original_review_artifact(
                replace(
                    frozen,
                    independent_review_verification=tampered_verification,
                )
            )
    artifact.write_bytes(b"changed after protocol freeze")
    with pytest.raises(ValidationError, match="original independent-review artifact no longer matches"):
        service.show_inquiry()
    with pytest.raises(ValidationError, match="original independent-review artifact no longer matches"):
        service.export_replication_package(
            frozen.protocol_id, str(tmp_path / "must-not-export")
        )
    artifact.write_bytes(original)

    future = _human_protocol(
        experiment_id="future-review", hypotheses_tested=[hypothesis_id],
        independent_reviewed_at="2026-09-03T11:00:00Z",
        independent_review_artifact_sha256=hashlib.sha256(original).hexdigest(),
    )
    future_values = {field.name: getattr(future, field.name) for field in fields(CreateProtocol)}
    future_draft = service.create_protocol(CreateProtocol(**future_values))
    before_future_freeze = ledger.read_bytes()
    with pytest.raises(ValidationError, match="cannot postdate"):
        service.freeze_protocol(future_draft.protocol_id, review_artifact_root=str(review_root))
    assert ledger.read_bytes() == before_future_freeze


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("protocol_id", "{protocol_id} ", "protocol_id must be canonical"),
        ("status", " suspended", "ethics review status must be canonical"),
        ("event_id", " ethics-manual", "event_id must be canonical"),
        ("effective_at", " 2026-09-02T12:00:00Z", "effective_at must be canonical"),
        ("expires_at", " 2026-12-31T23:59:59Z", "expires_at must be canonical"),
        ("reason", " Independent review classified this protocol as active. ", "ethics review event reason must be canonical"),
        ("review_artifact_locator", " status.json", "review_artifact_locator must be canonical"),
        ("review_artifact_root", "{root} ", "review_artifact_root must be canonical"),
    ],
)
def test_ethics_review_status_command_handles_must_be_canonical(
    tmp_path, field, value, message
) -> None:
    _, service, frozen = _frozen_reviewed_human_protocol(tmp_path)
    status_root = tmp_path / "status-evidence"
    status_root.mkdir()
    if value == "{protocol_id} ":
        value = f"{frozen.protocol_id} "
    command = _ethics_status_command(
        frozen.protocol_id, status_root, "status.json", "active",
        expires_at="2026-12-31T23:59:59Z",
    )

    with pytest.raises(ValidationError, match=message):
        if value == "{root} ":
            value = f"{status_root} "
        service.record_ethics_review_event(replace(command, **{field: value}))


def test_ethics_review_status_supersedes_handle_must_be_canonical(tmp_path) -> None:
    _, service, frozen = _frozen_reviewed_human_protocol(tmp_path)
    status_root = tmp_path / "status-evidence"
    status_root.mkdir()
    suspension = service.record_ethics_review_event(_ethics_status_command(
        frozen.protocol_id, status_root, "suspension.json", "suspended",
    ))

    with pytest.raises(ValidationError, match="supersedes_event_id must be canonical"):
        service.record_ethics_review_event(_ethics_status_command(
            frozen.protocol_id, status_root, "renewal.json", "active",
            expires_at="2026-12-31T23:59:59Z",
            supersedes_event_id=f"{suspension.event_id} ",
        ))


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("event_id", "{event_id} ", "event_id must be canonical"),
        ("protocol_id", "{protocol_id} ", "protocol_id must be canonical"),
        ("protocol_hash", "{protocol_hash} ", "protocol_hash must be canonical"),
        ("status", " suspended", "status must be canonical"),
        ("effective_at", " 2026-09-02T12:00:00Z", "event effective_at must be canonical"),
        ("created_at", " 2026-09-02T12:00:00Z", "event created_at must be canonical"),
        ("supersedes_event_id", "{event_id} ", "supersedes_event_id must be canonical"),
        ("reason", " Independent review classified this protocol as suspended. ", "review event reason must be canonical"),
        ("review_artifact_locator", " suspension.json", "review event artifact locator must be canonical"),
        ("review_artifact_root", "{root} ", "review event artifact root must be canonical"),
        ("created_by", " test-researcher", "review event created_by must be canonical"),
        ("conclusion_ceiling", " Records local review-status evidence. ", "review event conclusion_ceiling must be canonical"),
    ],
)
def test_ethics_review_status_reads_fail_closed_on_noncanonical_chain_tampering(
    tmp_path, field, value, message
) -> None:
    workspace, service, frozen = _frozen_reviewed_human_protocol(tmp_path)
    status_root = tmp_path / "status-evidence"
    status_root.mkdir()
    event = service.record_ethics_review_event(_ethics_status_command(
        frozen.protocol_id, status_root, "suspension.json", "suspended",
    ))
    if value == "{event_id} ":
        value = f"{event.event_id} "
    elif value == "{protocol_id} ":
        value = f"{frozen.protocol_id} "
    elif value == "{protocol_hash} ":
        value = f"{frozen.protocol_hash} "
    elif value == "{root} ":
        value = f"{status_root} "
    event_file = next(workspace.rglob(f"{event.event_id}.json"))
    tampered = json.loads(event_file.read_text(encoding="utf-8"))
    tampered[field] = value
    event_file.write_text(json.dumps(tampered), encoding="utf-8")

    with pytest.raises(ValidationError, match=message):
        service.show_inquiry()


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("reason", " Independent review classified this protocol as suspended. ", "review event reason must be canonical"),
        ("conclusion_ceiling", " Records local review-status evidence. ", "review event conclusion_ceiling must be canonical"),
        ("created_by", " test-researcher", "review event created_by must be canonical"),
    ],
)
def test_redacted_replication_package_replays_ethics_event_canonical_semantics(
    tmp_path, field, value, message
) -> None:
    from research_machine.replication.package import verify_replication_package

    _, service, frozen = _frozen_reviewed_human_protocol(tmp_path)
    status_root = tmp_path / "status-evidence"
    status_root.mkdir()
    service.record_ethics_review_event(_ethics_status_command(
        frozen.protocol_id, status_root, "suspension.json", "suspended",
    ))
    package = tmp_path / "package"
    exported = service.export_replication_package(frozen.protocol_id, str(package))
    verify_replication_package(package, exported["package_manifest_sha256"])

    events_path = package / "ethics-review-events.json"
    events = json.loads(events_path.read_text(encoding="utf-8"))
    events[0][field] = value
    events_path.write_text(
        json.dumps(events, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    manifest_path = package / "package-manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["files"]["ethics-review-events.json"] = hashlib.sha256(
        events_path.read_bytes()
    ).hexdigest()
    manifest_path.write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    commitment = hashlib.sha256(manifest_path.read_bytes()).hexdigest()

    with pytest.raises(ValidationError, match=message):
        verify_replication_package(package, commitment)


def test_conditional_review_obligations_require_exact_artifact_backed_discharge_at_data_intake(
    tmp_path,
) -> None:
    from research_machine.application.commands import RegisterDataset
    from research_machine.domain.models import DatasetArtifact, DatasetRole
    from test_execution import prepared_service

    workspace = tmp_path / "workspace"
    service, hypothesis_id = prepared_service(workspace)
    review_root = tmp_path / "review-root"
    review_artifact = review_root / "review" / "decision.pdf"
    review_artifact.parent.mkdir(parents=True)
    review_bytes = b"synthetic conditional independent review\n"
    review_artifact.write_bytes(review_bytes)
    condition = "Maintain the reviewed exclusion of minors throughout enrollment."
    base = _human_protocol(
        hypotheses_tested=[hypothesis_id],
        independent_review_decision="approved_with_conditions",
        independent_review_conditions=[condition],
        independent_reviewed_at="2026-09-02T11:00:00Z",
        independent_review_artifact_sha256=hashlib.sha256(review_bytes).hexdigest(),
    )
    values = {field.name: getattr(base, field.name) for field in fields(CreateProtocol)}
    draft = service.create_protocol(CreateProtocol(**values))
    frozen = service.freeze_protocol(
        draft.protocol_id, review_artifact_root=str(review_root)
    )
    ethics_root = tmp_path / "ethics-evidence"
    evidence = ethics_root / "eligibility-audit.json"
    evidence.parent.mkdir(parents=True)
    evidence_bytes = b'{"minors_enrolled":0,"synthetic_fixture":true}\n'
    evidence.write_bytes(evidence_bytes)
    evidence_sha256 = hashlib.sha256(evidence_bytes).hexdigest()
    discharge = {
        "discharge_id": "ethics-discharge-001",
        "protocol_id": frozen.protocol_id,
        "protocol_hash": frozen.protocol_hash,
        "independent_review_receipt": frozen.independent_review_receipt,
        "assessor": "fixture compliance reviewer",
        "assessed_at": service.clock(),
        "evidence_artifacts": [{
            "locator": "eligibility-audit.json", "sha256": evidence_sha256,
            "size_bytes": len(evidence_bytes),
            "media_type": "application/json",
        }],
        "conditions": [{
            "condition": condition,
            "compliance_status": "control_active",
            "rationale": "The reviewed eligibility control is active and the audit contains no minors.",
            "evidence_sha256": evidence_sha256,
            "evidence_location": "/minors_enrolled",
            "valid_through": "2026-12-31T23:59:59Z",
        }],
    }
    command = RegisterDataset(
        name="Synthetic conditional human data",
        role=DatasetRole.CONFIRMATORY,
        artifacts=[DatasetArtifact("human-data.csv", "d" * 64)],
        protocol_id=frozen.protocol_id,
        synthetic=True,
        metadata={"ethics_condition_discharge": discharge},
    )
    ledger = next(workspace.rglob("ledger.jsonl"))
    before = ledger.read_bytes()
    with pytest.raises(ValidationError, match="ethics_artifact_root"):
        service.register_dataset(command)
    assert ledger.read_bytes() == before
    assert service.list_datasets() == []
    forged = dict(discharge)
    forged["conditions"] = [{**discharge["conditions"][0], "condition": "A different condition"}]
    with pytest.raises(ValidationError, match="cover exactly"):
        service.register_dataset(replace(
            command,
            metadata={"ethics_condition_discharge": forged},
            ethics_artifact_root=str(ethics_root),
        ))
    assert ledger.read_bytes() == before
    bad_location = dict(discharge)
    bad_location["conditions"] = [{
        **discharge["conditions"][0], "evidence_location": "/not_present",
    }]
    with pytest.raises(ValidationError, match="does not resolve"):
        service.register_dataset(replace(
            command,
            metadata={"ethics_condition_discharge": bad_location},
            ethics_artifact_root=str(ethics_root),
        ))
    assert ledger.read_bytes() == before
    padded_media_type = dict(discharge)
    padded_media_type["evidence_artifacts"] = [{
        **discharge["evidence_artifacts"][0], "media_type": " application/json ",
    }]
    with pytest.raises(ValidationError, match="artifact media_type must be canonical"):
        service.register_dataset(replace(
            command,
            metadata={"ethics_condition_discharge": padded_media_type},
            ethics_artifact_root=str(ethics_root),
        ))
    assert ledger.read_bytes() == before
    evidence.write_bytes(b"tampered")
    with pytest.raises(ValidationError, match="evidence verification failed"):
        service.register_dataset(replace(
            command, ethics_artifact_root=str(ethics_root)
        ))
    assert ledger.read_bytes() == before
    assert service.list_datasets() == []
    evidence.write_bytes(evidence_bytes)
    with pytest.raises(ValidationError, match="condition evidence artifact root.*canonical"):
        service.register_dataset(replace(
            command,
            ethics_artifact_root=f" {ethics_root} ",
        ))
    assert ledger.read_bytes() == before
    accepted = service.register_dataset(replace(
        command, ethics_artifact_root=str(ethics_root)
    ))
    verification = accepted.metadata["ethics_condition_verification"]
    assert verification["protocol_hash"] == frozen.protocol_hash
    assert verification["evidence_artifact_root"] == str(ethics_root.resolve())
    assert verification["artifact_integrity"]["all_artifacts_match"] is True
    assert verification["evidence_location_checks"][0]["status"] == "resolved"
    assert verification["evidence_location_checks"][0]["location_kind"] == "json_pointer"
    assert verification["ongoing_controls_require_continued_monitoring"] is True
    assert verification["condition_truth_independently_established"] is False
    from research_machine.application.ethics import reverify_ethics_condition_discharge
    tampered_verification = dict(verification)
    tampered_verification["verified_by"] = f" {tampered_verification['verified_by']} "
    tampered = replace(
        accepted,
        metadata={**accepted.metadata, "ethics_condition_verification": tampered_verification},
    )
    with pytest.raises(ValidationError, match="condition verification actor.*canonical"):
        reverify_ethics_condition_discharge(frozen, tampered)
    from research_machine.application.ethics import validate_ethics_conditions_for_run
    current = validate_ethics_conditions_for_run(
        frozen, [accepted], datetime.fromisoformat("2026-09-03T00:00:00+00:00")
    )
    assert current["status"] == "condition_discharge_valid_for_run"
    evidence.write_bytes(b'{"minors_enrolled":1}\n')
    with pytest.raises(ValidationError, match="evidence verification failed"):
        validate_ethics_conditions_for_run(
            frozen, [accepted], datetime.fromisoformat("2026-09-03T00:00:00+00:00")
        )
    with pytest.raises(ValidationError, match="evidence verification failed"):
        service.show_inquiry()
    evidence.write_bytes(evidence_bytes)
    nonhuman_base = _human_protocol(
        experiment_id="nonhuman-laundering-target",
        hypotheses_tested=[hypothesis_id],
        human_subjects=False,
    )
    nonhuman_values = {
        field.name: getattr(nonhuman_base, field.name) for field in fields(CreateProtocol)
    }
    nonhuman_draft = service.create_protocol(CreateProtocol(**nonhuman_values))
    nonhuman = service.freeze_protocol(nonhuman_draft.protocol_id)
    before_cross_protocol = ledger.read_bytes()
    with pytest.raises(ValidationError, match="exact same frozen protocol"):
        service.register_dataset(RegisterDataset(
            dataset_id="cross-protocol-derived",
            name="Cross-protocol derived data",
            role=DatasetRole.CONFIRMATORY,
            artifacts=[DatasetArtifact("derived-human-data.csv", "f" * 64)],
            source_dataset_ids=[accepted.dataset_id],
            protocol_id=nonhuman.protocol_id,
            synthetic=True,
        ))
    assert ledger.read_bytes() == before_cross_protocol
    with pytest.raises(ValidationError, match="expired before run completion"):
        validate_ethics_conditions_for_run(
            frozen, [accepted], datetime.fromisoformat("2027-01-01T00:00:00+00:00")
        )
    from research_machine.application.commands import RecordEthicsReviewEvent
    status_root = tmp_path / "status-evidence"
    suspension_artifact = status_root / "suspension.json"
    suspension_artifact.parent.mkdir(parents=True)
    suspension_bytes = b'{"status":"suspended","reason":"fixture safety review"}\n'
    suspension_artifact.write_bytes(suspension_bytes)
    suspension = service.record_ethics_review_event(RecordEthicsReviewEvent(
        protocol_id=frozen.protocol_id,
        status="suspended",
        effective_at=service.clock(),
        reason="Fixture safety review suspended enrollment and analysis.",
        review_artifact_locator="suspension.json",
        review_artifact_sha256=hashlib.sha256(suspension_bytes).hexdigest(),
        review_artifact_root=str(status_root),
    ))
    package = tmp_path / "suspended-replication-package"
    exported = service.export_replication_package(frozen.protocol_id, str(package))
    package_manifest = json.loads((package / "package-manifest.json").read_text())
    assert package_manifest["latest_recorded_ethics_status"] == "suspended"
    assert package_manifest["ethics_review_event_ids"] == [suspension.event_id]
    assert package_manifest["replication_ethics_authorized"] is False
    packaged_events = json.loads((package / "ethics-review-events.json").read_text())
    assert packaged_events[0]["status"] == "suspended"
    assert packaged_events[0]["review_artifact_locator"].startswith("[redacted:")
    assert packaged_events[0]["review_artifact_root"].startswith("[redacted:")
    assert exported["package_manifest_sha256"]
    after_suspension = ledger.read_bytes()
    blocked = replace(
        command,
        dataset_id="blocked-after-suspension",
        artifacts=[DatasetArtifact("blocked.csv", "e" * 64)],
        ethics_artifact_root=str(ethics_root),
    )
    with pytest.raises(ValidationError, match="clearance is suspended"):
        service.register_dataset(blocked)
    with pytest.raises(ValidationError, match="clearance is suspended"):
        service.validate_analysis_execution(
            frozen.protocol_id,
            {},
            {},
            "a" * 64,
            "a" * 64,
            accepted.dataset_id,
            "d" * 64,
            0,
            "computation_only",
        )
    assert ledger.read_bytes() == after_suspension
    renewal_artifact = status_root / "renewal.json"
    renewal_bytes = b'{"status":"active","scope":"fixture renewal"}\n'
    renewal_artifact.write_bytes(renewal_bytes)
    with pytest.raises(ValidationError, match="supersede the exact latest"):
        service.record_ethics_review_event(RecordEthicsReviewEvent(
            protocol_id=frozen.protocol_id,
            status="active",
            effective_at=service.clock(),
            expires_at="2026-12-31T23:59:59Z",
            reason="Fixture renewal.",
            review_artifact_locator="renewal.json",
            review_artifact_sha256=hashlib.sha256(renewal_bytes).hexdigest(),
            review_artifact_root=str(status_root),
            supersedes_event_id="wrong-event",
        ))
    renewal = service.record_ethics_review_event(RecordEthicsReviewEvent(
        protocol_id=frozen.protocol_id,
        status="active",
        effective_at=service.clock(),
        expires_at="2026-12-31T23:59:59Z",
        reason="Fixture review restored clearance.",
        review_artifact_locator="renewal.json",
        review_artifact_sha256=hashlib.sha256(renewal_bytes).hexdigest(),
        review_artifact_root=str(status_root),
        supersedes_event_id=suspension.event_id,
    ))
    restored = service.register_dataset(blocked)
    status_check = restored.metadata["ethics_review_status_check"]
    assert status_check["status"] == "active"
    assert status_check["review_event_id"] == renewal.event_id
    assert status_check["basis"] == "append_only_ethics_review_event"
    assert service.verify_ledger()["valid"]
    renewal_artifact.write_bytes(b'{"status":"active","tampered":true}\n')
    with pytest.raises(ValidationError, match="artifact no longer matches its integrity receipt"):
        service.show_inquiry()
    with pytest.raises(ValidationError, match="artifact no longer matches its integrity receipt"):
        service.register_dataset(replace(blocked, dataset_id="blocked-after-artifact-mutation"))


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        ("receipt_status", "condition results changed"),
        ("discharge_status", "condition results changed"),
        ("location_check", "location check no longer matches"),
        ("monitoring_flag", "condition monitoring flag changed"),
    ],
)
def test_redacted_replication_package_replays_condition_discharge_semantics(
    tmp_path,
    mutation,
    message,
) -> None:
    from research_machine.application.commands import RegisterDataset
    from research_machine.domain.models import DatasetArtifact, DatasetRole
    from research_machine.replication.package import verify_replication_package
    from test_execution import prepared_service

    workspace = tmp_path / "workspace"
    service, hypothesis_id = prepared_service(workspace)
    review_root = tmp_path / "review-root"
    review_artifact = review_root / "review" / "decision.pdf"
    review_artifact.parent.mkdir(parents=True)
    review_bytes = b"synthetic conditional independent review\n"
    review_artifact.write_bytes(review_bytes)
    condition = "Maintain the reviewed exclusion of minors throughout enrollment."
    base = _human_protocol(
        hypotheses_tested=[hypothesis_id],
        independent_review_decision="approved_with_conditions",
        independent_review_conditions=[condition],
        independent_reviewed_at="2026-09-02T11:00:00Z",
        independent_review_artifact_sha256=hashlib.sha256(review_bytes).hexdigest(),
    )
    values = {field.name: getattr(base, field.name) for field in fields(CreateProtocol)}
    draft = service.create_protocol(CreateProtocol(**values))
    frozen = service.freeze_protocol(
        draft.protocol_id, review_artifact_root=str(review_root)
    )
    ethics_root = tmp_path / "ethics-evidence"
    evidence = ethics_root / "eligibility-audit.json"
    evidence.parent.mkdir(parents=True)
    evidence_bytes = b'{"minors_enrolled":0,"synthetic_fixture":true}\n'
    evidence.write_bytes(evidence_bytes)
    evidence_sha256 = hashlib.sha256(evidence_bytes).hexdigest()
    discharge = {
        "discharge_id": "ethics-discharge-001",
        "protocol_id": frozen.protocol_id,
        "protocol_hash": frozen.protocol_hash,
        "independent_review_receipt": frozen.independent_review_receipt,
        "assessor": "fixture compliance reviewer",
        "assessed_at": service.clock(),
        "evidence_artifacts": [{
            "locator": "eligibility-audit.json",
            "sha256": evidence_sha256,
            "size_bytes": len(evidence_bytes),
            "media_type": "application/json",
        }],
        "conditions": [{
            "condition": condition,
            "compliance_status": "control_active",
            "rationale": "The reviewed eligibility control is active and the audit contains no minors.",
            "evidence_sha256": evidence_sha256,
            "evidence_location": "/minors_enrolled",
            "valid_through": "2026-12-31T23:59:59Z",
        }],
    }
    service.register_dataset(RegisterDataset(
        name="Synthetic conditional human data",
        role=DatasetRole.CONFIRMATORY,
        artifacts=[DatasetArtifact("human-data.csv", "d" * 64)],
        protocol_id=frozen.protocol_id,
        synthetic=True,
        metadata={"ethics_condition_discharge": discharge},
        ethics_artifact_root=str(ethics_root),
    ))
    package = tmp_path / f"package-{mutation}"
    exported = service.export_replication_package(frozen.protocol_id, str(package))
    verify_replication_package(package, exported["package_manifest_sha256"])

    datasets_path = package / "datasets.json"
    datasets = json.loads(datasets_path.read_text(encoding="utf-8"))
    metadata = datasets[0]["metadata"]
    verification = metadata["ethics_condition_verification"]
    retained_discharge = metadata["ethics_condition_discharge"]
    if mutation == "receipt_status":
        verification["condition_results"][0]["compliance_status"] = "satisfied"
        verification["condition_results"][0]["valid_through"] = None
        verification["ongoing_controls_require_continued_monitoring"] = False
    elif mutation == "discharge_status":
        retained_discharge["conditions"][0]["compliance_status"] = "satisfied"
        retained_discharge["conditions"][0]["valid_through"] = None
    elif mutation == "location_check":
        verification["evidence_location_checks"][0]["evidence_location"] = "/synthetic_fixture"
    elif mutation == "monitoring_flag":
        verification["ongoing_controls_require_continued_monitoring"] = False
    datasets_path.write_text(
        json.dumps(datasets, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    commitment = _refresh_packaged_file(package, "datasets.json")

    with pytest.raises(ValidationError, match=message):
        verify_replication_package(package, commitment)
