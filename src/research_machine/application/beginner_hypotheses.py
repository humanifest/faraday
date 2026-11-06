"""Notebook proposal input over existing sealed, unreviewed hypotheses."""
import hashlib
import json
from research_machine.application.beginner import inspect_saved_inquiry
from research_machine.application.commands import ProposeHypothesis

FIELDS = ("statement", "observable_prediction", "null_model", "competing_models", "falsification_conditions", "scope", "lineage")


def validate_hypothesis_notes(value):
    if (not isinstance(value, dict) or set(value) != set(FIELDS)
            or any(not isinstance(text, str) or len(text) > 2000 for text in value.values())):
        raise ValueError("Hypothesis notes require the scientific text fields and optional lineage of at most 2000 characters.")
    return dict(value)


def notebook_hypothesis(service, payload, *, write=False):
    if not isinstance(payload, dict) or set(payload) != {"inquiry_id", "original_statement", "proposal"}:
        raise ValueError("Supply an exact saved question and proposal only.")
    if not isinstance(payload["inquiry_id"], str):
        raise ValueError("An explicit saved inquiry is required.")
    proposal = validate_hypothesis_notes(payload["proposal"])
    if any((not text.strip() and field != "lineage") or text != text.strip() for field, text in proposal.items()):
        raise ValueError("Complete every hypothesis field without surrounding whitespace.")
    lists = {}
    for field in ("competing_models", "falsification_conditions", "lineage"):
        lines = [] if field == "lineage" and not proposal[field] else proposal[field].split("\n")
        if (len(lines) > 20 or any(not line or line != line.strip() for line in lines)
                or len(set(lines)) != len(lines)):
            raise ValueError("Use up to 20 unique, nonblank, unpadded lines.")
        lists[field] = lines
    inspection = inspect_saved_inquiry(service, payload["original_statement"], payload["inquiry_id"])
    if inspection["status"] != "matching_complete":
        raise ValueError("The exact saved question and unresolved pathway were not verified.")
    digest = hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":"),
                                      allow_nan=False).encode()).hexdigest()
    tag = "notebook-proposal-sha256:" + digest
    hypotheses = [h for h in service.list_hypotheses(payload["inquiry_id"]) if tag in h.source_context]
    events = [e for e in service.repository._verified_ledger_events(payload["inquiry_id"])
              if e.get("command") == "hypothesis.propose" and tag in e.get("payload", {}).get("source_context", [])]
    created = False
    if hypotheses or events:
        if (len(hypotheses) != 1 or len(events) != 1
                or events[0]["payload"] != hypotheses[0].to_dict()
                or hypotheses[0].workflow_state.value != "unreviewed"):
            raise ValueError("Existing proposal and committed history need inspection; no replacement or retry.")
        hypothesis = hypotheses[0]
        expected = {**proposal, **lists}
        if any(getattr(hypothesis, field) != value for field, value in expected.items()):
            raise ValueError("Existing scientific proposition differs from the submitted proposal.")
    elif not write:
        return {"status": "not_found", "request_sha256": digest, "canonical_write_performed": False,
                "scientific_evidence_eligible": False, "original_statement": payload["original_statement"],
                "inquiry_id": payload["inquiry_id"], "proposal": proposal}
    else:
        hypothesis = service.propose_hypothesis(ProposeHypothesis(
            **{field: proposal[field] for field in FIELDS if field not in lists}, **lists,
            generated_by="beginner-notebook-contributor-unverified",
            source_context=[tag, "Explicit notebook proposal; contributor identity unverified; no approval."]),
            payload["inquiry_id"])
        created = True
    return {"status": "unreviewed_hypothesis", "request_sha256": digest,
            "inquiry_id": payload["inquiry_id"], "original_statement": payload["original_statement"],
            "proposal": proposal, "hypothesis": hypothesis.to_dict(),
            "ledger": service.verify_ledger(payload["inquiry_id"]),
            "canonical_write_performed": created, "scientific_evidence_eligible": False}
