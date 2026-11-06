"""Offline, pinned published-data replay. Never registers scientific records.

Source workbooks and generated replay files must stay outside this repository.
No network, package installation, workbook execution or formula evaluation.
"""
from __future__ import annotations

import argparse
import csv
import datetime as dt
import hashlib
import json
import math
from pathlib import Path
import xml.etree.ElementTree as ET
import zipfile

SOURCE_SHA256 = "13c89a084e8a74caf79b12f9878d2fab04a456e3392947e0c79911ca29f635fc"
SOURCE_DOI = "10.32920/25137140.v1"
SOURCE_URL = "https://rshare.library.torontomu.ca/articles/dataset/Temperature_data_for_vine_shade_study/25137140"
CITATION = "Millward, Andrew (2024). Temperature data for vine shade study, v1. Toronto Metropolitan University. https://doi.org/10.32920/25137140.v1. CC BY 4.0."
SUN = ("B", "C", "D", "E", "F", "G")
SHADE = ("N", "O", "P", "Q", "R", "S", "T", "U", "V", "W", "X", "Y")
SUN_IDS = ("S1", "S2", "S11", "S13", "S17", "S18")
SHADE_IDS = ("S3", "S4", "S5", "S6", "S7", "S8", "S9", "S10", "S12", "S14", "S15", "S16")
NS = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
LIMITS = ("Published south-facing wall temperatures, Toronto; vine-covered versus uncovered surfaces. "
          "Vegetation, wall placement, sensor allocation and time may contribute; this is not a pure shade intervention. "
          "Hourly values repeat the same wall/sensor groups and are not independent experimental units. "
          "This retrospective complete-day selection is for software rehearsal, not prospective confirmatory evidence.")


def read_source(path: Path):
    if path.is_symlink() or not path.is_file() or path.stat().st_size > 8_000_000:
        raise ValueError("Supply the unmodified regular source workbook (at most 8 MB).")
    raw = path.read_bytes()
    if hashlib.sha256(raw).hexdigest() != SOURCE_SHA256:
        raise ValueError("Source bytes differ from the retained published v1 workbook.")
    records = []
    seen = set()
    missing_rows = 0
    summary_rows = []
    with zipfile.ZipFile(path) as archive:
        if sum(item.file_size for item in archive.infolist()) > 150_000_000:
            raise ValueError("Workbook exceeds uncompressed bound.")
        workbook = ET.fromstring(archive.read("xl/workbook.xml"))
        properties = workbook.find(NS + "workbookPr")
        if properties is not None and properties.get("date1904") in ("1", "true"):
            raise ValueError("Unexpected date system.")
        strings = ["".join(t.text or "" for t in item.iter(NS + "t"))
                   for item in ET.fromstring(archive.read("xl/sharedStrings.xml"))]
        styles = ET.fromstring(archive.read("xl/styles.xml"))
        formats = list(styles.find(NS + "cellXfs"))
        fills = list(styles.find(NS + "fills"))
        def fill(cell):
            index = int(formats[int(cell.get("s", "0"))].get("fillId", "0"))
            return ET.tostring(fills[index])
        headers = {}
        legends = {}
        with archive.open("xl/worksheets/sheet1.xml") as stream:
            for _, row in ET.iterparse(stream, events=("end",)):
                if row.tag != NS + "row":
                    continue
                index = int(row.get("r"))
                if index > 100_000:
                    raise ValueError("Too many source rows.")
                cells = {}
                for cell in row:
                    col = "".join(c for c in cell.get("r", "") if c.isalpha())
                    value = cell.findtext(NS + "v", default="")
                    if cell.get("t") == "s" and value:
                        value = strings[int(value)]
                    cells[col] = value
                    if index == 1 and col in SUN + SHADE:
                        headers[col] = (value, fill(cell))
                    if col == "AQ" and value in ("Sun", "Shade"):
                        legends[value] = fill(cell)
                if index == 1 or not cells.get("A"):
                    row.clear()
                    continue
                if cells["A"] in {"Mean", "Standard deviation", "Skew", "Median", "Max", "Min"}:
                    summary_rows.append(index)
                    row.clear()
                    continue
                seconds = float(cells["A"]) * 86400
                if not math.isfinite(seconds) or abs(seconds - round(seconds)) > .01:
                    raise ValueError("Unexpected timestamp precision.")
                time = dt.datetime(1899, 12, 30) + dt.timedelta(seconds=round(seconds))
                if time in seen:
                    raise ValueError("Duplicate source timestamp.")
                seen.add(time)
                record = {"time": time, "source_row": index, "sun": None, "shade": None}
                try:
                    for label, columns, cached in (("sun", SUN, "H"), ("shade", SHADE, "Z")):
                        values = [float(cells[col]) for col in columns]
                        if not all(math.isfinite(v) and -273.15 <= v <= 1000 for v in values):
                            raise ValueError("Invalid sensor value.")
                        mean = math.fsum(values) / len(values)
                        record[label] = mean
                        record["cached_"+label] = cells.get(cached)
                except (KeyError, ValueError):
                    record["sun"] = record["shade"] = None
                    missing_rows += 1
                records.append(record)
                row.clear()
        for label, cols, ids in (("Sun", SUN, SUN_IDS), ("Shade", SHADE, SHADE_IDS)):
            if label not in legends or any(headers.get(col) != (identifier, legends[label]) for col, identifier in zip(cols, ids)):
                raise ValueError("Sensor headers do not match the workbook's explicit Sun/Shade legend.")
    return records, {"source_rows": len(records), "incomplete_or_invalid_rows": missing_rows,
                     "duplicate_timestamps": 0, "nonobservation_summary_rows": summary_rows,
                     "group_mean_check": "selected first complete day recomputed from raw sensors and checked against stored means"}


def first_complete_day(records):
    days = {}
    for record in records:
        days.setdefault(record["time"].date(), []).append(record)
    for day in sorted(days):
        rows = sorted(days[day], key=lambda item: item["time"])
        expected = [dt.datetime.combine(day, dt.time()) + dt.timedelta(minutes=15*i) for i in range(96)]
        if ([row["time"] for row in rows] == expected
            and all(row["sun"] is not None and row["shade"] is not None for row in rows)):
            return day, rows
    raise ValueError("No complete calendar day with both sensor groups was found.")


def replay_draft(day, records):
    actual_day, selected_day = first_complete_day(records)
    if len(records) != 96 or actual_day != day or records != selected_day:
        raise ValueError("Replay requires exactly one complete ordered day.")
    for record in records:
        for label in ("sun", "shade"):
            cached = float(record["cached_"+label])
            if not math.isfinite(cached) or not math.isclose(record[label], cached, abs_tol=1e-9, rel_tol=1e-12):
                raise ValueError("Selected source mean differs from raw-sensor recomputation; no replacement day selected.")
    rows = []
    lineage = []
    for hour in range(24):
        selected = records[4*hour:4*hour+4]
        rows.append({"id": f"{day.isoformat()}T{hour:02d}:00",
                     "sun": format(math.fsum(r["sun"] for r in selected)/4, ".15g"),
                     "shade": format(math.fsum(r["shade"] for r in selected)/4, ".15g")})
        lineage.append({"pair_id": rows[-1]["id"], "source_rows": [r["source_row"] for r in selected],
                        "sun_columns": list(SUN), "shade_columns": list(SHADE)})
    selection = "First complete calendar day with 96 unique 15-minute timestamps and all 18 wall sensors; four successive sensor-group means averaged per hour. No effect-size filter."
    draft = {"kind": "non-evidentiary-rehearsal-draft", "review_status": "unresolved",
             "scientific_evidence_eligible": False,
             "statement": "How do published vine-covered and uncovered south-facing wall temperatures differ across one complete day?",
             "prediction": "Retrospective published-data replay; no prospective prediction is claimed.",
             "reflection": LIMITS, "rows": rows, "history": [], "inquiry_id": None,
             "saved_statement": None, "save_state": "draft",
             "review_context": {"reviewer_kind": "ai", "identity_status": "unverified", "authority": "review_only",
                                "notes": "Published observations are not synthetic. Only the software workflow is simulated. No new collection, canonical dataset, protocol, run or evidence is created. " + LIMITS},
             "planning": {"title": "Attributed published-data wall-temperature replay",
                          "available_data_sources": CITATION + "\nSource SHA-256: " + SOURCE_SHA256,
                          "outcome": "Hourly mean of published wall-surface sensor-group means, degrees Celsius.",
                          "comparison": "Uncovered wall sensors minus vine-covered wall sensors at matching times.",
                          "time_window": day.isoformat() + "; source-local timestamps, timezone not established by workbook.",
                          "unit_of_observation": "A repeated hourly group summary, not an established independent experimental unit.",
                          "decision": "Rehearse data provenance, paired arithmetic, limitations and private report recovery.",
                          "ethical_constraints": "CC BY 4.0 attribution required. No human-subject observations selected. No new scientific evidence admission.",
                          "minimum_evidence": "For this rehearsal: exact source bytes, explicit legend mapping and reproducible extraction; physical validity remains unreviewed.",
                          "decision_change_criteria": "A source checksum, label mapping, timestamp or raw-group arithmetic mismatch blocks replay.",
                          "decision_owner": "Unassigned; AI review-only.",
                          "population": "One published south-facing building-wall dataset; no population generalization."}}
    draft["review_context"]["notes"] += " Selection: " + selection
    return draft, lineage, selection


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-xlsx", type=Path, required=True)
    parser.add_argument("--output-directory", type=Path, required=True)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    for path in (args.source_xlsx, args.output_directory):
        if path.resolve() == root or root in path.resolve().parents or path.is_symlink():
            parser.error("Keep source data and replay outputs outside the source checkout, without symlinks.")
    from research_machine.application.rehearsal_drafts import validate_draft
    from research_machine.application.beginner import rehearsal_report
    records, profile = read_source(args.source_xlsx)
    day, selected = first_complete_day(records)
    draft, lineage, selection = replay_draft(day, selected)
    validate_draft(draft)
    report = rehearsal_report(draft)
    # Validate everything before publishing the new, private, noncanonical directory.
    args.output_directory.mkdir(mode=0o700, exist_ok=False)
    def write(name, value):
        (args.output_directory/name).write_text(json.dumps(value, indent=2, ensure_ascii=False, allow_nan=False)+"\n")
    write("rehearsal-draft.json", draft)
    write("rehearsal-report.json", report)
    with (args.output_directory/"hourly-replay.csv").open("w", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=("id", "shade", "sun"));writer.writeheader();writer.writerows(draft["rows"])
    manifest = {"kind": "published-data-replay-manifest", "replay_schema_version": 1,
                "rehearsal_unit": "degC", "contrast_order": ["sun", "shade"], "source_data_synthetic": False,
                "scientific_evidence_eligible": False, "canonical_write_performed": False,
                "source_doi": SOURCE_DOI, "citation": CITATION, "license": "CC BY 4.0",
                "source_url": SOURCE_URL, "source_sha256": SOURCE_SHA256,
                "source_sheet": "Sheet1", "selection": selection, "selected_day": day.isoformat(),
                "profile": profile, "pair_count": len(draft["rows"]), "lineage": lineage, "limitations": LIMITS,
                "outputs": {name: hashlib.sha256((args.output_directory/name).read_bytes()).hexdigest()
                            for name in ("rehearsal-draft.json", "rehearsal-report.json", "hourly-replay.csv")}}
    write("replay-manifest.json", manifest)
    print(json.dumps({"output_directory": str(args.output_directory), "selected_day": day.isoformat(),
                      "pairs": len(draft["rows"]), "source_rows": profile["source_rows"],
                      "scientific_evidence_eligible": False}))


if __name__ == "__main__":
    import os
    os.umask(0o077)
    main()
