"""Write-once exchange artifacts for optional human or model collaborators.

Faraday does not invoke a provider here.  It freezes the context supplied to a
collaborator and validates the collaborator's response as an untrusted proposal.
Neither operation writes canonical inquiry state or creates scientific evidence.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import re
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Any

from research_machine.application.dataset_source_authority import (
    SOURCE_AUTHORITY_BOUNDARY,
    SOURCE_AUTHORITY_TYPES,
    validate_source_authority_timestamp,
)
from research_machine.collaboration.redaction import (
    COLLABORATOR_CONTEXT_REDACTION_MARKER,
    HOST_IDENTITY_KEYS,
    JSON_SELECTOR_KEYS,
    LEGACY_OPERATIONAL_CONTEXT_KEYS,
    OPERATIONAL_CONTEXT_KEYS,
    contains_forbidden_control,
    is_safe_logical_locator,
    is_typed_metadata_location_key,
)
from research_machine.domain.errors import ValidationError


_SHA256 = re.compile(r"[0-9a-f]{64}")
_COLLABORATOR_ARTIFACT_FIELDS = {
    "locator",
    "sha256",
    "size_bytes",
    "media_type",
    "metadata",
}
_REQUIRED_COLLABORATOR_ARTIFACT_FIELDS = {"locator", "sha256"}
_PROPOSAL_FIELDS = {
    "proposal_version",
    "proposal_id",
    "context_sha256",
    "generated_by",
    "purpose",
    "summary",
    "uncertainty",
    "competing_explanations",
    "disconfirming_evidence",
    "limitations",
    "suggestions",
}
_GENERATOR_FIELDS = {"kind", "provider", "model"}
_SUGGESTION_FIELDS = {
    "suggestion_id",
    "kind",
    "statement",
    "rationale",
    "uncertainty",
    "evidence_refs",
    "falsification_conditions",
    "next_test",
    "authority",
}
_GROUNDED_CLAIM_FIELDS = {"statement", "context_refs"}
_GENERATOR_KINDS = {"human", "llm", "hybrid"}
_SUGGESTION_KINDS = {
    "question",
    "hypothesis",
    "design_revision",
    "analysis_interpretation",
    "next_action",
}
_REVIEW_FIELDS = {
    "review_version",
    "review_id",
    "proposal_record_sha256",
    "reviewer",
    "reviewed_at",
    "overall_assessment",
    "decisions",
}
_REVIEWER_FIELDS = {"reviewer_id", "role"}
_DECISION_FIELDS = {"suggestion_id", "disposition", "rationale", "domain_route"}
_WRITE_BOUNDARY_FIELDS = {
    "context_is_read_only",
    "provider_required",
    "canonical_changes_require",
}
_DISPOSITIONS = {"advance_to_domain_review", "reject", "defer"}
_DOMAIN_ROUTES = {
    "question.add",
    "hypothesis.propose",
    "design.revise",
    "protocol.amend",
    "next-action.recommend",
}
_ROUTES_BY_SUGGESTION_KIND = {
    "question": {"question.add"},
    "hypothesis": {"hypothesis.propose"},
    "design_revision": {"design.revise", "protocol.amend"},
    "analysis_interpretation": {"hypothesis.propose", "next-action.recommend"},
    "next_action": {"next-action.recommend"},
}
_PROPOSAL_CONCLUSION_CEILING = (
    "Untrusted review proposal only. It is not a finding, evidence, approval, "
    "protocol amendment, analysis result, or authorization to act."
)
_REVIEW_CONCLUSION_CEILING = (
    "Accountable triage only. Advancement requests a separate domain review; "
    "it does not accept a claim, amend a protocol, create evidence, or authorize action."
)
_AUTHORITY_CLAIM = re.compile(
    r"\b(?:accepts?|accepted|approves?|approved|authorizes?|authorized|"
    r"confirms?|confirmed|proves?|proved|proof|validates?|validated)\b|"
    r"canonical write|canonical action|evidence creation|creates evidence|created evidence|"
    r"human[- ]reviewed|reviewed by human|reviewer identity authenticated|"
    r"authenticated reviewer|authenticated identity"
)
_PROPOSAL_RECORD_FIELDS = {
    "collaborator_proposal_record_version",
    "context_input",
    "context_reference_index",
    "context_scientific_constraints",
    "context_write_boundary",
    "proposal_input",
    "proposal_payload_sha256",
    "proposal_body_grounding",
    "proposal",
    "status",
    "canonical_writes_performed",
    "model_invoked_by_faraday",
    "scientific_evidence_eligible",
    "authorized_actions",
    "conclusion_ceiling",
}
_REVIEW_RECORD_FIELDS = {
    "collaborator_proposal_review_record_version",
    "proposal_record_input",
    "proposal_record_replay",
    "proposal_suggestion_ids",
    "context_reference_index",
    "context_scientific_constraints",
    "context_write_boundary",
    "proposal_body_grounding",
    "review_input",
    "review_payload_sha256",
    "review",
    "reviewed_suggestions",
    "advanced_suggestions",
    "status",
    "reviewer_identity_authenticated",
    "canonical_writes_performed",
    "scientific_evidence_eligible",
    "authorized_actions",
    "conclusion_ceiling",
}
_PROPOSAL_RECORD_REPLAY_FIELDS = {
    "context_reference_index_sha256",
    "context_scientific_constraints_sha256",
    "context_write_boundary_sha256",
    "proposal_body_grounding_sha256",
    "proposal_suggestions_sha256",
}
_LEGACY_PROPOSAL_RECORD_REPLAY_FIELDS = (
    _PROPOSAL_RECORD_REPLAY_FIELDS - {"context_write_boundary_sha256"}
)
_LEGACY_REVIEW_RECORD_FIELDS = _REVIEW_RECORD_FIELDS - {
    "context_reference_index",
    "proposal_record_replay",
    "proposal_suggestion_ids",
}
_LEGACY_REVIEW_RECORD_FIELDS_WITHOUT_REPLAY = _REVIEW_RECORD_FIELDS - {
    "proposal_record_replay"
}
_LEGACY_REVIEW_RECORD_FIELDS_WITHOUT_SUGGESTION_IDS = _REVIEW_RECORD_FIELDS - {
    "proposal_suggestion_ids"
}
_LEGACY_REVIEW_RECORD_FIELDS_WITHOUT_REPLAY_OR_SUGGESTION_IDS = (
    _REVIEW_RECORD_FIELDS - {"proposal_record_replay", "proposal_suggestion_ids"}
)
_LEGACY_REVIEW_RECORD_FIELDS_WITHOUT_CONTEXT_OR_REPLAY = (
    _REVIEW_RECORD_FIELDS - {"context_reference_index", "proposal_record_replay"}
)
_REVIEWED_SUGGESTION_FIELDS = {
    "suggestion_id",
    "suggestion_sha256",
    "suggestion",
    "disposition",
    "rationale",
    "domain_route",
    "manual_domain_review_required",
    "canonical_writes_performed",
    "scientific_evidence_eligible",
}
_ADVANCED_SUGGESTION_FIELDS = {
    "suggestion_id",
    "domain_route",
    "suggestion_sha256",
    "manual_domain_review_required",
    "canonical_writes_performed",
    "scientific_evidence_eligible",
}
_INPUT_FIELDS = {"sha256", "size_bytes"}
_CONTEXT_REFERENCE_FIELDS = {"ref", "kind"}
_BODY_GROUNDING_RECEIPT_FIELDS = {"section", "statement_sha256", "context_refs"}
_CONTEXT_REFERENCE_PREFIXES = {
    "inquiry": "inquiry:",
    "open_question": "question:",
    "claim": "claim:",
    "active_hypothesis": "hypothesis:",
    "pending_hypothesis": "hypothesis:",
    "evidence": "evidence:",
    "dataset": "dataset:",
    "protocol": "protocol:",
    "run": "run:",
    "evidence_status_event": "evidence_status_event:",
    "ethics_review_event": "ethics_review_event:",
}
_CONTEXT_RECORD_COLLECTIONS = {
    "claims": ("claim:", "claim_id"),
    "evidence": ("evidence:", "evidence_id"),
    "evidence_status_events": ("evidence_status_event:", "event_id"),
    "datasets": ("dataset:", "dataset_id"),
    "protocols": ("protocol:", "protocol_id"),
    "runs": ("run:", "run_id"),
    "ethics_review_events": ("ethics_review_event:", "event_id"),
}
_DATASET_INVENTORY_ROLES = {
    "calibration",
    "exploratory",
    "training",
    "confirmatory",
    "replication",
}
_DATASET_INVENTORY_SOURCE_AUTHORITY_FIELDS = {
    "status",
    "source_type",
    "source_name",
    "source_record_id",
    "retrieved_or_collected_at",
    "classification_service_checked",
    "source_truth_verified",
    "custody_verified_by_source_authority",
    "evidence_eligibility_conferred",
    "authority_boundary",
    "limitations",
    "summary",
}
_DATASET_INVENTORY_WORKFLOW_MATERIALIZATION_FIELDS = {
    "status",
    "service_verified",
    "source_receipts_replayed",
    "scientific_evidence_eligible",
    "scientific_interpretation_verified",
    "family_step_id",
    "family_id",
    "source_count",
    "output_sha256",
    "row_count",
    "summary",
}
_NOT_RECORDED_SOURCE_AUTHORITY_SUMMARY = (
    "source route not typed; artifact hashes and dataset role do not "
    "establish source authority"
)
_INVALID_SOURCE_AUTHORITY_SUMMARY = (
    "source authority metadata invalid; source route not trusted until the "
    "dataset rigor finding is resolved"
)
_NOT_RECORDED_WORKFLOW_MATERIALIZATION_SUMMARY = (
    "no workflow materialization verification recorded"
)
_INVALID_WORKFLOW_MATERIALIZATION_SUMMARY = (
    "workflow materialization metadata invalid; local byte-chain not trusted "
    "until the dataset rigor finding is resolved"
)
_WORKFLOW_MATERIALIZATION_LIMIT = (
    "Local Holm-family byte-chain replay only; not evidence eligibility, "
    "scientific interpretation, chronology authentication, executor "
    "independence, gate success, or source-data truth."
)


def _duplicate_pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValidationError(f"duplicate JSON object key: {key}")
        result[key] = value
    return result


def _nonfinite(value: str) -> None:
    raise ValidationError(f"non-finite JSON number is not permitted: {value}")


def _load_object(path: Path, label: str) -> tuple[dict[str, Any], bytes]:
    resolved = path.expanduser().resolve()
    if not resolved.is_file():
        raise ValidationError(f"{label} is not a file: {resolved}")
    content = resolved.read_bytes()
    try:
        value = json.loads(
            content.decode("utf-8"),
            object_pairs_hook=_duplicate_pairs,
            parse_constant=_nonfinite,
        )
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValidationError(f"{label} must be valid UTF-8 JSON: {exc}") from exc
    if not isinstance(value, dict):
        raise ValidationError(f"{label} must contain a JSON object")
    return value, content


def _text(value: Any, field: str, *, allow_empty: bool = False) -> str:
    if not isinstance(value, str) or (not allow_empty and not value.strip()):
        qualifier = "text" if allow_empty else "non-empty text"
        raise ValidationError(f"collaborator proposal {field} must be {qualifier}")
    return value


def _canonical_text(value: Any, field: str, *, allow_empty: bool = False) -> str:
    text = _text(value, field, allow_empty=allow_empty)
    if text != text.strip():
        raise ValidationError(
            f"collaborator proposal {field} must be canonical without surrounding whitespace"
        )
    return text


def _exact_fields(value: dict[str, Any], expected: set[str], label: str) -> None:
    missing = sorted(expected - set(value))
    unknown = sorted(set(value) - expected)
    if missing:
        raise ValidationError(f"{label} missing fields: " + ", ".join(missing))
    if unknown:
        raise ValidationError(f"{label} has unknown fields: " + ", ".join(unknown))


def _canonical_string_array(
    value: Any, field: str, *, label: str, nonempty: bool = True
) -> list[str]:
    if not isinstance(value, list) or (nonempty and not value):
        raise ValidationError(
            f"{label} {field} must be "
            + ("a non-empty" if nonempty else "an")
            + " array of unique non-empty strings"
        )
    if any(not isinstance(item, str) or not item.strip() for item in value):
        raise ValidationError(
            f"{label} {field} must contain only non-empty strings"
        )
    if any(item != item.strip() for item in value):
        raise ValidationError(
            f"{label} {field} must be canonical without surrounding whitespace"
        )
    if len(set(value)) != len(value):
        raise ValidationError(f"{label} {field} must be unique")
    return list(value)


def _string_array(value: Any, field: str, *, nonempty: bool = True) -> list[str]:
    return _canonical_string_array(
        value, field, label="collaborator proposal", nonempty=nonempty
    )


def _validate_refs(
    refs: Any,
    field: str,
    allowed_refs: set[str] | None,
    *,
    nonempty: bool,
    missing_label: str,
) -> list[str]:
    checked = _string_array(refs, field, nonempty=nonempty)
    if allowed_refs is not None:
        unknown_refs = sorted(set(checked) - allowed_refs)
        if unknown_refs:
            raise ValidationError(
                f"{missing_label} references are not present in the frozen context: "
                + ", ".join(unknown_refs)
            )
    return checked


def _validate_body_claims(
    proposal: dict[str, Any], allowed_refs: set[str] | None
) -> list[dict[str, Any]]:
    grounding: list[dict[str, Any]] = []
    require_grounding = bool(allowed_refs)
    for field in ("competing_explanations", "disconfirming_evidence", "limitations"):
        value = proposal[field]
        if not isinstance(value, list) or not value:
            raise ValidationError(
                f"collaborator proposal {field} must be a non-empty array"
            )
        statements: set[str] = set()
        for index, item in enumerate(value):
            item_label = f"{field}[{index}]"
            if isinstance(item, str):
                if require_grounding:
                    raise ValidationError(
                        f"collaborator proposal {item_label} must cite frozen context"
                    )
                statement = _proposal_boundary_text(item, item_label)
                context_refs: list[str] = []
            elif isinstance(item, dict):
                _exact_fields(
                    item,
                    _GROUNDED_CLAIM_FIELDS,
                    f"collaborator proposal {item_label}",
                )
                statement = _proposal_boundary_text(
                    item["statement"], f"{item_label}.statement"
                )
                context_refs = _validate_refs(
                    item["context_refs"],
                    f"{item_label}.context_refs",
                    allowed_refs,
                    nonempty=require_grounding,
                    missing_label=f"collaborator proposal {item_label}",
                )
            else:
                raise ValidationError(
                    f"collaborator proposal {item_label} must be a string or object"
                )
            if statement in statements:
                raise ValidationError(f"collaborator proposal {field} must be unique")
            statements.add(statement)
            grounding.append(
                {
                    "section": field,
                    "statement_sha256": hashlib.sha256(
                        statement.encode("utf-8")
                    ).hexdigest(),
                    "context_refs": context_refs,
                }
            )
    return grounding


def _validate_body_grounding_receipt(
    value: Any,
    allowed_refs: set[str] | None,
    *,
    require_grounding: bool,
) -> list[dict[str, Any]]:
    if not isinstance(value, list) or not value:
        raise ValidationError(
            "collaborator proposal body grounding must be a non-empty array"
        )
    seen: set[tuple[str, str]] = set()
    checked: list[dict[str, Any]] = []
    for index, item in enumerate(value):
        label = f"collaborator proposal body grounding[{index}]"
        if not isinstance(item, dict):
            raise ValidationError(f"{label} must be an object")
        _exact_fields(item, _BODY_GROUNDING_RECEIPT_FIELDS, label)
        section = _canonical_text(item["section"], f"body_grounding[{index}].section")
        if section not in {
            "competing_explanations",
            "disconfirming_evidence",
            "limitations",
        }:
            raise ValidationError(f"{label}.section is unsupported")
        digest = item["statement_sha256"]
        if not isinstance(digest, str) or not _SHA256.fullmatch(digest):
            raise ValidationError(f"{label}.statement_sha256 is invalid")
        context_refs = _validate_refs(
            item["context_refs"],
            f"body_grounding[{index}].context_refs",
            allowed_refs,
            nonempty=require_grounding,
            missing_label=label,
        )
        key = (section, digest)
        if key in seen:
            raise ValidationError(f"duplicate collaborator proposal body grounding: {section}")
        seen.add(key)
        checked.append(
            {
                "section": section,
                "statement_sha256": digest,
                "context_refs": context_refs,
            }
        )
    return checked


def _context_scientific_constraints(
    context: dict[str, Any],
    *,
    allow_legacy_inferential_boundary: bool = False,
) -> list[str]:
    constraints = _canonical_string_array(
        context.get("scientific_constraints"),
        "scientific_constraints",
        label="collaborator context",
    )
    folded = [item.casefold() for item in constraints]
    has_current_inferential_boundary = any(
        "do not claim" in item
        and "causality" in item
        and "mechanism" in item
        and "legal characterization" in item
        and "replication" in item
        for item in folded
    )
    has_legacy_inferential_boundary = allow_legacy_inferential_boundary and any(
        "do not claim" in item
        and "causality" in item
        and "mechanism" in item
        and "replication" in item
        for item in folded
    )
    if not (has_current_inferential_boundary or has_legacy_inferential_boundary):
        raise ValidationError(
            "collaborator context scientific_constraints must include an inferential-boundary warning"
        )
    if not any("do not authorize" in item for item in folded):
        raise ValidationError(
            "collaborator context scientific_constraints must include an authorization-boundary warning"
        )
    return constraints


def _context_write_boundary(context: dict[str, Any]) -> dict[str, Any]:
    boundary = context.get("write_boundary")
    if not isinstance(boundary, dict):
        raise ValidationError("collaborator context write_boundary must be an object")
    _exact_fields(boundary, _WRITE_BOUNDARY_FIELDS, "collaborator context write_boundary")
    if boundary.get("context_is_read_only") is not True:
        raise ValidationError("collaborator context must be read-only")
    if boundary.get("provider_required") is not False:
        raise ValidationError("collaborator context must not require a provider")
    canonical_changes_require = _canonical_string_array(
        boundary.get("canonical_changes_require"),
        "write_boundary.canonical_changes_require",
        label="collaborator context",
    )
    folded = [item.casefold() for item in canonical_changes_require]
    if not any("research" in item and "command" in item for item in folded):
        raise ValidationError(
            "collaborator context write_boundary.canonical_changes_require must identify canonical research commands"
        )
    if not any("review" in item and "gate" in item for item in folded):
        raise ValidationError(
            "collaborator context write_boundary.canonical_changes_require must identify review gates"
        )
    return {
        "context_is_read_only": True,
        "provider_required": False,
        "canonical_changes_require": canonical_changes_require,
    }


def _review_boundary_text(value: Any, field: str) -> str:
    text = _canonical_text(value, field)
    if _AUTHORITY_CLAIM.search(text.casefold()):
        raise ValidationError(
            f"collaborator proposal {field} must not claim acceptance, approval, "
            "authorization, proof, confirmation, validation, evidence creation, "
            "canonical action, human review completion, or authenticated reviewer identity"
        )
    return text


def _proposal_boundary_text(value: Any, field: str) -> str:
    text = _canonical_text(value, field)
    if _AUTHORITY_CLAIM.search(text.casefold()):
        raise ValidationError(
            f"collaborator proposal {field} must not claim acceptance, approval, "
            "authorization, proof, confirmation, validation, evidence creation, "
            "canonical action, human review completion, or authenticated reviewer identity"
        )
    return text


def _bounded_proposal_text_array(
    value: Any, field: str, *, nonempty: bool = True
) -> list[str]:
    return [
        _proposal_boundary_text(item, f"{field} item")
        for item in _string_array(value, field, nonempty=nonempty)
    ]


def _context_reference_ids(context: dict[str, Any]) -> set[str]:
    raw_index = context.get("context_reference_index")
    if raw_index is None:
        return set()
    if not isinstance(raw_index, list):
        raise ValidationError("collaborator context_reference_index must be an array")
    refs: set[str] = set()
    for index, item in enumerate(raw_index):
        if not isinstance(item, dict):
            raise ValidationError(f"collaborator context_reference_index[{index}] must be an object")
        _exact_fields(
            item,
            _CONTEXT_REFERENCE_FIELDS,
            f"collaborator context_reference_index[{index}]",
        )
        ref = item.get("ref")
        kind = item.get("kind")
        if not isinstance(ref, str) or not ref.strip():
            raise ValidationError(f"collaborator context_reference_index[{index}].ref must be non-empty text")
        if ref != ref.strip():
            raise ValidationError(
                f"collaborator context_reference_index[{index}].ref must be canonical without surrounding whitespace"
            )
        if not isinstance(kind, str) or not kind.strip():
            raise ValidationError(f"collaborator context_reference_index[{index}].kind must be non-empty text")
        if kind != kind.strip():
            raise ValidationError(
                f"collaborator context_reference_index[{index}].kind must be canonical without surrounding whitespace"
            )
        prefix = _CONTEXT_REFERENCE_PREFIXES.get(kind)
        if prefix is None:
            raise ValidationError(f"collaborator context_reference_index[{index}].kind is unsupported")
        if not ref.startswith(prefix):
            raise ValidationError(
                f"collaborator context_reference_index[{index}].ref must match kind {kind}"
            )
        if ref in refs:
            raise ValidationError(f"duplicate collaborator context reference: {ref}")
        refs.add(ref)
    return refs


def _context_body_reference_ids(context: dict[str, Any]) -> set[str]:
    refs: set[str] = set()

    def add_ref(ref: str) -> None:
        if ref in refs:
            raise ValidationError(
                f"collaborator context body contains duplicate citable record: {ref}"
            )
        refs.add(ref)

    inquiry = context.get("inquiry")
    if inquiry is not None:
        if not isinstance(inquiry, dict):
            raise ValidationError("collaborator context inquiry must be an object")
        inquiry_id = inquiry.get("inquiry_id")
        if not isinstance(inquiry_id, str) or not inquiry_id.strip():
            raise ValidationError("collaborator context inquiry.inquiry_id must be non-empty text")
        if inquiry_id != inquiry_id.strip():
            raise ValidationError(
                "collaborator context inquiry.inquiry_id must be canonical without surrounding whitespace"
            )
        add_ref(f"inquiry:{inquiry_id}")
    open_questions = context.get("open_questions")
    if open_questions is not None:
        if not isinstance(open_questions, list):
            raise ValidationError("collaborator context open_questions must be an array")
        for index, item in enumerate(open_questions):
            if not isinstance(item, dict):
                raise ValidationError(f"collaborator context open_questions[{index}] must be an object")
            question_id = item.get("question_id")
            if not isinstance(question_id, str) or not question_id.strip():
                raise ValidationError(f"collaborator context open_questions[{index}].question_id must be non-empty text")
            if question_id != question_id.strip():
                raise ValidationError(
                    f"collaborator context open_questions[{index}].question_id must be canonical without surrounding whitespace"
                )
            add_ref(f"question:{question_id}")
    for collection, (prefix, id_field) in _CONTEXT_RECORD_COLLECTIONS.items():
        records = context.get(collection)
        if records is None:
            continue
        if not isinstance(records, list):
            raise ValidationError(f"collaborator context {collection} must be an array")
        for index, item in enumerate(records):
            if not isinstance(item, dict):
                raise ValidationError(f"collaborator context {collection}[{index}] must be an object")
            record_id = item.get(id_field)
            if not isinstance(record_id, str) or not record_id.strip():
                raise ValidationError(
                    f"collaborator context {collection}[{index}].{id_field} must be non-empty text"
                )
            if record_id != record_id.strip():
                raise ValidationError(
                    f"collaborator context {collection}[{index}].{id_field} must be canonical without surrounding whitespace"
                )
            add_ref(prefix + record_id)
    for collection in ("active_hypotheses", "pending_hypotheses"):
        records = context.get(collection)
        if records is None:
            continue
        if not isinstance(records, list):
            raise ValidationError(f"collaborator context {collection} must be an array")
        for index, item in enumerate(records):
            if not isinstance(item, dict):
                raise ValidationError(f"collaborator context {collection}[{index}] must be an object")
            hypothesis_id = item.get("hypothesis_id")
            if not isinstance(hypothesis_id, str) or not hypothesis_id.strip():
                raise ValidationError(
                    f"collaborator context {collection}[{index}].hypothesis_id must be non-empty text"
                )
            if hypothesis_id != hypothesis_id.strip():
                raise ValidationError(
                    f"collaborator context {collection}[{index}].hypothesis_id must be canonical without surrounding whitespace"
                )
            add_ref(f"hypothesis:{hypothesis_id}")
    return refs


def _validate_v2_collaborator_artifact_shape(
    artifact: Any, path: str
) -> None:
    if not isinstance(artifact, dict):
        raise ValidationError(f"collaborator context {path} must be an object")
    missing = _REQUIRED_COLLABORATOR_ARTIFACT_FIELDS - set(artifact)
    unexpected = set(artifact) - _COLLABORATOR_ARTIFACT_FIELDS
    if missing or unexpected:
        raise ValidationError(
            f"collaborator context {path} fields mismatch; "
            f"missing={sorted(missing)} unexpected={sorted(unexpected)}"
        )
    digest = artifact["sha256"]
    if not isinstance(digest, str) or not _SHA256.fullmatch(digest):
        raise ValidationError(
            f"collaborator context {path}.sha256 must be a lowercase SHA-256 digest"
        )
    if "size_bytes" in artifact:
        size_bytes = artifact["size_bytes"]
        is_json_integer = type(size_bytes) is int or (
            type(size_bytes) is float
            and math.isfinite(size_bytes)
            and size_bytes.is_integer()
        )
        if size_bytes is not None and (
            not is_json_integer or size_bytes < 0
        ):
            raise ValidationError(
                f"collaborator context {path}.size_bytes must be a non-negative JSON integer or null"
            )
    if "media_type" in artifact and not isinstance(artifact["media_type"], str):
        raise ValidationError(
            f"collaborator context {path}.media_type must be text"
        )
    if "metadata" in artifact and not isinstance(artifact["metadata"], dict):
        raise ValidationError(
            f"collaborator context {path}.metadata must be an object"
        )


def _validate_context_operational_redaction(
    value: Any,
    path: str,
    *,
    context_version: int,
    dataset_record: bool = False,
    dataset_artifact: bool = False,
    metadata: bool = False,
) -> None:
    if isinstance(value, dict):
        for key, item in value.items():
            child_path = f"{path}.{key}" if path else key
            if dataset_artifact and metadata and contains_forbidden_control(key):
                raise ValidationError(
                    "collaborator context dataset artifact metadata property name "
                    f"at {child_path!r} must not contain C0 or DEL control characters"
                )
            operational_keys = (
                LEGACY_OPERATIONAL_CONTEXT_KEYS
                if context_version == 1
                else OPERATIONAL_CONTEXT_KEYS
            )
            if key in operational_keys:
                if context_version == 1:
                    invalid_operational_value = bool(item) and (
                        item != COLLABORATOR_CONTEXT_REDACTION_MARKER
                    )
                elif (
                    dataset_artifact
                    and metadata
                    and is_typed_metadata_location_key(key)
                ):
                    invalid_operational_value = (
                        item != COLLABORATOR_CONTEXT_REDACTION_MARKER
                    )
                elif key == "current_synthesis_path":
                    invalid_operational_value = item not in (
                        None,
                        COLLABORATOR_CONTEXT_REDACTION_MARKER,
                    )
                else:
                    invalid_operational_value = (
                        item != COLLABORATOR_CONTEXT_REDACTION_MARKER
                    )
                if invalid_operational_value:
                    raise ValidationError(
                        "collaborator context operational field "
                        f"{child_path} must use the canonical redaction marker before freezing"
                    )
            elif context_version == 1:
                _validate_context_operational_redaction(
                    item, child_path, context_version=context_version
                )
            elif key in HOST_IDENTITY_KEYS:
                if item not in (
                    None,
                    "",
                    COLLABORATOR_CONTEXT_REDACTION_MARKER,
                ):
                    raise ValidationError(
                        f"collaborator context host field {child_path} must use the canonical redaction marker"
                    )
            elif key in JSON_SELECTOR_KEYS:
                pass
            elif path == "context" and key == "datasets":
                if not isinstance(item, list):
                    raise ValidationError(
                        "collaborator context datasets must be an array"
                    )
                for index, entry in enumerate(item):
                    _validate_context_operational_redaction(
                        entry,
                        f"{child_path}[{index}]",
                        context_version=context_version,
                        dataset_record=True,
                    )
            elif dataset_record and key == "artifacts":
                if not isinstance(item, list):
                    raise ValidationError(
                        f"collaborator context {child_path} must be an array"
                    )
                for index, entry in enumerate(item):
                    artifact_path = f"{child_path}[{index}]"
                    _validate_v2_collaborator_artifact_shape(entry, artifact_path)
                    _validate_context_operational_redaction(
                        entry,
                        artifact_path,
                        context_version=context_version,
                        dataset_artifact=True,
                    )
            elif (
                dataset_artifact
                and metadata
                and is_typed_metadata_location_key(key)
            ):
                if item != COLLABORATOR_CONTEXT_REDACTION_MARKER:
                    raise ValidationError(
                        f"collaborator context dataset artifact metadata location {child_path} must use the canonical scalar redaction marker"
                    )
            elif key == "locator" or key.endswith("_locator"):
                if dataset_artifact and item != COLLABORATOR_CONTEXT_REDACTION_MARKER:
                    raise ValidationError(
                        f"collaborator context dataset artifact locator {child_path} must use the canonical redaction marker"
                    )
                if not dataset_artifact and not is_safe_logical_locator(item):
                    raise ValidationError(
                        f"collaborator context locator field {child_path} must be a safe relative logical locator or the canonical redaction marker"
                    )
            elif key == "locators" or key.endswith("_locators"):
                if not isinstance(item, list):
                    raise ValidationError(
                        f"collaborator context locator list {child_path} must be an array"
                    )
                if dataset_artifact and any(
                    entry != COLLABORATOR_CONTEXT_REDACTION_MARKER for entry in item
                ):
                    raise ValidationError(
                        f"collaborator context dataset artifact locator list {child_path} must contain only canonical redaction markers"
                    )
                if not dataset_artifact and any(
                    not is_safe_logical_locator(entry) for entry in item
                ):
                    raise ValidationError(
                        f"collaborator context locator list {child_path} must contain only safe relative logical locators or canonical redaction markers"
                    )
            elif key == "path" or key.endswith("_path") or key.endswith("_root"):
                if dataset_artifact and item != COLLABORATOR_CONTEXT_REDACTION_MARKER:
                    raise ValidationError(
                        f"collaborator context dataset artifact path {child_path} must use the canonical redaction marker"
                    )
                if (
                    not dataset_artifact
                    and item
                    and not is_safe_logical_locator(item)
                ):
                    raise ValidationError(
                        f"collaborator context path field {child_path} must be a safe relative logical path or the canonical redaction marker"
                    )
            else:
                _validate_context_operational_redaction(
                    item,
                    child_path,
                    context_version=context_version,
                    dataset_artifact=dataset_artifact,
                    metadata=metadata or key == "metadata",
                )
    elif isinstance(value, list):
        for index, item in enumerate(value):
            _validate_context_operational_redaction(
                item,
                f"{path}[{index}]",
                context_version=context_version,
                dataset_artifact=dataset_artifact,
                metadata=metadata,
            )


def _validate_dataset_inventory_source_authority(
    value: Any, path: str
) -> None:
    if not isinstance(value, dict):
        raise ValidationError(f"collaborator context {path} must be an object")
    _exact_fields(
        value,
        _DATASET_INVENTORY_SOURCE_AUTHORITY_FIELDS,
        f"collaborator context {path}",
    )
    status = _canonical_text(value["status"], f"{path}.status")
    if status not in {"not_recorded", "typed_source_route", "invalid_metadata"}:
        raise ValidationError(
            f"collaborator context {path}.status is unsupported"
        )
    source_type = _canonical_text(value["source_type"], f"{path}.source_type")
    if status in {"not_recorded", "invalid_metadata"}:
        expected_source_type = (
            "not_recorded" if status == "not_recorded" else "invalid_metadata"
        )
        if source_type != expected_source_type:
            raise ValidationError(
                f"collaborator context {path}.source_type must be {expected_source_type}"
            )
        for field in (
            "source_name",
            "source_record_id",
            "retrieved_or_collected_at",
        ):
            if value[field] != "":
                raise ValidationError(
                    f"collaborator context {path}.{field} must be blank when source authority is not recorded"
                )
        if value["classification_service_checked"] is not False:
            raise ValidationError(
                f"collaborator context {path}.classification_service_checked must be false when source authority is not trusted"
            )
        expected_summary = (
            _NOT_RECORDED_SOURCE_AUTHORITY_SUMMARY
            if status == "not_recorded"
            else _INVALID_SOURCE_AUTHORITY_SUMMARY
        )
        if value["summary"] != expected_summary:
            raise ValidationError(
                f"collaborator context {path}.summary must preserve the untrusted source-authority boundary"
            )
    else:
        if source_type not in SOURCE_AUTHORITY_TYPES:
            raise ValidationError(
                f"collaborator context {path}.source_type is unsupported"
            )
        if source_type == "not_recorded":
            raise ValidationError(
                f"collaborator context {path}.source_type cannot be not_recorded for typed source routes"
            )
        _canonical_text(value["source_name"], f"{path}.source_name")
        _canonical_text(
            value["source_record_id"],
            f"{path}.source_record_id",
            allow_empty=True,
        )
        _canonical_text(
            value["retrieved_or_collected_at"],
            f"{path}.retrieved_or_collected_at",
            allow_empty=True,
        )
        if value["retrieved_or_collected_at"]:
            validate_source_authority_timestamp(
                value["retrieved_or_collected_at"],
                f"collaborator context {path}.retrieved_or_collected_at",
            )
        if value["classification_service_checked"] is not True:
            raise ValidationError(
                f"collaborator context {path}.classification_service_checked must be true for typed source routes"
            )
        expected_summary = (
            f"{source_type} source route `{value['source_name']}` "
            "recorded as provenance only; connector, add-on, experiment, import, "
            "or attestation access does not confer evidence eligibility"
        )
        if value["summary"] != expected_summary:
            raise ValidationError(
                f"collaborator context {path}.summary must preserve the typed source-route boundary"
            )
    for field in (
        "source_truth_verified",
        "custody_verified_by_source_authority",
        "evidence_eligibility_conferred",
    ):
        if value[field] is not False:
            raise ValidationError(
                f"collaborator context {path}.{field} must remain false"
            )
    if value["authority_boundary"] != SOURCE_AUTHORITY_BOUNDARY:
        raise ValidationError(
            f"collaborator context {path}.authority_boundary must preserve the source-authority boundary"
        )
    limitations = value["limitations"]
    if not isinstance(limitations, list):
        raise ValidationError(
            f"collaborator context {path}.limitations must be an array"
        )
    if len(set(limitations)) != len(limitations):
        raise ValidationError(
            f"collaborator context {path}.limitations must be unique"
        )
    for index, item in enumerate(limitations):
        _canonical_text(item, f"{path}.limitations[{index}]")


def _validate_dataset_inventory_workflow_materialization(
    value: Any, path: str
) -> None:
    if not isinstance(value, dict):
        raise ValidationError(f"collaborator context {path} must be an object")
    _exact_fields(
        value,
        _DATASET_INVENTORY_WORKFLOW_MATERIALIZATION_FIELDS,
        f"collaborator context {path}",
    )
    status = _canonical_text(value["status"], f"{path}.status")
    if status not in {
        "not_recorded",
        "source_receipts_replayed",
        "invalid_metadata",
    }:
        raise ValidationError(f"collaborator context {path}.status is unsupported")
    for field in (
        "service_verified",
        "source_receipts_replayed",
        "scientific_evidence_eligible",
        "scientific_interpretation_verified",
    ):
        if not isinstance(value[field], bool):
            raise ValidationError(f"collaborator context {path}.{field} must be boolean")
    if value["scientific_evidence_eligible"] is not False:
        raise ValidationError(
            f"collaborator context {path}.scientific_evidence_eligible must remain false"
        )
    if value["scientific_interpretation_verified"] is not False:
        raise ValidationError(
            f"collaborator context {path}.scientific_interpretation_verified must remain false"
        )
    source_count = value["source_count"]
    row_count = value["row_count"]
    if (
        isinstance(source_count, bool)
        or not isinstance(source_count, int)
        or source_count < 0
        or isinstance(row_count, bool)
        or not isinstance(row_count, int)
        or row_count < 0
    ):
        raise ValidationError(
            f"collaborator context {path} source_count and row_count must be non-negative integers"
        )
    if status in {"not_recorded", "invalid_metadata"}:
        if value["service_verified"] is not False or value["source_receipts_replayed"] is not False:
            raise ValidationError(
                f"collaborator context {path} must not claim workflow verification when not trusted"
            )
        if value["family_step_id"] != "" or value["family_id"] != "":
            raise ValidationError(
                f"collaborator context {path} identifiers must be blank when not trusted"
            )
        if value["output_sha256"] is not None:
            raise ValidationError(
                f"collaborator context {path}.output_sha256 must be null when not trusted"
            )
        if source_count != 0 or row_count != 0:
            raise ValidationError(
                f"collaborator context {path} counts must be zero when not trusted"
            )
        expected_summary = (
            _NOT_RECORDED_WORKFLOW_MATERIALIZATION_SUMMARY
            if status == "not_recorded"
            else _INVALID_WORKFLOW_MATERIALIZATION_SUMMARY
        )
        if value["summary"] != expected_summary:
            raise ValidationError(
                f"collaborator context {path}.summary must preserve the untrusted workflow boundary"
            )
        return
    if value["service_verified"] is not True or value["source_receipts_replayed"] is not True:
        raise ValidationError(
            f"collaborator context {path} must retain source receipt replay status"
        )
    _canonical_text(value["family_step_id"], f"{path}.family_step_id")
    _canonical_text(value["family_id"], f"{path}.family_id")
    if source_count < 1 or row_count < 1:
        raise ValidationError(
            f"collaborator context {path} counts must be positive when replayed"
        )
    output_sha256 = value["output_sha256"]
    if not isinstance(output_sha256, str) or not _SHA256.fullmatch(output_sha256):
        raise ValidationError(
            f"collaborator context {path}.output_sha256 must be a lowercase SHA-256 digest"
        )
    if value["summary"] != _WORKFLOW_MATERIALIZATION_LIMIT:
        raise ValidationError(
            f"collaborator context {path}.summary must preserve the workflow materialization boundary"
        )


def _validate_context_dataset_inventory(context: dict[str, Any]) -> None:
    inventory = context.get("dataset_inventory")
    if not isinstance(inventory, dict):
        raise ValidationError("collaborator context dataset_inventory must be an object")
    datasets = context.get("datasets", [])
    if not isinstance(datasets, list):
        raise ValidationError("collaborator context datasets must be an array")
    visible_ids: list[str] = []
    for index, item in enumerate(datasets):
        if not isinstance(item, dict):
            raise ValidationError(f"collaborator context datasets[{index}] must be an object")
        dataset_id = item.get("dataset_id")
        if not isinstance(dataset_id, str) or not dataset_id.strip():
            raise ValidationError(
                f"collaborator context datasets[{index}].dataset_id must be non-empty text"
            )
        if dataset_id != dataset_id.strip():
            raise ValidationError(
                f"collaborator context datasets[{index}].dataset_id must be canonical without surrounding whitespace"
            )
        visible_ids.append(dataset_id)
    rows = inventory.get("datasets")
    if not isinstance(rows, list):
        raise ValidationError(
            "collaborator context dataset_inventory.datasets must be an array"
        )
    row_ids: list[str] = []
    role_counts: dict[str, int] = {}
    synthetic_count = 0
    datasets_with_errors = 0
    for index, row in enumerate(rows):
        if not isinstance(row, dict):
            raise ValidationError(
                f"collaborator context dataset_inventory.datasets[{index}] must be an object"
            )
        dataset_id = _canonical_text(
            row.get("dataset_id", ""),
            f"dataset_inventory.datasets[{index}].dataset_id",
        )
        if dataset_id in row_ids:
            raise ValidationError(
                f"duplicate collaborator context dataset_inventory dataset_id: {dataset_id}"
            )
        row_ids.append(dataset_id)
        role = row.get("role")
        if role not in _DATASET_INVENTORY_ROLES:
            raise ValidationError(
                f"collaborator context dataset_inventory.datasets[{index}].role is unsupported"
            )
        role_counts[role] = role_counts.get(role, 0) + 1
        synthetic = row.get("synthetic")
        if not isinstance(synthetic, bool):
            raise ValidationError(
                f"collaborator context dataset_inventory.datasets[{index}].synthetic must be boolean"
            )
        if synthetic:
            synthetic_count += 1
        if row.get("operational_roots_redacted") is not True:
            raise ValidationError(
                "collaborator context dataset_inventory rows must redact operational roots"
            )
        _validate_dataset_inventory_source_authority(
            row.get("source_authority"),
            f"dataset_inventory.datasets[{index}].source_authority",
        )
        _validate_dataset_inventory_workflow_materialization(
            row.get("workflow_materialization"),
            f"dataset_inventory.datasets[{index}].workflow_materialization",
        )
        findings = row.get("rigor_findings", [])
        if not isinstance(findings, list):
            raise ValidationError(
                f"collaborator context dataset_inventory.datasets[{index}].rigor_findings must be an array"
            )
        if any(
            isinstance(finding, dict) and finding.get("severity") == "error"
            for finding in findings
        ):
            datasets_with_errors += 1
    if sorted(row_ids) != sorted(visible_ids):
        raise ValidationError(
            "collaborator context dataset_inventory must exactly cover visible dataset records"
        )
    expected_count = len(row_ids)
    if inventory.get("registered_dataset_count") != expected_count:
        raise ValidationError(
            "collaborator context dataset_inventory registered_dataset_count disagrees with visible datasets"
        )
    if inventory.get("synthetic_count") != synthetic_count:
        raise ValidationError(
            "collaborator context dataset_inventory synthetic_count disagrees with inventory rows"
        )
    if inventory.get("non_synthetic_count") != expected_count - synthetic_count:
        raise ValidationError(
            "collaborator context dataset_inventory non_synthetic_count disagrees with inventory rows"
        )
    if inventory.get("datasets_with_rigor_errors") != datasets_with_errors:
        raise ValidationError(
            "collaborator context dataset_inventory datasets_with_rigor_errors disagrees with inventory rows"
        )
    if inventory.get("role_counts") != {
        role: role_counts[role] for role in sorted(role_counts)
    }:
        raise ValidationError(
            "collaborator context dataset_inventory role_counts disagree with inventory rows"
        )
    notice = inventory.get("empty_inventory_notice")
    if not isinstance(notice, str):
        raise ValidationError(
            "collaborator context dataset_inventory empty_inventory_notice must be text"
        )
    if expected_count == 0 and not notice:
        raise ValidationError(
            "collaborator context dataset_inventory must explain empty inventories"
        )
    if expected_count > 0 and notice:
        raise ValidationError(
            "collaborator context dataset_inventory empty_inventory_notice must be blank when datasets are present"
        )


def _validate_context_snapshot(context: dict[str, Any]) -> list[str]:
    context_version = context.get("context_version")
    if type(context_version) is not int or context_version not in {1, 2}:
        raise ValidationError("collaborator context_version must be 1 or 2")
    if context_version == 1 and "dataset_inventory" in context:
        raise ValidationError(
            "historical collaborator context_version 1 must not include dataset_inventory"
        )
    if context_version == 2 and "dataset_inventory" not in context:
        raise ValidationError(
            "collaborator context_version 2 requires dataset_inventory"
        )
    _validate_context_operational_redaction(
        context, "context", context_version=context_version
    )
    _context_write_boundary(context)
    _canonical_text(context.get("purpose", ""), "context purpose")
    indexed_refs = _context_reference_ids(context)
    body_refs = _context_body_reference_ids(context)
    missing_from_body = sorted(indexed_refs - body_refs)
    if missing_from_body:
        raise ValidationError(
            "collaborator context_reference_index cites records absent from the frozen context body: "
            + ", ".join(missing_from_body)
        )
    missing_from_index = sorted(body_refs - indexed_refs)
    if missing_from_index:
        raise ValidationError(
            "collaborator context body records are missing from context_reference_index: "
            + ", ".join(missing_from_index)
        )
    if context_version == 2:
        _validate_context_dataset_inventory(context)
    return _context_scientific_constraints(
        context,
        allow_legacy_inferential_boundary=context_version == 1,
    )


def _publish_json(root: Path, filename: str, value: dict[str, Any]) -> bytes:
    resolved = root.expanduser().resolve()
    if resolved.exists():
        raise ValidationError(f"collaboration output path already exists: {resolved}")
    resolved.parent.mkdir(parents=True, exist_ok=True)
    content = (
        json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False) + "\n"
    ).encode("utf-8")
    with tempfile.TemporaryDirectory(
        prefix=f".{resolved.name}-", dir=resolved.parent
    ) as temporary:
        staging = Path(temporary) / resolved.name
        staging.mkdir()
        (staging / filename).write_bytes(content)
        try:
            os.replace(staging, resolved)
        except OSError as exc:
            raise ValidationError(
                f"could not publish collaboration artifact atomically: {exc}"
            ) from exc
    return content


def _sha256_json(value: Any) -> str:
    content = json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False
    )
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


def _advanced_suggestion_entry(
    suggestion_id: str, domain_route: str, suggestion_sha256: str
) -> dict[str, Any]:
    return {
        "suggestion_id": suggestion_id,
        "domain_route": domain_route,
        "suggestion_sha256": suggestion_sha256,
        "manual_domain_review_required": True,
        "canonical_writes_performed": False,
        "scientific_evidence_eligible": False,
    }


def _proposal_record_replay(record: dict[str, Any]) -> dict[str, str]:
    replay = {
        "context_reference_index_sha256": _sha256_json(
            record.get("context_reference_index", [])
        ),
        "context_scientific_constraints_sha256": _sha256_json(
            record["context_scientific_constraints"]
        ),
        "proposal_body_grounding_sha256": _sha256_json(
            record["proposal_body_grounding"]
        ),
        "proposal_suggestions_sha256": _proposal_suggestions_sha256(record),
    }
    if "context_write_boundary" in record:
        replay["context_write_boundary_sha256"] = _sha256_json(
            record["context_write_boundary"]
        )
    return replay


def _proposal_suggestions_sha256(record: dict[str, Any]) -> str:
    proposal = record.get("proposal")
    if isinstance(proposal, dict) and isinstance(proposal.get("suggestions"), list):
        suggestions = proposal["suggestions"]
    else:
        reviewed_suggestions = record.get("reviewed_suggestions")
        suggestions = [
            item.get("suggestion")
            for item in reviewed_suggestions
            if isinstance(item, dict)
        ] if isinstance(reviewed_suggestions, list) else []
    return _sha256_json([_sha256_json(suggestion) for suggestion in suggestions])


def _validate_proposal_record_replay(
    value: Any, record: dict[str, Any]
) -> dict[str, str]:
    if not isinstance(value, dict):
        raise ValidationError(
            "collaborator proposal review record proposal_record_replay must be an object"
        )
    expected_fields = (
        _PROPOSAL_RECORD_REPLAY_FIELDS
        if "context_write_boundary" in record
        else _LEGACY_PROPOSAL_RECORD_REPLAY_FIELDS
    )
    _exact_fields(
        value,
        expected_fields,
        "collaborator proposal review record proposal_record_replay",
    )
    replay: dict[str, str] = {}
    for field in expected_fields:
        digest = value[field]
        if not isinstance(digest, str) or not _SHA256.fullmatch(digest):
            raise ValidationError(
                f"collaborator proposal review record proposal_record_replay.{field} is invalid"
            )
        replay[field] = digest
    expected = _proposal_record_replay(record)
    replay_guardrails = {
        key: value
        for key, value in replay.items()
        if key != "proposal_suggestions_sha256"
    }
    expected_guardrails = {
        key: value
        for key, value in expected.items()
        if key != "proposal_suggestions_sha256"
    }
    if replay_guardrails != expected_guardrails:
        raise ValidationError(
            "collaborator proposal review record proposal_record_replay disagrees with retained proposal-record guardrails"
        )
    return replay


def create_context_snapshot(context: dict[str, Any], output: Path) -> dict[str, Any]:
    """Freeze the exact read-only context sent to an optional collaborator."""
    _validate_context_snapshot(context)
    content = _publish_json(output, "collaborator-context.json", context)
    return {
        "path": str(output.expanduser().resolve()),
        "context_file": str(
            output.expanduser().resolve() / "collaborator-context.json"
        ),
        "context_sha256": hashlib.sha256(content).hexdigest(),
        "context_size_bytes": len(content),
        "provider_required": False,
        "canonical_writes_performed": False,
    }


def _validate_proposal(
    proposal: dict[str, Any], context: dict[str, Any], digest: str
) -> list[dict[str, Any]]:
    _exact_fields(proposal, _PROPOSAL_FIELDS, "collaborator proposal")
    if proposal["proposal_version"] != 1:
        raise ValidationError("collaborator proposal_version must be 1")
    _canonical_text(proposal["proposal_id"], "proposal_id")
    supplied_hash = _text(proposal["context_sha256"], "context_sha256")
    if not _SHA256.fullmatch(supplied_hash) or supplied_hash != digest:
        raise ValidationError("collaborator proposal is not bound to the exact context hash")
    if proposal["purpose"] != context.get("purpose"):
        raise ValidationError("collaborator proposal purpose does not match its context")
    _canonical_text(proposal["purpose"], "purpose")
    for field in ("summary", "uncertainty"):
        _proposal_boundary_text(proposal[field], field)
    allowed_evidence_refs = _context_reference_ids(context)
    proposal_body_grounding = _validate_body_claims(proposal, allowed_evidence_refs)

    generated_by = proposal["generated_by"]
    if not isinstance(generated_by, dict):
        raise ValidationError("collaborator proposal generated_by must be an object")
    _exact_fields(generated_by, _GENERATOR_FIELDS, "collaborator proposal generated_by")
    if generated_by["kind"] not in _GENERATOR_KINDS:
        raise ValidationError("collaborator proposal generated_by.kind is invalid")
    _canonical_text(
        generated_by["provider"], "generated_by.provider", allow_empty=True
    )
    _canonical_text(generated_by["model"], "generated_by.model", allow_empty=True)
    if generated_by["kind"] in {"llm", "hybrid"}:
        _canonical_text(generated_by["provider"], "generated_by.provider")
        _canonical_text(generated_by["model"], "generated_by.model")

    suggestions = proposal["suggestions"]
    if not isinstance(suggestions, list) or not suggestions:
        raise ValidationError("collaborator proposal suggestions must be non-empty")
    identifiers: set[str] = set()
    for index, suggestion in enumerate(suggestions):
        label = f"collaborator proposal suggestion {index + 1}"
        if not isinstance(suggestion, dict):
            raise ValidationError(f"{label} must be an object")
        _exact_fields(suggestion, _SUGGESTION_FIELDS, label)
        suggestion_id = _canonical_text(suggestion["suggestion_id"], "suggestion_id")
        if suggestion_id in identifiers:
            raise ValidationError(f"duplicate collaborator suggestion_id: {suggestion_id}")
        identifiers.add(suggestion_id)
        if suggestion["kind"] not in _SUGGESTION_KINDS:
            raise ValidationError(f"{label} kind is invalid")
        if suggestion["authority"] != "review_only":
            raise ValidationError(f"{label} authority must be review_only")
        for field in ("statement", "rationale", "uncertainty", "next_test"):
            _proposal_boundary_text(suggestion[field], field)
        evidence_refs = _string_array(
            suggestion["evidence_refs"],
            "evidence_refs",
            nonempty=bool(allowed_evidence_refs),
        )
        unknown_refs = sorted(set(evidence_refs) - allowed_evidence_refs)
        if unknown_refs:
            raise ValidationError(
                f"{label} evidence_refs are not present in the frozen context: "
                + ", ".join(unknown_refs)
            )
        _bounded_proposal_text_array(
            suggestion["falsification_conditions"], "falsification_conditions"
        )
    return proposal_body_grounding


def validate_collaborator_proposal(
    context_file: Path,
    expected_context_sha256: str,
    proposal_file: Path,
    output: Path,
) -> dict[str, Any]:
    """Validate and preserve a proposal without accepting or applying it."""
    if not _SHA256.fullmatch(expected_context_sha256):
        raise ValidationError("expected context SHA-256 must be 64 lowercase hex characters")
    context, context_content = _load_object(context_file, "collaborator context")
    context_digest = hashlib.sha256(context_content).hexdigest()
    if context_digest != expected_context_sha256:
        raise ValidationError("collaborator context does not match trusted SHA-256")
    context_scientific_constraints = _validate_context_snapshot(context)
    context_write_boundary = _context_write_boundary(context)

    proposal, proposal_content = _load_object(proposal_file, "collaborator proposal")
    proposal_body_grounding = _validate_proposal(proposal, context, context_digest)
    context_reference_index = context.get("context_reference_index", [])
    record = {
        "collaborator_proposal_record_version": 1,
        "context_input": {
            "sha256": context_digest,
            "size_bytes": len(context_content),
        },
        "context_reference_index": context_reference_index,
        "context_scientific_constraints": context_scientific_constraints,
        "context_write_boundary": context_write_boundary,
        "proposal_input": {
            "sha256": hashlib.sha256(proposal_content).hexdigest(),
            "size_bytes": len(proposal_content),
        },
        "proposal_payload_sha256": _sha256_json(proposal),
        "proposal_body_grounding": proposal_body_grounding,
        "proposal": proposal,
        "status": "pending_human_review",
        "canonical_writes_performed": False,
        "model_invoked_by_faraday": False,
        "scientific_evidence_eligible": False,
        "authorized_actions": [],
        "conclusion_ceiling": _PROPOSAL_CONCLUSION_CEILING,
    }
    content = _publish_json(output, "collaborator-proposal.json", record)
    return {
        "path": str(output.expanduser().resolve()),
        "record_file": str(output.expanduser().resolve() / "collaborator-proposal.json"),
        "record_sha256": hashlib.sha256(content).hexdigest(),
        "context_sha256": context_digest,
        "proposal_sha256": record["proposal_input"]["sha256"],
        "status": "pending_human_review",
        "canonical_writes_performed": False,
        "model_invoked_by_faraday": False,
        "scientific_evidence_eligible": False,
    }


def verify_collaborator_proposal_record(
    proposal_record_file: Path,
    expected_proposal_record_sha256: str,
) -> dict[str, Any]:
    """Replay a retained collaborator proposal record before human review."""
    if not _SHA256.fullmatch(expected_proposal_record_sha256):
        raise ValidationError(
            "expected proposal-record SHA-256 must be 64 lowercase hex characters"
        )
    record, record_content = _load_object(
        proposal_record_file, "collaborator proposal record"
    )
    record_digest = hashlib.sha256(record_content).hexdigest()
    if record_digest != expected_proposal_record_sha256:
        raise ValidationError(
            "collaborator proposal record does not match trusted SHA-256"
        )
    has_context_write_boundary = "context_write_boundary" in record
    has_proposal_payload = "proposal_payload_sha256" in record
    expected_fields = _PROPOSAL_RECORD_FIELDS
    if not has_context_write_boundary:
        expected_fields = expected_fields - {"context_write_boundary"}
    if not has_proposal_payload:
        expected_fields = expected_fields - {"proposal_payload_sha256"}
    _exact_fields(
        record,
        expected_fields,
        "collaborator proposal record",
    )
    if record.get("collaborator_proposal_record_version") != 1:
        raise ValidationError("collaborator proposal record version must be 1")
    if record.get("status") != "pending_human_review":
        raise ValidationError("collaborator proposal record is not pending human review")
    for field, expected in (
        ("canonical_writes_performed", False),
        ("model_invoked_by_faraday", False),
        ("scientific_evidence_eligible", False),
        ("authorized_actions", []),
    ):
        if record.get(field) != expected:
            raise ValidationError(
                f"collaborator proposal record violates its authority boundary: {field}"
            )
    context_input = _validate_input_receipt(
        record.get("context_input"),
        "collaborator proposal record context_input",
    )
    _validate_input_receipt(
        record.get("proposal_input"),
        "collaborator proposal record proposal_input",
    )
    if record["conclusion_ceiling"] != _PROPOSAL_CONCLUSION_CEILING:
        raise ValidationError(
            "collaborator proposal record conclusion ceiling has changed"
        )
    _context_scientific_constraints(
        {"scientific_constraints": record["context_scientific_constraints"]}
    )
    context_write_boundary_status = "legacy_missing"
    if has_context_write_boundary:
        _context_write_boundary({"write_boundary": record["context_write_boundary"]})
        context_write_boundary_status = "verified"
    proposal = record.get("proposal")
    if not isinstance(proposal, dict):
        raise ValidationError("collaborator proposal record has no proposal object")
    proposal_payload_status = "legacy_missing"
    replay_context = {
        "purpose": proposal.get("purpose"),
        "context_reference_index": record["context_reference_index"],
    }
    proposal_body_grounding = _validate_proposal(
        proposal,
        replay_context,
        context_input["sha256"],
    )
    if record["proposal_body_grounding"] != proposal_body_grounding:
        raise ValidationError(
            "collaborator proposal body grounding disagrees with retained proposal"
        )
    if has_proposal_payload:
        _validate_payload_digest(
            record["proposal_payload_sha256"],
            proposal,
            "collaborator proposal record proposal_payload_sha256",
        )
        proposal_payload_status = "verified"
    return {
        "record_sha256": record_digest,
        "record_status": record["status"],
        "context_sha256": context_input["sha256"],
        "proposal_sha256": record["proposal_input"]["sha256"],
        "proposal_id": proposal["proposal_id"],
        "suggestion_count": len(proposal["suggestions"]),
        "body_grounding_count": len(proposal_body_grounding),
        "context_reference_replay": "retained_index_verified",
        "context_write_boundary_replay": context_write_boundary_status,
        "proposal_payload_replay": proposal_payload_status,
        "canonical_writes_performed": False,
        "model_invoked_by_faraday": False,
        "scientific_evidence_eligible": False,
    }


def _rfc3339(value: Any, field: str) -> str:
    text = _text(value, field)
    candidate = text[:-1] + "+00:00" if text.endswith("Z") else text
    try:
        parsed = datetime.fromisoformat(candidate)
    except ValueError as exc:
        raise ValidationError(f"collaborator proposal {field} must be RFC 3339") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValidationError(f"collaborator proposal {field} must include a timezone")
    return text


def adjudicate_collaborator_proposal(
    proposal_record_file: Path,
    expected_proposal_record_sha256: str,
    review_file: Path,
    output: Path,
) -> dict[str, Any]:
    """Record accountable review without translating suggestions into state."""
    if not _SHA256.fullmatch(expected_proposal_record_sha256):
        raise ValidationError(
            "expected proposal-record SHA-256 must be 64 lowercase hex characters"
        )
    record, record_content = _load_object(
        proposal_record_file, "collaborator proposal record"
    )
    record_digest = hashlib.sha256(record_content).hexdigest()
    if record_digest != expected_proposal_record_sha256:
        raise ValidationError(
            "collaborator proposal record does not match trusted SHA-256"
        )
    has_context_write_boundary = "context_write_boundary" in record
    has_proposal_payload = "proposal_payload_sha256" in record
    expected_fields = _PROPOSAL_RECORD_FIELDS
    if not has_context_write_boundary:
        expected_fields = expected_fields - {"context_write_boundary"}
    if not has_proposal_payload:
        expected_fields = expected_fields - {"proposal_payload_sha256"}
    _exact_fields(
        record,
        expected_fields,
        "collaborator proposal record",
    )
    if record.get("collaborator_proposal_record_version") != 1:
        raise ValidationError("collaborator proposal record version must be 1")
    if record.get("status") != "pending_human_review":
        raise ValidationError("collaborator proposal record is not pending human review")
    for field, expected in (
        ("canonical_writes_performed", False),
        ("model_invoked_by_faraday", False),
        ("scientific_evidence_eligible", False),
        ("authorized_actions", []),
    ):
        if record.get(field) != expected:
            raise ValidationError(
                f"collaborator proposal record violates its authority boundary: {field}"
            )
    proposal = record.get("proposal")
    if not isinstance(proposal, dict):
        raise ValidationError("collaborator proposal record has no proposal object")
    context_input = record.get("context_input")
    if not isinstance(context_input, dict):
        raise ValidationError("collaborator proposal record has no context input")
    proposal_input = record.get("proposal_input")
    if not isinstance(proposal_input, dict):
        raise ValidationError("collaborator proposal record has no proposal input")
    for label, value in (("context input", context_input), ("proposal input", proposal_input)):
        _exact_fields(value, _INPUT_FIELDS, f"collaborator proposal record {label}")
        if not isinstance(value["sha256"], str) or not _SHA256.fullmatch(value["sha256"]):
            raise ValidationError(f"collaborator proposal record {label} SHA-256 is invalid")
        if (
            not isinstance(value["size_bytes"], int)
            or isinstance(value["size_bytes"], bool)
            or value["size_bytes"] <= 0
        ):
            raise ValidationError(f"collaborator proposal record {label} size is invalid")
    if record["conclusion_ceiling"] != _PROPOSAL_CONCLUSION_CEILING:
        raise ValidationError(
            "collaborator proposal record conclusion ceiling has changed"
        )
    _context_scientific_constraints(
        {"scientific_constraints": record["context_scientific_constraints"]}
    )
    if has_context_write_boundary:
        _context_write_boundary({"write_boundary": record["context_write_boundary"]})
    replay_context = {
        "purpose": proposal.get("purpose"),
        "context_reference_index": record.get("context_reference_index", []),
    }
    proposal_body_grounding = _validate_proposal(
        proposal, replay_context, context_input.get("sha256", "")
    )
    if record["proposal_body_grounding"] != proposal_body_grounding:
        raise ValidationError(
            "collaborator proposal body grounding disagrees with retained proposal"
        )
    if has_proposal_payload:
        _validate_payload_digest(
            record["proposal_payload_sha256"],
            proposal,
            "collaborator proposal record proposal_payload_sha256",
        )

    review, review_content = _load_object(review_file, "collaborator proposal review")
    _exact_fields(review, _REVIEW_FIELDS, "collaborator proposal review")
    if review["review_version"] != 1:
        raise ValidationError("collaborator proposal review_version must be 1")
    _canonical_text(review["review_id"], "review_id")
    if review["proposal_record_sha256"] != record_digest:
        raise ValidationError("collaborator proposal review is not bound to the exact proposal record")
    _rfc3339(review["reviewed_at"], "reviewed_at")
    _review_boundary_text(review["overall_assessment"], "overall_assessment")
    reviewer = review["reviewer"]
    if not isinstance(reviewer, dict):
        raise ValidationError("collaborator proposal review reviewer must be an object")
    _exact_fields(reviewer, _REVIEWER_FIELDS, "collaborator proposal review reviewer")
    _canonical_text(reviewer["reviewer_id"], "reviewer.reviewer_id")
    _canonical_text(reviewer["role"], "reviewer.role")

    suggestions = proposal["suggestions"]
    proposal_suggestion_ids = [suggestion["suggestion_id"] for suggestion in suggestions]
    suggestions_by_id = {item["suggestion_id"]: item for item in suggestions}
    decisions = review["decisions"]
    if not isinstance(decisions, list):
        raise ValidationError("collaborator proposal review decisions must be an array")
    seen: set[str] = set()
    advanced: list[dict[str, Any]] = []
    decisions_by_id: dict[str, dict[str, Any]] = {}
    for index, decision in enumerate(decisions):
        label = f"collaborator proposal review decision {index + 1}"
        if not isinstance(decision, dict):
            raise ValidationError(f"{label} must be an object")
        _exact_fields(decision, _DECISION_FIELDS, label)
        suggestion_id = _canonical_text(decision["suggestion_id"], "decision.suggestion_id")
        if suggestion_id in seen:
            raise ValidationError(f"duplicate collaborator review suggestion_id: {suggestion_id}")
        if suggestion_id not in suggestions_by_id:
            raise ValidationError(f"unknown collaborator review suggestion_id: {suggestion_id}")
        seen.add(suggestion_id)
        decisions_by_id[suggestion_id] = decision
        disposition = decision["disposition"]
        if disposition not in _DISPOSITIONS:
            raise ValidationError(f"{label} disposition is invalid")
        _review_boundary_text(decision["rationale"], "decision.rationale")
        route = decision["domain_route"]
        if disposition == "advance_to_domain_review":
            if route not in _DOMAIN_ROUTES:
                raise ValidationError(f"{label} domain_route is invalid")
            kind = suggestions_by_id[suggestion_id]["kind"]
            if route not in _ROUTES_BY_SUGGESTION_KIND[kind]:
                raise ValidationError(
                    f"{label} domain_route is incompatible with suggestion kind {kind}"
                )
            advanced.append(
                _advanced_suggestion_entry(
                    suggestion_id,
                    route,
                    _sha256_json(suggestions_by_id[suggestion_id]),
                )
            )
        elif route != "none":
            raise ValidationError(
                f"{label} domain_route must be none unless advanced to domain review"
            )
    missing = sorted(set(suggestions_by_id) - seen)
    if missing:
        raise ValidationError(
            "collaborator proposal review must decide every suggestion; missing: "
            + ", ".join(missing)
        )
    reviewed_suggestions = []
    for suggestion in suggestions:
        suggestion_id = suggestion["suggestion_id"]
        decision = decisions_by_id[suggestion_id]
        reviewed_suggestions.append({
            "suggestion_id": suggestion_id,
            "suggestion_sha256": _sha256_json(suggestion),
            "suggestion": suggestion,
            "disposition": decision["disposition"],
            "rationale": decision["rationale"],
            "domain_route": decision["domain_route"],
            "manual_domain_review_required": (
                decision["disposition"] == "advance_to_domain_review"
            ),
            "canonical_writes_performed": False,
            "scientific_evidence_eligible": False,
        })

    adjudication = {
        "collaborator_proposal_review_record_version": 1,
        "proposal_record_input": {
            "sha256": record_digest,
            "size_bytes": len(record_content),
        },
        "proposal_record_replay": _proposal_record_replay(record),
        "proposal_suggestion_ids": proposal_suggestion_ids,
        "context_reference_index": record["context_reference_index"],
        "context_scientific_constraints": record["context_scientific_constraints"],
        "proposal_body_grounding": record["proposal_body_grounding"],
        "review_input": {
            "sha256": hashlib.sha256(review_content).hexdigest(),
            "size_bytes": len(review_content),
        },
        "review_payload_sha256": _sha256_json(review),
        "review": review,
        "reviewed_suggestions": reviewed_suggestions,
        "advanced_suggestions": advanced,
        "status": "reviewed_requires_manual_domain_action",
        "reviewer_identity_authenticated": False,
        "canonical_writes_performed": False,
        "scientific_evidence_eligible": False,
        "authorized_actions": [],
        "conclusion_ceiling": _REVIEW_CONCLUSION_CEILING,
    }
    if has_context_write_boundary:
        adjudication["context_write_boundary"] = record["context_write_boundary"]
    content = _publish_json(output, "collaborator-proposal-review.json", adjudication)
    return {
        "path": str(output.expanduser().resolve()),
        "record_file": str(output.expanduser().resolve() / "collaborator-proposal-review.json"),
        "record_sha256": hashlib.sha256(content).hexdigest(),
        "proposal_record_sha256": record_digest,
        "status": adjudication["status"],
        "advanced_suggestion_count": len(advanced),
        "canonical_writes_performed": False,
        "scientific_evidence_eligible": False,
    }


def _validate_input_receipt(value: Any, label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValidationError(f"{label} must be an object")
    _exact_fields(value, _INPUT_FIELDS, label)
    if not isinstance(value["sha256"], str) or not _SHA256.fullmatch(value["sha256"]):
        raise ValidationError(f"{label} SHA-256 is invalid")
    if (
        not isinstance(value["size_bytes"], int)
        or isinstance(value["size_bytes"], bool)
        or value["size_bytes"] <= 0
    ):
        raise ValidationError(f"{label} size is invalid")
    return value


def _validate_payload_digest(digest: Any, payload: Any, label: str) -> None:
    if not isinstance(digest, str) or not _SHA256.fullmatch(digest):
        raise ValidationError(f"{label} is invalid")
    if digest != _sha256_json(payload):
        raise ValidationError(f"{label} does not match retained payload")


def verify_collaborator_review_record(
    review_record_file: Path,
    expected_review_record_sha256: str,
) -> dict[str, Any]:
    """Replay a collaborator review record without trusting its summary fields."""
    if not _SHA256.fullmatch(expected_review_record_sha256):
        raise ValidationError(
            "expected review-record SHA-256 must be 64 lowercase hex characters"
        )
    record, record_content = _load_object(
        review_record_file, "collaborator proposal review record"
    )
    record_digest = hashlib.sha256(record_content).hexdigest()
    if record_digest != expected_review_record_sha256:
        raise ValidationError(
            "collaborator proposal review record does not match trusted SHA-256"
        )
    context_reference_status = "verified"
    proposal_record_replay_status = "verified"
    proposal_suggestion_replay_status = "verified"
    has_context_reference_index = "context_reference_index" in record
    has_proposal_record_replay = "proposal_record_replay" in record
    has_proposal_suggestion_ids = "proposal_suggestion_ids" in record
    has_context_write_boundary = "context_write_boundary" in record
    has_review_payload = "review_payload_sha256" in record

    def fields_for_boundary(expected: set[str]) -> set[str]:
        fields = expected if has_context_write_boundary else expected - {"context_write_boundary"}
        return fields if has_review_payload else fields - {"review_payload_sha256"}

    if (
        has_context_reference_index
        and has_proposal_record_replay
        and has_proposal_suggestion_ids
    ):
        _exact_fields(
            record,
            fields_for_boundary(_REVIEW_RECORD_FIELDS),
            "collaborator proposal review record",
        )
    elif has_context_reference_index and has_proposal_record_replay:
        _exact_fields(
            record,
            fields_for_boundary(_LEGACY_REVIEW_RECORD_FIELDS_WITHOUT_SUGGESTION_IDS),
            "collaborator proposal review record",
        )
        proposal_suggestion_replay_status = "legacy_missing"
    elif has_context_reference_index and has_proposal_suggestion_ids:
        _exact_fields(
            record,
            fields_for_boundary(_LEGACY_REVIEW_RECORD_FIELDS_WITHOUT_REPLAY),
            "collaborator proposal review record",
        )
        proposal_record_replay_status = "legacy_missing"
    elif has_context_reference_index:
        _exact_fields(
            record,
            fields_for_boundary(
                _LEGACY_REVIEW_RECORD_FIELDS_WITHOUT_REPLAY_OR_SUGGESTION_IDS
            ),
            "collaborator proposal review record",
        )
        proposal_record_replay_status = "legacy_missing"
        proposal_suggestion_replay_status = "legacy_missing"
    elif not has_context_reference_index and not has_proposal_record_replay:
        expected = (
            _LEGACY_REVIEW_RECORD_FIELDS_WITHOUT_CONTEXT_OR_REPLAY
            if has_proposal_suggestion_ids else _LEGACY_REVIEW_RECORD_FIELDS
        )
        _exact_fields(
            record,
            fields_for_boundary(expected),
            "collaborator proposal review record",
        )
        context_reference_status = "legacy_missing"
        proposal_record_replay_status = "legacy_missing"
        if not has_proposal_suggestion_ids:
            proposal_suggestion_replay_status = "legacy_missing"
    else:
        raise ValidationError(
            "collaborator proposal review record retained replay fields require context_reference_index"
        )
    if record.get("collaborator_proposal_review_record_version") != 1:
        raise ValidationError("collaborator proposal review record version must be 1")
    if record.get("status") != "reviewed_requires_manual_domain_action":
        raise ValidationError("collaborator proposal review record status is invalid")
    for field, expected in (
        ("reviewer_identity_authenticated", False),
        ("canonical_writes_performed", False),
        ("scientific_evidence_eligible", False),
        ("authorized_actions", []),
    ):
        if record.get(field) != expected:
            raise ValidationError(
                f"collaborator proposal review record violates its authority boundary: {field}"
            )
    _validate_input_receipt(
        record.get("proposal_record_input"),
        "collaborator proposal review record proposal_record_input",
    )
    _validate_input_receipt(
        record.get("review_input"),
        "collaborator proposal review record review_input",
    )
    if record["conclusion_ceiling"] != _REVIEW_CONCLUSION_CEILING:
        raise ValidationError(
            "collaborator proposal review record conclusion ceiling has changed"
        )
    _context_scientific_constraints(
        {"scientific_constraints": record["context_scientific_constraints"]}
    )
    context_write_boundary_status = "legacy_missing"
    if has_context_write_boundary:
        _context_write_boundary({"write_boundary": record["context_write_boundary"]})
        context_write_boundary_status = "verified"
    if has_proposal_record_replay:
        _validate_proposal_record_replay(
            record["proposal_record_replay"],
            record,
        )
    allowed_evidence_refs = (
        _context_reference_ids(
            {"context_reference_index": record["context_reference_index"]}
        )
        if context_reference_status == "verified"
        else None
    )
    _validate_body_grounding_receipt(
        record["proposal_body_grounding"],
        allowed_evidence_refs,
        require_grounding=bool(allowed_evidence_refs),
    )
    proposal_suggestion_ids: list[str] | None = None
    proposal_suggestion_id_set: set[str] | None = None
    if has_proposal_suggestion_ids:
        proposal_suggestion_ids = _canonical_string_array(
            record["proposal_suggestion_ids"],
            "proposal_suggestion_ids",
            label="collaborator proposal review record",
        )
        if not proposal_suggestion_ids:
            raise ValidationError(
                "collaborator proposal review record proposal_suggestion_ids must be non-empty"
            )
        proposal_suggestion_id_set = set(proposal_suggestion_ids)

    review = record["review"]
    if not isinstance(review, dict):
        raise ValidationError("collaborator proposal review record review must be an object")
    review_payload_status = "legacy_missing"
    _exact_fields(review, _REVIEW_FIELDS, "collaborator proposal review")
    if review["review_version"] != 1:
        raise ValidationError("collaborator proposal review_version must be 1")
    if review["proposal_record_sha256"] != record["proposal_record_input"]["sha256"]:
        raise ValidationError(
            "collaborator proposal review record review is bound to a different proposal record"
        )
    _canonical_text(review["review_id"], "review_id")
    _rfc3339(review["reviewed_at"], "reviewed_at")
    _review_boundary_text(review["overall_assessment"], "overall_assessment")
    reviewer = review["reviewer"]
    if not isinstance(reviewer, dict):
        raise ValidationError("collaborator proposal review reviewer must be an object")
    _exact_fields(reviewer, _REVIEWER_FIELDS, "collaborator proposal review reviewer")
    _canonical_text(reviewer["reviewer_id"], "reviewer.reviewer_id")
    _canonical_text(reviewer["role"], "reviewer.role")
    decisions = review["decisions"]
    if not isinstance(decisions, list):
        raise ValidationError("collaborator proposal review decisions must be an array")
    decisions_by_id: dict[str, dict[str, Any]] = {}
    for index, decision in enumerate(decisions):
        label = f"collaborator proposal review decision {index + 1}"
        if not isinstance(decision, dict):
            raise ValidationError(f"{label} must be an object")
        _exact_fields(decision, _DECISION_FIELDS, label)
        suggestion_id = _canonical_text(decision["suggestion_id"], "decision.suggestion_id")
        if suggestion_id in decisions_by_id:
            raise ValidationError(f"duplicate collaborator review suggestion_id: {suggestion_id}")
        disposition = decision["disposition"]
        if disposition not in _DISPOSITIONS:
            raise ValidationError(f"{label} disposition is invalid")
        _review_boundary_text(decision["rationale"], "decision.rationale")
        decisions_by_id[suggestion_id] = decision

    reviewed_suggestions = record["reviewed_suggestions"]
    if not isinstance(reviewed_suggestions, list) or not reviewed_suggestions:
        raise ValidationError(
            "collaborator proposal review record reviewed_suggestions must be non-empty"
        )
    reviewed_ids: set[str] = set()
    reviewed_suggestion_sha256s: list[str] = []
    advanced: list[dict[str, Any]] = []
    for index, item in enumerate(reviewed_suggestions):
        label = f"collaborator proposal reviewed_suggestion {index + 1}"
        if not isinstance(item, dict):
            raise ValidationError(f"{label} must be an object")
        _exact_fields(item, _REVIEWED_SUGGESTION_FIELDS, label)
        suggestion_id = _canonical_text(item["suggestion_id"], "reviewed_suggestion.suggestion_id")
        if suggestion_id in reviewed_ids:
            raise ValidationError(f"duplicate collaborator reviewed_suggestion: {suggestion_id}")
        if (
            proposal_suggestion_id_set is not None
            and suggestion_id not in proposal_suggestion_id_set
        ):
            raise ValidationError(
                f"{label} is not present in the retained proposal suggestion set"
            )
        reviewed_ids.add(suggestion_id)
        if suggestion_id not in decisions_by_id:
            raise ValidationError(f"{label} has no matching review decision")
        suggestion = item["suggestion"]
        if not isinstance(suggestion, dict):
            raise ValidationError(f"{label} suggestion must be an object")
        _exact_fields(suggestion, _SUGGESTION_FIELDS, f"{label} suggestion")
        if suggestion.get("suggestion_id") != suggestion_id:
            raise ValidationError(f"{label} suggestion_id disagrees with embedded suggestion")
        if suggestion["kind"] not in _SUGGESTION_KINDS:
            raise ValidationError(f"{label} suggestion kind is invalid")
        if suggestion["authority"] != "review_only":
            raise ValidationError(f"{label} suggestion authority must be review_only")
        for field in ("statement", "rationale", "uncertainty", "next_test"):
            _proposal_boundary_text(suggestion[field], f"{label}.{field}")
        evidence_refs = _string_array(
            suggestion["evidence_refs"],
            f"{label}.evidence_refs",
            nonempty=bool(allowed_evidence_refs),
        )
        if allowed_evidence_refs is not None:
            unknown_refs = sorted(set(evidence_refs) - allowed_evidence_refs)
            if unknown_refs:
                raise ValidationError(
                    f"{label} evidence_refs are not present in the retained context: "
                    + ", ".join(unknown_refs)
                )
        _bounded_proposal_text_array(
            suggestion["falsification_conditions"],
            f"{label}.falsification_conditions",
        )
        suggestion_sha256 = item["suggestion_sha256"]
        if not isinstance(suggestion_sha256, str) or not _SHA256.fullmatch(suggestion_sha256):
            raise ValidationError(f"{label} suggestion_sha256 is invalid")
        if suggestion_sha256 != _sha256_json(suggestion):
            raise ValidationError(f"{label} suggestion_sha256 does not match the suggestion")
        reviewed_suggestion_sha256s.append(suggestion_sha256)
        decision = decisions_by_id[suggestion_id]
        for field in ("disposition", "rationale", "domain_route"):
            if item[field] != decision[field]:
                raise ValidationError(f"{label} {field} disagrees with the review decision")
        if item["canonical_writes_performed"] is not False:
            raise ValidationError(f"{label} violates its canonical write boundary")
        if item["scientific_evidence_eligible"] is not False:
            raise ValidationError(f"{label} violates its evidence boundary")
        if item["manual_domain_review_required"] is not (
            decision["disposition"] == "advance_to_domain_review"
        ):
            raise ValidationError(f"{label} manual review flag disagrees with disposition")
        route = decision["domain_route"]
        if decision["disposition"] == "advance_to_domain_review":
            kind = suggestion["kind"]
            if route not in _ROUTES_BY_SUGGESTION_KIND.get(kind, set()):
                raise ValidationError(
                    f"{label} domain_route is incompatible with suggestion kind {kind}"
                )
            advanced.append(
                _advanced_suggestion_entry(
                    suggestion_id,
                    route,
                    suggestion_sha256,
                )
            )
        elif route != "none":
            raise ValidationError(f"{label} domain_route must be none unless advanced")
    if proposal_suggestion_ids is not None:
        if proposal_suggestion_id_set is None:
            raise ValidationError(
                "collaborator proposal review record proposal_suggestion_ids are invalid"
            )
        missing_decisions = sorted(proposal_suggestion_id_set - set(decisions_by_id))
        extra_decisions = sorted(set(decisions_by_id) - proposal_suggestion_id_set)
        if missing_decisions or extra_decisions:
            raise ValidationError(
                "collaborator proposal review decisions must exactly cover the "
                "retained proposal suggestions"
            )
        reviewed_order = [item["suggestion_id"] for item in reviewed_suggestions]
        if reviewed_order != proposal_suggestion_ids:
            raise ValidationError(
                "collaborator proposal reviewed_suggestions must retain the "
                "proposal suggestion order and coverage"
            )
    if has_proposal_record_replay:
        proposal_suggestions_sha256 = record["proposal_record_replay"].get(
            "proposal_suggestions_sha256"
        )
        if proposal_suggestions_sha256 != _sha256_json(reviewed_suggestion_sha256s):
            raise ValidationError(
                "collaborator proposal review record proposal_record_replay "
                "disagrees with retained proposal suggestion snapshots"
            )
    missing = sorted(set(decisions_by_id) - reviewed_ids)
    if missing:
        raise ValidationError(
            "collaborator proposal review record omits reviewed suggestions: "
            + ", ".join(missing)
        )
    if has_review_payload:
        _validate_payload_digest(
            record["review_payload_sha256"],
            review,
            "collaborator proposal review record review_payload_sha256",
        )
        review_payload_status = "verified"
    record_advanced = record["advanced_suggestions"]
    if not isinstance(record_advanced, list):
        raise ValidationError(
            "collaborator proposal review record advanced_suggestions must be an array"
        )
    for index, item in enumerate(record_advanced):
        label = f"collaborator proposal advanced_suggestion {index + 1}"
        if not isinstance(item, dict):
            raise ValidationError(f"{label} must be an object")
        _exact_fields(item, _ADVANCED_SUGGESTION_FIELDS, label)
    if record_advanced != advanced:
        raise ValidationError(
            "collaborator proposal review record advanced_suggestions disagrees with reviewed suggestions"
        )
    return {
        "record_sha256": record_digest,
        "status": record["status"],
        "reviewed_suggestion_count": len(reviewed_suggestions),
        "advanced_suggestion_count": len(advanced),
        "context_reference_replay": context_reference_status,
        "context_write_boundary_replay": context_write_boundary_status,
        "proposal_record_replay": proposal_record_replay_status,
        "proposal_suggestion_replay": proposal_suggestion_replay_status,
        "review_payload_replay": review_payload_status,
        "canonical_writes_performed": False,
        "scientific_evidence_eligible": False,
    }
