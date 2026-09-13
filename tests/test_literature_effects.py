"""Synthetic effect records validate provenance and variance, not scientific truth."""
import copy
import hashlib
import json

import pytest

from research_machine.domain.errors import ValidationError
from research_machine.interfaces.cli import main
from research_machine.literature.effects import (
    create_effect_records,
    validate_effect_records_boundary,
)


def write_json(path, value):
    encoded = (json.dumps(value, sort_keys=True, indent=2) + "\n").encode(); path.write_bytes(encoded)
    return hashlib.sha256(encoded).hexdigest()


def claim_digest(source_id, record, source_retained_file_sha256="legacy_missing"):
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
    if source_retained_file_sha256 != "legacy_missing":
        payload["source_retained_file_sha256"] = source_retained_file_sha256
    return hashlib.sha256(
        json.dumps(
            payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False
        ).encode("utf-8")
    ).hexdigest()


def passage_receipt():
    return {
        "passage_verification_sha256": "c" * 64,
        "evidence_quote_sha256": "d" * 64,
        "quote_utf8_byte_count": 17,
        "quote_occurrence_count": 1,
        "machine_verification": "exact_utf8_quote_found_in_retained_source_bytes",
    }


def artifacts(tmp_path, minimum=1, with_passage=False):
    screening_sha = "1" * 64
    plan = tmp_path / "plan.json"
    plan_sha = write_json(plan, {"synthesis_plan_version": 1, "status": "synthesis_plan_frozen",
        "synthesis_type": "quantitative", "effect_measure": "log_risk_ratio",
        "contrast_definition": "experimental versus comparator",
        "minimum_independent_studies": minimum, "screening_sha256": screening_sha,
        "snapshot_id": "snap", "plan_id": "p1", "included_source_ids_at_freeze": ["source-fixture"],
        "scientific_evidence_eligible": False,
        "conclusion_authorized": False,
        "publication_authorized": False,
        "limitations": [
            "A frozen synthesis plan is a prospective commitment, not evidence.",
        ]})
    extraction = tmp_path / "extraction.json"
    extraction_records = [
        {"extraction_id": "claim-1", "study_id": "study-1",
         "claim_text": "Synthetic claim 1", "evidence_location": "page 1",
         "epistemic_layer": "observed", "result_direction": "mixed",
         "uncertainty": "fixture", "notes": "fixture notes 1"},
        {"extraction_id": "claim-2", "study_id": "study-2",
         "claim_text": "Synthetic claim 2", "evidence_location": "page 2",
         "epistemic_layer": "observed", "result_direction": "mixed",
         "uncertainty": "fixture", "notes": "fixture notes 2"},
    ]
    extraction_sha = write_json(extraction, {"extraction_version": 1, "status": "extraction_recorded",
        "screening_sha256": screening_sha, "snapshot_id": "snap", "record_count": 2,
        "scientific_evidence_eligible": False,
        "conclusion_authorized": False,
        "publication_authorized": False,
        "limitations": [
            "Records are reviewer assertions bound to source IDs and locations; the machine has not verified that source text supports them.",
            "Extraction does not perform risk-of-bias assessment, resolve disagreements, accept claims as facts, or conduct synthesis.",
        ],
        "source_reviews": [{"source_id": "source-fixture", "records": extraction_records}]})
    evidence_map = tmp_path / "map.json"
    def mapped_claim(extraction_id, study_id, digest):
        claim = {"study_id": study_id, "risk_of_bias": "low" if study_id == "study-1" else "high",
            "extraction_id": extraction_id,
            "source_id": "source-fixture",
            "extraction_claim_sha256": digest,
            "result_direction": "mixed",
            "interpretive_ceiling": "reviewed_source_claim",
            "citation_verdict": "supported",
            "citation_checked_location": "page fixture",
        }
        if with_passage:
            claim["passage_verification"] = passage_receipt()
        return claim
    map_sha = write_json(evidence_map, {"evidence_map_version": 1, "status": "evidence_map_recorded",
        "snapshot_id": "snap", "inputs": {
            "extraction_sha256": extraction_sha,
            "citation_verification_sha256": "2" * 64,
            "bias_assessment_sha256": "3" * 64,
            "study_reconciliation_sha256": "4" * 64,
        },
        "claims": [
            mapped_claim("claim-1", "study-1", claim_digest("source-fixture", extraction_records[0])),
            mapped_claim("claim-2", "study-2", claim_digest("source-fixture", extraction_records[1])),
        ],
        "claim_count": 2, "study_count": 2,
        "interpretive_ceiling_counts": {"reviewed_source_claim": 2},
        "scientific_evidence_eligible": False, "conclusion_authorized": False,
        "publication_authorized": False,
        "limitations": [
            "This deterministic map joins reviewed assertions without authorizing conclusions."
        ]})
    return plan, plan_sha, extraction, evidence_map, map_sha


def review(second="unavailable"):
    def record(study_id, status):
        available = status == "available"
        return {"study_id": study_id, "status": status, "reason": "Fixture record",
            "effect_measure": "log_risk_ratio", "estimate": 0.2 if available else None,
            "standard_error": 0.1 if available else None, "sample_size": 40 if available else None,
            "evidence_location": "table 2", "derivation": "Reported estimate and standard error"}
    return {"reviewer": "Effect reviewer", "records": [record("study-1", "available"), record("study-2", second)]}


def test_effect_cli_preserves_unavailable_study_and_is_write_once(tmp_path, capsys):
    plan, plan_sha, extraction, evidence_map, map_sha = artifacts(tmp_path)
    review_path = tmp_path / "review.json"; review_path.write_text(json.dumps(review()))
    output = tmp_path / "effects"
    assert main(["--json", "literature", "prepare-effects", "--plan-file", str(plan),
        "--expected-plan-sha256", plan_sha, "--extraction-file", str(extraction),
        "--evidence-map-file", str(evidence_map), "--expected-evidence-map-sha256", map_sha,
        "--review-file", str(review_path), "--output", str(output)]) == 0
    result = json.loads(capsys.readouterr().out)["result"]
    assert result["available_effect_count"] == 1 and result["unavailable_effect_count"] == 1
    assert result["records"][0]["variance"] == pytest.approx(0.01)
    assert result["contrast_definition"] == "experimental versus comparator"
    assert result["records"][1]["risk_of_bias"] == "high"
    assert result["records"][0]["mapped_claims"][0]["extraction_id"] == "claim-1"
    extraction_record = json.loads(extraction.read_text())["source_reviews"][0]["records"][0]
    assert result["records"][0]["mapped_claims"][0]["extraction_claim_sha256"] == claim_digest(
        "source-fixture", extraction_record
    )
    assert result["records"][0]["mapped_claims"][0]["citation_checked_location"] == "page fixture"
    assert result["scientific_evidence_eligible"] is False
    assert result["conclusion_authorized"] is False
    assert result["publication_authorized"] is False
    assert result["reviewer_identity_authenticated"] is False
    with pytest.raises(ValidationError, match="already exists"):
        create_effect_records(plan, plan_sha, extraction, evidence_map, map_sha, review(), output)


def test_insufficient_effects_is_recorded(tmp_path):
    plan, plan_sha, extraction, evidence_map, map_sha = artifacts(tmp_path, minimum=2)
    result = create_effect_records(plan, plan_sha, extraction, evidence_map, map_sha, review(), tmp_path / "effects")
    assert result["status"] == "insufficient_effects"


def test_effect_records_preserve_canonical_study_and_source_handles(tmp_path):
    plan, plan_sha, extraction, evidence_map, map_sha = artifacts(tmp_path)
    result = create_effect_records(plan, plan_sha, extraction, evidence_map, map_sha, review(), tmp_path / "effects")
    assert result["records"][0]["study_id"] == "study-1"
    assert result["records"][0]["mapped_claims"][0]["source_id"] == "source-fixture"
    assert result["records"][0]["evidence_location"] == "table 2"


def test_effect_records_preserve_passage_verification_receipts(tmp_path):
    plan, plan_sha, extraction, evidence_map, map_sha = artifacts(tmp_path, with_passage=True)
    result = create_effect_records(
        plan, plan_sha, extraction, evidence_map, map_sha, review(), tmp_path / "effects"
    )
    assert result["records"][0]["mapped_claims"][0]["passage_verification"] == passage_receipt()
    validate_effect_records_boundary(result)
    candidate = copy.deepcopy(result)
    candidate["records"][0]["mapped_claims"][0]["passage_verification"][
        "evidence_quote_sha256"
    ] = "A" * 64
    with pytest.raises(ValidationError):
        validate_effect_records_boundary(candidate)


@pytest.mark.parametrize(
    ("payload", "message"),
    [
        ('{"evidence_map_version": 1, "evidence_map_version": 1}\n', "duplicate JSON object key"),
        ('{"evidence_map_version": NaN}\n', "non-finite JSON number"),
    ],
)
def test_effect_records_reject_ambiguous_json_input_bytes(tmp_path, payload, message):
    plan, plan_sha, extraction, evidence_map, _map_sha = artifacts(tmp_path)
    evidence_map.write_text(payload, encoding="utf-8")
    tampered_map_sha = hashlib.sha256(evidence_map.read_bytes()).hexdigest()
    output = tmp_path / "effects"

    with pytest.raises(ValidationError, match=message):
        create_effect_records(
            plan,
            plan_sha,
            extraction,
            evidence_map,
            tampered_map_sha,
            review(),
            output,
        )
    assert not output.exists()


@pytest.mark.parametrize("tamper", [
    "version",
    "inputs-missing",
    "inputs-extra",
    "plan-input-hash",
    "extraction-input-hash",
    "map-input-hash",
    "plan-id",
    "snapshot-id",
    "reviewer",
    "derivation-scope",
    "scientific-authority",
    "conclusion-authority",
    "publication-authority",
    "reviewer-authenticated",
    "overclaim-limitation",
    "claim-count",
    "availability-count",
    "status-drift",
    "variance-drift",
    "unavailable-numeric",
    "overclaim-reason",
    "overclaim-derivation",
    "mapped-claim-digest",
    "padded-mapped-claim",
    "recomputed-without-summaries",
    "contrast-missing",
])
def test_effect_records_boundary_replays_output_summaries(tmp_path, tamper):
    plan, plan_sha, extraction, evidence_map, map_sha = artifacts(tmp_path)
    result = create_effect_records(
        plan, plan_sha, extraction, evidence_map, map_sha, review(), tmp_path / "effects"
    )
    candidate = copy.deepcopy(result)
    if tamper == "version":
        candidate["effect_records_version"] = 2
    elif tamper == "inputs-missing":
        del candidate["inputs"]["extraction_sha256"]
    elif tamper == "inputs-extra":
        candidate["inputs"]["extra_sha256"] = "0" * 64
    elif tamper == "plan-input-hash":
        candidate["inputs"]["synthesis_plan_sha256"] = "A" * 64
    elif tamper == "extraction-input-hash":
        candidate["inputs"]["extraction_sha256"] = "not a digest"
    elif tamper == "map-input-hash":
        candidate["inputs"]["evidence_map_sha256"] = "0" * 63
    elif tamper == "plan-id":
        candidate["plan_id"] = " p1 "
    elif tamper == "snapshot-id":
        candidate["snapshot_id"] = " snap "
    elif tamper == "reviewer":
        candidate["reviewer"] = " Effect reviewer "
    elif tamper == "derivation-scope":
        candidate["derivation_scope"] = "unregistered derivation"
    elif tamper == "scientific-authority":
        candidate["scientific_evidence_eligible"] = True
    elif tamper == "conclusion-authority":
        candidate["conclusion_authorized"] = True
    elif tamper == "publication-authority":
        candidate["publication_authorized"] = True
    elif tamper == "reviewer-authenticated":
        candidate["reviewer_identity_authenticated"] = True
    elif tamper == "overclaim-limitation":
        candidate["limitations"][0] = "The retained effect values validated the source calculation"
    elif tamper == "claim-count":
        candidate["study_count"] = 99
    elif tamper == "availability-count":
        candidate["available_effect_count"] = 99
    elif tamper == "status-drift":
        candidate["status"] = "effects_ready"
        candidate["available_effect_count"] = 0
    elif tamper == "variance-drift":
        candidate["records"][0]["variance"] = 2.0
    elif tamper == "unavailable-numeric":
        candidate["records"][1]["estimate"] = 0.0
    elif tamper == "overclaim-reason":
        candidate["records"][0]["reason"] = "Validated source table"
    elif tamper == "overclaim-derivation":
        candidate["records"][0]["derivation"] = "Reported estimate confirmed the effect"
    elif tamper == "mapped-claim-digest":
        candidate["records"][0]["mapped_claims"][0]["extraction_claim_sha256"] = "A" * 64
    elif tamper == "padded-mapped-claim":
        candidate["records"][0]["mapped_claims"][0]["citation_checked_location"] = " page fixture "
    elif tamper == "recomputed-without-summaries":
        candidate["derivation_scope"] = "recomputed_from_source_reported_arm_summaries"
    elif tamper == "contrast-missing":
        candidate["contrast_definition"] = "not_applicable"
    with pytest.raises(ValidationError):
        validate_effect_records_boundary(candidate)


@pytest.mark.parametrize("failure", [
    "plan-hash", "plan-authority", "plan-conclusion-authority",
    "plan-publication-authority", "plan-limitations-missing",
    "map-hash", "measure", "missing", "duplicate", "padded-duplicate",
    "extraction-source-duplicate", "nan", "se", "bool-n", "unavailable-value",
    "extraction-authority", "extraction-conclusion-authority",
    "extraction-publication-authority", "extraction-count-drift",
    "extraction-limitations-missing", "extraction-padded-limitation",
    "extraction-claim-payload", "extraction-extra-claim",
    "plan-source-missing", "plan-source-drift", "padded-plan-source",
    "padded-extraction-source", "padded-map-study", "padded-map-source",
    "padded-map-extraction", "padded-map-citation-location", "map-provenance",
    "map-claim-digest", "map-authority", "map-publication-authority",
    "map-claim-count", "map-ceiling-count",
    "map-boundary-limitations",
    "plan-contrast-missing", "plan-contrast-mismatch", "padded-plan-contrast",
    "padded-reviewer", "padded-reason", "padded-location", "padded-derivation",
    "overclaim-reason", "overclaim-derivation",
    "padded-derivation-scope",
])
def test_invalid_effect_records_never_publish(tmp_path, failure):
    plan, plan_sha, extraction, evidence_map, map_sha = artifacts(tmp_path)
    candidate = review()
    kwargs = {}
    if failure == "plan-hash": plan_sha = "0" * 64
    elif failure in {"plan-authority", "plan-conclusion-authority",
                     "plan-publication-authority", "plan-limitations-missing"}:
        value = json.loads(plan.read_text())
        if failure == "plan-authority":
            value["scientific_evidence_eligible"] = True
        elif failure == "plan-conclusion-authority":
            value["conclusion_authorized"] = True
        elif failure == "plan-publication-authority":
            value["publication_authorized"] = True
        else:
            value["limitations"] = []
        plan_sha = write_json(plan, value)
    elif failure == "map-hash": map_sha = "0" * 64
    elif failure == "measure": candidate["records"][0]["effect_measure"] = "odds_ratio"
    elif failure == "missing": candidate["records"].pop()
    elif failure == "duplicate": candidate["records"][1]["study_id"] = "study-1"
    elif failure == "padded-duplicate": candidate["records"][1]["study_id"] = " study-1 "
    elif failure == "extraction-source-duplicate":
        value = json.loads(extraction.read_text())
        value["source_reviews"].append({"source_id": "source-fixture", "records": []})
        write_json(extraction, value)
    elif failure in {
        "extraction-authority",
        "extraction-conclusion-authority",
        "extraction-publication-authority",
        "extraction-count-drift",
        "extraction-limitations-missing",
        "extraction-padded-limitation",
        "extraction-claim-payload",
        "extraction-extra-claim",
    }:
        value = json.loads(extraction.read_text())
        if failure == "extraction-authority":
            value["scientific_evidence_eligible"] = True
        elif failure == "extraction-conclusion-authority":
            value["conclusion_authorized"] = True
        elif failure == "extraction-publication-authority":
            value["publication_authorized"] = True
        elif failure == "extraction-count-drift":
            value["record_count"] = 1
        elif failure == "extraction-limitations-missing":
            value["limitations"] = []
        elif failure == "extraction-padded-limitation":
            value["limitations"][0] = " " + value["limitations"][0]
        elif failure == "extraction-claim-payload":
            value["source_reviews"][0]["records"][0]["notes"] = "changed fixture notes"
        elif failure == "extraction-extra-claim":
            duplicate = dict(value["source_reviews"][0]["records"][0])
            duplicate["extraction_id"] = "claim-3"
            value["source_reviews"][0]["records"].append(duplicate)
            value["record_count"] = 3
        extraction_sha = write_json(extraction, value)
        value = json.loads(evidence_map.read_text())
        value["inputs"]["extraction_sha256"] = extraction_sha
        map_sha = write_json(evidence_map, value)
    elif failure == "nan": candidate["records"][0]["estimate"] = float("nan")
    elif failure == "se": candidate["records"][0]["standard_error"] = 0
    elif failure == "bool-n": candidate["records"][0]["sample_size"] = True
    elif failure == "unavailable-value": candidate["records"][1]["estimate"] = 0.0
    elif failure == "plan-source-missing":
        value = json.loads(plan.read_text())
        del value["included_source_ids_at_freeze"]
        plan_sha = write_json(plan, value)
    elif failure == "plan-source-drift":
        value = json.loads(plan.read_text())
        value["included_source_ids_at_freeze"] = ["other-source"]
        plan_sha = write_json(plan, value)
    elif failure == "padded-plan-source":
        value = json.loads(plan.read_text())
        value["included_source_ids_at_freeze"] = [" source-fixture "]
        plan_sha = write_json(plan, value)
    elif failure == "padded-extraction-source":
        value = json.loads(extraction.read_text())
        value["source_reviews"][0]["source_id"] = " source-fixture "
        extraction_sha = write_json(extraction, value)
        value = json.loads(evidence_map.read_text())
        value["inputs"]["extraction_sha256"] = extraction_sha
        map_sha = write_json(evidence_map, value)
    elif failure in {"padded-map-study", "padded-map-source", "padded-map-extraction", "padded-map-citation-location"}:
        value = json.loads(evidence_map.read_text())
        if failure == "padded-map-study":
            value["claims"][0]["study_id"] = " study-1 "
        elif failure == "padded-map-source":
            value["claims"][0]["source_id"] = " source-fixture "
        elif failure == "padded-map-extraction":
            value["claims"][0]["extraction_id"] = " claim-1 "
        elif failure == "padded-map-citation-location":
            value["claims"][0]["citation_checked_location"] = " page fixture "
        map_sha = write_json(evidence_map, value)
    elif failure == "map-provenance":
        value = json.loads(evidence_map.read_text())
        value["claims"][0]["citation_checked_location"] = ""
        map_sha = write_json(evidence_map, value)
    elif failure == "map-claim-digest":
        value = json.loads(evidence_map.read_text())
        value["claims"][0]["extraction_claim_sha256"] = "A" * 64
        map_sha = write_json(evidence_map, value)
    elif failure == "map-authority":
        value = json.loads(evidence_map.read_text())
        value["scientific_evidence_eligible"] = True
        map_sha = write_json(evidence_map, value)
    elif failure == "map-publication-authority":
        value = json.loads(evidence_map.read_text())
        value["publication_authorized"] = True
        map_sha = write_json(evidence_map, value)
    elif failure == "map-claim-count":
        value = json.loads(evidence_map.read_text())
        value["claim_count"] = 1
        map_sha = write_json(evidence_map, value)
    elif failure == "map-ceiling-count":
        value = json.loads(evidence_map.read_text())
        value["interpretive_ceiling_counts"] = {"qualified_source_claim": 2}
        map_sha = write_json(evidence_map, value)
    elif failure == "map-boundary-limitations":
        value = json.loads(evidence_map.read_text())
        value["limitations"] = []
        map_sha = write_json(evidence_map, value)
    elif failure == "plan-contrast-missing":
        value = json.loads(plan.read_text())
        value["contrast_definition"] = "not_applicable"
        plan_sha = write_json(plan, value)
    elif failure == "plan-contrast-mismatch":
        kwargs = {"contrast_definition": "other contrast"}
    elif failure == "padded-plan-contrast":
        value = json.loads(plan.read_text())
        value["contrast_definition"] = " experimental versus comparator "
        plan_sha = write_json(plan, value)
    elif failure == "padded-reviewer": candidate["reviewer"] = " Effect reviewer "
    elif failure == "padded-reason": candidate["records"][0]["reason"] = " Fixture record "
    elif failure == "padded-location": candidate["records"][0]["evidence_location"] = " table 2 "
    elif failure == "padded-derivation": candidate["records"][0]["derivation"] = " Reported estimate and standard error "
    elif failure == "overclaim-reason": candidate["records"][0]["reason"] = "Validated source table"
    elif failure == "overclaim-derivation": candidate["records"][0]["derivation"] = "Reported estimate confirmed the effect"
    output = tmp_path / "effects"
    with pytest.raises(ValidationError):
        if failure == "padded-derivation-scope":
            kwargs = {"derivation_scope": " reviewer_reported_effect_and_standard_error "}
        create_effect_records(plan, plan_sha, extraction, evidence_map, map_sha, candidate, output, **kwargs)
    assert not output.exists()


@pytest.mark.parametrize(("field", "expected"), [
    ("plan", " A" * 32),
    ("map", "g" * 64),
])
def test_effect_records_reject_malformed_expected_hashes(tmp_path, field, expected):
    plan, plan_sha, extraction, evidence_map, map_sha = artifacts(tmp_path)
    if field == "plan":
        plan_sha = expected
        message = "expected_plan_sha256 must be a lowercase SHA-256 digest"
    else:
        map_sha = expected
        message = "expected_evidence_map_sha256 must be a lowercase SHA-256 digest"
    output = tmp_path / "effects"
    with pytest.raises(ValidationError, match=message):
        create_effect_records(plan, plan_sha, extraction, evidence_map, map_sha, review(), output)
    assert not output.exists()
