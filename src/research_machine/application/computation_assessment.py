"""Result-bound working assessments; no recommendation or evidence authority."""
import json
from research_machine.application.beginner_computation import NotebookComputation, encoded, sha
from research_machine.application.portable_computation import PortableComputation

FIELDS = ("interpretation", "uncertainty", "alternatives", "limitations", "followup_question", "decision_change")
NOTICE = "User-authored working assessment and unreviewed follow-up question. No scientific evidence, hypothesis review, ranked action recommendation or execution authority."


class ComputationAssessment(NotebookComputation):
    def __init__(self, service):
        self.service = service
        self.root = service.repository.root / "computation-assessments"
        self.computations = NotebookComputation(service)
        self.portable = PortableComputation(service.repository.root)

    def snapshot(self, source):
        if not isinstance(source, dict) or not isinstance(source.get("kind"), str):
            raise ValueError("An exact verified result reference is required.")
        kind = source["kind"]
        reference = {key: value for key, value in source.items() if key != "kind"}
        if kind == "notebook":
            if set(reference) not in ({"bundle_sha256", "receipt_sha256"}, {"bundle_sha256", "failure_sha256"}):
                raise ValueError("Supply one exact computation outcome hash.")
            value = self.computations.verify(**reference)
            bundle = value["bundle"]
            outcome = {key: value[key] for key in ("status", "result", "failure") if key in value}
        elif kind in {"portable_source", "portable_replay"}:
            if kind == "portable_source":
                if set(reference) != {"archive_sha256"}:
                    raise ValueError("Supply the exact retained source archive hash.")
                retained = self.portable.inspect(**reference)
                value = json.loads(retained["envelope"]["archive_json"])["computation"]
                if value["status"] not in {"verified_computation", "refused_computation"}:
                    raise ValueError("The archived source has no verified result or refusal to assess.")
                bundle = value["bundle"]
                outcome = {key: value[key] for key in ("status", "result", "failure") if key in value}
            else:
                if set(reference) not in ({"archive_sha256", "receipt_sha256"}, {"archive_sha256", "refusal_sha256"}):
                    raise ValueError("Supply the exact local replay outcome hash.")
                value = self.portable.verify_replay(**reference)
                bundle = json.loads(value["envelope"]["archive_json"])["computation"]["bundle"]
                outcome = {key: value[key] for key in ("status", "result", "refusal", "comparison") if key in value}
        else:
            raise ValueError("Unsupported working-result source.")
        return {"source": source, "bundle": bundle, "outcome": outcome,
                "scientific_evidence_eligible": False, "notice": NOTICE}

    def save(self, payload):
        if not isinstance(payload, dict) or set(payload) != {"source", "notes"}:
            raise ValueError("Supply the exact source reference and assessment notes only.")
        notes = payload["notes"]
        if (not isinstance(notes, dict) or set(notes) != set(FIELDS)
                or any(not isinstance(text, str) or not text or text != text.strip() or len(text) > 2000 for text in notes.values())):
            raise ValueError("Complete the six unpadded assessment fields with 1–2000 characters each.")
        snapshot = encoded(self.snapshot(payload["source"]))
        record = {"version": 1, "source": payload["source"], "source_snapshot_json": snapshot.decode(),
                  "source_snapshot_sha256": sha(snapshot), "notes": dict(notes),
                  "assessment_status": "unreviewed_working_notes", "followup_status": "unreviewed_user_proposal",
                  "action_recommendation_created": False, "scientific_evidence_eligible": False, "notice": NOTICE}
        raw = encoded(record); digest = sha(raw); directory = self.directory(digest)
        if directory.exists():
            return self.inspect(digest)
        self.root.mkdir(mode=0o700, exist_ok=True); directory.mkdir(mode=0o700)
        self.write(directory / "assessment.json", raw)
        return self.inspect(digest)

    def inspect(self, assessment_sha256):
        directory = self.directory(assessment_sha256); path = directory / "assessment.json"
        if path.is_symlink():
            raise ValueError("Symlinked working assessment.")
        raw = path.read_bytes()
        if sha(raw) != assessment_sha256:
            raise ValueError("Working assessment bytes changed.")
        record = json.loads(raw)
        if (record["assessment_status"] != "unreviewed_working_notes" or record["followup_status"] != "unreviewed_user_proposal"
                or record["action_recommendation_created"] is not False or record["scientific_evidence_eligible"] is not False
                or record["notice"] != NOTICE):
            raise ValueError("Working assessment authority differs.")
        snapshot = encoded(self.snapshot(record["source"]))
        if snapshot.decode() != record["source_snapshot_json"] or sha(snapshot) != record["source_snapshot_sha256"]:
            raise ValueError("Current result no longer matches the retained assessment source.")
        return {"status": "verified_working_assessment", "assessment_sha256": assessment_sha256, "record": record,
                "canonical_write_performed": False, "scientific_evidence_eligible": False,
                "action_recommendation_created": False}
