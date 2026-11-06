"""Read-only computational design preflight bound to an exact sealed hypothesis."""
import hashlib
import json
import re
from research_machine.application.beginner import inspect_saved_inquiry, validate_planning_notes
from research_machine.application.commands import CreateProtocol
from research_machine.domain.errors import ValidationError
from research_machine.domain.models import AnalysisMode, ProtocolKind

DESIGN_FIELDS = ("data_scope", "safety_constraints", "methodology", "inputs_required", "sample_size_or_stopping_rule",
                 "quality_requirements", "controls", "missing_data_policy", "success_conditions",
                 "failure_conditions", "expected_outputs", "environment_requirements", "analysis_code_hash")
LIST_FIELDS = {"safety_constraints", "inputs_required", "quality_requirements", "controls", "success_conditions",
               "failure_conditions", "expected_outputs", "environment_requirements"}


def validate_design_notes(value):
    if (not isinstance(value, dict) or set(value) != set(DESIGN_FIELDS)
            or any(not isinstance(text, str) or len(text) > 2000 for text in value.values())):
        raise ValueError("Computational design notes require the exact bounded text fields.")
    return dict(value)


def preview_notebook_design(service, payload):
    if not isinstance(payload, dict) or set(payload) != {"inquiry_id", "original_statement", "hypothesis_id", "hypothesis_sha256", "planning", "design"}:
        raise ValueError("Supply the exact saved question, sealed hypothesis and working design.")
    if not isinstance(payload["inquiry_id"], str):
        raise ValueError("An explicit saved inquiry is required.")
    if inspect_saved_inquiry(service, payload["original_statement"], payload["inquiry_id"])["status"] != "matching_complete":
        raise ValueError("The original saved inquiry was not verified.")
    h = service.get_hypothesis(payload["hypothesis_id"], payload["inquiry_id"])
    if not isinstance(payload["hypothesis_sha256"], str) or h.scientific_content_sha256 != payload["hypothesis_sha256"]:
        raise ValueError("Hypothesis content commitment changed.")
    planning = validate_planning_notes(payload["planning"])
    design = validate_design_notes(payload["design"])
    for field in ("title", "outcome"):
        if not planning.get(field, "").strip():
            raise ValueError("Enter a study title and primary outcome in the planning notes.")
    if any(text != text.strip() for text in list(design.values()) + list(planning.values())):
        raise ValueError("Preserve unpadded design and planning text.")
    if design["data_scope"] not in {"synthetic", "existing_nonhuman"}:
        raise ValueError("Choose declared synthetic or existing non-human data. Human-related or uncertain data needs a separate reviewed path.")
    fields = {}
    for key, text in design.items():
        if key == "data_scope":
            continue
        if key in LIST_FIELDS:
            lines = [] if not text else text.split("\n")
            if len(lines) > 20 or any(not line or line != line.strip() for line in lines) or len(set(lines)) != len(lines):
                raise ValueError("Use up to 20 unique, nonblank list lines.")
            fields[key] = lines
        else:
            fields[key] = text
    if fields["analysis_code_hash"] and re.fullmatch(r"[a-f0-9]{64}", fields["analysis_code_hash"]) is None:
        raise ValueError("Implementation identity must be a lowercase SHA-256 or visibly unresolved.")
    request_digest = hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode()).hexdigest()
    protocol_input = {"experiment_id": "notebook-design-" + request_digest, "title": planning["title"],
                      "analysis_mode": "exploratory", "protocol_kind": "computational",
                      "hypotheses_tested": [h.hypothesis_id], "primary_outcome": planning["outcome"],
                      "sampling_unit": planning.get("unit_of_observation", ""), "human_subjects": False, **fields}
    command = CreateProtocol(**{**protocol_input, "analysis_mode": AnalysisMode.EXPLORATORY,
                               "protocol_kind": ProtocolKind.COMPUTATIONAL})
    before = service.verify_ledger(payload["inquiry_id"])
    try:
        native = service.preflight_protocol(command, payload["inquiry_id"])
        if native["hypothesis_commitments"].get(h.hypothesis_id) != h.scientific_content_sha256:
            raise ValueError("Native preflight did not bind the exact hypothesis.")
        status, reason = "ready_at_check_time", "Native freeze preflight passed; no protocol was created or frozen."
    except ValidationError as error:
        native = None
        status, reason = "blocked", str(error)
    if service.verify_ledger(payload["inquiry_id"]) != before:
        raise ValueError("Read-only preflight unexpectedly changed the inquiry ledger.")
    digest = hashlib.sha256(json.dumps({"request": payload, "protocol_input": protocol_input}, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode()).hexdigest()
    return {"status": status, "authority": "review_only", "canonical_write_performed": False,
            "analysis_performed": False, "scientific_evidence_eligible": False,
            "inquiry_id": payload["inquiry_id"], "original_statement": payload["original_statement"],
            "hypothesis_id": h.hypothesis_id, "hypothesis_sha256": h.scientific_content_sha256,
            "hypothesis_statement": h.statement, "hypothesis_workflow_state": h.workflow_state.value,
            "planning": planning, "design": design, "protocol_input": protocol_input,
            "design_input_sha256": digest, "unresolved_fields": [key for key, value in design.items() if not value],
            "reason": reason, "native_preflight": native,
            "notice": "Declared synthetic/non-human exploratory computation only; this declaration does not verify data rights, ethics or scientific validity. Readiness is not approval, creation, freeze, execution or evidence. A blocked reason is the first native refusal, not an exhaustive review."}


def notebook_protocol_draft(service, payload, *, write=False):
    """Create/read only an exact draft through the canonical service, never freeze."""
    if not isinstance(payload, dict) or set(payload) != {"request", "design_input_sha256"}:
        raise ValueError("Supply the checked design request and exact input commitment only.")
    checked = preview_notebook_design(service, payload["request"])
    if not isinstance(payload["design_input_sha256"], str) or checked["design_input_sha256"] != payload["design_input_sha256"]:
        raise ValueError("The design changed after checking; recheck before any save.")
    inquiry_id = checked["inquiry_id"]
    expected = checked["protocol_input"]
    protocols = [p for p in service.list_protocols(inquiry_id) if p.experiment_id == expected["experiment_id"]]
    events = [e for e in service.repository._verified_ledger_events(inquiry_id)
              if e.get("command") == "protocol.create" and e.get("payload", {}).get("experiment_id") == expected["experiment_id"]]
    created = False
    if not protocols and not events:
        if not write:
            return {"status": "not_found", "design": checked, "canonical_write_performed": False,
                    "analysis_performed": False, "scientific_evidence_eligible": False}
        command = CreateProtocol(**{**expected, "analysis_mode": AnalysisMode.EXPLORATORY,
                                   "protocol_kind": ProtocolKind.COMPUTATIONAL})
        service.create_protocol(command, inquiry_id)
        created = True
        protocols = [p for p in service.list_protocols(inquiry_id) if p.experiment_id == expected["experiment_id"]]
        events = [e for e in service.repository._verified_ledger_events(inquiry_id)
                  if e.get("command") == "protocol.create" and e.get("payload", {}).get("experiment_id") == expected["experiment_id"]]
    if len(protocols) != 1 or len(events) != 1:
        raise ValueError("Incomplete or ambiguous draft history; no replacement or blind retry.")
    protocol = protocols[0]
    record = protocol.to_dict()
    if (record.get("status") != "draft" or record.get("protocol_hash") is not None
            or events[0]["payload"] != record or any(record.get(key) != value for key, value in expected.items())):
        raise ValueError("The stored protocol differs from its exact draft commitment; inspect native history.")
    ledger = service.verify_ledger(inquiry_id)
    if ledger.get("valid") is not True:
        raise ValueError("Protocol draft ledger is not valid.")
    digest = hashlib.sha256(json.dumps(record, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode()).hexdigest()
    return {"status": "notebook_protocol_draft", "design": checked, "protocol": record,
            "draft_payload_sha256": digest, "ledger": ledger,
            "canonical_write_performed": created, "analysis_performed": False,
            "scientific_evidence_eligible": False,
            "notice": "Saved draft only; not frozen, executable authorization, scientific approval or evidence. Working-note changes create a separate draft, never an amendment or replacement of a frozen protocol."}
