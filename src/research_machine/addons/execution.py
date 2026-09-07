from __future__ import annotations

import csv
import copy
import hashlib
import inspect
import io
import json
import os
import platform
import tempfile
import math
from datetime import datetime, timezone
from pathlib import Path
from collections.abc import Callable
from typing import Any

from research_machine.addons.registry import AddonRegistry
from research_machine.domain.errors import ValidationError

_SPEC_FIELDS = {
    "method",
    "analysis_id",
    "columns",
    "x_column",
    "y_column",
    "outcome_column",
    "group_column",
    "groups",
    "permutations",
    "seed",
    "study_design",
    "pair_column",
    "unit_column",
    "covariate_columns",
    "bootstrap_resamples",
    "confidence_level",
    "missing_data_policy",
    "purpose",
    "estimand",
    "contrast_definition",
    "claim_ceiling",
    "parameters",
    "hypothesis_column",
    "p_value_column",
    "family_name",
    "family_hypothesis_ids",
    "alpha",
}


def _validate_registered_confidence_interval(effect: Any, uncertainty: Any) -> None:
    if isinstance(effect, bool) or not isinstance(effect, (int, float)) or not math.isfinite(float(effect)):
        raise ValidationError("registered primary effect estimate must be a finite number")
    if not isinstance(uncertainty, dict):
        raise ValidationError("registered uncertainty must be a confidence-interval object")
    try:
        values = uncertainty["lower"], uncertainty["upper"], uncertainty["level"]
    except KeyError as exc:
        raise ValidationError("registered confidence interval requires lower, upper, and level") from exc
    if any(isinstance(value, bool) or not isinstance(value, (int, float))
           or not math.isfinite(float(value)) for value in values):
        raise ValidationError("registered confidence interval values must be finite numbers")
    lower, upper, level = values
    if lower > effect or effect > upper or not 0 < level < 1:
        raise ValidationError(
            "registered confidence interval must contain the effect and use a level between zero and one"
        )


def validate_registered_confidence_level(
    uncertainty: Any, registered_confidence_level: Any,
) -> None:
    """Reject an interval computed at a level other than the frozen level."""
    if registered_confidence_level is None:
        return
    if not isinstance(uncertainty, dict) or "level" not in uncertainty:
        raise ValidationError("registered uncertainty lacks a confidence level")
    if float(uncertainty["level"]) != float(registered_confidence_level):
        raise ValidationError(
            "analysis confidence interval level does not match the frozen analysis contract"
        )


def validate_registered_information(result: Any, contract: Any) -> dict[str, Any]:
    """Recompute the protocol's minimum-information and attrition gate."""
    if not isinstance(result, dict) or not isinstance(contract, dict):
        raise ValidationError("registered information check requires result and analysis contract objects")
    body = result.get("result")
    if not isinstance(body, dict):
        raise ValidationError("analysis result body must be an object")
    minimum = contract.get("minimum_analyzable_units")
    maximum_fraction = contract.get("maximum_excluded_fraction")
    maximum_group_difference = contract.get(
        "maximum_group_excluded_fraction_difference"
    )
    groups = contract.get("groups")
    if type(minimum) is not int or minimum < 2:
        raise ValidationError("analysis contract minimum_analyzable_units must be an integer of at least two")
    if (isinstance(maximum_fraction, bool) or not isinstance(maximum_fraction, (int, float))
            or not math.isfinite(float(maximum_fraction)) or not 0 <= float(maximum_fraction) < 1):
        raise ValidationError("analysis contract maximum_excluded_fraction must be in [0, 1)")
    if (
        isinstance(maximum_group_difference, bool)
        or not isinstance(maximum_group_difference, (int, float))
        or not math.isfinite(float(maximum_group_difference))
        or not 0 <= float(maximum_group_difference) <= 1
    ):
        raise ValidationError(
            "analysis contract maximum_group_excluded_fraction_difference must be in [0, 1]"
        )
    counts = body.get("n_by_group")
    if isinstance(counts, dict):
        if (not isinstance(groups, list) or set(counts) != set(groups)
                or any(type(counts[group]) is not int or counts[group] < 0 for group in groups)):
            raise ValidationError("analysis n_by_group does not match the frozen comparison groups")
        observed = min(counts[group] for group in groups)
    else:
        observed = body.get("n_pairs")
        if type(observed) is not int or observed < 0:
            raise ValidationError("analysis result lacks a valid analyzable-unit count")
    exclusion = body.get("exclusion_report")
    if exclusion is None:
        if body.get("missing_rows") != 0:
            raise ValidationError("analysis result lacks an exclusion report for omitted records")
        excluded_fraction = 0.0
        input_records = observed * 2 if "n_pairs" in body else sum(counts.values())
        included_records = input_records
        excluded_fraction_by_group = {group: 0.0 for group in groups}
    else:
        if not isinstance(exclusion, dict):
            raise ValidationError("analysis exclusion_report must be an object")
        input_records = exclusion.get("input_records")
        included_records = exclusion.get("included_records")
        excluded_records = exclusion.get("excluded_records")
        if (type(input_records) is not int or input_records < 1
                or type(included_records) is not int or not 0 <= included_records <= input_records
                or not isinstance(excluded_records, list)
                or len(excluded_records) != input_records - included_records):
            raise ValidationError("analysis exclusion report counts are internally inconsistent")
        excluded_fraction = (input_records - included_records) / input_records
        excluded_by_group = exclusion.get("excluded_by_group")
        excluded_without_group = exclusion.get("excluded_without_registered_group")
        if (
            not isinstance(counts, dict)
            or not isinstance(excluded_by_group, dict)
            or set(excluded_by_group) != set(groups)
            or any(
                type(excluded_by_group[group]) is not int
                or excluded_by_group[group] < 0
                for group in groups
            )
            or type(excluded_without_group) is not int
            or excluded_without_group < 0
        ):
            raise ValidationError(
                "analysis exclusion report lacks exact registered-group exclusion counts"
            )
        total_excluded = input_records - included_records
        if sum(counts.values()) != included_records:
            raise ValidationError(
                "analysis included group counts do not equal exclusion report included_records"
            )
        if sum(excluded_by_group.values()) + excluded_without_group != total_excluded:
            raise ValidationError(
                "analysis grouped and ungrouped exclusion counts do not equal the "
                "exclusion report total"
            )
        if excluded_without_group:
            raise ValidationError(
                "analysis has exclusions without a registered group; differential "
                "exclusion rates cannot be verified"
            )
        excluded_fraction_by_group = {}
        for group in groups:
            group_input = counts[group] + excluded_by_group[group]
            if group_input < 1:
                raise ValidationError(
                    "analysis group exclusion rate has a zero denominator"
                )
            excluded_fraction_by_group[group] = (
                excluded_by_group[group] / group_input
            )
    observed_group_difference = (
        max(excluded_fraction_by_group.values())
        - min(excluded_fraction_by_group.values())
    )
    if observed < minimum:
        raise ValidationError(
            f"analysis has {observed} analyzable units but the frozen minimum is {minimum}"
        )
    if excluded_fraction > float(maximum_fraction):
        raise ValidationError(
            f"analysis excluded fraction {excluded_fraction:.12g} exceeds the frozen maximum {float(maximum_fraction):.12g}"
        )
    if observed_group_difference > float(maximum_group_difference):
        raise ValidationError(
            "analysis between-group excluded-fraction difference "
            f"{observed_group_difference:.12g} exceeds the frozen maximum "
            f"{float(maximum_group_difference):.12g}"
        )
    return {
        "status": "passed",
        "registered_minimum_analyzable_units": minimum,
        "observed_minimum_analyzable_units": observed,
        "registered_maximum_excluded_fraction": float(maximum_fraction),
        "observed_excluded_fraction": excluded_fraction,
        "registered_maximum_group_excluded_fraction_difference": float(
            maximum_group_difference
        ),
        "observed_excluded_fraction_by_group": excluded_fraction_by_group,
        "observed_group_excluded_fraction_difference": observed_group_difference,
        "input_records": input_records,
        "included_records": included_records,
    }


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _hash_bytes(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _hash_path(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _json_bytes(value: Any) -> bytes:
    try:
        return (json.dumps(value, sort_keys=True, indent=2, ensure_ascii=False, allow_nan=False) + "\n").encode()
    except (TypeError, ValueError) as exc:
        raise ValidationError("analysis output must be JSON-serializable with finite numeric values") from exc


def _resolve_json_pointer(value: Any, pointer: str) -> Any:
    if not isinstance(pointer, str) or not pointer.startswith("/"):
        raise ValidationError("registered result selector must be an absolute JSON Pointer")
    current = value
    for raw_token in pointer[1:].split("/"):
        token = raw_token.replace("~1", "/").replace("~0", "~")
        if isinstance(current, dict) and token in current:
            current = current[token]
        elif isinstance(current, list) and token.isdigit() and int(token) < len(current):
            current = current[int(token)]
        else:
            raise ValidationError(f"registered result selector does not resolve: {pointer}")
    return current


def _reject_nonfinite(value: str) -> None:
    raise ValueError(f"non-finite JSON number: {value}")


def _reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate JSON object key: {key}")
        result[key] = value
    return result


def _read_spec(path: Path) -> tuple[dict[str, Any], str]:
    content = path.read_bytes()
    try:
        value = json.loads(
            content,
            parse_constant=_reject_nonfinite,
            object_pairs_hook=_reject_duplicate_keys,
        )
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
        raise ValidationError(f"invalid analysis specification: {exc}") from exc
    if not isinstance(value, dict):
        raise ValidationError("analysis specification must be a JSON object")
    unknown = sorted(set(value) - _SPEC_FIELDS)
    if unknown:
        raise ValidationError("unknown analysis specification fields: " + ", ".join(unknown))
    if not isinstance(value.get("method"), str):
        raise ValidationError("analysis specification requires method")
    if "unit_column" in value and value["method"] not in {
        "independent_mean_difference_ci", "adjusted_linear_effect",
        "permutation_mean_difference",
    }:
        raise ValidationError(
            "unit_column identity checking is supported only by independent_mean_difference_ci, "
            "adjusted_linear_effect, and permutation_mean_difference; it must not be silently ignored"
        )
    if value.get("missing_data_policy", "complete_case") != "complete_case":
        raise ValidationError("only the explicit complete_case missing-data policy is supported")
    claim_ceiling = value.get("claim_ceiling")
    if not isinstance(claim_ceiling, str) or not claim_ceiling.strip():
        raise ValidationError("analysis specification requires a non-empty claim_ceiling")
    return value, _hash_bytes(content)


def _read_csv(content: bytes) -> list[dict[str, str]]:
    try:
        with io.StringIO(content.decode("utf-8"), newline="") as handle:
            reader = csv.DictReader(handle)
            if not reader.fieldnames or any(not name for name in reader.fieldnames):
                raise ValidationError("CSV requires a non-empty header with named columns")
            if any(name != name.strip() for name in reader.fieldnames):
                raise ValidationError("CSV header names must be canonical without surrounding whitespace")
            normalized = [name.casefold() for name in reader.fieldnames]
            if len(set(normalized)) != len(normalized):
                raise ValidationError("CSV header contains duplicate columns after case-insensitive normalization")
            rows = list(reader)
    except UnicodeDecodeError as exc:
        raise ValidationError("CSV must be UTF-8") from exc
    if not rows:
        raise ValidationError("CSV contains no observations")
    if any(None in row for row in rows):
        raise ValidationError("CSV row contains more fields than the header")
    return rows


def _unit_structure(spec: dict[str, Any], rows: list[dict[str, str]]) -> dict[str, Any]:
    design = spec.get("study_design")
    column = spec.get("pair_column") if design == "paired" else spec.get("unit_column")
    if not isinstance(column, str) or not column.strip():
        raise ValidationError("protocol-bound analysis requires a non-empty unit or pair column")
    if column not in rows[0]:
        raise ValidationError("analysis unit or pair column is absent from the CSV")
    counts: dict[str, int] = {}
    mapping = []
    allocation = []
    group_column = spec.get("group_column")
    for row_number, row in enumerate(rows, start=2):
        value = row.get(column)
        if not isinstance(value, str) or not value.strip():
            raise ValidationError(f"analysis unit identifier is missing at CSV row {row_number}")
        identifier = value.strip()
        counts[identifier] = counts.get(identifier, 0) + 1
        mapping.append({"csv_row": row_number, "unit_id": identifier})
        if isinstance(group_column, str) and group_column.strip():
            group = row.get(group_column)
            if not isinstance(group, str) or not group.strip():
                raise ValidationError(f"analysis group assignment is missing at CSV row {row_number}")
            allocation.append({"unit_id": identifier, "group": group.strip()})
    frequencies = list(counts.values())
    return {
        "unit_id_column": column,
        "row_count": len(rows),
        "unit_count": len(counts),
        "repeated_unit_count": sum(count > 1 for count in frequencies),
        "minimum_observations_per_unit": min(frequencies),
        "maximum_observations_per_unit": max(frequencies),
        "row_to_unit_mapping_sha256": _hash_bytes(_json_bytes(mapping)),
        "unit_group_allocation_sha256": _hash_bytes(json.dumps(
            sorted(allocation, key=lambda item: (item["unit_id"], item["group"])),
            sort_keys=True, separators=(",", ":"), ensure_ascii=False,
        ).encode()),
    }


def _implementation_hash(runner: Callable[..., Any]) -> tuple[str, str]:
    source = inspect.getsourcefile(runner)
    if source is None:
        raise ValidationError("analysis method implementation source cannot be located")
    path = Path(source).resolve()
    return str(path), _hash_path(path)


def validate_measurement_values(
    rows: list[dict[str, str]], definitions: Any,
) -> dict[str, Any]:
    """Validate analyzed source values against frozen scale and domain contracts."""
    if not isinstance(definitions, list) or not definitions:
        raise ValidationError("protocol design receipt lacks executable measurement contracts")
    checks: list[dict[str, Any]] = []
    columns: list[str] = []
    for definition in definitions:
        if not isinstance(definition, dict):
            raise ValidationError("executable measurement contracts must be objects")
        column = definition.get("data_column")
        scale = definition.get("scale_type")
        unit = definition.get("unit")
        admissible = definition.get("admissible_values")
        missing_codes = definition.get("missing_value_codes")
        if (
            not isinstance(column, str)
            or not column
            or not isinstance(scale, str)
            or not scale
        ):
            raise ValidationError("executable measurement contract lacks data_column or scale_type")
        if column != column.strip():
            raise ValidationError("executable measurement data_column must be canonical without surrounding whitespace")
        if (
            not isinstance(unit, str)
            or not unit
            or not isinstance(admissible, list)
            or not isinstance(missing_codes, list)
        ):
            raise ValidationError("executable measurement contract lacks unit or value-domain lists")
        values = [*admissible, *missing_codes]
        if any(
            not isinstance(value, str) or not value or value != value.strip()
            for value in values
        ):
            raise ValidationError("executable measurement value-domain entries must be canonical non-blank strings")
        if len({value.casefold() for value in admissible}) != len(admissible):
            raise ValidationError("executable measurement admissible_values must be case-insensitively unique")
        if len({value.casefold() for value in missing_codes}) != len(missing_codes):
            raise ValidationError("executable measurement missing_value_codes must be case-insensitively unique")
        if {value.casefold() for value in admissible} & {value.casefold() for value in missing_codes}:
            raise ValidationError("executable measurement admissible_values and missing_value_codes must not overlap")
        lower, upper = definition.get("valid_min"), definition.get("valid_max")
        if (
            lower is not None
            and (
                isinstance(lower, bool)
                or not isinstance(lower, (int, float))
                or not math.isfinite(float(lower))
            )
        ) or (
            upper is not None
            and (
                isinstance(upper, bool)
                or not isinstance(upper, (int, float))
                or not math.isfinite(float(upper))
            )
        ):
            raise ValidationError("executable measurement validity bounds must be finite numbers when supplied")
        if lower is not None and upper is not None and not float(lower) < float(upper):
            raise ValidationError("executable measurement valid_min must be strictly below valid_max")
        columns.append(column)
        if len({item.casefold() for item in columns}) != len(columns):
            raise ValidationError("executable measurement data_column values must be case-insensitively unique")
        observed = 0
        missing = 0
        for index, row in enumerate(rows, start=2):
            if column not in row:
                raise ValidationError(f"registered measurement column {column!r} is absent")
            raw = row[column]
            is_missing = raw in missing_codes or (raw == "" and "<blank>" in missing_codes)
            if is_missing:
                missing += 1
                continue
            if raw == "":
                raise ValidationError(
                    f"unregistered blank missing value in {column!r} at CSV row {index}"
                )
            if scale in {"binary", "nominal", "ordinal"}:
                if raw not in admissible:
                    raise ValidationError(
                        f"value outside the frozen categorical domain in {column!r} at CSV row {index}"
                    )
            else:
                try:
                    value = float(raw)
                except ValueError as exc:
                    raise ValidationError(
                        f"non-numeric value for frozen {scale} measurement in {column!r} at CSV row {index}"
                    ) from exc
                if not math.isfinite(value):
                    raise ValidationError(
                        f"non-finite value in {column!r} at CSV row {index}"
                    )
                if ((lower is not None and value < lower)
                        or (upper is not None and value > upper)):
                    raise ValidationError(
                        f"value outside frozen validity bounds in {column!r} at CSV row {index}"
                    )
                if scale == "count" and not value.is_integer():
                    raise ValidationError(
                        f"non-integer value for frozen count measurement in {column!r} at CSV row {index}"
                    )
            observed += 1
        checks.append({
            "measurement_id": definition.get("measurement_id"),
            "data_column": column,
            "scale_type": scale,
            "unit": unit,
            "observed_count": observed,
            "missing_count": missing,
            "status": "passed",
        })
    return {
        "status": "passed",
        "scope": "source_values_against_frozen_scale_domain_bounds_and_missing_codes",
        "measurements": checks,
        "notice": "Domain conformance does not establish construct validity, calibration, independence, or lack of measurement error.",
    }


def execute_analysis(
    *, registry: AddonRegistry, spec_path: Path, data_path: Path, output_dir: Path,
    design_check: Callable[[dict[str, Any], dict[str, Any], str, str, str, int, str], dict[str, Any]] | None = None,
) -> dict[str, Any]:
    if not spec_path.is_file():
        raise ValidationError(f"analysis specification is not a file: {spec_path}")
    if not data_path.is_file():
        raise ValidationError(f"analysis dataset is not a file: {data_path}")
    if output_dir.exists():
        if not output_dir.is_dir():
            raise ValidationError(f"analysis output path is not a directory: {output_dir}")
        if any(output_dir.iterdir()):
            raise ValidationError(
                f"analysis output directory is not empty: {output_dir}"
            )
    spec, spec_sha256 = _read_spec(spec_path)
    addon, method = registry.resolve_method(spec["method"])
    missing = [field for field in method.required_spec_fields if field not in spec]
    if missing:
        raise ValidationError("analysis specification is missing fields: " + ", ".join(missing))
    if design_check is not None and method.method_id == "independent_mean_difference_ci" and "unit_column" not in spec:
        raise ValidationError("protocol-bound independent analysis requires a committed unit_column identity check")
    started_at = _utc_now()
    # Hash the same snapshot we parse, not a later version of the source path.
    data_content = data_path.read_bytes()
    data_sha256 = _hash_bytes(data_content)
    data_size = len(data_content)
    rows = _read_csv(data_content)
    row_count = len(rows)
    implementation_path, implementation_sha256 = _implementation_hash(method.runner)
    design_receipt = (
        design_check(spec, {} if method.method_id == "holm_adjustment" else _unit_structure(spec, rows), implementation_sha256,
                     spec_sha256, data_sha256, data_size, method.maximum_inference_level)
        if design_check is not None else None
    )
    measurement_value_check = (
        validate_measurement_values(rows, design_receipt.get("measurement_contracts"))
        if design_receipt is not None and design_receipt.get("measurement_contracts") else None
    )
    runner_spec = copy.deepcopy(spec)
    committed_spec = _json_bytes(spec)
    result_value = method.runner(runner_spec, rows)
    if _json_bytes(runner_spec) != committed_spec:
        raise ValidationError("analysis method modified its committed specification")
    completed_at = _utc_now()
    result = {
        "result_contract_version": 2,
        "analysis_id": spec.get("analysis_id") or f"{method.method_id}-{spec_sha256[:12]}",
        "addon_id": addon.addon_id,
        "addon_version": addon.version,
        "method": method.method_id,
        "purpose": spec.get("purpose", ""),
        "estimand": spec.get("estimand", ""),
        "contrast_definition": spec.get("contrast_definition", ""),
        "contrast_groups": list(spec.get("groups", [])),
        "claim_ceiling": method.maximum_claim_ceiling,
        "maximum_inference_level": method.maximum_inference_level,
        "declared_claim_ceiling": spec["claim_ceiling"],
        "claim_ceiling_status": "method_enforced_maximum; the researcher declaration is retained but cannot widen it",
        "missing_data_policy": spec.get("missing_data_policy"),
        "missing_data_policy_scope": "Declared specification setting only; consult method results for actual exclusions or rejection rules.",
        "result": result_value,
    }
    registered_result_selection = None
    registered_information_check = None
    registered_workflow_selection = None
    if design_receipt is not None and "analysis_contract" in design_receipt:
        contract = design_receipt.get("analysis_contract")
        if not isinstance(contract, dict):
            raise ValidationError("protocol design receipt lacks its analysis contract")
        effect_path = contract.get("effect_estimate_path")
        uncertainty_path = contract.get("uncertainty_path")
        effect_value = _resolve_json_pointer(result, effect_path)
        uncertainty_value = _resolve_json_pointer(result, uncertainty_path)
        _validate_registered_confidence_interval(effect_value, uncertainty_value)
        registered_confidence_level = contract.get("confidence_level")
        validate_registered_confidence_level(
            uncertainty_value, registered_confidence_level
        )
        registered_information_check = validate_registered_information(result, contract)
        registered_result_selection = {
            "effect_estimate_path": effect_path,
            "uncertainty_path": uncertainty_path,
            "null_value": contract.get("null_value"),
            "support_rule": contract.get("support_rule"),
            "confidence_interval_validated": True,
            "registered_confidence_level": registered_confidence_level,
            "effect_estimate_sha256": _hash_bytes(_json_bytes(effect_value)),
            "uncertainty_sha256": _hash_bytes(_json_bytes(uncertainty_value)),
        }
    if design_receipt is not None and isinstance(design_receipt.get("analysis_step_contract"), dict):
        step = design_receipt["analysis_step_contract"]
        if step.get("role") == "confirmatory_test":
            p_value_path = step.get("p_value_path")
            p_value = _resolve_json_pointer(result, p_value_path)
            if (isinstance(p_value, bool) or not isinstance(p_value, (int, float))
                    or not math.isfinite(float(p_value)) or not 0 <= float(p_value) <= 1):
                raise ValidationError("registered workflow p-value must be finite and within [0, 1]")
            registered_workflow_selection = {
                "step_id": step.get("step_id"),
                "p_value_path": p_value_path,
                "p_value": float(p_value),
                "p_value_sha256": _hash_bytes(_json_bytes(p_value)),
            }
    result_bytes = _json_bytes(result)
    receipt = {
        "receipt_version": 1,
        "protocol_design_check": design_receipt,
        "status": "completed",
        "started_at": started_at,
        "completed_at": completed_at,
        "addon": {"addon_id": addon.addon_id, "version": addon.version},
        "method": method.method_id,
        "maximum_inference_level": method.maximum_inference_level,
        "specification": {"locator": str(spec_path.resolve()), "sha256": spec_sha256},
        "input": {
            "locator": str(data_path.resolve()),
            "sha256": data_sha256,
            "size_bytes": data_size,
            "row_count": row_count,
            "media_type": "text/csv",
        },
        "implementation": {
            "locator": implementation_path,
            "sha256": implementation_sha256,
        },
        "environment": {
            "python": platform.python_version(),
            "platform": platform.platform(),
        },
        "output": {
            "locator": "analysis-result.json",
            "sha256": _hash_bytes(result_bytes),
            "size_bytes": len(result_bytes),
        },
        "registered_result_selection": registered_result_selection,
        "registered_information_check": registered_information_check,
        "registered_workflow_selection": registered_workflow_selection,
        "measurement_value_check": measurement_value_check,
        "quality_gates": [
            {"gate_id": "input-readable", "status": "passed", "required": True, "summary": "The committed UTF-8 CSV was readable and structurally valid."},
            {"gate_id": "method-resolved", "status": "passed", "required": True, "summary": "The requested method resolved through a validated add-on manifest."},
            {"gate_id": "analysis-completed", "status": "passed", "required": True, "summary": "The analysis completed without relaxing its specification."},
        ],
        "scientific_evidence_eligible": False,
        "eligibility_note": "Execution alone is not canonical evidence. Register the dataset, bind this output to a frozen protocol, record the run, and pass applicable domain gates.",
    }
    receipt_bytes = _json_bytes(receipt)
    output_dir.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=f".{output_dir.name}-", dir=output_dir.parent) as temporary:
        staging = Path(temporary)
        (staging / "analysis-result.json").write_bytes(result_bytes)
        (staging / "execution-receipt.json").write_bytes(receipt_bytes)
        try:
            os.replace(staging, output_dir)
        except OSError as exc:
            raise ValidationError(f"could not publish analysis output atomically: {exc}") from exc
    return {"output_directory": str(output_dir.resolve()), "result": result, "receipt": receipt}
