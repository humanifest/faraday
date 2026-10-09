"""Provider-neutral guide handoff exercised only by an in-process fixture.

Cypher owns any future live inference route. This module exposes no network,
filesystem, credential, or fallback capability to a provider.
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
from typing import Protocol

from research_machine.collaboration.proposal import (
    _duplicate_pairs,
    _load_object,
    _nonfinite,
    _validate_context_snapshot,
    _validate_proposal,
)
from research_machine.domain.errors import ValidationError


class GuideProviderPort(Protocol):
    """A replaceable byte-in, byte-out port without implicit tools."""

    provider_id: str
    data_destination: str

    def complete(self, prompt: bytes, *, max_output_bytes: int) -> bytes: ...


@dataclass(frozen=True)
class FixedResponseGuideProvider:
    response: bytes | None
    provider_id: str = "faraday-fixed-response-fixture-v1"
    data_destination: str = "in_process_only"

    def complete(self, prompt: bytes, *, max_output_bytes: int) -> bytes:
        del prompt
        if self.response is None:
            raise ValidationError("fixed guide provider fixture failed")
        if len(self.response) > max_output_bytes:
            raise ValidationError("fixed guide provider output exceeds the declared ceiling")
        return self.response


def run_fixed_guide_provider_fixture(
    context_file: Path, expected_context_sha256: str, instruction: str,
    provider: FixedResponseGuideProvider, *, max_prompt_bytes: int = 65536,
    max_output_bytes: int = 32768,
) -> dict:
    """Exercise the provider contract on a redacted context in-process only."""
    if type(provider) is not FixedResponseGuideProvider:
        raise ValidationError("guide provider fixture accepts only its fixed in-process adapter")
    if (provider.provider_id != "faraday-fixed-response-fixture-v1"
        or provider.data_destination != "in_process_only"):
        raise ValidationError("guide provider fixture identity or destination changed")
    if (not isinstance(instruction, str) or not instruction or instruction != instruction.strip()
        or not isinstance(max_prompt_bytes, int) or isinstance(max_prompt_bytes, bool)
        or not 1 <= max_prompt_bytes <= 65536
        or not isinstance(max_output_bytes, int) or isinstance(max_output_bytes, bool)
        or not 1 <= max_output_bytes <= 32768):
        raise ValidationError("guide provider fixture limits or instruction are invalid")
    context, context_bytes = _load_object(context_file, "guide provider context")
    digest = hashlib.sha256(context_bytes).hexdigest()
    if digest != expected_context_sha256:
        raise ValidationError("guide provider context differs from trusted SHA-256")
    _validate_context_snapshot(context)
    inventory = context.get("dataset_inventory", {})
    if (context.get("context_version") != 2
        or inventory.get("non_synthetic_count") != 0):
        raise ValidationError("guide provider fixture requires a version-2 synthetic-only context")
    prompt = instruction.encode("utf-8") + b"\n" + context_bytes
    if len(prompt) > max_prompt_bytes:
        raise ValidationError("guide provider prompt exceeds the declared ceiling")
    receipt = {
        "provider_receipt_version": 1,
        "status": "fixture_response_ready",
        "provider_id": provider.provider_id,
        "data_destination": provider.data_destination,
        "disclosure_scope": "redacted_context_in_process_fixture_only",
        "context_sha256": digest,
        "prompt_sha256": hashlib.sha256(prompt).hexdigest(),
        "prompt_size_bytes": len(prompt),
        "max_prompt_bytes": max_prompt_bytes,
        "max_output_bytes": max_output_bytes,
        "output_sha256": None,
        "output_size_bytes": None,
        "cost_units": 0,
        "cost_ceiling_units": 0,
        "fallback_used": False,
        "external_call_performed": False,
        "model_invoked_by_faraday": False,
        "canonical_write_performed": False,
        "scientific_evidence_eligible": False,
        "error_code": None,
    }
    try:
        response = provider.complete(prompt, max_output_bytes=max_output_bytes)
        if not isinstance(response, bytes):
            raise ValidationError("guide provider output must be bytes")
        proposal = json.loads(
            response.decode("utf-8"),
            object_pairs_hook=_duplicate_pairs,
            parse_constant=_nonfinite,
        )
        if not isinstance(proposal, dict):
            raise ValidationError("guide provider output must be a proposal object")
        _validate_proposal(proposal, context, digest)
    except (ValidationError, UnicodeDecodeError, json.JSONDecodeError):
        receipt["status"] = "fixture_failed"
        receipt["error_code"] = (
            "provider_failure" if provider.response is None else "invalid_or_oversize_output"
        )
        return {"receipt": receipt, "proposal": None}
    receipt["output_sha256"] = hashlib.sha256(response).hexdigest()
    receipt["output_size_bytes"] = len(response)
    return {"receipt": receipt, "proposal": proposal}
