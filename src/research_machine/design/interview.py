"""Provider-free interview logic shared by terminal and future form clients."""
from collections.abc import Callable
from typing import Any

from research_machine.design.causal import (
    ASSIGNMENT_CAUSAL_ASSUMPTIONS,
    CAUSAL_ASSESSMENT_KINDS,
    COMMON_CAUSAL_ASSUMPTIONS,
)
from research_machine.design.scaffold import scaffold_design
from research_machine.domain.models import CONTROL_FAMILIES, MEASUREMENT_TEMPORAL_ROLES


def _split_semicolon_answer(raw: str) -> list[str]:
    parts = raw.split(";")
    last = len(parts) - 1
    values: list[str] = []
    for index, part in enumerate(parts):
        value = part
        if index > 0:
            value = value.lstrip()
        if index < last:
            value = value.rstrip()
        if value.strip():
            values.append(value)
    return values


def interview_design(ask: Callable[[str], str]) -> dict[str, Any]:
    brief: dict[str, Any] = {}

    def answer(key: str, prompt: str, *, required: bool = False, choices: tuple[str, ...] = ()) -> None:
        while True:
            hint = f" ({', '.join(choices)})" if choices else ""
            raw_value = ask(prompt + hint + (" [required]" if required else " [blank = unresolved]"))
            choice_value = raw_value.strip()
            if not choice_value and not required:
                return
            if not choices and choice_value:
                brief[key] = raw_value
                return
            if choice_value and choice_value in choices:
                brief[key] = choice_value
                return

    def answer_number(key: str, prompt: str, *, integer: bool = False) -> None:
        while True:
            value = ask(prompt + " [blank = unresolved]").strip()
            if not value:
                return
            try:
                parsed = int(value) if integer else float(value)
            except ValueError:
                continue
            if (integer and parsed >= 2) or (not integer and 0 <= parsed < 1):
                brief[key] = parsed
                return

    def answer_finite(key: str, prompt: str) -> None:
        while True:
            value = ask(prompt + " [blank = unresolved]").strip()
            if not value:
                return
            try:
                parsed = float(value)
            except ValueError:
                continue
            if parsed == parsed and abs(parsed) != float("inf"):
                brief[key] = parsed
                return

    def answer_confidence(key: str, prompt: str) -> None:
        while True:
            value = ask(prompt + " [blank = unresolved]").strip()
            if not value:
                return
            try:
                parsed = float(value)
            except ValueError:
                continue
            if 0.8 <= parsed < 1:
                brief[key] = parsed
                return

    for key, prompt in (
        ("title", "What is the study's working title?"),
        ("question", "What question do you want to investigate?"),
        ("decision", "What practical decision would the findings inform?"),
        ("outcome", "What exactly will you measure as the primary outcome?"),
        ("unit_of_observation", "What does one data row represent, such as one pot-day?"),
    ):
        answer(key, prompt, required=True)
    answer("study_type", "What kind of claim are you investigating?", required=True,
           choices=("causal", "correlational", "exploratory", "descriptive"))
    answer("human_participants", "Does this involve people or data about people?", required=True, choices=("yes", "no"))
    brief["human_participants"] = brief["human_participants"] == "yes"
    for key, prompt in (
        ("population", "Which population could these findings describe?"),
        ("setting", "Where and over what time window will the study occur?"),
        ("outcome_unit", "What units or measurement scale will the outcome use?"),
        ("independent_unit", "What is sampled independently, such as a participant, pot, or site?"),
    ):
        answer(key, prompt)
    if brief.get("independent_unit"):
        answer(
            "unit_id_column",
            "What exact dataset column will identify the same independent unit across every row?",
        )
    answer("repeated_measures", "Will the same independent unit contribute multiple observations?", choices=("yes", "no"))
    if "repeated_measures" in brief:
        brief["repeated_measures"] = brief["repeated_measures"] == "yes"
    answer("analysis_design", "How will the analysis account for dependence between observations?",
           choices=("independent_groups", "paired", "clustered", "repeated_measures", "descriptive"))
    if brief.get("repeated_measures") or brief.get("analysis_design") in {"paired", "clustered", "repeated_measures"}:
        answer("unit_analysis_plan", "How will rows map to one independent unit's estimand? Define pairing, within-unit aggregation, clusters, and time structure.")
    for key, prompt in (
        ("intervention", "What will be changed, if anything?"),
        ("comparison", "What comparison could distinguish competing explanations?"),
        ("sampling_plan", "How will units be selected, including who or what may be excluded?"),
        ("randomization_plan", "How will assignment be randomized, or why is randomization inapplicable?"),
        ("measurement_validity", "How will you check that the measurement represents the intended construct?"),
        ("calibration_plan", "What calibration or quality failure would invalidate a measurement?"),
        ("analysis_commitment", "What effect, uncertainty calculation, exclusions, and multiplicity policy will you commit to?"),
        ("stopping_rule", "When will collection stop, regardless of whether the result is favorable?"),
        ("sample_size_justification", "Why is that amount of information useful? State the precision or power target and assumptions, or explain the feasibility limit and resulting inferential limits. Count independent units, not rows."),
    ):
        answer(key, prompt)
    raw_factors = ask(
        "Which factors will be deliberately changed? Separate exact factor names with semicolons [blank = none declared]"
    )
    brief["manipulated_factors"] = _split_semicolon_answer(raw_factors)
    if brief["manipulated_factors"]:
        answer(
            "factorial_or_crossover_design",
            "Is this a factorial or crossover design that can separate the changed factors?",
            choices=("yes", "no"),
        )
        if "factorial_or_crossover_design" in brief:
            brief["factorial_or_crossover_design"] = (
                brief["factorial_or_crossover_design"] == "yes"
            )
        answer(
            "factor_interpretability_plan",
            "How will the design estimate or separate the effect of each changed factor?",
        )
    answer_number("minimum_analyzable_units", "What is the minimum analyzable count required in the smaller comparison arm, or the minimum complete-pair count?", integer=True)
    answer_number("maximum_excluded_fraction", "What maximum fraction of submitted records may be excluded before the analysis must stop for review? Enter a number from 0 up to but not including 1.")
    answer_number(
        "maximum_group_excluded_fraction_difference",
        "What maximum absolute difference between comparison-group exclusion fractions is tolerable before analysis must stop for review? Enter a number from 0 through 1.",
    )
    answer(
        "missingness_assumption",
        "What exact assumption would make the registered complete-case analysis scientifically interpretable?",
    )
    answer(
        "missingness_assessment_plan",
        "How will missingness and exclusions be assessed before interpreting the primary result?",
    )
    answer(
        "missingness_assessment_kind",
        "What kind of missingness assessment will be used?",
        choices=("empirical_diagnostic", "design_record_review", "external_validation", "substantive_judgment"),
    )
    answer(
        "missingness_failure_response",
        "What will happen if the missingness assumption is contradicted or remains inconclusive?",
    )
    answer(
        "missingness_assessment_gate_id",
        "What dedicated required gate ID will record the missingness assessment?",
    )
    for key, prompt in (("controls", "Name planned controls, separated by semicolons"),
                        ("confounds", "Name alternative explanations or confounders, separated by semicolons")):
        value = ask(prompt + " [blank = unresolved]")
        brief[key] = _split_semicolon_answer(value)
    if brief["study_type"] == "causal":
        answer(
            "_enter_causal_structure",
            "Would you like to enter the causal graph and assumption register now?",
            choices=("yes", "no"),
        )
        if brief.pop("_enter_causal_structure", "no") == "yes":
            answer(
                "_causal_assignment",
                "How is the exposure assigned for this causal model?",
                required=True,
                choices=("observational", "randomized"),
            )
            answer("_causal_exposure", "What stable variable name identifies the exposure?", required=True)
            answer("_causal_outcome", "What stable variable name identifies the causal outcome?", required=True)
            while True:
                raw_nodes = ask(
                    "List every variable in the causal graph, separated by semicolons [required]"
                )
                node_ids = _split_semicolon_answer(raw_nodes)
                if (
                    len(node_ids) >= 2
                    and len(set(node_ids)) == len(node_ids)
                    and brief["_causal_exposure"] in node_ids
                    and brief["_causal_outcome"] in node_ids
                ):
                    break
            nodes = []
            for node_id in node_ids:
                answer(
                    "_causal_observed",
                    f"Will causal variable '{node_id}' be observed in this study?",
                    required=True,
                    choices=("yes", "no"),
                )
                nodes.append({
                    "id": node_id,
                    "observed": brief.pop("_causal_observed") == "yes",
                })
            while True:
                raw_edges = ask(
                    "List directed causal edges as cause -> effect, separated by semicolons [blank = none]"
                ).strip()
                edges = []
                valid = True
                for raw_edge in _split_semicolon_answer(raw_edges):
                    parts = [item.strip() for item in raw_edge.split("->")]
                    if len(parts) != 2 or parts[0] not in node_ids or parts[1] not in node_ids or parts[0] == parts[1]:
                        valid = False
                        break
                    edges.append({"cause": parts[0], "effect": parts[1]})
                edge_pairs = {(item["cause"], item["effect"]) for item in edges}
                if valid and len(edge_pairs) == len(edges):
                    break
            while True:
                raw_adjustment = ask(
                    "Which observed pre-exposure variables will be adjusted for? Separate names with semicolons [blank = none]"
                )
                adjustment = _split_semicolon_answer(raw_adjustment)
                if len(set(adjustment)) == len(adjustment) and all(item in node_ids for item in adjustment):
                    break
            assignment = brief.pop("_causal_assignment")
            brief["assignment_type"] = assignment
            for key, prompt in (
                ("_estimand_description", "State the causal estimand in one exact sentence"),
                ("_estimand_population", "Which target population does this causal estimand describe?"),
                ("_estimand_strategy_a", "Define the first exposure or treatment strategy precisely"),
                ("_estimand_strategy_b", "Define the comparison exposure or treatment strategy precisely"),
                ("_estimand_time_zero", "When is time zero, after eligibility and before follow-up?"),
                ("_estimand_outcome_time", "At what exact follow-up time is the outcome evaluated?"),
                ("_estimand_contrast", "What causal contrast compares the two strategies?"),
                ("_estimand_summary", "What population summary measure defines the effect?"),
                ("_estimand_intercurrent", "How will intercurrent events, treatment changes, and unavailable outcomes affect the estimand?"),
            ):
                answer(key, prompt, required=True)
            causal_estimand = {
                "target_hypothesis_id": "[REVIEW REQUIRED] bind the canonical reviewed hypothesis ID",
                "description": brief.pop("_estimand_description"),
                "population": brief.pop("_estimand_population"),
                "exposure_strategies": [
                    brief.pop("_estimand_strategy_a"),
                    brief.pop("_estimand_strategy_b"),
                ],
                "outcome_variable": brief["_causal_outcome"],
                "time_zero": brief.pop("_estimand_time_zero"),
                "outcome_time": brief.pop("_estimand_outcome_time"),
                "contrast": brief.pop("_estimand_contrast"),
                "summary_measure": brief.pop("_estimand_summary"),
                "intercurrent_events_policy": brief.pop("_estimand_intercurrent"),
            }
            categories = sorted(
                COMMON_CAUSAL_ASSUMPTIONS | ASSIGNMENT_CAUSAL_ASSUMPTIONS[assignment]
            )
            assumptions = []
            for category in categories:
                answer(
                    "_assumption_statement",
                    f"State the study-specific '{category}' assumption",
                    required=True,
                )
                answer(
                    "_assumption_assessment",
                    f"How will '{category}' be assessed or challenged?",
                    required=True,
                )
                answer(
                    "_assumption_assessment_kind",
                    f"What kind of assessment will be used for '{category}'?",
                    required=True,
                    choices=tuple(sorted(CAUSAL_ASSESSMENT_KINDS)),
                )
                answer(
                    "_assumption_failure",
                    f"What will happen if '{category}' is not defensible?",
                    required=True,
                )
                assumptions.append({
                    "category": category,
                    "statement": brief.pop("_assumption_statement"),
                    "assessment_kind": brief.pop("_assumption_assessment_kind"),
                    "assessment_plan": brief.pop("_assumption_assessment"),
                    "failure_response": brief.pop("_assumption_failure"),
                    "assessment_gate_id": f"causal-{category}-assessed",
                })
            brief["causal_identification"] = {
                "nodes": nodes,
                "edges": edges,
                "exposure": brief.pop("_causal_exposure"),
                "outcome": brief.pop("_causal_outcome"),
                "proposed_adjustment_set": adjustment,
                "assignment_type": assignment,
                "assumptions": assumptions,
                "causal_estimand": causal_estimand,
            }
    definitions = []
    for index, control in enumerate(brief["controls"], start=1):
        answer("_family", f"Which family describes control '{control}'?", choices=CONTROL_FAMILIES)
        answer("_purpose", f"What misleading explanation does control '{control}' test?")
        answer("_expected", f"What behavior do you expect from control '{control}'?")
        definitions.append({"control_id": f"control-{index}", "registered_control": control,
            "family": brief.pop("_family", ""), "purpose": brief.pop("_purpose", ""),
            "expected_behavior": brief.pop("_expected", ""), "evaluation_gate_id": f"control-{index}-evaluated"})
    if definitions:
        brief["control_definitions"] = definitions
    if brief["human_participants"]:
        for key, prompt in (
            ("consent_plan", "How will informed consent be obtained?"),
            ("withdrawal_plan", "How can participants withdraw without penalty?"),
            ("privacy_plan", "How will identifying data and access be protected?"),
            ("retention_deletion_plan", "When and how will data be retained or deleted?"),
            ("risk_description", "What physical or psychological risks need qualified review?"),
            ("vulnerable_population_plan", "Could eligibility include children, impaired consent, dependency relationships, or other vulnerability? State exclusions and additional protections, or explicitly justify none."),
            ("data_security_plan", "How will data be encrypted, access-controlled, audited, and handled after a security incident?"),
            ("incidental_findings_plan", "How will incidental, clinically relevant, or safety-relevant findings be handled and communicated?"),
        ):
            answer(key, prompt)
        answer("independent_review", "Has applicable qualified independent review been completed?", required=True, choices=("yes", "no"))
        brief["independent_review"] = brief["independent_review"] == "yes"
        if brief["independent_review"]:
            answer("independent_review_receipt", "What stable review receipt identifies that decision?")
            answer("independent_review_decision", "What decision did the reviewer record?", required=True,
                   choices=("approved", "approved_with_conditions", "not_approved", "pending", "withdrawn"))
            answer("independent_reviewer_role", "What qualified role or review body made the decision?")
            answer("independent_reviewed_at", "When was the decision recorded? Use an RFC 3339 timestamp with timezone.")
            answer("independent_review_scope", "What materials and activities were within the review scope?")
            answer("independent_review_artifact_locator", "Where is the review decision artifact stored below the artifact root?")
            answer("independent_review_artifact_sha256", "What is the lowercase SHA-256 digest of the review artifact?")
            if brief["independent_review_decision"] == "approved_with_conditions":
                conditions = ask("List every approval condition, separated by semicolons")
                brief["independent_review_conditions"] = _split_semicolon_answer(conditions)
    answer("observable_prediction", "What observable result do you predict, including direction and time window?")
    answer("null_model", "What no-effect or competing explanation could account for the observations?")
    falsifiers = ask("What observations would weaken your hypothesis? Separate conditions with semicolons [blank = unresolved]")
    brief["falsification_conditions"] = _split_semicolon_answer(falsifiers)
    answer("blinding_plan", "Who can see condition labels during collection, outcome assessment, and analysis? Describe masking, when labels are revealed, or why masking is infeasible and what safeguards replace it.")
    if brief["study_type"] in {"causal", "correlational"}:
        for key, prompt in (
            ("population", "What exact population may the final conclusion cover?"),
            ("setting", "What exact setting may the final conclusion cover?"),
            ("outcome_unit", "What unit will the primary effect estimate use?"),
            ("effect_scale", "What effect scale will define practical importance, such as a mean difference?"),
            ("conclusion_time_window", "What exact endpoint or time window may the final conclusion cover?"),
        ):
            if not brief.get(key, "").strip():
                answer(key, prompt)
        raw = ask("What is the smallest primary effect that would be scientifically or practically important? Enter a non-negative number [blank = unresolved]").strip()
        if raw:
            try:
                threshold = float(raw)
            except ValueError:
                threshold = None
            if threshold is not None and threshold >= 0:
                brief["smallest_effect_size_of_interest"] = threshold
        answer(
            "non_supporting_direction",
            "If the full support rule is not met, should the result be classified as inconclusive or weakening?",
            choices=("inconclusive", "weakens"),
        )
        unsupported = ask(
            "Which higher-level conclusions must remain unsupported? Separate them with semicolons [blank = unresolved]"
        )
        brief["higher_level_conclusions_unsupported"] = _split_semicolon_answer(unsupported)
    secondary = ask("What secondary outcomes will be analyzed? Separate exact outcome names with semicolons [blank = none declared]")
    brief["secondary_outcomes"] = _split_semicolon_answer(secondary)
    if brief["secondary_outcomes"]:
        registered_outcomes = [brief["outcome"], *brief["secondary_outcomes"]]
        if brief["study_type"] in {"exploratory", "descriptive"}:
            brief["confirmatory_outcomes"] = []
            brief["exploratory_outcomes"] = registered_outcomes
            brief["multiplicity_method"] = "exploratory_only"
            brief["multiplicity_alpha"] = None
        else:
            selected = ask("Which secondary outcomes are confirmatory? Enter exact names separated by semicolons [blank = none]")
            selected_keys = {
                item.casefold() for item in _split_semicolon_answer(selected)
            }
            brief["confirmatory_outcomes"] = [
                brief["outcome"],
                *[item for item in brief["secondary_outcomes"] if item.casefold() in selected_keys],
            ]
            brief["exploratory_outcomes"] = [
                item for item in brief["secondary_outcomes"] if item.casefold() not in selected_keys
            ]
            brief["multiplicity_method"] = (
                "single_test" if len(brief["confirmatory_outcomes"]) == 1 else "holm"
            )
            while "multiplicity_alpha" not in brief:
                value = ask("What family-wise alpha will govern the confirmatory family? Enter a number strictly between 0 and 1 [required]").strip()
                try:
                    alpha = float(value)
                except ValueError:
                    continue
                if 0 < alpha < 1:
                    brief["multiplicity_alpha"] = alpha
        answer("multiple_testing_policy", "What is the confirmatory testing family and adjustment or hierarchical rule? How will secondary outcomes be interpreted?", required=True)
    answer(
        "outcome_scale", "What is the primary outcome's data scale?",
        choices=("binary", "nominal", "ordinal", "interval", "ratio", "count", "time_to_event"),
    )
    if brief.get("outcome_scale") in {"binary", "nominal", "ordinal"}:
        values = ask("List every permitted outcome category, separated by semicolons [blank = unresolved]")
        brief["outcome_admissible_values"] = _split_semicolon_answer(values)
    answer(
        "primary_analysis_family", "Which structured primary analysis family fits the design and outcome scale?",
        choices=("mean_difference", "paired_mean_difference", "adjusted_linear_effect", "descriptive", "custom_reviewed"),
    )
    answer("primary_estimand", "What exact population quantity will the primary analysis estimate?")
    answer("contrast_definition", "Define the signed contrast order, such as treatment minus control.")
    contrast_groups = ask("List the two ordered contrast levels as first; second [blank = unresolved]")
    brief["contrast_groups"] = _split_semicolon_answer(contrast_groups)
    if len(brief["contrast_groups"]) == 2:
        answer(
            "group_data_column",
            "What exact dataset column will contain those comparison or exposure levels?",
        )
    answer(
        "expected_effect_direction", "What direction is predicted for that signed contrast?",
        choices=("positive", "negative", "two_sided", "equivalence"),
    )
    answer_finite("null_value", "What numeric null value will the primary estimate be compared with?")
    answer(
        "support_rule", "What result rule will govern support?",
        choices=("point_direction", "interval_excludes_null", "interval_within_equivalence_margin"),
    )
    answer_confidence("confidence_level", "What confidence level will the registered interval use, from 0.8 up to but not including 1?")
    answer("outcome_data_column", "What exact dataset column will contain the primary outcome?")
    answer("measurement_observable", "What exact observable or recorded quantity defines the primary outcome?")
    answer("measurement_input_condition", "Under what exact input condition or dataset slice is the primary measurement defined?")
    while True:
        raw_parameters = ask("List fixed measurement parameters as name=value pairs separated by semicolons [blank = unresolved]")
        if not raw_parameters.strip():
            break
        parameter_values: dict[str, str] = {}
        valid_parameters = True
        for item in _split_semicolon_answer(raw_parameters):
            parts = item.split("=", 1)
            if len(parts) != 2 or not all(part.strip() for part in parts) or parts[0] in parameter_values:
                valid_parameters = False
                break
            parameter_values[parts[0]] = parts[1]
        if valid_parameters:
            brief["measurement_parameter_values"] = parameter_values
            break
    for key, prompt in (
        ("measurement_evaluation_point", "At what exact time, location, scale point, or processing stage is the measurement evaluated?"),
        ("measurement_convention", "What sign, coding, normalization, or ordering convention defines the recorded value?"),
        ("measurement_aggregation", "How are repeated readings reduced to the primary reported value?"),
        ("measurement_tolerance", "What fixed measurement tolerance or acceptance bound applies?"),
        ("measurement_expected_behavior", "What behavior is prospectively expected from this outcome measurement?"),
    ):
        answer(key, prompt)
    answer(
        "measurement_temporal_role", "When is the primary measurement taken relative to exposure?",
        choices=MEASUREMENT_TEMPORAL_ROLES,
    )
    validity_names = ask(
        "Name prospective primary-measurement validity checks, separated by semicolons [blank = unresolved]"
    )
    validity_checks = []
    for name in _split_semicolon_answer(validity_names):
        draft: dict[str, str] = {"check_id": name}
        answer(
            "_validity_type",
            f"What evidence type will validity check '{name}' use?",
            choices=("criterion", "convergent", "discriminant", "known_groups", "test_retest", "inter_rater", "content", "calibration", "other"),
        )
        draft["evidence_type"] = brief.pop("_validity_type", "")
        for key, prompt in (
            ("validity_claim", f"What exact aspect of validity does check '{name}' address?"),
            ("assessment_plan", f"How will validity check '{name}' be assessed before interpreting the primary result?"),
            ("acceptance_criterion", f"What prospective result will count as acceptable for validity check '{name}'?"),
            ("failure_response", f"What will happen if validity check '{name}' fails or is inconclusive?"),
            ("assessment_gate_id", f"What dedicated required gate ID will record validity check '{name}'?"),
        ):
            answer("_validity_value", prompt)
            draft[key] = brief.pop("_validity_value", "")
        if all(draft.values()):
            validity_checks.append(draft)
    if validity_checks:
        brief["measurement_validity_checks"] = validity_checks
    secondary_measurements = []
    for outcome in brief["secondary_outcomes"]:
        draft: dict[str, Any] = {"outcome": outcome}
        for key, prompt in (
            ("observable", f"What exact observable defines secondary outcome '{outcome}'?"),
            ("input_condition", f"Under what input condition is secondary outcome '{outcome}' measured?"),
        ):
            answer("_secondary_value", prompt)
            draft[key] = brief.pop("_secondary_value", "")
        while True:
            raw = ask(f"List fixed parameters for secondary outcome '{outcome}' as name=value pairs separated by semicolons [blank = unresolved]")
            if not raw.strip():
                draft["parameter_values"] = {}
                break
            values: dict[str, str] = {}
            valid = True
            for item in _split_semicolon_answer(raw):
                parts = item.split("=", 1)
                if len(parts) != 2 or not all(part.strip() for part in parts) or parts[0] in values:
                    valid = False
                    break
                values[parts[0]] = parts[1]
            if valid:
                draft["parameter_values"] = values
                break
        for key, prompt in (
            ("evaluation_point", f"Where or when is secondary outcome '{outcome}' evaluated?"),
            ("convention", f"What coding or sign convention defines secondary outcome '{outcome}'?"),
            ("aggregation", f"How is secondary outcome '{outcome}' aggregated per independent unit?"),
            ("tolerance", f"What measurement tolerance applies to secondary outcome '{outcome}'?"),
            ("expected_behavior", f"What behavior is prospectively expected for secondary outcome '{outcome}'?"),
            ("data_column", f"What exact data column will contain secondary outcome '{outcome}'?"),
        ):
            answer("_secondary_value", prompt)
            draft[key] = brief.pop("_secondary_value", "")
        answer("_secondary_temporal", f"What is the temporal role of secondary outcome '{outcome}'?", choices=MEASUREMENT_TEMPORAL_ROLES)
        draft["temporal_role"] = brief.pop("_secondary_temporal", "")
        answer("_secondary_scale", f"What is the scale type of secondary outcome '{outcome}'?", choices=("binary", "nominal", "ordinal", "interval", "ratio", "count", "time_to_event"))
        draft["scale_type"] = brief.pop("_secondary_scale", "")
        answer("_secondary_unit", f"What physical or semantic unit does secondary outcome '{outcome}' use?")
        draft["unit"] = brief.pop("_secondary_unit", "")
        if draft["scale_type"] in {"binary", "nominal", "ordinal"}:
            raw = ask(f"List every admissible value for secondary outcome '{outcome}', separated by semicolons [blank = unresolved]")
            draft["admissible_values"] = _split_semicolon_answer(raw)
        else:
            draft["admissible_values"] = []
        raw = ask(f"List missing-value codes for secondary outcome '{outcome}', separated by semicolons [blank = none]")
        draft["missing_value_codes"] = _split_semicolon_answer(raw)
        draft["valid_min"] = None
        draft["valid_max"] = None
        if (
            all(draft[key] for key in (
                "observable", "input_condition", "parameter_values",
                "evaluation_point", "convention", "aggregation", "tolerance",
                "expected_behavior", "data_column", "temporal_role", "scale_type", "unit",
            ))
            and (draft["scale_type"] not in {"binary", "nominal", "ordinal"} or draft["admissible_values"])
        ):
            secondary_measurements.append(draft)
    if secondary_measurements:
        brief["secondary_measurements"] = secondary_measurements
    causal_measurements = []
    identification = brief.get("causal_identification")
    if brief.get("study_type") == "causal" and isinstance(identification, dict):
        required_causal = [
            ("exposure", identification["exposure"]),
            *[("covariate", item) for item in identification["proposed_adjustment_set"]],
        ]
        for role, variable in required_causal:
            draft: dict[str, Any] = {
                "role": role,
                "variable": variable,
                "data_column": (
                    brief.get("group_data_column", "")
                    if role == "exposure" else variable
                ),
            }
            for key, prompt in (
                ("observable", f"What exact observable defines causal {role} '{variable}'?"),
                ("input_condition", f"Under what exact input condition is causal {role} '{variable}' measured?"),
            ):
                answer("_causal_value", prompt)
                draft[key] = brief.pop("_causal_value", "")
            while True:
                raw = ask(f"List fixed parameters for causal {role} '{variable}' as name=value pairs separated by semicolons [blank = unresolved]")
                if not raw.strip():
                    draft["parameter_values"] = {}
                    break
                values: dict[str, str] = {}
                valid = True
                for item in _split_semicolon_answer(raw):
                    parts = item.split("=", 1)
                    if len(parts) != 2 or not all(part.strip() for part in parts) or parts[0] in values:
                        valid = False
                        break
                    values[parts[0]] = parts[1]
                if valid:
                    draft["parameter_values"] = values
                    break
            for key, prompt in (
                ("evaluation_point", f"Where or when is causal {role} '{variable}' evaluated?"),
                ("convention", f"What coding or sign convention defines causal {role} '{variable}'?"),
                ("aggregation", f"How is causal {role} '{variable}' aggregated per independent unit?"),
                ("tolerance", f"What measurement tolerance applies to causal {role} '{variable}'?"),
                ("expected_behavior", f"What behavior is prospectively expected for causal {role} '{variable}'?"),
            ):
                answer("_causal_value", prompt)
                draft[key] = brief.pop("_causal_value", "")
            answer("_causal_temporal", f"What is the temporal role of causal {role} '{variable}'?", choices=MEASUREMENT_TEMPORAL_ROLES)
            draft["temporal_role"] = brief.pop("_causal_temporal", "")
            answer("_causal_scale", f"What is the scale type of causal {role} '{variable}'?", choices=("binary", "nominal", "ordinal", "interval", "ratio", "count", "time_to_event"))
            draft["scale_type"] = brief.pop("_causal_scale", "")
            answer("_causal_unit", f"What physical or semantic unit does causal {role} '{variable}' use?")
            draft["unit"] = brief.pop("_causal_unit", "")
            if draft["scale_type"] in {"binary", "nominal", "ordinal"}:
                raw = ask(f"List every admissible value for causal {role} '{variable}', separated by semicolons [blank = unresolved]")
                draft["admissible_values"] = _split_semicolon_answer(raw)
            else:
                draft["admissible_values"] = []
            raw = ask(f"List missing-value codes for causal {role} '{variable}', separated by semicolons [blank = none]")
            draft["missing_value_codes"] = _split_semicolon_answer(raw)
            draft["valid_min"] = None
            draft["valid_max"] = None
            if (
                all(draft[key] for key in (
                    "observable", "input_condition", "parameter_values",
                    "evaluation_point", "convention", "aggregation", "tolerance",
                    "expected_behavior", "data_column", "temporal_role", "scale_type", "unit",
                ))
                and (draft["scale_type"] not in {"binary", "nominal", "ordinal"} or draft["admissible_values"])
            ):
                causal_measurements.append(draft)
    if causal_measurements:
        brief["causal_measurements"] = causal_measurements
    control_measurements = []
    for control in brief["controls"]:
        draft: dict[str, Any] = {"control": control}
        for key, prompt in (
            ("observable", f"What exact observable defines control '{control}'?"),
            ("input_condition", f"Under what input condition is control '{control}' evaluated?"),
        ):
            answer("_control_value", prompt)
            draft[key] = brief.pop("_control_value", "")
        while True:
            raw = ask(f"List fixed parameters for control '{control}' as name=value pairs separated by semicolons [blank = unresolved]")
            if not raw.strip():
                draft["parameter_values"] = {}
                break
            values: dict[str, str] = {}
            valid = True
            for item in _split_semicolon_answer(raw):
                parts = item.split("=", 1)
                if len(parts) != 2 or not all(part.strip() for part in parts) or parts[0] in values:
                    valid = False
                    break
                values[parts[0]] = parts[1]
            if valid:
                draft["parameter_values"] = values
                break
        for key, prompt in (
            ("evaluation_point", f"Where or when is control '{control}' evaluated?"),
            ("convention", f"What coding, sign, or ordering convention defines control '{control}'?"),
            ("aggregation", f"How are readings for control '{control}' aggregated?"),
            ("tolerance", f"What fixed acceptance tolerance applies to control '{control}'?"),
            ("expected_behavior", f"What prospective behavior is expected for control '{control}'?"),
            ("data_column", f"What data column contains control '{control}'? Leave blank if it is evaluated only in a retained artifact."),
        ):
            answer("_control_value", prompt)
            draft[key] = brief.pop("_control_value", "")
        answer("_control_temporal", f"What is the temporal role of control '{control}'?", choices=MEASUREMENT_TEMPORAL_ROLES)
        draft["temporal_role"] = brief.pop("_control_temporal", "")
        draft.update({
            "scale_type": "", "unit": "", "admissible_values": [],
            "valid_min": None, "valid_max": None, "missing_value_codes": [],
        })
        if draft["data_column"]:
            answer("_control_scale", f"What is the scale type of control '{control}'?", choices=("binary", "nominal", "ordinal", "interval", "ratio", "count", "time_to_event"))
            draft["scale_type"] = brief.pop("_control_scale", "")
            answer("_control_unit", f"What physical or semantic unit does control '{control}' use?")
            draft["unit"] = brief.pop("_control_unit", "")
            if draft["scale_type"] in {"binary", "nominal", "ordinal"}:
                raw = ask(f"List every admissible value for control '{control}', separated by semicolons [blank = unresolved]")
                draft["admissible_values"] = _split_semicolon_answer(raw)
            raw = ask(f"List missing-value codes for control '{control}', separated by semicolons [blank = none]")
            draft["missing_value_codes"] = _split_semicolon_answer(raw)
        if all(draft[key] for key in (
            "observable", "input_condition", "parameter_values",
            "evaluation_point", "convention", "aggregation", "tolerance",
            "expected_behavior", "temporal_role",
        )):
            control_measurements.append(draft)
    if control_measurements:
        brief["control_measurements"] = control_measurements
    return {"brief": brief, "scaffold": scaffold_design(brief)}
