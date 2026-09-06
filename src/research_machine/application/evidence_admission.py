"""Semantic replay of scientific-evidence admission receipts."""

from __future__ import annotations

from datetime import datetime
import hashlib
import json
from typing import Sequence

from research_machine.application.ethics import evaluate_ethics_clearance
from research_machine.application.run_integrity import reverify_run_artifacts
from research_machine.domain.errors import ValidationError
from research_machine.domain.models import (
    DatasetManifest,
    Claim,
    EthicsReviewEvent,
    EvidenceRecord,
    ExperimentProtocol,
    ResearchRun,
)


def _time(value: str, field: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (AttributeError, ValueError) as exc:
        raise ValidationError(f"{field} must be valid ISO-8601") from exc
    if parsed.utcoffset() is None:
        raise ValidationError(f"{field} must include a UTC offset")
    return parsed


def evidence_payload_sha256(record: EvidenceRecord) -> str:
    """Commit every immutable evidence field without recursively hashing its receipt."""
    payload = record.to_dict()
    payload.pop("admission_checks", None)
    return hashlib.sha256(
        json.dumps(
            payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False
        ).encode("utf-8")
    ).hexdigest()


def validate_evidence_admission_receipts(
    evidence: Sequence[EvidenceRecord],
    claims: Sequence[Claim],
    runs: Sequence[ResearchRun],
    protocols: Sequence[ExperimentProtocol],
    datasets: Sequence[DatasetManifest],
    ethics_events: Sequence[EthicsReviewEvent],
) -> None:
    """Require every contributing scientific record to reproduce its admission."""
    runs_by_id = {item.run_id: item for item in runs}
    protocols_by_id = {item.protocol_id: item for item in protocols}
    datasets_by_id = {item.dataset_id: item for item in datasets}
    claims_by_id = {item.claim_id: item for item in claims}
    for record in evidence:
        if not record.scientific_evidence_eligible:
            if record.admission_checks:
                raise ValidationError(
                    f"non-scientific evidence {record.evidence_id} must not claim admission checks"
                )
            continue
        if record.run_id is None or record.protocol_id is None:
            raise ValidationError(
                f"scientific evidence {record.evidence_id} lacks a run or protocol"
            )
        run = runs_by_id.get(record.run_id)
        protocol = protocols_by_id.get(record.protocol_id)
        if run is None or protocol is None:
            raise ValidationError(
                f"scientific evidence {record.evidence_id} references unavailable canonical state"
            )
        if (
            not run.scientific_evidence_eligible
            or run.protocol_id != protocol.protocol_id
            or run.protocol_hash != protocol.protocol_hash
            or record.analysis_id != run.run_id
        ):
            raise ValidationError(
                f"scientific evidence {record.evidence_id} disagrees with its eligible run"
            )
        run_datasets: list[DatasetManifest] = []
        for dataset_id in run.dataset_ids:
            dataset = datasets_by_id.get(dataset_id)
            if dataset is None:
                raise ValidationError(
                    f"scientific evidence {record.evidence_id} run references unknown dataset {dataset_id}"
                )
            run_datasets.append(dataset)
        if record.dataset_id is not None and record.dataset_id not in run.dataset_ids:
            raise ValidationError(
                f"scientific evidence {record.evidence_id} names a dataset outside its run"
            )
        integrity = reverify_run_artifacts(run)
        applicable_events = [
            item for item in ethics_events if item.protocol_id == protocol.protocol_id
        ]
        ethics_check = evaluate_ethics_clearance(
            protocol, applicable_events, _time(record.created_at, "evidence created_at")
        )
        claim = claims_by_id.get(record.claim_id) if record.claim_id else None
        if record.claim_id is not None and claim is None:
            raise ValidationError(
                f"scientific evidence {record.evidence_id} references unknown claim {record.claim_id}"
            )
        gates_by_id = {gate.gate_id: gate for gate in run.quality_gates}
        expected_validity_check_ids: list[str] = []
        for check in protocol.measurement_validity_checks:
            gate = gates_by_id.get(check.assessment_gate_id)
            results = (
                gate.details.get("measurement_validity_results", {})
                if gate is not None else {}
            )
            result = results.get(check.check_id) if isinstance(results, dict) else None
            if (
                isinstance(result, dict)
                and result.get("assessment_status")
                == "consistent_with_validity_claim"
            ):
                expected_validity_check_ids.append(check.check_id)
        if record.measurement_validity_check_ids != expected_validity_check_ids:
            raise ValidationError(
                f"scientific evidence {record.evidence_id} measurement-validity check binding no longer reproduces exactly"
            )
        from research_machine.application.claim_integrity import (
            claim_scientific_sha256,
        )
        expected = {
            "check_version": 1,
            "checked_at": record.created_at,
            "protocol_id": protocol.protocol_id,
            "protocol_hash": protocol.protocol_hash,
            "dataset_ids": list(run.dataset_ids),
            "dataset_current_bytes_status": (
                "verified" if run_datasets else "not_applicable"
            ),
            "run_output_current_bytes_verified": True,
            "run_artifact_set_sha256": integrity["artifact_set_sha256"],
            "evidence_payload_sha256": evidence_payload_sha256(record),
            "claim_scientific_sha256": (
                claim_scientific_sha256(claim) if claim is not None else None
            ),
            "ethics_review_status_check": ethics_check,
            "scientific_interpretation_verified": False,
        }
        if record.admission_checks != expected:
            raise ValidationError(
                f"scientific evidence {record.evidence_id} admission receipt no longer reproduces exactly"
            )
