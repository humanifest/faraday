"""Synthetic amendment timing prevents retrospective commitments from masquerading as prospective."""
from dataclasses import fields

import pytest

from research_machine.application.commands import CreateProtocol
from research_machine.domain.errors import ValidationError
from test_execution import prepared_service, frozen_formal_protocol


def amendment(tmp_path, timing, exposure):
    service, hypothesis = prepared_service(tmp_path)
    predecessor = frozen_formal_protocol(service, hypothesis)
    values = {field.name: getattr(predecessor, field.name) for field in fields(CreateProtocol)}
    amended = service.amend_protocol(
        predecessor.protocol_id, CreateProtocol(**values), "Improve the planned check",
        timing, exposure,
    )
    return service, predecessor, amended


def test_prospective_amendment_records_timing_and_preserves_predecessor(tmp_path):
    service, predecessor, amended = amendment(tmp_path, "before_collection", "not_seen")
    assert amended.supersedes_protocol_id == predecessor.protocol_id
    assert amended.amendment_timing == "before_collection"
    assert amended.evidence_exposure == "not_seen"
    assert service.get_protocol(predecessor.protocol_id).protocol_hash == predecessor.protocol_hash
    audit = service.audit_rigor()
    assert any(item.code == "PROSPECTIVE_PROTOCOL_AMENDMENT_DISCLOSED" for item in audit.findings)


@pytest.mark.parametrize("timing,exposure", [
    ("after_analysis", "full_data_seen"), ("unknown", "not_seen"),
    ("before_collection", "aggregate_seen"),
])
def test_retrospective_exposed_or_uncertain_amendment_is_flagged(tmp_path, timing, exposure):
    service, _, amended = amendment(tmp_path, timing, exposure)
    audit = service.audit_rigor()
    finding = next(item for item in audit.findings if item.entity_id == amended.protocol_id
                   and item.code == "RETROSPECTIVE_OR_EXPOSED_PROTOCOL_AMENDMENT")
    assert finding.severity.value == "warning"


@pytest.mark.parametrize("timing,exposure", [("later", "not_seen"), ("before_collection", "maybe")])
def test_invalid_amendment_disclosure_writes_nothing(tmp_path, timing, exposure):
    service, hypothesis = prepared_service(tmp_path)
    predecessor = frozen_formal_protocol(service, hypothesis)
    values = {field.name: getattr(predecessor, field.name) for field in fields(CreateProtocol)}
    before = len(service.list_protocols())
    with pytest.raises(ValidationError):
        service.amend_protocol(predecessor.protocol_id, CreateProtocol(**values), "reason", timing, exposure)
    assert len(service.list_protocols()) == before
    assert service.verify_ledger()["valid"]
