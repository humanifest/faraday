from __future__ import annotations

from research_machine.addons.general_science import missingness_report


def test_missingness_report_preserves_observed_patterns() -> None:
    report = missingness_report(
        {"columns": ["outcome", "covariate"]},
        [
            {"outcome": "1", "covariate": "x"},
            {"outcome": "", "covariate": "x"},
            {"outcome": "", "covariate": ""},
        ],
    )
    assert report["complete_case_row_count"] == 1
    assert report["missing_by_column"] == {"outcome": 2, "covariate": 1}
    assert {"missing_columns": ["outcome", "covariate"], "row_count": 1} in report["missingness_patterns"]


def test_missingness_patterns_do_not_collide_with_column_names():
    report = missingness_report({"columns": ["a", "b", "a | b"]}, [
        {"a": "", "b": "", "a | b": "present"},
        {"a": "present", "b": "present", "a | b": ""},
    ])
    assert report["missingness_patterns"] == [
        {"missing_columns": ["a", "b"], "row_count": 1},
        {"missing_columns": ["a | b"], "row_count": 1},
    ]
    assert report["complete_case_fraction"] == 0


def test_missingness_empty_input_has_no_invented_fraction():
    import pytest
    from research_machine.domain.errors import ValidationError
    with pytest.raises(ValidationError, match="at least one observation"):
        missingness_report({"columns": ["a"]}, [])
