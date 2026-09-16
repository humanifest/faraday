"""Bounded, low-authority execution of scientific connector fetches."""

from __future__ import annotations

import hashlib
import inspect
import re
import json
from pathlib import Path
from typing import Any

from research_machine.addons.models import AddonManifest, ScientificConnector
from research_machine.domain.errors import ValidationError

_MAX_CONNECTOR_OUTPUT_BYTES = 10_000_000
_SHA256 = re.compile(r"^[0-9a-f]{64}$")


def _implementation_commitment(connector: ScientificConnector) -> dict[str, Any]:
    source_file = inspect.getsourcefile(connector.fetch)
    if not source_file:
        raise ValidationError("connector implementation source file is unavailable")
    path = Path(source_file).expanduser().resolve()
    if not path.is_file() or path.is_symlink():
        raise ValidationError("connector implementation source must be a regular file")
    data = path.read_bytes()
    return {"locator": path.name, "sha256": hashlib.sha256(data).hexdigest(), "size_bytes": len(data)}


def fetch_source_proposal(
    manifest: AddonManifest,
    connector: ScientificConnector,
    query: dict[str, Any],
    *,
    max_bytes: int = _MAX_CONNECTOR_OUTPUT_BYTES,
) -> dict[str, Any]:
    """Run a connector and return source material for later canonical intake."""
    if not isinstance(max_bytes, int) or isinstance(max_bytes, bool) or max_bytes <= 0:
        raise ValidationError("connector max_bytes must be a positive integer")
    if not isinstance(query, dict):
        raise ValidationError("connector query must be an object")
    allowed = set(connector.required_query_fields) | set(connector.optional_query_fields)
    unknown = sorted(set(query) - allowed)
    if unknown:
        raise ValidationError("connector query has unknown fields: " + ", ".join(unknown))
    missing = sorted(set(connector.required_query_fields) - set(query))
    if missing:
        raise ValidationError("connector query is missing fields: " + ", ".join(missing))
    result = connector.fetch(dict(query))
    if not isinstance(result, dict) or set(result) != {"bytes", "metadata"}:
        raise ValidationError("connector must return exactly bytes and metadata")
    source_bytes = result["bytes"]
    if not isinstance(source_bytes, bytes):
        raise ValidationError("connector bytes must be immutable bytes")
    if len(source_bytes) > max_bytes or len(source_bytes) > _MAX_CONNECTOR_OUTPUT_BYTES:
        raise ValidationError("connector output exceeds bounded byte limit")
    if not isinstance(result["metadata"], dict):
        raise ValidationError("connector metadata must be an object")
    try:
        metadata_bytes = len(
            json.dumps(
                result["metadata"],
                sort_keys=True,
                separators=(",", ":"),
                ensure_ascii=False,
                allow_nan=False,
            ).encode()
        )
    except (TypeError, ValueError) as exc:
        raise ValidationError("connector metadata must be JSON-compatible") from exc
    if metadata_bytes > max_bytes or metadata_bytes > _MAX_CONNECTOR_OUTPUT_BYTES:
        raise ValidationError("connector metadata exceeds bounded byte limit")
    return {
        "connector": {
            "addon_id": manifest.addon_id,
            "addon_version": manifest.version,
            "connector_id": connector.connector_id,
            "implementation": _implementation_commitment(connector),
        },
        "query": query,
        "source": {
            "sha256": hashlib.sha256(source_bytes).hexdigest(),
            "size_bytes": len(source_bytes),
            "bytes": source_bytes,
        },
        "metadata": result["metadata"],
        "authority": "bounded_source_material_proposal_only",
        "scientific_evidence_eligible": False,
        "canonical_dataset_registered": False,
        "custody_cleared": False,
        "authorized_actions": ["submit_to_canonical_dataset_intake"],
    }


def write_source_proposal(
    proposal: dict[str, Any], output_dir: str | Path
) -> dict[str, Any]:
    """Persist a connector proposal as a byte file plus a replayable receipt."""
    if not isinstance(proposal, dict) or proposal.get("authority") != "bounded_source_material_proposal_only":
        raise ValidationError("connector proposal has an invalid authority boundary")
    source = proposal.get("source")
    if not isinstance(source, dict) or not isinstance(source.get("bytes"), bytes):
        raise ValidationError("connector proposal source bytes are missing")
    root = Path(output_dir).expanduser().resolve()
    if root.exists() and not root.is_dir():
        raise ValidationError("connector proposal output must be a directory")
    root.mkdir(parents=True, exist_ok=True)
    source_path = root / "source.bin"
    receipt_path = root / "connector-proposal.json"
    if source_path.exists() or receipt_path.exists():
        raise ValidationError("connector proposal output already exists")
    source_bytes = source["bytes"]
    digest = hashlib.sha256(source_bytes).hexdigest()
    if source.get("sha256") != digest or source.get("size_bytes") != len(source_bytes):
        raise ValidationError("connector proposal source commitment does not match bytes")
    source_path.write_bytes(source_bytes)
    receipt = {key: value for key, value in proposal.items() if key != "source"}
    receipt["source"] = {"locator": source_path.name, "sha256": digest, "size_bytes": len(source_bytes)}
    receipt_path.write_text(json.dumps(receipt, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    return {"output_dir": str(root), "source": str(source_path), "receipt": str(receipt_path), "source_sha256": digest}


def verify_source_proposal(
    receipt_file: str | Path,
    connector: ScientificConnector | None = None,
    manifest: AddonManifest | None = None,
    expected_receipt_sha256: str | None = None,
) -> dict[str, Any]:
    """Replay a persisted connector proposal from its receipt and current bytes."""
    receipt_path = Path(receipt_file).expanduser().resolve()
    if not receipt_path.is_file() or receipt_path.is_symlink():
        raise ValidationError("connector proposal receipt must be a regular file")
    receipt_bytes = receipt_path.read_bytes()
    actual_receipt_sha256 = hashlib.sha256(receipt_bytes).hexdigest()
    if expected_receipt_sha256 is not None:
        if not isinstance(expected_receipt_sha256, str) or not _SHA256.fullmatch(expected_receipt_sha256):
            raise ValidationError("expected connector receipt SHA-256 must be lowercase hex")
        if expected_receipt_sha256 != actual_receipt_sha256:
            raise ValidationError("connector proposal receipt does not match expected SHA-256")
    try:
        receipt = json.loads(receipt_bytes.decode("utf-8"))
    except (OSError, ValueError) as exc:
        raise ValidationError("connector proposal receipt is unreadable JSON") from exc
    if not isinstance(receipt, dict) or receipt.get("authority") != "bounded_source_material_proposal_only":
        raise ValidationError("connector proposal receipt has an invalid authority boundary")
    receipt_connector = receipt.get("connector")
    implementation = (
        receipt_connector.get("implementation")
        if isinstance(receipt_connector, dict)
        else None
    )
    if not isinstance(implementation, dict) or set(implementation) != {"locator", "sha256", "size_bytes"}:
        raise ValidationError("connector implementation commitment is missing")
    implementation_replayed = False
    if connector is not None:
        if not isinstance(receipt_connector, dict) or receipt_connector.get("connector_id") != connector.connector_id:
            raise ValidationError("connector identity does not match receipt")
        if manifest is not None and receipt_connector.get("addon_id") != manifest.addon_id:
            raise ValidationError("connector add-on identity does not match receipt")
        current = _implementation_commitment(connector)
        if current != implementation:
            raise ValidationError("connector implementation does not match receipt")
        implementation_replayed = True
    source = receipt.get("source")
    if not isinstance(source, dict) or set(source) != {"locator", "sha256", "size_bytes"}:
        raise ValidationError("connector proposal receipt source commitment is invalid")
    locator = source["locator"]
    if not isinstance(locator, str) or locator != Path(locator).name or locator in {".", ".."}:
        raise ValidationError("connector proposal source locator must be a safe relative name")
    source_path = receipt_path.parent / locator
    if not source_path.is_file() or source_path.is_symlink():
        raise ValidationError("connector proposal source must be a regular file")
    source_bytes = source_path.read_bytes()
    digest = hashlib.sha256(source_bytes).hexdigest()
    if source["sha256"] != digest or source["size_bytes"] != len(source_bytes):
        raise ValidationError("connector proposal source bytes do not match receipt")
    return {
        "status": "verified_source_material_proposal",
        "receipt": str(receipt_path),
        "receipt_sha256": actual_receipt_sha256,
        "source": str(source_path),
        "source_sha256": digest,
        "size_bytes": len(source_bytes),
        "scientific_evidence_eligible": False,
        "canonical_dataset_registered": False,
        "custody_cleared": False,
        "implementation_replayed": implementation_replayed,
    }
