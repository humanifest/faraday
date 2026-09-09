import json

from research_machine.interfaces.cli import main
from research_machine.design.interview import interview_design
import pytest


@pytest.mark.parametrize("complete", [True, False])
def test_interview_emits_reviewable_control_definitions(complete):
    answers = iter(["Fixture", "Question", "Decision", "Height", "pot", "exploratory", "no"]
        + [""] * 24 + ["Blank sample", ""]
        + (["negative", "Detect background signal", "No signal"] if complete else ["", "", ""])
        + [""] * 35)
    result = interview_design(lambda prompt: next(answers))
    draft = result["scaffold"]["artifacts"]["protocol-draft.json"]
    definition = draft["control_definitions"][0]
    assert definition["registered_control"] == "Blank sample"
    assert definition["evaluation_gate_id"] in draft["quality_requirements"]
    codes = {item["code"] for item in result["scaffold"]["findings"]}
    assert ("CONTROL_DEFINITION_INCOMPLETE" in codes) is (not complete)
    assert "observed_behavior" not in definition


def test_interview_cli_creates_review_only_experiment_without_json(tmp_path, monkeypatch, capsys):
    answers = iter(
        ["Fixture", "Question", "Decision", "Height", "pot-day", "exploratory", "no"]
        + [""] * 14
        + [
            "Target 40 independent pots per group for a two-millimeter interval half-width under the stated variance assumption.",
            *([""] * 11),
            "Higher mean height after 7 days",
            "No difference between conditions",
            "A zero or negative mean difference",
            "Assessor masked until analysis lock; collection unmasked with standardized procedures.",
            "leaf count; biomass",
            "Primary height only; Holm-adjust the two secondary outcomes.",
            "interval",
            "mean_difference",
            "Mean height difference between assigned conditions",
            "blue light minus white light",
            "blue light; white light",
            "light_condition",
            "two_sided",
            "0",
            "interval_excludes_null",
            "0.95",
            "height_mm",
            "Mean marked-stem height in millimetres",
            "all eligible final-day pots",
            "ruler_resolution=1 mm; replicate_readings=2",
            "day 7 after assignment",
            "positive values mean taller under blue light",
            "mean of two blinded readings per pot",
            "readings must agree within 2 mm",
            "retain all valid measurements regardless of direction",
            "post_exposure",
            *( [""] * 27 ),
        ]
    )
    monkeypatch.setattr("builtins.input", lambda: next(answers))
    output = tmp_path / "experiment"
    assert main(["--json", "design", "interview", "--output", str(output)]) == 0
    result = json.loads(capsys.readouterr().out)["result"]
    assert result["experiment"]["hypothesis_state"] == "unreviewed"
    assert result["brief"]["human_participants"] is False
    assert result["brief"]["blinding_plan"].startswith("Assessor masked")
    assert result["brief"]["sample_size_justification"].startswith("Target 40 independent pots")
    assert result["brief"]["secondary_outcomes"] == ["leaf count", "biomass"]
    assert result["brief"]["confirmatory_outcomes"] == []
    assert result["brief"]["exploratory_outcomes"] == ["Height", "leaf count", "biomass"]
    assert result["brief"]["multiplicity_method"] == "exploratory_only"
    assert result["brief"]["multiplicity_alpha"] is None
    assert result["brief"]["multiple_testing_policy"].startswith("Primary height only")
    assert result["brief"]["primary_estimand"].startswith("Mean height difference")
    assert result["brief"]["contrast_definition"] == "blue light minus white light"
    assert result["brief"]["contrast_groups"] == ["blue light", "white light"]
    assert result["brief"]["group_data_column"] == "light_condition"
    assert result["brief"]["expected_effect_direction"] == "two_sided"
    assert result["brief"]["null_value"] == 0.0
    assert result["brief"]["support_rule"] == "interval_excludes_null"
    assert result["brief"]["confidence_level"] == 0.95
    assert result["brief"]["outcome_data_column"] == "height_mm"
    assert result["brief"]["measurement_observable"] == "Mean marked-stem height in millimetres"
    assert result["brief"]["measurement_parameter_values"] == {
        "ruler_resolution": "1 mm", "replicate_readings": "2",
    }
    measurement = result["scaffold"]["artifacts"]["measurement-definition-draft.json"]
    assert measurement["data_column"] == "height_mm"
    assert measurement["observable"] == "Mean marked-stem height in millimetres"
    assert measurement["input_condition"] == "all eligible final-day pots"
    assert measurement["aggregation"].startswith("mean of two")
    assert measurement["temporal_role"] == "post_exposure"
    analysis = result["scaffold"]["artifacts"]["analysis-commitment-draft.json"]
    assert analysis["group_column"] == "light_condition"
    assert "SAMPLE_SIZE_JUSTIFICATION_MISSING" not in {item["code"] for item in result["scaffold"]["findings"]}
    assert "BLINDING_UNRESOLVED" not in {item["code"] for item in result["scaffold"]["findings"]}
    stored = json.loads((output / "drafts" / "protocol-draft.json").read_text())
    assert stored["blinding_plan"] == result["brief"]["blinding_plan"]
    assert "independent_unit" not in result["brief"]
    assert result["scaffold"]["status"] == "blocked"
    assert (output / "drafts" / "protocol-draft.json").exists()
    proposal = result["scaffold"]["artifacts"]["hypothesis-proposal.json"]
    assert proposal["observable_prediction"] == "Higher mean height after 7 days"
    assert proposal["falsification_conditions"] == ["A zero or negative mean difference"]


def test_interview_cancellation_creates_nothing(tmp_path, monkeypatch, capsys):
    def cancel():
        raise EOFError
    monkeypatch.setattr("builtins.input", cancel)
    output = tmp_path / "experiment"
    assert main(["--json", "design", "interview", "--output", str(output)]) == 2
    assert "cancelled" in capsys.readouterr().err
    assert not output.exists()


def test_interview_collects_exact_independent_unit_column() -> None:
    def ask(prompt: str) -> str:
        responses = {
            "What is the study's working title?": "Unit identity fixture",
            "What question do you want to investigate?": "Question",
            "What practical decision would the findings inform?": "Decision",
            "What exactly will you measure as the primary outcome?": "Score",
            "What does one data row represent, such as one pot-day?": "participant-visit",
            "What kind of claim are you investigating?": "exploratory",
            "Does this involve people or data about people?": "no",
            "What is sampled independently, such as a participant, pot, or site?": "participant",
            "What exact dataset column will identify the same independent unit across every row?": "participant_key",
        }
        return next((value for key, value in responses.items() if prompt.startswith(key)), "")

    result = interview_design(ask)
    assert result["brief"]["unit_id_column"] == "participant_key"
    assert result["scaffold"]["artifacts"]["protocol-draft.json"]["unit_id_column"] == "participant_key"
    columns = result["scaffold"]["artifacts"]["data-dictionary-draft.json"]["proposed_columns"]
    assert any(
        item["name"] == "participant_key" and item["role"] == "independent_unit_identity"
        for item in columns
    )


def test_interview_collects_prospective_measurement_validity_check() -> None:
    def ask(prompt: str) -> str:
        responses = {
            "What is the study's working title?": "Validity interview",
            "What question do you want to investigate?": "Question",
            "What practical decision would the findings inform?": "Decision",
            "What exactly will you measure as the primary outcome?": "Height",
            "What does one data row represent, such as one pot-day?": "pot",
            "What kind of claim are you investigating?": "exploratory",
            "Does this involve people or data about people?": "no",
            "Name prospective primary-measurement validity checks": "reference-agreement",
            "What evidence type will validity check 'reference-agreement' use?": "criterion",
            "What exact aspect of validity does check 'reference-agreement' address?": "Agreement with a traceable reference ruler",
            "How will validity check 'reference-agreement' be assessed before interpreting the primary result?": "Blindly remeasure the registered subset",
            "What prospective result will count as acceptable for validity check 'reference-agreement'?": "At least 95% agree within 2 mm",
            "What will happen if validity check 'reference-agreement' fails or is inconclusive?": "Stop primary interpretation",
            "What dedicated required gate ID will record validity check 'reference-agreement'?": "reference-agreement-assessed",
        }
        return next((value for key, value in responses.items() if prompt.startswith(key)), "")

    result = interview_design(ask)
    check = result["brief"]["measurement_validity_checks"][0]
    assert check["check_id"] == "reference-agreement"
    assert check["acceptance_criterion"] == "At least 95% agree within 2 mm"
    protocol = result["scaffold"]["artifacts"]["protocol-draft.json"]
    assert "reference-agreement-assessed" in protocol["quality_requirements"]
    assert "MEASUREMENT_VALIDITY_PLAN_INCOMPLETE" not in {
        item["code"] for item in result["scaffold"]["findings"]
    }


def test_interview_preserves_noncanonical_free_text_for_scaffold_audit() -> None:
    def ask(prompt: str) -> str:
        responses = {
            "What is the study's working title?": " Padded interview ",
            "What question do you want to investigate?": "Question",
            "What practical decision would the findings inform?": "Decision",
            "What exactly will you measure as the primary outcome?": "Score",
            "What does one data row represent, such as one pot-day?": "unit",
            "What kind of claim are you investigating?": "correlational",
            "Does this involve people or data about people?": "no",
            "What effect, uncertainty calculation, exclusions, and multiplicity policy will you commit to?": " Estimate the registered contrast ",
            "What exact observable or recorded quantity defines the primary outcome?": " Mean score ",
        }
        return next((value for key, value in responses.items() if prompt.startswith(key)), "")

    result = interview_design(ask)

    assert result["brief"]["title"] == " Padded interview "
    assert result["brief"]["analysis_commitment"] == " Estimate the registered contrast "
    assert result["brief"]["measurement_observable"] == " Mean score "
    codes = {item["code"] for item in result["scaffold"]["findings"]}
    assert {
        "CORE_BRIEF_FIELD_NONCANONICAL",
        "PROSPECTIVE_COMMITMENT_NONCANONICAL",
        "MEASUREMENT_CONTRACT_NONCANONICAL",
    } <= codes
    assert result["scaffold"]["status"] == "blocked"


def test_interview_preserves_noncanonical_measurement_parameter_bindings() -> None:
    def ask(prompt: str) -> str:
        responses = {
            "What is the study's working title?": "Parameter interview",
            "What question do you want to investigate?": "Question",
            "What practical decision would the findings inform?": "Decision",
            "What exactly will you measure as the primary outcome?": "Score",
            "What does one data row represent, such as one pot-day?": "unit",
            "What kind of claim are you investigating?": "correlational",
            "Does this involve people or data about people?": "no",
            "List fixed measurement parameters as name=value pairs separated by semicolons": " window = 10 minutes ",
        }
        return next((value for key, value in responses.items() if prompt.startswith(key)), "")

    result = interview_design(ask)

    assert result["brief"]["measurement_parameter_values"] == {" window ": " 10 minutes "}
    assert "MEASUREMENT_CONTRACT_NONCANONICAL" in {
        item["code"] for item in result["scaffold"]["findings"]
    }


def test_interview_preserves_noncanonical_list_commitments_for_scaffold_audit() -> None:
    def ask(prompt: str) -> str:
        responses = {
            "What is the study's working title?": "List interview",
            "What question do you want to investigate?": "Question",
            "What practical decision would the findings inform?": "Decision",
            "What exactly will you measure as the primary outcome?": "Score",
            "What does one data row represent, such as one pot-day?": "unit",
            "What kind of claim are you investigating?": "correlational",
            "Does this involve people or data about people?": "no",
            "Which factors will be deliberately changed?": " person ",
            "Name planned controls, separated by semicolons": " Blank sample ",
            "Name alternative explanations or confounders, separated by semicolons": " Selection ",
            "What observations would weaken your hypothesis?": " Null result ",
            "Which higher-level conclusions must remain unsupported?": " No causal conclusion ",
            "What secondary outcomes will be analyzed?": " Response time ",
            "Which secondary outcomes are confirmatory?": "",
            "What family-wise alpha will govern the confirmatory family?": "0.05",
            "What is the confirmatory testing family and adjustment or hierarchical rule? How will secondary outcomes be interpreted?": " Primary only ",
            "List the two ordered contrast levels as first; second": " treated; control ",
        }
        return next((value for key, value in responses.items() if prompt.startswith(key)), "")

    result = interview_design(ask)

    assert result["brief"]["manipulated_factors"] == [" person "]
    assert result["brief"]["controls"] == [" Blank sample "]
    assert result["brief"]["confounds"] == [" Selection "]
    assert result["brief"]["falsification_conditions"] == [" Null result "]
    assert result["brief"]["higher_level_conclusions_unsupported"] == [
        " No causal conclusion "
    ]
    assert result["brief"]["secondary_outcomes"] == [" Response time "]
    assert result["brief"]["contrast_groups"] == [" treated", "control "]
    codes = {item["code"] for item in result["scaffold"]["findings"]}
    assert {
        "MANIPULATED_FACTOR_NONCANONICAL",
        "CONTROL_LABEL_NONCANONICAL",
        "CONFOUND_LABEL_NONCANONICAL",
        "FALSIFICATION_CONDITION_NONCANONICAL",
        "UNSUPPORTED_CONCLUSION_NONCANONICAL",
        "SECONDARY_OUTCOME_LABEL_NONCANONICAL",
        "CONTRAST_GROUP_LABEL_NONCANONICAL",
    } <= codes
    assert result["scaffold"]["status"] == "blocked"


def test_interview_collects_numeric_information_thresholds() -> None:
    def ask(prompt: str) -> str:
        responses = {
            "What is the study's working title?": "Threshold fixture",
            "What question do you want to investigate?": "Question",
            "What practical decision would the findings inform?": "Decision",
            "What exactly will you measure as the primary outcome?": "Score",
            "What does one data row represent, such as one pot-day?": "pot",
            "What kind of claim are you investigating?": "exploratory",
            "Does this involve people or data about people?": "no",
            "What is the minimum analyzable count required in the smaller comparison arm, or the minimum complete-pair count?": "20",
            "What maximum fraction of submitted records may be excluded before the analysis must stop for review? Enter a number from 0 up to but not including 1.": "0.1",
            "What maximum absolute difference between comparison-group exclusion fractions is tolerable before analysis must stop for review? Enter a number from 0 through 1.": "0.05",
            "What exact assumption would make the registered complete-case analysis scientifically interpretable?": "Unavailable outcomes do not materially distort the registered contrast.",
            "How will missingness and exclusions be assessed before interpreting the primary result?": "Inspect total, group-specific, and reason-specific missingness patterns.",
            "What kind of missingness assessment will be used?": "empirical_diagnostic",
            "What will happen if the missingness assumption is contradicted or remains inconclusive?": "Stop primary interpretation and report the result as inconclusive.",
            "What dedicated required gate ID will record the missingness assessment?": "missingness-assessed",
        }
        return next((value for key, value in responses.items() if prompt.startswith(key)), "")

    result = interview_design(ask)
    assert result["brief"]["minimum_analyzable_units"] == 20
    assert result["brief"]["maximum_excluded_fraction"] == 0.1
    assert result["brief"]["maximum_group_excluded_fraction_difference"] == 0.05
    dictionary = result["scaffold"]["artifacts"]["data-dictionary-draft.json"]
    assert dictionary["minimum_analyzable_units"] == 20
    assert dictionary["maximum_excluded_fraction"] == 0.1
    assert dictionary["maximum_group_excluded_fraction_difference"] == 0.05
    assert dictionary["missingness_assessment"]["missingness_assessment_kind"] == "empirical_diagnostic"
    protocol = result["scaffold"]["artifacts"]["protocol-draft.json"]
    assert "missingness-assessed" in protocol["quality_requirements"]
    assert "MISSINGNESS_ASSESSMENT_INCOMPLETE" not in {
        item["code"] for item in result["scaffold"]["findings"]
    }


def test_interview_collects_factor_interpretability_plan() -> None:
    def ask(prompt: str) -> str:
        responses = {
            "What is the study's working title?": "Factor interview",
            "What question do you want to investigate?": "Question",
            "What practical decision would the findings inform?": "Decision",
            "What exactly will you measure as the primary outcome?": "Score",
            "What does one data row represent, such as one pot-day?": "unit",
            "What kind of claim are you investigating?": "exploratory",
            "Does this involve people or data about people?": "no",
            "Which factors will be deliberately changed?": "person; room",
            "Is this a factorial or crossover design that can separate the changed factors?": "yes",
            "How will the design estimate or separate the effect of each changed factor?": (
                "Cross each person condition with each room before interpreting either factor."
            ),
        }
        return next((value for key, value in responses.items() if prompt.startswith(key)), "")

    result = interview_design(ask)
    assert result["brief"]["manipulated_factors"] == ["person", "room"]
    assert result["brief"]["factorial_or_crossover_design"] is True
    assert result["brief"]["factor_interpretability_plan"].startswith("Cross each")
    protocol = result["scaffold"]["artifacts"]["protocol-draft.json"]
    assert protocol["manipulated_factors"] == ["person", "room"]
    assert "MULTI_FACTOR_INTERVENTION_UNINTERPRETABLE" not in {
        item["code"] for item in result["scaffold"]["findings"]
    }


def test_interview_collects_scale_and_analysis_family_without_an_llm() -> None:
    def ask(prompt: str) -> str:
        responses = {
            "What is the study's working title?": "Scale interview",
            "What question do you want to investigate?": "Question",
            "What practical decision would the findings inform?": "Decision",
            "What exactly will you measure as the primary outcome?": "Response",
            "What does one data row represent, such as one pot-day?": "unit",
            "What kind of claim are you investigating?": "descriptive",
            "Does this involve people or data about people?": "no",
            "What is the primary outcome's data scale?": "binary",
            "List every permitted outcome category, separated by semicolons": "absent; present",
            "Which structured primary analysis family fits the design and outcome scale?": "descriptive",
        }
        return next((value for key, value in responses.items() if prompt.startswith(key)), "")

    result = interview_design(ask)
    assert result["brief"]["outcome_scale"] == "binary"
    assert result["brief"]["outcome_admissible_values"] == ["absent", "present"]
    measurement = result["scaffold"]["artifacts"]["measurement-definition-draft.json"]
    assert measurement["scale_type"] == "binary"
    assert measurement["analysis_family"] == "descriptive"


def test_interview_collects_complete_secondary_measurement_contract() -> None:
    def ask(prompt: str) -> str:
        responses = {
            "What is the study's working title?": "Secondary interview",
            "What question do you want to investigate?": "Question",
            "What practical decision would the findings inform?": "Decision",
            "What exactly will you measure as the primary outcome?": "Primary score",
            "What does one data row represent, such as one pot-day?": "unit",
            "What kind of claim are you investigating?": "exploratory",
            "Does this involve people or data about people?": "no",
            "What secondary outcomes will be analyzed?": "Errors",
            "What is the confirmatory testing family": "All outcomes are exploratory.",
            "What exact observable defines secondary outcome 'Errors'?": "Number of registered errors",
            "Under what input condition is secondary outcome 'Errors' measured?": "All eligible trials",
            "List fixed parameters for secondary outcome 'Errors'": "window=10 minutes",
            "Where or when is secondary outcome 'Errors' evaluated?": "End of task",
            "What coding or sign convention defines secondary outcome 'Errors'?": "Higher means more errors",
            "How is secondary outcome 'Errors' aggregated per independent unit?": "Sum per unit",
            "What measurement tolerance applies to secondary outcome 'Errors'?": "Exact integer count",
            "What behavior is prospectively expected for secondary outcome 'Errors'?": "Report all valid counts",
            "What exact data column will contain secondary outcome 'Errors'?": "error_count",
            "What is the temporal role of secondary outcome 'Errors'?": "not_applicable",
            "What is the scale type of secondary outcome 'Errors'?": "count",
            "What physical or semantic unit does secondary outcome 'Errors' use?": "count",
            "List missing-value codes for secondary outcome 'Errors'": "<blank>",
        }
        return next((value for key, value in responses.items() if prompt.startswith(key)), "")

    result = interview_design(ask)
    assert len(result["brief"]["secondary_measurements"]) == 1
    measurement = result["scaffold"]["artifacts"][
        "secondary-measurement-definitions-draft.json"
    ]["measurements"][0]
    assert measurement["registered_target"] == "Errors"
    assert measurement["data_column"] == "error_count"
    assert measurement["parameter_values"] == {"window": "10 minutes"}
    assert "SECONDARY_MEASUREMENT_COVERAGE_INVALID" not in {
        item["code"] for item in result["scaffold"]["findings"]
    }


def test_interview_collects_artifact_evaluated_control_measurement() -> None:
    def ask(prompt: str) -> str:
        responses = {
            "What is the study's working title?": "Control interview",
            "What question do you want to investigate?": "Question",
            "What practical decision would the findings inform?": "Decision",
            "What exactly will you measure as the primary outcome?": "Signal",
            "What does one data row represent, such as one pot-day?": "capture",
            "What kind of claim are you investigating?": "exploratory",
            "Does this involve people or data about people?": "no",
            "Name planned controls, separated by semicolons": "Blank capture",
            "Which family describes control 'Blank capture'?": "negative",
            "What misleading explanation does control 'Blank capture' test?": "Background contamination",
            "What behavior do you expect from control 'Blank capture'?": "No detected signal",
            "What exact observable defines control 'Blank capture'?": "Blank-spectrum diagnostic",
            "Under what input condition is control 'Blank capture' evaluated?": "Registered blank input",
            "List fixed parameters for control 'Blank capture'": "threshold=0.01 units",
            "Where or when is control 'Blank capture' evaluated?": "Before sample batch",
            "What coding, sign, or ordering convention defines control 'Blank capture'?": "Positive means detected signal",
            "How are readings for control 'Blank capture' aggregated?": "Maximum blank response",
            "What fixed acceptance tolerance applies to control 'Blank capture'?": "At most 0.01 units",
            "What prospective behavior is expected for control 'Blank capture'?": "Remain at or below tolerance",
            "What data column contains control 'Blank capture'?": "",
            "What is the temporal role of control 'Blank capture'?": "pre_exposure",
        }
        return next((value for key, value in responses.items() if prompt.startswith(key)), "")

    result = interview_design(ask)
    measurement = result["brief"]["control_measurements"][0]
    assert measurement["data_column"] == ""
    assert measurement["parameter_values"] == {"threshold": "0.01 units"}
    draft = result["scaffold"]["artifacts"][
        "control-measurement-definitions-draft.json"
    ]["measurements"][0]
    assert draft["registered_target"] == "Blank capture"
    assert "CONTROL_MEASUREMENT_COVERAGE_INVALID" not in {
        item["code"] for item in result["scaffold"]["findings"]
    }


def test_provider_free_interview_collects_auditable_causal_design() -> None:
    def ask(prompt: str) -> str:
        fixed = {
            "What is the study's working title?": "Causal interview fixture",
            "What question do you want to investigate?": "Does treatment change outcome?",
            "What practical decision would the findings inform?": "Choose treatment",
            "What exactly will you measure as the primary outcome?": "outcome",
            "What does one data row represent, such as one pot-day?": "unit",
            "What kind of claim are you investigating?": "causal",
            "Does this involve people or data about people?": "no",
            "What exact population may the final conclusion cover?": "Eligible study units.",
            "What exact setting may the final conclusion cover?": "Registered fixture setting.",
            "What unit will the primary effect estimate use?": "outcome units",
            "What effect scale will define practical importance, such as a mean difference?": "mean difference",
            "What exact endpoint or time window may the final conclusion cover?": "Seven days after assignment.",
            "What is the smallest primary effect that would be scientifically or practically important?": "1.0",
            "If the full support rule is not met, should the result be classified as inconclusive or weakening?": "inconclusive",
            "Which higher-level conclusions must remain unsupported?": "No mechanism; No out-of-scope generalization",
            "Name planned controls, separated by semicolons": "",
            "Name alternative explanations or confounders, separated by semicolons": "baseline",
            "Would you like to enter the causal graph and assumption register now?": "yes",
            "How is the exposure assigned for this causal model?": "observational",
            "What stable variable name identifies the exposure?": "treatment",
            "What stable variable name identifies the causal outcome?": "outcome",
            "List every variable in the causal graph, separated by semicolons": "treatment; outcome; baseline",
            "Will causal variable 'treatment' be observed in this study?": "yes",
            "Will causal variable 'outcome' be observed in this study?": "yes",
            "Will causal variable 'baseline' be observed in this study?": "yes",
            "List directed causal edges as cause -> effect, separated by semicolons": "baseline -> treatment; baseline -> outcome; treatment -> outcome",
            "Which observed pre-exposure variables will be adjusted for?": "baseline",
            "State the causal estimand in one exact sentence": "Mean outcome under treatment minus control at day 7.",
            "Which target population does this causal estimand describe?": "Eligible study units.",
            "Define the first exposure or treatment strategy precisely": "Assign treatment.",
            "Define the comparison exposure or treatment strategy precisely": "Assign control.",
            "When is time zero, after eligibility and before follow-up?": "At assignment.",
            "At what exact follow-up time is the outcome evaluated?": "Seven days after assignment.",
            "What causal contrast compares the two strategies?": "Treatment minus control.",
            "What population summary measure defines the effect?": "Population mean difference.",
            "How will intercurrent events, treatment changes, and unavailable outcomes affect the estimand?": "Retain assigned units and disclose unavailable outcomes.",
            "Define the signed contrast order, such as treatment minus control.": "treatment minus control",
            "List the two ordered contrast levels as first; second": "treated; control",
            "What exact dataset column will contain those comparison or exposure levels?": "treatment",
        }
        for question, response in fixed.items():
            if prompt.startswith(question):
                return response
        if prompt.startswith("State the study-specific"):
            return "This study requires the stated assumption to hold."
        if prompt.startswith("How will '"):
            return "Inspect design records and diagnostics before interpretation."
        if prompt.startswith("What kind of assessment will be used"):
            return "design_record_review"
        if prompt.startswith("What will happen if '"):
            return "Do not make the causal interpretation."
        if prompt.startswith("What exact observable defines causal"):
            return "Value recorded under the registered causal measurement procedure."
        if prompt.startswith("Under what exact input condition is causal"):
            return "All eligible independent units."
        if prompt.startswith("List fixed parameters for causal"):
            return "instrument=registered fixture"
        if prompt.startswith("Where or when is causal"):
            return "At the registered causal time point."
        if prompt.startswith("What coding or sign convention defines causal"):
            return "Use the preregistered coding dictionary."
        if prompt.startswith("How is causal"):
            return "One value per independent unit."
        if prompt.startswith("What measurement tolerance applies to causal"):
            return "Exact registered parsing."
        if prompt.startswith("What behavior is prospectively expected for causal"):
            return "Retain valid values regardless of outcome direction."
        if prompt.startswith("What is the temporal role of causal exposure"):
            return "at_exposure"
        if prompt.startswith("What is the temporal role of causal covariate"):
            return "pre_exposure"
        if prompt.startswith("What is the scale type of causal exposure"):
            return "nominal"
        if prompt.startswith("What is the scale type of causal covariate"):
            return "interval"
        if prompt.startswith("What physical or semantic unit does causal exposure"):
            return "exposure level"
        if prompt.startswith("What physical or semantic unit does causal covariate"):
            return "baseline points"
        if prompt.startswith("List every admissible value for causal exposure"):
            return "treated; control"
        if prompt.startswith("List missing-value codes for causal"):
            return "<blank>"
        return ""

    result = interview_design(ask)
    identification = result["brief"]["causal_identification"]
    assert identification["proposed_adjustment_set"] == ["baseline"]
    assert len(identification["assumptions"]) == 7
    assert {item["assessment_kind"] for item in identification["assumptions"]} == {
        "design_record_review"
    }
    assert identification["causal_estimand"]["outcome_variable"] == "outcome"
    assert "REVIEW REQUIRED" in identification["causal_estimand"]["target_hypothesis_id"]
    audit = result["scaffold"]["artifacts"]["causal-identification-audit.json"]
    assert audit["backdoor_criterion_satisfied"] is True
    assert audit["missing_assumption_categories"] == []
    requirements = result["scaffold"]["artifacts"][
        "data-dictionary-draft.json"
    ]["causal_variable_measurement_requirements"]
    assert [(item["variable"], item["role"]) for item in requirements] == [
        ("treatment", "exposure"),
        ("outcome", "primary"),
        ("baseline", "covariate"),
    ]
    assert all("data_column" in item["required_definition_fields"] for item in requirements)
    assert all("temporal_role" in item["required_definition_fields"] for item in requirements)
    causal_measurements = result["brief"]["causal_measurements"]
    assert [(item["role"], item["variable"]) for item in causal_measurements] == [
        ("exposure", "treatment"), ("covariate", "baseline"),
    ]
    assert causal_measurements[0]["data_column"] == "treatment"
    assert causal_measurements[0]["admissible_values"] == ["treated", "control"]
    assert causal_measurements[1]["temporal_role"] == "pre_exposure"
    assert "CAUSAL_MEASUREMENT_COVERAGE_INVALID" not in {
        item["code"] for item in result["scaffold"]["findings"]
    }
    assert "CAUSAL_GRAPH_UNRESOLVED" not in {
        item["code"] for item in result["scaffold"]["findings"]
    }


def test_human_interview_retains_hold_and_retries_invalid_choice():
    answers = iter(["Fixture", "Question", "Decision", "Score", "participant-day",
                    "invalid choice", "causal", "yes"] + [""] * 35 + ["no"] + [""] * 33)
    result = interview_design(lambda prompt: next(answers))
    assert result["brief"]["study_type"] == "causal"
    assert "BLINDING_UNRESOLVED" in {item["code"] for item in result["scaffold"]["findings"]}
    assert result["brief"]["independent_review"] is False
    assert "HUMAN_REVIEW_REQUIRED" in {item["code"] for item in result["scaffold"]["findings"]}
    assert result["scaffold"]["status"] == "blocked"
    assert "FALSIFIER_UNRESOLVED" in {item["code"] for item in result["scaffold"]["findings"]}
    assert "SAMPLE_SIZE_JUSTIFICATION_MISSING" in {item["code"] for item in result["scaffold"]["findings"]}
