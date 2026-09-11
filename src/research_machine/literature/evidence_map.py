"""Deterministic literature evidence map with bounded interpretive ceilings."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import tempfile
from typing import Any

from research_machine.domain.errors import ValidationError
from research_machine.literature.bias import validate_bias_assessment_boundary
from research_machine.literature.extraction import validate_extraction_boundary
from research_machine.literature.hashes import require_sha256
from research_machine.literature.snapshot import _text
from research_machine.literature.studies import validate_study_reconciliation_boundary
from research_machine.literature.verification import validate_citation_verification_boundary


_EXTRACTION_RECORD_FIELDS = {
    "extraction_id",
    "study_id",
    "claim_text",
    "evidence_location",
    "epistemic_layer",
    "result_direction",
    "uncertainty",
    "notes",
}
_LEGACY_SOURCE_ANCHOR = "legacy_missing"
_INTERPRETIVE_CEILINGS = {
    "reviewed_source_claim",
    "qualified_source_claim",
    "source_hypothesis_only",
    "insufficient_for_conclusion",
}


def _load(path: Path, label: str) -> tuple[dict[str, Any], str]:
    try:
        content = path.read_bytes()
        value = json.loads(content)
    except (OSError, UnicodeDecodeError, ValueError) as exc:
        raise ValidationError(f"could not read valid {label} JSON") from exc
    if not isinstance(value, dict):
        raise ValidationError(f"{label} must be a JSON object")
    return value, hashlib.sha256(content).hexdigest()


def _canonical_text(value: Any, field: str) -> str:
    text = _text(value, field)
    if text != text.strip():
        raise ValidationError(f"{field} must be canonical without surrounding whitespace")
    return text


def _ceiling(citation_verdict: str, bias_judgment: str, epistemic_layer: str) -> str:
    if bias_judgment in {"high", "unclear"}:
        return "insufficient_for_conclusion"
    if citation_verdict == "partially_supported" or bias_judgment == "some_concerns":
        return "qualified_source_claim"
    if epistemic_layer in {"hypothesized", "speculative"}:
        return "source_hypothesis_only"
    return "reviewed_source_claim"


def _source_anchor(value: Any, field: str) -> str:
    if value == _LEGACY_SOURCE_ANCHOR:
        return _LEGACY_SOURCE_ANCHOR
    return require_sha256(value, field)


def _validate_limitations(record: dict[str, Any], label: str) -> None:
    limitations = record.get("limitations")
    if not isinstance(limitations, list) or not limitations:
        raise ValidationError(f"{label} requires retained boundary limitations")
    for index, limitation in enumerate(limitations):
        _canonical_text(limitation, f"{label} limitation {index + 1}")


def _validate_extraction_boundary(extraction: dict[str, Any]) -> None:
    source_reviews = extraction.get("source_reviews")
    if not isinstance(source_reviews, list):
        raise ValidationError("extraction source_reviews must be an array")
    record_count = 0
    for source_review in source_reviews:
        if not isinstance(source_review, dict):
            raise ValidationError("extraction source review must be an object")
        records = source_review.get("records")
        if not isinstance(records, list):
            raise ValidationError("extraction records must be an array")
        record_count += len(records)
    validate_extraction_boundary(extraction, record_count)


def _validate_citation_verification_boundary(
    verification: dict[str, Any],
    assessments: list[dict[str, Any]],
) -> None:
    validate_citation_verification_boundary(
        verification, assessments, require_clean_verdicts=True
    )


def validate_evidence_map_boundary(
    evidence_map: dict[str, Any],
    claims: list[dict[str, Any]],
) -> None:
    """Replay evidence-map non-authority and summary counts."""
    if evidence_map.get("evidence_map_version") != 1:
        raise ValidationError("evidence map version is invalid")
    inputs = evidence_map.get("inputs")
    required_inputs = {
        "extraction_sha256",
        "citation_verification_sha256",
        "bias_assessment_sha256",
        "study_reconciliation_sha256",
    }
    if not isinstance(inputs, dict) or set(inputs) != required_inputs:
        raise ValidationError("evidence map inputs do not match the documented contract")
    for key in sorted(required_inputs):
        require_sha256(inputs.get(key), f"evidence map input {key}")
    _canonical_text(evidence_map.get("snapshot_id"), "evidence map snapshot_id")
    if evidence_map.get("status") != "evidence_map_recorded":
        raise ValidationError("evidence map status is invalid")
    if evidence_map.get("scientific_evidence_eligible") is not False:
        raise ValidationError("evidence map must remain scientifically ineligible")
    if evidence_map.get("conclusion_authorized") is not False:
        raise ValidationError("evidence map must not authorize conclusions")
    if evidence_map.get("publication_authorized") is not False:
        raise ValidationError("evidence map must not authorize publication")
    if evidence_map.get("reviewer_identity_authenticated", False) is not False:
        raise ValidationError("evidence map must not authenticate reviewer identity")
    limitations = evidence_map.get("limitations")
    if not isinstance(limitations, list) or not limitations:
        raise ValidationError("evidence map requires retained boundary limitations")
    for index, limitation in enumerate(limitations):
        _canonical_text(limitation, f"evidence map limitation {index + 1}")

    claim_count = evidence_map.get("claim_count")
    if isinstance(claim_count, bool) or claim_count != len(claims):
        raise ValidationError("evidence map claim_count does not replay from claims")
    study_ids = set()
    for index, claim in enumerate(claims):
        if not isinstance(claim, dict):
            raise ValidationError("evidence map claim is malformed")
        study_ids.add(
            _canonical_text(
                claim.get("study_id"),
                f"evidence map claim {index + 1} study_id",
            )
        )
    study_count = evidence_map.get("study_count")
    if (
        isinstance(study_count, bool)
        or not isinstance(study_count, int)
        or study_count != len(study_ids)
    ):
        raise ValidationError("evidence map study_count does not replay from claims")
    ceilings = evidence_map.get("interpretive_ceiling_counts")
    if not isinstance(ceilings, dict):
        raise ValidationError("evidence map interpretive_ceiling_counts must be an object")
    unknown_ceilings = sorted(
        {
            str(claim.get("interpretive_ceiling"))
            for claim in claims
            if claim.get("interpretive_ceiling") not in _INTERPRETIVE_CEILINGS
        }
    )
    if unknown_ceilings:
        raise ValidationError(
            "evidence map claim interpretive ceiling is invalid: "
            + ", ".join(unknown_ceilings)
        )
    expected = {
        ceiling: sum(claim.get("interpretive_ceiling") == ceiling for claim in claims)
        for ceiling in sorted({claim["interpretive_ceiling"] for claim in claims})
    }
    if ceilings != expected:
        raise ValidationError(
            "evidence map interpretive_ceiling_counts does not replay from claims"
        )


def _extraction_claim_payload_sha256(
    source_id: str,
    record: dict[str, Any],
    source_retained_file_sha256: str = _LEGACY_SOURCE_ANCHOR,
) -> str:
    payload = {
        "source_id": source_id,
        "extraction_id": record["extraction_id"],
        "study_id": record["study_id"],
        "claim_text": record["claim_text"],
        "evidence_location": record["evidence_location"],
        "epistemic_layer": record["epistemic_layer"],
        "result_direction": record["result_direction"],
        "uncertainty": record["uncertainty"],
        "notes": record["notes"],
    }
    if source_retained_file_sha256 != _LEGACY_SOURCE_ANCHOR:
        payload["source_retained_file_sha256"] = source_retained_file_sha256
    encoded = json.dumps(
        payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def create_evidence_map(
    extraction_path: Path,
    verification_path: Path,
    bias_path: Path,
    reconciliation_path: Path,
    expected_reconciliation_sha256: str,
    output: Path,
) -> dict[str, Any]:
    expected_reconciliation_sha256 = require_sha256(
        expected_reconciliation_sha256, "expected_study_reconciliation_sha256"
    )
    extraction, extraction_sha = _load(extraction_path, "extraction")
    verification, verification_sha = _load(verification_path, "citation verification")
    bias, bias_sha = _load(bias_path, "bias assessment")
    reconciliation, reconciliation_sha = _load(reconciliation_path, "study reconciliation")
    if reconciliation_sha != expected_reconciliation_sha256:
        raise ValidationError("evidence map reconciliation does not match the expected SHA-256")
    if extraction.get("extraction_version") != 1 or extraction.get("status") != "extraction_recorded":
        raise ValidationError("evidence map requires a completed version 1 extraction")
    if (verification.get("citation_verification_version") != 1
            or verification.get("status") != "citation_review_recorded"
            or verification.get("extraction_sha256") != extraction_sha):
        raise ValidationError("citation verification is incomplete or does not bind the supplied extraction")
    if (bias.get("bias_assessment_version") != 1
            or bias.get("status") != "bias_assessment_recorded"
            or bias.get("citation_verification_sha256") != verification_sha):
        raise ValidationError("bias assessment is incomplete or does not bind the supplied citation review")
    if (reconciliation.get("study_reconciliation_version") != 1
            or reconciliation.get("status") != "study_identities_reconciled"
            or reconciliation.get("bias_assessment_sha256") != bias_sha):
        raise ValidationError("study identities are unresolved or do not bind the supplied bias assessment")
    _validate_extraction_boundary(extraction)

    citation_by_id = {}
    verification_assessments = verification.get("assessments", [])
    if not isinstance(verification_assessments, list):
        raise ValidationError("citation assessments must be an array")
    _validate_citation_verification_boundary(verification, verification_assessments)
    for item in verification_assessments:
        if not isinstance(item, dict):
            raise ValidationError("citation assessments are malformed")
        extraction_id = _canonical_text(item.get("extraction_id"), "citation extraction_id")
        if extraction_id in citation_by_id:
            raise ValidationError("citation assessments contain duplicate extraction_id")
        citation_by_id[extraction_id] = {**item, "extraction_id": extraction_id}
    bias_by_study = {}
    bias_assessments = bias.get("assessments", [])
    if not isinstance(bias_assessments, list):
        raise ValidationError("bias assessments must be an array")
    validate_bias_assessment_boundary(
        bias,
        bias_assessments,
        require_assessment_contract=True,
    )
    for item in bias_assessments:
        if not isinstance(item, dict):
            raise ValidationError("bias assessments are malformed")
        study_id = _canonical_text(item.get("study_id"), "bias study_id")
        if study_id in bias_by_study:
            raise ValidationError("bias assessments contain duplicate study_id")
        bias_by_study[study_id] = {**item, "study_id": study_id}
    reconciled_studies = set()
    relationships = reconciliation.get("relationships", [])
    if not isinstance(relationships, list):
        raise ValidationError("study relationships must be an array")
    validate_study_reconciliation_boundary(
        reconciliation,
        relationships,
        require_reconciled=True,
        require_reconciliation_contract=True,
    )
    for item in reconciliation.get("studies", []):
        if not isinstance(item, dict):
            raise ValidationError("reconciled studies are malformed")
        study_id = _canonical_text(item.get("study_id"), "reconciled study_id")
        if study_id in reconciled_studies:
            raise ValidationError("reconciled studies contain duplicate study_id")
        reconciled_studies.add(study_id)

    claims = []
    seen = set()
    for source_review in extraction.get("source_reviews", []):
        if not isinstance(source_review, dict):
            raise ValidationError("extraction source reviews are malformed")
        source_id = _canonical_text(source_review.get("source_id"), "extraction source_id")
        source_retained_file_sha256 = _source_anchor(
            source_review.get(
                "source_retained_file_sha256", _LEGACY_SOURCE_ANCHOR
            ),
            "extraction source_retained_file_sha256",
        )
        for record in source_review.get("records", []):
            if not isinstance(record, dict):
                raise ValidationError("extraction records are malformed")
            if set(record) != _EXTRACTION_RECORD_FIELDS:
                raise ValidationError("extraction record fields do not match the documented contract")
            extraction_id = _canonical_text(record.get("extraction_id"), "extraction_id")
            if extraction_id in seen:
                raise ValidationError("extraction records contain invalid or duplicate extraction_id")
            study_id = _canonical_text(record.get("study_id"), "extraction study_id")
            normalized_record = {
                field: _canonical_text(record.get(field), f"extraction {field}")
                for field in _EXTRACTION_RECORD_FIELDS
            }
            seen.add(extraction_id)
            citation = citation_by_id.get(extraction_id)
            study_bias = bias_by_study.get(study_id)
            if (citation is None or study_bias is None or study_id not in reconciled_studies
                    or _canonical_text(citation.get("source_id"), "citation source_id") != source_id
                    or _canonical_text(citation.get("study_id"), "citation study_id") != study_id
                    or _source_anchor(
                        citation.get(
                            "source_retained_file_sha256",
                            _LEGACY_SOURCE_ANCHOR,
                        ),
                        "citation source_retained_file_sha256",
                    ) != source_retained_file_sha256):
                raise ValidationError("literature artifacts do not provide consistent claim, source, and study coverage")
            citation_claim_sha = require_sha256(
                citation.get("extraction_claim_sha256"), "citation extraction_claim_sha256"
            )
            if citation_claim_sha != _extraction_claim_payload_sha256(
                source_id, normalized_record, source_retained_file_sha256
            ):
                raise ValidationError("citation verification does not bind the exact extracted claim payload")
            verdict, overall = citation.get("verdict"), study_bias.get("overall_judgment")
            layer = normalized_record["epistemic_layer"]
            if verdict not in {"supported", "partially_supported"}:
                raise ValidationError("evidence map cannot include unsupported or unclear citations")
            if overall not in {"low", "some_concerns", "high", "unclear"}:
                raise ValidationError("evidence map bias judgment is invalid")
            extracted_location = normalized_record["evidence_location"]
            checked_location = citation.get("checked_location")
            citation_rationale = citation.get("rationale")
            if any(not isinstance(value, str) or not value.strip()
                   or value != value.strip()
                   for value in (extracted_location, checked_location, citation_rationale)):
                raise ValidationError("evidence map requires retained extraction and citation-review locations")
            domains = study_bias.get("domains")
            if not isinstance(domains, list) or not domains:
                raise ValidationError("evidence map requires retained bias-domain judgments")
            domain_summaries = []
            seen_domains = set()
            for domain in domains:
                if not isinstance(domain, dict):
                    raise ValidationError("evidence map bias-domain judgment is malformed")
                name, judgment, locations = (
                    domain.get("domain"), domain.get("judgment"), domain.get("evidence_locations")
                )
                name = _canonical_text(name, "bias domain")
                if name in seen_domains:
                    raise ValidationError("evidence map bias-domain names must be unique non-empty text")
                seen_domains.add(name)
                if judgment not in {"low", "some_concerns", "high", "unclear", "not_applicable"}:
                    raise ValidationError("evidence map bias-domain judgment is invalid")
                if (not isinstance(locations, list)
                        or any(not isinstance(item, str) or not item.strip() or item != item.strip()
                               for item in locations)
                        or (judgment != "not_applicable" and not locations)):
                    raise ValidationError("evidence map bias-domain locations are invalid")
                domain_summaries.append({
                    "domain": name,
                    "judgment": judgment,
                    "evidence_locations": locations,
                })
            claims.append({
                "extraction_id": extraction_id, "study_id": study_id, "source_id": source_id,
                "source_retained_file_sha256": source_retained_file_sha256,
                "extracted_evidence_location": extracted_location,
                "extraction_claim_sha256": citation_claim_sha,
                "claim_text": normalized_record["claim_text"], "epistemic_layer": layer,
                "result_direction": normalized_record["result_direction"], "uncertainty": normalized_record["uncertainty"],
                "citation_checked_location": checked_location,
                "citation_rationale": citation_rationale,
                "citation_verdict": verdict, "risk_of_bias": overall,
                "bias_domain_judgments": domain_summaries,
                "interpretive_ceiling": _ceiling(verdict, overall, layer),
            })
    if set(citation_by_id) != seen or not claims:
        raise ValidationError("evidence map requires exact, non-empty claim coverage")

    ceiling_counts = {ceiling: sum(item["interpretive_ceiling"] == ceiling for item in claims)
                      for ceiling in sorted({item["interpretive_ceiling"] for item in claims})}
    result = {
        "evidence_map_version": 1,
        "inputs": {
            "extraction_sha256": extraction_sha,
            "citation_verification_sha256": verification_sha,
            "bias_assessment_sha256": bias_sha,
            "study_reconciliation_sha256": reconciliation_sha,
        },
        "snapshot_id": extraction.get("snapshot_id"),
        "claims": sorted(claims, key=lambda item: item["extraction_id"]),
        "claim_count": len(claims), "study_count": len(reconciled_studies),
        "interpretive_ceiling_counts": ceiling_counts,
        "status": "evidence_map_recorded",
        "scientific_evidence_eligible": False,
        "conclusion_authorized": False,
        "publication_authorized": False,
        "reviewer_identity_authenticated": False,
        "limitations": [
            "This deterministic map joins reviewed assertions; it does not estimate an effect or establish that any claim is true.",
            "Interpretive ceilings can only restrict claims and do not replace subject-matter judgment, applicability review, or replication.",
            "The machine does not authenticate reviewer identity or expertise for the extraction, citation, bias, study-identity, or mapping judgments.",
            "No qualitative conclusion, meta-analysis, causal conclusion, recommendation, or publication is authorized by this artifact.",
        ],
    }
    validate_evidence_map_boundary(result, result["claims"])
    root = output.expanduser().resolve()
    if root.exists():
        raise ValidationError("evidence map output already exists")
    root.parent.mkdir(parents=True, exist_ok=True)
    encoded = (json.dumps(result, sort_keys=True, indent=2, ensure_ascii=False, allow_nan=False) + "\n").encode()
    with tempfile.TemporaryDirectory(prefix=".evidence-map-", dir=root.parent) as temporary:
        staging = Path(temporary) / "evidence-map"
        staging.mkdir()
        (staging / "evidence-map.json").write_bytes(encoded)
        os.replace(staging, root)
    return {"path": str(root), "evidence_map_sha256": hashlib.sha256(encoded).hexdigest(), **result}
