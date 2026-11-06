"""Read-only configured published example; no scientific record or authority."""
import csv
import hashlib
import io
import json
from pathlib import Path
import re

from research_machine.application.beginner import rehearsal_report
from research_machine.application.rehearsal_drafts import validate_draft


def _object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Duplicate example field.")
        result[key] = value
    return result


def _json(raw):
    def invalid(_):
        raise ValueError("Non-finite JSON is unsupported.")
    return json.loads(raw, object_pairs_hook=_object, parse_constant=invalid)


class PublishedReplayExample:
    def __init__(self, directory=None, manifest_sha256=None):
        if (directory is None) != (manifest_sha256 is None):
            raise ValueError("Supply both published replay directory and manifest SHA-256.")
        if directory is not None and (
            not isinstance(manifest_sha256, str)
            or re.fullmatch(r"[a-f0-9]{64}", manifest_sha256) is None
        ):
            raise ValueError("Published replay requires an exact lowercase SHA-256.")
        self.directory = Path(directory).expanduser().absolute() if directory is not None else None
        self.manifest_sha256 = manifest_sha256

    @property
    def configured(self):
        return self.directory is not None

    def load(self):
        if not self.configured:
            raise ValueError("No published example is configured.")
        directory = self.directory
        if any(part.is_symlink() for part in (directory, *directory.parents)):
            raise ValueError("Symlinked example storage is unsupported.")
        directory = directory.resolve()
        checkout = Path(__file__).resolve().parents[3]
        if directory == checkout or checkout in directory.parents:
            raise ValueError("Keep published examples outside the source checkout.")

        def read(name):
            path = directory / name
            if path.is_symlink() or not path.is_file() or not 0 < path.stat().st_size <= 1048576:
                raise ValueError("Example file is missing, symlinked or oversized.")
            with path.open("rb") as stream:
                raw = stream.read(1048577)
            if len(raw) > 1048576:
                raise ValueError("Example file exceeds its bound.")
            return raw

        raw = read("replay-manifest.json")
        if hashlib.sha256(raw).hexdigest() != self.manifest_sha256:
            raise ValueError("Published example manifest changed.")
        manifest = _json(raw)
        if (not isinstance(manifest, dict)
            or manifest.get("kind") != "published-data-replay-manifest"
            or type(manifest.get("replay_schema_version")) is not int
            or manifest["replay_schema_version"] != 1
            or manifest.get("rehearsal_unit") != "degC"
            or manifest.get("contrast_order") != ["sun", "shade"]
            or manifest.get("source_data_synthetic") is not False
            or manifest.get("scientific_evidence_eligible") is not False
            or manifest.get("canonical_write_performed") is not False):
            raise ValueError("Unsupported published replay contract.")
        for field in ("source_doi", "source_url", "citation", "license", "selection", "limitations"):
            if not isinstance(manifest.get(field), str) or not manifest[field].strip():
                raise ValueError("Example attribution and limitations are required.")
        if not isinstance(manifest.get("source_sha256"), str) or re.fullmatch(r"[a-f0-9]{64}", manifest["source_sha256"]) is None:
            raise ValueError("Original source commitment is required.")
        names = ("rehearsal-draft.json", "rehearsal-report.json", "hourly-replay.csv")
        if not isinstance(manifest.get("outputs"), dict) or set(manifest["outputs"]) != set(names):
            raise ValueError("Unexpected example output inventory.")
        files = {name: read(name) for name in names}
        for name, content in files.items():
            if hashlib.sha256(content).hexdigest() != manifest["outputs"][name]:
                raise ValueError("Published example output changed.")
        draft = _json(files["rehearsal-draft.json"])
        if (not isinstance(draft, dict)
            or draft.get("kind") != "non-evidentiary-rehearsal-draft"
            or draft.get("review_status") != "unresolved"
            or draft.get("scientific_evidence_eligible") is not False):
            raise ValueError("Example must remain an unresolved rehearsal.")
        clean = validate_draft(draft)
        if clean["inquiry_id"] is not None or clean["saved_statement"] is not None or clean["save_state"] != "draft" or clean["history"]:
            raise ValueError("An example cannot carry saved inquiry references or private history.")
        notes = clean.get("planning", {}).get("available_data_sources", "")
        if manifest["citation"] not in notes or manifest["source_sha256"] not in notes:
            raise ValueError("Draft attribution must retain the source commitment.")
        if _json(files["rehearsal-report.json"]) != rehearsal_report(draft):
            raise ValueError("Example report differs from current rehearsal arithmetic.")
        reader = csv.DictReader(io.StringIO(files["hourly-replay.csv"].decode("utf-8")))
        if reader.fieldnames != ["id", "shade", "sun"] or list(reader) != clean["rows"]:
            raise ValueError("Example CSV differs from its draft.")
        lineage = manifest.get("lineage")
        if (type(manifest.get("pair_count")) is not int or manifest["pair_count"] != len(clean["rows"])
            or not isinstance(lineage, list) or any(not isinstance(item, dict) for item in lineage)
            or [item.get("pair_id") for item in lineage] != [row["id"] for row in clean["rows"]]):
            raise ValueError("Example pair lineage does not match its draft.")
        return {"status": "published_example_checked", "manifest_sha256": self.manifest_sha256,
                "draft": draft, "data_classification": "published_observations_not_synthetic",
                "source": {field: manifest[field] for field in ("source_doi", "source_url", "citation", "license", "source_sha256", "selection", "limitations")},
                "canonical_write_performed": False, "scientific_evidence_eligible": False,
                "notice": "Configured published observations, not synthetic data. Generated files match the operator-pinned manifest; original source bytes, measurements and scientific validity are not verified by this loading check."}
