"""C04 fixed provider fixture has an exact, effect-free disclosure boundary."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from research_machine.adapters.filesystem import FileSystemRepository
from research_machine.application.commands import CreateInquiry
from research_machine.application.service import ResearchService
from research_machine.collaboration.guide_provider import (
    FixedResponseGuideProvider, run_fixed_guide_provider_fixture,
)
from research_machine.collaboration.proposal import create_context_snapshot
from research_machine.domain.errors import ValidationError
from test_guide_models import _proposal


def _fixture(tmp_path: Path) -> tuple[Path, str, bytes]:
    workspace = tmp_path / "workspace"
    service = ResearchService(FileSystemRepository(workspace), actor="guide-fixture")
    service.init_workspace()
    service.create_inquiry(CreateInquiry(
        "Synthetic provider fixture", "Could a fabricated comparison differ?",
        inquiry_id="guide-provider-v1",
    ))
    purpose = "Propose four synthetic models"
    snapshot = create_context_snapshot(
        service.collaborator_context(purpose=purpose), tmp_path / "context",
    )
    proposal = _proposal(
        snapshot["context_sha256"], purpose, "inquiry:guide-provider-v1"
    )
    return Path(snapshot["context_file"]), snapshot["context_sha256"], json.dumps(proposal).encode()


def test_fixed_provider_receipt_and_review_only_proposal(tmp_path: Path) -> None:
    context, digest, response = _fixture(tmp_path)
    before = context.read_bytes()
    result = run_fixed_guide_provider_fixture(
        context, digest, "Draft review-only alternatives.",
        FixedResponseGuideProvider(response),
    )
    receipt = result["receipt"]
    assert receipt["status"] == "fixture_response_ready"
    assert receipt["context_sha256"] == digest
    assert receipt["prompt_sha256"] == hashlib.sha256(
        b"Draft review-only alternatives.\n" + before
    ).hexdigest()
    assert receipt["output_sha256"] == hashlib.sha256(response).hexdigest()
    assert receipt["output_size_bytes"] == len(response)
    assert receipt["data_destination"] == "in_process_only"
    assert receipt["cost_units"] == receipt["cost_ceiling_units"] == 0
    assert receipt["fallback_used"] is False
    assert receipt["external_call_performed"] is False
    assert receipt["canonical_write_performed"] is False
    assert receipt["scientific_evidence_eligible"] is False
    assert all(item["authority"] == "review_only" for item in result["proposal"]["suggestions"])
    assert context.read_bytes() == before


def test_fixed_provider_fails_closed_without_fallback(tmp_path: Path) -> None:
    context, digest, response = _fixture(tmp_path)
    failed = run_fixed_guide_provider_fixture(
        context, digest, "Draft alternatives.", FixedResponseGuideProvider(None),
    )
    assert failed["proposal"] is None
    assert failed["receipt"]["status"] == "fixture_failed"
    assert failed["receipt"]["error_code"] == "provider_failure"
    assert failed["receipt"]["fallback_used"] is False
    assert failed["receipt"]["output_sha256"] is None

    oversized = run_fixed_guide_provider_fixture(
        context, digest, "Draft alternatives.",
        FixedResponseGuideProvider(response), max_output_bytes=16,
    )
    assert oversized["proposal"] is None
    assert oversized["receipt"]["error_code"] == "invalid_or_oversize_output"

    unauthorized = json.loads(response)
    unauthorized["suggestions"][0]["authority"] = "approved"
    invalid = run_fixed_guide_provider_fixture(
        context, digest, "Draft alternatives.",
        FixedResponseGuideProvider(json.dumps(unauthorized).encode()),
    )
    assert invalid["proposal"] is None
    assert invalid["receipt"]["status"] == "fixture_failed"
    assert invalid["receipt"]["external_call_performed"] is False

    with pytest.raises(ValidationError, match="trusted SHA-256"):
        run_fixed_guide_provider_fixture(
            context, "0" * 64, "Draft alternatives.", FixedResponseGuideProvider(response),
        )

    class UnexpectedAdapter(FixedResponseGuideProvider):
        called = False

        def complete(self, prompt: bytes, *, max_output_bytes: int) -> bytes:
            self.called = True
            return response

    adapter = UnexpectedAdapter(response)
    with pytest.raises(ValidationError, match="only its fixed"):
        run_fixed_guide_provider_fixture(context, digest, "Draft alternatives.", adapter)
    assert adapter.called is False
