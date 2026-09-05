from __future__ import annotations

import csv
import hashlib
import inspect
import json
import os
import platform
import tempfile
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
    "bootstrap_resamples",
    "confidence_level",
    "missing_data_policy",
    "purpose",
    "claim_ceiling",
    "parameters",
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
    return (json.dumps(value, sort_keys=True, indent=2, ensure_ascii=False) + "\n").encode()


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
    if value.get("missing_data_policy", "complete_case") != "complete_case":
        raise ValidationError("only the explicit complete_case missing-data policy is supported")
    claim_ceiling = value.get("claim_ceiling")
    if not isinstance(claim_ceiling, str) or not claim_ceiling.strip():
        raise ValidationError("analysis specification requires a non-empty claim_ceiling")
    return value, _hash_bytes(content)


def _read_csv(path: Path) -> list[dict[str, str]]:
    try:
        with path.open(encoding="utf-8", newline="") as handle:
            reader = csv.DictReader(handle)
            if not reader.fieldnames or any(not name for name in reader.fieldnames):
                raise ValidationError("CSV requires a non-empty header with named columns")
            if len(set(reader.fieldnames)) != len(reader.fieldnames):
                raise ValidationError("CSV header contains duplicate columns")
            rows = list(reader)
    except UnicodeDecodeError as exc:
        raise ValidationError("CSV must be UTF-8") from exc
    if not rows:
        raise ValidationError("CSV contains no observations")
    if any(None in row for row in rows):
        raise ValidationError("CSV row contains more fields than the header")
    return rows


def _implementation_hash(runner: Callable[..., Any]) -> tuple[str, str]:
    source = inspect.getsourcefile(runner)
    if source is None:
        raise ValidationError("analysis method implementation source cannot be located")
    path = Path(source).resolve()
    return str(path), _hash_path(path)


def execute_analysis(
    *, registry: AddonRegistry, spec_path: Path, data_path: Path, output_dir: Path
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
    started_at = _utc_now()
    rows = _read_csv(data_path)
    implementation_path, implementation_sha256 = _implementation_hash(method.runner)
    result_value = method.runner(spec, rows)
    completed_at = _utc_now()
    result = {
        "analysis_id": spec.get("analysis_id") or f"{method.method_id}-{spec_sha256[:12]}",
        "addon_id": addon.addon_id,
        "addon_version": addon.version,
        "method": method.method_id,
        "purpose": spec.get("purpose", ""),
        "claim_ceiling": spec["claim_ceiling"],
        "missing_data_policy": "complete_case",
        "result": result_value,
    }
    result_bytes = _json_bytes(result)
    data_sha256 = _hash_path(data_path)
    receipt = {
        "receipt_version": 1,
        "status": "completed",
        "started_at": started_at,
        "completed_at": completed_at,
        "addon": {"addon_id": addon.addon_id, "version": addon.version},
        "method": method.method_id,
        "specification": {"locator": str(spec_path.resolve()), "sha256": spec_sha256},
        "input": {
            "locator": str(data_path.resolve()),
            "sha256": data_sha256,
            "size_bytes": data_path.stat().st_size,
            "row_count": len(rows),
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
