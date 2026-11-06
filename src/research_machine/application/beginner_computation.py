"""Retained exploratory computations linked to an exact canonical draft.

These bundles are working artifacts, not frozen protocols or scientific evidence.
Only the bundled mean-difference method runs; no caller code or paths are accepted.
"""
import csv
import hashlib
import inspect
import io
import json
import os
from pathlib import Path
import re

from research_machine.addons.execution import execute_analysis
from research_machine.addons.receipt import verify_execution_output
from research_machine.addons.registry import default_registry
from research_machine.application.beginner_design import notebook_protocol_draft
from research_machine.domain.errors import ValidationError

NOTICE = "Exploratory working computation only; draft protocol is not frozen. No scientific evidence, causal conclusion, review approval or independent replication."


def encoded(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode()


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def method_identity():
    _, method = default_registry(include_installed=False).resolve_method("independent_mean_difference_ci")
    return {"method": method.method_id,
            "implementation_sha256": sha(Path(inspect.getsourcefile(method.runner)).read_bytes())}


class NotebookComputation:
    def __init__(self, service):
        self.service = service
        self.root = service.repository.root / "notebook-computations"

    def directory(self, digest):
        if not isinstance(digest, str) or re.fullmatch(r"[a-f0-9]{64}", digest) is None:
            raise ValueError("An exact retained bundle SHA-256 is required.")
        directory = self.root / digest
        for path in (self.root.parent, self.root, directory):
            if path.is_symlink():
                raise ValueError("Symlinked computation storage is unsupported.")
        return directory

    @staticmethod
    def write(path, raw):
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
        with os.fdopen(fd, "wb") as stream:
            stream.write(raw)

    def prepare(self, payload):
        if not isinstance(payload, dict) or set(payload) != {"checked_draft", "specification_json", "input_csv", "provenance"}:
            raise ValueError("Supply the exact checked draft, JSON specification, CSV and provenance only.")
        for field, limit in (("specification_json", 12000), ("input_csv", 40000), ("provenance", 4000)):
            text = payload[field]
            if not isinstance(text, str) or not text.strip() or len(text.encode()) > limit:
                raise ValueError("Specification, data and provenance must be nonempty bounded UTF-8 text.")
        checked = notebook_protocol_draft(self.service, payload["checked_draft"])
        if checked["status"] != "notebook_protocol_draft":
            raise ValueError("Save and inspect the exact protocol draft first.")
        identity = method_identity()
        if checked["protocol"]["analysis_code_hash"] != identity["implementation_sha256"]:
            raise ValueError("Draft implementation hash differs from the bundled method; revise and recheck the design.")
        spec = json.loads(payload["specification_json"])
        if (not isinstance(spec, dict) or spec.get("method") != identity["method"]
                or type(spec.get("bootstrap_resamples")) is not int
                or not 100 <= spec["bootstrap_resamples"] <= 5000
                or type(spec.get("seed")) is not int
                or not isinstance(spec.get("unit_column"), str) or not spec["unit_column"]):
            raise ValueError("Use the bundled mean-difference method, explicit unit column, integer seed and 100–5000 resamples.")
        rows = list(csv.reader(io.StringIO(payload["input_csv"])))
        if not 3 <= len(rows) <= 1001:
            raise ValueError("CSV must have a header and 2–1000 records.")
        hypothesis = self.service.get_hypothesis(checked["design"]["hypothesis_id"], checked["design"]["inquiry_id"])
        if hypothesis.contrast_definition and spec.get("contrast_definition") != hypothesis.contrast_definition:
            raise ValueError("The specification differs from the sealed signed contrast.")
        if hypothesis.contrast_groups and spec.get("groups") != hypothesis.contrast_groups:
            raise ValueError("The specification differs from the sealed group order.")
        bundle = {"version": 1, "checked_draft": payload["checked_draft"],
                  "protocol_id": checked["protocol"]["protocol_id"],
                  "draft_payload_sha256": checked["draft_payload_sha256"],
                  "data_scope": checked["design"]["design"]["data_scope"],
                  "specification_json": payload["specification_json"], "input_csv": payload["input_csv"],
                  "provenance": payload["provenance"], **identity,
                  "specification_sha256": sha(payload["specification_json"].encode()),
                  "input_sha256": sha(payload["input_csv"].encode()),
                  "notice": NOTICE, "scientific_evidence_eligible": False}
        digest = sha(encoded(bundle))
        directory = self.directory(digest)
        if directory.exists():
            return self.inspect(digest)
        self.root.mkdir(mode=0o700, exist_ok=True)
        directory.mkdir(mode=0o700)
        self.write(directory / "analysis.json", payload["specification_json"].encode())
        self.write(directory / "input.csv", payload["input_csv"].encode())
        self.write(directory / "bundle.json", encoded(bundle))
        return self.inspect(digest)

    def inspect(self, bundle_sha256):
        directory = self.directory(bundle_sha256)
        for name in ("bundle.json", "analysis.json", "input.csv"):
            if (directory / name).is_symlink():
                raise ValueError("Symlinked computation artifact.")
        raw = (directory / "bundle.json").read_bytes()
        if sha(raw) != bundle_sha256:
            raise ValueError("Retained computation bundle changed.")
        bundle = json.loads(raw)
        checked = notebook_protocol_draft(self.service, bundle["checked_draft"])
        if (checked.get("status") != "notebook_protocol_draft"
                or checked["draft_payload_sha256"] != bundle["draft_payload_sha256"]
                or checked["protocol"]["protocol_id"] != bundle["protocol_id"]
                or method_identity()["implementation_sha256"] != bundle["implementation_sha256"]
                or (directory / "analysis.json").read_bytes() != bundle["specification_json"].encode()
                or (directory / "input.csv").read_bytes() != bundle["input_csv"].encode()):
            raise ValueError("Draft, implementation or retained input bytes changed.")
        return {"status": "prepared_computation", "bundle_sha256": bundle_sha256, "bundle": bundle,
                "attempted": (directory / "attempt.json").exists() or (directory / "attempt.json").is_symlink(),
                "canonical_write_performed": False, "scientific_evidence_eligible": False}

    def run(self, bundle_sha256):
        prepared = self.inspect(bundle_sha256)
        bundle = prepared["bundle"]
        directory = self.directory(bundle_sha256)
        output = directory / "execution"
        if output.exists() or output.is_symlink():
            raise ValueError("Execution output already exists; preserve it for inspection.")
        # Write-once attempt marker also covers failures before native output exists.
        self.write(directory / "attempt.json", encoded({"bundle_sha256": bundle_sha256}))
        try:
            execute_analysis(registry=default_registry(include_installed=False),
                             spec_path=directory / "analysis.json", data_path=directory / "input.csv", output_dir=output,
                             expected_spec_sha256=bundle["specification_sha256"], expected_input_sha256=bundle["input_sha256"])
        except ValidationError as error:
            failure = {"status": "execution_refused", "bundle_sha256": bundle_sha256,
                       "error": str(error).replace(str(directory), "$COMPUTATION"), "notice": NOTICE,
                       "scientific_evidence_eligible": False}
            raw = encoded(failure)
            self.write(directory / "failure.json", raw)
            return self.verify(bundle_sha256, failure_sha256=sha(raw))
        digest = sha((output / "execution-receipt.json").read_bytes())
        return self.verify(bundle_sha256, digest)

    def verify(self, bundle_sha256, receipt_sha256=None, failure_sha256=None):
        prepared = self.inspect(bundle_sha256)
        directory = self.directory(bundle_sha256)
        if (receipt_sha256 is None) == (failure_sha256 is None):
            raise ValueError("Supply exactly one retained execution receipt or refusal hash.")
        if failure_sha256 is not None:
            path = directory / "failure.json"
            if path.is_symlink():
                raise ValueError("Symlinked refusal artifact.")
            raw = path.read_bytes()
            failure = json.loads(raw)
            if (sha(raw) != failure_sha256 or failure.get("bundle_sha256") != bundle_sha256
                    or failure.get("status") != "execution_refused" or failure.get("scientific_evidence_eligible") is not False):
                raise ValueError("Execution refusal differs from retained commitment.")
            return {**prepared, "status": "refused_computation", "failure_sha256": failure_sha256,
                    "failure": failure, "notice": NOTICE}
        if (directory / "execution").is_symlink():
            raise ValueError("Symlinked execution output.")
        result = verify_execution_output(directory / "execution", receipt_sha256)
        receipt, bundle = result["receipt"], prepared["bundle"]
        if (receipt["specification"]["sha256"] != bundle["specification_sha256"]
                or receipt["input"]["sha256"] != bundle["input_sha256"]
                or receipt["implementation"]["sha256"] != bundle["implementation_sha256"]
                or receipt["method"] != bundle["method"]):
            raise ValueError("Execution is not bound to the retained draft computation.")
        return {**prepared, "status": "verified_computation", "receipt_sha256": receipt_sha256,
                "result": result["result"], "method": receipt["method"],
                "environment": receipt["environment"], "notice": NOTICE}
