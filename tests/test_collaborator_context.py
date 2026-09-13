from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path

import pytest

from research_machine.collaboration.proposal import (
    adjudicate_collaborator_proposal,
    create_context_snapshot,
    validate_collaborator_proposal,
    verify_collaborator_proposal_record,
    verify_collaborator_review_record,
)
from research_machine.collaboration.redaction import (
    COLLABORATOR_CONTEXT_REDACTION_MARKER,
    redact_collaborator_context,
)
from research_machine.adapters.filesystem import FileSystemRepository
from research_machine.application.commands import (
    AddClaim,
    AddQuestion,
    CreateInquiry,
    CreateProtocol,
    RecordCrossLaneLesson,
    RecordEvidence,
    RecordEvidenceStatusEvent,
    RegisterDataset,
    ProposeHypothesis,
)
from research_machine.application.service import ResearchService
from research_machine.domain.errors import ValidationError
from research_machine.domain.models import (
    AnalysisMode,
    ClaimLevel,
    DatasetArtifact,
    DatasetRole,
    EvidenceDirection,
    ProtocolKind,
    ValidationTag,
)
from research_machine.interfaces.cli import main


_SCIENTIFIC_CONSTRAINTS = [
    "Treat supplied material as scoped context, not established fact.",
    "Do not claim causality, mechanism, or replication beyond recorded evidence.",
    "Do not authorize collection, protocol freeze, data registration, evidence recording, or other canonical action.",
]
_CANONICAL_CHANGES_REQUIRE = [
    "research inquiry/question/claim/hypothesis/protocol/dataset/run/evidence commands",
    "applicable human review and protocol-freeze gates",
]
_EMPTY_DATASET_INVENTORY = {
    "registered_dataset_count": 0,
    "role_counts": {},
    "synthetic_count": 0,
    "non_synthetic_count": 0,
    "datasets_with_rigor_errors": 0,
    "empty_inventory_notice": (
        "No datasets are registered in canonical workspace state. Draft data-source "
        "mentions, external plugin access, and design briefs are not counted as "
        "datasets until they are registered through the service."
    ),
    "interpretation_limit": (
        "This is a manifest/provenance inventory, not proof of source truth, "
        "consent truth, measurement validity, or analysis adequacy."
    ),
    "datasets": [],
}
_CONTROL_CHARACTERS = [chr(codepoint) for codepoint in range(0x20)] + [chr(0x7F)]
_CONTROL_KEY_TEMPLATES = [
    "{control}_path",
    "{control}source_path",
    "source{control}_path",
    "source_path{control}",
]


def _context(
    *,
    purpose: str = "Stress-test the design.",
    context_reference_index: list[dict[str, str]] | None = None,
    scientific_constraints: list[str] | None = None,
) -> dict:
    context = {
        "context_version": 2,
        "purpose": purpose,
        "dataset_inventory": copy.deepcopy(_EMPTY_DATASET_INVENTORY),
        "scientific_constraints": list(
            _SCIENTIFIC_CONSTRAINTS
            if scientific_constraints is None
            else scientific_constraints
        ),
        "write_boundary": {
            "context_is_read_only": True,
            "provider_required": False,
            "canonical_changes_require": list(_CANONICAL_CHANGES_REQUIRE),
        },
    }
    if context_reference_index is not None:
        context["context_reference_index"] = context_reference_index
        for item in context_reference_index:
            ref = item.get("ref", "")
            kind = item.get("kind")
            if kind == "inquiry" and ref.startswith("inquiry:"):
                context["inquiry"] = {"inquiry_id": ref.removeprefix("inquiry:")}
            elif kind == "open_question" and ref.startswith("question:"):
                context.setdefault("open_questions", []).append(
                    {"question_id": ref.removeprefix("question:")}
                )
            elif kind == "claim" and ref.startswith("claim:"):
                context.setdefault("claims", []).append(
                    {"claim_id": ref.removeprefix("claim:")}
                )
            elif kind in {"active_hypothesis", "pending_hypothesis"} and ref.startswith("hypothesis:"):
                collection = (
                    "active_hypotheses"
                    if kind == "active_hypothesis"
                    else "pending_hypotheses"
                )
                context.setdefault(collection, []).append(
                    {"hypothesis_id": ref.removeprefix("hypothesis:")}
                )
            elif kind == "evidence" and ref.startswith("evidence:"):
                context.setdefault("evidence", []).append(
                    {"evidence_id": ref.removeprefix("evidence:")}
                )
            elif kind == "evidence_status_event" and ref.startswith("evidence_status_event:"):
                context.setdefault("evidence_status_events", []).append(
                    {"event_id": ref.removeprefix("evidence_status_event:")}
                )
            elif kind == "dataset" and ref.startswith("dataset:"):
                context.setdefault("datasets", []).append(
                    {"dataset_id": ref.removeprefix("dataset:")}
                )
            elif kind == "protocol" and ref.startswith("protocol:"):
                context.setdefault("protocols", []).append(
                    {"protocol_id": ref.removeprefix("protocol:")}
                )
            elif kind == "run" and ref.startswith("run:"):
                context.setdefault("runs", []).append(
                    {"run_id": ref.removeprefix("run:")}
                )
            elif kind == "ethics_review_event" and ref.startswith("ethics_review_event:"):
                context.setdefault("ethics_review_events", []).append(
                    {"event_id": ref.removeprefix("ethics_review_event:")}
                )
    return context


def _context_with_artifact_metadata(metadata: dict) -> dict:
    dataset_id = "metadata-key-fixture"
    context = _context(
        context_reference_index=[{"ref": f"dataset:{dataset_id}", "kind": "dataset"}]
    )
    context["datasets"][0]["artifacts"] = [{
        "locator": COLLABORATOR_CONTEXT_REDACTION_MARKER,
        "sha256": "a" * 64,
        "metadata": metadata,
    }]
    context["dataset_inventory"].update({
        "registered_dataset_count": 1,
        "role_counts": {"exploratory": 1},
        "synthetic_count": 1,
        "empty_inventory_notice": "",
        "datasets": [{
            "dataset_id": dataset_id,
            "role": "exploratory",
            "synthetic": True,
            "protocol_id": None,
            "observation_access": {"status": "synthetic_fixture"},
            "readiness": {"status": "not_protected_evidence_dataset"},
            "rigor_error_codes": [],
            "operational_roots_redacted": True,
        }],
    })
    return context


def test_collaborator_context_is_read_only_and_preserves_scientific_boundaries(
    tmp_path
) -> None:
    service = ResearchService(FileSystemRepository(tmp_path), actor="test")
    service.init_workspace()
    service.create_inquiry(CreateInquiry("Question", "Statement", "question"))
    service.add_question(AddQuestion("What comparison would discriminate causes?"))
    claim = service.add_claim(
        AddClaim(
            "The observed contrast is a source claim, not a causal finding.",
            ClaimLevel.STATISTICAL_ASSOCIATION,
        )
    )
    context = service.collaborator_context(purpose="Help draft a design review.")
    assert context["context_version"] == 2
    assert context["write_boundary"]["provider_required"] is False
    assert context["ethics_review_events"] == []
    assert context["write_boundary"]["context_is_read_only"] is True
    assert context["open_questions"][0]["text"].startswith("What comparison")
    assert context["claims"][0]["claim_id"] == claim.claim_id
    assert context["evidence"] == []
    assert context["datasets"] == []
    assert context["dataset_inventory"]["registered_dataset_count"] == 0
    assert "Draft data-source mentions" in context["dataset_inventory"][
        "empty_inventory_notice"
    ]
    assert context["protocols"] == []
    assert context["runs"] == []
    assert context["context_reference_index"] == [
        {"ref": f"inquiry:{context['inquiry']['inquiry_id']}", "kind": "inquiry"},
        {
            "ref": f"question:{context['open_questions'][0]['question_id']}",
            "kind": "open_question",
        },
        {"ref": f"claim:{claim.claim_id}", "kind": "claim"},
    ]
    assert any("causality" in item for item in context["scientific_constraints"])


def test_collaborator_context_includes_bounded_dataset_inventory(tmp_path) -> None:
    service = ResearchService(FileSystemRepository(tmp_path), actor="test")
    service.init_workspace()
    inquiry = service.create_inquiry(
        CreateInquiry("Dataset review", "What data are available?", "dataset")
    )
    service.register_dataset(
        RegisterDataset(
            dataset_id="context-dataset",
            name="Context dataset",
            role=DatasetRole.EXPLORATORY,
            artifacts=[
                DatasetArtifact(
                    "context.csv",
                    hashlib.sha256(b"unit,outcome\nu1,1\n").hexdigest(),
                    18,
                    "text/csv",
                )
            ],
            synthetic=True,
            quality_attestations=["Synthetic collaborator-context fixture."],
        ),
        inquiry.inquiry_id,
    )

    context = service.collaborator_context(
        inquiry.inquiry_id,
        purpose="Review dataset availability.",
    )

    assert context["datasets"][0]["dataset_id"] == "context-dataset"
    inventory = context["dataset_inventory"]
    assert inventory["registered_dataset_count"] == 1
    assert inventory["role_counts"] == {"exploratory": 1}
    row = inventory["datasets"][0]
    assert row["dataset_id"] == "context-dataset"
    assert row["observation_access"]["status"] == "synthetic_fixture"
    assert row["readiness"]["status"] == "not_protected_evidence_dataset"
    assert row["operational_roots_redacted"] is True
    assert str(tmp_path.resolve()) not in json.dumps(context)


def test_cli_absolute_dataset_file_is_redacted_but_canonical_state_is_unchanged(
    tmp_path: Path, capsys
) -> None:
    workspace = tmp_path / "workspace"
    source = tmp_path / "Users" / "alice" / "observations.csv"
    source.parent.mkdir(parents=True)
    source.write_text("unit,outcome\nu1,1\n", encoding="utf-8")
    common = ["--workspace", str(workspace), "--json"]
    assert main([*common, "workspace", "init"]) == 0
    capsys.readouterr()
    assert main([
        *common, "inquiry", "create", "--id", "path-audit",
        "--title", "Path audit", "--statement", "Can host paths stay local?",
    ]) == 0
    capsys.readouterr()
    assert main([
        *common, "dataset", "register", "--id", "absolute-file",
        "--name", "Absolute file", "--role", "exploratory", "--file", str(source),
        "--synthetic", "--quality-attestation", "Synthetic redaction fixture.",
    ]) == 0
    capsys.readouterr()
    output = tmp_path / "frozen"
    assert main([
        *common, "collaborator", "context", "--purpose", "Audit disclosure.",
        "--output", str(output),
    ]) == 0
    result = json.loads(capsys.readouterr().out)["result"]
    context = json.loads(Path(result["context_file"]).read_text(encoding="utf-8"))
    artifact = context["datasets"][0]["artifacts"][0]
    assert artifact["locator"] == COLLABORATOR_CONTEXT_REDACTION_MARKER
    assert artifact["sha256"] == hashlib.sha256(source.read_bytes()).hexdigest()
    assert artifact["size_bytes"] == source.stat().st_size
    serialized = json.dumps(context, sort_keys=True)
    assert str(source) not in serialized
    assert str(tmp_path) not in serialized
    assert "alice" not in serialized
    assert "locator" not in json.dumps(context["dataset_inventory"], sort_keys=True)
    canonical = ResearchService(FileSystemRepository(workspace), actor="test")
    assert canonical.list_datasets()[0].artifacts[0].locator == str(source.resolve())


def test_v2_dataset_locators_are_always_redacted_and_replay_stable(
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "workspace"
    service = ResearchService(
        FileSystemRepository(workspace),
        actor="test",
        clock=lambda: "2026-09-12T12:00:00Z",
    )
    service.init_workspace()
    inquiry = service.create_inquiry(
        CreateInquiry("Projection", "Which locators are safe?", "projection")
    )
    safe_file = workspace / "logical" / "safe.csv"
    safe_file.parent.mkdir()
    safe_file.write_text("safe\n", encoding="utf-8")
    outside = tmp_path / "private" / "result.csv"
    outside.parent.mkdir()
    outside.write_text("outside\n", encoding="utf-8")
    (workspace / "linked.csv").symlink_to(outside)
    artifacts = [
        DatasetArtifact("logical/safe.csv", "a" * 64, 5, "text/csv"),
        DatasetArtifact("linked.csv", "b" * 64, 8, "text/csv"),
        DatasetArtifact("../private/result.csv", "c" * 64, 11, "text/csv"),
        DatasetArtifact(
            "/Users/alice/result.csv", "d" * 64, 12, "application/json",
            {
                "artifact_role": "analysis_input",
                "hostname": "alice-macbook.local",
                "host": 0,
                "host_id": "host-42",
                "user_id": "alice",
                "root": {"kind": "local", "value": "/Users/alice"},
                "locators": ["logical/result.csv", "/Users/alice/result.csv"],
                "source_note": "copied from /Users/alice/private/result.csv",
                "drive_hint": "C:result.csv",
                "escaped_hint": "logical/%2e%2e/result.csv",
                "remote_hint": "macbook:/private/result.csv",
                "unc_hint": "\\\\server\\share\\result.csv",
                "/Users/alice/private-key": "unsafe metadata key",
                "nested": {
                    "source_path": ["/Users/alice/nested/result.csv"],
                    "location": {"host": "alice-macbook.local"},
                    "roots": [],
                    "current_synthesis_path": None,
                    "effect_estimate_path": {
                        "selector": "/results/effect/estimate",
                        "source_path": "/selector/value/is/not/a/filesystem/path",
                    },
                    "note": "X:12345",
                },
            },
        ),
        DatasetArtifact(
            "/home/bob/result.csv", "e" * 64, 13, "application/octet-stream",
            {"artifact_role": "control_input"},
        ),
        DatasetArtifact("alice-macbook.local/result.csv", "f" * 64, 14, "text/csv"),
        DatasetArtifact("Users/alice/result.csv", "1" * 64, 15, "text/csv"),
        DatasetArtifact("logical/%252e%252e/result.csv", "2" * 64, 16, "text/csv"),
    ]
    service.register_dataset(
        RegisterDataset(
            dataset_id="projection-fixture",
            name="Projection fixture",
            role=DatasetRole.EXPLORATORY,
            artifacts=artifacts,
            synthetic=True,
            quality_attestations=["Synthetic projection fixture."],
        ),
        inquiry.inquiry_id,
    )

    first = service.collaborator_context(
        inquiry.inquiry_id, purpose="Stress-test the design."
    )
    second = service.collaborator_context(
        inquiry.inquiry_id, purpose="Stress-test the design."
    )
    assert first == second
    projected = first["datasets"][0]["artifacts"]
    assert [item["locator"] for item in projected] == [
        COLLABORATOR_CONTEXT_REDACTION_MARKER
    ] * len(artifacts)
    assert [item["sha256"] for item in projected] == [item.sha256 for item in artifacts]
    assert [item["media_type"] for item in projected] == [
        item.media_type for item in artifacts
    ]
    assert [item["size_bytes"] for item in projected] == [
        item.size_bytes for item in artifacts
    ]
    assert first["datasets"][0]["role"] == "exploratory"
    assert projected[3]["metadata"]["hostname"] == COLLABORATOR_CONTEXT_REDACTION_MARKER
    assert projected[3]["metadata"]["host"] == COLLABORATOR_CONTEXT_REDACTION_MARKER
    assert projected[3]["metadata"]["host_id"] == COLLABORATOR_CONTEXT_REDACTION_MARKER
    assert projected[3]["metadata"]["user_id"] == COLLABORATOR_CONTEXT_REDACTION_MARKER
    assert projected[3]["metadata"]["root"] == COLLABORATOR_CONTEXT_REDACTION_MARKER
    assert projected[3]["metadata"]["locators"] == COLLABORATOR_CONTEXT_REDACTION_MARKER
    assert projected[3]["metadata"]["source_note"] == (
        "copied from /Users/alice/private/result.csv"
    )
    assert projected[3]["metadata"]["drive_hint"] == "C:result.csv"
    assert projected[3]["metadata"]["escaped_hint"] == "logical/%2e%2e/result.csv"
    assert projected[3]["metadata"]["remote_hint"] == "macbook:/private/result.csv"
    assert projected[3]["metadata"]["unc_hint"] == "\\\\server\\share\\result.csv"
    assert projected[3]["metadata"]["/Users/alice/private-key"] == "unsafe metadata key"
    assert projected[3]["metadata"]["nested"] == {
        "source_path": COLLABORATOR_CONTEXT_REDACTION_MARKER,
        "location": COLLABORATOR_CONTEXT_REDACTION_MARKER,
        "roots": COLLABORATOR_CONTEXT_REDACTION_MARKER,
        "current_synthesis_path": COLLABORATOR_CONTEXT_REDACTION_MARKER,
        "effect_estimate_path": {
            "selector": "/results/effect/estimate",
            "source_path": "/selector/value/is/not/a/filesystem/path",
        },
        "note": "X:12345",
    }
    assert "locator" not in json.dumps(first["dataset_inventory"], sort_keys=True)
    assert service.list_datasets(inquiry.inquiry_id)[0].artifacts == artifacts

    tampered = copy.deepcopy(first)
    tampered["datasets"][0]["artifacts"][3]["metadata"]["nested"][
        "source_path"
    ] = [COLLABORATOR_CONTEXT_REDACTION_MARKER]
    with pytest.raises(ValidationError, match="canonical scalar redaction marker"):
        create_context_snapshot(tampered, tmp_path / "tampered-context")

    artifact_extension = copy.deepcopy(first)
    artifact_extension["datasets"][0]["artifacts"][3][
        "source_path"
    ] = COLLABORATOR_CONTEXT_REDACTION_MARKER
    with pytest.raises(ValidationError, match="fields mismatch"):
        create_context_snapshot(artifact_extension, tmp_path / "artifact-extension")

    identity_tampering = copy.deepcopy(first)
    identity_tampering["datasets"][0]["artifacts"][3]["metadata"][
        "host_id"
    ] = "host-42"
    with pytest.raises(ValidationError, match="host field"):
        create_context_snapshot(identity_tampering, tmp_path / "identity-tampering")

    first_snapshot = create_context_snapshot(first, tmp_path / "context-one")
    second_snapshot = create_context_snapshot(second, tmp_path / "context-two")
    assert first_snapshot["context_sha256"] == second_snapshot["context_sha256"]
    assert Path(first_snapshot["context_file"]).read_bytes() == Path(
        second_snapshot["context_file"]
    ).read_bytes()
    proposal_file = tmp_path / "proposal.json"
    proposal_file.write_text(json.dumps(_proposal(
        first_snapshot["context_sha256"],
        evidence_refs=["dataset:projection-fixture"],
    )), encoding="utf-8")
    first_record = validate_collaborator_proposal(
        Path(first_snapshot["context_file"]), first_snapshot["context_sha256"],
        proposal_file, tmp_path / "proposal-one",
    )
    second_record = validate_collaborator_proposal(
        Path(second_snapshot["context_file"]), second_snapshot["context_sha256"],
        proposal_file, tmp_path / "proposal-two",
    )
    assert first_record["record_sha256"] == second_record["record_sha256"]
    assert Path(first_record["record_file"]).read_bytes() == Path(
        second_record["record_file"]
    ).read_bytes()
    assert verify_collaborator_proposal_record(
        Path(second_record["record_file"]), second_record["record_sha256"]
    )["record_status"] == "pending_human_review"


@pytest.mark.parametrize(
    "control",
    _CONTROL_CHARACTERS,
    ids=lambda value: f"U+{ord(value):04X}",
)
@pytest.mark.parametrize(
    "key_template",
    _CONTROL_KEY_TEMPLATES,
    ids=["minimal-leading", "leading", "embedded", "trailing"],
)
def test_v2_artifact_metadata_control_bearing_keys_fail_closed_everywhere(
    tmp_path: Path, control: str, key_template: str
) -> None:
    key = key_template.format(control=control)
    context = _context_with_artifact_metadata({key: "scientific value"})

    with pytest.raises(ValidationError, match="metadata property names"):
        redact_collaborator_context(context)
    with pytest.raises(ValidationError, match="metadata property name"):
        create_context_snapshot(context, tmp_path / "context")


def test_v2_artifact_metadata_controls_in_values_and_selectors_remain_exact(
    tmp_path: Path,
) -> None:
    scientific_value = "measurement:" + "".join(_CONTROL_CHARACTERS)
    selector = {
        "source\n_path": scientific_value,
        "pointer": "/results/effect/estimate",
    }
    context = _context_with_artifact_metadata({
        "note": scientific_value,
        "effect_estimate_path": selector,
    })

    projected = redact_collaborator_context(context)
    metadata = projected["datasets"][0]["artifacts"][0]["metadata"]
    assert metadata["note"] == scientific_value
    assert metadata["effect_estimate_path"] == selector
    create_context_snapshot(projected, tmp_path / "context")


@pytest.mark.parametrize(
    "locator",
    [
        "logical/safe.csv",
        "alice-macbook.local/result.csv",
        "Users/alice/result.csv",
        "/private/result.csv",
        "../private/result.csv",
        "C:result.csv",
        "C:/result.csv",
        "urn:artifact:result",
        "file:/private/result.csv",
        "logical/%2e%2e/result.csv",
        "logical/%252e%252e/result.csv",
        "logical/result\x1f.csv",
        "logical/result\x7f.csv",
    ],
)
def test_v2_context_freeze_rejects_unsafe_locator_tampering(
    tmp_path: Path, locator: str
) -> None:
    context = _context()
    context["datasets"] = [{
        "dataset_id": "tampered-locator",
        "artifacts": [{"locator": locator, "sha256": "a" * 64}],
    }]
    context["dataset_inventory"]["registered_dataset_count"] = 1
    context["dataset_inventory"]["synthetic_count"] = 1
    context["dataset_inventory"]["empty_inventory_notice"] = ""
    context["dataset_inventory"]["datasets"] = [{
        "dataset_id": "tampered-locator",
        "role": "exploratory",
        "synthetic": True,
        "protocol_id": None,
        "observation_access": {"status": "synthetic_fixture"},
        "readiness": {"status": "not_protected_evidence_dataset"},
        "rigor_error_codes": [],
        "operational_roots_redacted": True,
    }]
    context["dataset_inventory"]["role_counts"] = {"exploratory": 1}
    context["context_reference_index"] = [
        {"ref": "dataset:tampered-locator", "kind": "dataset"}
    ]

    with pytest.raises(ValidationError, match="dataset artifact locator"):
        create_context_snapshot(context, tmp_path / "context")


def test_v2_context_preserves_json_selectors_and_safe_relative_paths(
    tmp_path: Path,
) -> None:
    context = _context(
        context_reference_index=[{"ref": "inquiry:inq-1", "kind": "inquiry"}]
    )
    context["inquiry"]["analysis_path"] = "summaries/current.json"
    context["inquiry"]["effect_estimate_path"] = "/results/effect/estimate"
    snapshot = create_context_snapshot(context, tmp_path / "context")
    frozen = json.loads(Path(snapshot["context_file"]).read_text(encoding="utf-8"))
    assert frozen["inquiry"]["analysis_path"] == "summaries/current.json"
    assert frozen["inquiry"]["effect_estimate_path"] == "/results/effect/estimate"


@pytest.mark.parametrize(
    "path",
    [
        "alice-macbook.local/result.csv",
        "Users/alice/result.csv",
        "reports/Users/alice/result.csv",
        "logical/%252e%252e/result.csv",
    ],
)
def test_v2_context_rejects_host_platform_and_encoded_typed_paths(
    tmp_path: Path, path: str
) -> None:
    context = _context(
        context_reference_index=[{"ref": "inquiry:inq-1", "kind": "inquiry"}]
    )
    context["inquiry"]["analysis_path"] = path
    with pytest.raises(ValidationError, match="path field"):
        create_context_snapshot(context, tmp_path / "context")


def test_v2_typed_projection_preserves_colon_bearing_scientific_prose(
    tmp_path: Path,
) -> None:
    service = ResearchService(FileSystemRepository(tmp_path), actor="test")
    service.init_workspace()
    inquiry = service.create_inquiry(
        CreateInquiry(
            "X:12345",
            "Compare X:12345 with DOI:10.1000/example and ratio 1/2.",
            "typed-prose",
        )
    )
    context = service.collaborator_context(
        inquiry.inquiry_id, purpose="Review X:12345 without reinterpretation."
    )
    assert context["inquiry"]["title"] == "X:12345"
    assert context["inquiry"]["initial_statement"] == (
        "Compare X:12345 with DOI:10.1000/example and ratio 1/2."
    )
    assert context["purpose"] == "Review X:12345 without reinterpretation."
    create_context_snapshot(context, tmp_path / "context")


def test_v2_context_validation_rejects_explicit_host_identity_tampering(
    tmp_path: Path,
) -> None:
    context = _context(
        context_reference_index=[{"ref": "inquiry:inq-1", "kind": "inquiry"}]
    )
    context["inquiry"]["metadata"] = {"hostname": "alice-macbook.local"}
    with pytest.raises(ValidationError, match="host field"):
        create_context_snapshot(context, tmp_path / "context")


@pytest.mark.parametrize(
    "field",
    ["current_synthesis_path", "evidence_artifact_root", "interpreter_path"],
)
def test_v2_context_requires_new_operational_fields_to_be_redacted(
    tmp_path: Path, field: str
) -> None:
    context = _context(
        context_reference_index=[{"ref": "inquiry:inq-1", "kind": "inquiry"}]
    )
    context["inquiry"][field] = "local/relative-value"
    with pytest.raises(ValidationError, match="operational field"):
        create_context_snapshot(context, tmp_path / "context")


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        (
            lambda context: context["dataset_inventory"].update({"datasets": []}),
            "dataset_inventory must exactly cover visible dataset records",
        ),
        (
            lambda context: context["dataset_inventory"].update(
                {"registered_dataset_count": 0}
            ),
            "registered_dataset_count disagrees",
        ),
        (
            lambda context: context["dataset_inventory"]["datasets"][0].update(
                {"operational_roots_redacted": False}
            ),
            "rows must redact operational roots",
        ),
        (
            lambda context: context["dataset_inventory"].update(
                {"role_counts": {"confirmatory": 1}}
            ),
            "role_counts disagree",
        ),
    ],
)
def test_context_snapshot_replays_dataset_inventory_consistency(
    tmp_path: Path, mutation, message: str
) -> None:
    service = ResearchService(FileSystemRepository(tmp_path), actor="test")
    service.init_workspace()
    inquiry = service.create_inquiry(
        CreateInquiry("Dataset review", "What data are available?", "dataset")
    )
    service.register_dataset(
        RegisterDataset(
            dataset_id="context-dataset",
            name="Context dataset",
            role=DatasetRole.EXPLORATORY,
            artifacts=[
                DatasetArtifact(
                    "context.csv",
                    hashlib.sha256(b"unit,outcome\nu1,1\n").hexdigest(),
                    18,
                    "text/csv",
                )
            ],
            synthetic=True,
            quality_attestations=["Synthetic collaborator-context fixture."],
        ),
        inquiry.inquiry_id,
    )
    context = service.collaborator_context(
        inquiry.inquiry_id,
        purpose="Review dataset availability.",
    )
    mutation(context)

    with pytest.raises(ValidationError, match=message):
        create_context_snapshot(context, tmp_path / "context")
    assert not (tmp_path / "context").exists()


def test_collaborator_context_exposes_acquisition_timing_as_non_authority(
    tmp_path: Path,
) -> None:
    service = ResearchService(FileSystemRepository(tmp_path), actor="test")
    service.init_workspace()
    inquiry = service.create_inquiry(
        CreateInquiry("Timing review", "Can timing commitments be reviewed?", "timing")
    )
    hypothesis = service.propose_hypothesis(
        ProposeHypothesis(
            statement="The temporal ordering check is prospectively bounded.",
            observable_prediction="The registered control window remains outside the tolerated clock uncertainty.",
            null_model="Timing uncertainty is too large to order the observed events.",
            falsification_conditions=["Clock drift exceeds the registered tolerance."],
        ),
        inquiry.inquiry_id,
    )
    service.activate_hypothesis(hypothesis.hypothesis_id, inquiry.inquiry_id)
    draft = service.create_protocol(
        CreateProtocol(
            experiment_id="timing-review",
            title="Timing review protocol",
            analysis_mode=AnalysisMode.CONFIRMATORY,
            hypotheses_tested=[hypothesis.hypothesis_id],
            primary_outcome="Temporal order classification",
            protocol_kind=ProtocolKind.FORMAL,
            methodology="Review the registered timing commitments before analysis.",
            quality_requirements=["timing-review"],
            controls=["Random-time control window"],
            expected_outputs=["Timing review memo"],
            success_conditions=["Report whether the timing plan is reviewable."],
            environment_requirements=["Pinned review fixture"],
            sample_size_or_stopping_rule="One frozen timing review.",
            sensor_requirements=["audio recorder at 48 kHz", "event marker stream"],
            clock_accuracy_requirement="Clock drift remains below 10 ms.",
            control_windows=["pre-event baseline", "random-time control"],
            failure_conditions=["Clock uncertainty exceeds the registered lag window."],
            safety_constraints=["No physical intervention."],
            analysis_code_hash="a" * 64,
        ),
        inquiry.inquiry_id,
    )
    protocol = service.freeze_protocol(draft.protocol_id, inquiry.inquiry_id)

    context = service.collaborator_context(
        inquiry.inquiry_id, purpose="Review acquisition timing boundaries."
    )

    assert any(
        "not proof of custody, calibration, synchronization, or timing validity" in item
        for item in context["scientific_constraints"]
    )
    assert context["protocols"][0]["protocol_id"] == protocol.protocol_id
    assert context["protocols"][0]["sensor_requirements"] == [
        "audio recorder at 48 kHz",
        "event marker stream",
    ]
    assert (
        context["protocols"][0]["clock_accuracy_requirement"]
        == "Clock drift remains below 10 ms."
    )
    assert context["protocols"][0]["control_windows"] == [
        "pre-event baseline",
        "random-time control",
    ]
    assert {
        "ref": f"protocol:{protocol.protocol_id}",
        "kind": "protocol",
    } in context["context_reference_index"]

    snapshot = create_context_snapshot(context, tmp_path / "context")
    frozen = json.loads(
        Path(snapshot["context_file"]).read_text(encoding="utf-8")
    )
    assert frozen["protocols"][0]["control_windows"] == [
        "pre-event baseline",
        "random-time control",
    ]


def test_proposal_can_cite_body_backed_evidence_status_event(
    tmp_path: Path,
) -> None:
    context = _context(
        context_reference_index=[
            {
                "ref": "evidence_status_event:evidence-status-1",
                "kind": "evidence_status_event",
            }
        ]
    )
    snapshot = create_context_snapshot(context, tmp_path / "context")
    proposal = _proposal(
        snapshot["context_sha256"],
        evidence_refs=["evidence_status_event:evidence-status-1"],
    )
    proposal_path = tmp_path / "proposal.json"
    proposal_path.write_text(json.dumps(proposal), encoding="utf-8")

    validated = validate_collaborator_proposal(
        Path(snapshot["context_file"]),
        snapshot["context_sha256"],
        proposal_path,
        tmp_path / "validated",
    )
    record = json.loads(Path(validated["record_file"]).read_text(encoding="utf-8"))
    assert record["proposal"]["suggestions"][0]["evidence_refs"] == [
        "evidence_status_event:evidence-status-1"
    ]


def test_context_snapshot_rejects_index_without_visible_body_record(
    tmp_path: Path,
) -> None:
    context = _context()
    context["context_reference_index"] = [
        {"ref": "claim:claim-1", "kind": "claim"}
    ]

    with pytest.raises(ValidationError, match="absent from the frozen context body"):
        create_context_snapshot(context, tmp_path / "context")
    assert not (tmp_path / "context").exists()


def test_context_snapshot_rejects_visible_body_record_missing_from_index(
    tmp_path: Path,
) -> None:
    context = _context()
    context["claims"] = [{"claim_id": "claim-1"}]
    context["context_reference_index"] = []

    with pytest.raises(ValidationError, match="missing from context_reference_index"):
        create_context_snapshot(context, tmp_path / "context")
    assert not (tmp_path / "context").exists()


def test_context_snapshot_rejects_duplicate_visible_body_reference(
    tmp_path: Path,
) -> None:
    context = _context(
        context_reference_index=[{"ref": "claim:claim-1", "kind": "claim"}]
    )
    context["claims"].append({"claim_id": "claim-1"})

    with pytest.raises(
        ValidationError,
        match="duplicate citable record: claim:claim-1",
    ):
        create_context_snapshot(context, tmp_path / "context")
    assert not (tmp_path / "context").exists()


def test_context_snapshot_rejects_duplicate_hypothesis_across_review_lanes(
    tmp_path: Path,
) -> None:
    context = _context(
        context_reference_index=[
            {"ref": "hypothesis:hypothesis-1", "kind": "active_hypothesis"}
        ]
    )
    context["pending_hypotheses"] = [{"hypothesis_id": "hypothesis-1"}]

    with pytest.raises(
        ValidationError,
        match="duplicate citable record: hypothesis:hypothesis-1",
    ):
        create_context_snapshot(context, tmp_path / "context")
    assert not (tmp_path / "context").exists()


def test_collaborator_context_purpose_must_be_canonical(tmp_path: Path) -> None:
    service = ResearchService(FileSystemRepository(tmp_path), actor="test")
    service.init_workspace()
    service.create_inquiry(CreateInquiry("Question", "Statement", "question"))

    with pytest.raises(ValidationError, match="purpose must be canonical"):
        service.collaborator_context(purpose=" design review ")
    with pytest.raises(ValidationError, match="purpose must not be empty"):
        service.collaborator_context(purpose="")


def test_collaborator_context_redacts_operational_review_roots(
    tmp_path: Path,
) -> None:
    service = ResearchService(
        FileSystemRepository(tmp_path / "workspace"),
        actor="test",
        clock=lambda: "2026-09-02T12:00:00Z",
    )
    service.init_workspace()
    service.create_inquiry(CreateInquiry("Question", "Statement", "question"))
    hypothesis = service.propose_hypothesis(
        ProposeHypothesis(
            statement="The exploratory source contains a signal.",
            observable_prediction="The source audit can inspect the signal.",
            null_model="The source audit is inconclusive.",
            falsification_conditions=["The source audit contradicts the signal."],
        )
    )
    service.activate_hypothesis(hypothesis.hypothesis_id)
    dataset = service.register_dataset(
        RegisterDataset(
            name="Exploratory fixture",
            role=DatasetRole.EXPLORATORY,
            artifacts=[DatasetArtifact("source.json", "d" * 64)],
            synthetic=True,
            quality_attestations=["Synthetic collaborator-context fixture."],
        )
    )
    evidence = service.record_evidence(
        RecordEvidence(
            hypothesis_id=hypothesis.hypothesis_id,
            direction=EvidenceDirection.INCONCLUSIVE,
            summary="The source audit is retained only as exploratory context.",
            analysis_id="source-audit-1",
            dataset_id=dataset.dataset_id,
            uncertainty="Synthetic fixture; no scientific conclusion.",
            scope="Exploratory source-audit fixture only.",
            controls_passed=["Schema shape was inspected."],
            higher_level_conclusions_unsupported=[
                "The signal is real.",
                "The result is replicated.",
            ],
            validation_tags=[ValidationTag.SOURCE_ASSESSMENT],
            exploratory=True,
        )
    )
    review_root = tmp_path / "private-review"
    review_root.mkdir()
    review_artifact = review_root / "qualified.txt"
    review_artifact.write_text("qualified review", encoding="utf-8")
    event = service.record_evidence_status_event(
        RecordEvidenceStatusEvent(
            evidence_id=evidence.evidence_id,
            status="qualified",
            effective_at="2026-09-02T12:00:00Z",
            reason="Independent review qualified the exploratory source audit.",
            review_artifact_locator=review_artifact.name,
            review_artifact_sha256=hashlib.sha256(
                review_artifact.read_bytes()
            ).hexdigest(),
            review_artifact_root=str(review_root),
        )
    )

    context = service.collaborator_context(
        purpose="Review the qualified source audit."
    )

    assert context["evidence_status_events"][0]["event_id"] == event.event_id
    assert context["evidence_status_events"][0]["review_artifact_sha256"] == (
        event.review_artifact_sha256
    )
    assert context["evidence_status_events"][0]["review_artifact_root"] == (
        "[redacted: retained in canonical store]"
    )
    assert str(review_root) not in json.dumps(context)
    assert {
        "ref": f"evidence_status_event:{event.event_id}",
        "kind": "evidence_status_event",
    } in context["context_reference_index"]
    assert service.show_inquiry()["evidence_status_events"][0][
        "review_artifact_root"
    ] == str(review_root.resolve())


def test_collaborator_context_redacts_cross_lane_origin_artifact_root(
    tmp_path: Path,
) -> None:
    service = ResearchService(FileSystemRepository(tmp_path), actor="test")
    service.init_workspace()
    service.create_inquiry(
        CreateInquiry("Process lesson", "Can a process lesson stay bounded?", "lesson")
    )
    artifact_root = tmp_path / "lesson-origin"
    artifact = artifact_root / "results" / "run.json"
    artifact.parent.mkdir(parents=True)
    artifact.write_text('{"status":"failed"}\n', encoding="utf-8")
    digest = hashlib.sha256(artifact.read_bytes()).hexdigest()
    lesson = service.record_cross_lane_lesson(
        RecordCrossLaneLesson(
            origin_lane_id="science",
            target_lane_ids=["machine"],
            origin_artifact_locator="results/run.json",
            origin_artifact_sha256=digest,
            origin_integrity_status="verified_local",
            observation="A fixture failure exposed a missing gate.",
            failure_class="machine_failure",
            strongest_alternative_explanation="The fixture data may be incomplete.",
            challenged_invariant="Every exposed failure has a retained origin.",
            first_permitted_future_versions=["machine-v2"],
            prohibited_retroactive_targets=["machine-v1"],
            proposed_repair="Require a retained local origin receipt.",
            repair_falsifier="A local-origin lesson can be recorded without bytes.",
            conclusion_ceiling="Process lesson only.",
            origin_artifact_root=str(artifact_root),
        )
    )

    context = service.collaborator_context(
        purpose="Review the process lesson."
    )

    assert context["cross_lane_lessons"][0]["lesson_id"] == lesson.lesson_id
    assert context["cross_lane_lessons"][0]["origin_artifact_root"] == (
        "[redacted: retained in canonical store]"
    )
    assert context["cross_lane_lessons"][0]["origin_artifact_integrity"][
        "status"
    ] == "passed"
    assert str(artifact_root) not in json.dumps(context)
    assert service.show_inquiry()["cross_lane_lessons"][0][
        "origin_artifact_root"
    ] == str(artifact_root.resolve())


@pytest.mark.parametrize(
    "root_value",
    [
        "/private/review-root",
        "[redacted: /private/review-root]",
    ],
)
def test_context_snapshot_rejects_unredacted_operational_roots(
    tmp_path: Path, root_value: str,
) -> None:
    context = _context(
        context_reference_index=[
            {
                "ref": "evidence_status_event:evidence-status-1",
                "kind": "evidence_status_event",
            }
        ]
    )
    context["evidence_status_events"][0][
        "review_artifact_root"
    ] = root_value

    with pytest.raises(
        ValidationError,
        match=(
            "context.evidence_status_events\\[0\\].review_artifact_root "
            "must use the canonical redaction marker"
        ),
    ):
        create_context_snapshot(context, tmp_path / "context")
    assert not (tmp_path / "context").exists()


def test_collaborator_context_exposes_pending_review_hypotheses(
    tmp_path: Path,
) -> None:
    service = ResearchService(FileSystemRepository(tmp_path), actor="test")
    service.init_workspace()
    service.create_inquiry(CreateInquiry("Question", "Statement", "question"))
    hypothesis = service.propose_hypothesis(
        ProposeHypothesis(
            statement="A pending proposal needs review before confirmation.",
            observable_prediction="A reviewer can inspect a bounded prediction.",
            null_model="The bounded prediction does not hold.",
            falsification_conditions=["The registered observation is absent."],
        )
    )
    staged = service.stage_hypothesis(
        hypothesis.hypothesis_id,
        rationale="The proposal is complete but still needs human review.",
        confidence="high",
    )

    context = service.collaborator_context(purpose="Stress-test the design.")

    assert context["active_hypotheses"] == []
    assert context["pending_hypotheses"][0]["hypothesis_id"] == staged.hypothesis_id
    assert context["pending_hypotheses"][0]["workflow_state"] == "pending_review"
    assert {
        "ref": f"hypothesis:{staged.hypothesis_id}",
        "kind": "pending_hypothesis",
    } in context["context_reference_index"]
    context_result = create_context_snapshot(context, tmp_path / "context")
    proposal_path = tmp_path / "proposal.json"
    proposal_path.write_text(
        json.dumps(
            _proposal(
                context_result["context_sha256"],
                evidence_refs=[f"hypothesis:{staged.hypothesis_id}"],
            )
        ),
        encoding="utf-8",
    )
    result = validate_collaborator_proposal(
        Path(context_result["context_file"]),
        context_result["context_sha256"],
        proposal_path,
        tmp_path / "validated",
    )
    record = json.loads(Path(result["record_file"]).read_text(encoding="utf-8"))
    assert record["proposal"]["suggestions"][0]["evidence_refs"] == [
        f"hypothesis:{staged.hypothesis_id}"
    ]


def test_context_snapshot_purpose_must_be_canonical(tmp_path: Path) -> None:
    context = _context(purpose=" Stress-test the design. ")

    with pytest.raises(ValidationError, match="context purpose must be canonical"):
        create_context_snapshot(context, tmp_path / "context")
    assert not (tmp_path / "context").exists()


def test_context_snapshot_purpose_must_be_non_empty(tmp_path: Path) -> None:
    context = _context(purpose="")

    with pytest.raises(ValidationError, match="context purpose must be non-empty"):
        create_context_snapshot(context, tmp_path / "context")
    assert not (tmp_path / "context").exists()


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        (
            lambda context: context["write_boundary"].pop(
                "canonical_changes_require"
            ),
            "missing fields: canonical_changes_require",
        ),
        (
            lambda context: context["write_boundary"].update(
                {"model_provider": "hosted"}
            ),
            "unknown fields: model_provider",
        ),
        (
            lambda context: context["write_boundary"].update(
                {"canonical_changes_require": [" research commands "]}
            ),
            "canonical_changes_require must be canonical",
        ),
        (
            lambda context: context["write_boundary"].update(
                {"canonical_changes_require": ["Use the app to edit directly."]}
            ),
            "canonical research commands",
        ),
        (
            lambda context: context["write_boundary"].update(
                {"canonical_changes_require": ["Use research commands."]}
            ),
            "review gates",
        ),
    ],
)
def test_context_snapshot_write_boundary_must_be_exact(
    tmp_path: Path, mutation, message: str
) -> None:
    context = _context()
    mutation(context)

    with pytest.raises(ValidationError, match=message):
        create_context_snapshot(context, tmp_path / "context")
    assert not (tmp_path / "context").exists()


@pytest.mark.parametrize(
    ("context", "message"),
    [
        (
            {
                key: value
                for key, value in _context().items()
                if key != "scientific_constraints"
            },
            "scientific_constraints",
        ),
        (
            _context(scientific_constraints=[]),
            "scientific_constraints must be a non-empty",
        ),
        (
            _context(
                scientific_constraints=[
                    "Do not authorize collection, protocol freeze, data registration, evidence recording, or other canonical action."
                ]
            ),
            "inferential-boundary",
        ),
        (
            _context(
                scientific_constraints=[
                    "Do not claim causality, mechanism, or replication beyond recorded evidence."
                ]
            ),
            "authorization-boundary",
        ),
        (
            _context(
                scientific_constraints=[
                    "You may claim causality, mechanism, and replication when the proposal sounds plausible.",
                    "Do not authorize collection, protocol freeze, data registration, evidence recording, or other canonical action.",
                ]
            ),
            "inferential-boundary",
        ),
        (
            _context(
                scientific_constraints=[
                    "Do not claim causality, mechanism, or replication beyond recorded evidence.",
                    "You may authorize collection, protocol freeze, data registration, and evidence recording after review.",
                ]
            ),
            "authorization-boundary",
        ),
    ],
)
def test_context_snapshot_requires_scientific_constraints(
    tmp_path: Path, context: dict, message: str
) -> None:
    with pytest.raises(ValidationError, match=message):
        create_context_snapshot(context, tmp_path / "context")
    assert not (tmp_path / "context").exists()


def _grounded(value: str, refs: list[str]) -> dict:
    return {"statement": value, "context_refs": refs}


def _proposal(context_sha256: str, *, evidence_refs: list[str] | None = None) -> dict:
    if evidence_refs is None:
        evidence_refs = []
    competing_explanations: list[str | dict[str, list[str] | str]]
    disconfirming_evidence: list[str | dict[str, list[str] | str]]
    limitations: list[str | dict[str, list[str] | str]]
    if evidence_refs:
        competing_explanations = [
            _grounded(
                "Selection into exposure groups could create the contrast.",
                evidence_refs,
            ),
            _grounded(
                "Differential measurement error could create the contrast.",
                evidence_refs,
            ),
        ]
        disconfirming_evidence = [
            _grounded(
                "A negative-control outcome showing the same contrast would weaken the claim.",
                evidence_refs,
            )
        ]
        limitations = [
            _grounded("This review used only the frozen context payload.", evidence_refs)
        ]
    else:
        competing_explanations = [
            "Selection into exposure groups could create the contrast.",
            "Differential measurement error could create the contrast.",
        ]
        disconfirming_evidence = [
            "A negative-control outcome showing the same contrast would weaken the claim."
        ]
        limitations = ["This review used only the frozen context payload."]
    return {
        "proposal_version": 1,
        "proposal_id": "proposal-1",
        "context_sha256": context_sha256,
        "generated_by": {
            "kind": "llm",
            "provider": "local-runtime",
            "model": "research-helper",
        },
        "purpose": "Stress-test the design.",
        "summary": "The observed contrast may not identify the proposed cause.",
        "uncertainty": "No data or protocol details establish effect identification.",
        "competing_explanations": competing_explanations,
        "disconfirming_evidence": disconfirming_evidence,
        "limitations": limitations,
        "suggestions": [
            {
                "suggestion_id": "suggestion-1",
                "kind": "design_revision",
                "statement": "Add a prespecified negative-control outcome.",
                "rationale": "It probes residual selection and measurement structure.",
                "uncertainty": "A null control result would not eliminate all confounding.",
                "evidence_refs": evidence_refs,
                "falsification_conditions": [
                    "The negative-control outcome exhibits the predicted primary contrast."
                ],
                "next_test": "Review whether the control is causally insulated from exposure.",
                "authority": "review_only",
            }
        ],
    }


def test_historical_version_1_context_replays_without_dataset_inventory(
    tmp_path: Path,
) -> None:
    fixture = (
        Path(__file__).parent
        / "fixtures"
        / "collaborator-context-v1.json"
    )
    context = json.loads(fixture.read_text(encoding="utf-8"))
    assert context["context_version"] == 1
    assert "dataset_inventory" not in context

    snapshot = create_context_snapshot(context, tmp_path / "context")
    proposal = _proposal(
        snapshot["context_sha256"], evidence_refs=["inquiry:inq-1"]
    )
    proposal_file = tmp_path / "proposal.json"
    proposal_file.write_text(json.dumps(proposal), encoding="utf-8")
    result = validate_collaborator_proposal(
        Path(snapshot["context_file"]),
        snapshot["context_sha256"],
        proposal_file,
        tmp_path / "validated",
    )

    assert result["status"] == "pending_human_review"
    assert result["canonical_writes_performed"] is False


def test_historical_v1_replays_local_locator_bytes_without_retroactive_rewrite(
    tmp_path: Path,
) -> None:
    fixture = Path(__file__).parent / "fixtures" / "collaborator-context-v1.json"
    historical = json.loads(fixture.read_text(encoding="utf-8"))
    historical["datasets"] = [{
        "dataset_id": "legacy-local-locator",
        "artifacts": [{
            "locator": "/Users/historical-user/archive/result.csv",
            "sha256": "a" * 64,
        }],
    }]
    historical["context_reference_index"].append(
        {"ref": "dataset:legacy-local-locator", "kind": "dataset"}
    )

    snapshot = create_context_snapshot(historical, tmp_path / "historical-context")
    assert json.loads(Path(snapshot["context_file"]).read_text(encoding="utf-8")) == historical


def test_context_versions_fail_closed_across_dataset_inventory_boundary(
    tmp_path: Path,
) -> None:
    current = _context()
    current.pop("dataset_inventory")
    with pytest.raises(
        ValidationError,
        match="context_version 2 requires dataset_inventory",
    ):
        create_context_snapshot(current, tmp_path / "missing-current-inventory")

    historical = json.loads(
        (Path(__file__).parent / "fixtures" / "collaborator-context-v1.json").read_text(
            encoding="utf-8"
        )
    )
    historical["dataset_inventory"] = copy.deepcopy(_EMPTY_DATASET_INVENTORY)
    with pytest.raises(
        ValidationError,
        match="context_version 1 must not include dataset_inventory",
    ):
        create_context_snapshot(historical, tmp_path / "invented-legacy-inventory")


@pytest.mark.parametrize("invalid_version", [True, 0, 3, "2"])
def test_context_snapshot_rejects_unsupported_context_versions(
    tmp_path: Path, invalid_version: object
) -> None:
    context = _context()
    context["context_version"] = invalid_version
    with pytest.raises(
        ValidationError,
        match="collaborator context_version must be 1 or 2",
    ):
        create_context_snapshot(context, tmp_path / "context")


def _review(proposal_record_sha256: str) -> dict:
    return {
        "review_version": 1,
        "review_id": "review-1",
        "proposal_record_sha256": proposal_record_sha256,
        "reviewer": {"reviewer_id": "researcher-1", "role": "principal investigator"},
        "reviewed_at": "2026-09-06T12:00:00Z",
        "overall_assessment": "Advance the control idea for ordinary design review.",
        "decisions": [
            {
                "suggestion_id": "suggestion-1",
                "disposition": "advance_to_domain_review",
                "rationale": "The proposed control could discriminate an alternative explanation.",
                "domain_route": "design.revise",
            }
        ],
    }


def _canonical_json_sha256(value: dict) -> str:
    return hashlib.sha256(
        json.dumps(
            value, sort_keys=True, separators=(",", ":"), ensure_ascii=False
        ).encode("utf-8")
    ).hexdigest()


def _proposal_body_grounding(proposal: dict) -> list[dict]:
    result = []
    for section in ("competing_explanations", "disconfirming_evidence", "limitations"):
        for item in proposal[section]:
            if isinstance(item, dict):
                statement = item["statement"]
                refs = item["context_refs"]
            else:
                statement = item
                refs = []
            result.append(
                {
                    "section": section,
                    "statement_sha256": hashlib.sha256(
                        statement.encode("utf-8")
                    ).hexdigest(),
                    "context_refs": refs,
                }
            )
    return result


def _pad_retained_suggestion_statement(record: dict) -> None:
    suggestion = record["reviewed_suggestions"][0]["suggestion"]
    suggestion["statement"] = " Add a prespecified negative-control outcome. "
    record["reviewed_suggestions"][0]["suggestion_sha256"] = _canonical_json_sha256(
        suggestion
    )


def test_context_snapshot_and_proposal_are_write_once_and_noncanonical(
    tmp_path: Path,
) -> None:
    repository = FileSystemRepository(tmp_path / "workspace")
    service = ResearchService(repository, actor="test")
    service.init_workspace()
    inquiry = service.create_inquiry(
        CreateInquiry("Question", "Can exposure cause outcome?", "question")
    )
    service.add_question(
        AddQuestion("Which design change would best test the alternative explanation?"),
        inquiry.inquiry_id,
    )
    claim = service.add_claim(
        AddClaim(
            "The current comparison is associational until a causal protocol is frozen.",
            ClaimLevel.STATISTICAL_ASSOCIATION,
        ),
        inquiry.inquiry_id,
    )
    before = service.show_inquiry(inquiry.inquiry_id)

    context_result = create_context_snapshot(
        service.collaborator_context(inquiry.inquiry_id, purpose="Stress-test the design."),
        tmp_path / "context",
    )
    context = json.loads(Path(context_result["context_file"]).read_text(encoding="utf-8"))
    cited_refs = [
        item["ref"]
        for item in context["context_reference_index"]
        if item["ref"] in {
            f"question:{context['open_questions'][0]['question_id']}",
            f"claim:{claim.claim_id}",
        }
    ]
    proposal_path = tmp_path / "proposal.json"
    proposal_path.write_text(
        json.dumps(_proposal(context_result["context_sha256"], evidence_refs=cited_refs)),
        encoding="utf-8",
    )
    result = validate_collaborator_proposal(
        Path(context_result["context_file"]),
        context_result["context_sha256"],
        proposal_path,
        tmp_path / "validated",
    )

    record = json.loads(Path(result["record_file"]).read_text(encoding="utf-8"))
    assert record["status"] == "pending_human_review"
    assert record["context_reference_index"] == context["context_reference_index"]
    assert record["context_scientific_constraints"] == context["scientific_constraints"]
    assert record["context_write_boundary"] == context["write_boundary"]
    assert record["proposal_body_grounding"] == _proposal_body_grounding(
        record["proposal"]
    )
    assert record["proposal_payload_sha256"] == _canonical_json_sha256(
        record["proposal"]
    )
    assert record["proposal"]["suggestions"][0]["evidence_refs"] == cited_refs
    assert record["canonical_writes_performed"] is False
    assert record["model_invoked_by_faraday"] is False
    assert record["scientific_evidence_eligible"] is False
    assert record["authorized_actions"] == []
    verified = verify_collaborator_proposal_record(
        Path(result["record_file"]),
        result["record_sha256"],
    )
    assert verified == {
        "record_sha256": result["record_sha256"],
        "record_status": "pending_human_review",
        "context_sha256": context_result["context_sha256"],
        "proposal_sha256": result["proposal_sha256"],
        "proposal_id": "proposal-1",
        "suggestion_count": 1,
        "body_grounding_count": 4,
        "context_reference_replay": "retained_index_verified",
        "context_write_boundary_replay": "verified",
        "proposal_payload_replay": "verified",
        "canonical_writes_performed": False,
        "model_invoked_by_faraday": False,
        "scientific_evidence_eligible": False,
    }
    assert service.show_inquiry(inquiry.inquiry_id) == before
    with pytest.raises(ValidationError, match="already exists"):
        validate_collaborator_proposal(
            Path(context_result["context_file"]),
            context_result["context_sha256"],
            proposal_path,
            tmp_path / "validated",
        )


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        (
            lambda proposal: proposal["suggestions"][0].update(
                {"authority": "canonical_write"}
            ),
            "authority must be review_only",
        ),
        (
            lambda proposal: proposal.update({"disconfirming_evidence": []}),
            "disconfirming_evidence must be a non-empty",
        ),
        (
            lambda proposal: proposal["suggestions"][0].update(
                {"falsification_conditions": []}
            ),
            "falsification_conditions must be a non-empty",
        ),
        (
            lambda proposal: proposal["suggestions"][0].update(
                {
                    "falsification_conditions": [
                        "This proves the suggested mechanism."
                    ]
                }
            ),
            "falsification_conditions item must not claim acceptance",
        ),
        (
            lambda proposal: proposal["suggestions"][0].update(
                {"evidence_refs": ["evidence:not-in-context"]}
            ),
            "evidence_refs are not present in the frozen context",
        ),
        (
            lambda proposal: proposal["suggestions"][0].update(
                {"evidence_refs": ["claim:claim-1", " claim:claim-1 "]}
            ),
            "evidence_refs must be canonical",
        ),
        (
            lambda proposal: proposal.update(
                {"summary": " The observed contrast may not identify the proposed cause. "}
            ),
            "summary must be canonical",
        ),
        (
            lambda proposal: proposal.update(
                {"summary": "This proposal confirms the result."}
            ),
            "summary must not claim acceptance",
        ),
        (
            lambda proposal: proposal.update(
                {"summary": "This proposal is human-reviewed and ready for use."}
            ),
            "summary must not claim acceptance",
        ),
        (
            lambda proposal: proposal["competing_explanations"][0].update(
                {"statement": "This validates the favored mechanism."}
            ),
            "competing_explanations\\[0\\].statement must not claim acceptance",
        ),
        (
            lambda proposal: proposal["suggestions"][0].update(
                {"statement": " Add a prespecified negative-control outcome. "}
            ),
            "statement must be canonical",
        ),
        (
            lambda proposal: proposal["suggestions"][0].update(
                {"rationale": "This proposal authorizes evidence creation."}
            ),
            "rationale must not claim acceptance",
        ),
        (
            lambda proposal: proposal["suggestions"][0].update(
                {"next_test": " Review whether the control is causally insulated from exposure. "}
            ),
            "next_test must be canonical",
        ),
    ],
)
def test_proposal_fails_closed_on_missing_scientific_boundaries(
    tmp_path: Path, mutation, message: str
) -> None:
    context = _context(
        context_reference_index=[{"ref": "claim:claim-1", "kind": "claim"}]
    )
    snapshot = create_context_snapshot(context, tmp_path / "context")
    proposal = _proposal(
        snapshot["context_sha256"],
        evidence_refs=["claim:claim-1"],
    )
    mutation(proposal)
    proposal_path = tmp_path / "proposal.json"
    proposal_path.write_text(json.dumps(proposal), encoding="utf-8")
    with pytest.raises(ValidationError, match=message):
        validate_collaborator_proposal(
            Path(snapshot["context_file"]),
            snapshot["context_sha256"],
            proposal_path,
            tmp_path / "validated",
        )
    assert not (tmp_path / "validated").exists()


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        (
            lambda record: record.update({"canonical_writes_performed": True}),
            "authority boundary",
        ),
        (
            lambda record: record["proposal"].update({"context_sha256": "0" * 64}),
            "not bound to the exact context hash",
        ),
        (
            lambda record: record["proposal"]["suggestions"][0].update(
                {"authority": "canonical_write"}
            ),
            "authority must be review_only",
        ),
        (
            lambda record: record["proposal_body_grounding"][0].update(
                {"context_refs": ["claim:not-in-context"]}
            ),
            "body grounding disagrees",
        ),
        (
            lambda record: record["proposal"]["suggestions"][0].update(
                {"evidence_refs": ["claim:not-in-context"]}
            ),
            "evidence_refs are not present",
        ),
        (
            lambda record: record["proposal"].update(
                {"summary": "This proposal proves the finding."}
            ),
            "summary must not claim acceptance",
        ),
        (
            lambda record: record.update(
                {
                    "context_scientific_constraints": [
                        "Do not authorize collection, protocol freeze, data registration, evidence recording, or other canonical action."
                    ]
                }
            ),
            "inferential-boundary",
        ),
        (
            lambda record: record["context_write_boundary"].update(
                {"canonical_changes_require": []}
            ),
            "canonical_changes_require must be a non-empty",
        ),
        (
            lambda record: record["context_write_boundary"].update(
                {"provider_required": True}
            ),
            "must not require a provider",
        ),
        (
            lambda record: record.update(
                {"conclusion_ceiling": "This proposal authorizes protocol changes."}
            ),
            "conclusion ceiling has changed",
        ),
    ],
)
def test_verify_collaborator_proposal_record_replays_retained_boundaries(
    tmp_path: Path, mutation, message: str
) -> None:
    context = _context(
        context_reference_index=[{"ref": "claim:claim-1", "kind": "claim"}]
    )
    snapshot = create_context_snapshot(context, tmp_path / "context")
    proposal_path = tmp_path / "proposal.json"
    proposal_path.write_text(
        json.dumps(
            _proposal(
                snapshot["context_sha256"],
                evidence_refs=["claim:claim-1"],
            )
        ),
        encoding="utf-8",
    )
    validated = validate_collaborator_proposal(
        Path(snapshot["context_file"]),
        snapshot["context_sha256"],
        proposal_path,
        tmp_path / "validated",
    )
    record_path = Path(validated["record_file"])
    record = json.loads(record_path.read_text(encoding="utf-8"))
    mutation(record)
    record_path.write_text(
        json.dumps(record, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    trusted_hash = hashlib.sha256(record_path.read_bytes()).hexdigest()

    with pytest.raises(ValidationError, match=message):
        verify_collaborator_proposal_record(record_path, trusted_hash)


def test_verify_collaborator_proposal_record_replays_embedded_proposal_payload(
    tmp_path: Path,
) -> None:
    context = _context()
    snapshot = create_context_snapshot(context, tmp_path / "context")
    proposal_path = tmp_path / "proposal.json"
    proposal_path.write_text(
        json.dumps(_proposal(snapshot["context_sha256"])), encoding="utf-8"
    )
    validated = validate_collaborator_proposal(
        Path(snapshot["context_file"]),
        snapshot["context_sha256"],
        proposal_path,
        tmp_path / "validated",
    )
    record_path = Path(validated["record_file"])
    record = json.loads(record_path.read_text(encoding="utf-8"))
    record["proposal"]["summary"] = "The contrast may reflect unresolved selection."
    record_path.write_text(
        json.dumps(record, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    trusted_hash = hashlib.sha256(record_path.read_bytes()).hexdigest()

    with pytest.raises(ValidationError, match="proposal_payload_sha256"):
        verify_collaborator_proposal_record(record_path, trusted_hash)


def test_proposal_requires_a_citation_when_context_has_references(
    tmp_path: Path,
) -> None:
    context = _context(
        context_reference_index=[{"ref": "claim:claim-1", "kind": "claim"}]
    )
    snapshot = create_context_snapshot(context, tmp_path / "context")
    proposal = _proposal(
        snapshot["context_sha256"],
        evidence_refs=["claim:claim-1"],
    )
    proposal["suggestions"][0]["evidence_refs"] = []
    proposal_path = tmp_path / "proposal.json"
    proposal_path.write_text(json.dumps(proposal), encoding="utf-8")

    with pytest.raises(ValidationError, match="evidence_refs must be a non-empty"):
        validate_collaborator_proposal(
            Path(snapshot["context_file"]),
            snapshot["context_sha256"],
            proposal_path,
            tmp_path / "validated",
        )
    assert not (tmp_path / "validated").exists()


def test_proposal_requires_grounded_body_claims_when_context_has_references(
    tmp_path: Path,
) -> None:
    context = _context(
        context_reference_index=[{"ref": "claim:claim-1", "kind": "claim"}]
    )
    snapshot = create_context_snapshot(context, tmp_path / "context")
    proposal = _proposal(
        snapshot["context_sha256"],
        evidence_refs=["claim:claim-1"],
    )
    proposal["competing_explanations"] = [
        "Selection into exposure groups could create the contrast."
    ]
    proposal_path = tmp_path / "proposal.json"
    proposal_path.write_text(json.dumps(proposal), encoding="utf-8")

    with pytest.raises(ValidationError, match="must cite frozen context"):
        validate_collaborator_proposal(
            Path(snapshot["context_file"]),
            snapshot["context_sha256"],
            proposal_path,
            tmp_path / "validated",
        )
    assert not (tmp_path / "validated").exists()


def test_proposal_rejects_body_grounding_outside_frozen_context(
    tmp_path: Path,
) -> None:
    context = _context(
        context_reference_index=[{"ref": "claim:claim-1", "kind": "claim"}]
    )
    snapshot = create_context_snapshot(context, tmp_path / "context")
    proposal = _proposal(
        snapshot["context_sha256"],
        evidence_refs=["claim:claim-1"],
    )
    proposal["limitations"][0]["context_refs"] = ["claim:not-in-context"]
    proposal_path = tmp_path / "proposal.json"
    proposal_path.write_text(json.dumps(proposal), encoding="utf-8")

    with pytest.raises(ValidationError, match="references are not present"):
        validate_collaborator_proposal(
            Path(snapshot["context_file"]),
            snapshot["context_sha256"],
            proposal_path,
            tmp_path / "validated",
        )
    assert not (tmp_path / "validated").exists()


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        (
            lambda review: review.update(
                {"overall_assessment": " Advance the control idea for ordinary design review. "}
            ),
            "overall_assessment must be canonical",
        ),
        (
            lambda review: review["decisions"][0].update(
                {"rationale": " The proposed control could discriminate an alternative explanation. "}
            ),
            "decision.rationale must be canonical",
        ),
    ],
)
def test_collaborator_review_prose_must_be_canonical(
    tmp_path: Path, mutation, message: str
) -> None:
    context = _context()
    snapshot = create_context_snapshot(context, tmp_path / "context")
    proposal = _proposal(snapshot["context_sha256"])
    proposal_path = tmp_path / "proposal.json"
    proposal_path.write_text(json.dumps(proposal), encoding="utf-8")
    validated = validate_collaborator_proposal(
        Path(snapshot["context_file"]),
        snapshot["context_sha256"],
        proposal_path,
        tmp_path / "validated",
    )
    review = _review(validated["record_sha256"])
    mutation(review)
    review_path = tmp_path / "review.json"
    review_path.write_text(json.dumps(review), encoding="utf-8")
    with pytest.raises(ValidationError, match=message):
        adjudicate_collaborator_proposal(
            Path(validated["record_file"]),
            validated["record_sha256"],
            review_path,
            tmp_path / "reviewed",
        )
    assert not (tmp_path / "reviewed").exists()


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        (
            lambda review: review.update(
                {
                    "overall_assessment": (
                        "This review approves the claim and authorizes evidence creation."
                    )
                }
            ),
            "must not claim acceptance",
        ),
        (
            lambda review: review.update(
                {"overall_assessment": "Reviewer identity authenticated for this triage."}
            ),
            "must not claim acceptance",
        ),
        (
            lambda review: review["decisions"][0].update(
                {"rationale": "The proposal confirms the result."}
            ),
            "must not claim acceptance",
        ),
    ],
)
def test_collaborator_review_prose_must_remain_non_authority(
    tmp_path: Path, mutation, message: str
) -> None:
    context = _context()
    snapshot = create_context_snapshot(context, tmp_path / "context")
    proposal = _proposal(snapshot["context_sha256"])
    proposal_path = tmp_path / "proposal.json"
    proposal_path.write_text(json.dumps(proposal), encoding="utf-8")
    validated = validate_collaborator_proposal(
        Path(snapshot["context_file"]),
        snapshot["context_sha256"],
        proposal_path,
        tmp_path / "validated",
    )
    review = _review(validated["record_sha256"])
    mutation(review)
    review_path = tmp_path / "review.json"
    review_path.write_text(json.dumps(review), encoding="utf-8")
    with pytest.raises(ValidationError, match=message):
        adjudicate_collaborator_proposal(
            Path(validated["record_file"]),
            validated["record_sha256"],
            review_path,
            tmp_path / "reviewed",
        )
    assert not (tmp_path / "reviewed").exists()


def test_proposal_adjudication_replays_retained_body_grounding(
    tmp_path: Path,
) -> None:
    context = _context(
        context_reference_index=[{"ref": "claim:claim-1", "kind": "claim"}]
    )
    snapshot = create_context_snapshot(context, tmp_path / "context")
    proposal_path = tmp_path / "proposal.json"
    proposal_path.write_text(
        json.dumps(
            _proposal(
                snapshot["context_sha256"],
                evidence_refs=["claim:claim-1"],
            )
        ),
        encoding="utf-8",
    )
    validated = validate_collaborator_proposal(
        Path(snapshot["context_file"]),
        snapshot["context_sha256"],
        proposal_path,
        tmp_path / "validated",
    )
    record_path = Path(validated["record_file"])
    record = json.loads(record_path.read_text(encoding="utf-8"))
    record["proposal_body_grounding"][0]["context_refs"] = ["claim:not-in-context"]
    record_path.write_text(
        json.dumps(record, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    trusted_hash = hashlib.sha256(record_path.read_bytes()).hexdigest()
    review_path = tmp_path / "review.json"
    review_path.write_text(json.dumps(_review(trusted_hash)), encoding="utf-8")

    with pytest.raises(ValidationError, match="body grounding disagrees"):
        adjudicate_collaborator_proposal(
            record_path,
            trusted_hash,
            review_path,
            tmp_path / "reviewed",
        )
    assert not (tmp_path / "reviewed").exists()


def test_proposal_record_replay_rejects_rewritten_body_authority_claim(
    tmp_path: Path,
) -> None:
    context = _context(
        context_reference_index=[{"ref": "claim:claim-1", "kind": "claim"}]
    )
    snapshot = create_context_snapshot(context, tmp_path / "context")
    proposal_path = tmp_path / "proposal.json"
    proposal_path.write_text(
        json.dumps(
            _proposal(
                snapshot["context_sha256"],
                evidence_refs=["claim:claim-1"],
            )
        ),
        encoding="utf-8",
    )
    validated = validate_collaborator_proposal(
        Path(snapshot["context_file"]),
        snapshot["context_sha256"],
        proposal_path,
        tmp_path / "validated",
    )
    record_path = Path(validated["record_file"])
    record = json.loads(record_path.read_text(encoding="utf-8"))
    record["proposal"]["limitations"][0]["statement"] = (
        "This validates the favored mechanism."
    )
    record["proposal_body_grounding"] = _proposal_body_grounding(record["proposal"])
    record_path.write_text(
        json.dumps(record, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    trusted_hash = hashlib.sha256(record_path.read_bytes()).hexdigest()

    with pytest.raises(
        ValidationError,
        match="limitations\\[0\\].statement must not claim acceptance",
    ):
        verify_collaborator_proposal_record(record_path, trusted_hash)


def test_review_record_replay_rejects_rewritten_falsification_authority_claim(
    tmp_path: Path,
) -> None:
    context = _context(
        context_reference_index=[{"ref": "claim:claim-1", "kind": "claim"}]
    )
    snapshot = create_context_snapshot(context, tmp_path / "context")
    proposal_path = tmp_path / "proposal.json"
    proposal_path.write_text(
        json.dumps(
            _proposal(
                snapshot["context_sha256"],
                evidence_refs=["claim:claim-1"],
            )
        ),
        encoding="utf-8",
    )
    validated = validate_collaborator_proposal(
        Path(snapshot["context_file"]),
        snapshot["context_sha256"],
        proposal_path,
        tmp_path / "validated",
    )
    review_path = tmp_path / "review.json"
    review_path.write_text(
        json.dumps(_review(validated["record_sha256"])), encoding="utf-8"
    )
    reviewed = adjudicate_collaborator_proposal(
        Path(validated["record_file"]),
        validated["record_sha256"],
        review_path,
        tmp_path / "reviewed",
    )
    review_record_path = Path(reviewed["record_file"])
    record = json.loads(review_record_path.read_text(encoding="utf-8"))
    record["reviewed_suggestions"][0]["suggestion"]["falsification_conditions"] = [
        "This proves the suggested mechanism."
    ]
    review_record_path.write_text(
        json.dumps(record, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    trusted_hash = hashlib.sha256(review_record_path.read_bytes()).hexdigest()

    with pytest.raises(
        ValidationError,
        match="falsification_conditions item must not claim acceptance",
    ):
        verify_collaborator_review_record(review_record_path, trusted_hash)


def test_proposal_suggestion_ids_must_be_canonical(tmp_path: Path) -> None:
    context = _context()
    snapshot = create_context_snapshot(context, tmp_path / "context")
    proposal = _proposal(snapshot["context_sha256"])
    duplicate = dict(proposal["suggestions"][0])
    duplicate["suggestion_id"] = " suggestion-1 "
    proposal["suggestions"].append(duplicate)
    proposal_path = tmp_path / "proposal.json"
    proposal_path.write_text(json.dumps(proposal), encoding="utf-8")
    with pytest.raises(ValidationError, match="suggestion_id must be canonical"):
        validate_collaborator_proposal(
            Path(snapshot["context_file"]),
            snapshot["context_sha256"],
            proposal_path,
            tmp_path / "validated",
        )
    assert not (tmp_path / "validated").exists()


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        (
            lambda proposal: proposal.update({"proposal_id": " proposal-1 "}),
            "proposal_id must be canonical",
        ),
        (
            lambda proposal: proposal.update(
                {"purpose": " Stress-test the design. "}
            ),
            "purpose does not match its context",
        ),
        (
            lambda proposal: proposal["generated_by"].update(
                {"provider": " local-runtime "}
            ),
            "generated_by.provider must be canonical",
        ),
        (
            lambda proposal: proposal["generated_by"].update(
                {"model": " research-helper "}
            ),
            "generated_by.model must be canonical",
        ),
    ],
)
def test_proposal_identity_and_generator_handles_must_be_canonical(
    tmp_path: Path, mutation, message: str
) -> None:
    context = _context()
    snapshot = create_context_snapshot(context, tmp_path / "context")
    proposal = _proposal(snapshot["context_sha256"])
    mutation(proposal)
    proposal_path = tmp_path / "proposal.json"
    proposal_path.write_text(json.dumps(proposal), encoding="utf-8")
    with pytest.raises(ValidationError, match=message):
        validate_collaborator_proposal(
            Path(snapshot["context_file"]),
            snapshot["context_sha256"],
            proposal_path,
            tmp_path / "validated",
        )
    assert not (tmp_path / "validated").exists()


def test_proposal_rejects_stale_context_and_duplicate_json_keys(tmp_path: Path) -> None:
    context = _context()
    snapshot = create_context_snapshot(context, tmp_path / "context")
    proposal_path = tmp_path / "proposal.json"
    proposal_path.write_text(
        '{"proposal_version":1,"proposal_version":1}', encoding="utf-8"
    )
    with pytest.raises(ValidationError, match="trusted SHA-256"):
        validate_collaborator_proposal(
            Path(snapshot["context_file"]),
            "0" * 64,
            proposal_path,
            tmp_path / "stale",
        )
    with pytest.raises(ValidationError, match="duplicate JSON object key"):
        validate_collaborator_proposal(
            Path(snapshot["context_file"]),
            snapshot["context_sha256"],
            proposal_path,
            tmp_path / "duplicate",
        )


@pytest.mark.parametrize(
    ("reference", "message"),
    [
        (
            [
                {"ref": "question:q1", "kind": "open_question"},
                {"ref": " question:q1 ", "kind": "open_question"},
            ],
            "ref must be canonical",
        ),
        (
            [{"ref": "source:x", "kind": "external_source"}],
            "kind is unsupported",
        ),
        (
            [{"ref": "evidence:ev1", "kind": "claim"}],
            "ref must match kind claim",
        ),
        (
            [{"ref": "claim:claim-1", "kind": "claim", "title": "Extra label"}],
            "has unknown fields",
        ),
    ],
)
def test_proposal_rejects_malformed_context_reference_index(
    tmp_path: Path, reference: list[dict[str, str]], message: str
) -> None:
    context = _context(context_reference_index=reference)
    with pytest.raises(ValidationError, match=message):
        create_context_snapshot(context, tmp_path / "context")
    assert not (tmp_path / "context").exists()


def test_validate_proposal_replays_context_scientific_constraints(
    tmp_path: Path,
) -> None:
    context = _context()
    del context["scientific_constraints"]
    context_dir = tmp_path / "manual-context"
    context_dir.mkdir()
    context_file = context_dir / "collaborator-context.json"
    context_file.write_text(json.dumps(context), encoding="utf-8")
    context_sha256 = hashlib.sha256(context_file.read_bytes()).hexdigest()
    proposal_path = tmp_path / "proposal.json"
    proposal_path.write_text(json.dumps(_proposal(context_sha256)), encoding="utf-8")

    with pytest.raises(ValidationError, match="scientific_constraints"):
        validate_collaborator_proposal(
            context_file,
            context_sha256,
            proposal_path,
            tmp_path / "validated",
        )
    assert not (tmp_path / "validated").exists()


def test_cli_exports_context_and_validates_proposal_without_a_provider(
    tmp_path: Path, capsys
) -> None:
    workspace = tmp_path / "workspace"
    common = ["--workspace", str(workspace), "--json"]
    assert main([*common, "workspace", "init"]) == 0
    capsys.readouterr()
    assert main(
        [
            *common,
            "inquiry",
            "create",
            "--id",
            "provider-neutral",
            "--title",
            "Provider-neutral review",
            "--statement",
            "Can optional collaboration preserve scientific authority?",
        ]
    ) == 0
    capsys.readouterr()
    context_dir = tmp_path / "context"
    assert main(
        [
            *common,
            "collaborator",
            "context",
            "--purpose",
            "Stress-test the design.",
            "--output",
            str(context_dir),
        ]
    ) == 0
    context_result = json.loads(capsys.readouterr().out)["result"]
    context_payload = json.loads(
        Path(context_result["context_file"]).read_text(encoding="utf-8")
    )
    inquiry_ref = context_payload["context_reference_index"][0]["ref"]
    proposal_path = tmp_path / "proposal.json"
    proposal_path.write_text(
        json.dumps(
            _proposal(context_result["context_sha256"], evidence_refs=[inquiry_ref])
        ),
        encoding="utf-8",
    )
    output = tmp_path / "validated"
    assert main(
        [
            *common,
            "collaborator",
            "validate-proposal",
            "--context-file",
            context_result["context_file"],
            "--expected-context-sha256",
            context_result["context_sha256"],
            "--proposal-file",
            str(proposal_path),
            "--output",
            str(output),
        ]
    ) == 0
    result = json.loads(capsys.readouterr().out)["result"]
    assert result["status"] == "pending_human_review"
    assert result["model_invoked_by_faraday"] is False
    assert main(
        [
            *common,
            "collaborator",
            "verify-proposal",
            "--proposal-record-file",
            result["record_file"],
            "--expected-proposal-record-sha256",
            result["record_sha256"],
        ]
    ) == 0
    verified_proposal = json.loads(capsys.readouterr().out)["result"]
    assert verified_proposal["record_status"] == "pending_human_review"
    assert verified_proposal["context_reference_replay"] == "retained_index_verified"
    assert verified_proposal["model_invoked_by_faraday"] is False

    review_file = tmp_path / "review.json"
    review_file.write_text(json.dumps(_review(result["record_sha256"])), encoding="utf-8")
    assert main(
        [
            *common,
            "collaborator",
            "review-proposal",
            "--proposal-record-file",
            result["record_file"],
            "--expected-proposal-record-sha256",
            result["record_sha256"],
            "--review-file",
            str(review_file),
            "--output",
            str(tmp_path / "reviewed"),
        ]
    ) == 0
    reviewed = json.loads(capsys.readouterr().out)["result"]
    assert reviewed["status"] == "reviewed_requires_manual_domain_action"
    assert reviewed["advanced_suggestion_count"] == 1
    assert reviewed["canonical_writes_performed"] is False
    assert main(
        [
            *common,
            "collaborator",
            "verify-review",
            "--review-record-file",
            reviewed["record_file"],
            "--expected-review-record-sha256",
            reviewed["record_sha256"],
        ]
    ) == 0
    verified = json.loads(capsys.readouterr().out)["result"]
    assert verified["reviewed_suggestion_count"] == 1
    assert verified["context_reference_replay"] == "verified"
    assert verified["proposal_record_replay"] == "verified"
    assert verified["proposal_suggestion_replay"] == "verified"
    assert verified["canonical_writes_performed"] is False


def test_collaborator_context_cli_requires_purpose(tmp_path: Path) -> None:
    common = ["--workspace", str(tmp_path / "workspace"), "--json"]
    assert main([*common, "workspace", "init"]) == 0

    with pytest.raises(SystemExit):
        main([*common, "collaborator", "context"])


def test_proposal_adjudication_is_complete_hash_bound_and_noncanonical(
    tmp_path: Path,
) -> None:
    context = _context()
    snapshot = create_context_snapshot(context, tmp_path / "context")
    proposal = _proposal(snapshot["context_sha256"])
    second_suggestion = {
        **proposal["suggestions"][0],
        "suggestion_id": "suggestion-2",
        "kind": "question",
        "statement": "Ask whether selection into the exposure is measured.",
        "rationale": "The design cannot interpret exposure differences without it.",
        "next_test": "Decide whether this is already represented in the DAG.",
    }
    proposal["suggestions"].append(second_suggestion)
    proposal_path = tmp_path / "proposal.json"
    proposal_path.write_text(json.dumps(proposal), encoding="utf-8")
    validated = validate_collaborator_proposal(
        Path(snapshot["context_file"]),
        snapshot["context_sha256"],
        proposal_path,
        tmp_path / "validated",
    )
    review = _review(validated["record_sha256"])
    review["decisions"].append({
        "suggestion_id": "suggestion-2",
        "disposition": "defer",
        "rationale": "The existing design record needs to be checked first.",
        "domain_route": "none",
    })
    review_path = tmp_path / "review.json"
    review_path.write_text(json.dumps(review), encoding="utf-8")
    result = adjudicate_collaborator_proposal(
        Path(validated["record_file"]),
        validated["record_sha256"],
        review_path,
        tmp_path / "reviewed",
    )
    record = json.loads(Path(result["record_file"]).read_text(encoding="utf-8"))
    expected_suggestions = proposal["suggestions"]
    assert record["advanced_suggestions"] == [
        {
            "suggestion_id": "suggestion-1",
            "domain_route": "design.revise",
            "suggestion_sha256": _canonical_json_sha256(expected_suggestions[0]),
            "manual_domain_review_required": True,
            "canonical_writes_performed": False,
            "scientific_evidence_eligible": False,
        }
    ]
    assert record["review_payload_sha256"] == _canonical_json_sha256(review)
    assert record["proposal_suggestion_ids"] == ["suggestion-1", "suggestion-2"]
    assert record["context_reference_index"] == []
    assert record["context_write_boundary"] == {
        "context_is_read_only": True,
        "provider_required": False,
        "canonical_changes_require": _CANONICAL_CHANGES_REQUIRE,
    }
    assert record["proposal_record_replay"] == {
        "context_reference_index_sha256": _canonical_json_sha256([]),
        "context_scientific_constraints_sha256": _canonical_json_sha256(
            _SCIENTIFIC_CONSTRAINTS
        ),
        "context_write_boundary_sha256": _canonical_json_sha256(
            record["context_write_boundary"]
        ),
        "proposal_body_grounding_sha256": _canonical_json_sha256(
            _proposal_body_grounding(proposal)
        ),
        "proposal_suggestions_sha256": _canonical_json_sha256(
            [_canonical_json_sha256(item) for item in expected_suggestions]
        ),
    }
    assert record["proposal_body_grounding"] == _proposal_body_grounding(proposal)
    reviewed = record["reviewed_suggestions"]
    assert reviewed == [
        {
            "suggestion_id": "suggestion-1",
            "suggestion_sha256": _canonical_json_sha256(expected_suggestions[0]),
            "suggestion": expected_suggestions[0],
            "disposition": "advance_to_domain_review",
            "rationale": "The proposed control could discriminate an alternative explanation.",
            "domain_route": "design.revise",
            "manual_domain_review_required": True,
            "canonical_writes_performed": False,
            "scientific_evidence_eligible": False,
        },
        {
            "suggestion_id": "suggestion-2",
            "suggestion_sha256": _canonical_json_sha256(expected_suggestions[1]),
            "suggestion": expected_suggestions[1],
            "disposition": "defer",
            "rationale": "The existing design record needs to be checked first.",
            "domain_route": "none",
            "manual_domain_review_required": False,
            "canonical_writes_performed": False,
            "scientific_evidence_eligible": False,
        },
    ]
    assert record["context_scientific_constraints"] == _SCIENTIFIC_CONSTRAINTS
    assert record["reviewer_identity_authenticated"] is False
    assert record["authorized_actions"] == []
    assert record["scientific_evidence_eligible"] is False
    verified = verify_collaborator_review_record(
        Path(result["record_file"]),
        result["record_sha256"],
    )
    assert verified["reviewed_suggestion_count"] == 2
    assert verified["advanced_suggestion_count"] == 1
    assert verified["context_reference_replay"] == "verified"
    assert verified["context_write_boundary_replay"] == "verified"
    assert verified["proposal_record_replay"] == "verified"
    assert verified["proposal_suggestion_replay"] == "verified"
    assert verified["review_payload_replay"] == "verified"
    assert verified["scientific_evidence_eligible"] is False


def test_verify_collaborator_review_replays_embedded_review_payload(
    tmp_path: Path,
) -> None:
    context = _context()
    snapshot = create_context_snapshot(context, tmp_path / "context")
    proposal_path = tmp_path / "proposal.json"
    proposal_path.write_text(
        json.dumps(_proposal(snapshot["context_sha256"])), encoding="utf-8"
    )
    validated = validate_collaborator_proposal(
        Path(snapshot["context_file"]),
        snapshot["context_sha256"],
        proposal_path,
        tmp_path / "validated",
    )
    review_path = tmp_path / "review.json"
    review_path.write_text(
        json.dumps(_review(validated["record_sha256"])), encoding="utf-8"
    )
    reviewed = adjudicate_collaborator_proposal(
        Path(validated["record_file"]),
        validated["record_sha256"],
        review_path,
        tmp_path / "reviewed",
    )
    record_path = Path(reviewed["record_file"])
    record = json.loads(record_path.read_text(encoding="utf-8"))
    record["review"]["decisions"][0].update(
        {
            "disposition": "reject",
            "rationale": "The idea is not ready for domain review.",
            "domain_route": "none",
        }
    )
    record["reviewed_suggestions"][0].update(
        {
            "disposition": "reject",
            "rationale": "The idea is not ready for domain review.",
            "domain_route": "none",
            "manual_domain_review_required": False,
        }
    )
    record["advanced_suggestions"] = []
    record_path.write_text(
        json.dumps(record, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    trusted_hash = hashlib.sha256(record_path.read_bytes()).hexdigest()

    with pytest.raises(ValidationError, match="review_payload_sha256"):
        verify_collaborator_review_record(record_path, trusted_hash)


def test_verify_collaborator_review_replays_conclusion_ceiling(
    tmp_path: Path,
) -> None:
    context = _context()
    snapshot = create_context_snapshot(context, tmp_path / "context")
    proposal_path = tmp_path / "proposal.json"
    proposal_path.write_text(
        json.dumps(_proposal(snapshot["context_sha256"])), encoding="utf-8"
    )
    validated = validate_collaborator_proposal(
        Path(snapshot["context_file"]),
        snapshot["context_sha256"],
        proposal_path,
        tmp_path / "validated",
    )
    review_path = tmp_path / "review.json"
    review_path.write_text(
        json.dumps(_review(validated["record_sha256"])), encoding="utf-8"
    )
    reviewed = adjudicate_collaborator_proposal(
        Path(validated["record_file"]),
        validated["record_sha256"],
        review_path,
        tmp_path / "reviewed",
    )
    record_path = Path(reviewed["record_file"])
    record = json.loads(record_path.read_text(encoding="utf-8"))
    record["conclusion_ceiling"] = "This review accepts the claim."
    record_path.write_text(
        json.dumps(record, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    trusted_hash = hashlib.sha256(record_path.read_bytes()).hexdigest()

    with pytest.raises(ValidationError, match="conclusion ceiling has changed"):
        verify_collaborator_review_record(record_path, trusted_hash)


def test_verify_collaborator_review_replays_non_authority_review_prose(
    tmp_path: Path,
) -> None:
    context = _context()
    snapshot = create_context_snapshot(context, tmp_path / "context")
    proposal_path = tmp_path / "proposal.json"
    proposal_path.write_text(
        json.dumps(_proposal(snapshot["context_sha256"])), encoding="utf-8"
    )
    validated = validate_collaborator_proposal(
        Path(snapshot["context_file"]),
        snapshot["context_sha256"],
        proposal_path,
        tmp_path / "validated",
    )
    review_path = tmp_path / "review.json"
    review_path.write_text(
        json.dumps(_review(validated["record_sha256"])), encoding="utf-8"
    )
    reviewed = adjudicate_collaborator_proposal(
        Path(validated["record_file"]),
        validated["record_sha256"],
        review_path,
        tmp_path / "reviewed",
    )
    record_path = Path(reviewed["record_file"])
    record = json.loads(record_path.read_text(encoding="utf-8"))
    record["review"]["overall_assessment"] = (
        "This review accepted the proposal as a canonical action."
    )
    record_path.write_text(
        json.dumps(record, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    trusted_hash = hashlib.sha256(record_path.read_bytes()).hexdigest()

    with pytest.raises(ValidationError, match="must not claim acceptance"):
        verify_collaborator_review_record(record_path, trusted_hash)


def test_verify_collaborator_review_rejects_omitted_proposal_suggestion(
    tmp_path: Path,
) -> None:
    context = _context()
    snapshot = create_context_snapshot(context, tmp_path / "context")
    proposal = _proposal(snapshot["context_sha256"])
    proposal["suggestions"].append(
        {
            **proposal["suggestions"][0],
            "suggestion_id": "suggestion-2",
            "kind": "question",
            "statement": "Ask whether a simpler artifact explanation fits first.",
            "rationale": "The review should not jump to the favored explanation.",
            "next_test": "Check the existing evidence graph for artifact controls.",
        }
    )
    proposal_path = tmp_path / "proposal.json"
    proposal_path.write_text(json.dumps(proposal), encoding="utf-8")
    validated = validate_collaborator_proposal(
        Path(snapshot["context_file"]),
        snapshot["context_sha256"],
        proposal_path,
        tmp_path / "validated",
    )
    review = _review(validated["record_sha256"])
    review["decisions"].append(
        {
            "suggestion_id": "suggestion-2",
            "disposition": "defer",
            "rationale": "The artifact explanation needs separate domain review.",
            "domain_route": "none",
        }
    )
    review_path = tmp_path / "review.json"
    review_path.write_text(json.dumps(review), encoding="utf-8")
    reviewed = adjudicate_collaborator_proposal(
        Path(validated["record_file"]),
        validated["record_sha256"],
        review_path,
        tmp_path / "reviewed",
    )
    record_path = Path(reviewed["record_file"])
    record = json.loads(record_path.read_text(encoding="utf-8"))
    record["review"]["decisions"] = record["review"]["decisions"][:1]
    record["reviewed_suggestions"] = record["reviewed_suggestions"][:1]
    record_path.write_text(
        json.dumps(record, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    trusted_hash = hashlib.sha256(record_path.read_bytes()).hexdigest()

    with pytest.raises(ValidationError, match="exactly cover"):
        verify_collaborator_review_record(record_path, trusted_hash)


def test_verify_collaborator_review_rejects_reordered_proposal_suggestions(
    tmp_path: Path,
) -> None:
    context = _context()
    snapshot = create_context_snapshot(context, tmp_path / "context")
    proposal = _proposal(snapshot["context_sha256"])
    proposal["suggestions"].append(
        {
            **proposal["suggestions"][0],
            "suggestion_id": "suggestion-2",
            "kind": "question",
            "statement": "Ask whether a simpler artifact explanation fits first.",
            "rationale": "The review should not jump to the favored explanation.",
            "next_test": "Check the existing evidence graph for artifact controls.",
        }
    )
    proposal_path = tmp_path / "proposal.json"
    proposal_path.write_text(json.dumps(proposal), encoding="utf-8")
    validated = validate_collaborator_proposal(
        Path(snapshot["context_file"]),
        snapshot["context_sha256"],
        proposal_path,
        tmp_path / "validated",
    )
    review = _review(validated["record_sha256"])
    review["decisions"].append(
        {
            "suggestion_id": "suggestion-2",
            "disposition": "defer",
            "rationale": "The artifact explanation needs separate domain review.",
            "domain_route": "none",
        }
    )
    review_path = tmp_path / "review.json"
    review_path.write_text(json.dumps(review), encoding="utf-8")
    reviewed = adjudicate_collaborator_proposal(
        Path(validated["record_file"]),
        validated["record_sha256"],
        review_path,
        tmp_path / "reviewed",
    )
    record_path = Path(reviewed["record_file"])
    record = json.loads(record_path.read_text(encoding="utf-8"))
    record["reviewed_suggestions"].reverse()
    record_path.write_text(
        json.dumps(record, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    trusted_hash = hashlib.sha256(record_path.read_bytes()).hexdigest()

    with pytest.raises(ValidationError, match="order and coverage"):
        verify_collaborator_review_record(record_path, trusted_hash)


def test_verify_legacy_collaborator_review_discloses_missing_suggestion_ids(
    tmp_path: Path,
) -> None:
    context = _context()
    snapshot = create_context_snapshot(context, tmp_path / "context")
    proposal_path = tmp_path / "proposal.json"
    proposal_path.write_text(
        json.dumps(_proposal(snapshot["context_sha256"])), encoding="utf-8"
    )
    validated = validate_collaborator_proposal(
        Path(snapshot["context_file"]),
        snapshot["context_sha256"],
        proposal_path,
        tmp_path / "validated",
    )
    review_path = tmp_path / "review.json"
    review_path.write_text(json.dumps(_review(validated["record_sha256"])), encoding="utf-8")
    reviewed = adjudicate_collaborator_proposal(
        Path(validated["record_file"]),
        validated["record_sha256"],
        review_path,
        tmp_path / "reviewed",
    )
    record_path = Path(reviewed["record_file"])
    record = json.loads(record_path.read_text(encoding="utf-8"))
    record.pop("proposal_suggestion_ids")
    record_path.write_text(
        json.dumps(record, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    trusted_hash = hashlib.sha256(record_path.read_bytes()).hexdigest()

    verified = verify_collaborator_review_record(record_path, trusted_hash)

    assert verified["context_reference_replay"] == "verified"
    assert verified["proposal_record_replay"] == "verified"
    assert verified["proposal_suggestion_replay"] == "legacy_missing"


def test_verify_legacy_collaborator_review_discloses_missing_proposal_replay(
    tmp_path: Path,
) -> None:
    context = _context(
        context_reference_index=[{"ref": "claim:claim-1", "kind": "claim"}]
    )
    snapshot = create_context_snapshot(context, tmp_path / "context")
    proposal_path = tmp_path / "proposal.json"
    proposal_path.write_text(
        json.dumps(
            _proposal(
                snapshot["context_sha256"],
                evidence_refs=["claim:claim-1"],
            )
        ),
        encoding="utf-8",
    )
    validated = validate_collaborator_proposal(
        Path(snapshot["context_file"]),
        snapshot["context_sha256"],
        proposal_path,
        tmp_path / "validated",
    )
    review_path = tmp_path / "review.json"
    review_path.write_text(
        json.dumps(_review(validated["record_sha256"])), encoding="utf-8"
    )
    reviewed = adjudicate_collaborator_proposal(
        Path(validated["record_file"]),
        validated["record_sha256"],
        review_path,
        tmp_path / "reviewed",
    )
    record_path = Path(reviewed["record_file"])
    record = json.loads(record_path.read_text(encoding="utf-8"))
    record.pop("proposal_record_replay")
    record_path.write_text(
        json.dumps(record, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    trusted_hash = hashlib.sha256(record_path.read_bytes()).hexdigest()

    verified = verify_collaborator_review_record(record_path, trusted_hash)

    assert verified["context_reference_replay"] == "verified"
    assert verified["proposal_record_replay"] == "legacy_missing"
    assert verified["proposal_suggestion_replay"] == "verified"
    assert verified["reviewed_suggestion_count"] == 1
    assert verified["scientific_evidence_eligible"] is False


def test_verify_legacy_collaborator_review_discloses_missing_context_index(
    tmp_path: Path,
) -> None:
    context = _context(
        context_reference_index=[{"ref": "claim:claim-1", "kind": "claim"}]
    )
    snapshot = create_context_snapshot(context, tmp_path / "context")
    proposal_path = tmp_path / "proposal.json"
    proposal_path.write_text(
        json.dumps(
            _proposal(
                snapshot["context_sha256"],
                evidence_refs=["claim:claim-1"],
            )
        ),
        encoding="utf-8",
    )
    validated = validate_collaborator_proposal(
        Path(snapshot["context_file"]),
        snapshot["context_sha256"],
        proposal_path,
        tmp_path / "validated",
    )
    review_path = tmp_path / "review.json"
    review_path.write_text(
        json.dumps(_review(validated["record_sha256"])), encoding="utf-8"
    )
    reviewed = adjudicate_collaborator_proposal(
        Path(validated["record_file"]),
        validated["record_sha256"],
        review_path,
        tmp_path / "reviewed",
    )
    record_path = Path(reviewed["record_file"])
    record = json.loads(record_path.read_text(encoding="utf-8"))
    record.pop("context_reference_index")
    record.pop("proposal_record_replay")
    record_path.write_text(
        json.dumps(record, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    trusted_hash = hashlib.sha256(record_path.read_bytes()).hexdigest()

    verified = verify_collaborator_review_record(record_path, trusted_hash)

    assert verified["context_reference_replay"] == "legacy_missing"
    assert verified["proposal_record_replay"] == "legacy_missing"
    assert verified["proposal_suggestion_replay"] == "verified"
    assert verified["reviewed_suggestion_count"] == 1
    assert verified["scientific_evidence_eligible"] is False


def test_verify_collaborator_review_replays_retained_context_references(
    tmp_path: Path,
) -> None:
    context = _context(
        context_reference_index=[{"ref": "claim:claim-1", "kind": "claim"}]
    )
    snapshot = create_context_snapshot(context, tmp_path / "context")
    proposal_path = tmp_path / "proposal.json"
    proposal_path.write_text(
        json.dumps(
            _proposal(
                snapshot["context_sha256"],
                evidence_refs=["claim:claim-1"],
            )
        ),
        encoding="utf-8",
    )
    validated = validate_collaborator_proposal(
        Path(snapshot["context_file"]),
        snapshot["context_sha256"],
        proposal_path,
        tmp_path / "validated",
    )
    review_path = tmp_path / "review.json"
    review_path.write_text(
        json.dumps(_review(validated["record_sha256"])), encoding="utf-8"
    )
    reviewed = adjudicate_collaborator_proposal(
        Path(validated["record_file"]),
        validated["record_sha256"],
        review_path,
        tmp_path / "reviewed",
    )
    record_path = Path(reviewed["record_file"])
    record = json.loads(record_path.read_text(encoding="utf-8"))
    assert record["context_reference_index"] == context["context_reference_index"]
    suggestion = record["reviewed_suggestions"][0]["suggestion"]
    suggestion["evidence_refs"] = ["claim:not-in-context"]
    record["reviewed_suggestions"][0]["suggestion_sha256"] = _canonical_json_sha256(
        suggestion
    )
    record_path.write_text(
        json.dumps(record, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    trusted_hash = hashlib.sha256(record_path.read_bytes()).hexdigest()

    with pytest.raises(
        ValidationError,
        match="evidence_refs are not present in the retained context",
    ):
        verify_collaborator_review_record(record_path, trusted_hash)


def test_verify_collaborator_review_requires_retained_suggestion_citations(
    tmp_path: Path,
) -> None:
    context = _context(
        context_reference_index=[{"ref": "claim:claim-1", "kind": "claim"}]
    )
    snapshot = create_context_snapshot(context, tmp_path / "context")
    proposal_path = tmp_path / "proposal.json"
    proposal_path.write_text(
        json.dumps(
            _proposal(
                snapshot["context_sha256"],
                evidence_refs=["claim:claim-1"],
            )
        ),
        encoding="utf-8",
    )
    validated = validate_collaborator_proposal(
        Path(snapshot["context_file"]),
        snapshot["context_sha256"],
        proposal_path,
        tmp_path / "validated",
    )
    review_path = tmp_path / "review.json"
    review_path.write_text(
        json.dumps(_review(validated["record_sha256"])), encoding="utf-8"
    )
    reviewed = adjudicate_collaborator_proposal(
        Path(validated["record_file"]),
        validated["record_sha256"],
        review_path,
        tmp_path / "reviewed",
    )
    record_path = Path(reviewed["record_file"])
    record = json.loads(record_path.read_text(encoding="utf-8"))
    suggestion = record["reviewed_suggestions"][0]["suggestion"]
    suggestion["evidence_refs"] = []
    record["reviewed_suggestions"][0]["suggestion_sha256"] = _canonical_json_sha256(
        suggestion
    )
    record_path.write_text(
        json.dumps(record, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    trusted_hash = hashlib.sha256(record_path.read_bytes()).hexdigest()

    with pytest.raises(ValidationError, match="evidence_refs must be a non-empty"):
        verify_collaborator_review_record(record_path, trusted_hash)


def test_verify_collaborator_review_replays_proposal_body_grounding_refs(
    tmp_path: Path,
) -> None:
    context = _context(
        context_reference_index=[{"ref": "claim:claim-1", "kind": "claim"}]
    )
    snapshot = create_context_snapshot(context, tmp_path / "context")
    proposal_path = tmp_path / "proposal.json"
    proposal_path.write_text(
        json.dumps(
            _proposal(
                snapshot["context_sha256"],
                evidence_refs=["claim:claim-1"],
            )
        ),
        encoding="utf-8",
    )
    validated = validate_collaborator_proposal(
        Path(snapshot["context_file"]),
        snapshot["context_sha256"],
        proposal_path,
        tmp_path / "validated",
    )
    review_path = tmp_path / "review.json"
    review_path.write_text(
        json.dumps(_review(validated["record_sha256"])), encoding="utf-8"
    )
    reviewed = adjudicate_collaborator_proposal(
        Path(validated["record_file"]),
        validated["record_sha256"],
        review_path,
        tmp_path / "reviewed",
    )
    record_path = Path(reviewed["record_file"])
    record = json.loads(record_path.read_text(encoding="utf-8"))
    record["proposal_body_grounding"][0]["context_refs"] = ["claim:not-in-context"]
    record["proposal_record_replay"]["proposal_body_grounding_sha256"] = (
        _canonical_json_sha256(record["proposal_body_grounding"])
    )
    record_path.write_text(
        json.dumps(record, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    trusted_hash = hashlib.sha256(record_path.read_bytes()).hexdigest()

    with pytest.raises(ValidationError, match="references are not present"):
        verify_collaborator_review_record(record_path, trusted_hash)


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        (
            lambda record: record["reviewed_suggestions"][0]["suggestion"].update(
                {"statement": "A later rewrite cannot keep the old suggestion digest."}
            ),
            "suggestion_sha256 does not match",
        ),
        (
            lambda record: record["reviewed_suggestions"][0].update(
                {"canonical_writes_performed": True}
            ),
            "canonical write boundary",
        ),
        (
            lambda record: record.update({"advanced_suggestions": []}),
            "advanced_suggestions disagrees",
        ),
        (
            lambda record: record["advanced_suggestions"][0].update(
                {"suggestion_sha256": "0" * 64}
            ),
            "advanced_suggestions disagrees",
        ),
        (
            lambda record: record["advanced_suggestions"][0].update(
                {"scientific_evidence_eligible": True}
            ),
            "advanced_suggestions disagrees",
        ),
        (
            lambda record: record["reviewed_suggestions"][0].update(
                {"manual_domain_review_required": False}
            ),
            "manual review flag",
        ),
        (
            lambda record: record["review"].update({"proposal_record_sha256": "0" * 64}),
            "different proposal record",
        ),
        (
            lambda record: record["review"].update({"review_version": 2}),
            "review_version must be 1",
        ),
        (
            lambda record: record["reviewed_suggestions"][0]["suggestion"].update(
                {"authority": "canonical_write"}
            ),
            "authority must be review_only",
        ),
        (
            lambda record: record["review"].update(
                {"overall_assessment": " Advance the control idea for ordinary design review. "}
            ),
            "overall_assessment must be canonical",
        ),
        (
            lambda record: record["review"]["decisions"][0].update(
                {"rationale": " The proposed control could discriminate an alternative explanation. "}
            ),
            "decision.rationale must be canonical",
        ),
        (
            _pad_retained_suggestion_statement,
            "statement must be canonical",
        ),
        (
            lambda record: record["context_scientific_constraints"].append(
                "Additional causal and authorization boundary reminder."
            ),
            "proposal_record_replay disagrees",
        ),
    ],
)
def test_verify_collaborator_review_record_replays_retained_receipts(
    tmp_path: Path, mutation, message: str
) -> None:
    context = _context()
    snapshot = create_context_snapshot(context, tmp_path / "context")
    proposal_path = tmp_path / "proposal.json"
    proposal_path.write_text(
        json.dumps(_proposal(snapshot["context_sha256"])), encoding="utf-8"
    )
    validated = validate_collaborator_proposal(
        Path(snapshot["context_file"]),
        snapshot["context_sha256"],
        proposal_path,
        tmp_path / "validated",
    )
    review_path = tmp_path / "review.json"
    review_path.write_text(json.dumps(_review(validated["record_sha256"])), encoding="utf-8")
    reviewed = adjudicate_collaborator_proposal(
        Path(validated["record_file"]),
        validated["record_sha256"],
        review_path,
        tmp_path / "reviewed",
    )
    record_path = Path(reviewed["record_file"])
    record = json.loads(record_path.read_text(encoding="utf-8"))
    mutation(record)
    record_path.write_text(json.dumps(record, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    trusted_hash = hashlib.sha256(record_path.read_bytes()).hexdigest()

    with pytest.raises(ValidationError, match=message):
        verify_collaborator_review_record(record_path, trusted_hash)


def test_verify_collaborator_review_replays_original_suggestion_anchor(
    tmp_path: Path,
) -> None:
    context = _context()
    snapshot = create_context_snapshot(context, tmp_path / "context")
    proposal_path = tmp_path / "proposal.json"
    proposal_path.write_text(
        json.dumps(_proposal(snapshot["context_sha256"])), encoding="utf-8"
    )
    validated = validate_collaborator_proposal(
        Path(snapshot["context_file"]),
        snapshot["context_sha256"],
        proposal_path,
        tmp_path / "validated",
    )
    review_path = tmp_path / "review.json"
    review_path.write_text(
        json.dumps(_review(validated["record_sha256"])), encoding="utf-8"
    )
    reviewed = adjudicate_collaborator_proposal(
        Path(validated["record_file"]),
        validated["record_sha256"],
        review_path,
        tmp_path / "reviewed",
    )
    record_path = Path(reviewed["record_file"])
    record = json.loads(record_path.read_text(encoding="utf-8"))
    suggestion = record["reviewed_suggestions"][0]["suggestion"]
    suggestion["statement"] = "Replace the reviewed suggestion after adjudication."
    record["reviewed_suggestions"][0]["suggestion_sha256"] = _canonical_json_sha256(
        suggestion
    )
    record_path.write_text(
        json.dumps(record, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    trusted_hash = hashlib.sha256(record_path.read_bytes()).hexdigest()

    with pytest.raises(ValidationError, match="proposal_record_replay disagrees"):
        verify_collaborator_review_record(record_path, trusted_hash)


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        (
            lambda review: review.update({"decisions": []}),
            "must decide every suggestion",
        ),
        (
            lambda review: review["decisions"][0].update(
                {"domain_route": "hypothesis.propose"}
            ),
            "incompatible with suggestion kind",
        ),
        (
            lambda review: review["decisions"][0].update(
                {"disposition": "reject", "domain_route": "design.revise"}
            ),
            "domain_route must be none",
        ),
        (
            lambda review: review["decisions"].append(
                {
                    "suggestion_id": " suggestion-1 ",
                    "disposition": "defer",
                    "rationale": "A padded duplicate cannot become another review.",
                    "domain_route": "none",
                }
            ),
            "decision.suggestion_id must be canonical",
        ),
        (
            lambda review: review.update({"review_id": " review-1 "}),
            "review_id must be canonical",
        ),
        (
            lambda review: review["reviewer"].update({"reviewer_id": " researcher-1 "}),
            "reviewer.reviewer_id must be canonical",
        ),
    ],
)
def test_proposal_adjudication_fails_closed(
    tmp_path: Path, mutation, message: str
) -> None:
    context = _context()
    snapshot = create_context_snapshot(context, tmp_path / "context")
    proposal_path = tmp_path / "proposal.json"
    proposal_path.write_text(
        json.dumps(_proposal(snapshot["context_sha256"])), encoding="utf-8"
    )
    validated = validate_collaborator_proposal(
        Path(snapshot["context_file"]),
        snapshot["context_sha256"],
        proposal_path,
        tmp_path / "validated",
    )
    review = _review(validated["record_sha256"])
    mutation(review)
    review_path = tmp_path / "review.json"
    review_path.write_text(json.dumps(review), encoding="utf-8")
    with pytest.raises(ValidationError, match=message):
        adjudicate_collaborator_proposal(
            Path(validated["record_file"]),
            validated["record_sha256"],
            review_path,
            tmp_path / "reviewed",
        )
    assert not (tmp_path / "reviewed").exists()
