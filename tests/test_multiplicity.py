"""Synthetic arithmetic fixtures, not validation of an inferential family."""
import pytest

from research_machine.addons.general_science import holm_adjustment
from research_machine.domain.errors import ValidationError


SPEC = {"hypothesis_column": "hypothesis", "p_value_column": "p",
        "family_name": "three prespecified outcomes",
        "family_hypothesis_ids": ["h1", "h2", "h3"], "alpha": 0.05}


def test_holm_adjustment_is_monotone_and_input_order_invariant():
    rows = [{"hypothesis": "h1", "p": "0.01"}, {"hypothesis": "h2", "p": "0.04"},
            {"hypothesis": "h3", "p": "0.03"}]
    result = holm_adjustment(SPEC, rows)
    assert {item["hypothesis_id"]: item["holm_adjusted_p_value"] for item in result["results"]} == {
        "h1": pytest.approx(0.03), "h2": pytest.approx(0.06), "h3": pytest.approx(0.06)}
    assert result["rejected_hypothesis_ids"] == ["h1"]
    assert result["family_hypothesis_ids"] == ["h1", "h2", "h3"]
    reversed_result = holm_adjustment(SPEC, list(reversed(rows)))
    assert {item["hypothesis_id"]: item["holm_adjusted_p_value"] for item in reversed_result["results"]} == {
        item["hypothesis_id"]: item["holm_adjusted_p_value"] for item in result["results"]}


@pytest.mark.parametrize("rows", [
    [{"hypothesis": "h1", "p": ""}], [{"hypothesis": "", "p": "0.1"}],
    [{"hypothesis": "h1", "p": "-0.1"}], [{"hypothesis": "h1", "p": "1.1"}],
    [{"hypothesis": "h1", "p": "nan"}],
    [{"hypothesis": "h1", "p": "0.1"}, {"hypothesis": " h1 ", "p": "0.2"}],
])
def test_holm_adjustment_rejects_incomplete_or_invalid_family(rows):
    with pytest.raises(ValidationError):
        holm_adjustment(SPEC, rows)


@pytest.mark.parametrize("rows", [
    [],
    [{"hypothesis": "h1", "p": "0.01"}, {"hypothesis": "h2", "p": "0.02"}],
    [{"hypothesis": "h1", "p": "0.01"}, {"hypothesis": "h2", "p": "0.02"},
     {"hypothesis": "h3", "p": "0.03"}, {"hypothesis": "h4", "p": "0.04"}],
    [{"hypothesis": "h1", "p": "0.01"}, {"hypothesis": "h2", "p": "0.02"},
     {"hypothesis": "other", "p": "0.03"}],
])
def test_holm_adjustment_rejects_selective_or_substituted_family(rows):
    with pytest.raises(ValidationError, match="exactly match the prespecified family"):
        holm_adjustment(SPEC, rows)


@pytest.mark.parametrize("family", [[], ["h1", "h1"], [" h1"], [""], "h1"])
def test_holm_adjustment_rejects_invalid_prespecified_family(family):
    with pytest.raises(ValidationError, match="family_hypothesis_ids"):
        holm_adjustment({**SPEC, "family_hypothesis_ids": family}, [
            {"hypothesis": "h1", "p": "0.01"}
        ])
