"""Write-once exchange artifacts for optional human or model collaborators.

Faraday does not invoke a provider here.  It freezes the context supplied to a
collaborator and validates the collaborator's response as an untrusted proposal.
Neither operation writes canonical inquiry state or creates scientific evidence.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Any

from research_machine.domain.errors import ValidationError


_SHA256 = re.compile(r"[0-9a-f]{64}")
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
_PROPOSAL_RECORD_FIELDS = {
    "collaborator_proposal_record_version",
    "context_input",
    "context_reference_index",
    "context_scientific_constraints",
    "proposal_input",
    "proposal",
    "status",
    "canonical_writes_performed",
    "model_invoked_by_faraday",
    "scientific_evidence_eligible",
    "authorized_actions",
    "conclusion_ceiling",
}
_INPUT_FIELDS = {"sha256", "size_bytes"}
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
    "ethics_review_event": "ethics_review_event:",
}


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


def _context_scientific_constraints(context: dict[str, Any]) -> list[str]:
    constraints = _canonical_string_array(
        context.get("scientific_constraints"),
        "scientific_constraints",
        label="collaborator context",
    )
    folded = [item.casefold() for item in constraints]
    if not any("causal" in item for item in folded):
        raise ValidationError(
            "collaborator context scientific_constraints must include an inferential-boundary warning"
        )
    if not any("authoriz" in item for item in folded):
        raise ValidationError(
            "collaborator context scientific_constraints must include an authorization-boundary warning"
        )
    return constraints


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


def _validate_context_snapshot(context: dict[str, Any]) -> list[str]:
    if context.get("context_version") != 1:
        raise ValidationError("collaborator context_version must be 1")
    boundary = context.get("write_boundary")
    if not isinstance(boundary, dict):
        raise ValidationError("collaborator context write_boundary must be an object")
    if boundary.get("context_is_read_only") is not True:
        raise ValidationError("collaborator context must be read-only")
    if boundary.get("provider_required") is not False:
        raise ValidationError("collaborator context must not require a provider")
    _canonical_text(context.get("purpose", ""), "context purpose", allow_empty=True)
    _context_reference_ids(context)
    return _context_scientific_constraints(context)


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


def _sha256_json(value: dict[str, Any]) -> str:
    content = json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False
    )
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


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


def _validate_proposal(proposal: dict[str, Any], context: dict[str, Any], digest: str) -> None:
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
        _text(proposal[field], field)
    for field in ("competing_explanations", "disconfirming_evidence", "limitations"):
        _string_array(proposal[field], field)
    allowed_evidence_refs = _context_reference_ids(context)

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
            _text(suggestion[field], field)
        evidence_refs = _string_array(
            suggestion["evidence_refs"], "evidence_refs", nonempty=False
        )
        unknown_refs = sorted(set(evidence_refs) - allowed_evidence_refs)
        if unknown_refs:
            raise ValidationError(
                f"{label} evidence_refs are not present in the frozen context: "
                + ", ".join(unknown_refs)
            )
        _string_array(
            suggestion["falsification_conditions"], "falsification_conditions"
        )


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

    proposal, proposal_content = _load_object(proposal_file, "collaborator proposal")
    _validate_proposal(proposal, context, context_digest)
    context_reference_index = context.get("context_reference_index", [])
    record = {
        "collaborator_proposal_record_version": 1,
        "context_input": {
            "sha256": context_digest,
            "size_bytes": len(context_content),
        },
        "context_reference_index": context_reference_index,
        "context_scientific_constraints": context_scientific_constraints,
        "proposal_input": {
            "sha256": hashlib.sha256(proposal_content).hexdigest(),
            "size_bytes": len(proposal_content),
        },
        "proposal": proposal,
        "status": "pending_human_review",
        "canonical_writes_performed": False,
        "model_invoked_by_faraday": False,
        "scientific_evidence_eligible": False,
        "authorized_actions": [],
        "conclusion_ceiling": (
            "Untrusted review proposal only. It is not a finding, evidence, approval, "
            "protocol amendment, analysis result, or authorization to act."
        ),
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
    _exact_fields(record, _PROPOSAL_RECORD_FIELDS, "collaborator proposal record")
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
    _text(record["conclusion_ceiling"], "record.conclusion_ceiling")
    _context_scientific_constraints(
        {"scientific_constraints": record["context_scientific_constraints"]}
    )
    replay_context = {
        "purpose": proposal.get("purpose"),
        "context_reference_index": record.get("context_reference_index", []),
    }
    _validate_proposal(proposal, replay_context, context_input.get("sha256", ""))

    review, review_content = _load_object(review_file, "collaborator proposal review")
    _exact_fields(review, _REVIEW_FIELDS, "collaborator proposal review")
    if review["review_version"] != 1:
        raise ValidationError("collaborator proposal review_version must be 1")
    _canonical_text(review["review_id"], "review_id")
    if review["proposal_record_sha256"] != record_digest:
        raise ValidationError("collaborator proposal review is not bound to the exact proposal record")
    _rfc3339(review["reviewed_at"], "reviewed_at")
    _text(review["overall_assessment"], "overall_assessment")
    reviewer = review["reviewer"]
    if not isinstance(reviewer, dict):
        raise ValidationError("collaborator proposal review reviewer must be an object")
    _exact_fields(reviewer, _REVIEWER_FIELDS, "collaborator proposal review reviewer")
    _canonical_text(reviewer["reviewer_id"], "reviewer.reviewer_id")
    _canonical_text(reviewer["role"], "reviewer.role")

    suggestions = proposal["suggestions"]
    suggestions_by_id = {item["suggestion_id"]: item for item in suggestions}
    decisions = review["decisions"]
    if not isinstance(decisions, list):
        raise ValidationError("collaborator proposal review decisions must be an array")
    seen: set[str] = set()
    advanced: list[dict[str, str]] = []
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
        _text(decision["rationale"], "decision.rationale")
        route = decision["domain_route"]
        if disposition == "advance_to_domain_review":
            if route not in _DOMAIN_ROUTES:
                raise ValidationError(f"{label} domain_route is invalid")
            kind = suggestions_by_id[suggestion_id]["kind"]
            if route not in _ROUTES_BY_SUGGESTION_KIND[kind]:
                raise ValidationError(
                    f"{label} domain_route is incompatible with suggestion kind {kind}"
                )
            advanced.append({"suggestion_id": suggestion_id, "domain_route": route})
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
        "context_scientific_constraints": record["context_scientific_constraints"],
        "review_input": {
            "sha256": hashlib.sha256(review_content).hexdigest(),
            "size_bytes": len(review_content),
        },
        "review": review,
        "reviewed_suggestions": reviewed_suggestions,
        "advanced_suggestions": advanced,
        "status": "reviewed_requires_manual_domain_action",
        "reviewer_identity_authenticated": False,
        "canonical_writes_performed": False,
        "scientific_evidence_eligible": False,
        "authorized_actions": [],
        "conclusion_ceiling": (
            "Accountable triage only. Advancement requests a separate domain review; "
            "it does not accept a claim, amend a protocol, create evidence, or authorize action."
        ),
    }
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
