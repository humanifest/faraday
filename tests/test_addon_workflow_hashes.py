import hashlib
import json

import pytest

from research_machine.addons.workflow import (
    adjudicate_holm_workflow,
    materialize_holm_family,
    verify_holm_adjudication,
)
from research_machine.domain.errors import ValidationError


class FailingService:
    def __getattr__(self, name):
        raise AssertionError(f"service should not be consulted for {name}")


def _write_json(path, value):
    encoded = json.dumps(value, sort_keys=True).encode()
    path.write_bytes(encoded)
    return hashlib.sha256(encoded).hexdigest()


@pytest.mark.parametrize("expected", [" 0123", "A" * 64, "g" * 64, "0" * 63, "0" * 65])
def test_materialize_holm_requires_canonical_manifest_hash(tmp_path, expected):
    manifest = tmp_path / "dependencies.json"
    _write_json(manifest, {"family_step_id": "holm", "sources": []})

    with pytest.raises(ValidationError, match="workflow dependency manifest expected_manifest_sha256 must be a lowercase SHA-256 digest"):
        materialize_holm_family(
            FailingService(), "protocol", manifest, expected, tmp_path / "materialized"
        )

    assert not (tmp_path / "materialized").exists()


@pytest.mark.parametrize("expected", [" 0123", "A" * 64, "g" * 64, "0" * 63, "0" * 65])
def test_adjudicate_holm_requires_canonical_manifest_hash(tmp_path, expected):
    manifest = tmp_path / "workflow-adjudication.json"
    _write_json(manifest, {})

    with pytest.raises(ValidationError, match="workflow adjudication manifest expected_sha256 must be a lowercase SHA-256 digest"):
        adjudicate_holm_workflow(
            FailingService(), "protocol", manifest, expected, tmp_path / "adjudication"
        )

    assert not (tmp_path / "adjudication").exists()


@pytest.mark.parametrize("expected", [" 0123", "A" * 64, "g" * 64, "0" * 63, "0" * 65])
def test_verify_holm_adjudication_requires_canonical_receipt_hash(tmp_path, expected):
    directory = tmp_path / "adjudication"
    directory.mkdir()
    _write_json(directory / "workflow-adjudication-receipt.json", {})

    with pytest.raises(ValidationError, match="workflow adjudication receipt expected_sha256 must be a lowercase SHA-256 digest"):
        verify_holm_adjudication(FailingService(), directory, expected)
