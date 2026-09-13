"""Execute a bounded deterministic qualitative literature synthesis."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import tempfile
from typing import Any

from research_machine.application.report_language import report_overclaim_terms
from research_machine.domain.errors import ValidationError
from research_machine.literature.deviations import (
    validate_retained_synthesis_deviations,
    validate_frozen_plan_commitments_boundary,
    validate_synthesis_deviations_boundary,
)
from research_machine.literature.evidence_map import validate_evidence_map_boundary
from research_machine.literature.extraction import validate_extraction_boundary
from research_machine.literature.hashes import require_sha256
from research_machine.literature.json_loading import load_json_object
from research_machine.literature.snapshot import _text
from research_machine.literature.synthesis_plan import validate_synthesis_plan_boundary
from research_machine.literature.verification import _validate_passage_receipt

_LEGACY_SOURCE_ANCHOR = "legacy_missing"
_DEVIATION_STATUSES = {
    "no_deviations_declared",
    "prospective_deviations_recorded",
    "retrospective_or_uncertain_deviation_review_required",
}
_RESULT_DIRECTIONS = ("supports", "weakens", "mixed", "null", "not_applicable")
_INTERPRETIVE_CEILINGS = (
    "reviewed_source_claim",
    "qualified_source_claim",
    "source_hypothesis_only",
    "insufficient_for_conclusion",
)
_PASSAGE_MACHINE_VERIFICATION = "exact_utf8_quote_found_in_retained_source_bytes"
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


def _load(path: Path, label: str) -> tuple[dict[str, Any], str]:
    return load_json_object(path, label)


def _canonical_text(value: Any, field: str) -> str:
    text = _text(value, field)
    if text != text.strip():
        raise ValidationError(f"{field} must be canonical without surrounding whitespace")
    return text


def _bounded_synthesis_text(value: Any, field: str) -> str:
    text = _canonical_text(value, field)
    if report_overclaim_terms(text):
        raise ValidationError(
            f"{field} uses literature-synthesis prohibited overclaiming language; "
            "describe the organized review result without claiming proof, "
            "confirmation, validation, or explanation"
        )
    return text


def _source_anchor(value: object, field: str) -> str:
    if value == _LEGACY_SOURCE_ANCHOR:
        return _LEGACY_SOURCE_ANCHOR
    return require_sha256(value, field)


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


def _validate_extraction_boundary_and_records(
    extraction: dict[str, Any],
) -> tuple[list[str], dict[str, dict[str, str]]]:
    source_reviews = extraction.get("source_reviews")
    if not isinstance(source_reviews, list):
        raise ValidationError("extraction source_reviews must be an array")

    source_ids: list[str] = []
    extracted_claims: dict[str, dict[str, str]] = {}
    for source_review in source_reviews:
        if not isinstance(source_review, dict):
            raise ValidationError("extraction source review must be an object")
        source_id = _canonical_text(source_review.get("source_id"), "extraction source_id")
        source_ids.append(source_id)
        source_retained_file_sha256 = _source_anchor(
            source_review.get("source_retained_file_sha256", _LEGACY_SOURCE_ANCHOR),
            "extraction source_retained_file_sha256",
        )
        records = source_review.get("records")
        if not isinstance(records, list):
            raise ValidationError("extraction records must be an array")
        for record in records:
            if not isinstance(record, dict) or set(record) != _EXTRACTION_RECORD_FIELDS:
                raise ValidationError("extraction record fields do not match the synthesis contract")
            normalized_record = {
                field: _canonical_text(record.get(field), f"extraction {field}")
                for field in _EXTRACTION_RECORD_FIELDS
            }
            extraction_id = normalized_record["extraction_id"]
            if extraction_id in extracted_claims:
                raise ValidationError("extraction records contain duplicate extraction_id")
            extracted_claims[extraction_id] = {
                "source_id": source_id,
                "study_id": normalized_record["study_id"],
                "source_retained_file_sha256": source_retained_file_sha256,
                "extraction_claim_sha256": _extraction_claim_payload_sha256(
                    source_id, normalized_record, source_retained_file_sha256
                ),
            }
    validate_extraction_boundary(extraction, len(extracted_claims))
    if not extracted_claims:
        raise ValidationError("qualitative synthesis requires extracted claim records")
    return source_ids, extracted_claims


def validate_literature_synthesis_boundary(synthesis: dict[str, Any]) -> None:
    """Replay qualitative synthesis non-authority and retained summary boundaries."""
    if synthesis.get("literature_synthesis_version") != 1:
        raise ValidationError("literature synthesis version is invalid")
    inputs = synthesis.get("inputs")
    required_inputs = {
        "synthesis_plan_sha256",
        "extraction_sha256",
        "evidence_map_sha256",
        "synthesis_deviations_sha256",
    }
    if not isinstance(inputs, dict) or set(inputs) != required_inputs:
        raise ValidationError("literature synthesis inputs do not match the documented contract")
    for key in sorted(required_inputs):
        require_sha256(inputs.get(key), f"literature synthesis input {key}")
    for field in (
        "plan_id",
        "snapshot_id",
        "research_question",
        "primary_outcome",
        "conclusion_rule",
    ):
        _canonical_text(synthesis.get(field), f"literature synthesis {field}")
    if synthesis.get("scientific_evidence_eligible") is not False:
        raise ValidationError("literature synthesis must remain scientifically ineligible")
    if synthesis.get("conclusion_authorized") is not False:
        raise ValidationError("literature synthesis must not authorize conclusions")
    if synthesis.get("publication_authorized") is not False:
        raise ValidationError("literature synthesis must not authorize publication claims")
    if synthesis.get("reviewer_identity_authenticated", False) is not False:
        raise ValidationError("literature synthesis must not authenticate reviewer identity")
    limitations = synthesis.get("limitations")
    if not isinstance(limitations, list) or not limitations:
        raise ValidationError("literature synthesis requires retained boundary limitations")
    for index, limitation in enumerate(limitations):
        _bounded_synthesis_text(
            limitation,
            f"literature synthesis limitation {index + 1}",
        )

    deviation_status = synthesis.get("deviation_status")
    if deviation_status not in _DEVIATION_STATUSES:
        raise ValidationError("literature synthesis deviation_status is invalid")
    _retained_deviations, _timing_counts, retained_deviation_status = validate_retained_synthesis_deviations(
        synthesis.get("deviations"), synthesis_type="qualitative"
    )
    if retained_deviation_status != deviation_status:
        raise ValidationError("literature synthesis deviation_status does not replay from retained deviations")
    minimum = synthesis.get("minimum_independent_studies")
    if isinstance(minimum, bool) or not isinstance(minimum, int) or minimum < 1:
        raise ValidationError("literature synthesis minimum_independent_studies is invalid")

    claims = synthesis.get("claims")
    if not isinstance(claims, list) or not claims:
        raise ValidationError("literature synthesis requires retained claims")
    seen_claims: set[str] = set()
    study_ids: set[str] = set()
    passage_verification_counts = {
        _PASSAGE_MACHINE_VERIFICATION: 0,
        "not_provided": 0,
    }
    for claim in claims:
        if not isinstance(claim, dict):
            raise ValidationError("literature synthesis claim is malformed")
        extraction_id = _canonical_text(claim.get("extraction_id"), "literature synthesis extraction_id")
        if extraction_id in seen_claims:
            raise ValidationError("literature synthesis claim IDs must be unique")
        seen_claims.add(extraction_id)
        study_ids.add(_canonical_text(claim.get("study_id"), "literature synthesis study_id"))
        _canonical_text(claim.get("source_id"), "literature synthesis source_id")
        require_sha256(
            claim.get("extraction_claim_sha256"),
            "literature synthesis extraction_claim_sha256",
        )
        _source_anchor(
            claim.get("source_retained_file_sha256", _LEGACY_SOURCE_ANCHOR),
            "literature synthesis source_retained_file_sha256",
        )
        for field in (
            "extracted_evidence_location",
            "citation_checked_location",
            "citation_rationale",
            "claim_text",
            "epistemic_layer",
            "uncertainty",
        ):
            _canonical_text(claim.get(field), f"literature synthesis {field}")
        if claim.get("result_direction") not in _RESULT_DIRECTIONS:
            raise ValidationError("literature synthesis result direction is invalid")
        if claim.get("interpretive_ceiling") not in _INTERPRETIVE_CEILINGS:
            raise ValidationError("literature synthesis interpretive ceiling is invalid")
        if claim.get("citation_verdict") not in {"supported", "partially_supported"}:
            raise ValidationError("literature synthesis citation verdict is invalid")
        if claim.get("risk_of_bias") not in {"low", "some_concerns", "high", "unclear"}:
            raise ValidationError("literature synthesis risk_of_bias is invalid")
        if "passage_verification" in claim:
            receipt = _validate_passage_receipt(
                claim.get("passage_verification"),
                "literature synthesis passage_verification",
            )
            passage_verification_counts[receipt["machine_verification"]] += 1
        else:
            passage_verification_counts["not_provided"] += 1
        domains = claim.get("bias_domain_judgments")
        if not isinstance(domains, list) or not domains:
            raise ValidationError("literature synthesis requires retained bias-domain judgments")
        seen_domains: set[str] = set()
        for domain in domains:
            if not isinstance(domain, dict) or set(domain) != {"domain", "judgment", "evidence_locations"}:
                raise ValidationError("literature synthesis bias-domain provenance is malformed")
            name = _canonical_text(domain.get("domain"), "literature synthesis bias-domain")
            if name in seen_domains:
                raise ValidationError("literature synthesis bias-domain names must be unique")
            seen_domains.add(name)
            if domain.get("judgment") not in {"low", "some_concerns", "high", "unclear", "not_applicable"}:
                raise ValidationError("literature synthesis bias-domain judgment is invalid")
            locations = domain.get("evidence_locations")
            if (not isinstance(locations, list)
                    or any(not isinstance(item, str) or not item.strip() or item != item.strip()
                           for item in locations)
                    or (domain.get("judgment") != "not_applicable" and not locations)):
                raise ValidationError("literature synthesis bias-domain locations are invalid")

    claim_count = synthesis.get("claim_count")
    if isinstance(claim_count, bool) or claim_count != len(claims):
        raise ValidationError("literature synthesis claim_count does not replay from claims")
    independent_study_count = synthesis.get("independent_study_count")
    if isinstance(independent_study_count, bool) or independent_study_count != len(study_ids):
        raise ValidationError("literature synthesis independent_study_count does not replay from claims")
    minimum_met = len(study_ids) >= minimum
    if synthesis.get("minimum_study_requirement_met") is not minimum_met:
        raise ValidationError("literature synthesis minimum_study_requirement_met does not replay")
    expected_status = (
        "deviation_review_required"
        if deviation_status == "retrospective_or_uncertain_deviation_review_required"
        else "qualitative_synthesis_recorded" if minimum_met else "insufficient_independent_studies"
    )
    if synthesis.get("status") != expected_status:
        raise ValidationError("literature synthesis status does not replay from deviation and study counts")
    commitments = synthesis.get("deviation_plan_commitments")
    validate_frozen_plan_commitments_boundary(commitments)
    if (commitments.get("synthesis_type") != "qualitative"
            or commitments.get("research_question") != synthesis.get("research_question")
            or commitments.get("primary_outcome") != synthesis.get("primary_outcome")
            or commitments.get("effect_measure") not in {None, "not_applicable"}
            or commitments.get("contrast_definition") not in {None, "not_applicable"}
            or commitments.get("statistical_model") not in {None, "not_applicable"}
            or commitments.get("minimum_independent_studies") != minimum
            or commitments.get("conclusion_rule") != synthesis.get("conclusion_rule")):
        raise ValidationError("literature synthesis deviation-plan commitments do not replay")
    bounded_conclusion = synthesis.get("bounded_conclusion")
    if not isinstance(bounded_conclusion, str) or not bounded_conclusion.strip():
        raise ValidationError("literature synthesis requires a bounded conclusion boundary")
    bounded_conclusion = _bounded_synthesis_text(
        bounded_conclusion,
        "literature synthesis bounded_conclusion",
    )
    if minimum_met and "No automated substantive conclusion" not in bounded_conclusion:
        raise ValidationError("literature synthesis must not author an automated substantive conclusion")
    if not minimum_met and not bounded_conclusion.startswith("No conclusion:"):
        raise ValidationError("literature synthesis insufficient-study conclusion boundary is invalid")

    expected_directions = {
        value: sum(claim.get("result_direction") == value for claim in claims)
        for value in _RESULT_DIRECTIONS
    }
    if synthesis.get("result_direction_counts") != expected_directions:
        raise ValidationError("literature synthesis result_direction_counts do not replay from claims")
    expected_ceilings = {
        value: sum(claim.get("interpretive_ceiling") == value for claim in claims)
        for value in _INTERPRETIVE_CEILINGS
    }
    if synthesis.get("interpretive_ceiling_counts") != expected_ceilings:
        raise ValidationError("literature synthesis interpretive_ceiling_counts do not replay from claims")
    if synthesis.get("passage_verification_counts") != passage_verification_counts:
        raise ValidationError("literature synthesis passage_verification_counts do not replay from claims")


def execute_qualitative_synthesis(
    plan_path: Path,
    expected_plan_sha256: str,
    extraction_path: Path,
    evidence_map_path: Path,
    expected_evidence_map_sha256: str,
    deviations_path: Path,
    expected_deviations_sha256: str,
    output: Path,
) -> dict[str, Any]:
    expected_plan_sha256 = require_sha256(expected_plan_sha256, "expected_plan_sha256")
    expected_evidence_map_sha256 = require_sha256(
        expected_evidence_map_sha256, "expected_evidence_map_sha256"
    )
    expected_deviations_sha256 = require_sha256(
        expected_deviations_sha256, "expected_deviations_sha256"
    )
    plan, plan_sha = _load(plan_path, "synthesis plan")
    extraction, extraction_sha = _load(extraction_path, "extraction")
    evidence_map, evidence_map_sha = _load(evidence_map_path, "evidence map")
    deviations, deviations_sha = _load(deviations_path, "synthesis deviations")
    if plan_sha != expected_plan_sha256:
        raise ValidationError("synthesis plan does not match the expected SHA-256")
    if evidence_map_sha != expected_evidence_map_sha256:
        raise ValidationError("evidence map does not match the expected SHA-256")
    if deviations_sha != expected_deviations_sha256:
        raise ValidationError("synthesis deviations do not match the expected SHA-256")
    if plan.get("synthesis_plan_version") != 1 or plan.get("status") != "synthesis_plan_frozen":
        raise ValidationError("qualitative synthesis requires a frozen version 1 synthesis plan")
    validate_synthesis_plan_boundary(plan)
    if plan.get("synthesis_type") != "qualitative":
        raise ValidationError("this executor supports qualitative synthesis only; quantitative plans require a validated effect-size executor")
    deviation_status = deviations.get("status")
    if (deviations.get("synthesis_deviations_version") != 1
            or deviations.get("synthesis_plan_sha256") != plan_sha
            or deviation_status not in {"no_deviations_declared", "prospective_deviations_recorded",
                                        "retrospective_or_uncertain_deviation_review_required"}):
        raise ValidationError("qualitative synthesis requires a valid deviation declaration bound to the plan")
    validate_synthesis_deviations_boundary(deviations, synthesis_type="qualitative")
    frozen_deviation_plan = deviations.get("frozen_plan_commitments")
    if not isinstance(frozen_deviation_plan, dict):
        raise ValidationError("qualitative synthesis requires deviation-bound frozen plan commitments")
    if (frozen_deviation_plan.get("synthesis_type") != "qualitative"
            or frozen_deviation_plan.get("minimum_independent_studies") != plan.get("minimum_independent_studies")
            or frozen_deviation_plan.get("conclusion_rule") != plan.get("conclusion_rule")):
        raise ValidationError("deviation-bound frozen plan commitments do not match the supplied plan")
    if extraction.get("extraction_version") != 1 or extraction.get("status") != "extraction_recorded":
        raise ValidationError("qualitative synthesis requires a completed version 1 extraction")
    if extraction.get("screening_sha256") != plan.get("screening_sha256"):
        raise ValidationError("synthesis plan and extraction do not bind the same screening artifact")
    extraction_sources, extracted_claims = _validate_extraction_boundary_and_records(extraction)
    plan_sources = plan.get("included_source_ids_at_freeze")
    if (not isinstance(plan_sources, list)
            or any(not isinstance(item, str) or not item.strip() or item != item.strip()
                   for item in plan_sources)
            or len(set(plan_sources)) != len(plan_sources)):
        raise ValidationError("qualitative synthesis requires frozen included source IDs from the plan")
    if len(extraction_sources) != len(set(extraction_sources)):
        raise ValidationError("qualitative synthesis extraction contains duplicate source IDs")
    if sorted(plan_sources) != sorted(extraction_sources):
        raise ValidationError("qualitative synthesis extraction sources do not match the frozen plan")
    inputs = evidence_map.get("inputs")
    if (evidence_map.get("evidence_map_version") != 1
            or evidence_map.get("status") != "evidence_map_recorded"
            or not isinstance(inputs, dict)
            or inputs.get("extraction_sha256") != extraction_sha):
        raise ValidationError("evidence map is incomplete or does not bind the supplied extraction")
    if not (plan.get("snapshot_id") == extraction.get("snapshot_id") == evidence_map.get("snapshot_id")):
        raise ValidationError("synthesis artifacts do not share a snapshot_id")

    claims = evidence_map.get("claims")
    if not isinstance(claims, list) or not claims:
        raise ValidationError("qualitative synthesis requires mapped claims")
    required_claim_fields = {
        "extraction_id", "study_id", "source_id", "extracted_evidence_location",
        "extraction_claim_sha256", "claim_text", "epistemic_layer",
        "result_direction", "uncertainty", "citation_checked_location",
        "citation_rationale", "citation_verdict", "risk_of_bias",
        "bias_domain_judgments", "interpretive_ceiling",
    }
    optional_claim_fields = {
        "source_retained_file_sha256",
        "passage_verification",
    }
    seen = set()
    normalized_claims = []
    for claim in claims:
        if not isinstance(claim, dict):
            raise ValidationError("evidence-map claim fields do not match the synthesis contract")
        claim_fields = set(claim)
        if claim_fields == required_claim_fields:
            claim = {**claim, "source_retained_file_sha256": _LEGACY_SOURCE_ANCHOR}
        elif not required_claim_fields <= claim_fields <= required_claim_fields | optional_claim_fields:
            raise ValidationError("evidence-map claim fields do not match the synthesis contract")
        elif "source_retained_file_sha256" not in claim:
            claim = {**claim, "source_retained_file_sha256": _LEGACY_SOURCE_ANCHOR}
        extraction_id = _canonical_text(claim["extraction_id"], "evidence-map extraction_id")
        if extraction_id in seen:
            raise ValidationError("evidence-map extraction IDs must be unique non-empty text")
        seen.add(extraction_id)
        study_id = _canonical_text(claim["study_id"], "evidence-map study_id")
        source_id = _canonical_text(claim["source_id"], "evidence-map source_id")
        extraction_claim_sha256 = require_sha256(
            claim["extraction_claim_sha256"], "evidence-map extraction_claim_sha256"
        )
        source_retained_file_sha256 = _source_anchor(
            claim["source_retained_file_sha256"],
            "evidence-map source_retained_file_sha256",
        )
        if claim["result_direction"] not in {"supports", "weakens", "mixed", "null", "not_applicable"}:
            raise ValidationError("evidence-map result direction is invalid")
        if claim["interpretive_ceiling"] not in {
            "reviewed_source_claim", "qualified_source_claim", "source_hypothesis_only",
            "insufficient_for_conclusion",
        }:
            raise ValidationError("evidence-map interpretive ceiling is invalid")
        for field in ("extracted_evidence_location", "citation_checked_location", "citation_rationale"):
            if (not isinstance(claim[field], str) or not claim[field].strip()
                    or claim[field] != claim[field].strip()):
                raise ValidationError("evidence-map claim provenance fields must be non-empty text")
        bias_domains = claim["bias_domain_judgments"]
        if not isinstance(bias_domains, list) or not bias_domains:
            raise ValidationError("evidence-map claim requires retained bias-domain judgments")
        seen_domains = set()
        for domain in bias_domains:
            if not isinstance(domain, dict) or set(domain) != {"domain", "judgment", "evidence_locations"}:
                raise ValidationError("evidence-map bias-domain provenance is malformed")
            name, judgment, locations = domain["domain"], domain["judgment"], domain["evidence_locations"]
            name = _canonical_text(name, "evidence-map bias-domain")
            if name in seen_domains:
                raise ValidationError("evidence-map bias-domain names must be unique non-empty text")
            seen_domains.add(name)
            if judgment not in {"low", "some_concerns", "high", "unclear", "not_applicable"}:
                raise ValidationError("evidence-map bias-domain judgment is invalid")
            if (not isinstance(locations, list)
                    or any(not isinstance(item, str) or not item.strip() or item != item.strip()
                           for item in locations)
                    or (judgment != "not_applicable" and not locations)):
                raise ValidationError("evidence-map bias-domain locations are invalid")
        normalized_claims.append({
            **claim,
            "extraction_id": extraction_id,
            "study_id": study_id,
            "source_id": source_id,
            "source_retained_file_sha256": source_retained_file_sha256,
            "extraction_claim_sha256": extraction_claim_sha256,
            "bias_domain_judgments": [
                {**domain, "domain": domain["domain"],
                 "evidence_locations": domain["evidence_locations"]}
                for domain in bias_domains
            ],
        })
        extracted = extracted_claims.get(extraction_id)
        if (extracted is None
                or extracted["source_id"] != source_id
                or extracted["study_id"] != study_id
                or extracted["source_retained_file_sha256"] != source_retained_file_sha256
                or extracted["extraction_claim_sha256"] != extraction_claim_sha256):
            raise ValidationError("evidence-map claim does not replay from the exact extraction payload")
        if "passage_verification" in claim:
            claim["passage_verification"] = _validate_passage_receipt(
                claim.get("passage_verification"),
                "literature synthesis passage_verification",
            )
    if set(extracted_claims) != seen:
        raise ValidationError("qualitative synthesis requires exact extraction-to-map claim coverage")
    validate_evidence_map_boundary(evidence_map, normalized_claims)
    study_ids = {claim["study_id"] for claim in normalized_claims}
    minimum = plan.get("minimum_independent_studies")
    if isinstance(minimum, bool) or not isinstance(minimum, int) or minimum < 1:
        raise ValidationError("frozen synthesis minimum_independent_studies is invalid")
    minimum_met = len(study_ids) >= minimum
    directions = {value: sum(claim["result_direction"] == value for claim in normalized_claims)
                  for value in _RESULT_DIRECTIONS}
    ceilings = {value: sum(claim["interpretive_ceiling"] == value for claim in normalized_claims)
                for value in _INTERPRETIVE_CEILINGS}
    passage_verification_counts = {
        _PASSAGE_MACHINE_VERIFICATION: sum(
            "passage_verification" in claim for claim in normalized_claims
        ),
        "not_provided": sum(
            "passage_verification" not in claim for claim in normalized_claims
        ),
    }
    result = {
        "literature_synthesis_version": 1,
        "inputs": {"synthesis_plan_sha256": plan_sha, "extraction_sha256": extraction_sha,
                   "evidence_map_sha256": evidence_map_sha, "synthesis_deviations_sha256": deviations_sha},
        "deviation_status": deviation_status,
        "deviation_plan_commitments": frozen_deviation_plan,
        "deviations": deviations.get("deviations"),
        "plan_id": plan.get("plan_id"), "snapshot_id": plan.get("snapshot_id"),
        "research_question": plan.get("research_question"),
        "primary_outcome": plan.get("primary_outcome"),
        "conclusion_rule": plan.get("conclusion_rule"),
        "claims": sorted(normalized_claims, key=lambda item: item["extraction_id"]),
        "claim_count": len(normalized_claims), "independent_study_count": len(study_ids),
        "minimum_independent_studies": minimum, "minimum_study_requirement_met": minimum_met,
        "result_direction_counts": directions, "interpretive_ceiling_counts": ceilings,
        "passage_verification_counts": passage_verification_counts,
        "status": ("deviation_review_required"
                   if deviation_status == "retrospective_or_uncertain_deviation_review_required" else
                   "qualitative_synthesis_recorded" if minimum_met else "insufficient_independent_studies"),
        "bounded_conclusion": (
            "No automated substantive conclusion. Evidence is organized for human interpretation under the frozen conclusion rule."
            if minimum_met else
            "No conclusion: the frozen minimum independent-study requirement was not met."
        ),
        "scientific_evidence_eligible": False,
        "conclusion_authorized": False,
        "publication_authorized": False,
        "reviewer_identity_authenticated": False,
        "limitations": [
            "This executor reports complete directional and ceiling counts; counts of claims are not effect sizes and multiple claims from one study are not independent evidence.",
            "Null, adverse, mixed, high-bias, and hypothesis-only claims remain visible and are not filtered from the artifact.",
            "The machine does not interpret prose eligibility rules, assess applicability, resolve heterogeneity, or author a substantive conclusion.",
            "The machine does not authenticate reviewer identity or expertise for the extraction, mapping, deviation, or synthesis judgments.",
            "Execution requires an explicit plan-bound deviation declaration; retrospective or unknown-timing departures force review status.",
        ],
    }
    validate_literature_synthesis_boundary(result)
    root = output.expanduser().resolve()
    if root.exists():
        raise ValidationError("literature synthesis output already exists")
    root.parent.mkdir(parents=True, exist_ok=True)
    encoded = (json.dumps(result, sort_keys=True, indent=2, ensure_ascii=False, allow_nan=False) + "\n").encode()
    with tempfile.TemporaryDirectory(prefix=".literature-synthesis-", dir=root.parent) as temporary:
        staging = Path(temporary) / "literature-synthesis"
        staging.mkdir()
        (staging / "literature-synthesis.json").write_bytes(encoded)
        os.replace(staging, root)
    return {"path": str(root), "literature_synthesis_sha256": hashlib.sha256(encoded).hexdigest(), **result}
