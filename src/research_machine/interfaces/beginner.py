"""Single-user loopback prototype; no scientific review or evidence authority."""
from __future__ import annotations
import argparse
import hmac
import hashlib
import json
import os
import re
from pathlib import Path
import secrets
import sqlite3
from http.server import BaseHTTPRequestHandler, HTTPServer
from research_machine.adapters.filesystem import FileSystemRepository
from research_machine.application.service import ResearchService
from research_machine.application.beginner import pathway, question_pathway, rehearsal_preview, start_inquiry, inspect_saved_inquiry, planning_preview, rehearsal_report
from research_machine.domain.errors import ResearchMachineError
from research_machine.application.rehearsal_drafts import RehearsalDraftStore, DraftConflict
from research_machine.application.beginner_simulation import SimulationWorkbench
from research_machine.application.published_replay import PublishedReplayExample
from research_machine.application.beginner_hypotheses import notebook_hypothesis
from research_machine.application.beginner_design import preview_notebook_design, notebook_protocol_draft
from research_machine.application.beginner_computation import NotebookComputation, method_identity
from research_machine.application.portable_computation import PortableComputation, export_computation
from research_machine.application.computation_assessment import ComputationAssessment

PAGE = Path(__file__).with_name("beginner.html")
CLIENT = Path(__file__).with_name("beginner.js")

def make_handler(workspace, token, *, draft_namespace=None, published_replay_directory=None, published_replay_manifest_sha256=None):
    repository = FileSystemRepository(workspace)
    if draft_namespace is not None and (
        not isinstance(draft_namespace, str)
        or re.fullmatch(r"[0-9a-f]{64}", draft_namespace) is None
    ):
        raise ValueError("Draft namespace must be 64 lowercase hexadecimal characters.")
    namespace = draft_namespace or hashlib.sha256(str(repository.root).encode()).hexdigest()
    service = ResearchService(repository, actor="beginner-interface-unverified")
    drafts = RehearsalDraftStore(repository.root, namespace)
    simulations = SimulationWorkbench(repository.root)
    computations = NotebookComputation(service)
    portable_computations = PortableComputation(repository.root)
    assessments = ComputationAssessment(service)
    published = PublishedReplayExample(published_replay_directory, published_replay_manifest_sha256)
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass  # Do not log learner text or request data.

        def reply(self, status, body, content_type="application/json"):
            data = body.encode() if isinstance(body, str) else json.dumps(body, allow_nan=False).encode()
            self.send_response(status)
            self.send_header("Content-Type", content_type + "; charset=utf-8")
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Referrer-Policy", "no-referrer")
            self.send_header("Content-Security-Policy",
                             "default-src 'none'; script-src 'nonce-" + token +
                             "'; style-src 'nonce-" + token +
                             "'; connect-src 'self'; frame-ancestors 'none'; form-action 'none'")
            self.end_headers()
            self.wfile.write(data)

        def allowed(self, write=False):
            host = "127.0.0.1:" + str(self.server.server_port)
            if self.headers.get("Host") != host:
                return False
            origin = self.headers.get("Origin")
            if origin is not None and origin != "http://" + host:
                return False
            return not write or hmac.compare_digest(self.headers.get("X-Faraday-Token", ""), token)

        def do_GET(self):
            if not self.allowed():
                return self.reply(403, {"error": "Loopback origin required."})
            if self.path == "/":
                return self.reply(200, PAGE.read_text().replace("__TOKEN__", token).replace("__DRAFT_KEY__", namespace), "text/html")
            if self.path == "/beginner.js":
                return self.reply(200, CLIENT.read_text().replace("__TOKEN__", token).replace("__DRAFT_KEY__", namespace), "application/javascript")
            if self.path == "/api/pathway":
                return self.reply(200, {**question_pathway(), "published_example_available": published.configured})
            if self.path == "/api/computation/method":
                return self.reply(200, method_identity())
            return self.reply(404, {"error": "Not found."})

        def do_POST(self):
            if not self.allowed(write=True):
                return self.reply(403, {"error": "Same-origin session required."})
            if self.path not in ("/api/assessment/save", "/api/assessment/inspect", "/api/computation/export", "/api/portable-computation/restore", "/api/portable-computation/inspect", "/api/portable-computation/replay", "/api/portable-computation/verify", "/api/computation/prepare", "/api/computation/inspect", "/api/computation/run", "/api/computation/verify", "/api/design/save", "/api/design/inspect", "/api/design/preview", "/api/hypothesis/propose", "/api/hypothesis/inspect", "/api/inquiry", "/api/inquiry/inspect", "/api/planning", "/api/rehearsal", "/api/rehearsal/report", "/api/draft/load", "/api/draft/save", "/api/examples/published", "/api/simulation/design", "/api/simulation/prepare", "/api/simulation/run", "/api/simulation/verify", "/api/simulation/canonical", "/api/simulation/inspect", "/api/simulation/export", "/api/simulation/replay"):
                return self.reply(404, {"error": "Not found."})
            try:
                length = int(self.headers.get("Content-Length", "0"))
                limit = 1100000 if self.path == "/api/portable-computation/restore" else 256000 if self.path == "/api/computation/prepare" else 1100000 if self.path in ("/api/draft/save","/api/rehearsal/report") else 65536
                if not 0 < length <= limit:
                    raise ValueError("Request must contain at most 64 KiB.")
                if self.headers.get("Content-Type") != "application/json":
                    raise ValueError("JSON required.")
                payload = json.loads(self.rfile.read(length))
                if self.path.startswith("/api/assessment/"):
                    if self.path.endswith("/save"):
                        result = assessments.save(payload)
                    else:
                        if not isinstance(payload, dict) or set(payload) != {"assessment_sha256"}:
                            raise ValueError("Supply the exact retained assessment hash.")
                        result = assessments.inspect(**payload)
                elif self.path == "/api/computation/export":
                    result = export_computation(computations, payload)
                elif self.path.startswith("/api/portable-computation/"):
                    if self.path.endswith("/restore"):
                        result = portable_computations.restore(payload)
                    elif self.path.endswith("/verify"):
                        if not isinstance(payload, dict) or set(payload) not in ({"archive_sha256", "receipt_sha256"}, {"archive_sha256", "refusal_sha256"}):
                            raise ValueError("Supply the retained archive and one replay outcome hash.")
                        result = portable_computations.verify_replay(**payload)
                    else:
                        if not isinstance(payload, dict) or set(payload) != {"archive_sha256"}:
                            raise ValueError("Supply the exact retained archive hash.")
                        result = (portable_computations.replay if self.path.endswith("/replay") else portable_computations.inspect)(**payload)
                elif self.path.startswith("/api/computation/"):
                    if self.path.endswith("/prepare"):
                        result = computations.prepare(payload)
                    elif self.path.endswith("/verify"):
                        if not isinstance(payload, dict) or set(payload) not in ({"bundle_sha256", "receipt_sha256"}, {"bundle_sha256", "failure_sha256"}):
                            raise ValueError("Supply retained bundle and receipt hashes only.")
                        result = computations.verify(**payload)
                    else:
                        if not isinstance(payload, dict) or set(payload) != {"bundle_sha256"}:
                            raise ValueError("Supply the exact retained bundle hash only.")
                        result = (computations.run if self.path.endswith("/run") else computations.inspect)(**payload)
                elif self.path in ("/api/design/save", "/api/design/inspect"):
                    result = notebook_protocol_draft(service, payload, write=self.path.endswith("/save"))
                elif self.path == "/api/design/preview":
                    result = preview_notebook_design(service, payload)
                elif self.path in ("/api/hypothesis/propose", "/api/hypothesis/inspect"):
                    result = notebook_hypothesis(service, payload, write=self.path.endswith("/propose"))
                elif self.path == "/api/examples/published":
                    if payload != {}:
                        raise ValueError("The configured example accepts no caller-supplied paths or data.")
                    result = published.load()
                elif self.path.startswith("/api/simulation/"):
                    if not isinstance(payload,dict):
                        raise ValueError("Simulation object required.")
                    if self.path.endswith("/prepare"):
                        if set(payload)!={"case"}:raise ValueError("Supply a simulation case only.")
                        result=simulations.prepare(payload["case"])
                    elif self.path.endswith("/design"):
                        if set(payload)!={"simulation_id","recipe_sha256"}:raise ValueError("Supply the exact retained simulation recipe.")
                        result={**simulations.inspect_recipe(**payload), "method_identity":method_identity()}
                    elif self.path.endswith("/inspect") or self.path.endswith("/export") or self.path.endswith("/replay"):
                        if set(payload)!={"simulation_id","recipe_sha256","report_sha256","package_manifest_sha256"}:raise ValueError("Supply retained simulation commitments.")
                        result=({"/api/simulation/inspect":simulations.inspect_canonical,"/api/simulation/export":simulations.export_canonical,"/api/simulation/replay":simulations.replay_canonical}[self.path])(**payload)
                    elif self.path.endswith("/canonical"):
                        if set(payload)!={"simulation_id","recipe_sha256"}:raise ValueError("Supply the retained simulation recipe.")
                        result=simulations.canonical_fixture(**payload)
                    elif self.path.endswith("/run"):
                        if set(payload)!={"simulation_id","recipe_sha256"}:raise ValueError("Supply the retained simulation recipe.")
                        result=simulations.run(**payload)
                    else:
                        if set(payload)!={"simulation_id","recipe_sha256","receipt_sha256"}:raise ValueError("Supply retained simulation and receipt hashes.")
                        result=simulations.verify(**payload)
                elif self.path == "/api/rehearsal/report":
                    result=rehearsal_report(payload)
                elif self.path == "/api/planning":
                    result=planning_preview(payload)
                elif self.path == "/api/inquiry/inspect":
                    if not isinstance(payload,dict) or set(payload)!={"statement","inquiry_id"}:
                        raise ValueError("Supply exact question and optional inquiry reference only.")
                    result=inspect_saved_inquiry(service,payload["statement"],payload["inquiry_id"])
                elif self.path == "/api/draft/load":
                    if payload != {}:
                        raise ValueError("Draft load needs an empty object.")
                    result = drafts.load()
                elif self.path == "/api/draft/save":
                    if not isinstance(payload, dict) or set(payload) != {"expected_revision", "draft"}:
                        raise ValueError("Supply revision and draft only.")
                    result = drafts.save(payload["expected_revision"], payload["draft"])
                elif self.path == "/api/rehearsal":
                    result = rehearsal_preview(payload)
                else:
                    if not isinstance(payload, dict) or set(payload) != {"statement"}:
                        raise ValueError("Supply only the original question.")
                    statement = payload["statement"]
                    if not isinstance(statement, str) or not statement.strip() or statement != statement.strip() or len(statement) > 2000:
                        raise ValueError("Write a question using between 1 and 2000 characters.")
                    service.init_workspace()
                    result = start_inquiry(service, statement)
                self.reply(200, result)
            except DraftConflict as error:
                self.reply(409, {"error": str(error)})
            except sqlite3.Error:
                self.reply(500, {"error": "Server draft storage failed. Keep or download your local draft."})
            except (ValueError, TypeError, ResearchMachineError):
                if self.path.startswith("/api/assessment/"):
                    return self.reply(400, {"error": "Working assessment could not be saved or verified. Check its exact retained source and six complete fields. Changed artifacts block verification. Earlier notes remain; no scientific evidence or action recommendation was created."})
                if self.path.startswith(("/api/computation/", "/api/portable-computation/")):
                    return self.reply(400, {"error": "Computation refused or its integrity could not be confirmed. Preserve retained inputs and outputs. Check the exact saved draft, bundled method hash, specification, CSV and source description. A prior attempt cannot be rerun. No canonical record or scientific evidence was advanced."})
                if self.path.startswith("/api/design/"):
                    return self.reply(400, {"error": "Design save or inspection could not be confirmed. Keep the exact notes and use read-only inspection before retrying; partial records may remain. Check the saved hypothesis, title/outcome, unpadded notes and unique list lines. No freeze or analysis was requested."})
                if self.path.startswith("/api/hypothesis/"):
                    return self.reply(400, {"error": "Proposal not saved or verified. Check the exact saved question, six complete fields and unique nonblank list lines. Inspect an uncertain save before trying again; no approval is inferred."})
                if self.path == "/api/examples/published":
                    return self.reply(400, {"error": "Published example unavailable or its files failed checks. Your current draft is unchanged. Ask the operator to check the configured replay folder and manifest pin."})
                if self.path.startswith("/api/simulation/"):
                    return self.reply(400, {"error":"Simulation input or integrity check failed. Retained files were not replaced. Invalid-value cases intentionally fail; choose a fresh recipe to try another case."})
                self.reply(400, {"error": "Input could not be saved or previewed. Check the question, "
                                 "question whitespace, unique pair labels, Celsius numbers and missing readings. "
                                 "If saving failed, inspect the workspace before retrying."})
            except OSError:
                self.reply(500, {"error": "Workspace operation failed. Do not retry a save until "
                                 "you inspect the workspace for a partially completed inquiry."})
    return Handler

def prepare_preview_workspace(workspace):
    """Prepare only the explicitly selected working folder, never parent paths or research state."""
    if workspace.is_symlink():
        raise ValueError("Symlinked preview working folders are unsupported.")
    workspace.mkdir(mode=0o700, exist_ok=True)


def main():
    os.umask(0o077)
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workspace", type=Path, required=True)
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--draft-namespace", help="Retain an existing browser draft namespace when moving a workspace (64 lowercase hex characters).")
    parser.add_argument("--published-replay-directory", type=Path, help="Optional offline replay folder outside the checkout.")
    parser.add_argument("--published-replay-manifest-sha256", help="Independently retained replay-manifest.json hash; required with the replay folder.")
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[3]
    workspace = args.workspace.expanduser().resolve()
    if workspace == root or root in workspace.parents:
        parser.error("Keep research workspaces outside the source checkout.")
    try:
        prepare_preview_workspace(workspace)
        handler = make_handler(workspace, secrets.token_hex(24), draft_namespace=args.draft_namespace,
                               published_replay_directory=args.published_replay_directory,
                               published_replay_manifest_sha256=args.published_replay_manifest_sha256)
    except ValueError as error:
        parser.error(str(error))
    except OSError:
        parser.error("Preview working folder is unavailable. Choose an existing permitted parent; no parent paths or connections were created or repaired.")
    with HTTPServer(("127.0.0.1", args.port), handler) as server:
        server.timeout = 10
        print("Beginner developer prototype: http://127.0.0.1:" + str(server.server_port), flush=True)
        print("Scientific review unresolved. Single user only. Stop with Ctrl-C.", flush=True)
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            pass

if __name__ == "__main__":
    main()
