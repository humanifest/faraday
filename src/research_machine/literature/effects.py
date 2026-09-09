"""Plan-bound effect-size records for later quantitative synthesis."""
from __future__ import annotations

import hashlib
import json
import math
import os
from pathlib import Path
import tempfile
from typing import Any

from research_machine.domain.errors import ValidationError
from research_machine.literature.evidence_map import validate_evidence_map_boundary
from research_machine.literature.extraction import validate_extraction_boundary
from research_machine.literature.hashes import require_sha256
from research_machine.literature.snapshot import _text
from research_machine.literature.synthesis_plan import validate_synthesis_plan_boundary

_LEGACY_SOURCE_ANCHOR = "legacy_missing"
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
                raise ValidationError("extraction record fields do not match the effect-preparation contract")
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
        raise ValidationError("effect records require extracted claim records")
    return source_ids, extracted_claims


def _positive_integer(value: Any, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ValidationError(f"{field} must be a positive integer")
    return value


def _finite(value: Any, field: str, *, positive: bool = False) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ValidationError(f"{field} must be finite numeric data")
    result = float(value)
    if positive and result <= 0:
        raise ValidationError(f"{field} must be positive")
    return result


def _validate_source_summary_arm(
    arm: Any, *, effect_measure: str, label: str
) -> dict[str, int | float]:
    if not isinstance(arm, dict):
        raise ValidationError(f"{label} must be an object")
    if effect_measure == "mean_difference":
        expected = {"sample_size", "mean", "standard_deviation"}
        if set(arm) != expected:
            raise ValidationError(
                f"{label} requires sample_size, mean, and standard_deviation"
            )
        return {
            "sample_size": _positive_integer(arm["sample_size"], f"{label} sample_size"),
            "mean": _finite(arm["mean"], f"{label} mean"),
            "standard_deviation": _finite(
                arm["standard_deviation"],
                f"{label} standard_deviation",
                positive=True,
            ),
        }
    if effect_measure == "log_risk_ratio":
        expected = {"sample_size", "events"}
        if set(arm) != expected:
            raise ValidationError(f"{label} requires sample_size and events")
        sample_size = _positive_integer(arm["sample_size"], f"{label} sample_size")
        events = _positive_integer(arm["events"], f"{label} events")
        if events > sample_size:
            raise ValidationError(f"{label} events cannot exceed sample_size")
        return {"sample_size": sample_size, "events": events}
    raise ValidationError(
        "retained source summaries require mean_difference or log_risk_ratio"
    )


def validate_retained_source_summaries(
    value: Any, *, expected_statuses: dict[str, str], effect_measure: str
) -> list[dict[str, Any]]:
    if effect_measure not in {"mean_difference", "log_risk_ratio"}:
        raise ValidationError(
            "retained source summaries require mean_difference or log_risk_ratio"
        )
    if not isinstance(value, list):
        raise ValidationError("retained source summaries must be an array")
    required = {
        "study_id",
        "status",
        "reason",
        "evidence_location",
        "experimental",
        "comparator",
    }
    by_study: dict[str, dict[str, Any]] = {}
    for item in value:
        if not isinstance(item, dict) or set(item) != required:
            raise ValidationError(
                "retained source summary fields do not match the documented contract"
            )
        study_id = _canonical_text(item["study_id"], "retained source summary study_id")
        if study_id not in expected_statuses or study_id in by_study:
            raise ValidationError("retained source summary study_id is unknown or duplicated")
        status = item["status"]
        if status != expected_statuses[study_id]:
            raise ValidationError("retained source summary status disagrees with effect record")
        if status not in {"available", "unavailable"}:
            raise ValidationError("retained source summary status is invalid")
        reason = _canonical_text(item["reason"], "retained source summary reason")
        location = _canonical_text(
            item["evidence_location"], "retained source summary evidence_location"
        )
        if status == "unavailable":
            if item["experimental"] is not None or item["comparator"] is not None:
                raise ValidationError("unavailable retained source summaries require null arms")
            experimental = comparator = None
        else:
            experimental = _validate_source_summary_arm(
                item["experimental"],
                effect_measure=effect_measure,
                label="retained source summary experimental arm",
            )
            comparator = _validate_source_summary_arm(
                item["comparator"],
                effect_measure=effect_measure,
                label="retained source summary comparator arm",
            )
        by_study[study_id] = {
            "study_id": study_id,
            "status": status,
            "reason": reason,
            "evidence_location": location,
            "experimental": experimental,
            "comparator": comparator,
        }
    if set(by_study) != set(expected_statuses):
        raise ValidationError("retained source summaries must cover exactly all effect records")
    return [by_study[study_id] for study_id in sorted(by_study)]


def retained_source_summary_sha256(summary: dict[str, Any]) -> str:
    encoded = json.dumps(
        summary,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode()
    return hashlib.sha256(encoded).hexdigest()


def validate_effect_records_boundary(effects: dict[str, Any]) -> None:
    """Replay effect-record non-authority, provenance, counts, and readiness status."""
    if effects.get("scientific_evidence_eligible") is not False:
        raise ValidationError("effect records must remain scientifically ineligible")
    if effects.get("conclusion_authorized") is not False:
        raise ValidationError("effect records must not authorize conclusions")
    if effects.get("publication_authorized") is not False:
        raise ValidationError("effect records must not authorize publication claims")
    limitations = effects.get("limitations")
    if not isinstance(limitations, list) or not limitations:
        raise ValidationError("effect records require retained boundary limitations")
    for index, limitation in enumerate(limitations):
        _canonical_text(limitation, f"effect-record limitation {index + 1}")

    records = effects.get("records")
    if not isinstance(records, list) or not records:
        raise ValidationError("effect records require retained study records")
    effect_measure = _canonical_text(effects.get("effect_measure"), "effect-record effect_measure")
    available = 0
    unavailable = 0
    seen = set()
    expected_statuses: dict[str, str] = {}
    required_record = {
        "study_id", "status", "reason", "risk_of_bias", "mapped_claims",
        "effect_measure", "estimate", "standard_error", "variance",
        "sample_size", "evidence_location", "derivation",
    }
    required_claim = {
        "extraction_id", "extraction_claim_sha256", "source_id",
        "source_retained_file_sha256", "result_direction", "interpretive_ceiling",
        "citation_verdict", "citation_checked_location",
    }
    for item in records:
        if not isinstance(item, dict) or set(item) != required_record:
            raise ValidationError("effect records contain malformed study records")
        study_id = _canonical_text(item.get("study_id"), "effect record study_id")
        if study_id in seen:
            raise ValidationError("effect records contain duplicate study IDs")
        seen.add(study_id)
        if item.get("effect_measure") != effect_measure:
            raise ValidationError("effect record measure does not match artifact measure")
        _canonical_text(item.get("reason"), "effect record reason")
        _canonical_text(item.get("evidence_location"), "effect record evidence_location")
        _canonical_text(item.get("derivation"), "effect record derivation")
        if item.get("risk_of_bias") not in {"low", "some_concerns", "high", "unclear"}:
            raise ValidationError("effect record risk_of_bias is invalid")
        mapped_claims = item.get("mapped_claims")
        if not isinstance(mapped_claims, list) or not mapped_claims:
            raise ValidationError("effect record requires retained mapped claims")
        seen_claims = set()
        for claim in mapped_claims:
            if not isinstance(claim, dict) or set(claim) != required_claim:
                raise ValidationError("effect mapped-claim provenance is malformed")
            extraction_id = _canonical_text(
                claim.get("extraction_id"), "effect mapped claim extraction_id"
            )
            if extraction_id in seen_claims:
                raise ValidationError("effect mapped-claim provenance requires unique extraction IDs")
            seen_claims.add(extraction_id)
            require_sha256(
                claim.get("extraction_claim_sha256"),
                "effect mapped claim extraction_claim_sha256",
            )
            _canonical_text(claim.get("source_id"), "effect mapped claim source_id")
            _source_anchor(
                claim.get("source_retained_file_sha256", _LEGACY_SOURCE_ANCHOR),
                "effect mapped claim source_retained_file_sha256",
            )
            if claim.get("result_direction") not in {
                "supports", "weakens", "mixed", "null", "not_applicable",
            }:
                raise ValidationError("effect mapped-claim result direction is invalid")
            if claim.get("interpretive_ceiling") not in {
                "reviewed_source_claim", "qualified_source_claim",
                "source_hypothesis_only", "insufficient_for_conclusion",
            }:
                raise ValidationError("effect mapped-claim interpretive ceiling is invalid")
            if claim.get("citation_verdict") not in {"supported", "partially_supported"}:
                raise ValidationError("effect mapped-claim citation verdict is invalid")
            _canonical_text(
                claim.get("citation_checked_location"),
                "effect mapped claim citation_checked_location",
            )
        status = item.get("status")
        if status == "available":
            estimate = item.get("estimate")
            standard_error = item.get("standard_error")
            variance = item.get("variance")
            sample_size = item.get("sample_size")
            if (isinstance(estimate, bool) or not isinstance(estimate, (int, float))
                    or not math.isfinite(estimate)):
                raise ValidationError("available effect estimate must be finite numeric data")
            if (isinstance(standard_error, bool) or not isinstance(standard_error, (int, float))
                    or not math.isfinite(standard_error) or standard_error <= 0):
                raise ValidationError("available effect standard_error must be finite and positive")
            if (isinstance(variance, bool) or not isinstance(variance, (int, float))
                    or not math.isfinite(variance) or variance <= 0
                    or not math.isclose(float(variance), float(standard_error) ** 2)):
                raise ValidationError("available effect variance must replay from standard_error")
            if isinstance(sample_size, bool) or not isinstance(sample_size, int) or sample_size <= 0:
                raise ValidationError("available effect sample_size must be a positive integer")
            available += 1
        elif status == "unavailable":
            if any(item.get(field) is not None for field in ("estimate", "standard_error", "variance", "sample_size")):
                raise ValidationError("unavailable effects require null numeric fields")
            unavailable += 1
        else:
            raise ValidationError("effect record status is invalid")
        expected_statuses[study_id] = status

    study_count = effects.get("study_count")
    available_count = effects.get("available_effect_count")
    unavailable_count = effects.get("unavailable_effect_count")
    if isinstance(study_count, bool) or study_count != len(records):
        raise ValidationError("effect-record study_count does not replay from records")
    if isinstance(available_count, bool) or available_count != available:
        raise ValidationError("effect-record available_effect_count does not replay from records")
    if isinstance(unavailable_count, bool) or unavailable_count != unavailable:
        raise ValidationError("effect-record unavailable_effect_count does not replay from records")
    minimum = effects.get("minimum_independent_studies")
    if isinstance(minimum, bool) or not isinstance(minimum, int) or minimum < 1:
        raise ValidationError("effect records require a valid minimum_independent_studies")
    expected_status = "effects_ready" if available >= minimum else "insufficient_effects"
    if effects.get("status") != expected_status:
        raise ValidationError("effect-record status does not replay from retained counts")
    source_summaries = effects.get("source_summaries")
    if source_summaries is not None:
        validate_retained_source_summaries(
            source_summaries,
            expected_statuses=expected_statuses,
            effect_measure=effect_measure,
        )
    if (effects.get("derivation_scope") == "recomputed_from_source_reported_arm_summaries"
            and source_summaries is None):
        raise ValidationError("reproducibly derived effect records require retained source summaries")


def create_effect_records(
    plan_path: Path,
    expected_plan_sha256: str,
    extraction_path: Path,
    evidence_map_path: Path,
    expected_evidence_map_sha256: str,
    review: dict[str, Any],
    output: Path,
    *,
    derivation_scope: str = "reviewer_reported_effect_and_standard_error",
    contrast_definition: str | None = None,
    source_summaries: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    expected_plan_sha256 = require_sha256(expected_plan_sha256, "expected_plan_sha256")
    expected_evidence_map_sha256 = require_sha256(
        expected_evidence_map_sha256, "expected_evidence_map_sha256"
    )
    plan, plan_sha = _load(plan_path, "synthesis plan")
    extraction, extraction_sha = _load(extraction_path, "extraction")
    evidence_map, map_sha = _load(evidence_map_path, "evidence map")
    if plan_sha != expected_plan_sha256 or map_sha != expected_evidence_map_sha256:
        raise ValidationError("effect-record input does not match an expected SHA-256")
    if (plan.get("synthesis_plan_version") != 1 or plan.get("status") != "synthesis_plan_frozen"
            or plan.get("synthesis_type") != "quantitative"):
        raise ValidationError("effect records require a frozen quantitative synthesis plan")
    validate_synthesis_plan_boundary(plan)
    if (extraction.get("extraction_version") != 1 or extraction.get("status") != "extraction_recorded"
            or extraction.get("screening_sha256") != plan.get("screening_sha256")):
        raise ValidationError("effect records require an extraction from the plan's pinned screening")
    extraction_sources, extracted_claims = _validate_extraction_boundary_and_records(extraction)
    plan_sources = plan.get("included_source_ids_at_freeze")
    if (not isinstance(plan_sources, list)
            or any(not isinstance(item, str) or not item.strip() or item != item.strip()
                   for item in plan_sources)
            or len(set(plan_sources)) != len(plan_sources)):
        raise ValidationError("effect records require frozen included source IDs from the synthesis plan")
    if len(extraction_sources) != len(set(extraction_sources)):
        raise ValidationError("effect records extraction contains duplicate source IDs")
    if sorted(plan_sources) != sorted(extraction_sources):
        raise ValidationError("effect records extraction sources do not match the frozen synthesis plan")
    inputs = evidence_map.get("inputs")
    if (evidence_map.get("evidence_map_version") != 1 or evidence_map.get("status") != "evidence_map_recorded"
            or not isinstance(inputs, dict) or inputs.get("extraction_sha256") != extraction_sha):
        raise ValidationError("effect records require an evidence map bound to the supplied extraction")
    if not (plan.get("snapshot_id") == extraction.get("snapshot_id") == evidence_map.get("snapshot_id")):
        raise ValidationError("effect-record artifacts do not share a snapshot_id")
    claims = evidence_map.get("claims")
    if not isinstance(claims, list) or not claims:
        raise ValidationError("effect records require mapped claims")
    studies = set()
    study_biases: dict[str, str] = {}
    study_claims: dict[str, list[dict[str, Any]]] = {}
    for claim in claims:
        if not isinstance(claim, dict) or claim.get("risk_of_bias") not in {"low", "some_concerns", "high", "unclear"}:
            raise ValidationError("mapped claims require a valid study risk_of_bias")
        study_id = _canonical_text(claim.get("study_id"), "mapped claim study_id")
        studies.add(study_id)
        prior = study_biases.setdefault(study_id, claim["risk_of_bias"])
        if prior != claim["risk_of_bias"]:
            raise ValidationError("mapped claims disagree on study risk_of_bias")
        extraction_claim_sha256 = require_sha256(
            claim.get("extraction_claim_sha256"), "mapped claim extraction_claim_sha256"
        )
        source_retained_file_sha256 = _source_anchor(
            claim.get("source_retained_file_sha256", _LEGACY_SOURCE_ANCHOR),
            "mapped claim source_retained_file_sha256",
        )
        claim_summary = {
            "extraction_id": claim.get("extraction_id"),
            "extraction_claim_sha256": extraction_claim_sha256,
            "source_id": claim.get("source_id"),
            "source_retained_file_sha256": source_retained_file_sha256,
            "result_direction": claim.get("result_direction"),
            "interpretive_ceiling": claim.get("interpretive_ceiling"),
            "citation_verdict": claim.get("citation_verdict"),
            "citation_checked_location": claim.get("citation_checked_location"),
        }
        if any(not isinstance(value, str) or not value.strip() or value != value.strip()
               for value in claim_summary.values()):
            raise ValidationError("mapped claims require retained citation provenance before effect preparation")
        extracted = extracted_claims.get(_canonical_text(claim_summary["extraction_id"], "mapped claim extraction_id"))
        if (extracted is None
                or extracted["source_id"] != _canonical_text(claim_summary["source_id"], "mapped claim source_id")
                or extracted["study_id"] != study_id
                or extracted["source_retained_file_sha256"] != source_retained_file_sha256
                or extracted["extraction_claim_sha256"] != extraction_claim_sha256):
            raise ValidationError("mapped claim does not replay from the exact extraction payload")
        study_claims.setdefault(study_id, []).append(
            dict(claim_summary)
        )
    if set(extracted_claims) != {
        _canonical_text(claim.get("extraction_id"), "mapped claim extraction_id")
        for claim in claims
        if isinstance(claim, dict)
    }:
        raise ValidationError("effect records require exact extraction-to-map claim coverage")
    validate_evidence_map_boundary(evidence_map, claims)

    if not isinstance(review, dict) or set(review) != {"reviewer", "records"}:
        raise ValidationError("effect review requires exactly reviewer and records")
    reviewer = _canonical_text(review["reviewer"], "effect reviewer")
    records = review["records"]
    if not isinstance(records, list):
        raise ValidationError("effect records must be an array")
    required = {"study_id", "status", "reason", "effect_measure", "estimate",
                "standard_error", "sample_size", "evidence_location", "derivation"}
    by_study: dict[str, dict[str, Any]] = {}
    expected_measure = plan.get("effect_measure")
    for item in records:
        if not isinstance(item, dict) or set(item) != required:
            raise ValidationError("effect record fields do not match the documented contract")
        study_id = _canonical_text(item["study_id"], "effect study_id")
        if study_id not in studies or study_id in by_study:
            raise ValidationError("effect study_id is unknown or duplicated")
        status = item["status"]
        if status not in {"available", "unavailable"}:
            raise ValidationError("effect status must be available or unavailable")
        if item["effect_measure"] != expected_measure:
            raise ValidationError("effect measure must exactly match the frozen synthesis plan")
        reason = _canonical_text(item["reason"], "effect reason")
        location = _canonical_text(item["evidence_location"], "effect evidence_location")
        derivation = _canonical_text(item["derivation"], "effect derivation")
        estimate, standard_error, sample_size = item["estimate"], item["standard_error"], item["sample_size"]
        if status == "available":
            if (isinstance(estimate, bool) or not isinstance(estimate, (int, float))
                    or not math.isfinite(estimate)):
                raise ValidationError("available effect estimate must be finite numeric data")
            if (isinstance(standard_error, bool) or not isinstance(standard_error, (int, float))
                    or not math.isfinite(standard_error) or standard_error <= 0):
                raise ValidationError("available effect standard_error must be finite and positive")
            if isinstance(sample_size, bool) or not isinstance(sample_size, int) or sample_size <= 0:
                raise ValidationError("available effect sample_size must be a positive integer")
        elif any(value is not None for value in (estimate, standard_error, sample_size)):
            raise ValidationError("unavailable effects require null estimate, standard_error, and sample_size")
        by_study[study_id] = {"study_id": study_id, "status": status, "reason": reason,
            "risk_of_bias": study_biases[study_id],
            "mapped_claims": sorted(study_claims[study_id], key=lambda claim: claim["extraction_id"]),
            "effect_measure": expected_measure, "estimate": estimate, "standard_error": standard_error,
            "variance": standard_error ** 2 if status == "available" else None,
            "sample_size": sample_size, "evidence_location": location, "derivation": derivation}
    if set(by_study) != studies:
        raise ValidationError("effect records must cover exactly all mapped studies")
    available = sum(item["status"] == "available" for item in by_study.values())
    minimum = plan.get("minimum_independent_studies")
    if isinstance(minimum, bool) or not isinstance(minimum, int) or minimum < 1:
        raise ValidationError("frozen minimum_independent_studies is invalid")
    retained_source_summaries = (
        validate_retained_source_summaries(
            source_summaries,
            expected_statuses={
                study_id: record["status"] for study_id, record in by_study.items()
            },
            effect_measure=expected_measure,
        )
        if source_summaries is not None
        else None
    )
    result = {"effect_records_version": 1, "inputs": {"synthesis_plan_sha256": plan_sha,
        "extraction_sha256": extraction_sha, "evidence_map_sha256": map_sha},
        "plan_id": plan.get("plan_id"), "snapshot_id": plan.get("snapshot_id"),
        "reviewer": reviewer, "effect_measure": expected_measure,
        "derivation_scope": _canonical_text(derivation_scope, "effect derivation_scope"),
        "contrast_definition": contrast_definition,
        "source_summaries": retained_source_summaries,
        "records": [by_study[item] for item in sorted(by_study)], "study_count": len(studies),
        "available_effect_count": available, "unavailable_effect_count": len(studies) - available,
        "minimum_independent_studies": minimum,
        "status": "effects_ready" if available >= minimum else "insufficient_effects",
        "scientific_evidence_eligible": False,
        "conclusion_authorized": False,
        "publication_authorized": False,
        "limitations": [
            "Effect values and derivations are reviewer assertions; the machine validates shape and variance but does not reproduce calculations from source data.",
            "Unavailable statistics remain explicit and are not imputed or silently excluded.",
            "One planned effect per study avoids within-study double counting but does not establish outcome compatibility or authorize pooling.",
        ]}
    validate_effect_records_boundary(result)
    root = output.expanduser().resolve()
    if root.exists():
        raise ValidationError("effect-record output already exists")
    root.parent.mkdir(parents=True, exist_ok=True)
    encoded = (json.dumps(result, sort_keys=True, indent=2, ensure_ascii=False, allow_nan=False) + "\n").encode()
    with tempfile.TemporaryDirectory(prefix=".effect-records-", dir=root.parent) as temporary:
        staging = Path(temporary) / "effect-records"; staging.mkdir()
        (staging / "effect-records.json").write_bytes(encoded); os.replace(staging, root)
    return {"path": str(root), "effect_records_sha256": hashlib.sha256(encoded).hexdigest(), **result}
