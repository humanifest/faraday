"""Synthetic passage checks; exact quote matching is not source interpretation."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from research_machine.domain.errors import ValidationError
from research_machine.interfaces.cli import main
from research_machine.literature.extraction import create_extraction
from research_machine.literature.passages import (
    create_passage_verification,
    validate_passage_verification_boundary,
)
from research_machine.literature.screening import create_screening
from research_machine.literature.snapshot import create_snapshot


def prepared_extraction(tmp_path: Path) -> tuple[Path, str, Path]:
    source = tmp_path / "source.txt"
    source.write_text(
        "Synthetic background.\n"
        "The source reports a synthetic difference in the retained table.\n"
        "More synthetic text.",
        encoding="utf-8",
    )
    snapshot = create_snapshot(
        {
            "snapshot_id": "passage-fixture",
            "query": "fixture",
            "inclusion_criteria": ["Eligible"],
            "exclusion_criteria": ["Ineligible"],
            "sources": [
                {
                    "source_id": "s1",
                    "title": "Source",
                    "locator": "fixture:s1",
                    "source_class": "primary",
                    "file": str(source),
                }
            ],
        },
        tmp_path / "snapshot",
    )
    screening = create_screening(
        tmp_path / "snapshot/literature-snapshot.json",
        snapshot["snapshot_sha256"],
        {
            "reviewer": "Screening reviewer",
            "decisions": [
                {
                    "source_id": "s1",
                    "decision": "include",
                    "reason": "Eligible",
                    "criterion_refs": ["inclusion:1"],
                }
            ],
        },
        tmp_path / "screening",
    )
    extraction = create_extraction(
        tmp_path / "screening/screening.json",
        screening["screening_sha256"],
        {
            "reviewer": "Extraction reviewer",
            "source_reviews": [
                {
                    "source_id": "s1",
                    "status": "extracted",
                    "reason": "One relevant claim",
                    "records": [
                        {
                            "extraction_id": "claim-1",
                            "study_id": "study-1",
                            "claim_text": "The source reports a synthetic difference.",
                            "evidence_location": "retained table",
                            "epistemic_layer": "inferred",
                            "result_direction": "supports",
                            "uncertainty": "Synthetic fixture uncertainty",
                            "notes": "Needs independent interpretation",
                        }
                    ],
                }
            ],
        },
        tmp_path / "extraction",
    )
    return (
        tmp_path / "extraction/extraction.json",
        extraction["extraction_sha256"],
        tmp_path / "snapshot/sources",
    )


def passage_review(quote: str | None = None) -> dict[str, object]:
    return {
        "reviewer": "Passage reviewer",
        "passages": [
            {
                "extraction_id": "claim-1",
                "evidence_quote": quote
                or "The source reports a synthetic difference in the retained table.",
            }
        ],
    }


def test_passage_verification_cli_checks_exact_retained_source_quote(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    extraction, digest, source_root = prepared_extraction(tmp_path)
    review_path = tmp_path / "passage-review.json"
    review_path.write_text(json.dumps(passage_review()), encoding="utf-8")
    output = tmp_path / "passages"

    assert main(
        [
            "--json",
            "literature",
            "verify-passages",
            "--extraction-file",
            str(extraction),
            "--expected-extraction-sha256",
            digest,
            "--retained-source-root",
            str(source_root),
            "--review-file",
            str(review_path),
            "--output",
            str(output),
        ]
    ) == 0

    result = json.loads(capsys.readouterr().out)["result"]
    claim = result["claims"][0]
    assert result["scientific_evidence_eligible"] is False
    assert result["conclusion_authorized"] is False
    assert result["publication_authorized"] is False
    assert result["reviewer_identity_authenticated"] is False
    assert claim["machine_verification"] == "exact_utf8_quote_found_in_retained_source_bytes"
    assert claim["quote_occurrence_count"] == 1
    assert claim["evidence_quote_sha256"] == hashlib.sha256(
        claim["evidence_quote"].encode("utf-8")
    ).hexdigest()
    with pytest.raises(ValidationError, match="already exists"):
        create_passage_verification(
            extraction,
            digest,
            source_root,
            passage_review(),
            output,
        )


@pytest.mark.parametrize(
    ("payload", "message"),
    [
        ('{"extraction_version": 1, "extraction_version": 1}\n', "duplicate JSON object key"),
        ('{"extraction_version": NaN}\n', "non-finite JSON number"),
    ],
)
def test_passage_verification_rejects_ambiguous_extraction_json_bytes(
    tmp_path: Path, payload: str, message: str
) -> None:
    extraction, _digest, source_root = prepared_extraction(tmp_path)
    extraction.write_text(payload, encoding="utf-8")
    tampered_digest = hashlib.sha256(extraction.read_bytes()).hexdigest()
    output = tmp_path / "passages"

    with pytest.raises(ValidationError, match=message):
        create_passage_verification(
            extraction,
            tampered_digest,
            source_root,
            passage_review(),
            output,
        )
    assert not output.exists()


@pytest.mark.parametrize(
    "failure",
    [
        "missing-source",
        "changed-source",
        "invented-quote",
        "missing-claim",
        "legacy-anchor",
        "overclaim-limitation",
        "quote-hash-drift",
    ],
)
def test_invalid_passage_verification_never_publishes(tmp_path: Path, failure: str) -> None:
    extraction, digest, source_root = prepared_extraction(tmp_path)
    review = passage_review()
    if failure == "missing-source":
        for path in source_root.iterdir():
            path.unlink()
    elif failure == "changed-source":
        for path in source_root.iterdir():
            path.write_text("changed retained source bytes", encoding="utf-8")
    elif failure == "invented-quote":
        review = passage_review("This sentence is not in the retained file.")
    elif failure == "missing-claim":
        review["passages"] = []
    elif failure == "legacy-anchor":
        value = json.loads(extraction.read_text(encoding="utf-8"))
        value["source_reviews"][0]["source_retained_file_sha256"] = "legacy_missing"
        extraction.write_text(
            json.dumps(value, sort_keys=True, indent=2) + "\n",
            encoding="utf-8",
        )
        digest = hashlib.sha256(extraction.read_bytes()).hexdigest()
    output = tmp_path / "passages"

    if failure in {"overclaim-limitation", "quote-hash-drift"}:
        result = create_passage_verification(
            extraction,
            digest,
            source_root,
            review,
            output,
        )
        candidate = json.loads(json.dumps(result))
        if failure == "overclaim-limitation":
            candidate["limitations"][0] = "Passage verification confirmed source support"
        else:
            candidate["claims"][0]["evidence_quote_sha256"] = "0" * 64
        with pytest.raises(ValidationError):
            validate_passage_verification_boundary(candidate, candidate["claims"])
        return

    with pytest.raises(ValidationError):
        create_passage_verification(
            extraction,
            digest,
            source_root,
            review,
            output,
        )
    assert not output.exists()


@pytest.mark.parametrize(
    ("target", "value", "message"),
    [
        ("reviewer", " Passage reviewer", "passage reviewer must be canonical"),
        ("extraction_id", " claim-1", "passage verification extraction_id must be canonical"),
        ("evidence_quote", " The source reports", "passage verification evidence_quote must be canonical"),
    ],
)
def test_passage_review_text_must_be_canonical(
    tmp_path: Path, target: str, value: str, message: str
) -> None:
    extraction, digest, source_root = prepared_extraction(tmp_path)
    review = passage_review()
    if target == "reviewer":
        review["reviewer"] = value
    else:
        review["passages"][0][target] = value  # type: ignore[index]
    output = tmp_path / "passages"
    with pytest.raises(ValidationError, match=message):
        create_passage_verification(
            extraction,
            digest,
            source_root,
            review,
            output,
        )
    assert not output.exists()
