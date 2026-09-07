"""Deterministic literature evidence map with bounded interpretive ceilings."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import tempfile
from typing import Any

from research_machine.domain.errors import ValidationError
from research_machine.literature.snapshot import _text


def _load(path: Path, label: str) -> tuple[dict[str, Any], str]:
    try:
        content = path.read_bytes()
        value = json.loads(content)
    except (OSError, UnicodeDecodeError, ValueError) as exc:
        raise ValidationError(f"could not read valid {label} JSON") from exc
    if not isinstance(value, dict):
        raise ValidationError(f"{label} must be a JSON object")
    return value, hashlib.sha256(content).hexdigest()


def _ceiling(citation_verdict: str, bias_judgment: str, epistemic_layer: str) -> str:
    if bias_judgment in {"high", "unclear"}:
        return "insufficient_for_conclusion"
    if citation_verdict == "partially_supported" or bias_judgment == "some_concerns":
        return "qualified_source_claim"
    if epistemic_layer in {"hypothesized", "speculative"}:
        return "source_hypothesis_only"
    return "reviewed_source_claim"


def create_evidence_map(
    extraction_path: Path,
    verification_path: Path,
    bias_path: Path,
    reconciliation_path: Path,
    expected_reconciliation_sha256: str,
    output: Path,
) -> dict[str, Any]:
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

    citation_by_id = {}
    for item in verification.get("assessments", []):
        if not isinstance(item, dict) or not isinstance(item.get("extraction_id"), str) or not item["extraction_id"].strip():
            raise ValidationError("citation assessments are malformed")
        extraction_id = item["extraction_id"].strip()
        if extraction_id in citation_by_id:
            raise ValidationError("citation assessments contain duplicate extraction_id")
        citation_by_id[extraction_id] = {**item, "extraction_id": extraction_id}
    bias_by_study = {}
    for item in bias.get("assessments", []):
        if not isinstance(item, dict) or not isinstance(item.get("study_id"), str) or not item["study_id"].strip():
            raise ValidationError("bias assessments are malformed")
        study_id = item["study_id"].strip()
        if study_id in bias_by_study:
            raise ValidationError("bias assessments contain duplicate study_id")
        bias_by_study[study_id] = {**item, "study_id": study_id}
    reconciled_studies = set()
    for item in reconciliation.get("studies", []):
        if not isinstance(item, dict) or not isinstance(item.get("study_id"), str) or not item["study_id"].strip():
            raise ValidationError("reconciled studies are malformed")
        study_id = item["study_id"].strip()
        if study_id in reconciled_studies:
            raise ValidationError("reconciled studies contain duplicate study_id")
        reconciled_studies.add(study_id)

    claims = []
    seen = set()
    for source_review in extraction.get("source_reviews", []):
        if not isinstance(source_review, dict):
            raise ValidationError("extraction source reviews are malformed")
        source_id = _text(source_review.get("source_id"), "extraction source_id").strip()
        for record in source_review.get("records", []):
            if not isinstance(record, dict):
                raise ValidationError("extraction records are malformed")
            extraction_id, study_id = record.get("extraction_id"), record.get("study_id")
            if not isinstance(extraction_id, str) or not extraction_id.strip():
                raise ValidationError("extraction records contain invalid or duplicate extraction_id")
            extraction_id = extraction_id.strip()
            if extraction_id in seen:
                raise ValidationError("extraction records contain invalid or duplicate extraction_id")
            study_id = _text(study_id, "extraction study_id").strip()
            seen.add(extraction_id)
            citation = citation_by_id.get(extraction_id)
            study_bias = bias_by_study.get(study_id)
            if (citation is None or study_bias is None or study_id not in reconciled_studies
                    or _text(citation.get("source_id"), "citation source_id").strip() != source_id
                    or _text(citation.get("study_id"), "citation study_id").strip() != study_id):
                raise ValidationError("literature artifacts do not provide consistent claim, source, and study coverage")
            verdict, overall = citation.get("verdict"), study_bias.get("overall_judgment")
            layer = record.get("epistemic_layer")
            if verdict not in {"supported", "partially_supported"}:
                raise ValidationError("evidence map cannot include unsupported or unclear citations")
            if overall not in {"low", "some_concerns", "high", "unclear"}:
                raise ValidationError("evidence map bias judgment is invalid")
            extracted_location = record.get("evidence_location")
            checked_location = citation.get("checked_location")
            citation_rationale = citation.get("rationale")
            if any(not isinstance(value, str) or not value.strip()
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
                if not isinstance(name, str) or not name.strip():
                    raise ValidationError("evidence map bias-domain names must be unique non-empty text")
                name = name.strip()
                if name in seen_domains:
                    raise ValidationError("evidence map bias-domain names must be unique non-empty text")
                seen_domains.add(name)
                if judgment not in {"low", "some_concerns", "high", "unclear", "not_applicable"}:
                    raise ValidationError("evidence map bias-domain judgment is invalid")
                if (not isinstance(locations, list)
                        or any(not isinstance(item, str) or not item.strip() for item in locations)
                        or (judgment != "not_applicable" and not locations)):
                    raise ValidationError("evidence map bias-domain locations are invalid")
                domain_summaries.append({
                    "domain": name,
                    "judgment": judgment,
                    "evidence_locations": [item.strip() for item in locations],
                })
            claims.append({
                "extraction_id": extraction_id, "study_id": study_id, "source_id": source_id,
                "extracted_evidence_location": extracted_location.strip(),
                "claim_text": record.get("claim_text"), "epistemic_layer": layer,
                "result_direction": record.get("result_direction"), "uncertainty": record.get("uncertainty"),
                "citation_checked_location": checked_location.strip(),
                "citation_rationale": citation_rationale.strip(),
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
        "limitations": [
            "This deterministic map joins reviewed assertions; it does not estimate an effect or establish that any claim is true.",
            "Interpretive ceilings can only restrict claims and do not replace subject-matter judgment, applicability review, or replication.",
            "No qualitative conclusion, meta-analysis, causal conclusion, recommendation, or publication is authorized by this artifact.",
        ],
    }
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
