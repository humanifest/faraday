"""Execute a bounded deterministic qualitative literature synthesis."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import tempfile
from typing import Any

from research_machine.domain.errors import ValidationError
from research_machine.literature.evidence_map import validate_evidence_map_boundary
from research_machine.literature.hashes import require_sha256
from research_machine.literature.snapshot import _text

_LEGACY_SOURCE_ANCHOR = "legacy_missing"


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


def _source_anchor(value: object, field: str) -> str:
    if value == _LEGACY_SOURCE_ANCHOR:
        return _LEGACY_SOURCE_ANCHOR
    return require_sha256(value, field)


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
    if plan.get("synthesis_type") != "qualitative":
        raise ValidationError("this executor supports qualitative synthesis only; quantitative plans require a validated effect-size executor")
    deviation_status = deviations.get("status")
    if (deviations.get("synthesis_deviations_version") != 1
            or deviations.get("synthesis_plan_sha256") != plan_sha
            or deviation_status not in {"no_deviations_declared", "prospective_deviations_recorded",
                                        "retrospective_or_uncertain_deviation_review_required"}):
        raise ValidationError("qualitative synthesis requires a valid deviation declaration bound to the plan")
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
    plan_sources = plan.get("included_source_ids_at_freeze")
    if (not isinstance(plan_sources, list)
            or any(not isinstance(item, str) or not item.strip() or item != item.strip()
                   for item in plan_sources)
            or len(set(plan_sources)) != len(plan_sources)):
        raise ValidationError("qualitative synthesis requires frozen included source IDs from the plan")
    extraction_sources = [
        item.get("source_id") for item in extraction.get("source_reviews", [])
        if isinstance(item, dict)
    ]
    if any(not isinstance(item, str) or not item.strip() or item != item.strip()
           for item in extraction_sources):
        raise ValidationError("qualitative synthesis extraction contains invalid source IDs")
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
    seen = set()
    normalized_claims = []
    for claim in claims:
        if not isinstance(claim, dict):
            raise ValidationError("evidence-map claim fields do not match the synthesis contract")
        claim_fields = set(claim)
        if claim_fields == required_claim_fields:
            claim = {**claim, "source_retained_file_sha256": _LEGACY_SOURCE_ANCHOR}
        elif claim_fields != required_claim_fields | {"source_retained_file_sha256"}:
            raise ValidationError("evidence-map claim fields do not match the synthesis contract")
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
    validate_evidence_map_boundary(evidence_map, normalized_claims)
    study_ids = {claim["study_id"] for claim in normalized_claims}
    minimum = plan.get("minimum_independent_studies")
    if isinstance(minimum, bool) or not isinstance(minimum, int) or minimum < 1:
        raise ValidationError("frozen synthesis minimum_independent_studies is invalid")
    minimum_met = len(study_ids) >= minimum
    directions = {value: sum(claim["result_direction"] == value for claim in normalized_claims)
                  for value in ("supports", "weakens", "mixed", "null", "not_applicable")}
    ceilings = {value: sum(claim["interpretive_ceiling"] == value for claim in normalized_claims)
                for value in ("reviewed_source_claim", "qualified_source_claim",
                              "source_hypothesis_only", "insufficient_for_conclusion")}
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
        "status": ("deviation_review_required"
                   if deviation_status == "retrospective_or_uncertain_deviation_review_required" else
                   "qualitative_synthesis_recorded" if minimum_met else "insufficient_independent_studies"),
        "bounded_conclusion": (
            "No automated substantive conclusion. Evidence is organized for human interpretation under the frozen conclusion rule."
            if minimum_met else
            "No conclusion: the frozen minimum independent-study requirement was not met."
        ),
        "scientific_evidence_eligible": False,
        "publication_authorized": False,
        "limitations": [
            "This executor reports complete directional and ceiling counts; counts of claims are not effect sizes and multiple claims from one study are not independent evidence.",
            "Null, adverse, mixed, high-bias, and hypothesis-only claims remain visible and are not filtered from the artifact.",
            "The machine does not interpret prose eligibility rules, assess applicability, resolve heterogeneity, or author a substantive conclusion.",
            "Execution requires an explicit plan-bound deviation declaration; retrospective or unknown-timing departures force review status.",
        ],
    }
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
