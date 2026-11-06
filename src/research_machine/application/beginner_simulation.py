"""Bounded synthetic analysis workbench over the existing execution contracts.

Retained recipes are software artifacts, never canonical scientific protocols.
"""
from __future__ import annotations
import hashlib
import json
import os
from pathlib import Path
import re
import secrets
from research_machine.addons.execution import execute_analysis
from research_machine.addons.receipt import verify_execution_output
from research_machine.addons.registry import default_registry

CASES = ("positive", "null", "negative", "missing", "invalid")
NOTICE = "Synthetic software simulation only. No physical measurement, scientific evidence, review approval or causal conclusion."

def _bytes(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()

def _sha(raw):
    return hashlib.sha256(raw).hexdigest()

def _inputs(case):
    if case not in (*CASES, "comparison"):
        raise ValueError("Choose a supported synthetic case.")
    offset = {"positive": 4, "negative": -4}.get(case, 0)
    spec = {"method": "independent_mean_difference_ci", "study_design": "independent_groups",
            "outcome_column": "temperature", "group_column": "group", "groups": ["sun", "shade"],
            "unit_column": "unit", "seed": 17, "bootstrap_resamples": 1000,
            "confidence_level": 0.95, "claim_ceiling": NOTICE}
    if case == "comparison":
        spec.update(outcome_column="value", groups=["first", "second"])
        rows = ["unit,group,value"]
        for group, values in (("first", (8, 10, 11, 13)), ("second", (7, 8, 9, 10))):
            rows.extend(f"{group}-{index},{group},{value}" for index, value in enumerate(values, 1))
        return _bytes(spec), ("\n".join(rows) + "\n").encode()
    if case == "missing":
        spec["missing_data_policy"] = "complete_case"
    rows = ["unit,group,temperature"]
    for group in ("sun", "shade"):
        for index, base in enumerate((20, 22, 24, 26)):
            value = str(base + (offset if group == "sun" else 0))
            if group == "sun" and index == 0 and case in ("missing", "invalid"):
                value = "" if case == "missing" else "not-a-number"
            rows.append(f"{group}-{index+1},{group},{value}")
    return _bytes(spec), ("\n".join(rows) + "\n").encode()

class SimulationWorkbench:
    def __init__(self, workspace):
        self.root = Path(workspace) / "simulation-workbench"

    def _directory(self, identifier):
        if not isinstance(identifier, str) or re.fullmatch(r"[a-f0-9]{32}", identifier) is None:
            raise ValueError("Invalid simulation identifier.")
        directory = self.root / identifier
        if self.root.parent.is_symlink() or self.root.is_symlink() or directory.is_symlink():
            raise ValueError("Symlinked simulation storage is unsupported.")
        return directory

    @staticmethod
    def _write(path, raw):
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
        with os.fdopen(fd, "wb") as stream:
            stream.write(raw)

    def prepare(self, case):
        spec, data = _inputs(case)
        identifier = secrets.token_hex(16)
        directory = self._directory(identifier)
        # Preparing a simulation is an explicit write; no canonical state is initialized.
        self.root.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        self.root.mkdir(mode=0o700, exist_ok=True)
        directory.mkdir(mode=0o700)
        recipe = {"version": 1, "case": case, "data_classification": "synthetic",
                  "specification_sha256": _sha(spec), "input_sha256": _sha(data),
                  "notice": NOTICE, "scientific_evidence_eligible": False}
        self._write(directory / "analysis.json", spec)
        self._write(directory / "input.csv", data)
        raw = _bytes(recipe)
        self._write(directory / "recipe.json", raw)
        return self.inspect_recipe(identifier, _sha(raw))

    def _load(self, identifier, recipe_sha256):
        directory = self._directory(identifier)
        for name in ("recipe.json", "analysis.json", "input.csv"):
            if (directory / name).is_symlink():
                raise ValueError("Symlinked simulation artifact.")
        raw = (directory / "recipe.json").read_bytes()
        if _sha(raw) != recipe_sha256:
            raise ValueError("Simulation recipe changed.")
        recipe = json.loads(raw)
        spec, data = _inputs(recipe["case"])
        expected = {"version": 1, "case": recipe["case"], "data_classification": "synthetic",
                    "specification_sha256": _sha(spec), "input_sha256": _sha(data),
                    "notice": NOTICE, "scientific_evidence_eligible": False}
        if recipe != expected or (directory / "analysis.json").read_bytes() != spec or (directory / "input.csv").read_bytes() != data:
            raise ValueError("Simulation inputs differ from the retained recipe.")
        return directory, recipe

    def inspect_recipe(self, simulation_id, recipe_sha256):
        """Read current retained bytes without execution or canonical writes."""
        _, recipe = self._load(simulation_id, recipe_sha256)
        spec, data = _inputs(recipe["case"])
        return {"simulation_id": simulation_id, "recipe_sha256": recipe_sha256, "recipe": recipe,
                "status": "prepared", "canonical_write_performed": False,
                "design": {"specification_json": spec.decode("utf-8"), "input_csv": data.decode("utf-8")}}

    def run(self, simulation_id, recipe_sha256):
        identifier = simulation_id
        directory, recipe = self._load(identifier, recipe_sha256)
        if (directory / "execution").exists() or (directory / "execution").is_symlink():
            raise ValueError("Execution already attempted; retain it and prepare a fresh recipe.")
        execute_analysis(registry=default_registry(include_installed=False),
                         spec_path=directory / "analysis.json", data_path=directory / "input.csv",
                         output_dir=directory / "execution",
                         expected_spec_sha256=recipe["specification_sha256"],
                         expected_input_sha256=recipe["input_sha256"])
        receipt_hash = _sha((directory / "execution" / "execution-receipt.json").read_bytes())
        return self.verify(identifier, recipe_sha256, receipt_hash)

    def verify(self, simulation_id, recipe_sha256, receipt_sha256):
        identifier = simulation_id
        directory, recipe = self._load(identifier, recipe_sha256)
        verified = verify_execution_output(directory / "execution", receipt_sha256)
        receipt = verified["receipt"]
        if receipt["specification"]["sha256"] != recipe["specification_sha256"] or receipt["input"]["sha256"] != recipe["input_sha256"]:
            raise ValueError("Execution does not match the simulation recipe.")
        return {"status": "verified", "simulation_id": identifier, "recipe_sha256": recipe_sha256,
                "receipt_sha256": receipt_sha256, "result": verified["result"], "notice": NOTICE,
                "method": receipt["method"], "addon": receipt["addon"],
                "implementation_sha256": receipt["implementation"]["sha256"],
                "environment": receipt["environment"],
                "scientific_evidence_eligible": False, "canonical_write_performed": False}

    def canonical_fixture(self, simulation_id, recipe_sha256):
        """Exercise the existing canonical service in an isolated synthetic workspace."""
        import platform
        import sys
        from research_machine.adapters.filesystem import FileSystemRepository
        from research_machine.application.commands import CreateInquiry, ProposeHypothesis, CreateProtocol, RegisterDataset, RecordRun
        from research_machine.application.service import ResearchService
        from research_machine.domain.models import AnalysisMode, ProtocolKind, DatasetRole, DatasetArtifact, QualityGateResult, QualityGateStatus
        from research_machine.domain.errors import ValidationError
        directory, recipe = self._load(simulation_id, recipe_sha256)
        root = directory / "canonical-fixture"
        if (directory / "canonical-execution").exists() or (directory / "canonical-execution").is_symlink():
            raise ValueError("Canonical output already exists; no replacement is allowed.")
        if root.exists() or root.is_symlink():
            raise ValueError("Canonical fixture already attempted. Retain it and prepare a fresh recipe.")
        root.mkdir(mode=0o700)
        service = ResearchService(FileSystemRepository(root), actor="synthetic-software-fixture-unverified")
        service.init_workspace()
        inquiry = service.create_inquiry(CreateInquiry(
            title=f"Synthetic {recipe['case']} computational workflow fixture", initial_statement="Can the registered executor retain a hash-bound synthetic calculation without admitting scientific evidence?"))
        hypothesis = service.propose_hypothesis(ProposeHypothesis(
            statement="The registered executor retains a reproducible synthetic calculation.",
            observable_prediction="A completed computation has a receipt matching its retained input and result bytes.",
            null_model="The bounded execution or integrity check fails.",
            competing_models=["Input selection or serialization changes the calculation.", "Runtime dependencies change while registered module bytes remain unchanged.", "An integrity check misses an altered artifact."],
            falsification_conditions=["Changed input or result bytes are accepted as unchanged."],
            scope=NOTICE, boundary_conditions=["Software fixture only; no physical entities or independent scientific review."]))
        service.stage_hypothesis(hypothesis.hypothesis_id, confidence="high",
            rationale="The software test proposition includes an observable result, competing null and falsifier. Provisional exploratory staging is reversible and does not establish scientific validity or human review.")
        registry = default_registry(include_installed=False)
        _, method = registry.resolve_method("independent_mean_difference_ci")
        import inspect
        code_hash = _sha(Path(inspect.getsourcefile(method.runner)).read_bytes())
        command = CreateProtocol(experiment_id="synthetic-computation", title=f"Retain the synthetic {recipe['case']} registered-method calculation",
            analysis_mode=AnalysisMode.EXPLORATORY, protocol_kind=ProtocolKind.COMPUTATIONAL,
            hypotheses_tested=[hypothesis.hypothesis_id], primary_outcome="Synthetic calculation and integrity disposition",
            methodology="Execute the retained fixed synthetic CSV with the registered mean-difference method and inspect the native receipt.",
            inputs_required=["Retained synthetic CSV and analysis specification"],
            quality_requirements=["execution-integrity"], controls=["Adverse changed-byte and invalid-value cases are separate software checks."],
            expected_outputs=["Native result and execution receipt, or retained execution-refusal record"],
            success_conditions=["Retain any valid signed result, including zero and negative values."],
            failure_conditions=["Native execution or receipt verification fails."],
            environment_requirements=["Local Python and bundled registered method only"],
            sample_size_or_stopping_rule="Execute this one fixed eight-record synthetic input once.",
            safety_constraints=["No physical acquisition, human subjects, network or model calls."],
            analysis_code_hash=code_hash, analysis_specification_sha256=recipe["specification_sha256"], unit_id_column="unit")
        protocol = service.create_protocol(command)
        protocol = service.freeze_protocol(protocol.protocol_id)
        data_raw = (directory / "input.csv").read_bytes()
        dataset = service.register_dataset(RegisterDataset(name="Fixed synthetic fixture inputs", role=DatasetRole.EXPLORATORY,
            artifacts=[DatasetArtifact("input.csv", recipe["input_sha256"], size_bytes=len(data_raw), media_type="text/csv")],
            protocol_id=protocol.protocol_id, synthetic=True, observation_unit="One generated software unit",
            description=NOTICE))
        environment = {"python":sys.version,"platform":platform.platform(),"executor":"registered local method; installed addons excluded"}
        output = directory / "canonical-execution"
        started = service.clock()
        try:
            execution = execute_analysis(registry=registry, spec_path=directory/"analysis.json", data_path=directory/"input.csv", output_dir=output,
                expected_spec_sha256=recipe["specification_sha256"], expected_input_sha256=recipe["input_sha256"])
            receipt_hash = _sha((output/"execution-receipt.json").read_bytes())
            verified = verify_execution_output(output,receipt_hash)
            raw = (output/"analysis-result.json").read_bytes()
            gate_status = QualityGateStatus.PASSED
            summary = "Native synthetic execution and current-byte receipt verification completed. " + NOTICE
            artifact_name = "analysis-result.json"
            result = verified["result"]
        except ValidationError as error:
            output.mkdir(mode=0o700, exist_ok=True)
            raw = _bytes({"status":"execution_refused","error":str(error),"scientific_evidence_eligible":False})
            self._write(output/"failure.json",raw)
            gate_status = QualityGateStatus.FAILED
            summary = "The native executor refused this synthetic case; no valid numeric result is asserted. " + NOTICE
            artifact_name = "failure.json"
            result = None
        self._write(output/"environment.json",_bytes(environment))
        artifact_hash = _sha(raw)
        run = service.record_run(RecordRun(protocol_id=protocol.protocol_id, started_at=started, completed_at=service.clock(),
            analysis_code_hash=code_hash, environment_hash=_sha(_bytes(environment)), dataset_ids=[dataset.dataset_id],
            output_artifacts=[DatasetArtifact(artifact_name, artifact_hash, size_bytes=len(raw), media_type="application/json"),
                              DatasetArtifact("environment.json",_sha(_bytes(environment)),size_bytes=len(_bytes(environment)),media_type="application/json")],
            artifact_root=str(output), synthetic=True,
            quality_gates=[QualityGateResult(gate_id="execution-integrity",status=gate_status,summary=summary,
                details={"evidence_sha256":artifact_hash} if gate_status is QualityGateStatus.PASSED else {})],
            summary=summary, metadata={"protocol_deviation_disclosure":{"status":"no_deviations_declared","deviations":[]},
                "result_exposure_disclosure":{"status":"unknown","exposures":[]},"simulation_recipe_sha256":recipe_sha256}))
        if run.scientific_evidence_eligible:
            raise ValueError("Synthetic fixture unexpectedly eligible for scientific evidence.")
        state = service.show_inquiry(inquiry.inquiry_id)
        report = service.build_synthesis(inquiry.inquiry_id)
        exported = service.export_replication_package(protocol.protocol_id, str(directory / "canonical-export"), inquiry.inquiry_id)
        from research_machine.replication.package import verify_replication_package
        package_check = verify_replication_package(directory / "canonical-export", exported["package_manifest_sha256"])
        current_hypothesis = next(item for item in service.list_hypotheses() if item.hypothesis_id == hypothesis.hypothesis_id)
        return {"status":"canonical_fixture_recorded", "canonical_write_performed":True, "workspace_scope":"isolated_synthetic_fixture", "recipe_sha256":recipe_sha256, "report_sha256":_sha(report["content"].encode()), "report":report["content"], "package_manifest_sha256":exported["package_manifest_sha256"], "package_verification":package_check, "simulation_id":simulation_id,
            "inquiry_id":inquiry.inquiry_id,"protocol_id":protocol.protocol_id,"protocol_hash":protocol.protocol_hash,
            "dataset_id":dataset.dataset_id,"run_id":run.run_id,"run_status":run.status.value,
            "hypothesis_status":current_hypothesis.workflow_state.value, "scientific_evidence_eligible":False,
            "evidence_count":len(state["evidence"]),"ledger":service.verify_ledger(inquiry.inquiry_id),"result":result,"notice":NOTICE}

    def inspect_canonical(self, simulation_id, recipe_sha256, report_sha256, package_manifest_sha256):
        from research_machine.adapters.filesystem import FileSystemRepository
        from research_machine.application.service import ResearchService
        from research_machine.replication.package import verify_replication_package
        directory, recipe = self._load(simulation_id, recipe_sha256)
        root = directory / "canonical-fixture"
        if root.is_symlink() or any(path.is_symlink() for path in root.rglob("*")):
            raise ValueError("Symlinked canonical fixture is unsupported.")
        service = ResearchService(FileSystemRepository(root), actor="simulation-readback-unverified")
        state = service.show_inquiry()
        identifier = state["inquiry"]["inquiry_id"]
        report_path = root / "inquiries" / identifier / "reports" / "current-synthesis.md"
        if report_path.stat().st_size > 1_048_576:
            raise ValueError("Simulation report exceeds bounded read size.")
        raw = report_path.read_bytes()
        if _sha(raw) != report_sha256:
            raise ValueError("Canonical fixture report changed.")
        check = verify_replication_package(directory / "canonical-export", package_manifest_sha256)
        ledger = service.verify_ledger(identifier)
        if not ledger["valid"] or state["evidence"] or any(run.scientific_evidence_eligible for run in service.list_runs()):
            raise ValueError("Fixture history or non-evidence boundary changed.")
        return {"status":"verified_canonical_fixture", "simulation_id":simulation_id,
                "recipe_sha256":recipe_sha256,"report_sha256":report_sha256,
                "package_manifest_sha256":package_manifest_sha256,"package_verification":check,
                "ledger":ledger,"case":recipe["case"],"report":raw.decode("utf-8"),
                "run_status":service.list_runs()[0].status.value,"analysis_code_hash":service.list_runs()[0].analysis_code_hash,
                "output_artifacts":[artifact.to_dict() for run in service.list_runs() for artifact in run.output_artifacts],
                "scientific_evidence_eligible":False}

    def export_canonical(self, simulation_id, recipe_sha256, report_sha256, package_manifest_sha256):
        import base64
        import io
        import tempfile
        import zipfile
        from research_machine.replication.package import verify_replication_package
        verified = self.inspect_canonical(simulation_id,recipe_sha256,report_sha256,package_manifest_sha256)
        directory, recipe = self._load(simulation_id,recipe_sha256)
        package = directory / "canonical-export"
        members = {str(path.relative_to(package)):path.read_bytes() for path in package.rglob("*") if path.is_file()}
        if sum(map(len,members.values())) > 5_000_000:
            raise ValueError("Simulation package exceeds bounded export size.")
        # Verify the exact metadata snapshot included in the archive, not earlier path bytes.
        with tempfile.TemporaryDirectory(prefix="faraday-simulation-export-") as temporary:
            snapshot = Path(temporary)
            for name, raw in members.items():
                relative = Path(name)
                if relative.is_absolute() or ".." in relative.parts:
                    raise ValueError("Unsafe metadata export member.")
                (snapshot/relative).parent.mkdir(parents=True,exist_ok=True)
                self._write(snapshot/relative,raw)
            verify_replication_package(snapshot,package_manifest_sha256)
        spec, data = _inputs(recipe["case"])
        members = {"metadata/"+name:raw for name,raw in members.items()}
        for artifact in verified["output_artifacts"]:
            name=artifact["locator"]
            if name not in {"analysis-result.json","failure.json","environment.json"}:
                raise ValueError("Unexpected simulation output member.")
            path=directory/"canonical-execution"/name
            if path.is_symlink():raise ValueError("Symlinked simulation output.")
            raw=path.read_bytes()
            if _sha(raw)!=artifact["sha256"]:raise ValueError("Simulation output changed during export.")
            members["outputs/"+name]=raw
        members.update({"recipe.json":_bytes(recipe),"inputs/analysis.json":spec,"inputs/input.csv":data,
                        "simulation-report.md":verified["report"].encode(),
                        "README.txt":(NOTICE+"\nMetadata uses the native redacted exporter; synthetic inputs and outputs are separate. This archive is not independent replication.\n"+
                            "With an existing matching Faraday installation, after extraction:\n"+
                            "research replication verify --package metadata --expected-manifest-sha256 "+package_manifest_sha256+"\n"+
                            "research analysis run --spec-file inputs/analysis.json --data-file inputs/input.csv --output replay --expect-spec-sha256 "+recipe["specification_sha256"]+" --expect-input-sha256 "+recipe["input_sha256"]+"\n"+
                            "Compare replay/analysis-result.json with outputs/analysis-result.json. A match is a same-code software check, not independent scientific replication. Verify the method implementation matches the protocol's analysis_code_hash. The package hash must come from a separately retained trusted record, not from this README alone.\n").encode()})
        buffer=io.BytesIO()
        with zipfile.ZipFile(buffer,"w",compression=zipfile.ZIP_DEFLATED) as archive:
            for name,raw in sorted(members.items()):
                archive.writestr(name,raw)
        raw=buffer.getvalue()
        return {"filename":"faraday-synthetic-study.zip","media_type":"application/zip",
                "archive_sha256":_sha(raw),"archive_base64":base64.b64encode(raw).decode(),
                "scientific_evidence_eligible":False}


    def replay_canonical(self, simulation_id, recipe_sha256, report_sha256, package_manifest_sha256):
        import inspect
        verified = self.inspect_canonical(simulation_id,recipe_sha256,report_sha256,package_manifest_sha256)
        if verified["run_status"] != "completed":
            raise ValueError("Only a completed synthetic calculation can be replayed.")
        directory, recipe = self._load(simulation_id,recipe_sha256)
        registry=default_registry(include_installed=False)
        _,method=registry.resolve_method("independent_mean_difference_ci")
        if _sha(Path(inspect.getsourcefile(method.runner)).read_bytes())!=verified["analysis_code_hash"]:
            raise ValueError("Registered method bytes changed; same-code replay refused.")
        replays=directory/"replays"
        if replays.is_symlink():raise ValueError("Symlinked replay directory.")
        replays.mkdir(mode=0o700,exist_ok=True)
        replay=replays/secrets.token_hex(16);replay.mkdir(mode=0o700)
        execute_analysis(registry=registry,spec_path=directory/"analysis.json",data_path=directory/"input.csv",output_dir=replay/"execution",
            expected_spec_sha256=recipe["specification_sha256"],expected_input_sha256=recipe["input_sha256"])
        receipt_hash=_sha((replay/"execution"/"execution-receipt.json").read_bytes())
        current=verify_execution_output(replay/"execution",receipt_hash)
        original=(directory/"canonical-execution"/"analysis-result.json").read_bytes()
        expected=next(item["sha256"] for item in verified["output_artifacts"] if item["locator"]=="analysis-result.json")
        if _sha(original)!=expected:raise ValueError("Original result changed during replay.")
        result={"status":"replay_completed","matches":current["result"]==json.loads(original),
            "receipt_sha256":receipt_hash,"original_result_sha256":expected,
            "replayed_result_sha256":_sha((replay/"execution"/"analysis-result.json").read_bytes()),
            "comparison_scope":"Same registered method module and pinned input/specification; not independent replication or complete environment closure.",
            "scientific_evidence_eligible":False,"canonical_write_performed":False}
        self._write(replay/"replay-summary.json",_bytes(result))
        return result
