"""Published schema syntax and representative synthetic command compatibility."""
import json
from pathlib import Path

import pytest

jsonschema = pytest.importorskip("jsonschema")
SCHEMAS = Path(__file__).resolve().parents[1] / "schemas"
EXAMPLES = Path(__file__).resolve().parents[1] / "examples"
from research_machine.addons.general_science import MANIFEST
from research_machine.application.dataset_inventory import build_dataset_inventory
from research_machine.domain.models import (
    ClaimDisposition,
    ClaimEpistemicLayer,
    ClaimLevel,
    DatasetArtifact,
    DatasetManifest,
    DatasetRole,
    ExperimentProtocol,
    RigorFinding,
    RigorSeverity,
    ValidationTag,
)


@pytest.mark.parametrize("method", MANIFEST.methods, ids=lambda method: method.method_id)
def test_analysis_schema_requires_every_manifest_field(method):
    schema = json.loads((SCHEMAS / "general-analysis.schema.json").read_text())
    values = {"columns": ["x"], "x_column": "x", "y_column": "y",
                  "outcome_column": "x", "group_column": "group", "groups": ["a", "b"],
                  "seed": 1, "pair_column": "pair", "unit_column": "unit",
                  "covariate_columns": ["baseline"],
              "study_design": "paired" if method.method_id == "paired_mean_difference_ci" else "independent_groups"}
    values.update(hypothesis_column="hypothesis", p_value_column="p", family_name="primary family", family_hypothesis_ids=["h1"], alpha=0.05)
    command = {"method": method.method_id, "claim_ceiling": "Synthetic fixture",
               **{key: values[key] for key in method.required_spec_fields}}
    jsonschema.validate(command, schema)
    for key in method.required_spec_fields:
        with pytest.raises(jsonschema.ValidationError):
            jsonschema.validate({name: value for name, value in command.items() if name != key}, schema)
    if method.method_id not in {"permutation_mean_difference", "independent_mean_difference_ci", "adjusted_linear_effect"}:
        with pytest.raises(jsonschema.ValidationError):
            jsonschema.validate({**command, "unit_column": "unit"}, schema)


@pytest.mark.parametrize("path", sorted(SCHEMAS.glob("*.schema.json")), ids=lambda p: p.name)
def test_published_schema_is_well_formed(path):
    jsonschema.Draft202012Validator.check_schema(json.loads(path.read_text()))


@pytest.mark.parametrize(
    ("schema_name", "mutation"),
    [
        (
            "evidence-command.schema.json",
            lambda command: command.update(
                {"summary": "This confirmed the mechanism."}
            ),
        ),
        (
            "run-record.schema.json",
            lambda command: command.update(
                {"summary": "This proved the execution result."}
            ),
        ),
        (
            "run-record.schema.json",
            lambda command: command["quality_gates"][0].update(
                {"summary": "This explained the effect."}
            ),
        ),
        (
            "evidence-command.schema.json",
            lambda command: command.update(
                {"summary": "This validates the mechanism."}
            ),
        ),
    ],
)
def test_report_command_schemas_reject_overclaiming_summaries(schema_name, mutation):
    schema = json.loads((SCHEMAS / schema_name).read_text())
    if schema_name == "evidence-command.schema.json":
        command = {
            "hypothesis_id": "hyp-bounded",
            "direction": "inconclusive",
            "summary": "The result remains inconclusive against registered alternatives.",
            "dataset_id": "dataset-bounded",
            "analysis_id": "analysis-bounded",
            "uncertainty": "Synthetic fixture uncertainty remains large.",
            "scope": "Synthetic schema fixture only.",
            "higher_level_conclusions_unsupported": [
                "Mechanism and causality remain unsupported."
            ],
            "validation_tags": ["calibration"],
            "exploratory": True,
        }
    else:
        command = json.loads((EXAMPLES / "run-record.json").read_text())
    jsonschema.validate(command, schema)
    mutation(command)
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(command, schema)


def test_evidence_command_schema_validation_tags_match_domain_model():
    schema = json.loads((SCHEMAS / "evidence-command.schema.json").read_text())
    published_tags = set(schema["properties"]["validation_tags"]["items"]["enum"])
    assert published_tags == {tag.value for tag in ValidationTag}


def test_claim_command_schema_enums_match_domain_model():
    schema = json.loads((SCHEMAS / "claim-command.schema.json").read_text())
    assert set(schema["properties"]["level"]["enum"]) == {
        level.value for level in ClaimLevel
    }
    assert set(schema["properties"]["epistemic_layer"]["enum"]) == {
        layer.value for layer in ClaimEpistemicLayer
    }
    assert set(schema["properties"]["disposition"]["enum"]) == {
        disposition.value for disposition in ClaimDisposition
    }


def test_dataset_inventory_schema_accepts_builder_payloads():
    schema = json.loads((SCHEMAS / "dataset-inventory.schema.json").read_text())
    protocol = ExperimentProtocol(
        protocol_id="protocol-schema-fixture",
        protocol_family_id="protocol-schema-fixture",
        version=1,
        experiment_id="dataset-inventory-schema",
        title="Dataset inventory schema fixture",
        analysis_mode="confirmatory",
        hypotheses_tested=[],
        primary_outcome="Fixture outcome",
        created_at="2026-09-13T00:00:00Z",
        created_by="schema-test",
        protocol_kind="observational",
        quality_requirements=["fixture-gate"],
        controls=["fixture-control"],
        sample_size_or_stopping_rule="Synthetic schema fixture.",
        status="frozen",
        protocol_hash="a" * 64,
    )
    exploratory = DatasetManifest(
        dataset_id="exploratory-schema-fixture",
        name="Exploratory schema fixture",
        role=DatasetRole.EXPLORATORY,
        created_at="2026-09-13T00:00:00Z",
        artifacts=[DatasetArtifact("explore.csv", "b" * 64, 11, "text/csv")],
        synthetic=True,
        metadata={"dataset_payload_sha256": "c" * 64},
    )
    protected = DatasetManifest(
        dataset_id="protected-schema-fixture",
        name="Protected schema fixture",
        role=DatasetRole.CONFIRMATORY,
        created_at="2026-09-13T00:00:00Z",
        artifacts=[DatasetArtifact("observations.csv", "d" * 64, 13, "text/csv")],
        protocol_id=protocol.protocol_id,
        synthetic=False,
        metadata={
            "dataset_payload_sha256": "e" * 64,
            "dataset_artifact_verification": {
                "artifact_integrity": {
                    "status": "passed",
                    "all_artifacts_match": True,
                }
            },
        },
    )
    finding = RigorFinding(
        code="PROTECTED_DATASET_SCHEMA_FIXTURE",
        severity=RigorSeverity.ERROR,
        message="Synthetic fixture protected dataset remains blocked.",
        entity_type="dataset",
        entity_id=protected.dataset_id,
        remediation="Resolve the synthetic fixture blocker before use.",
    )

    empty_inventory = build_dataset_inventory([], [])
    populated_inventory = build_dataset_inventory(
        [exploratory, protected], [protocol], [finding]
    )

    jsonschema.validate(empty_inventory, schema)
    jsonschema.validate(populated_inventory, schema)
    protected_row = next(
        row for row in populated_inventory["datasets"]
        if row["dataset_id"] == protected.dataset_id
    )
    assert protected_row["operational_roots_redacted"] is True
    assert protected_row["readiness"]["status"] == "protected_use_blocked_by_rigor"


def test_dataset_inventory_schema_requires_operational_root_redaction():
    schema = json.loads((SCHEMAS / "dataset-inventory.schema.json").read_text())
    inventory = build_dataset_inventory(
        [
            DatasetManifest(
                dataset_id="redaction-schema-fixture",
                name="Redaction schema fixture",
                role=DatasetRole.EXPLORATORY,
                created_at="2026-09-13T00:00:00Z",
                artifacts=[DatasetArtifact("fixture.csv", "f" * 64, 17, "text/csv")],
                synthetic=False,
            )
        ],
        [],
    )
    jsonschema.validate(inventory, schema)
    inventory["datasets"][0]["operational_roots_redacted"] = False
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(inventory, schema)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("statement", " "),
        ("parent_claims", [" clm-parent "]),
        ("source_refs", [" source:record "]),
        ("conflicts_with", [" clm-conflict "]),
        ("falsified_by", [" falsifier:record "]),
    ],
)
def test_claim_command_schema_rejects_blank_or_padded_scientific_handles(
    field, value
):
    schema = json.loads((SCHEMAS / "claim-command.schema.json").read_text())
    command = {
        "statement": "The source makes a bounded claim.",
        "level": "other",
    }
    command[field] = value
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(command, schema)


@pytest.mark.parametrize(
    "mutation",
    [
        lambda command: command.pop("last_reviewed"),
        lambda command: command.update({"last_reviewed": " "}),
        lambda command: command.pop("decision_owner"),
        lambda command: command.update({"decision_owner": " "}),
        lambda command: (
            command.update({"epistemic_layer": "source_claim"}),
            command.pop("source_refs"),
        ),
    ],
)
def test_claim_command_schema_preflights_accepted_claim_authority(mutation):
    schema = json.loads((SCHEMAS / "claim-command.schema.json").read_text())
    command = {
        "statement": "The source reports the bounded observation.",
        "level": "other",
        "epistemic_layer": "documented_fact",
        "disposition": "accepted",
        "last_reviewed": "2026-09-03T12:00:00Z",
        "decision_owner": "project-owner",
        "source_refs": ["source:record"],
    }
    jsonschema.validate(command, schema)
    mutation(command)
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(command, schema)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("statement", " "),
        ("generated_by", " "),
        ("parent_claims", [" clm-parent "]),
        ("lineage", [" hyp-prior "]),
        ("source_context", [" "]),
        ("competing_models", [" "]),
        ("contrast_groups", ["treatment", "treatment"]),
        ("covariates", [" "]),
        ("known_confounds", [" "]),
        ("falsification_conditions", [" "]),
        ("support_conditions", [" "]),
        ("boundary_conditions", [" "]),
    ],
)
def test_hypothesis_proposal_schema_rejects_noncanonical_scientific_inputs(
    field, value
):
    schema = json.loads((SCHEMAS / "hypothesis-proposal.schema.json").read_text())
    command = {
        "statement": "The bounded candidate remains a proposal.",
        "generated_by": "codex",
    }
    command[field] = value
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(command, schema)


@pytest.mark.parametrize(
    "mutation",
    [
        lambda command: command.pop("contrast_groups"),
        lambda command: command.update({"contrast_groups": ["treatment"]}),
        lambda command: command.pop("contrast_definition"),
        lambda command: command.update({"contrast_definition": " "}),
    ],
)
def test_hypothesis_proposal_schema_pairs_contrast_definition_and_groups(
    mutation,
):
    schema = json.loads((SCHEMAS / "hypothesis-proposal.schema.json").read_text())
    command = {
        "statement": "The bounded two-level contrast remains a proposal.",
        "contrast_definition": "Treatment minus control.",
        "contrast_groups": ["treatment", "control"],
    }
    jsonschema.validate(command, schema)
    mutation(command)
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(command, schema)


def _protocol_command_with_component_calibration():
    command = json.loads((EXAMPLES / "formal-protocol.json").read_text())
    command["measurement_custody_requirements"] = ["field-map-check"]
    command["calibration_acceptance_criteria"] = [
        {
            "criterion_id": "field-map-residuals",
            "calibration_id": "field-map",
            "quantity": "two-axis field-map residual",
            "unit": "milliunit",
            "rationale": "Every registered calibration axis remains inside tolerance.",
            "component_bounds": [
                {
                    "component_id": "x-axis",
                    "quantity": "x-axis residual",
                    "unit": "milliunit",
                    "lower_bound": -0.5,
                    "upper_bound": 0.5,
                },
                {
                    "component_id": "y-axis",
                    "quantity": "y-axis residual",
                    "unit": "milliunit",
                    "lower_bound": -0.5,
                    "upper_bound": 0.5,
                },
            ],
        }
    ]
    return command


def test_protocol_schema_accepts_component_calibration_bounds():
    schema = json.loads((SCHEMAS / "protocol-command.schema.json").read_text())
    jsonschema.validate(_protocol_command_with_component_calibration(), schema)


@pytest.mark.parametrize(
    "mutation",
    [
        lambda command: command["calibration_acceptance_criteria"][0].update(
            {"criterion_id": " field-map-residuals "}
        ),
        lambda command: command["calibration_acceptance_criteria"][0][
            "component_bounds"
        ][0].update({"component_id": " x-axis "}),
        lambda command: command["calibration_acceptance_criteria"][0].update(
            {"lower_bound": -0.5}
        ),
        lambda command: command["calibration_acceptance_criteria"][0][
            "component_bounds"
        ][0].update({"lower_bound": None, "upper_bound": None}),
    ],
)
def test_protocol_schema_preflights_component_calibration_shape(mutation):
    schema = json.loads((SCHEMAS / "protocol-command.schema.json").read_text())
    command = _protocol_command_with_component_calibration()
    mutation(command)
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(command, schema)


def test_evidence_command_schema_accepts_causal_estimate_tag_without_overclaiming():
    schema = json.loads((SCHEMAS / "evidence-command.schema.json").read_text())
    command = {
        "hypothesis_id": "hyp-causal-fixture",
        "claim_id": "claim-causal-fixture",
        "direction": "supports",
        "summary": "The registered estimate supports the scoped causal-direction claim under the frozen design assumptions.",
        "run_id": "run-causal-fixture",
        "analysis_id": "analysis-causal-fixture",
        "effect_estimate": "Synthetic fixture design-conditional estimate.",
        "uncertainty": "Synthetic fixture interval remains bounded to the registered estimand.",
        "scope": "Synthetic schema fixture for a registered causal-direction claim.",
        "higher_level_conclusions_unsupported": [
            "Mechanism, intent, and unrestricted generalization remain unsupported."
        ],
        "validation_tags": ["empirical_test", "causal_estimate"],
        "exploratory": False,
    }
    jsonschema.validate(command, schema)


def test_evidence_command_schema_rejects_duplicate_unsupported_conclusions():
    schema = json.loads((SCHEMAS / "evidence-command.schema.json").read_text())
    command = {
        "hypothesis_id": "hyp-ceiling-fixture",
        "direction": "inconclusive",
        "summary": "The fixture remains inconclusive.",
        "dataset_id": "dataset-ceiling-fixture",
        "analysis_id": "analysis-ceiling-fixture",
        "uncertainty": "Synthetic fixture uncertainty remains unresolved.",
        "scope": "Synthetic schema fixture only.",
        "higher_level_conclusions_unsupported": [
            "Causality remains unsupported.",
            "Causality remains unsupported.",
        ],
        "validation_tags": ["source_assessment"],
        "exploratory": True,
    }
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(command, schema)


def test_evidence_command_schema_rejects_overclaiming_unsupported_conclusion():
    schema = json.loads((SCHEMAS / "evidence-command.schema.json").read_text())
    command = {
        "hypothesis_id": "hyp-ceiling-overclaim-fixture",
        "direction": "inconclusive",
        "summary": "The fixture remains inconclusive.",
        "dataset_id": "dataset-ceiling-overclaim-fixture",
        "analysis_id": "analysis-ceiling-overclaim-fixture",
        "uncertainty": "Synthetic fixture uncertainty remains unresolved.",
        "scope": "Synthetic schema fixture only.",
        "higher_level_conclusions_unsupported": [
            "The mechanism is not validated by this result."
        ],
        "validation_tags": ["source_assessment"],
        "exploratory": True,
    }
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(command, schema)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("summary", " "),
        ("scope", " "),
        ("uncertainty", " "),
        ("higher_level_conclusions_unsupported", [" "]),
        ("controls_passed", ["negative control", "negative control"]),
        ("controls_failed", [" "]),
    ],
)
def test_evidence_command_schema_preflights_evidence_annotation_invariants(
    field, value
):
    schema = json.loads((SCHEMAS / "evidence-command.schema.json").read_text())
    command = {
        "hypothesis_id": "hyp-annotation-fixture",
        "direction": "supports",
        "summary": "The fixture supports only the scoped synthetic check.",
        "dataset_id": "dataset-annotation-fixture",
        "analysis_id": "analysis-annotation-fixture",
        "uncertainty": "Synthetic fixture uncertainty.",
        "scope": "Synthetic schema fixture only.",
        "controls_passed": ["negative control"],
        "higher_level_conclusions_unsupported": [
            "Causality remains unsupported."
        ],
        "validation_tags": ["controlled_benchmark"],
        "exploratory": True,
    }
    command[field] = value
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(command, schema)


@pytest.mark.parametrize("bad_analysis_id", [None, " "])
def test_evidence_command_schema_requires_dataset_only_analysis_identity(
    bad_analysis_id,
):
    schema = json.loads((SCHEMAS / "evidence-command.schema.json").read_text())
    command = {
        "hypothesis_id": "hyp-dataset-analysis-fixture",
        "direction": "inconclusive",
        "summary": "The exploratory dataset-only note remains bounded.",
        "dataset_id": "dataset-analysis-fixture",
        "analysis_id": "analysis-dataset-fixture",
        "uncertainty": "Synthetic fixture uncertainty.",
        "scope": "Synthetic schema fixture only.",
        "higher_level_conclusions_unsupported": [
            "Confirmatory interpretation remains unsupported."
        ],
        "validation_tags": ["source_assessment"],
        "exploratory": True,
    }
    jsonschema.validate(command, schema)
    if bad_analysis_id is None:
        del command["analysis_id"]
    else:
        command["analysis_id"] = bad_analysis_id
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(command, schema)


def test_evidence_command_schema_allows_run_to_infer_analysis_identity():
    schema = json.loads((SCHEMAS / "evidence-command.schema.json").read_text())
    command = {
        "hypothesis_id": "hyp-run-analysis-fixture",
        "direction": "inconclusive",
        "summary": "The run-backed note remains bounded.",
        "run_id": "run-analysis-fixture",
        "uncertainty": "Synthetic fixture uncertainty.",
        "scope": "Synthetic schema fixture only.",
        "higher_level_conclusions_unsupported": [
            "Confirmatory interpretation remains unsupported."
        ],
        "validation_tags": ["source_assessment"],
        "exploratory": True,
    }
    jsonschema.validate(command, schema)


def test_empirical_protocol_command_matches_published_schema():
    from test_ethics_gate import _human_protocol
    from research_machine.interfaces.cli import _PROTOCOL_FIELDS
    protocol = _human_protocol(human_subjects=False).to_dict()
    command = {key: value for key, value in protocol.items() if key in _PROTOCOL_FIELDS}
    schema = json.loads((SCHEMAS / "protocol-command.schema.json").read_text())
    jsonschema.validate(command, schema)


def test_protocol_command_schema_accepts_apparatus_only_control_family():
    from dataclasses import replace
    from test_ethics_gate import _human_protocol
    from research_machine.domain.models import ControlDefinition
    from research_machine.interfaces.cli import _PROTOCOL_FIELDS

    protocol = replace(
        _human_protocol(human_subjects=False),
        controls=["Apparatus-only sample"],
        control_definitions=[
            ControlDefinition(
                "apparatus-only-1",
                "Apparatus-only sample",
                "apparatus_only",
                "Detect equipment or environment-generated artifacts.",
                "No target-dependent signal is detected.",
                "integrity",
            )
        ],
    ).to_dict()
    command = {key: value for key, value in protocol.items() if key in _PROTOCOL_FIELDS}
    schema = json.loads((SCHEMAS / "protocol-command.schema.json").read_text())
    jsonschema.validate(command, schema)


def test_protocol_command_schema_rejects_overclaiming_conclusion_ceiling():
    from test_protocol_design_structure import _multi_step_protocol
    from research_machine.interfaces.cli import _PROTOCOL_FIELDS

    protocol = _multi_step_protocol().to_dict()
    command = {key: value for key, value in protocol.items() if key in _PROTOCOL_FIELDS}
    command["conclusion_contract"]["higher_level_conclusions_unsupported"] = [
        "The protocol will not validate mechanism or intent."
    ]
    schema = json.loads((SCHEMAS / "protocol-command.schema.json").read_text())
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(command, schema)


def test_protocol_schema_accepts_and_constrains_measurement_validity_checks():
    from test_ethics_gate import _human_protocol
    from research_machine.interfaces.cli import _PROTOCOL_FIELDS

    protocol = _human_protocol(human_subjects=False).to_dict()
    command = {key: value for key, value in protocol.items() if key in _PROTOCOL_FIELDS}
    command["measurement_validity_checks"] = [{
        "check_id": "primary-validity",
        "measurement_id": "primary-measurement",
        "evidence_type": "criterion",
        "validity_claim": "Agreement with the registered reference.",
        "assessment_plan": "Compare the frozen validation subset.",
        "acceptance_criterion": "Agreement remains within the frozen tolerance.",
        "failure_response": "Stop primary interpretation.",
        "assessment_gate_id": "primary-validity-assessed",
    }]
    schema = json.loads((SCHEMAS / "protocol-command.schema.json").read_text())
    jsonschema.validate(command, schema)
    from research_machine.interfaces.cli import _protocol_command
    parsed = _protocol_command(command)
    assert parsed.measurement_validity_checks[0].check_id == "primary-validity"
    malformed = dict(command)
    malformed["measurement_validity_checks"] = [
        {**command["measurement_validity_checks"][0], "evidence_type": "trust_me"}
    ]
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(malformed, schema)


@pytest.mark.parametrize(
    "mutation",
    [
        lambda contract: contract.pop("contrast_definition"),
        lambda contract: contract.pop("contrast_groups"),
        lambda contract: contract.update({"contrast_definition": " group a minus group b "}),
        lambda contract: contract.update({"contrast_groups": ["a", " b "]}),
    ],
)
def test_protocol_schema_requires_explicit_analysis_contract_contrast(mutation):
    from test_protocol_design_structure import _multi_step_protocol
    from research_machine.interfaces.cli import _PROTOCOL_FIELDS

    protocol = _multi_step_protocol().to_dict()
    command = {key: value for key, value in protocol.items() if key in _PROTOCOL_FIELDS}
    schema = json.loads((SCHEMAS / "protocol-command.schema.json").read_text())
    jsonschema.validate(command, schema)

    mutation(command["analysis_contract"])
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(command, schema)


def test_published_causal_schemas_require_structured_assumption_register():
    from test_causal_identification import _confounded

    causal = _confounded(["baseline"])
    causal_schema = json.loads(
        (SCHEMAS / "causal-identification.schema.json").read_text()
    )
    jsonschema.validate(causal, causal_schema)
    without_assumptions = {
        key: value for key, value in causal.items() if key != "assumptions"
    }
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(without_assumptions, causal_schema)
    without_estimand = {
        key: value for key, value in causal.items() if key != "causal_estimand"
    }
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(without_estimand, causal_schema)

    protocol_schema = json.loads(
        (SCHEMAS / "protocol-command.schema.json").read_text()
    )
    from test_ethics_gate import _human_protocol
    from research_machine.interfaces.cli import _PROTOCOL_FIELDS
    protocol = _human_protocol(
        human_subjects=False,
        causal_claim=True,
        causal_identification=causal,
    ).to_dict()
    command = {key: value for key, value in protocol.items() if key in _PROTOCOL_FIELDS}
    jsonschema.validate(command, protocol_schema)
    command["causal_identification"] = without_assumptions
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(command, protocol_schema)


def test_identity_checked_analysis_matches_published_schema():
    schema = json.loads((SCHEMAS / "general-analysis.schema.json").read_text())
    command = {"method": "independent_mean_difference_ci", "study_design": "independent_groups",
               "groups": ["a", "b"], "outcome_column": "score", "group_column": "condition",
               "unit_column": "unit", "seed": 1, "claim_ceiling": "Synthetic fixture"}
    jsonschema.validate(command, schema)
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate({**command, "unit_column": " "}, schema)


def test_analysis_schema_rejects_padded_analysis_id():
    schema = json.loads((SCHEMAS / "general-analysis.schema.json").read_text())
    command = {
        "method": "descriptive_summary",
        "columns": ["x"],
        "analysis_id": " padded ",
        "claim_ceiling": "Synthetic fixture",
    }
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(command, schema)


def test_analysis_schema_fields_match_shared_execution_contract():
    from research_machine.addons.contracts import ANALYSIS_SPEC_FIELDS

    schema = json.loads((SCHEMAS / "general-analysis.schema.json").read_text())
    assert set(schema["properties"]) == set(ANALYSIS_SPEC_FIELDS)


@pytest.mark.parametrize(
    ("schema_name", "example_name"),
    [
        ("next-action.schema.json", "next-actions.json"),
        ("next-action-portfolio.schema.json", "next-action-portfolio.json"),
    ],
)
def test_next_action_examples_match_published_schemas(schema_name, example_name):
    schema = json.loads((SCHEMAS / schema_name).read_text())
    example = json.loads((EXAMPLES / example_name).read_text())
    jsonschema.validate(example, schema)


@pytest.mark.parametrize(
    "schema_name",
    ["next-action.schema.json", "next-action-portfolio.schema.json"],
)
def test_next_action_schema_requires_discrimination_targets(schema_name):
    schema = json.loads((SCHEMAS / schema_name).read_text())
    candidate = {
        "action_id": "hypothesis-target",
        "title": "Hypothesis target",
        "distinguishes_hypotheses": ["hyp-active"],
        "information_targets": ["lane:uncertainty"],
        "expected_discrimination": 0.8,
        "uncertainty_reduction": 0.7,
        "cost": 0.2,
        "burden": 0.1,
        "safety_risk": 0.0,
        "ambiguity_risk": 0.1,
        "rationale": "Separate the registered hypothesis from an alternative.",
        "prerequisite_evidence_refs": ["design-review:hypothesis-target"],
        "safety_review_refs": ["safety-review:hypothesis-target"],
        "lane_id": "science",
    }
    command = {"candidates": [candidate]}
    if schema_name == "next-action-portfolio.schema.json":
        command["lanes"] = [{"lane_id": "science", "title": "Science"}]
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(command, schema)


@pytest.mark.parametrize(
    "schema_name",
    ["next-action.schema.json", "next-action-portfolio.schema.json"],
)
def test_next_action_schema_rejects_service_derived_workflow_states(schema_name):
    schema = json.loads((SCHEMAS / schema_name).read_text())
    candidate = {
        "action_id": "hypothesis-target",
        "title": "Hypothesis target",
        "distinguishes_hypotheses": ["hyp-active"],
        "hypothesis_discrimination_targets": [
            {
                "hypothesis_id": "hyp-active",
                "discriminating_observation": "The registered falsifier separates the target from the alternative.",
                "expected_if_hypothesis": "The target pattern remains.",
                "expected_if_alternative": "The target pattern follows the alternative.",
                "would_weaken_if": "The target pattern disappears.",
                "competing_model_ref": "alternative",
            }
        ],
        "hypothesis_workflow_states": {"hyp-active": "active"},
        "expected_discrimination": 0.8,
        "uncertainty_reduction": 0.7,
        "cost": 0.2,
        "burden": 0.1,
        "safety_risk": 0.0,
        "ambiguity_risk": 0.1,
        "rationale": "Separate the registered hypothesis from an alternative.",
        "prerequisite_evidence_refs": ["design-review:hypothesis-target"],
        "safety_review_refs": ["safety-review:hypothesis-target"],
        "lane_id": "science",
    }
    command = {"candidates": [candidate]}
    if schema_name == "next-action-portfolio.schema.json":
        command["lanes"] = [{"lane_id": "science", "title": "Science"}]
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(command, schema)


def test_cross_lane_lesson_schema_requires_local_root_only_for_local_verification():
    schema = json.loads((SCHEMAS / "cross-lane-lesson.schema.json").read_text())
    command = {
        "origin_lane_id": "science",
        "target_lane_ids": ["machine"],
        "origin_artifact_locator": "results/run.json",
        "origin_artifact_sha256": "a" * 64,
        "origin_integrity_status": "declared",
        "observation": "A control omitted its evaluation time.",
        "failure_class": "interface_ambiguity",
        "strongest_alternative_explanation": "The implementation may be defective.",
        "challenged_invariant": "Every target is reproducibly defined.",
        "first_permitted_future_versions": ["machine-v2"],
        "prohibited_retroactive_targets": ["machine-v1"],
        "proposed_repair": "Require a typed evaluation time.",
        "repair_falsifier": "An omitted-time fixture is accepted.",
        "conclusion_ceiling": "Process lesson only.",
    }

    jsonschema.validate(command, schema)
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate({**command, "origin_artifact_root": "/tmp/artifacts"}, schema)
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(
            {**command, "origin_integrity_status": "verified_local"},
            schema,
        )
    jsonschema.validate(
        {
            **command,
            "origin_integrity_status": "verified_local",
            "origin_artifact_root": "/tmp/artifacts",
        },
        schema,
    )


def test_next_action_schema_rejects_single_action_dependencies():
    schema = json.loads((SCHEMAS / "next-action.schema.json").read_text())
    command = {
        "candidates": [
            {
                "action_id": "dependent-action",
                "title": "Dependent action",
                "distinguishes_hypotheses": ["hyp-active"],
                "hypothesis_discrimination_targets": [
                    {
                        "hypothesis_id": "hyp-active",
                        "discriminating_observation": "The next observation separates the target from the alternative.",
                        "expected_if_hypothesis": "The target pattern appears.",
                        "expected_if_alternative": "The target pattern follows the alternative.",
                        "would_weaken_if": "The target pattern disappears.",
                        "competing_model_ref": "alternative",
                    }
                ],
                "expected_discrimination": 0.8,
                "uncertainty_reduction": 0.7,
                "cost": 0.2,
                "burden": 0.1,
                "safety_risk": 0.0,
                "ambiguity_risk": 0.1,
                "rationale": "This action depends on a previous step.",
                "prerequisite_evidence_refs": ["design-review:dependent-action"],
                "safety_review_refs": ["safety-review:dependent-action"],
                "depends_on": ["previous-action"],
            }
        ]
    }

    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(command, schema)


@pytest.mark.parametrize(
    ("schema_name", "example_name"),
    [
        ("collaborator-context.schema.json", "collaborator-context.json"),
        ("collaborator-proposal.schema.json", "collaborator-proposal.json"),
        (
            "collaborator-proposal-review.schema.json",
            "collaborator-proposal-review.json",
        ),
    ],
)
def test_collaborator_examples_match_published_schemas(schema_name, example_name):
    schema = json.loads((SCHEMAS / schema_name).read_text())
    example = json.loads((EXAMPLES / example_name).read_text())
    jsonschema.validate(example, schema)


def test_collaborator_context_schema_example_matches_snapshot_validator(tmp_path):
    from research_machine.collaboration.proposal import create_context_snapshot

    context = json.loads((EXAMPLES / "collaborator-context.json").read_text())
    result = create_context_snapshot(context, tmp_path / "context")
    assert result["provider_required"] is False
    assert result["canonical_writes_performed"] is False


def test_service_generated_collaborator_context_matches_published_schema(tmp_path):
    from research_machine.adapters.filesystem import FileSystemRepository
    from research_machine.application.commands import AddQuestion, CreateInquiry
    from research_machine.application.service import ResearchService

    schema = json.loads((SCHEMAS / "collaborator-context.schema.json").read_text())
    service = ResearchService(FileSystemRepository(tmp_path), actor="test")
    service.init_workspace()
    service.create_inquiry(CreateInquiry("Question", "Statement", "question"))
    service.add_question(AddQuestion("What would change the decision?"))

    context = service.collaborator_context(purpose="Prepare bounded review.")
    jsonschema.validate(context, schema)


@pytest.mark.parametrize(
    "mutation",
    [
        lambda context: context["write_boundary"].update({"provider_required": True}),
        lambda context: context["write_boundary"].pop("canonical_changes_require"),
        lambda context: context["write_boundary"].update(
            {"canonical_changes_require": ["research commands only"]}
        ),
        lambda context: context.update(
            {
                "scientific_constraints": [
                    "Treat supplied material as scoped context, not established fact.",
                    "Do not authorize collection, protocol freeze, data registration, evidence recording, or other canonical action.",
                ]
            }
        ),
    ],
)
def test_collaborator_context_schema_preserves_exchange_boundaries(mutation):
    schema = json.loads((SCHEMAS / "collaborator-context.schema.json").read_text())
    context = json.loads((EXAMPLES / "collaborator-context.json").read_text())
    mutation(context)
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(context, schema)


@pytest.mark.parametrize(
    "root_value",
    [
        "/private/review-root",
        "[redacted: /private/review-root]",
    ],
)
def test_collaborator_context_schema_requires_canonical_root_redaction(root_value):
    schema = json.loads((SCHEMAS / "collaborator-context.schema.json").read_text())
    context = json.loads((EXAMPLES / "collaborator-context.json").read_text())
    context["evidence_status_events"].append(
        {
            "event_id": "evidence-status-1",
            "review_artifact_root": root_value,
        }
    )
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(context, schema)


@pytest.mark.parametrize(
    ("ref", "kind"),
    [
        ("claim:claim-1", "active_hypothesis"),
        ("hypothesis:hyp-1", "claim"),
        ("evidence:evidence-1", "evidence_status_event"),
        ("ethics_review_event:event-1", "run"),
    ],
)
def test_collaborator_context_schema_matches_reference_prefix_to_kind(ref, kind):
    schema = json.loads((SCHEMAS / "collaborator-context.schema.json").read_text())
    context = json.loads((EXAMPLES / "collaborator-context.json").read_text())
    context["context_reference_index"][0] = {"ref": ref, "kind": kind}
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(context, schema)


def test_collaborator_proposal_schema_preserves_review_only_boundary():
    schema = json.loads((SCHEMAS / "collaborator-proposal.schema.json").read_text())
    proposal = json.loads((EXAMPLES / "collaborator-proposal.json").read_text())
    proposal["suggestions"][0]["authority"] = "canonical_write"
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(proposal, schema)


def test_collaborator_proposal_schema_requires_provider_for_model_generators():
    schema = json.loads((SCHEMAS / "collaborator-proposal.schema.json").read_text())
    proposal = json.loads((EXAMPLES / "collaborator-proposal.json").read_text())
    proposal["generated_by"] = {"kind": "llm", "provider": "", "model": ""}
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(proposal, schema)


@pytest.mark.parametrize(
    "mutation",
    [
        lambda proposal: proposal.update(
            {"summary": "This proposal confirms the result."}
        ),
        lambda proposal: proposal.update(
            {"summary": "This proposal APPROVED the result."}
        ),
        lambda proposal: proposal.update(
            {"summary": "This proposal is human-reviewed."}
        ),
        lambda proposal: proposal["competing_explanations"].__setitem__(
            0, "This validates the favored mechanism."
        ),
        lambda proposal: proposal["suggestions"][0].update(
            {"statement": "This proposal Validated the route."}
        ),
        lambda proposal: proposal["suggestions"][0].update(
            {"rationale": "This proposal authorizes evidence creation."}
        ),
        lambda proposal: proposal["suggestions"][0].update(
            {"falsification_conditions": ["This proves the suggested mechanism."]}
        ),
    ],
)
def test_collaborator_proposal_schema_rejects_authority_claims(mutation):
    schema = json.loads((SCHEMAS / "collaborator-proposal.schema.json").read_text())
    proposal = json.loads((EXAMPLES / "collaborator-proposal.json").read_text())
    mutation(proposal)
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(proposal, schema)


@pytest.mark.parametrize(
    "mutation",
    [
        lambda review: review["decisions"][0].update(
            {"disposition": "defer", "domain_route": "design.revise"}
        ),
        lambda review: review["decisions"][0].update(
            {"disposition": "advance_to_domain_review", "domain_route": "none"}
        ),
    ],
)
def test_collaborator_review_schema_constrains_route_authority(mutation):
    schema = json.loads(
        (SCHEMAS / "collaborator-proposal-review.schema.json").read_text()
    )
    review = json.loads((EXAMPLES / "collaborator-proposal-review.json").read_text())
    mutation(review)
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(review, schema)


@pytest.mark.parametrize(
    "mutation",
    [
        lambda review: review.update(
            {"overall_assessment": "This review approves the proposal."}
        ),
        lambda review: review.update(
            {"overall_assessment": "This review APPROVES the proposal."}
        ),
        lambda review: review.update(
            {"overall_assessment": "Reviewer identity authenticated for this triage."}
        ),
        lambda review: review["decisions"][0].update(
            {"rationale": "The proposal confirms the result."}
        ),
        lambda review: review["decisions"][0].update(
            {"rationale": "This triage proposes Evidence Creation."}
        ),
    ],
)
def test_collaborator_review_schema_rejects_authority_claims(mutation):
    schema = json.loads(
        (SCHEMAS / "collaborator-proposal-review.schema.json").read_text()
    )
    review = json.loads((EXAMPLES / "collaborator-proposal-review.json").read_text())
    mutation(review)
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(review, schema)


def test_collaborator_schema_examples_match_service_validator(tmp_path):
    from research_machine.collaboration.proposal import (
        adjudicate_collaborator_proposal,
        create_context_snapshot,
        validate_collaborator_proposal,
    )

    proposal_schema = json.loads(
        (SCHEMAS / "collaborator-proposal.schema.json").read_text()
    )
    proposal_record_schema = json.loads(
        (SCHEMAS / "collaborator-proposal-record.schema.json").read_text()
    )
    review_schema = json.loads(
        (SCHEMAS / "collaborator-proposal-review.schema.json").read_text()
    )
    review_record_schema = json.loads(
        (SCHEMAS / "collaborator-proposal-review-record.schema.json").read_text()
    )
    context = {
        "context_version": 1,
        "purpose": "Stress-test the design.",
        "dataset_inventory": build_dataset_inventory([], []),
        "scientific_constraints": [
            "Treat supplied material as scoped context, not established fact.",
            "Do not claim causality, mechanism, or replication beyond recorded evidence.",
            "Do not authorize collection, protocol freeze, data registration, evidence recording, or other canonical action.",
        ],
        "write_boundary": {
            "context_is_read_only": True,
            "provider_required": False,
            "canonical_changes_require": [
                "research inquiry/question/claim/hypothesis/protocol/dataset/run/evidence commands",
                "applicable human review and protocol-freeze gates",
            ],
        },
        "context_reference_index": [],
    }
    context_result = create_context_snapshot(context, tmp_path / "context")
    proposal = json.loads((EXAMPLES / "collaborator-proposal.json").read_text())
    proposal["context_sha256"] = context_result["context_sha256"]
    jsonschema.validate(proposal, proposal_schema)
    proposal_path = tmp_path / "proposal.json"
    proposal_path.write_text(json.dumps(proposal), encoding="utf-8")
    proposal_result = validate_collaborator_proposal(
        Path(context_result["context_file"]),
        context_result["context_sha256"],
        proposal_path,
        tmp_path / "validated",
    )

    review = json.loads((EXAMPLES / "collaborator-proposal-review.json").read_text())
    review["proposal_record_sha256"] = proposal_result["record_sha256"]
    jsonschema.validate(review, review_schema)
    review_path = tmp_path / "review.json"
    review_path.write_text(json.dumps(review), encoding="utf-8")
    review_result = adjudicate_collaborator_proposal(
        Path(proposal_result["record_file"]),
        proposal_result["record_sha256"],
        review_path,
        tmp_path / "reviewed",
    )
    assert proposal_result["status"] == "pending_human_review"
    assert proposal_result["canonical_writes_performed"] is False
    assert proposal_result["model_invoked_by_faraday"] is False
    proposal_record = json.loads(Path(proposal_result["record_file"]).read_text())
    jsonschema.validate(proposal_record, proposal_record_schema)
    assert proposal_record["status"] == "pending_human_review"
    assert proposal_record["proposal"]["suggestions"][0]["authority"] == "review_only"
    assert proposal_record["canonical_writes_performed"] is False
    assert proposal_record["model_invoked_by_faraday"] is False
    assert proposal_record["scientific_evidence_eligible"] is False
    assert review_result["status"] == "reviewed_requires_manual_domain_action"
    assert review_result["advanced_suggestion_count"] == 1
    assert review_result["canonical_writes_performed"] is False
    review_record = json.loads(Path(review_result["record_file"]).read_text())
    jsonschema.validate(review_record, review_record_schema)
    assert review_record["advanced_suggestions"] == [
        {
            "suggestion_id": "suggestion-1",
            "domain_route": "design.revise",
            "suggestion_sha256": review_record["reviewed_suggestions"][0][
                "suggestion_sha256"
            ],
            "manual_domain_review_required": True,
            "canonical_writes_performed": False,
            "scientific_evidence_eligible": False,
        }
    ]


@pytest.mark.parametrize(
    "mutation",
    [
        lambda record: record["advanced_suggestions"][0].pop("suggestion_sha256"),
        lambda record: record["advanced_suggestions"][0].update(
            {"scientific_evidence_eligible": True}
        ),
        lambda record: record.update({"canonical_writes_performed": True}),
        lambda record: record.update(
            {"conclusion_ceiling": "This review authorizes the design revision."}
        ),
        lambda record: record["review"]["decisions"][0].update(
            {"disposition": "defer", "domain_route": "design.revise"}
        ),
        lambda record: record["reviewed_suggestions"][0].update(
            {"disposition": "reject", "domain_route": "design.revise"}
        ),
        lambda record: record["reviewed_suggestions"][0].update(
            {
                "disposition": "reject",
                "domain_route": "none",
                "manual_domain_review_required": True,
            }
        ),
        lambda record: record["reviewed_suggestions"][0]["suggestion"].update(
            {"kind": "question"}
        ),
        lambda record: record["reviewed_suggestions"][0]["suggestion"].update(
            {"kind": "hypothesis"}
        ),
        lambda record: record["reviewed_suggestions"][0]["suggestion"].update(
            {"kind": "next_action"}
        ),
    ],
)
def test_collaborator_review_record_schema_keeps_advanced_triage_bounded(
    tmp_path, mutation
):
    from research_machine.collaboration.proposal import (
        adjudicate_collaborator_proposal,
        create_context_snapshot,
        validate_collaborator_proposal,
    )

    proposal_schema = json.loads(
        (SCHEMAS / "collaborator-proposal.schema.json").read_text()
    )
    review_schema = json.loads(
        (SCHEMAS / "collaborator-proposal-review.schema.json").read_text()
    )
    review_record_schema = json.loads(
        (SCHEMAS / "collaborator-proposal-review-record.schema.json").read_text()
    )
    context = {
        "context_version": 1,
        "purpose": "Stress-test the design.",
        "dataset_inventory": build_dataset_inventory([], []),
        "scientific_constraints": [
            "Treat supplied material as scoped context, not established fact.",
            "Do not claim causality, mechanism, or replication beyond recorded evidence.",
            "Do not authorize collection, protocol freeze, data registration, evidence recording, or other canonical action.",
        ],
        "write_boundary": {
            "context_is_read_only": True,
            "provider_required": False,
            "canonical_changes_require": [
                "research inquiry/question/claim/hypothesis/protocol/dataset/run/evidence commands",
                "applicable human review and protocol-freeze gates",
            ],
        },
        "context_reference_index": [],
    }
    context_result = create_context_snapshot(context, tmp_path / "context")
    proposal = json.loads((EXAMPLES / "collaborator-proposal.json").read_text())
    proposal["context_sha256"] = context_result["context_sha256"]
    jsonschema.validate(proposal, proposal_schema)
    proposal_path = tmp_path / "proposal.json"
    proposal_path.write_text(json.dumps(proposal), encoding="utf-8")
    proposal_result = validate_collaborator_proposal(
        Path(context_result["context_file"]),
        context_result["context_sha256"],
        proposal_path,
        tmp_path / "validated",
    )
    review = json.loads((EXAMPLES / "collaborator-proposal-review.json").read_text())
    review["proposal_record_sha256"] = proposal_result["record_sha256"]
    jsonschema.validate(review, review_schema)
    review_path = tmp_path / "review.json"
    review_path.write_text(json.dumps(review), encoding="utf-8")
    review_result = adjudicate_collaborator_proposal(
        Path(proposal_result["record_file"]),
        proposal_result["record_sha256"],
        review_path,
        tmp_path / "reviewed",
    )
    review_record = json.loads(Path(review_result["record_file"]).read_text())
    mutation(review_record)

    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(review_record, review_record_schema)


@pytest.mark.parametrize(
    "mutation",
    [
        lambda record: record.update({"status": "accepted"}),
        lambda record: record.update({"model_invoked_by_faraday": True}),
        lambda record: record["proposal"]["suggestions"][0].update(
            {"authority": "canonical_write"}
        ),
        lambda record: record["context_write_boundary"].update(
            {"provider_required": True}
        ),
        lambda record: record.update(
            {"conclusion_ceiling": "This proposal authorizes a protocol amendment."}
        ),
    ],
)
def test_collaborator_proposal_record_schema_keeps_pending_review_bounded(
    tmp_path, mutation
):
    from research_machine.collaboration.proposal import (
        create_context_snapshot,
        validate_collaborator_proposal,
    )

    proposal_schema = json.loads(
        (SCHEMAS / "collaborator-proposal.schema.json").read_text()
    )
    proposal_record_schema = json.loads(
        (SCHEMAS / "collaborator-proposal-record.schema.json").read_text()
    )
    context = {
        "context_version": 1,
        "purpose": "Stress-test the design.",
        "dataset_inventory": build_dataset_inventory([], []),
        "scientific_constraints": [
            "Treat supplied material as scoped context, not established fact.",
            "Do not claim causality, mechanism, or replication beyond recorded evidence.",
            "Do not authorize collection, protocol freeze, data registration, evidence recording, or other canonical action.",
        ],
        "write_boundary": {
            "context_is_read_only": True,
            "provider_required": False,
            "canonical_changes_require": [
                "research inquiry/question/claim/hypothesis/protocol/dataset/run/evidence commands",
                "applicable human review and protocol-freeze gates",
            ],
        },
        "context_reference_index": [],
    }
    context_result = create_context_snapshot(context, tmp_path / "context")
    proposal = json.loads((EXAMPLES / "collaborator-proposal.json").read_text())
    proposal["context_sha256"] = context_result["context_sha256"]
    jsonschema.validate(proposal, proposal_schema)
    proposal_path = tmp_path / "proposal.json"
    proposal_path.write_text(json.dumps(proposal), encoding="utf-8")
    proposal_result = validate_collaborator_proposal(
        Path(context_result["context_file"]),
        context_result["context_sha256"],
        proposal_path,
        tmp_path / "validated",
    )
    proposal_record = json.loads(Path(proposal_result["record_file"]).read_text())
    mutation(proposal_record)

    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(proposal_record, proposal_record_schema)


def test_general_addon_manifest_matches_published_schema():
    from research_machine.addons.models import AddonManifest, InstrumentAdapter

    schema = json.loads((SCHEMAS / "addon-manifest.schema.json").read_text())
    jsonschema.validate(MANIFEST.describe(), schema)
    unsafe = MANIFEST.describe()
    unsafe["methods"][0]["maximum_claim_ceiling"] = " "
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(unsafe, schema)
    unsafe = MANIFEST.describe()
    unsafe["methods"][0]["randomness_control"] = "ambient_rng"
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(unsafe, schema)
    unsafe = MANIFEST.describe()
    unsafe["methods"][0]["randomness_control"] = "seeded"
    unsafe["methods"][0]["required_spec_fields"] = ["columns"]
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(unsafe, schema)
    instrument_manifest = AddonManifest(
        "instrument_fixture", "Instrument fixture", "1", "test", "Fixture",
        instrument_adapters=(InstrumentAdapter(
            "fixture_reader", "Fixture reader", "Fixture metadata reader",
            ("application/octet-stream",), ("device_id",), lambda raw, config: {},
            ("timezone",),
        ),),
    ).describe()
    jsonschema.validate(instrument_manifest, schema)
    instrument_manifest["instrument_adapters"][0]["authority"] = "passes_quality_gates"
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(instrument_manifest, schema)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("capabilities", ["csv-ingestion "]),
        ("protocol_kinds", ["observational "]),
        ("dataset_media_types", ["text/csv "]),
    ],
)
def test_addon_manifest_schema_rejects_padded_metadata_handles(field, value):
    schema = json.loads((SCHEMAS / "addon-manifest.schema.json").read_text())
    manifest = MANIFEST.describe()
    manifest[field] = value
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(manifest, schema)


@pytest.mark.parametrize(
    ("path", "value"),
    [
        (("name",), " General Science Toolkit"),
        (("version",), "8.0.0 "),
        (("discipline",), " cross-disciplinary"),
        (("description",), "Deterministic toolkit. "),
        (("documentation",), " docs/addons.md"),
        (("methods", 0, "title"), " Descriptive summary"),
        (("methods", 0, "description"), "Summarize values. "),
        (("methods", 0, "maximum_claim_ceiling"), "Description only. "),
        (("instrument_adapters", 0, "title"), " Fixture reader"),
        (("instrument_adapters", 0, "description"), "Fixture reader. "),
    ],
)
def test_addon_manifest_schema_rejects_padded_metadata_text(path, value):
    from research_machine.addons.models import AddonManifest, InstrumentAdapter

    schema = json.loads((SCHEMAS / "addon-manifest.schema.json").read_text())
    manifest = AddonManifest(
        "instrument_fixture", "Instrument fixture", "1", "test", "Fixture",
        methods=MANIFEST.methods,
        instrument_adapters=(InstrumentAdapter(
            "fixture_reader", "Fixture reader", "Fixture metadata reader",
            ("application/octet-stream",), ("device_id",), lambda raw, config: {},
            ("timezone",),
        ),),
        capabilities=MANIFEST.capabilities,
        protocol_kinds=MANIFEST.protocol_kinds,
        dataset_media_types=MANIFEST.dataset_media_types,
        documentation="docs/addons.md",
    ).describe()
    target = manifest
    for part in path[:-1]:
        target = target[part]
    target[path[-1]] = value
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(manifest, schema)
