import pytest

from research_machine.domain.errors import ValidationError
from research_machine.literature.bias import _bounded_bias_text
from research_machine.literature.deviations import _bounded_deviation_text
from research_machine.literature.effect_verification import _bounded_verification_text
from research_machine.literature.effects import _bounded_effect_text
from research_machine.literature.evidence_map import (
    _bounded_citation_text as evidence_map_citation_text,
)
from research_machine.literature.evidence_map import _bounded_evidence_map_text
from research_machine.literature.extraction import _bounded_extraction_text
from research_machine.literature.meta_analysis import _bounded_meta_text
from research_machine.literature.passages import _bounded_passage_text
from research_machine.literature.screening import _bounded_screening_text
from research_machine.literature.studies import _bounded_study_text
from research_machine.literature.synthesis import _bounded_synthesis_text
from research_machine.literature.synthesis_plan import _bounded_plan_text
from research_machine.literature.verification import _bounded_citation_text


LEGAL_INTENT_OVERCLAIM = "The retained source establishes legal responsibility."
BOUNDED_SOURCE_STATEMENT = "The retained source is reviewed only within this bounded record."


@pytest.mark.parametrize(
    "validator",
    [
        _bounded_bias_text,
        _bounded_deviation_text,
        _bounded_effect_text,
        _bounded_evidence_map_text,
        _bounded_extraction_text,
        _bounded_meta_text,
        _bounded_passage_text,
        _bounded_plan_text,
        _bounded_screening_text,
        _bounded_study_text,
        _bounded_synthesis_text,
        _bounded_verification_text,
        _bounded_citation_text,
        evidence_map_citation_text,
    ],
)
def test_literature_bounded_prose_rejects_legal_intent_overclaims(validator):
    with pytest.raises(ValidationError, match="prohibited overclaiming language"):
        validator(LEGAL_INTENT_OVERCLAIM, "retained prose")


@pytest.mark.parametrize(
    "validator",
    [
        _bounded_bias_text,
        _bounded_deviation_text,
        _bounded_effect_text,
        _bounded_evidence_map_text,
        _bounded_extraction_text,
        _bounded_meta_text,
        _bounded_passage_text,
        _bounded_plan_text,
        _bounded_screening_text,
        _bounded_study_text,
        _bounded_synthesis_text,
        _bounded_verification_text,
        _bounded_citation_text,
        evidence_map_citation_text,
    ],
)
def test_literature_bounded_prose_allows_bounded_source_language(validator):
    assert validator(BOUNDED_SOURCE_STATEMENT, "retained prose") == BOUNDED_SOURCE_STATEMENT
