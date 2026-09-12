"""Strict JSON loading rejects ambiguous retained literature artifacts."""
import hashlib

import pytest

from research_machine.domain.errors import ValidationError
from research_machine.literature.json_loading import load_json_object


@pytest.mark.parametrize(
    ("payload", "message"),
    [
        ('{"status": "first", "status": "second"}\n', "duplicate JSON object key"),
        ('{"estimate": NaN}\n', "non-finite JSON number"),
    ],
)
def test_load_json_object_rejects_ambiguous_json_bytes(tmp_path, payload, message):
    artifact = tmp_path / "artifact.json"
    artifact.write_text(payload, encoding="utf-8")

    with pytest.raises(ValidationError, match=message):
        load_json_object(artifact, "literature artifact")


def test_load_json_object_returns_hash_of_exact_bytes(tmp_path):
    payload = b'{"status": "retained"}\n'
    artifact = tmp_path / "artifact.json"
    artifact.write_bytes(payload)

    value, digest = load_json_object(artifact, "literature artifact")

    assert value == {"status": "retained"}
    assert digest == hashlib.sha256(payload).hexdigest()
