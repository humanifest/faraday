"""Hash-pinned audit prerequisites for prospective action selection.

This module establishes only workflow eligibility from declared, retained bytes.
It does not authenticate an auditor, establish independence, or validate science.
"""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime
import hashlib
import json
from pathlib import Path
from typing import Any, Sequence

from research_machine.domain.errors import IntegrityError, ValidationError
from research_machine.domain.models import (
    ActionAuditClass,
    ActionCandidate,
    AuditPrerequisiteArtifact,
    AuditPrerequisiteContract,
    AuditPrerequisiteSupportingArtifact,
    AuditPrerequisiteSubject,
)


AUDIT_PREREQUISITE_CONCLUSION_CEILING = (
    "Workflow eligibility only; does not establish audit truth, auditor identity "
    "or independence, scientific validity, or evidence eligibility."
)
_SUBJECT_ROLES = {"candidate", "implementation"}
_VERDICTS = {"favorable", "pending", "adverse"}


def _canonical_text(value: object, field: str, *, allow_empty: bool = False) -> str:
    if not isinstance(value, str):
        raise ValidationError(f"{field} must be text")
    if value != value.strip():
        raise ValidationError(f"{field} must be canonical without surrounding whitespace")
    if not allow_empty and not value:
        raise ValidationError(f"{field} must be non-empty text")
    return value


def _sha256(value: object, field: str) -> str:
    text = _canonical_text(value, field)
    if len(text) != 64 or any(character not in "0123456789abcdef" for character in text):
        raise ValidationError(f"{field} must be 64 lowercase hexadecimal characters")
    return text


def _canonical_list(value: object, field: str, *, required: bool = False) -> list[str]:
    if isinstance(value, (str, bytes)) or not isinstance(value, list):
        raise ValidationError(f"{field} must be a list")
    normalized = [_canonical_text(item, f"{field} item") for item in value]
    if len(set(normalized)) != len(normalized):
        raise ValidationError(f"{field} must not repeat items")
    if required and not normalized:
        raise ValidationError(f"{field} must contain at least one item")
    return normalized


def _safe_locator(value: object, field: str) -> str:
    locator = _canonical_text(value, field)
    path = Path(locator)
    if path.is_absolute() or any(part in {"", ".", ".."} for part in path.parts):
        raise ValidationError(f"{field} must be a safe relative path")
    return locator


def _timezone_aware_timestamp(value: object, field: str) -> str:
    text = _canonical_text(value, field)
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValidationError(f"{field} must be an ISO-8601 timestamp") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValidationError(f"{field} must include a timezone")
    return text


def _normalize_subject(subject: AuditPrerequisiteSubject) -> AuditPrerequisiteSubject:
    if not isinstance(subject, AuditPrerequisiteSubject):
        raise ValidationError(
            "audit prerequisite subjects must contain AuditPrerequisiteSubject values"
        )
    role = _canonical_text(subject.subject_role, "audit subject role")
    if role not in _SUBJECT_ROLES:
        raise ValidationError("audit subject role must be candidate or implementation")
    return AuditPrerequisiteSubject(
        subject_role=role,
        subject_id=_canonical_text(subject.subject_id, "audit subject id"),
        artifact_locator=_safe_locator(
            subject.artifact_locator, "audit subject artifact locator"
        ),
        artifact_sha256=_sha256(
            subject.artifact_sha256, "audit subject artifact sha256"
        ),
    )


def _normalize_supporting_artifact(
    artifact: AuditPrerequisiteSupportingArtifact,
) -> AuditPrerequisiteSupportingArtifact:
    if not isinstance(artifact, AuditPrerequisiteSupportingArtifact):
        raise ValidationError(
            "audit supporting_artifacts must contain "
            "AuditPrerequisiteSupportingArtifact values"
        )
    return AuditPrerequisiteSupportingArtifact(
        artifact_role=_canonical_text(
            artifact.artifact_role, "audit supporting artifact role"
        ),
        artifact_locator=_safe_locator(
            artifact.artifact_locator, "audit supporting artifact locator"
        ),
        artifact_sha256=_sha256(
            artifact.artifact_sha256, "audit supporting artifact sha256"
        ),
    )


def _normalize_audit(audit: AuditPrerequisiteArtifact) -> AuditPrerequisiteArtifact:
    if not isinstance(audit, AuditPrerequisiteArtifact):
        raise ValidationError(
            "required_audits must contain AuditPrerequisiteArtifact values"
        )
    subject_role = _canonical_text(
        audit.audited_subject_role, "audit artifact audited subject role"
    )
    if subject_role not in _SUBJECT_ROLES:
        raise ValidationError(
            "audit artifact audited subject role must be candidate or implementation"
        )
    verdict = _canonical_text(audit.verdict, "audit artifact verdict")
    if verdict not in _VERDICTS:
        raise ValidationError(
            "audit artifact verdict must be favorable, pending, or adverse"
        )
    if isinstance(audit.supporting_artifacts, (str, bytes)) or not isinstance(
        audit.supporting_artifacts, Sequence
    ):
        raise ValidationError("audit supporting_artifacts must be a list")
    supporting_artifacts = [
        _normalize_supporting_artifact(item) for item in audit.supporting_artifacts
    ]
    if not supporting_artifacts:
        raise ValidationError(
            "candidate-advancing audits require at least one supporting artifact"
        )
    supporting_locators = [
        item.artifact_locator for item in supporting_artifacts
    ]
    if len(set(supporting_locators)) != len(supporting_locators):
        raise ValidationError("audit supporting artifact locators must be unique")
    return AuditPrerequisiteArtifact(
        audit_id=_canonical_text(audit.audit_id, "audit id"),
        artifact_role=_canonical_text(audit.artifact_role, "audit artifact role"),
        artifact_locator=_safe_locator(
            audit.artifact_locator, "audit artifact locator"
        ),
        artifact_sha256=_sha256(
            audit.artifact_sha256, "audit artifact sha256"
        ),
        audited_subject_role=subject_role,
        audited_subject_id=_canonical_text(
            audit.audited_subject_id, "audit artifact audited subject id"
        ),
        audited_subject_sha256=_sha256(
            audit.audited_subject_sha256,
            "audit artifact audited subject sha256",
        ),
        verdict=verdict,
        scope=_canonical_text(audit.scope, "audit artifact scope"),
        auditor_identity=_canonical_text(
            audit.auditor_identity, "audit artifact auditor identity"
        ),
        audited_at=_timezone_aware_timestamp(
            audit.audited_at, "audit artifact audited_at"
        ),
        limitations=_canonical_list(
            audit.limitations, "audit artifact limitations", required=True
        ),
        supporting_artifacts=supporting_artifacts,
    )


def validate_audit_prerequisite_contract(
    contract: AuditPrerequisiteContract | dict[str, Any],
) -> AuditPrerequisiteContract:
    if isinstance(contract, dict):
        try:
            contract = AuditPrerequisiteContract.from_dict(contract)
        except (KeyError, TypeError, ValueError) as exc:
            raise ValidationError("audit_prerequisite_contract is malformed") from exc
    if not isinstance(contract, AuditPrerequisiteContract):
        raise ValidationError(
            "audit_prerequisite_contract must be an AuditPrerequisiteContract"
        )
    if isinstance(contract.contract_version, bool) or contract.contract_version != 1:
        raise ValidationError("audit prerequisite contract_version must be 1")
    try:
        action_class = ActionAuditClass(contract.action_class)
    except (TypeError, ValueError) as exc:
        raise ValidationError(
            "audit prerequisite action_class must be candidate_advancing, "
            "exposed_evaluator_development, or nonadvancing_information"
        ) from exc
    if isinstance(contract.subjects, (str, bytes)) or not isinstance(
        contract.subjects, Sequence
    ):
        raise ValidationError("audit prerequisite subjects must be a list")
    if isinstance(contract.required_audits, (str, bytes)) or not isinstance(
        contract.required_audits, Sequence
    ):
        raise ValidationError("audit prerequisite required_audits must be a list")
    subjects = [_normalize_subject(item) for item in contract.subjects]
    audits = [_normalize_audit(item) for item in contract.required_audits]
    exposure = _canonical_text(
        contract.evaluator_exposure_statement,
        "evaluator exposure statement",
        allow_empty=True,
    )
    information_statement = _canonical_text(
        contract.nonadvancing_information_statement,
        "nonadvancing information statement",
        allow_empty=True,
    )
    limitations = _canonical_list(
        contract.limitations, "audit prerequisite limitations", required=True
    )
    ceiling = _canonical_text(
        contract.conclusion_ceiling, "audit prerequisite conclusion ceiling"
    )
    if ceiling != AUDIT_PREREQUISITE_CONCLUSION_CEILING:
        raise ValidationError(
            "audit prerequisite conclusion ceiling must use the bounded workflow-only text"
        )

    subject_keys = [(item.subject_role, item.subject_id) for item in subjects]
    if len(set(subject_keys)) != len(subject_keys):
        raise ValidationError("audit prerequisite subjects must not repeat role and id")
    subject_locators = [item.artifact_locator for item in subjects]
    if len(set(subject_locators)) != len(subject_locators):
        raise ValidationError("audit prerequisite subject locators must be unique")
    audit_ids = [item.audit_id for item in audits]
    if len(set(audit_ids)) != len(audit_ids):
        raise ValidationError("audit prerequisite audit ids must be unique")
    audit_locators = [item.artifact_locator for item in audits]
    if len(set(audit_locators)) != len(audit_locators):
        raise ValidationError("audit prerequisite audit locators must be unique")
    if set(subject_locators) & set(audit_locators):
        raise ValidationError("audit and audited-subject artifacts must use distinct locators")
    supporting_locators = [
        supporting.artifact_locator
        for audit in audits
        for supporting in audit.supporting_artifacts
    ]
    if set(supporting_locators) & (set(subject_locators) | set(audit_locators)):
        raise ValidationError(
            "audit supporting artifacts must use locators distinct from audit and "
            "audited-subject artifacts"
        )

    if action_class is ActionAuditClass.EXPOSED_EVALUATOR_DEVELOPMENT:
        if subjects or audits:
            raise ValidationError(
                "exposed evaluator development must not claim candidate audit coverage"
            )
        if not exposure:
            raise ValidationError(
                "exposed evaluator development requires an evaluator exposure statement"
            )
        if information_statement:
            raise ValidationError(
                "exposed evaluator development cannot use the nonadvancing "
                "information statement"
            )
    elif action_class is ActionAuditClass.NONADVANCING_INFORMATION:
        if subjects or audits:
            raise ValidationError(
                "nonadvancing information work must not claim candidate audit coverage"
            )
        if exposure:
            raise ValidationError(
                "nonadvancing information work cannot use the evaluator-development "
                "exposure statement"
            )
        if not information_statement:
            raise ValidationError(
                "nonadvancing information work requires a dedicated canonical statement"
            )
    else:
        if not subjects:
            raise ValidationError(
                "candidate-advancing actions require at least one exact audited subject"
            )
        if not audits:
            raise ValidationError(
                "candidate-advancing actions require at least one audit artifact"
            )
        if exposure:
            raise ValidationError(
                "candidate-advancing actions cannot use the evaluator-development exemption"
            )
        if information_statement:
            raise ValidationError(
                "candidate-advancing actions cannot use the nonadvancing-information "
                "classification"
            )
        subject_by_key = {
            (item.subject_role, item.subject_id): item for item in subjects
        }
        covered: set[tuple[str, str]] = set()
        for audit in audits:
            key = (audit.audited_subject_role, audit.audited_subject_id)
            subject = subject_by_key.get(key)
            if subject is None:
                raise ValidationError(
                    f"audit {audit.audit_id} is scoped to an undeclared audited subject"
                )
            if audit.audited_subject_sha256 != subject.artifact_sha256:
                raise ValidationError(
                    f"audit {audit.audit_id} is scoped to different candidate or "
                    "implementation bytes"
                )
            covered.add(key)
        if covered != set(subject_by_key):
            missing = sorted(
                f"{role}:{subject_id}"
                for role, subject_id in set(subject_by_key) - covered
            )
            raise ValidationError(
                "candidate-advancing audit coverage is incomplete for: "
                + ", ".join(missing)
            )

    return AuditPrerequisiteContract(
        contract_version=1,
        action_class=action_class,
        subjects=subjects,
        required_audits=audits,
        evaluator_exposure_statement=exposure,
        nonadvancing_information_statement=information_statement,
        limitations=limitations,
        conclusion_ceiling=ceiling,
    )


def _audit_payload(audit: AuditPrerequisiteArtifact) -> dict[str, Any]:
    payload = audit.to_dict()
    payload.pop("artifact_locator")
    payload.pop("artifact_sha256")
    return payload


def _canonical_json_sha256(value: object) -> str:
    return hashlib.sha256(
        json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        ).encode("utf-8")
    ).hexdigest()


def _load_exact_json(path: Path) -> tuple[dict[str, Any], bytes]:
    try:
        content = path.read_bytes()
    except OSError as exc:
        raise IntegrityError(
            f"required audit prerequisite artifact is unavailable: {path}"
        ) from exc

    def reject_constant(value: str) -> object:
        raise ValueError(f"non-finite JSON number: {value}")

    def reject_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                raise ValueError(f"duplicate JSON key: {key}")
            result[key] = value
        return result

    try:
        value = json.loads(
            content,
            parse_constant=reject_constant,
            object_pairs_hook=reject_duplicates,
        )
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
        raise IntegrityError(f"audit prerequisite artifact is not strict JSON: {path}") from exc
    if not isinstance(value, dict):
        raise IntegrityError(f"audit prerequisite artifact must contain one JSON object: {path}")
    return value, content


def _resolve_artifact(root: Path, locator: str) -> Path:
    if not root.is_absolute():
        raise ValidationError("audit_artifact_root must be absolute")
    try:
        resolved_root = root.resolve(strict=True)
    except OSError as exc:
        raise IntegrityError(f"audit artifact root is unavailable: {root}") from exc
    if not resolved_root.is_dir():
        raise IntegrityError(f"audit artifact root is not a directory: {root}")
    candidate = resolved_root / locator
    current = resolved_root
    for part in Path(locator).parts:
        current = current / part
        if current.is_symlink():
            raise IntegrityError(
                f"audit prerequisite artifacts must not traverse symlinks: {locator}"
            )
    try:
        resolved = candidate.resolve(strict=True)
        resolved.relative_to(resolved_root)
    except (OSError, ValueError) as exc:
        raise IntegrityError(
            f"audit prerequisite artifact escapes or is missing from its root: {locator}"
        ) from exc
    if not resolved.is_file():
        raise IntegrityError(f"audit prerequisite artifact is not a file: {locator}")
    return resolved


def _receipt_without_hash(receipt: dict[str, Any]) -> dict[str, Any]:
    payload = dict(receipt)
    payload.pop("receipt_sha256", None)
    return payload


def _build_receipt(
    contract: AuditPrerequisiteContract,
    artifact_root: str | Path | None,
) -> dict[str, Any]:
    if contract.action_class is not ActionAuditClass.CANDIDATE_ADVANCING:
        is_evaluator = (
            contract.action_class is ActionAuditClass.EXPOSED_EVALUATOR_DEVELOPMENT
        )
        payload: dict[str, Any] = {
            "contract_version": 1,
            "action_class": contract.action_class.value,
            "status": (
                "exposed_evaluator_development_nonadvancing"
                if is_evaluator
                else "nonadvancing_information"
            ),
            "workflow_eligible": True,
            "candidate_advancement_eligible": False,
            "artifact_root": "",
            "subject_observations": [],
            "audit_observations": [],
            "conclusion_ceiling": contract.conclusion_ceiling,
            "audit_truth_established": False,
            "auditor_identity_authenticated": False,
            "auditor_independence_established": False,
            "scientific_validity_established": False,
            "scientific_evidence_eligible": False,
            "replication_authority_established": False,
        }
        if is_evaluator:
            payload["evaluator_exposure_statement"] = (
                contract.evaluator_exposure_statement
            )
        else:
            payload["nonadvancing_information_statement"] = (
                contract.nonadvancing_information_statement
            )
        payload["receipt_sha256"] = _canonical_json_sha256(payload)
        return payload

    if artifact_root is None:
        raise ValidationError(
            "candidate-advancing actions require audit_artifact_root for current-byte verification"
        )
    root = Path(artifact_root).resolve()
    subject_observations: list[dict[str, Any]] = []
    for subject in contract.subjects:
        path = _resolve_artifact(root, subject.artifact_locator)
        content = path.read_bytes()
        observed = hashlib.sha256(content).hexdigest()
        if observed != subject.artifact_sha256:
            raise IntegrityError(
                f"audited subject hash mismatch for {subject.subject_role}:{subject.subject_id}: "
                f"expected {subject.artifact_sha256}, observed {observed}"
            )
        subject_observations.append(
            {
                **subject.to_dict(),
                "observed_sha256": observed,
                "size_bytes": len(content),
                "status": "matched",
            }
        )

    audit_observations: list[dict[str, Any]] = []
    for audit in contract.required_audits:
        path = _resolve_artifact(root, audit.artifact_locator)
        value, content = _load_exact_json(path)
        observed = hashlib.sha256(content).hexdigest()
        if observed != audit.artifact_sha256:
            raise IntegrityError(
                f"audit artifact hash mismatch for {audit.audit_id}: expected "
                f"{audit.artifact_sha256}, observed {observed}"
            )
        expected_payload = _audit_payload(audit)
        if value != expected_payload:
            raise IntegrityError(
                f"audit artifact {audit.audit_id} content does not match its typed contract"
            )
        supporting_observations: list[dict[str, Any]] = []
        for supporting in audit.supporting_artifacts:
            supporting_path = _resolve_artifact(root, supporting.artifact_locator)
            supporting_content = supporting_path.read_bytes()
            supporting_observed = hashlib.sha256(supporting_content).hexdigest()
            if supporting_observed != supporting.artifact_sha256:
                raise IntegrityError(
                    f"audit supporting artifact hash mismatch for {audit.audit_id} "
                    f"role {supporting.artifact_role}: expected "
                    f"{supporting.artifact_sha256}, observed {supporting_observed}"
                )
            supporting_observations.append(
                {
                    **supporting.to_dict(),
                    "observed_sha256": supporting_observed,
                    "size_bytes": len(supporting_content),
                    "status": "matched",
                }
            )
        audit_observations.append(
            {
                **audit.to_dict(),
                "observed_sha256": observed,
                "size_bytes": len(content),
                "selected_payload_sha256": _canonical_json_sha256(value),
                "supporting_artifact_observations": supporting_observations,
                "status": "matched",
            }
        )

    eligible = all(item.verdict == "favorable" for item in contract.required_audits)
    payload = {
        "contract_version": 1,
        "action_class": contract.action_class.value,
        "status": "passed" if eligible else "not_eligible",
        "workflow_eligible": eligible,
        "candidate_advancement_eligible": eligible,
        "artifact_root": str(root),
        "subject_observations": subject_observations,
        "audit_observations": audit_observations,
        "conclusion_ceiling": contract.conclusion_ceiling,
        "audit_truth_established": False,
        "auditor_identity_authenticated": False,
        "auditor_independence_established": False,
        "scientific_validity_established": False,
        "scientific_evidence_eligible": False,
        "replication_authority_established": False,
    }
    payload["receipt_sha256"] = _canonical_json_sha256(payload)
    return payload


def bind_action_audit_prerequisites(
    candidates: Sequence[ActionCandidate],
    artifact_root: str | Path | None,
) -> list[ActionCandidate]:
    bound: list[ActionCandidate] = []
    for candidate in candidates:
        if candidate.audit_prerequisite_receipt:
            raise ValidationError(
                "audit_prerequisite_receipt is service-generated and must not be supplied"
            )
        if candidate.audit_prerequisite_contract is None:
            raise ValidationError(
                f"action {candidate.action_id} requires an audit_prerequisite_contract"
            )
        contract = validate_audit_prerequisite_contract(
            candidate.audit_prerequisite_contract
        )
        _validate_nonadvancing_candidate_claims(candidate, contract)
        receipt = _build_receipt(contract, artifact_root)
        bound.append(
            replace(
                candidate,
                audit_prerequisite_contract=contract,
                audit_prerequisite_receipt=receipt,
            )
        )
    return bound


def _validate_nonadvancing_candidate_claims(
    candidate: ActionCandidate,
    contract: AuditPrerequisiteContract,
) -> None:
    if (
        contract.action_class is not ActionAuditClass.CANDIDATE_ADVANCING
        and (
            candidate.distinguishes_hypotheses
            or candidate.expected_discrimination != 0
        )
    ):
        raise ValidationError(
            f"action {candidate.action_id} is {contract.action_class.value} and "
            "cannot claim hypothesis discrimination, nonzero expected_discrimination, "
            "or candidate advancement"
        )


def verify_action_audit_prerequisite(candidate: ActionCandidate) -> dict[str, Any]:
    if candidate.audit_prerequisite_contract is None:
        raise ValidationError(
            f"action {candidate.action_id} lacks a current audit prerequisite contract"
        )
    contract = validate_audit_prerequisite_contract(
        candidate.audit_prerequisite_contract
    )
    _validate_nonadvancing_candidate_claims(candidate, contract)
    retained = candidate.audit_prerequisite_receipt
    if not isinstance(retained, dict) or not retained:
        raise IntegrityError(
            f"action {candidate.action_id} lacks its service-generated audit prerequisite receipt"
        )
    retained_hash = retained.get("receipt_sha256")
    if retained_hash != _canonical_json_sha256(_receipt_without_hash(retained)):
        raise IntegrityError(
            f"action {candidate.action_id} audit prerequisite receipt commitment mismatch"
        )
    root = retained.get("artifact_root") or None
    recomputed = _build_receipt(contract, root)
    if recomputed != retained:
        raise IntegrityError(
            f"action {candidate.action_id} audit prerequisite receipt does not replay"
        )
    return retained


def audit_prerequisite_allows_selection(
    candidate: ActionCandidate,
    *,
    allow_legacy_missing: bool = False,
) -> bool:
    if candidate.audit_prerequisite_contract is None:
        if allow_legacy_missing:
            return True
        raise ValidationError(
            f"action {candidate.action_id} lacks a current audit prerequisite contract"
        )
    receipt = verify_action_audit_prerequisite(candidate)
    return receipt.get("workflow_eligible") is True
