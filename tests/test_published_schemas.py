"""Published schema syntax and representative synthetic command compatibility."""
import json
from pathlib import Path

import pytest

jsonschema = pytest.importorskip("jsonschema")
SCHEMAS = Path(__file__).resolve().parents[1] / "schemas"
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


def test_general_addon_manifest_matches_published_schema():
    from research_machine.addons.models import AddonManifest, InstrumentAdapter

    schema = json.loads((SCHEMAS / "addon-manifest.schema.json").read_text())
    jsonschema.validate(MANIFEST.describe(), schema)
    unsafe = MANIFEST.describe()
    unsafe["methods"][0]["maximum_claim_ceiling"] = " "
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
