"""Artifact-backed enforcement for conditional human-subject review obligations."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime
from pathlib import Path
from typing import Any

from research_machine.application.artifact_integrity import verify_run_artifacts
from research_machine.application.policies import validate_dataset_artifacts
from research_machine.domain.errors import ValidationError
from research_machine.domain.models import (
    DatasetArtifact,
    DatasetManifest,
    EthicsReviewEvent,
    ExperimentProtocol,
)


_STATUSES = {"satisfied", "control_active"}
_REVIEW_STATUSES = {"active", "suspended", "withdrawn", "expired"}
_HEX = set("0123456789abcdef")


def _text(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValidationError(f"ethics condition discharge {field} must be non-empty text")
    return value


def _canonical_text(value: Any, field: str) -> str:
    text = _text(value, field)
    if text != value.strip():
        raise ValidationError(f"ethics review event {field} must be canonical without surrounding whitespace")
    return text


def _digest(value: Any, field: str) -> str:
    value = _text(value, field)
    if len(value) != 64 or set(value) - _HEX:
        raise ValidationError(f"ethics condition discharge {field} must be a lowercase SHA-256")
    return value


def _time(value: Any, field: str) -> datetime:
    value = _canonical_text(value, field)
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValidationError(f"ethics condition discharge {field} must be ISO-8601") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValidationError(f"ethics condition discharge {field} must include a UTC offset")
    return parsed


def validate_original_review_artifact(
    protocol: ExperimentProtocol, *, verify_current_artifact: bool = True
) -> dict[str, Any]:
    """Revalidate the frozen human-review root-of-trust receipt."""
    if not protocol.human_subjects:
        return {}
    verification = protocol.independent_review_verification
    legacy_required = {
        "verification_version", "verified_at", "verified_by",
        "artifact_integrity", "scope",
        "reviewer_identity_authenticated", "substantive_adequacy_verified",
    }
    required = legacy_required | {"review_artifact_root"}
    allowed_legacy_package_receipt = (
        not verify_current_artifact
        and isinstance(verification, dict)
        and set(verification) == legacy_required
    )
    if (
        not isinstance(verification, dict)
        or (set(verification) != required and not allowed_legacy_package_receipt)
    ):
        raise ValidationError(
            "human-subject protocol lacks an exact independent-review verification receipt"
        )
    if verification["verification_version"] != 1:
        raise ValidationError("independent-review verification version is unsupported")
    _time(verification["verified_at"], "independent-review verified_at")
    verified_by = _canonical_text(
        verification["verified_by"], "independent-review verified_by"
    )
    _canonical_text(verification["scope"], "independent-review verification scope")
    if verification["reviewer_identity_authenticated"] is not False:
        raise ValidationError("independent-review receipt cannot claim authenticated reviewer identity")
    if verification["substantive_adequacy_verified"] is not False:
        raise ValidationError("independent-review receipt cannot claim substantive adequacy")
    retained = verification["artifact_integrity"]
    if not isinstance(retained, dict) or retained.get("status") != "passed":
        raise ValidationError("independent-review verification lacks passed artifact integrity")
    if verify_current_artifact:
        current = verify_run_artifacts(
            [DatasetArtifact(
                locator=_canonical_text(
                    protocol.independent_review_artifact_locator,
                    "independent-review artifact locator",
                ),
                sha256=_digest(protocol.independent_review_artifact_sha256, "independent-review artifact SHA-256"),
            )],
            artifact_root=_canonical_text(
                verification["review_artifact_root"],
                "independent-review artifact root",
            ),
            actor=verified_by, analysis_code_hash="", run_metadata={},
            attestation_schema_path=None, expected_attestation_schema_sha256=None,
        ).to_dict()
        if current != retained:
            raise ValidationError(
                "original independent-review artifact no longer matches its integrity receipt"
            )
    return verification


def _strict_json(path: Path) -> Any:
    def reject_constant(value: str) -> None:
        raise ValueError(f"non-finite JSON number: {value}")

    def reject_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                raise ValueError(f"duplicate JSON object key: {key}")
            result[key] = value
        return result

    try:
        return json.loads(
            path.read_bytes(),
            parse_constant=reject_constant,
            object_pairs_hook=reject_duplicates,
        )
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
        raise ValidationError(f"ethics condition JSON evidence is invalid: {exc}") from exc


def _resolve_pointer(value: Any, pointer: str) -> Any:
    if not pointer.startswith("/"):
        raise ValidationError(
            "ethics condition JSON evidence_location must be an absolute JSON Pointer"
        )
    current = value
    for raw in pointer[1:].split("/"):
        token = raw.replace("~1", "/").replace("~0", "~")
        if isinstance(current, dict) and token in current:
            current = current[token]
        elif isinstance(current, list) and token.isdigit() and int(token) < len(current):
            current = current[int(token)]
        else:
            raise ValidationError(
                "ethics condition evidence_location does not resolve in verified JSON bytes"
            )
    return current


def verify_ethics_condition_discharge(
    receipt: Any,
    protocol: ExperimentProtocol,
    artifact_root: str,
    *,
    actor: str,
    verified_at: str,
) -> dict[str, Any]:
    """Require exact, evidenced coverage of every conditional-review obligation."""
    if not isinstance(receipt, dict):
        raise ValidationError("ethics_condition_discharge must be an object")
    allowed = {
        "discharge_id", "protocol_id", "protocol_hash",
        "independent_review_receipt", "assessor", "assessed_at",
        "evidence_artifacts", "conditions",
    }
    if set(receipt) != allowed:
        raise ValidationError("ethics condition discharge fields do not match the required contract")
    _text(receipt.get("discharge_id"), "discharge_id")
    if receipt.get("protocol_id") != protocol.protocol_id or receipt.get("protocol_hash") != protocol.protocol_hash:
        raise ValidationError("ethics condition discharge does not match the frozen protocol")
    if receipt.get("independent_review_receipt") != protocol.independent_review_receipt:
        raise ValidationError("ethics condition discharge does not match the independent review receipt")
    assessor = _text(receipt.get("assessor"), "assessor")
    assessed_at = _time(receipt.get("assessed_at"), "assessed_at")
    reviewed_at = _time(protocol.independent_reviewed_at, "independent_reviewed_at")
    verification_time = _time(verified_at, "verification time")
    verifier = _canonical_text(actor, "condition verification actor")
    root = _canonical_text(artifact_root, "condition evidence artifact root")
    if assessed_at < reviewed_at:
        raise ValidationError("ethics condition discharge predates the independent review decision")
    if assessed_at > verification_time:
        raise ValidationError("ethics condition discharge cannot postdate dataset registration")

    evidence = receipt.get("evidence_artifacts")
    if not isinstance(evidence, list) or not evidence:
        raise ValidationError("ethics condition discharge evidence_artifacts must be non-empty")
    artifacts: list[DatasetArtifact] = []
    evidence_hashes: set[str] = set()
    evidence_by_hash: dict[str, dict[str, Any]] = {}
    for item in evidence:
        if not isinstance(item, dict) or set(item) != {
            "locator", "sha256", "size_bytes", "media_type"
        }:
            raise ValidationError("ethics condition discharge evidence artifact is invalid")
        digest = _digest(item.get("sha256"), "evidence artifact sha256")
        if digest in evidence_hashes:
            raise ValidationError("ethics condition discharge evidence hashes must be unique")
        evidence_hashes.add(digest)
        media_type = _text(item.get("media_type"), "evidence artifact media_type")
        evidence_by_hash[digest] = item
        artifacts.append(DatasetArtifact(
            locator=_text(item.get("locator"), "evidence artifact locator"),
            sha256=digest,
            size_bytes=item.get("size_bytes"),
            media_type=media_type,
        ))

    conditions = receipt.get("conditions")
    if not isinstance(conditions, list):
        raise ValidationError("ethics condition discharge conditions must be an array")
    by_condition: dict[str, dict[str, Any]] = {}
    for item in conditions:
        if not isinstance(item, dict) or set(item) != {
            "condition", "compliance_status", "rationale",
            "evidence_sha256", "evidence_location", "valid_through",
        }:
            raise ValidationError("ethics condition discharge condition result is invalid")
        condition = _text(item.get("condition"), "condition")
        if condition in by_condition:
            raise ValidationError("ethics condition discharge conditions must be unique")
        if item.get("compliance_status") not in _STATUSES:
            raise ValidationError("ethics condition compliance_status must be satisfied or control_active")
        valid_through = item.get("valid_through")
        if item["compliance_status"] == "control_active":
            if _time(valid_through, "condition valid_through") < verification_time:
                raise ValidationError(
                    "active ethics condition control expires before dataset registration"
                )
        elif valid_through is not None:
            raise ValidationError(
                "satisfied ethics conditions must use null valid_through"
            )
        _text(item.get("rationale"), "condition rationale")
        digest = _digest(item.get("evidence_sha256"), "condition evidence_sha256")
        if digest not in evidence_hashes:
            raise ValidationError("ethics condition result must reference a listed evidence artifact")
        _text(item.get("evidence_location"), "condition evidence_location")
        by_condition[condition] = item
    if set(by_condition) != set(protocol.independent_review_conditions):
        raise ValidationError("ethics condition discharge must cover exactly every frozen review condition")

    report = verify_run_artifacts(
        validate_dataset_artifacts(artifacts),
        artifact_root=root,
        actor=verifier,
        analysis_code_hash="",
        run_metadata={},
        attestation_schema_path=None,
        expected_attestation_schema_sha256=None,
    )
    if report.status != "passed":
        raise ValidationError(
            "ethics condition evidence verification failed: "
            + ", ".join(item["code"] for item in report.findings)
        )
    location_checks: list[dict[str, Any]] = []
    resolved_root = Path(root).expanduser().resolve()
    for condition in protocol.independent_review_conditions:
        result = by_condition[condition]
        artifact = evidence_by_hash[result["evidence_sha256"]]
        if artifact["media_type"] == "application/json":
            selected = _resolve_pointer(
                _strict_json(resolved_root / artifact["locator"]),
                result["evidence_location"],
            )
            try:
                selected_sha256 = hashlib.sha256(json.dumps(
                    selected, sort_keys=True, separators=(",", ":"),
                    ensure_ascii=False, allow_nan=False,
                ).encode()).hexdigest()
            except (TypeError, ValueError) as exc:
                raise ValidationError(
                    "ethics condition selected evidence is not finite JSON"
                ) from exc
            location_checks.append({
                "condition": condition,
                "evidence_sha256": result["evidence_sha256"],
                "evidence_location": result["evidence_location"],
                "location_kind": "json_pointer",
                "selected_value_sha256": selected_sha256,
                "status": "resolved",
            })
        else:
            location_checks.append({
                "condition": condition,
                "evidence_sha256": result["evidence_sha256"],
                "evidence_location": result["evidence_location"],
                "location_kind": "human_inspectable",
                "selected_value_sha256": None,
                "status": "recorded_not_machine_resolved",
            })
    encoded = json.dumps(
        receipt, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode()
    return {
        "verification_version": 1,
        "verified_at": verified_at,
        "verified_by": verifier,
        "evidence_artifact_root": str(resolved_root),
        "discharge_receipt_sha256": hashlib.sha256(encoded).hexdigest(),
        "protocol_id": protocol.protocol_id,
        "protocol_hash": protocol.protocol_hash,
        "independent_review_receipt": protocol.independent_review_receipt,
        "assessor": assessor,
        "assessed_at": receipt["assessed_at"],
        "condition_results": [by_condition[value] for value in protocol.independent_review_conditions],
        "evidence_location_checks": location_checks,
        "artifact_integrity": report.to_dict(),
        "reviewer_identity_authenticated": False,
        "condition_truth_independently_established": False,
        "ongoing_controls_require_continued_monitoring": any(
            item["compliance_status"] == "control_active" for item in by_condition.values()
        ),
    }


def validate_ethics_conditions_for_run(
    protocol: ExperimentProtocol,
    datasets: list[DatasetManifest],
    completed_at: datetime,
) -> dict[str, Any]:
    """Prevent analysis after an ongoing ethics control's recorded horizon."""
    if not protocol.human_subjects:
        return {}
    if protocol.independent_review_decision != "approved_with_conditions":
        return {
            "status": "unconditional_review_approval",
            "protocol_id": protocol.protocol_id,
            "protocol_hash": protocol.protocol_hash,
        }
    checked: list[dict[str, Any]] = []
    for dataset in datasets:
        verification = reverify_ethics_condition_discharge(protocol, dataset)
        if (
            verification.get("protocol_id") != protocol.protocol_id
            or verification.get("protocol_hash") != protocol.protocol_hash
        ):
            raise ValidationError(
                f"human-subject dataset {dataset.dataset_id} ethics verification does not match the run protocol"
            )
        results = verification.get("condition_results")
        if not isinstance(results, list):
            raise ValidationError("human-subject dataset ethics condition results are missing")
        by_condition = {
            item.get("condition"): item for item in results if isinstance(item, dict)
        }
        if set(by_condition) != set(protocol.independent_review_conditions):
            raise ValidationError(
                "human-subject dataset ethics verification does not cover every frozen condition"
            )
        for condition in protocol.independent_review_conditions:
            item = by_condition[condition]
            if item.get("compliance_status") == "control_active":
                if _time(item.get("valid_through"), "condition valid_through") < completed_at:
                    raise ValidationError(
                        f"human-subject ethics control expired before run completion: {condition}"
                    )
            elif item.get("compliance_status") != "satisfied":
                raise ValidationError("human-subject ethics condition has an invalid compliance status")
        checked.append({
            "dataset_id": dataset.dataset_id,
            "discharge_receipt_sha256": verification.get("discharge_receipt_sha256"),
            "ongoing_controls_require_continued_monitoring": verification.get(
                "ongoing_controls_require_continued_monitoring"
            ),
        })
    return {
        "status": "condition_discharge_valid_for_run",
        "protocol_id": protocol.protocol_id,
        "protocol_hash": protocol.protocol_hash,
        "run_completed_at": completed_at.isoformat(),
        "datasets": checked,
        "condition_truth_independently_established": False,
    }


def reverify_ethics_condition_discharge(
    protocol: ExperimentProtocol, dataset: DatasetManifest
) -> dict[str, Any]:
    """Replay a dataset's complete conditional-review verification."""
    verification = dataset.metadata.get("ethics_condition_verification")
    if not isinstance(verification, dict):
        raise ValidationError(
            f"human-subject dataset {dataset.dataset_id} lacks service-verified condition discharge"
        )
    artifact_root = verification.get("evidence_artifact_root")
    if not isinstance(artifact_root, str) or not artifact_root.strip():
        raise ValidationError(
            f"human-subject dataset {dataset.dataset_id} lacks retained condition-evidence artifact root"
        )
    recomputed = verify_ethics_condition_discharge(
        dataset.metadata.get("ethics_condition_discharge"),
        protocol,
        artifact_root,
        actor=_text(verification.get("verified_by"), "condition verification actor"),
        verified_at=_text(
            verification.get("verified_at"), "condition verification time"
        ),
    )
    if recomputed != verification:
        raise ValidationError(
            f"human-subject dataset {dataset.dataset_id} condition verification no longer reproduces exactly"
        )
    return verification


def evaluate_ethics_clearance(
    protocol: ExperimentProtocol,
    events: list[EthicsReviewEvent],
    at_time: datetime,
) -> dict[str, Any]:
    """Evaluate the latest append-only ethics status without mutating protocol truth."""
    if not protocol.human_subjects:
        return {}
    validate_original_review_artifact(protocol)
    events = validate_ethics_review_event_chain(protocol, events)
    applicable = sorted(
        (item for item in events if _time(item.effective_at, "event effective_at") <= at_time),
        key=lambda item: item.sequence,
    )
    if not applicable:
        return {
            "status": "active",
            "basis": "frozen_independent_review_decision",
            "protocol_id": protocol.protocol_id,
            "protocol_hash": protocol.protocol_hash,
            "review_event_id": None,
            "checked_at": at_time.isoformat(),
        }
    latest = applicable[-1]
    if latest.protocol_hash != protocol.protocol_hash:
        raise ValidationError("latest ethics review event does not match the frozen protocol")
    if latest.status not in _REVIEW_STATUSES:
        raise ValidationError("latest ethics review event has an unsupported status")
    if latest.status != "active":
        raise ValidationError(
            f"human-subject ethics clearance is {latest.status} as of {latest.effective_at}"
        )
    if latest.expires_at is not None and _time(latest.expires_at, "event expires_at") < at_time:
        raise ValidationError(
            f"human-subject ethics clearance expired at {latest.expires_at}"
        )
    return {
        "status": "active",
        "basis": "append_only_ethics_review_event",
        "protocol_id": protocol.protocol_id,
        "protocol_hash": protocol.protocol_hash,
        "review_event_id": latest.event_id,
        "event_artifact_sha256": latest.review_artifact_sha256,
        "expires_at": latest.expires_at,
        "checked_at": at_time.isoformat(),
        "reviewer_identity_authenticated": False,
        "substantive_adequacy_verified": False,
    }


def validate_ethics_review_event_chain(
    protocol: ExperimentProtocol,
    events: list[EthicsReviewEvent],
    *,
    verify_current_artifacts: bool = True,
) -> list[EthicsReviewEvent]:
    ordered = sorted(events, key=lambda item: item.sequence)
    previous: EthicsReviewEvent | None = None
    for expected_sequence, event in enumerate(ordered, start=1):
        _canonical_text(event.event_id, "event_id")
        _canonical_text(event.protocol_id, "protocol_id")
        _canonical_text(event.protocol_hash, "protocol_hash")
        status = _canonical_text(event.status, "status")
        if event.supersedes_event_id is not None:
            _canonical_text(event.supersedes_event_id, "supersedes_event_id")
        if event.sequence != expected_sequence:
            raise ValidationError("ethics review event sequence is incomplete or duplicated")
        if event.protocol_id != protocol.protocol_id or event.protocol_hash != protocol.protocol_hash:
            raise ValidationError("ethics review event chain does not match the frozen protocol")
        if status not in _REVIEW_STATUSES:
            raise ValidationError("ethics review event has an unsupported status")
        effective = _time(event.effective_at, "event effective_at")
        created = _time(event.created_at, "event created_at")
        reviewed = _time(protocol.independent_reviewed_at, "independent reviewed_at")
        if effective < reviewed or effective > created:
            raise ValidationError("ethics review event has impossible chronology")
        if event.status == "active" and event.expires_at is not None:
            if _time(event.expires_at, "event expires_at") <= effective:
                raise ValidationError("active ethics review event expiry must follow its effective time")
        elif event.status != "active" and event.expires_at is not None:
            raise ValidationError("non-active ethics review event cannot expire")
        _text(event.reason, "review event reason")
        _digest(event.review_artifact_sha256, "review event artifact SHA-256")
        if not isinstance(event.artifact_integrity, dict) or event.artifact_integrity.get("status") != "passed":
            raise ValidationError("ethics review event lacks passed artifact integrity")
        if verify_current_artifacts:
            root = _canonical_text(event.review_artifact_root, "review event artifact root")
            current = verify_run_artifacts(
                [DatasetArtifact(
                    locator=_canonical_text(
                        event.review_artifact_locator,
                        "review event artifact locator",
                    ),
                    sha256=event.review_artifact_sha256,
                )],
                artifact_root=root,
                actor=_canonical_text(event.created_by, "review event created_by"),
                analysis_code_hash="",
                run_metadata={},
                attestation_schema_path=None,
                expected_attestation_schema_sha256=None,
            ).to_dict()
            if current != event.artifact_integrity:
                raise ValidationError(
                    f"ethics review event {event.event_id} artifact no longer matches its integrity receipt"
                )
        if previous is None:
            if event.supersedes_event_id is not None:
                raise ValidationError("first ethics review event cannot supersede another event")
        else:
            if event.supersedes_event_id != previous.event_id:
                raise ValidationError("ethics review event chain has a broken supersession link")
            if effective < _time(
                previous.effective_at, "prior event effective_at"
            ):
                raise ValidationError("ethics review event effective times move backward")
        previous = event
    return ordered
