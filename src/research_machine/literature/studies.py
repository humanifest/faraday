"""Study-identity reconciliation that prevents silent double counting."""
from __future__ import annotations

import hashlib
import itertools
import json
import os
from pathlib import Path
import tempfile
from typing import Any

from research_machine.domain.errors import ValidationError
from research_machine.literature.bias import validate_bias_assessment_boundary
from research_machine.literature.hashes import require_sha256
from research_machine.literature.snapshot import _text


_RELATIONSHIPS = {"independent", "overlapping_cohort", "duplicate_report", "unclear"}
def _canonical_text(value: Any, field: str) -> str:
    text = _text(value, field)
    if text != text.strip():
        raise ValidationError(f"{field} must be canonical without surrounding whitespace")
    return text


def validate_study_reconciliation_boundary(
    reconciliation: dict[str, Any],
    relationships: list[dict[str, Any]],
    *,
    require_reconciled: bool = False,
    require_reconciliation_contract: bool = False,
) -> None:
    """Replay study-reconciliation non-authority boundaries and pair counts."""
    if (
        not isinstance(reconciliation, dict)
        or reconciliation.get("study_reconciliation_version") != 1
    ):
        raise ValidationError("study reconciliation version is invalid")
    require_sha256(
        reconciliation.get("bias_assessment_sha256"),
        "study reconciliation bias_assessment_sha256",
    )
    _canonical_text(reconciliation.get("snapshot_id"), "study reconciliation snapshot_id")
    _canonical_text(reconciliation.get("reviewer"), "study reconciliation reviewer")
    if reconciliation.get("independent_review") is not True:
        raise ValidationError("study reconciliation must retain independent-review status")
    if reconciliation.get("scientific_evidence_eligible") is not False:
        raise ValidationError("study reconciliation must remain scientifically ineligible")
    if reconciliation.get("conclusion_authorized") is not False:
        raise ValidationError("study reconciliation must not authorize conclusions")
    if reconciliation.get("publication_authorized") is not False:
        raise ValidationError("study reconciliation must not authorize publication")
    reviewer_identity_authenticated = reconciliation.get(
        "reviewer_identity_authenticated", False
    )
    if reviewer_identity_authenticated is not False:
        raise ValidationError(
            "study reconciliation must not authenticate reviewer identity"
        )
    limitations = reconciliation.get("limitations")
    if not isinstance(limitations, list) or not limitations:
        raise ValidationError("study reconciliation requires retained boundary limitations")
    for index, limitation in enumerate(limitations):
        _canonical_text(limitation, f"study reconciliation limitation {index + 1}")
    if (
        not isinstance(reconciliation.get("studies"), list)
        or not reconciliation["studies"]
    ):
        raise ValidationError("study reconciliation requires retained studies")
    if (
        not isinstance(relationships, list)
        or reconciliation.get("relationships") != relationships
    ):
        raise ValidationError("study reconciliation relationships must be retained")
    counts = {relationship: 0 for relationship in sorted(_RELATIONSHIPS)}
    for item in relationships:
        if not isinstance(item, dict):
            raise ValidationError("study relationship is invalid")
        relationship = item.get("relationship")
        if relationship not in _RELATIONSHIPS:
            raise ValidationError("study relationship is invalid")
        counts[relationship] += 1
    if reconciliation.get("relationship_counts") != counts:
        raise ValidationError("study reconciliation relationship_counts do not replay from relationships")
    expected_status = (
        "review_required"
        if counts["overlapping_cohort"] or counts["duplicate_report"] or counts["unclear"]
        else "study_identities_reconciled"
    )
    if reconciliation.get("status") != expected_status:
        raise ValidationError("study reconciliation status does not replay from relationships")
    if require_reconciled and expected_status != "study_identities_reconciled":
        raise ValidationError("evidence map requires fully reconciled independent study identities")
    if require_reconciliation_contract:
        studies = reconciliation.get("studies")
        if not isinstance(studies, list) or not studies:
            raise ValidationError("study reconciliation requires retained studies")
        required_study = {
            "study_id",
            "source_ids",
            "registration_ids",
            "population",
            "setting",
            "recruitment_period",
            "sample_size",
            "identity_notes",
        }
        by_study: dict[str, dict[str, Any]] = {}
        for study in studies:
            if not isinstance(study, dict) or set(study) != required_study:
                raise ValidationError(
                    "reconciled study metadata fields do not match the documented contract"
                )
            study_id = _canonical_text(study.get("study_id"), "reconciled study_id")
            if study_id in by_study:
                raise ValidationError("reconciled studies contain duplicate study_id")
            source_ids = study.get("source_ids")
            if (
                not isinstance(source_ids, list)
                or not source_ids
                or any(
                    not isinstance(source, str)
                    or not source.strip()
                    or source != source.strip()
                    for source in source_ids
                )
                or len(source_ids) != len(set(source_ids))
            ):
                raise ValidationError(
                    "reconciled source_ids must be unique non-empty canonical text"
                )
            registration_ids = study.get("registration_ids")
            if (
                not isinstance(registration_ids, list)
                or any(
                    not isinstance(value, str)
                    or not value.strip()
                    or value != value.strip()
                    for value in registration_ids
                )
                or len(registration_ids) != len(set(registration_ids))
            ):
                raise ValidationError("registration_ids must be unique non-empty text")
            sample_size = study.get("sample_size")
            if (
                isinstance(sample_size, bool)
                or not isinstance(sample_size, int)
                or sample_size <= 0
            ):
                raise ValidationError("study sample_size must be a positive integer")
            _canonical_text(study.get("population"), "study population")
            _canonical_text(study.get("setting"), "study setting")
            _canonical_text(study.get("recruitment_period"), "recruitment_period")
            _canonical_text(study.get("identity_notes"), "identity_notes")
            by_study[study_id] = study

        expected_pairs = {
            tuple(pair) for pair in itertools.combinations(sorted(by_study), 2)
        }
        by_pair: dict[tuple[str, str], dict[str, Any]] = {}
        required_relationship = {
            "study_ids",
            "relationship",
            "rationale",
            "evidence_locations",
        }
        for item in relationships:
            if not isinstance(item, dict) or set(item) != required_relationship:
                raise ValidationError(
                    "study relationship fields do not match the documented contract"
                )
            pair = item.get("study_ids")
            if (
                not isinstance(pair, list)
                or len(pair) != 2
                or any(
                    not isinstance(value, str)
                    or not value.strip()
                    or value != value.strip()
                    for value in pair
                )
            ):
                raise ValidationError("study_ids must name two distinct assessed studies")
            if any(value not in by_study for value in pair) or pair[0] == pair[1]:
                raise ValidationError("study_ids must name two distinct assessed studies")
            key = tuple(sorted(pair))
            if key in by_pair:
                raise ValidationError("duplicate study relationship")
            if item.get("relationship") not in _RELATIONSHIPS:
                raise ValidationError("invalid study relationship")
            locations = item.get("evidence_locations")
            if (
                not isinstance(locations, list)
                or not locations
                or any(
                    not isinstance(value, str)
                    or not value.strip()
                    or value != value.strip()
                    for value in locations
                )
            ):
                raise ValidationError("study relationships require evidence_locations")
            _canonical_text(item.get("rationale"), "relationship rationale")
            by_pair[key] = item
        if set(by_pair) != expected_pairs:
            raise ValidationError(
                "study relationships must cover every unordered pair exactly once"
            )


def create_study_reconciliation(
    bias_path: Path,
    expected_sha256: str,
    review: dict[str, Any],
    output: Path,
) -> dict[str, Any]:
    expected_sha256 = require_sha256(expected_sha256, "expected_bias_assessment_sha256")
    try:
        content = bias_path.read_bytes()
        bias = json.loads(content)
    except (OSError, UnicodeDecodeError, ValueError) as exc:
        raise ValidationError("could not read valid bias-assessment JSON") from exc
    digest = hashlib.sha256(content).hexdigest()
    if digest != expected_sha256:
        raise ValidationError("study reconciliation bias assessment does not match the expected SHA-256")
    if (not isinstance(bias, dict) or bias.get("bias_assessment_version") != 1
            or bias.get("status") != "bias_assessment_recorded"):
        raise ValidationError("study reconciliation requires a completed version 1 bias assessment")
    prior_reviewer = _canonical_text(bias.get("reviewer"), "bias reviewer")
    bias_assessments = bias.get("assessments")
    if not isinstance(bias_assessments, list) or not bias_assessments:
        raise ValidationError("study reconciliation requires bias-assessed studies")
    validate_bias_assessment_boundary(
        bias,
        bias_assessments,
        require_assessment_contract=True,
    )
    studies: dict[str, list[str]] = {}
    for item in bias_assessments:
        if not isinstance(item, dict):
            raise ValidationError("bias study assessment must be an object")
        study_id = _canonical_text(item.get("study_id"), "bias study_id")
        source_ids = item.get("source_ids")
        if (not isinstance(source_ids, list) or not source_ids
                or any(not isinstance(source, str) or not source.strip() or source != source.strip()
                       for source in source_ids)):
            raise ValidationError("bias study source_ids must be non-empty text")
        if len(source_ids) != len(set(source_ids)):
            raise ValidationError("bias study source_ids must be unique")
        if study_id in studies:
            raise ValidationError("bias assessment contains duplicate study_id")
        studies[study_id] = sorted(source_ids)

    if not isinstance(review, dict) or set(review) != {"reviewer", "studies", "relationships"}:
        raise ValidationError("study reconciliation requires exactly reviewer, studies, and relationships")
    reviewer = _canonical_text(review["reviewer"], "study reconciliation reviewer")
    if reviewer.casefold() == prior_reviewer.casefold():
        raise ValidationError("study reconciliation reviewer must differ from the bias reviewer")
    metadata = review["studies"]
    if not isinstance(metadata, list):
        raise ValidationError("reconciled studies must be an array")
    by_study: dict[str, dict[str, Any]] = {}
    required_study = {
        "study_id", "source_ids", "registration_ids", "population", "setting",
        "recruitment_period", "sample_size", "identity_notes",
    }
    for item in metadata:
        if not isinstance(item, dict) or set(item) != required_study:
            raise ValidationError("reconciled study metadata fields do not match the documented contract")
        study_id = _canonical_text(item["study_id"], "reconciled study_id")
        if study_id not in studies or study_id in by_study:
            raise ValidationError("reconciled study_id is unknown or duplicated")
        source_ids = item["source_ids"]
        if (not isinstance(source_ids, list)
                or any(not isinstance(source, str) or not source.strip() or source != source.strip()
                       for source in source_ids)):
            raise ValidationError("reconciled source_ids must exactly match the bias assessment")
        if (len(source_ids) != len(set(source_ids))
                or set(source_ids) != set(studies[study_id])):
            raise ValidationError("reconciled source_ids must exactly match the bias assessment")
        registration_ids = item["registration_ids"]
        if (not isinstance(registration_ids, list)
                or any(not isinstance(value, str) or not value.strip() or value != value.strip()
                       for value in registration_ids)
                or len(set(registration_ids)) != len(registration_ids)):
            raise ValidationError("registration_ids must be unique non-empty text")
        sample_size = item["sample_size"]
        if isinstance(sample_size, bool) or not isinstance(sample_size, int) or sample_size <= 0:
            raise ValidationError("study sample_size must be a positive integer")
        by_study[study_id] = {
            "study_id": study_id, "source_ids": sorted(source_ids),
            "registration_ids": sorted(registration_ids),
            "population": _canonical_text(item["population"], "study population"),
            "setting": _canonical_text(item["setting"], "study setting"),
            "recruitment_period": _canonical_text(item["recruitment_period"], "recruitment_period"),
            "sample_size": sample_size,
            "identity_notes": _canonical_text(item["identity_notes"], "identity_notes"),
        }
    if set(by_study) != set(studies):
        raise ValidationError("reconciled study metadata must cover exactly all bias-assessed studies")

    expected_pairs = {tuple(pair) for pair in itertools.combinations(sorted(studies), 2)}
    relationships = review["relationships"]
    if not isinstance(relationships, list):
        raise ValidationError("study relationships must be an array")
    by_pair: dict[tuple[str, str], dict[str, Any]] = {}
    required_relationship = {"study_ids", "relationship", "rationale", "evidence_locations"}
    for item in relationships:
        if not isinstance(item, dict) or set(item) != required_relationship:
            raise ValidationError("study relationship fields do not match the documented contract")
        pair = item["study_ids"]
        if (not isinstance(pair, list) or len(pair) != 2
                or any(not isinstance(value, str) or not value.strip() or value != value.strip()
                       for value in pair)):
            raise ValidationError("study_ids must name two distinct assessed studies")
        if (any(value not in studies for value in pair) or pair[0] == pair[1]):
            raise ValidationError("study_ids must name two distinct assessed studies")
        key = tuple(sorted(pair))
        if key in by_pair:
            raise ValidationError("duplicate study relationship")
        relationship = item["relationship"]
        if relationship not in _RELATIONSHIPS:
            raise ValidationError("invalid study relationship")
        locations = item["evidence_locations"]
        if (not isinstance(locations, list) or not locations
                or any(not isinstance(value, str) or not value.strip() or value != value.strip()
                       for value in locations)):
            raise ValidationError("study relationships require evidence_locations")
        by_pair[key] = {
            "study_ids": list(key), "relationship": relationship,
            "rationale": _canonical_text(item["rationale"], "relationship rationale"),
            "evidence_locations": locations,
        }
    if set(by_pair) != expected_pairs:
        raise ValidationError("study relationships must cover every unordered pair exactly once")

    counts = {value: sum(item["relationship"] == value for item in by_pair.values())
              for value in sorted(_RELATIONSHIPS)}
    unresolved = bool(counts["overlapping_cohort"] or counts["duplicate_report"] or counts["unclear"])
    result = {
        "study_reconciliation_version": 1,
        "bias_assessment_sha256": digest,
        "snapshot_id": bias.get("snapshot_id"),
        "reviewer": reviewer,
        "independent_review": True,
        "studies": [by_study[item] for item in sorted(by_study)],
        "relationships": [by_pair[item] for item in sorted(by_pair)],
        "relationship_counts": counts,
        "status": "review_required" if unresolved else "study_identities_reconciled",
        "scientific_evidence_eligible": False,
        "conclusion_authorized": False,
        "publication_authorized": False,
        "reviewer_identity_authenticated": False,
        "limitations": [
            "Pairwise identity judgments are reviewer assertions; metadata similarity cannot prove cohort independence.",
            "Overlap, duplicate, and unclear relationships are preserved and block a reconciled status rather than being silently deduplicated.",
            "Study reconciliation does not validate outcomes, assess applicability, or authorize quantitative synthesis.",
        ],
    }
    validate_study_reconciliation_boundary(
        result,
        result["relationships"],
        require_reconciliation_contract=True,
    )
    root = output.expanduser().resolve()
    if root.exists():
        raise ValidationError("study reconciliation output already exists")
    root.parent.mkdir(parents=True, exist_ok=True)
    encoded = (json.dumps(result, sort_keys=True, indent=2, ensure_ascii=False, allow_nan=False) + "\n").encode()
    with tempfile.TemporaryDirectory(prefix=".study-reconciliation-", dir=root.parent) as temporary:
        staging = Path(temporary) / "study-reconciliation"
        staging.mkdir()
        (staging / "study-reconciliation.json").write_bytes(encoded)
        os.replace(staging, root)
    return {"path": str(root), "study_reconciliation_sha256": hashlib.sha256(encoded).hexdigest(), **result}
