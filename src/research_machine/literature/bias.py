"""Structured, conservative study-level risk-of-bias review."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import tempfile
from typing import Any

from research_machine.domain.errors import ValidationError
from research_machine.literature.hashes import require_sha256
from research_machine.literature.snapshot import _text
from research_machine.literature.verification import validate_citation_verification_boundary


_DOMAINS = (
    "selection",
    "confounding",
    "exposure_or_intervention_classification",
    "deviations_from_intended_conditions",
    "missing_data",
    "outcome_measurement",
    "selective_reporting",
)
_JUDGMENTS = {"low", "some_concerns", "high", "unclear", "not_applicable"}


def _canonical_text(value: Any, field: str) -> str:
    text = _text(value, field)
    if text != text.strip():
        raise ValidationError(f"{field} must be canonical without surrounding whitespace")
    return text


def _overall(domains: list[dict[str, Any]]) -> str:
    values = {item["judgment"] for item in domains}
    if "high" in values:
        return "high"
    if "some_concerns" in values:
        return "some_concerns"
    if "unclear" in values:
        return "unclear"
    return "low" if "low" in values else "unclear"


def validate_bias_assessment_boundary(
    bias: dict[str, Any],
    assessments: list[dict[str, Any]],
    *,
    require_assessment_contract: bool = False,
) -> None:
    """Replay risk-of-bias authority, independence, and summary counts."""
    if not isinstance(bias, dict) or bias.get("bias_assessment_version") != 1:
        raise ValidationError("bias assessment version is invalid")
    require_sha256(
        bias.get("citation_verification_sha256"),
        "bias assessment citation_verification_sha256",
    )
    _canonical_text(bias.get("snapshot_id"), "bias assessment snapshot_id")
    _canonical_text(bias.get("reviewer"), "bias reviewer")
    if bias.get("independent_review") is not True:
        raise ValidationError("bias assessment must retain independent-review status")
    if bias.get("scientific_evidence_eligible") is not False:
        raise ValidationError("bias assessment must remain scientifically ineligible")
    if bias.get("conclusion_authorized") is not False:
        raise ValidationError("bias assessment must not authorize conclusions")
    if bias.get("publication_authorized") is not False:
        raise ValidationError("bias assessment must not authorize publication claims")
    limitations = bias.get("limitations")
    if not isinstance(limitations, list) or not limitations:
        raise ValidationError("bias assessment requires retained boundary limitations")
    for index, limitation in enumerate(limitations):
        _canonical_text(limitation, f"bias assessment limitation {index + 1}")
    if bias.get("domain_order") != list(_DOMAINS):
        raise ValidationError("bias assessment domain_order is invalid")
    if (
        not isinstance(assessments, list)
        or not assessments
        or bias.get("assessments") != assessments
    ):
        raise ValidationError("bias assessment assessments must be retained")

    counts: dict[str, int] = {
        judgment: 0 for judgment in ("low", "some_concerns", "high", "unclear")
    }
    for item in assessments:
        judgment = item.get("overall_judgment") if isinstance(item, dict) else None
        if judgment not in counts:
            raise ValidationError("bias assessment overall_judgment is invalid")
        counts[judgment] += 1
    if bias.get("overall_judgment_counts") != counts:
        raise ValidationError("bias assessment overall_judgment_counts do not replay from studies")
    if bias.get("status") != "bias_assessment_recorded":
        raise ValidationError("bias assessment status is invalid")
    if require_assessment_contract:
        seen_study_ids: set[str] = set()
        required_assessment = {
            "study_id",
            "study_design",
            "source_ids",
            "domains",
            "overall_judgment",
            "notes",
        }
        required_domain = {
            "domain",
            "judgment",
            "rationale",
            "evidence_locations",
        }
        for item in assessments:
            if not isinstance(item, dict) or set(item) != required_assessment:
                raise ValidationError(
                    "bias assessment fields do not match the documented contract"
                )
            study_id = _canonical_text(item.get("study_id"), "bias study_id")
            if study_id in seen_study_ids:
                raise ValidationError("bias assessments contain duplicate study_id")
            seen_study_ids.add(study_id)
            _canonical_text(item.get("study_design"), "study_design")
            source_ids = item.get("source_ids")
            if (
                not isinstance(source_ids, list)
                or not source_ids
                or any(
                    not isinstance(source_id, str)
                    or not source_id.strip()
                    or source_id != source_id.strip()
                    for source_id in source_ids
                )
                or len(source_ids) != len(set(source_ids))
            ):
                raise ValidationError(
                    "bias source_ids must be unique non-empty canonical text"
                )
            domains = item.get("domains")
            if not isinstance(domains, list):
                raise ValidationError("bias domains must be an array")
            by_domain: dict[str, dict[str, Any]] = {}
            for domain in domains:
                if not isinstance(domain, dict) or set(domain) != required_domain:
                    raise ValidationError(
                        "bias domain fields do not match the documented contract"
                    )
                name = _canonical_text(domain.get("domain"), "bias domain")
                judgment = domain.get("judgment")
                if name not in _DOMAINS or name in by_domain:
                    raise ValidationError(
                        "bias domains must be unique documented domain names"
                    )
                if judgment not in _JUDGMENTS:
                    raise ValidationError("invalid risk-of-bias judgment")
                locations = domain.get("evidence_locations")
                if (
                    not isinstance(locations, list)
                    or any(
                        not isinstance(location, str)
                        or not location.strip()
                        or location != location.strip()
                        for location in locations
                    )
                    or (judgment != "not_applicable" and not locations)
                ):
                    raise ValidationError(
                        "applicable bias domains require non-empty evidence_locations"
                    )
                by_domain[name] = {
                    "domain": name,
                    "judgment": judgment,
                    "rationale": _canonical_text(
                        domain.get("rationale"), "bias rationale"
                    ),
                    "evidence_locations": locations,
                }
            if set(by_domain) != set(_DOMAINS):
                raise ValidationError("bias assessment must cover every documented domain")
            ordered_domains = [by_domain[name] for name in _DOMAINS]
            if item.get("overall_judgment") != _overall(ordered_domains):
                raise ValidationError(
                    "bias assessment overall_judgment does not replay from domains"
                )
            _canonical_text(item.get("notes"), "bias notes")


def create_bias_assessment(
    verification_path: Path,
    expected_sha256: str,
    review: dict[str, Any],
    output: Path,
) -> dict[str, Any]:
    expected_sha256 = require_sha256(expected_sha256, "expected_citation_verification_sha256")
    try:
        content = verification_path.read_bytes()
        verification = json.loads(content)
    except (OSError, UnicodeDecodeError, ValueError) as exc:
        raise ValidationError("could not read valid citation-verification JSON") from exc
    digest = hashlib.sha256(content).hexdigest()
    if digest != expected_sha256:
        raise ValidationError("bias assessment citation verification does not match the expected SHA-256")
    if (not isinstance(verification, dict)
            or verification.get("citation_verification_version") != 1
            or verification.get("status") != "citation_review_recorded"):
        raise ValidationError("bias assessment requires a completed citation review without unsupported or unclear claims")

    prior_reviewers = {
        _canonical_text(verification.get("extraction_reviewer"), "extraction reviewer").casefold(),
        _canonical_text(verification.get("citation_reviewer"), "citation reviewer").casefold(),
    }
    claims = verification.get("assessments")
    if not isinstance(claims, list) or not claims:
        raise ValidationError("bias assessment requires citation-reviewed claims")
    validate_citation_verification_boundary(
        verification,
        claims,
        require_clean_verdicts=True,
        require_assessment_contract=True,
    )
    studies: dict[str, set[str]] = {}
    for claim in claims:
        if not isinstance(claim, dict):
            raise ValidationError("citation assessment must be an object")
        study_id = _canonical_text(claim.get("study_id"), "citation study_id")
        source_id = _canonical_text(claim.get("source_id"), "citation source_id")
        studies.setdefault(study_id, set()).add(source_id)

    if not isinstance(review, dict) or set(review) != {"reviewer", "assessments"}:
        raise ValidationError("bias review requires exactly reviewer and assessments")
    reviewer = _canonical_text(review["reviewer"], "bias reviewer")
    if reviewer.casefold() in prior_reviewers:
        raise ValidationError("bias reviewer must be independent of extraction and citation reviewers")
    assessments = review["assessments"]
    if not isinstance(assessments, list):
        raise ValidationError("bias assessments must be an array")

    by_study: dict[str, dict[str, Any]] = {}
    for assessment in assessments:
        if not isinstance(assessment, dict) or set(assessment) != {
            "study_id", "study_design", "source_ids", "domains", "notes"
        }:
            raise ValidationError("each bias assessment requires study_id, study_design, source_ids, domains, and notes")
        study_id = _canonical_text(assessment["study_id"], "bias study_id")
        if study_id not in studies:
            raise ValidationError("bias assessment references an unknown study_id")
        if study_id in by_study:
            raise ValidationError("duplicate study bias assessment")
        source_ids = assessment["source_ids"]
        if (not isinstance(source_ids, list)
                or any(not isinstance(item, str) or not item.strip() or item != item.strip()
                       for item in source_ids)
                or len(set(source_ids)) != len(source_ids)
                or set(source_ids) != studies[study_id]):
            raise ValidationError("bias source_ids must exactly cover citation-reviewed sources for the study")
        domains = assessment["domains"]
        if not isinstance(domains, list):
            raise ValidationError("bias domains must be an array")
        by_domain: dict[str, dict[str, Any]] = {}
        for domain in domains:
            if not isinstance(domain, dict) or set(domain) != {
                "domain", "judgment", "rationale", "evidence_locations"
            }:
                raise ValidationError("each bias domain requires domain, judgment, rationale, and evidence_locations")
            name = domain["domain"]
            judgment = domain["judgment"]
            if name not in _DOMAINS or name in by_domain:
                raise ValidationError("bias domains must be unique documented domain names")
            if judgment not in _JUDGMENTS:
                raise ValidationError("invalid risk-of-bias judgment")
            locations = domain["evidence_locations"]
            if (not isinstance(locations, list)
                    or any(not isinstance(item, str) or not item.strip() or item != item.strip()
                           for item in locations)
                    or (judgment != "not_applicable" and not locations)):
                raise ValidationError("applicable bias domains require non-empty evidence_locations")
            by_domain[name] = {
                "domain": name, "judgment": judgment,
                "rationale": _canonical_text(domain["rationale"], "bias rationale"),
                "evidence_locations": locations,
            }
        if set(by_domain) != set(_DOMAINS):
            raise ValidationError("bias assessment must cover every documented domain")
        normalized_domains = [by_domain[name] for name in _DOMAINS]
        by_study[study_id] = {
            "study_id": study_id,
            "study_design": _canonical_text(assessment["study_design"], "study_design"),
            "source_ids": sorted(source_ids),
            "domains": normalized_domains,
            "overall_judgment": _overall(normalized_domains),
            "notes": _canonical_text(assessment["notes"], "bias notes"),
        }
    if set(by_study) != set(studies):
        raise ValidationError("bias assessments must cover exactly all citation-reviewed studies")

    counts = {judgment: sum(item["overall_judgment"] == judgment for item in by_study.values())
              for judgment in ("low", "some_concerns", "high", "unclear")}
    result = {
        "bias_assessment_version": 1,
        "citation_verification_sha256": digest,
        "snapshot_id": verification.get("snapshot_id"),
        "reviewer": reviewer,
        "independent_review": True,
        "domain_order": list(_DOMAINS),
        "assessments": [by_study[item] for item in sorted(by_study)],
        "overall_judgment_counts": counts,
        "status": "bias_assessment_recorded",
        "scientific_evidence_eligible": False,
        "conclusion_authorized": False,
        "publication_authorized": False,
        "limitations": [
            "Overall judgments are conservative deterministic summaries of reviewer-entered domain judgments, not automated validity findings.",
            "The generic domains do not replace design-specific validated instruments or authenticate reviewer expertise or independence.",
            "Risk-of-bias assessment does not make a literature claim true or authorize quantitative synthesis.",
        ],
    }
    validate_bias_assessment_boundary(
        result,
        result["assessments"],
        require_assessment_contract=True,
    )
    root = output.expanduser().resolve()
    if root.exists():
        raise ValidationError("bias assessment output already exists")
    root.parent.mkdir(parents=True, exist_ok=True)
    encoded = (json.dumps(result, sort_keys=True, indent=2, ensure_ascii=False, allow_nan=False) + "\n").encode()
    with tempfile.TemporaryDirectory(prefix=".bias-assessment-", dir=root.parent) as temporary:
        staging = Path(temporary) / "bias-assessment"
        staging.mkdir()
        (staging / "bias-assessment.json").write_bytes(encoded)
        os.replace(staging, root)
    return {"path": str(root), "bias_assessment_sha256": hashlib.sha256(encoded).hexdigest(), **result}
