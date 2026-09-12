"""Synthetic citation reviews; no fixture claim is scientific evidence."""
import hashlib
import json

import pytest

from research_machine.domain.errors import ValidationError
from research_machine.interfaces.cli import main
from research_machine.literature.verification import (
    create_citation_verification,
    validate_citation_verification_boundary,
)


def extraction_file(tmp_path):
    value = {
        "extraction_version": 1, "status": "extraction_recorded",
        "screening_sha256": "1" * 64,
        "snapshot_id": "snapshot-fixture", "reviewer": "Extractor One",
        "record_count": 2,
        "scientific_evidence_eligible": False,
        "conclusion_authorized": False,
        "publication_authorized": False,
        "limitations": [
            "Records are reviewer assertions bound to source IDs and locations; the machine has not verified that source text supports them.",
            "Extraction does not perform risk-of-bias assessment, resolve disagreements, accept claims as facts, or conduct synthesis.",
        ],
        "source_reviews": [{"source_id": "source-1", "status": "extracted", "reason": "fixture",
            "records": [
                {"extraction_id": "claim-1", "study_id": "study-1", "claim_text": "Synthetic claim one",
                 "evidence_location": "page 1", "epistemic_layer": "inferred", "result_direction": "supports",
                 "uncertainty": "fixture", "notes": "fixture"},
                {"extraction_id": "claim-2", "study_id": "study-1", "claim_text": "Synthetic claim two",
                 "evidence_location": "page 2", "epistemic_layer": "observed", "result_direction": "null",
                 "uncertainty": "fixture", "notes": "fixture"},
            ]}],
    }
    path = tmp_path / "extraction.json"
    encoded = (json.dumps(value, sort_keys=True, indent=2) + "\n").encode()
    path.write_bytes(encoded)
    return path, hashlib.sha256(encoded).hexdigest()


def anchored_extraction_file(tmp_path):
    path, _ = extraction_file(tmp_path)
    value = json.loads(path.read_text())
    value["source_reviews"][0]["source_retained_file_sha256"] = "b" * 64
    encoded = (json.dumps(value, sort_keys=True, indent=2) + "\n").encode()
    path.write_bytes(encoded)
    return path, hashlib.sha256(encoded).hexdigest()


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


def passage_file(tmp_path, extraction, extraction_sha):
    value = json.loads(extraction.read_text())
    claims = []
    for index, record in enumerate(value["source_reviews"][0]["records"], start=1):
        quote = f"Synthetic retained passage {index}"
        quote_bytes = quote.encode("utf-8")
        source_sha = value["source_reviews"][0]["source_retained_file_sha256"]
        claims.append({
            "extraction_id": record["extraction_id"],
            "source_id": "source-1",
            "source_retained_file_sha256": source_sha,
            "study_id": record["study_id"],
            "claim_text": record["claim_text"],
            "extracted_evidence_location": record["evidence_location"],
            "extraction_claim_sha256": claim_digest("source-1", record, source_sha),
            "evidence_quote": quote,
            "evidence_quote_sha256": hashlib.sha256(quote_bytes).hexdigest(),
            "quote_utf8_byte_count": len(quote_bytes),
            "quote_occurrence_count": 1,
            "machine_verification": "exact_utf8_quote_found_in_retained_source_bytes",
        })
    passage = {
        "passage_verification_version": 1,
        "extraction_sha256": extraction_sha,
        "snapshot_id": value["snapshot_id"],
        "extraction_reviewer": value["reviewer"],
        "passage_reviewer": "Passage reviewer",
        "claims": claims,
        "claim_count": len(claims),
        "status": "passage_verification_recorded",
        "scientific_evidence_eligible": False,
        "conclusion_authorized": False,
        "publication_authorized": False,
        "reviewer_identity_authenticated": False,
        "limitations": [
            "Exact quote matching proves only that supplied UTF-8 quote bytes occur in the retained source bytes; it does not interpret the passage or prove the extracted claim.",
            "Reviewer identity, source semantics, risk of bias, and applicability remain unauthenticated and require later review gates.",
            "Passage verification is not scientific evidence, conclusion authorization, or publication authorization.",
        ],
    }
    path = tmp_path / "passage-verification.json"
    encoded = (json.dumps(passage, sort_keys=True, indent=2) + "\n").encode()
    path.write_bytes(encoded)
    return path, hashlib.sha256(encoded).hexdigest()


def review(verdict="supported"):
    return {"reviewer": "Verifier Two", "assessments": [
        {"extraction_id": "claim-1", "verdict": verdict, "checked_location": "page 1", "rationale": "Text checked"},
        {"extraction_id": "claim-2", "verdict": "partially_supported", "checked_location": "page 2", "rationale": "Qualified wording"},
    ]}


def test_citation_verification_cli_is_exhaustive_independent_and_write_once(tmp_path, capsys):
    extraction, digest = extraction_file(tmp_path)
    review_path = tmp_path / "review.json"
    review_path.write_text(json.dumps(review()))
    output = tmp_path / "verification"
    assert main(["--json", "literature", "verify-citations", "--extraction-file", str(extraction),
        "--expected-extraction-sha256", digest, "--review-file", str(review_path), "--output", str(output)]) == 0
    result = json.loads(capsys.readouterr().out)["result"]
    assert result["status"] == "citation_review_recorded"
    assert result["independent_review"] is True
    assert result["scientific_evidence_eligible"] is False
    assert result["conclusion_authorized"] is False
    assert result["publication_authorized"] is False
    assert result["reviewer_identity_authenticated"] is False
    with pytest.raises(ValidationError, match="already exists"):
        create_citation_verification(extraction, digest, review(), output)


def test_unsupported_claim_is_preserved_and_requires_review(tmp_path):
    extraction, digest = extraction_file(tmp_path)
    result = create_citation_verification(extraction, digest, review("unsupported"), tmp_path / "verification")
    assert result["status"] == "review_required"
    assert result["verdict_counts"]["unsupported"] == 1
    assert any(item["verdict"] == "unsupported" for item in result["assessments"])


def test_citation_verification_preserves_canonical_extraction_handles(tmp_path):
    extraction, digest = extraction_file(tmp_path)
    extraction_record = json.loads(extraction.read_text())["source_reviews"][0]["records"][0]
    result = create_citation_verification(
        extraction, digest, review(), tmp_path / "verification"
    )
    assert result["assessments"][0]["extraction_id"] == "claim-1"
    assert result["assessments"][0]["checked_location"] == "page 1"
    assert result["assessments"][0]["extraction_claim_sha256"] == claim_digest(
        "source-1", extraction_record
    )


@pytest.mark.parametrize(
    ("payload", "message"),
    [
        ('{"extraction_version": 1, "extraction_version": 1}\n', "duplicate JSON object key"),
        ('{"extraction_version": NaN}\n', "non-finite JSON number"),
    ],
)
def test_citation_verification_rejects_ambiguous_extraction_json_bytes(tmp_path, payload, message):
    extraction, _digest = extraction_file(tmp_path)
    extraction.write_text(payload, encoding="utf-8")
    tampered_digest = hashlib.sha256(extraction.read_bytes()).hexdigest()
    output = tmp_path / "verification"

    with pytest.raises(ValidationError, match=message):
        create_citation_verification(extraction, tampered_digest, review(), output)
    assert not output.exists()


def test_citation_verification_binds_retained_source_bytes_when_available(tmp_path):
    extraction, digest = extraction_file(tmp_path)
    retained_source_sha = "b" * 64
    value = json.loads(extraction.read_text())
    value["source_reviews"][0]["source_retained_file_sha256"] = retained_source_sha
    encoded = (json.dumps(value, sort_keys=True, indent=2) + "\n").encode()
    extraction.write_bytes(encoded)
    digest = hashlib.sha256(encoded).hexdigest()

    result = create_citation_verification(
        extraction, digest, review(), tmp_path / "verification"
    )
    extraction_record = value["source_reviews"][0]["records"][0]
    assert result["assessments"][0]["source_retained_file_sha256"] == retained_source_sha
    assert result["assessments"][0]["extraction_claim_sha256"] == claim_digest(
        "source-1", extraction_record, retained_source_sha
    )


@pytest.mark.parametrize(
    ("payload", "message"),
    [
        ('{"passage_verification_version": 1, "passage_verification_version": 1}\n', "duplicate JSON object key"),
        ('{"passage_verification_version": NaN}\n', "non-finite JSON number"),
    ],
)
def test_citation_verification_rejects_ambiguous_passage_json_bytes(tmp_path, payload, message):
    extraction, digest = anchored_extraction_file(tmp_path)
    passage, _passage_digest = passage_file(tmp_path, extraction, digest)
    passage.write_text(payload, encoding="utf-8")
    tampered_passage_digest = hashlib.sha256(passage.read_bytes()).hexdigest()
    output = tmp_path / "verification"

    with pytest.raises(ValidationError, match=message):
        create_citation_verification(
            extraction,
            digest,
            review(),
            output,
            passage_verification_path=passage,
            expected_passage_verification_sha256=tampered_passage_digest,
        )
    assert not output.exists()


def test_citation_verification_replays_passage_verification_receipts(tmp_path, capsys):
    extraction, digest = anchored_extraction_file(tmp_path)
    passage, passage_digest = passage_file(tmp_path, extraction, digest)
    review_path = tmp_path / "review.json"
    review_path.write_text(json.dumps(review()))
    output = tmp_path / "verification"

    assert main(["--json", "literature", "verify-citations",
        "--extraction-file", str(extraction), "--expected-extraction-sha256", digest,
        "--passage-verification-file", str(passage),
        "--expected-passage-verification-sha256", passage_digest,
        "--review-file", str(review_path), "--output", str(output)]) == 0

    result = json.loads(capsys.readouterr().out)["result"]
    retained = result["assessments"][0]["passage_verification"]
    assert retained["passage_verification_sha256"] == passage_digest
    assert retained["machine_verification"] == "exact_utf8_quote_found_in_retained_source_bytes"
    assert "evidence_quote" not in retained
    validate_citation_verification_boundary(
        result,
        result["assessments"],
        require_assessment_contract=True,
    )


@pytest.mark.parametrize("failure", [
    "missing-expected",
    "bad-passage-hash",
    "wrong-extraction",
    "missing-claim",
    "claim-drift",
])
def test_citation_verification_rejects_invalid_passage_verification(tmp_path, failure):
    extraction, digest = anchored_extraction_file(tmp_path)
    passage, passage_digest = passage_file(tmp_path, extraction, digest)
    if failure == "missing-expected":
        with pytest.raises(ValidationError, match="supplied together"):
            create_citation_verification(
                extraction, digest, review(), tmp_path / "verification",
                passage_verification_path=passage,
            )
        return
    if failure == "bad-passage-hash":
        passage_digest = "0" * 64
    elif failure in {"wrong-extraction", "missing-claim", "claim-drift"}:
        value = json.loads(passage.read_text())
        if failure == "wrong-extraction":
            value["extraction_sha256"] = "0" * 64
        elif failure == "missing-claim":
            value["claims"].pop()
            value["claim_count"] = 1
        elif failure == "claim-drift":
            value["claims"][0]["claim_text"] = "Synthetic claim changed"
        encoded = (json.dumps(value, sort_keys=True, indent=2) + "\n").encode()
        passage.write_bytes(encoded)
        passage_digest = hashlib.sha256(encoded).hexdigest()

    with pytest.raises(ValidationError):
        create_citation_verification(
            extraction, digest, review(), tmp_path / "verification",
            passage_verification_path=passage,
            expected_passage_verification_sha256=passage_digest,
        )
    assert not (tmp_path / "verification").exists()


def test_citation_verification_boundary_replays_artifact_envelope(tmp_path):
    extraction, digest = extraction_file(tmp_path)
    result = create_citation_verification(
        extraction, digest, review(), tmp_path / "verification"
    )
    validate_citation_verification_boundary(result, result["assessments"])

    for mutate, message in [
        (lambda candidate: candidate.update({"citation_verification_version": 2}), "version is invalid"),
        (lambda candidate: candidate.update({"extraction_sha256": "A" * 64}), "lowercase SHA-256"),
        (lambda candidate: candidate.update({"snapshot_id": " snapshot-fixture "}), "canonical"),
        (lambda candidate: candidate.update({"extraction_reviewer": " Extractor One "}), "canonical"),
        (lambda candidate: candidate.update({"citation_reviewer": "Extractor One"}), "reviewers must be independent"),
        (lambda candidate: candidate.update({"independent_review": False}), "independent-review"),
        (lambda candidate: candidate.update({"reviewer_identity_authenticated": True}), "authenticate reviewer identity"),
        (lambda candidate: candidate.update({"status": "review_required"}), "status does not replay"),
        (lambda candidate: candidate.__setitem__("assessments", []), "assessments must be retained"),
    ]:
        candidate = json.loads(json.dumps(result))
        mutate(candidate)
        with pytest.raises(ValidationError, match=message):
            validate_citation_verification_boundary(candidate, candidate["assessments"])


def test_citation_verification_boundary_rejects_retained_overclaiming_rationale(tmp_path):
    extraction, digest = extraction_file(tmp_path)
    result = create_citation_verification(
        extraction, digest, review(), tmp_path / "verification"
    )
    result["assessments"][0]["rationale"] = "Validated source support"

    with pytest.raises(ValidationError, match="prohibited overclaiming language"):
        validate_citation_verification_boundary(
            result,
            result["assessments"],
            require_assessment_contract=True,
        )


def test_citation_verification_boundary_rejects_retained_overclaiming_limitation(tmp_path):
    extraction, digest = extraction_file(tmp_path)
    result = create_citation_verification(
        extraction, digest, review(), tmp_path / "verification"
    )
    result["limitations"][0] = "Citation verification confirmed source support"

    with pytest.raises(ValidationError, match="prohibited overclaiming language"):
        validate_citation_verification_boundary(result, result["assessments"])


@pytest.mark.parametrize("failure", [
    "hash",
    "same-reviewer",
    "padded-reviewer",
    "missing",
    "duplicate",
    "padded_duplicate",
    "padded_extraction_duplicate",
    "padded-extractor",
    "padded-source",
    "padded-study",
    "padded-claim-text",
    "padded-evidence-location",
    "extraction-authority",
    "extraction-conclusion-authority",
    "extraction-publication-authority",
    "extraction-count-drift",
    "extraction-limitations-missing",
    "extraction-padded-limitation",
    "extraction-source-status-drift",
    "extraction-source-padded-reason",
    "extraction-source-overclaim-reason",
    "extraction-source-duplicate-empty",
    "extraction-source-retained-hash",
    "extraction-overclaim-uncertainty",
    "extraction-overclaim-notes",
    "unknown",
    "location",
    "padded-location",
    "padded-rationale",
    "overclaim-rationale",
    "verdict",
    "missing-claim-field",
])
def test_invalid_citation_review_never_publishes(tmp_path, failure):
    extraction, digest = extraction_file(tmp_path)
    candidate = review()
    if failure == "hash": digest = "0" * 64
    elif failure == "same-reviewer": candidate["reviewer"] = "Extractor One"
    elif failure == "padded-reviewer": candidate["reviewer"] = " Verifier Two "
    elif failure == "missing": candidate["assessments"].pop()
    elif failure == "duplicate": candidate["assessments"][1]["extraction_id"] = "claim-1"
    elif failure == "padded_duplicate": candidate["assessments"][1]["extraction_id"] = " claim-1 "
    elif failure in {
        "padded_extraction_duplicate",
        "padded-extractor",
        "padded-source",
        "padded-study",
        "padded-claim-text",
        "padded-evidence-location",
        "extraction-authority",
        "extraction-conclusion-authority",
        "extraction-publication-authority",
        "extraction-count-drift",
        "extraction-limitations-missing",
        "extraction-padded-limitation",
        "extraction-source-status-drift",
        "extraction-source-padded-reason",
        "extraction-source-overclaim-reason",
        "extraction-source-duplicate-empty",
        "extraction-source-retained-hash",
        "extraction-overclaim-uncertainty",
        "extraction-overclaim-notes",
        "missing-claim-field",
    }:
        value = json.loads(extraction.read_text())
        if failure == "padded_extraction_duplicate":
            duplicate = dict(value["source_reviews"][0]["records"][0])
            duplicate["extraction_id"] = " claim-1 "
            value["source_reviews"][0]["records"].append(duplicate)
        elif failure == "padded-extractor":
            value["reviewer"] = " Extractor One "
        elif failure == "padded-source":
            value["source_reviews"][0]["source_id"] = " source-1 "
        elif failure == "padded-study":
            value["source_reviews"][0]["records"][0]["study_id"] = " study-1 "
        elif failure == "padded-claim-text":
            value["source_reviews"][0]["records"][0]["claim_text"] = " Synthetic claim one "
        elif failure == "padded-evidence-location":
            value["source_reviews"][0]["records"][0]["evidence_location"] = " page 1 "
        elif failure == "missing-claim-field":
            del value["source_reviews"][0]["records"][0]["notes"]
        elif failure == "extraction-authority":
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
        elif failure == "extraction-source-status-drift":
            value["source_reviews"][0]["status"] = "no_extractable_claim"
        elif failure == "extraction-source-padded-reason":
            value["source_reviews"][0]["reason"] = " fixture "
        elif failure == "extraction-source-overclaim-reason":
            value["source_reviews"][0]["reason"] = "Confirmed source relevance"
        elif failure == "extraction-source-duplicate-empty":
            value["source_reviews"].append({
                "source_id": "source-1",
                "status": "no_extractable_claim",
                "reason": "duplicate empty source review",
                "records": [],
            })
        elif failure == "extraction-source-retained-hash":
            value["source_reviews"][0]["source_retained_file_sha256"] = "A" * 64
        elif failure == "extraction-overclaim-uncertainty":
            value["source_reviews"][0]["records"][0]["uncertainty"] = "Validated estimate"
        elif failure == "extraction-overclaim-notes":
            value["source_reviews"][0]["records"][0]["notes"] = "Explained the finding"
        encoded = (json.dumps(value, sort_keys=True, indent=2) + "\n").encode()
        extraction.write_bytes(encoded)
        digest = hashlib.sha256(encoded).hexdigest()
    elif failure == "unknown": candidate["assessments"][0]["extraction_id"] = "claim-x"
    elif failure == "location": candidate["assessments"][0]["checked_location"] = ""
    elif failure == "padded-location": candidate["assessments"][0]["checked_location"] = " page 1 "
    elif failure == "padded-rationale": candidate["assessments"][0]["rationale"] = " Text checked "
    elif failure == "overclaim-rationale": candidate["assessments"][0]["rationale"] = "Confirmed source support"
    elif failure == "verdict": candidate["assessments"][0]["verdict"] = "true"
    output = tmp_path / "verification"
    with pytest.raises(ValidationError):
        create_citation_verification(extraction, digest, candidate, output)
    assert not output.exists()


@pytest.mark.parametrize("expected", [" 0123", "A" * 64, "g" * 64, "0" * 63, "0" * 65])
def test_citation_verification_rejects_malformed_expected_extraction_hash(tmp_path, expected):
    extraction, _ = extraction_file(tmp_path)
    output = tmp_path / "verification"
    with pytest.raises(ValidationError, match="expected_extraction_sha256 must be a lowercase SHA-256 digest"):
        create_citation_verification(extraction, expected, review(), output)
    assert not output.exists()
