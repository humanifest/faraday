from __future__ import annotations

import json
from pathlib import Path

import pytest

from research_machine.addons.models import AddonManifest, AnalysisMethod, InstrumentAdapter
from research_machine.addons.general_science import (
    descriptive_summary,
    independent_mean_difference_ci,
    pearson_correlation,
    permutation_mean_difference,
)
from research_machine.addons.registry import (
    AddonRegistry,
    default_registry,
    load_local_addons,
)
from research_machine.domain.errors import ValidationError
from research_machine.interfaces.cli import main


def test_receipt_binds_bytes_analyzed_despite_source_mutation(tmp_path: Path) -> None:
    """Synthetic fixture: an executor changes both the path and its row list."""
    import hashlib
    from research_machine.addons.execution import execute_analysis
    from research_machine.addons.models import AnalysisMethod

    data = tmp_path / "data.csv"
    original = b"value\r\n1\r\n2\r\n"
    data.write_bytes(original)
    spec = tmp_path / "spec.json"
    spec.write_text(json.dumps({"method": "mutating_fixture", "claim_ceiling": "Fixture only."}))

    def runner(spec, rows):
        values = [row["value"] for row in rows]
        data.write_bytes(b"value\n999\n")
        rows.clear()
        return {"values": values}

    registry = AddonRegistry()
    registry.register(AddonManifest(
        "snapshot_fixture", "Snapshot fixture", "1", "test", "Synthetic regression fixture",
        methods=(AnalysisMethod("mutating_fixture", "Fixture", "Fixture only", (), runner),),
    ))
    execution = execute_analysis(
        registry=registry, spec_path=spec, data_path=data, output_dir=tmp_path / "output",
    )
    assert execution["result"]["result"] == {"values": ["1", "2"]}
    receipt = execution["receipt"]
    assert execution["result"]["maximum_inference_level"] == "computation_only"
    assert receipt["maximum_inference_level"] == "computation_only"
    assert receipt["input"]["sha256"] == hashlib.sha256(original).hexdigest()
    assert receipt["input"]["sha256"] != hashlib.sha256(data.read_bytes()).hexdigest()
    assert receipt["input"]["size_bytes"] == len(original)
    assert receipt["input"]["row_count"] == 2
    assert receipt["scientific_evidence_eligible"] is False


def _result(capsys) -> object:
    captured = capsys.readouterr()
    assert captured.err == ""
    payload = json.loads(captured.out)
    assert payload["ok"] is True
    return payload["result"]


def test_pearson_correlation_requires_canonical_column_handles() -> None:
    """Synthetic fixture: padded handles must not be silently rewritten."""
    with pytest.raises(ValidationError, match="pearson_correlation x_column must be canonical"):
        pearson_correlation(
            {"x_column": " x ", "y_column": "y"},
            [{"x": "1", "y": "2"}, {"x": "2", "y": "4"}, {"x": "3", "y": "6"}],
        )


def test_pearson_correlation_rejects_duplicate_columns() -> None:
    """Synthetic fixture: a self-correlation request remains invalid."""
    with pytest.raises(ValidationError, match="distinct x_column and y_column"):
        pearson_correlation(
            {"x_column": "x", "y_column": "x"},
            [{"x": "1"}, {"x": "2"}, {"x": "3"}],
        )


def test_pearson_correlation_rejects_noncanonical_columns_before_duplicates() -> None:
    with pytest.raises(ValidationError, match="pearson_correlation y_column must be canonical"):
        pearson_correlation(
            {"x_column": "x", "y_column": " x "},
            [{"x": "1"}, {"x": "2"}, {"x": "3"}],
        )


def test_pearson_correlation_runs_with_canonical_handles() -> None:
    result = pearson_correlation(
        {"x_column": "x", "y_column": "y"},
        [{"x": "1", "y": "2"}, {"x": "2", "y": "4"}, {"x": "3", "y": "6"}],
    )

    assert result["n"] == 3
    assert result["pearson_r"] == pytest.approx(1.0)
    assert result["missing_pairs"] == 0


@pytest.mark.parametrize("case", ["unique", "duplicate", "missing", "unsupported_method"])
def test_unit_identity_check_through_cli(tmp_path, capsys, case):
    """Synthetic identity fixtures verify the public execution boundary."""
    import hashlib
    data = tmp_path / "synthetic.csv"
    last_id = {"duplicate": "u0", "missing": ""}.get(case, "u3")
    content = f"unit,group,outcome\nu0,a,1\nu1,a,2\nu2,b,4\n{last_id},b,5\n"
    data.write_text(content)
    spec = tmp_path / "spec.json"
    spec.write_text(json.dumps({
            "method": "pearson_correlation" if case == "unsupported_method" else "independent_mean_difference_ci",
        "claim_ceiling": "Synthetic fixture only", "outcome_column": "outcome",
        "group_column": "group", "groups": ["a", "b"], "unit_column": "unit",
        "study_design": "independent_groups", "seed": 1, "bootstrap_resamples": 1000,
    }))
    output = tmp_path / "output"
    code = main(["--json", "analysis", "run", "--spec-file", str(spec),
                 "--data-file", str(data), "--output", str(output)])
    if case == "unique":
        assert code == 0
        execution = _result(capsys)
        assert execution["result"]["result"]["independent_unit_check"]["status"] == "unique_identifiers"
        assert execution["receipt"]["input"]["sha256"] == hashlib.sha256(content.encode()).hexdigest()
        assert execution["receipt"]["scientific_evidence_eligible"] is False
    else:
        assert code == 2
        error = capsys.readouterr().err
        assert ("silently ignored" if case == "unsupported_method" else "independent-unit identifier") in error
        assert not output.exists()
    assert data.read_text() == content


@pytest.mark.parametrize("field", ["claim_ceiling", "analysis_id", "purpose", "parameters"])
def test_addon_specification_mutation_fails_before_publication(tmp_path: Path, field) -> None:
    from research_machine.addons.execution import execute_analysis
    from research_machine.addons.models import AnalysisMethod

    data = tmp_path / "synthetic.csv"
    data.write_text("x\n1\n2\n")
    spec_path = tmp_path / "spec.json"
    original = json.dumps({"method": "mutation_fixture", "claim_ceiling": "Fixture only",
                           "analysis_id": "original", "purpose": "test",
                           "parameters": {"thresholds": [1, 2]}})
    spec_path.write_text(original)

    def runner(spec, rows):
        if field == "parameters":
            spec[field]["thresholds"].append(3)
        else:
            spec[field] = "changed"
        return {"estimate": 1}

    registry = AddonRegistry()
    registry.register(AddonManifest(
        "mutation_fixture", "Mutation fixture", "1", "test", "Synthetic fixture",
        methods=(AnalysisMethod("mutation_fixture", "Fixture", "Fixture", (), runner),),
    ))
    output = tmp_path / "output"
    with pytest.raises(ValidationError, match="modified its committed specification"):
        execute_analysis(registry=registry, spec_path=spec_path, data_path=data, output_dir=output)
    assert not output.exists()
    assert spec_path.read_text() == original


@pytest.mark.parametrize("invalid", [float("nan"), float("inf"), -float("inf"), {1, 2}])
def test_invalid_numeric_or_non_json_output_is_not_published(tmp_path: Path, invalid) -> None:
    from research_machine.addons.execution import execute_analysis
    from research_machine.addons.models import AnalysisMethod

    data = tmp_path / "synthetic.csv"
    data.write_text("x\n1\n2\n")
    spec = tmp_path / "spec.json"
    spec.write_text(json.dumps({"method": "invalid_fixture", "claim_ceiling": "Fixture only"}))

    def runner(spec, rows):
        return {"nested": [{"estimate": invalid}]}

    registry = AddonRegistry()
    registry.register(AddonManifest(
        "invalid_fixture", "Invalid fixture", "1", "test", "Synthetic fixture",
        methods=(AnalysisMethod("invalid_fixture", "Fixture", "Fixture", (), runner),),
    ))
    output = tmp_path / "output"
    with pytest.raises(ValidationError, match="finite numeric values"):
        execute_analysis(registry=registry, spec_path=spec, data_path=data, output_dir=output)
    assert not output.exists()
    assert data.read_text() == "x\n1\n2\n"


def test_default_registry_exposes_general_and_domain_addons() -> None:
    registry = default_registry(include_installed=False)
    assert [item.addon_id for item in registry.list()] == ["general_science"]
    addon, method = registry.resolve_method("permutation_mean_difference")
    assert addon.addon_id == "general_science"
    assert "seed" in method.required_spec_fields
    assert method.maximum_inference_level == "design_conditional_effect"


def test_descriptive_summary_requires_canonical_requested_columns() -> None:
    with pytest.raises(ValidationError, match="descriptive_summary column must be canonical"):
        descriptive_summary({"columns": [" x "]}, [{"x": "1"}, {"x": ""}])


def test_descriptive_summary_rejects_noncanonical_columns_before_duplicates() -> None:
    with pytest.raises(ValidationError, match="descriptive_summary column must be canonical"):
        descriptive_summary({"columns": ["x", " x "]}, [{"x": "1"}])


def test_descriptive_summary_rejects_duplicate_columns() -> None:
    with pytest.raises(ValidationError, match="duplicates"):
        descriptive_summary({"columns": ["x", "x"]}, [{"x": "1"}])


@pytest.mark.parametrize(("field", "message"), [
    ("outcome_column", "permutation_mean_difference outcome_column must be canonical"),
    ("group_column", "permutation_mean_difference group_column must be canonical"),
    ("groups", "group label must be canonical"),
    ("unit_column", "permutation_mean_difference unit_column must be canonical"),
    ("row_group", "row group label must be canonical"),
])
def test_permutation_mean_difference_requires_canonical_comparison_handles(field, message) -> None:
    """Synthetic fixture: padded comparison handles cannot enter result provenance."""
    spec = {
        "outcome_column": "outcome",
        "group_column": "group",
        "groups": ["treatment", "control"],
        "permutations": 100,
        "seed": 7,
        "missing_data_policy": "complete_case",
        "unit_column": "unit",
    }
    rows = [
        {"unit": "u1", "group": "treatment", "outcome": "4"},
        {"unit": "u2", "group": "treatment", "outcome": "5"},
        {"unit": "u3", "group": "control", "outcome": "1"},
        {"unit": "u4", "group": "control", "outcome": "2"},
        {"unit": "u5", "group": "treatment", "outcome": ""},
    ]
    if field == "groups":
        spec[field] = [" treatment ", "control"]
    elif field == "row_group":
        rows[-1]["group"] = " treatment "
    else:
        spec[field] = f" {spec[field]} "
    with pytest.raises(ValidationError, match=message):
        permutation_mean_difference(spec, rows)


def test_permutation_mean_difference_runs_with_canonical_comparison_handles() -> None:
    result = permutation_mean_difference(
        {
            "outcome_column": "outcome",
            "group_column": "group",
            "groups": ["treatment", "control"],
            "permutations": 100,
            "seed": 7,
            "missing_data_policy": "complete_case",
            "unit_column": "unit",
        },
        [
            {"unit": "u1", "group": "treatment", "outcome": "4"},
            {"unit": "u2", "group": "treatment", "outcome": "5"},
            {"unit": "u3", "group": "control", "outcome": "1"},
            {"unit": "u4", "group": "control", "outcome": "2"},
            {"unit": "u5", "group": "treatment", "outcome": ""},
        ],
    )

    assert result["groups"] == ["treatment", "control"]
    assert result["n_by_group"] == {"treatment": 2, "control": 2}
    assert result["independent_unit_check"]["column"] == "unit"
    assert result["exclusion_report"]["excluded_by_group"] == {"treatment": 1, "control": 0}
    assert result["missing_rows"] == 1


def test_independent_mean_difference_rejects_noncanonical_handles_before_duplicates() -> None:
    """Synthetic fixture: whitespace cannot enter executable column handles."""
    with pytest.raises(ValidationError, match="group_column must be canonical"):
        independent_mean_difference_ci(
            {
                "study_design": "independent_groups",
                "outcome_column": "value",
                "group_column": " value ",
                "groups": ["a", "b"],
                "seed": 1,
                "bootstrap_resamples": 1000,
            },
            [{"value": "1"}, {"value": "2"}, {"value": "3"}, {"value": "4"}],
        )


def test_registry_rejects_duplicate_addon_ids() -> None:
    registry = AddonRegistry()
    manifest = AddonManifest("example", "Example", "1", "any", "Example")
    registry.register(manifest)
    with pytest.raises(ValidationError, match="duplicate add-on id"):
        registry.register(manifest)


@pytest.mark.parametrize("ceiling", ["", "   ", None, False])
def test_registry_rejects_missing_method_ceiling(ceiling) -> None:
    registry = AddonRegistry()
    method = AnalysisMethod("unsafe", "Unsafe", "Fixture", (), lambda spec, rows: {}, ceiling)
    with pytest.raises(ValidationError, match="maximum_claim_ceiling"):
        registry.register(AddonManifest("unsafe", "Unsafe", "1", "test", "Fixture", methods=(method,)))


def test_registry_rejects_unknown_machine_readable_inference_ceiling() -> None:
    registry = AddonRegistry()
    method = AnalysisMethod(
        "unsafe", "Unsafe", "Fixture", (), lambda spec, rows: {},
        maximum_inference_level="causal_proof",
    )
    with pytest.raises(ValidationError, match="maximum_inference_level"):
        registry.register(
            AddonManifest("unsafe", "Unsafe", "1", "test", "Fixture", methods=(method,))
        )


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("name", " ", "name"),
        ("version", None, "version"),
        ("discipline", "", "discipline"),
        ("description", False, "description"),
    ],
)
def test_registry_rejects_missing_manifest_metadata(field, value, message) -> None:
    registry = AddonRegistry()
    kwargs = {
        "addon_id": "unsafe",
        "name": "Unsafe",
        "version": "1",
        "discipline": "test",
        "description": "Fixture",
    }
    kwargs[field] = value
    with pytest.raises(ValidationError, match=message):
        registry.register(AddonManifest(**kwargs))


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("name", " Unsafe", "add-on name"),
        ("version", "1 ", "add-on version"),
        ("discipline", " test", "add-on discipline"),
        ("description", "Fixture ", "add-on description"),
        ("documentation", " docs/addons.md", "add-on documentation"),
    ],
)
def test_registry_rejects_padded_manifest_metadata_text(field, value, message) -> None:
    registry = AddonRegistry()
    kwargs = {
        "addon_id": "unsafe",
        "name": "Unsafe",
        "version": "1",
        "discipline": "test",
        "description": "Fixture",
        "documentation": "docs/addons.md",
    }
    kwargs[field] = value
    with pytest.raises(ValidationError, match=message):
        registry.register(AddonManifest(**kwargs))


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("capabilities", ("csv-ingestion ",), "capabilities"),
        ("capabilities", ("csv-ingestion", "csv-ingestion"), "capabilities"),
        ("protocol_kinds", ("observational ",), "protocol_kinds"),
        ("protocol_kinds", ("observational", "observational"), "protocol_kinds"),
        ("dataset_media_types", ("text/csv ",), "dataset_media_types"),
        ("dataset_media_types", ("text/csv", "text/csv"), "dataset_media_types"),
    ],
)
def test_registry_rejects_noncanonical_manifest_metadata_handles(
    field, value, message
) -> None:
    registry = AddonRegistry()
    kwargs = {
        "capabilities": ("csv-ingestion",),
        "protocol_kinds": ("observational",),
        "dataset_media_types": ("text/csv",),
    }
    kwargs[field] = value
    with pytest.raises(ValidationError, match=message):
        registry.register(
            AddonManifest(
                "unsafe",
                "Unsafe",
                "1",
                "test",
                "Fixture",
                **kwargs,
            )
        )


@pytest.mark.parametrize(
    "required_fields",
    [("outcome_column ",), ("outcome_column", "outcome_column")],
)
def test_registry_rejects_noncanonical_method_required_spec_fields(
    required_fields,
) -> None:
    registry = AddonRegistry()
    method = AnalysisMethod(
        "unsafe", "Unsafe", "Fixture", required_fields, lambda spec, rows: {},
    )
    with pytest.raises(ValidationError, match="required_spec_fields"):
        registry.register(
            AddonManifest("unsafe", "Unsafe", "1", "test", "Fixture", methods=(method,))
        )


def test_registry_rejects_required_spec_fields_unknown_to_execution() -> None:
    registry = AddonRegistry()
    method = AnalysisMethod(
        "unsafe", "Unsafe", "Fixture", ("domain_specific_threshold",), lambda spec, rows: {},
    )
    with pytest.raises(ValidationError, match="not supported analysis specification fields"):
        registry.register(
            AddonManifest("unsafe", "Unsafe", "1", "test", "Fixture", methods=(method,))
        )


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("title", " Unsafe", "method title"),
        ("description", "Fixture ", "method description"),
        ("maximum_claim_ceiling", " Calculation only. ", "method maximum_claim_ceiling"),
    ],
)
def test_registry_rejects_padded_method_metadata_text(field, value, message) -> None:
    registry = AddonRegistry()
    kwargs = {
        "method_id": "unsafe",
        "title": "Unsafe",
        "description": "Fixture",
        "required_spec_fields": (),
        "runner": lambda spec, rows: {},
        "maximum_claim_ceiling": "Calculation only.",
    }
    kwargs[field] = value
    method = AnalysisMethod(**kwargs)
    with pytest.raises(ValidationError, match=message):
        registry.register(
            AddonManifest("unsafe", "Unsafe", "1", "test", "Fixture", methods=(method,))
        )


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("supported_media_types", ("application/json ",), "supported_media_types"),
        ("supported_media_types", ("application/json", "application/json"), "supported_media_types"),
        ("required_config_fields", ("device_id ",), "required_config_fields"),
        ("required_config_fields", ("device_id", "device_id"), "required_config_fields"),
        ("optional_config_fields", (" calibration_id",), "optional_config_fields"),
        ("optional_config_fields", ("calibration_id", "calibration_id"), "optional_config_fields"),
        ("overlap", (), "optional_config_fields"),
    ],
)
def test_registry_rejects_noncanonical_instrument_adapter_contract_fields(
    field, value, message
) -> None:
    registry = AddonRegistry()
    adapter = InstrumentAdapter(
        "fixture_adapter",
        "Fixture adapter",
        "Inspects synthetic fixture bytes.",
        ("application/json",),
        ("device_id",),
        lambda source, config: {},
        optional_config_fields=("calibration_id",),
    )
    if field == "overlap":
        adapter = InstrumentAdapter(
            adapter.adapter_id,
            adapter.title,
            adapter.description,
            adapter.supported_media_types,
            adapter.required_config_fields,
            adapter.inspector,
            optional_config_fields=("device_id",),
        )
    else:
        adapter = InstrumentAdapter(
            adapter.adapter_id,
            adapter.title,
            adapter.description,
            value if field == "supported_media_types" else adapter.supported_media_types,
            value if field == "required_config_fields" else adapter.required_config_fields,
            adapter.inspector,
            optional_config_fields=(
                value if field == "optional_config_fields"
                else adapter.optional_config_fields
            ),
        )

    with pytest.raises(ValidationError, match=message):
        registry.register(AddonManifest(
            "adapter_fixture", "Adapter fixture", "1", "test", "Fixture",
            instrument_adapters=(adapter,),
        ))


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("title", " Fixture adapter", "instrument adapter title"),
        (
            "description",
            "Inspects synthetic fixture bytes. ",
            "instrument adapter description",
        ),
    ],
)
def test_registry_rejects_padded_instrument_adapter_metadata_text(
    field, value, message
) -> None:
    registry = AddonRegistry()
    kwargs = {
        "adapter_id": "fixture_adapter",
        "title": "Fixture adapter",
        "description": "Inspects synthetic fixture bytes.",
        "supported_media_types": ("application/json",),
        "required_config_fields": ("device_id",),
        "inspector": lambda source, config: {},
    }
    kwargs[field] = value
    adapter = InstrumentAdapter(**kwargs)
    with pytest.raises(ValidationError, match=message):
        registry.register(AddonManifest(
            "adapter_fixture", "Adapter fixture", "1", "test", "Fixture",
            instrument_adapters=(adapter,),
        ))


def test_cli_lists_addons_without_initializing_workspace(tmp_path: Path, capsys) -> None:
    workspace = tmp_path / "not-created"
    assert main(["--workspace", str(workspace), "--json", "addon", "list"]) == 0
    values = _result(capsys)
    assert {item["addon_id"] for item in values} >= {"general_science"}
    assert not workspace.exists()


def test_general_analysis_is_deterministic_and_non_evidentiary(
    tmp_path: Path, capsys
) -> None:
    data = tmp_path / "observations.csv"
    data.write_text("group,outcome\ncontrol,1\ncontrol,2\ntreatment,4\ntreatment,5\n")
    spec = tmp_path / "analysis.json"
    spec.write_text(
        json.dumps(
            {
                "method": "permutation_mean_difference",
                "analysis_id": "registered-comparison-v1",
                "outcome_column": "outcome",
                "group_column": "group",
                "groups": ["treatment", "control"],
                "permutations": 500,
                "seed": 8128,
                "missing_data_policy": "complete_case",
                "claim_ceiling": "Difference in group means in this dataset only.",
            }
        )
    )
    first = tmp_path / "first"
    second = tmp_path / "second"
    common = ["--workspace", str(tmp_path / "unused"), "--json", "analysis", "run", "--spec-file", str(spec), "--data-file", str(data)]
    assert main([*common, "--output", str(first)]) == 0
    first_result = _result(capsys)
    assert main([*common, "--output", str(second)]) == 0
    second_result = _result(capsys)
    assert first_result["result"] == second_result["result"]
    assert first_result["result"]["missing_data_policy"] == "complete_case"
    assert first_result["receipt"]["scientific_evidence_eligible"] is False
    receipt = json.loads((first / "execution-receipt.json").read_text())
    result_bytes = (first / "analysis-result.json").read_bytes()
    import hashlib

    assert receipt["output"]["sha256"] == hashlib.sha256(result_bytes).hexdigest()
    from research_machine.addons.receipt import verify_execution_output

    receipt_hash = hashlib.sha256((first / "execution-receipt.json").read_bytes()).hexdigest()
    assert verify_execution_output(first, receipt_hash)["receipt"]["method"] == "permutation_mean_difference"
    with pytest.raises(ValidationError, match="lowercase SHA-256"):
        verify_execution_output(first, f" {receipt_hash} ")


def test_explicit_local_addon_loads_without_installing_a_package(
    tmp_path: Path, capsys
) -> None:
    addon = tmp_path / "example-addon"
    addon.mkdir()
    (addon / "research_addon.py").write_text(
        """from research_machine.addons import AddonManifest, AnalysisMethod

def count_rows(spec, rows):
    return {"n": len(rows)}

MANIFEST = AddonManifest(
    addon_id="example_domain",
    name="Example domain",
    version="1.0.0",
    discipline="test discipline",
    description="A local test add-on.",
    methods=(AnalysisMethod("count_rows", "Count rows", "Count input rows.", (), count_rows),),
)
""",
        encoding="utf-8",
    )
    registry = load_local_addons(
        default_registry(include_installed=False), [addon]
    )
    assert registry.get("example_domain").name == "Example domain"

    data = tmp_path / "data.csv"
    data.write_text("value\n1\n2\n", encoding="utf-8")
    spec = tmp_path / "spec.json"
    spec.write_text(
        json.dumps({"method": "count_rows", "claim_ceiling": "Row count only."}),
        encoding="utf-8",
    )
    output = tmp_path / "output"
    assert main(
        [
            "--json",
            "--addon-path",
            str(addon),
            "analysis",
            "run",
            "--spec-file",
            str(spec),
            "--data-file",
            str(data),
            "--output",
            str(output),
        ]
    ) == 0
    result = _result(capsys)
    assert result["result"]["result"] == {"n": 2}
    assert result["receipt"]["addon"]["addon_id"] == "example_domain"


def test_local_instrument_adapter_proposes_only_core_hashed_acquisition_metadata(
    tmp_path: Path, capsys
) -> None:
    addon = tmp_path / "instrument-addon"
    addon.mkdir()
    (addon / "research_addon.py").write_text(
        """from research_machine.addons import AddonManifest, InstrumentAdapter

def inspect(source_bytes, config):
    assert source_bytes.startswith(b"DEVICE")
    return {
        "captured_at": config["captured_at"],
        "captured_at_basis": "device_metadata",
        "acquisition_method": "native binary export",
        "instrument_identifier": config["instrument_identifier"],
        "instrument_model": "FixtureScope 1",
        "firmware_version": "1.2.3",
        "native_metadata": {"sample_count": 2},
        "streams": [{
            "stream_id": "stream-main",
            "source_device": config["instrument_identifier"],
            "channel": "main",
            "sample_rate_hz": 256,
            "clock_source": "device clock",
            "start_time": config["captured_at"],
            "clock_drift": {
                "estimate": 0.2,
                "uncertainty": 0.05,
                "unit": "ms",
                "basis": "manufacturer sidecar",
            },
            "missing_intervals": [{
                "start_time": "2026-09-06T12:00:01Z",
                "end_time": "2026-09-06T12:00:02Z",
                "reason": "Dropped packet fixture",
            }],
            "calibration_record": "clock-sync-record-1",
            "quality_flags": ["synthetic-fixture"],
        }],
        "warnings": ["Synthetic adapter fixture"],
    }

MANIFEST = AddonManifest(
    addon_id="fixture_instrument",
    name="Fixture instrument",
    version="1.0.0",
    discipline="test",
    description="Synthetic instrument inspection fixture.",
    instrument_adapters=(InstrumentAdapter(
        "fixture_scope", "Fixture scope", "Read fixture acquisition metadata.",
        ("application/octet-stream",), ("captured_at", "instrument_identifier"), inspect,
    ),),
)
""",
        encoding="utf-8",
    )
    source = tmp_path / "capture.bin"
    source_bytes = b"DEVICE\x00\x01"
    source.write_bytes(source_bytes)
    config = tmp_path / "instrument-config.json"
    config.write_text(json.dumps({
        "captured_at": "2026-09-06T12:00:00Z",
        "instrument_identifier": "scope-fixture-01",
    }))
    output = tmp_path / "inspection"
    assert main([
        "--json", "--addon-path", str(addon), "measurement", "inspect-source",
        "--adapter", "fixture_scope", "--source-file", str(source),
        "--media-type", "application/octet-stream",
        "--config-file", str(config), "--output", str(output),
    ]) == 0
    result = _result(capsys)
    assert result["scientific_evidence_eligible"] is False
    record = json.loads((output / "instrument-inspection.json").read_text())
    import hashlib

    digest = hashlib.sha256(source_bytes).hexdigest()
    assert record["source"]["sha256"] == digest
    assert record["source"]["media_type"] == "application/octet-stream"
    assert record["proposed_raw_source"]["sha256"] == digest
    assert record["adapter"]["authority"] == "acquisition_metadata_proposal_only"
    adapter_source = addon / "research_addon.py"
    assert record["adapter"]["implementation"] == {
        "locator": "research_addon.py",
        "sha256": hashlib.sha256(adapter_source.read_bytes()).hexdigest(),
        "size_bytes": adapter_source.stat().st_size,
    }
    assert record["temporal_metadata"] == {
        "status": "proposed_unverified",
        "stream_count": 1,
        "limitations": [
            "Stream metadata is an adapter proposal bound to raw bytes and adapter code; it is not calibration, synchronization validation, or custody approval.",
            "Clock-drift estimates and uncertainties remain asserted metadata until a separate quality gate verifies timing against the frozen protocol.",
            "Missing intervals are preserved as acquisition limitations and must be handled by later custody or analysis gates.",
        ],
    }
    assert record["streams"] == [{
        "stream_id": "stream-main",
        "source_device": "scope-fixture-01",
        "channel": "main",
        "sample_rate_hz": 256,
        "clock_source": "device clock",
        "start_time": "2026-09-06T12:00:00Z",
        "clock_drift": {
            "estimate": 0.2,
            "uncertainty": 0.05,
            "unit": "ms",
            "basis": "manufacturer sidecar",
        },
        "missing_intervals": [{
            "start_time": "2026-09-06T12:00:01Z",
            "end_time": "2026-09-06T12:00:02Z",
            "reason": "Dropped packet fixture",
        }],
        "calibration_record": "clock-sync-record-1",
        "quality_flags": ["synthetic-fixture"],
        "raw_file_sha256": digest,
        "conversion_code_sha256": hashlib.sha256(adapter_source.read_bytes()).hexdigest(),
    }]
    assert record["authorized_actions"] == []
    assert "No calibration" in record["conclusion_ceiling"]
    unsupported_output = tmp_path / "unsupported-media-inspection"
    assert main([
        "--json", "--addon-path", str(addon), "measurement", "inspect-source",
        "--adapter", "fixture_scope", "--source-file", str(source),
        "--media-type", "text/csv", "--config-file", str(config),
        "--output", str(unsupported_output),
    ]) == 2
    assert "does not support media type text/csv" in capsys.readouterr().err
    assert not unsupported_output.exists()
    record_file = output / "instrument-inspection.json"
    assert main([
        "--json", "--addon-path", str(addon), "measurement",
        "verify-source-inspection", "--adapter", "fixture_scope",
        "--source-file", str(source), "--config-file", str(config),
        "--media-type", "application/octet-stream",
        "--record-file", str(record_file),
        "--expected-record-sha256", result["inspection_sha256"],
    ]) == 0
    verified = _result(capsys)
    assert verified["status"] == "instrument_inspection_verified"
    assert verified["source_sha256"] == digest
    assert main([
        "--json", "--addon-path", str(addon), "measurement",
        "verify-source-inspection", "--adapter", "fixture_scope",
        "--source-file", str(source), "--config-file", str(config),
        "--media-type", "application/octet-stream",
        "--record-file", str(record_file),
        "--expected-record-sha256", f" {result['inspection_sha256']} ",
    ]) == 2
    assert "lowercase SHA-256" in capsys.readouterr().err
    altered = json.loads(record_file.read_text())
    altered["instrument"]["model"] = "Unregistered reinterpretation"
    altered_file = tmp_path / "altered-instrument-inspection.json"
    altered_file.write_text(json.dumps(altered, indent=2, sort_keys=True) + "\n")
    altered_sha256 = hashlib.sha256(altered_file.read_bytes()).hexdigest()
    assert main([
        "--json", "--addon-path", str(addon), "measurement",
        "verify-source-inspection", "--adapter", "fixture_scope",
        "--source-file", str(source), "--config-file", str(config),
        "--media-type", "application/octet-stream",
        "--record-file", str(altered_file),
        "--expected-record-sha256", altered_sha256,
    ]) == 2
    assert "does not exactly recompute" in capsys.readouterr().err


def test_instrument_inspection_discloses_absent_stream_metadata(tmp_path: Path) -> None:
    from research_machine.addons.models import InstrumentAdapter
    from research_machine.measurement.instrument import inspect_instrument_source

    source = tmp_path / "capture.bin"
    source.write_bytes(b"fixture")

    def inspect(source_bytes, config):
        return {
            "captured_at": "2026-09-06T12:00:00Z",
            "captured_at_basis": "user_supplied",
            "acquisition_method": "fixture",
            "instrument_identifier": "fixture-01",
            "instrument_model": "FixtureScope",
            "native_metadata": {},
            "warnings": [],
        }

    adapter = InstrumentAdapter(
        "stream_omitted", "Stream omitted", "Synthetic absent stream fixture.",
        ("application/octet-stream",), ("captured_at",), inspect,
    )
    manifest = AddonManifest(
        "stream_omitted_instrument", "Stream omitted instrument", "1", "test", "Fixture",
        instrument_adapters=(adapter,),
    )
    result = inspect_instrument_source(
        manifest, adapter, source, "application/octet-stream",
        {"captured_at": "2026-09-06T12:00:00Z"}, tmp_path / "inspection",
    )
    record = json.loads(Path(result["path"], "instrument-inspection.json").read_text())
    assert record["streams"] == []
    assert record["temporal_metadata"] == {
        "status": "not_provided",
        "stream_count": 0,
        "limitations": [
            "No typed stream metadata was proposed; synchronized timing cannot be assessed from this inspection."
        ],
    }
    assert record["scientific_evidence_eligible"] is False


def test_instrument_adapter_cannot_mutate_config_or_publish_invalid_result(
    tmp_path: Path,
) -> None:
    from research_machine.addons.models import InstrumentAdapter
    from research_machine.measurement.instrument import inspect_instrument_source

    source = tmp_path / "capture.bin"
    source.write_bytes(b"fixture")
    adapter = InstrumentAdapter(
        "mutating_adapter", "Mutating adapter", "Synthetic invalid fixture.",
        ("application/octet-stream",), ("captured_at",),
        lambda source_bytes, config: (
            config.update({"captured_at": "changed"})
            or {
                "captured_at": "2026-09-06T12:00:00Z",
                "captured_at_basis": "user_supplied",
                "acquisition_method": "fixture",
                "instrument_identifier": "fixture",
                "instrument_model": "fixture",
                "native_metadata": {},
                "warnings": [],
            }
        ),
    )
    manifest = AddonManifest(
        "mutating_instrument", "Mutating instrument", "1", "test", "Fixture",
        instrument_adapters=(adapter,),
    )
    output = tmp_path / "invalid-inspection"
    with pytest.raises(ValidationError, match="modified its committed config"):
        inspect_instrument_source(
            manifest, adapter, source, "application/octet-stream",
            {"captured_at": "2026-09-06T12:00:00Z"}, output,
        )
    assert not output.exists()

    def mutate_source(source_bytes, config):
        source.write_bytes(b"changed")
        return {
            "captured_at": config["captured_at"],
            "captured_at_basis": "user_supplied",
            "acquisition_method": "fixture",
            "instrument_identifier": "fixture",
            "instrument_model": "fixture",
            "native_metadata": {},
            "warnings": [],
        }

    source.write_bytes(b"fixture")
    source_mutator = InstrumentAdapter(
        "source_mutator", "Source mutator", "Synthetic invalid fixture.",
        ("application/octet-stream",), ("captured_at",), mutate_source,
    )
    source_output = tmp_path / "source-mutator-inspection"
    with pytest.raises(ValidationError, match="modified its source file"):
        inspect_instrument_source(
            manifest, source_mutator, source, "application/octet-stream",
            {"captured_at": "2026-09-06T12:00:00Z"}, source_output,
        )
    assert not source_output.exists()


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("acquisition_method", " fixture ", "acquisition_method"),
        ("instrument_identifier", " fixture-01 ", "instrument_identifier"),
        ("instrument_model", " FixtureScope ", "instrument_model"),
        ("firmware_version", " 1.2.3 ", "firmware_version"),
        ("warnings", [" padded warning "], "warnings"),
        ("native_metadata", {" serial_number": "fixture-01"}, "native_metadata keys"),
        ("native_metadata", {"serial_number": " fixture-01 "}, "native_metadata text"),
    ],
)
def test_instrument_adapter_output_text_must_be_canonical(
    tmp_path: Path, field, value, message
) -> None:
    from research_machine.addons.models import InstrumentAdapter
    from research_machine.measurement.instrument import inspect_instrument_source

    source = tmp_path / "capture.bin"
    source.write_bytes(b"fixture")

    def inspect(source_bytes, config):
        proposed = {
            "captured_at": "2026-09-06T12:00:00Z",
            "captured_at_basis": "user_supplied",
            "acquisition_method": "fixture",
            "instrument_identifier": "fixture-01",
            "instrument_model": "FixtureScope",
            "firmware_version": "1.2.3",
            "native_metadata": {},
            "warnings": ["Synthetic fixture"],
        }
        proposed[field] = value
        return proposed

    adapter = InstrumentAdapter(
        "padded_output", "Padded output", "Synthetic invalid fixture.",
        ("application/octet-stream",), ("captured_at",), inspect,
    )
    manifest = AddonManifest(
        "padded_instrument", "Padded instrument", "1", "test", "Fixture",
        instrument_adapters=(adapter,),
    )
    with pytest.raises(ValidationError, match=message):
        inspect_instrument_source(
            manifest, adapter, source, "application/octet-stream",
            {"captured_at": "2026-09-06T12:00:00Z"}, tmp_path / "inspection",
        )
    assert not (tmp_path / "inspection").exists()


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        (
            lambda stream: stream.update({"stream_id": "StreamMain"}),
            "stream_id must be a stable lowercase identifier",
        ),
        (
            lambda stream: stream.update({"channel": " main "}),
            "streams\\[0\\].channel",
        ),
        (
            lambda stream: stream.update({"sample_rate_hz": 0}),
            "sample_rate_hz",
        ),
        (
            lambda stream: stream["clock_drift"].update({"estimate": float("nan")}),
            "clock_drift.estimate",
        ),
        (
            lambda stream: stream["clock_drift"].pop("uncertainty"),
            "missing fields: uncertainty",
        ),
        (
            lambda stream: stream["clock_drift"].update({"uncertainty": -0.1}),
            "clock_drift.uncertainty must be non-negative",
        ),
        (
            lambda stream: stream["clock_drift"].update({"unit": "samples"}),
            "clock_drift.unit is unsupported",
        ),
        (
            lambda stream: stream["missing_intervals"][0].update(
                {"end_time": "2026-09-06T12:00:01Z"}
            ),
            "end_time must be after",
        ),
        (
            lambda stream: stream["missing_intervals"][0].update(
                {"start_time": "2026-09-06T11:59:59Z"}
            ),
            "must not precede stream start_time",
        ),
        (
            lambda stream: stream["missing_intervals"].append({
                "start_time": "2026-09-06T12:00:01.500000Z",
                "end_time": "2026-09-06T12:00:03Z",
                "reason": "Overlapping packet fixture",
            }),
            "ordered and non-overlapping",
        ),
        (
            lambda stream: stream["missing_intervals"].append({
                "start_time": "2026-09-06T12:00:00.500000Z",
                "end_time": "2026-09-06T12:00:00.750000Z",
                "reason": "Out-of-order packet fixture",
            }),
            "ordered and non-overlapping",
        ),
        (
            lambda stream: stream.update({"quality_flags": ["flag", "flag"]}),
            "quality_flags must be unique",
        ),
    ],
)
def test_instrument_stream_metadata_fails_closed(tmp_path: Path, mutation, message) -> None:
    from research_machine.addons.models import InstrumentAdapter
    from research_machine.measurement.instrument import inspect_instrument_source

    source = tmp_path / "capture.bin"
    source.write_bytes(b"fixture")
    stream = {
        "stream_id": "stream-main",
        "source_device": "fixture-01",
        "channel": "main",
        "sample_rate_hz": 256,
        "clock_source": "device clock",
        "start_time": "2026-09-06T12:00:00Z",
        "clock_drift": {
            "estimate": 0.2,
            "uncertainty": 0.05,
            "unit": "ms",
            "basis": "manufacturer sidecar",
        },
        "missing_intervals": [{
            "start_time": "2026-09-06T12:00:01Z",
            "end_time": "2026-09-06T12:00:02Z",
            "reason": "Dropped packet fixture",
        }],
        "calibration_record": "clock-sync-record-1",
        "quality_flags": ["synthetic-fixture"],
    }
    mutation(stream)

    def inspect(source_bytes, config):
        return {
            "captured_at": "2026-09-06T12:00:00Z",
            "captured_at_basis": "user_supplied",
            "acquisition_method": "fixture",
            "instrument_identifier": "fixture-01",
            "instrument_model": "FixtureScope",
            "native_metadata": {},
            "streams": [stream],
            "warnings": [],
        }

    adapter = InstrumentAdapter(
        "stream_fixture", "Stream fixture", "Synthetic stream metadata fixture.",
        ("application/octet-stream",), ("captured_at",), inspect,
    )
    manifest = AddonManifest(
        "stream_instrument", "Stream instrument", "1", "test", "Fixture",
        instrument_adapters=(adapter,),
    )
    with pytest.raises(ValidationError, match=message):
        inspect_instrument_source(
            manifest, adapter, source, "application/octet-stream",
            {"captured_at": "2026-09-06T12:00:00Z"}, tmp_path / "inspection",
        )
    assert not (tmp_path / "inspection").exists()


def test_analysis_refuses_overwrite_and_undeclared_claim_ceiling(
    tmp_path: Path, capsys
) -> None:
    data = tmp_path / "observations.csv"
    data.write_text("x\n1\n2\n")
    spec = tmp_path / "analysis.json"
    spec.write_text(json.dumps({"method": "descriptive_summary", "columns": ["x"]}))
    output = tmp_path / "output"
    assert main(["--json", "analysis", "run", "--spec-file", str(spec), "--data-file", str(data), "--output", str(output)]) == 2
    assert "claim_ceiling" in json.loads(capsys.readouterr().err)["error"]["message"]

    spec.write_text(json.dumps({"method": "descriptive_summary", "columns": ["x"], "claim_ceiling": "Description only."}))
    output.mkdir()
    (output / "preserved.txt").write_text("keep")
    assert main(["--json", "analysis", "run", "--spec-file", str(spec), "--data-file", str(data), "--output", str(output)]) == 2
    assert "not empty" in json.loads(capsys.readouterr().err)["error"]["message"]
    assert (output / "preserved.txt").read_text() == "keep"


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("method", " descriptive_summary ", "method must be canonical"),
        ("analysis_id", " padded-analysis ", "analysis_id must be canonical"),
        ("analysis_id", "", "analysis_id must be canonical"),
    ],
)
def test_analysis_rejects_noncanonical_provenance_handles(
    tmp_path: Path, capsys, field, value, message
) -> None:
    data = tmp_path / "observations.csv"
    data.write_text("x\n1\n2\n")
    spec = tmp_path / "analysis.json"
    command = {
        "method": "descriptive_summary",
        "columns": ["x"],
        "claim_ceiling": "Synthetic fixture only.",
    }
    command[field] = value
    spec.write_text(json.dumps(command))

    assert main([
        "--json", "analysis", "run", "--spec-file", str(spec),
        "--data-file", str(data), "--output", str(tmp_path / "output"),
    ]) == 2
    assert message in json.loads(capsys.readouterr().err)["error"]["message"]


@pytest.mark.parametrize(
    ("header", "message"),
    [
        (" x \n1\n2\n", "canonical"),
        ("x,X\n1,2\n3,4\n", "case-insensitive"),
    ],
)
def test_analysis_rejects_ambiguous_csv_headers(tmp_path: Path, capsys, header, message) -> None:
    data = tmp_path / "observations.csv"
    data.write_text(header)
    spec = tmp_path / "analysis.json"
    spec.write_text(json.dumps({
        "method": "descriptive_summary",
        "columns": ["x"],
        "claim_ceiling": "Synthetic header fixture only.",
    }))

    assert main([
        "--json", "analysis", "run", "--spec-file", str(spec),
        "--data-file", str(data), "--output", str(tmp_path / "output"),
    ]) == 2
    assert message in json.loads(capsys.readouterr().err)["error"]["message"]


def test_researcher_claim_cannot_widen_method_ceiling(tmp_path, capsys):
    data = tmp_path / "synthetic.csv"
    data.write_text("x\n1\n2\n")
    spec = tmp_path / "spec.json"
    overclaim = "This proves the intervention caused the outcome everywhere."
    spec.write_text(json.dumps({"method": "descriptive_summary", "columns": ["x"],
                                "claim_ceiling": overclaim}))
    assert main(["--json", "analysis", "run", "--spec-file", str(spec),
                 "--data-file", str(data), "--output", str(tmp_path / "output")]) == 0
    result = _result(capsys)["result"]
    assert result["result_contract_version"] == 2
    assert result["declared_claim_ceiling"] == overclaim
    assert result["claim_ceiling"] != overclaim
    assert result["claim_ceiling"].startswith("Descriptive summaries")
    assert "method_enforced_maximum" in result["claim_ceiling_status"]
