from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Any

from research_machine.application.evidence_admission import evidence_payload_sha256
from research_machine.application.policies import require_canonical_text, require_sha256
from research_machine.domain.errors import ConflictError, ValidationError
from research_machine.domain.models import (
    Claim,
    DatasetManifest,
    EvidenceRecord,
    EvidenceStatusEvent,
    ExperimentProtocol,
    Hypothesis,
    Inquiry,
    ResearchRun,
)


SHERLOCK_REFERENCE_KINDS = frozenset(
    {"artifact", "assertion", "claim", "finding", "annotation", "report"}
)


def _json_bytes(value: dict[str, Any]) -> bytes:
    return (
        json.dumps(value, sort_keys=True, indent=2, ensure_ascii=False) + "\n"
    ).encode("utf-8")


def _write_new_file(path: Path, content: bytes) -> None:
    if path.exists():
        raise ConflictError(f"bridge export file already exists: {path}")
    temporary = path.with_name(f".{path.name}.tmp-{os.getpid()}")
    try:
        with temporary.open("xb") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        temporary.replace(path)
    finally:
        if temporary.exists():
            temporary.unlink()


def _latest_status(
    evidence: EvidenceRecord, events: list[EvidenceStatusEvent]
) -> dict[str, Any]:
    matching = [event for event in events if event.evidence_id == evidence.evidence_id]
    if not matching:
        return {"status": "active", "source": "implicit_no_status_event"}
    latest = sorted(matching, key=lambda event: event.sequence)[-1]
    return {
        "status": latest.status,
        "source": "evidence_status_event",
        "event": latest.to_dict(),
    }


def build_sherlock_evidence_summary(
    *,
    inquiry: Inquiry,
    evidence: EvidenceRecord,
    hypothesis: Hypothesis,
    claim: Claim | None,
    dataset: DatasetManifest | None,
    protocol: ExperimentProtocol | None,
    run: ResearchRun | None,
    status_events: list[EvidenceStatusEvent],
    created_at: str,
) -> dict[str, Any]:
    return {
        "format_version": 1,
        "created_at": created_at,
        "summary_role": "immutable_faraday_summary",
        "authority_boundary": {
            "owner": "Faraday",
            "canonical_state_mutated_by_export": False,
            "sherlock_note_is_faraday_evidence": False,
            "statement": (
                "This export is a read-only projection for Sherlock investigation. "
                "It is not evidence admission, review promotion, or publication authorization."
            ),
        },
        "inquiry": inquiry.to_dict(),
        "faraday_reference": {
            "kind": "evidence",
            "id": evidence.evidence_id,
            "evidence_record_sha256": evidence_payload_sha256(evidence),
            "protocol_id": evidence.protocol_id,
            "run_id": evidence.run_id,
            "dataset_id": evidence.dataset_id,
            "claim_id": evidence.claim_id,
            "hypothesis_id": evidence.hypothesis_id,
            "claim_ceiling": evidence.analysis_claim_ceiling
            or "; ".join(evidence.higher_level_conclusions_unsupported),
        },
        "current_status": _latest_status(evidence, status_events),
        "evidence": evidence.to_dict(),
        "claim": claim.to_dict() if claim is not None else None,
        "hypothesis": hypothesis.to_dict(),
        "dataset": dataset.to_dict() if dataset is not None else None,
        "protocol": protocol.to_dict() if protocol is not None else None,
        "run": run.to_dict() if run is not None else None,
        "known_limitations": [
            "Sherlock may preserve and annotate this summary but cannot mutate Faraday state.",
            "Faraday must independently admit any later source or Sherlock note through its own gates.",
        ],
    }


def bridge_receipt_for_summary(
    *,
    evidence: EvidenceRecord,
    run: ResearchRun | None,
    summary_sha256: str,
    summary_locator: str,
    created_at: str,
    receipt_id: str,
    sherlock_case_id: str,
    sherlock_kind: str,
    sherlock_id: str,
    sherlock_artifact_sha256: str | None,
) -> dict[str, Any]:
    faraday_reference: dict[str, Any] = {
        "kind": "evidence",
        "id": evidence.evidence_id,
        "evidence_record_sha256": evidence_payload_sha256(evidence),
    }
    if run is not None and isinstance(run.metadata.get("run_payload_sha256"), str):
        faraday_reference["run_receipt_sha256"] = run.metadata["run_payload_sha256"]
    if evidence.protocol_id:
        faraday_reference["protocol_sha256"] = (
            evidence.admission_checks.get("protocol_hash", "")
        )
    if evidence.analysis_claim_ceiling:
        faraday_reference["claim_ceiling"] = evidence.analysis_claim_ceiling
    elif evidence.higher_level_conclusions_unsupported:
        faraday_reference["claim_ceiling"] = "; ".join(
            evidence.higher_level_conclusions_unsupported
        )
    faraday_reference = {
        key: value for key, value in faraday_reference.items() if value not in {"", None}
    }

    sherlock_reference: dict[str, Any] = {
        "case_id": sherlock_case_id,
        "kind": sherlock_kind,
        "id": sherlock_id,
    }
    if sherlock_artifact_sha256 is not None:
        sherlock_reference["artifact_sha256"] = sherlock_artifact_sha256

    return {
        "format_version": 1,
        "receipt_id": receipt_id,
        "created_at": created_at,
        "direction": "faraday_export_to_sherlock",
        "faraday_reference": faraday_reference,
        "sherlock_reference": sherlock_reference,
        "translation": {
            "summary_sha256": summary_sha256,
            "summary_locator": summary_locator,
            "summary_role": "immutable_faraday_summary",
            "known_limitations": [
                "Sherlock reference preserves investigative context only.",
                "Faraday canonical state changes require Faraday commands and gates.",
            ],
        },
        "authority_boundary": {
            "faraday_canonical_state_mutated": False,
            "sherlock_note_is_faraday_evidence": False,
            "publication_authorized": False,
            "review_promotion_authorized": False,
            "boundary_statement": (
                "This receipt links Faraday and Sherlock records without merging "
                "authority or canonical state."
            ),
        },
    }


def validate_sherlock_export_options(
    *,
    evidence_id: str,
    sherlock_case_id: str,
    sherlock_kind: str,
    sherlock_id: str | None,
    sherlock_artifact_sha256: str | None,
) -> tuple[str, str, str, str | None]:
    evidence_id = require_canonical_text(evidence_id, "evidence_id")
    sherlock_case_id = require_canonical_text(sherlock_case_id, "sherlock_case_id")
    sherlock_kind = require_canonical_text(sherlock_kind, "sherlock_kind")
    if sherlock_kind not in SHERLOCK_REFERENCE_KINDS:
        raise ValidationError("sherlock_kind is not supported by the bridge schema")
    if sherlock_id is None:
        sherlock_id = f"pending-{evidence_id}"
    sherlock_id = require_canonical_text(sherlock_id, "sherlock_id")
    if sherlock_artifact_sha256 is not None:
        sherlock_artifact_sha256 = require_sha256(
            sherlock_artifact_sha256, "sherlock_artifact_sha256"
        )
    return evidence_id, sherlock_case_id, sherlock_kind, sherlock_id, sherlock_artifact_sha256


def write_sherlock_evidence_export(
    *,
    output_dir: Path,
    summary: dict[str, Any],
    receipt: dict[str, Any],
) -> dict[str, Any]:
    if output_dir.exists():
        raise ConflictError(f"bridge export output already exists: {output_dir}")
    output_dir.mkdir(parents=True)
    try:
        summary_bytes = _json_bytes(summary)
        receipt_bytes = _json_bytes(receipt)
        _write_new_file(output_dir / "faraday-summary.json", summary_bytes)
        _write_new_file(output_dir / "sherlock-bridge-link.json", receipt_bytes)
    except Exception:
        for path in (output_dir / "faraday-summary.json", output_dir / "sherlock-bridge-link.json"):
            if path.exists():
                path.unlink()
        try:
            output_dir.rmdir()
        except OSError:
            pass
        raise
    return {
        "output_dir": str(output_dir),
        "summary_path": str(output_dir / "faraday-summary.json"),
        "summary_sha256": hashlib.sha256(summary_bytes).hexdigest(),
        "bridge_link_path": str(output_dir / "sherlock-bridge-link.json"),
        "bridge_link_sha256": hashlib.sha256(receipt_bytes).hexdigest(),
    }
