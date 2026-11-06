"""Portable working archives; no canonical import or scientific authority."""
import json
from pathlib import Path
import tempfile

from research_machine.addons.execution import execute_analysis
from research_machine.addons.receipt import verify_execution_output
from research_machine.addons.registry import default_registry
from research_machine.application.beginner_computation import NotebookComputation, encoded, sha, method_identity
from research_machine.application.beginner_design import DESIGN_FIELDS, LIST_FIELDS
from research_machine.application.hypothesis_integrity import validate_hypothesis_scientific_commitment
from research_machine.domain.models import Hypothesis, ExperimentProtocol
from research_machine.domain.errors import ValidationError

FORMAT = "faraday-portable-computation-v1"
SCOPE = "Archive hash consistency only; source identity and chronology are unauthenticated. Receipt locators are redacted and its portable hash differs from the retained source receipt hash. No canonical records, scientific evidence, approval or independent replication."


def export_computation(work, reference):
    if not isinstance(reference, dict) or set(reference) not in ({"bundle_sha256"}, {"bundle_sha256", "receipt_sha256"}, {"bundle_sha256", "failure_sha256"}):
        raise ValueError("Supply retained computation commitments only.")
    value = work.inspect(**reference) if len(reference) == 1 else work.verify(**reference)
    b = value["bundle"]
    request = b["checked_draft"]["request"]
    service = work.service
    protocol = next(p for p in service.list_protocols(request["inquiry_id"]) if p.protocol_id == b["protocol_id"])
    context = {"protocol": protocol.to_dict(), "hypothesis": service.get_hypothesis(request["hypothesis_id"], request["inquiry_id"]).to_dict()}
    outcome = {}
    directory = work.directory(value["bundle_sha256"])
    if value["status"] == "verified_computation":
        receipt = json.loads((directory / "execution" / "execution-receipt.json").read_bytes())
        for field, locator in (("specification", "analysis.json"), ("input", "input.csv"), ("implementation", "bundled-method")):
            receipt[field]["locator"] = locator
        outcome = {"receipt_json": encoded(receipt).decode(),
                   "result_json": (directory / "execution" / "analysis-result.json").read_text()}
    elif value["status"] == "refused_computation":
        outcome = {"failure_json": (directory / "failure.json").read_text()}
    archive = {"version": 1, "computation": value, "context": context,
               "source_outcome": outcome, "scope": SCOPE, "scientific_evidence_eligible": False}
    envelope = {"format": FORMAT, "archive_sha256": sha(encoded(archive)), "archive_json": encoded(archive).decode()}
    validate_archive(envelope)
    return envelope


def validate_archive(envelope):
    try:
        return _validate_archive(envelope)
    except (KeyError, TypeError, AttributeError, OverflowError, RecursionError) as error:
        raise ValueError("Malformed portable working archive.") from error


def _validate_archive(envelope):
    if (not isinstance(envelope, dict) or set(envelope) != {"format", "archive_sha256", "archive_json"}
            or envelope["format"] != FORMAT or len(encoded(envelope)) > 1000000):
        raise ValueError("A bounded portable working archive is required.")
    archive = json.loads(envelope["archive_json"])
    if (not isinstance(archive, dict) or set(archive) != {"version", "computation", "context", "source_outcome", "scope", "scientific_evidence_eligible"}
            or type(archive["version"]) is not int or archive["version"] != 1
            or archive["scope"] != SCOPE or archive["scientific_evidence_eligible"] is not False
            or sha(envelope["archive_json"].encode()) != envelope["archive_sha256"] or encoded(archive).decode() != envelope["archive_json"]):
        raise ValueError("Archive content differs from its commitment or scope.")
    value, context = archive["computation"], archive["context"]
    if (not isinstance(value, dict) or value.get("status") not in {"prepared_computation", "verified_computation", "refused_computation"}
            or value.get("scientific_evidence_eligible") is not False or value.get("canonical_write_performed") is not False
            or type(value.get("attempted")) is not bool or (value.get("status") != "prepared_computation" and value.get("attempted") is not True) or not isinstance(context, dict) or set(context) != {"protocol", "hypothesis"}):
        raise ValueError("Invalid working-computation authority or context.")
    b = value["bundle"]
    if sha(encoded(b)) != value["bundle_sha256"] or b.get("scientific_evidence_eligible") is not False:
        raise ValueError("Input bundle commitment differs.")
    request = b["checked_draft"]["request"]
    protocol, hypothesis = ExperimentProtocol.from_dict(context["protocol"]), Hypothesis.from_dict(context["hypothesis"])
    validate_hypothesis_scientific_commitment(hypothesis)
    if protocol.to_dict() != context["protocol"] or hypothesis.to_dict() != context["hypothesis"]:
        raise ValueError("Context must retain exact canonical-shaped snapshots.")
    p = context["protocol"]
    if (sha(encoded(p)) != b["draft_payload_sha256"] or p["protocol_id"] != b["protocol_id"]
            or p["status"] != "draft" or p["protocol_hash"] is not None or p["human_subjects"] is not False
            or p["hypotheses_tested"] != [hypothesis.hypothesis_id]
            or request["hypothesis_id"] != hypothesis.hypothesis_id or request["hypothesis_sha256"] != hypothesis.scientific_content_sha256
            or b["data_scope"] not in {"synthetic", "existing_nonhuman"} or b["data_scope"] != request["design"]["data_scope"]):
        raise ValueError("Archived draft or hypothesis binding differs.")
    protocol_input = {"experiment_id": "notebook-design-" + sha(encoded(request)), "title": request["planning"]["title"],
                      "analysis_mode": "exploratory", "protocol_kind": "computational", "hypotheses_tested": [hypothesis.hypothesis_id],
                      "primary_outcome": request["planning"]["outcome"], "sampling_unit": request["planning"].get("unit_of_observation", ""),
                      "human_subjects": False}
    for key in DESIGN_FIELDS:
        if key != "data_scope":
            text = request["design"][key]
            protocol_input[key] = (text.split("\n") if text else []) if key in LIST_FIELDS else text
    if (any(p.get(key) != val for key, val in protocol_input.items())
            or sha(encoded({"request": request, "protocol_input": protocol_input})) != b["checked_draft"]["design_input_sha256"]):
        raise ValueError("Archived checked design differs from its draft.")
    for field, limit in (("specification_json", 12000), ("input_csv", 40000), ("provenance", 4000)):
        if not isinstance(b.get(field), str) or not b[field].strip() or len(b[field].encode()) > limit:
            raise ValueError("Archived inputs exceed the working-computation bounds.")
    if (sha(b["specification_json"].encode()) != b["specification_sha256"] or sha(b["input_csv"].encode()) != b["input_sha256"]
            or b["implementation_sha256"] != p["analysis_code_hash"] or b["method"] != "independent_mean_difference_ci"):
        raise ValueError("Archived input or implementation identity differs.")
    spec = json.loads(b["specification_json"])
    if ((hypothesis.contrast_definition and spec.get("contrast_definition") != hypothesis.contrast_definition)
            or (hypothesis.contrast_groups and spec.get("groups") != hypothesis.contrast_groups)):
        raise ValueError("Archived specification differs from the sealed signed contrast.")
    outcome = archive["source_outcome"]
    if value["status"] == "verified_computation":
        if set(outcome) != {"receipt_json", "result_json"}:
            raise ValueError("Completed source needs exact portable receipt and output bytes.")
        receipt = json.loads(outcome["receipt_json"])
        if any(receipt[field]["locator"] != locator for field, locator in (("specification", "analysis.json"), ("input", "input.csv"), ("implementation", "bundled-method"))):
            raise ValueError("Portable receipt locators must be redacted.")
        with tempfile.TemporaryDirectory(prefix="faraday-portable-check-") as tmp:
            root = Path(tmp)
            (root / "execution-receipt.json").write_text(outcome["receipt_json"])
            (root / "analysis-result.json").write_text(outcome["result_json"])
            verified = verify_execution_output(root, sha(outcome["receipt_json"].encode()))
        if (verified["result"] != value.get("result") or receipt["environment"] != value.get("environment")
                or receipt["method"] != b["method"] or value.get("method") != b["method"]
                or receipt["specification"]["sha256"] != b["specification_sha256"]
                or receipt["input"]["sha256"] != b["input_sha256"]
                or receipt["implementation"]["sha256"] != b["implementation_sha256"]):
            raise ValueError("Archived result is not bound to the archived inputs.")
    elif value["status"] == "refused_computation":
        if set(outcome) != {"failure_json"} or sha(outcome["failure_json"].encode()) != value.get("failure_sha256"):
            raise ValueError("Archived refusal commitment differs.")
        failure = json.loads(outcome["failure_json"])
        if (failure != value.get("failure") or failure.get("bundle_sha256") != value["bundle_sha256"]
                or failure.get("status") != "execution_refused" or failure.get("scientific_evidence_eligible") is not False or "result" in value):
            raise ValueError("Archived refusal must not assert a numerical result.")
    elif outcome or "result" in value or "failure" in value:
        raise ValueError("Prepared source must not claim a completed outcome.")
    return archive


class PortableComputation(NotebookComputation):
    """Retain imported working archives without initializing a canonical workspace."""
    def __init__(self, workspace):
        self.root = Path(workspace) / "portable-computations"

    def restore(self, envelope):
        validate_archive(envelope)
        digest = envelope["archive_sha256"]
        directory = self.directory(digest)
        if directory.exists():
            return self.inspect(digest)
        self.root.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        self.root.mkdir(mode=0o700, exist_ok=True)
        directory.mkdir(mode=0o700)
        self.write(directory / "archive.json", encoded(envelope))
        b = json.loads(envelope["archive_json"])["computation"]["bundle"]
        self.write(directory / "analysis.json", b["specification_json"].encode())
        self.write(directory / "input.csv", b["input_csv"].encode())
        return self.inspect(digest)

    def inspect(self, archive_sha256):
        directory = self.directory(archive_sha256)
        for name in ("archive.json", "analysis.json", "input.csv"):
            if (directory / name).is_symlink():
                raise ValueError("Symlinked portable artifact.")
        envelope = json.loads((directory / "archive.json").read_bytes())
        archive = validate_archive(envelope)
        b = archive["computation"]["bundle"]
        if (envelope["archive_sha256"] != archive_sha256
                or (directory / "analysis.json").read_bytes() != b["specification_json"].encode()
                or (directory / "input.csv").read_bytes() != b["input_csv"].encode()):
            raise ValueError("Retained portable inputs changed.")
        return {"status": "retained_portable_computation", "archive_sha256": archive_sha256,
                "envelope": envelope, "replay_attempted": (directory / "replay-attempt.json").exists() or (directory / "replay-attempt.json").is_symlink(),
                "canonical_write_performed": False, "scientific_evidence_eligible": False, "scope": SCOPE}

    def replay(self, archive_sha256):
        retained = self.inspect(archive_sha256)
        b = json.loads(retained["envelope"]["archive_json"])["computation"]["bundle"]
        if method_identity() != {"method": b["method"], "implementation_sha256": b["implementation_sha256"]}:
            raise ValueError("Current bundled implementation differs; viewing remains available, replay is blocked.")
        # Repeat the exact same bounded runner checks as local computations.
        spec = json.loads(b["specification_json"])
        import csv, io
        if (type(spec.get("bootstrap_resamples")) is not int or not 100 <= spec["bootstrap_resamples"] <= 5000
                or type(spec.get("seed")) is not int or spec.get("method") != b["method"]
                or not isinstance(spec.get("unit_column"), str) or not spec["unit_column"]
                or not 3 <= len(list(csv.reader(io.StringIO(b["input_csv"])))) <= 1001):
            raise ValueError("Portable replay exceeds the bounded runner contract.")
        directory = self.directory(archive_sha256)
        output = directory / "replay"
        if output.exists() or output.is_symlink():
            raise ValueError("Replay output already exists; preserve it.")
        self.write(directory / "replay-attempt.json", encoded({"archive_sha256": archive_sha256}))
        try:
            execute_analysis(registry=default_registry(include_installed=False), spec_path=directory / "analysis.json", data_path=directory / "input.csv",
                             output_dir=output, expected_spec_sha256=b["specification_sha256"], expected_input_sha256=b["input_sha256"])
        except ValidationError as error:
            raw = encoded({"status": "execution_refused", "archive_sha256": archive_sha256,
                           "error": str(error).replace(str(directory), "$PORTABLE"), "scientific_evidence_eligible": False})
            self.write(directory / "replay-refusal.json", raw)
            return self.verify_replay(archive_sha256, refusal_sha256=sha(raw))
        return self.verify_replay(archive_sha256, receipt_sha256=sha((output / "execution-receipt.json").read_bytes()))

    def verify_replay(self, archive_sha256, receipt_sha256=None, refusal_sha256=None):
        retained = self.inspect(archive_sha256)
        directory = self.directory(archive_sha256)
        source = json.loads(retained["envelope"]["archive_json"])
        if (receipt_sha256 is None) == (refusal_sha256 is None):
            raise ValueError("Supply exactly one pinned replay outcome hash.")
        if refusal_sha256 is not None:
            path = directory / "replay-refusal.json"
            if path.is_symlink(): raise ValueError("Symlinked replay refusal.")
            raw = path.read_bytes(); refusal = json.loads(raw)
            if sha(raw) != refusal_sha256 or refusal.get("archive_sha256") != archive_sha256 or refusal.get("status") != "execution_refused" or refusal.get("scientific_evidence_eligible") is not False:
                raise ValueError("Replay refusal differs from its commitment.")
            return {**retained, "status": "verified_portable_refusal", "refusal_sha256": refusal_sha256,
                    "refusal": refusal, "comparison": "No numerical result; archived source preserved."}
        verified = verify_execution_output(directory / "replay", receipt_sha256)
        receipt, b = verified["receipt"], source["computation"]["bundle"]
        if (receipt["specification"]["sha256"] != b["specification_sha256"] or receipt["input"]["sha256"] != b["input_sha256"]
                or receipt["implementation"]["sha256"] != b["implementation_sha256"] or receipt["method"] != b["method"]):
            raise ValueError("Replay does not match the archived computation.")
        comparison = "Source had no verified numerical result; this is a new working computation."
        if "result_json" in source["source_outcome"]:
            comparison = "Byte-identical result replay." if (directory / "replay" / "analysis-result.json").read_bytes() == source["source_outcome"]["result_json"].encode() else "Result differs from the archived source; preserve and investigate both outcomes."
        return {**retained, "status": "verified_portable_replay", "receipt_sha256": receipt_sha256,
                "result": verified["result"], "comparison": comparison}
