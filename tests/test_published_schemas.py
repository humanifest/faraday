"""Published schema syntax and representative synthetic command compatibility."""
import json
from pathlib import Path

import pytest

jsonschema = pytest.importorskip("jsonschema")
SCHEMAS = Path(__file__).resolve().parents[1] / "schemas"
EXAMPLES = Path(__file__).resolve().parents[1] / "examples"
from research_machine.addons.general_science import MANIFEST


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


def test_empirical_protocol_command_matches_published_schema():
    from test_ethics_gate import _human_protocol
    from research_machine.interfaces.cli import _PROTOCOL_FIELDS
    protocol = _human_protocol(human_subjects=False).to_dict()
    command = {key: value for key, value in protocol.items() if key in _PROTOCOL_FIELDS}
    schema = json.loads((SCHEMAS / "protocol-command.schema.json").read_text())
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
        "lane_id": "science",
    }
    command = {"candidates": [candidate]}
    if schema_name == "next-action-portfolio.schema.json":
        command["lanes"] = [{"lane_id": "science", "title": "Science"}]
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(command, schema)


@pytest.mark.parametrize(
    ("schema_name", "example_name"),
    [
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


def test_collaborator_schema_examples_match_service_validator(tmp_path):
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
    context = {
        "context_version": 1,
        "purpose": "Stress-test the design.",
        "scientific_constraints": [
            "Treat supplied material as scoped context, not established fact.",
            "Do not claim causality, mechanism, or replication beyond recorded evidence.",
            "Do not authorize collection, protocol freeze, data registration, evidence recording, or other canonical action.",
        ],
        "write_boundary": {
            "context_is_read_only": True,
            "provider_required": False,
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
    assert review_result["status"] == "reviewed_requires_manual_domain_action"
    assert review_result["advanced_suggestion_count"] == 1
    assert review_result["canonical_writes_performed"] is False


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
