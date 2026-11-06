"""Review-blocked, non-evidentiary beginner pathway and rehearsal preview."""
from __future__ import annotations
import math
from research_machine.application.commands import AddQuestion, CreateInquiry
from research_machine.application.guide import INTAKE_FIELDS, preview_question_intake, preview_guide_packet

def validate_planning_notes(value):
    if (not isinstance(value,dict) or set(value)-(INTAKE_FIELDS-{"original_statement"})
        or any(not isinstance(text,str) or len(text)>2000 for text in value.values())):
        raise ValueError("Planning answers must be known fields of at most 2000 characters each.")
    return dict(value)

def planning_preview(payload):
    if not isinstance(payload,dict) or set(payload)!={"statement","planning"}:
        raise ValueError("Supply exact question and planning answers only.")
    statement=payload["statement"]
    if not isinstance(statement,str) or len(statement)>2000:
        raise ValueError("Question exceeds the notebook bound.")
    answers=validate_planning_notes(payload["planning"])
    brief={"original_statement":statement}
    for field,text in answers.items():
        if text!="":
            brief[field]=text.split("\n") if field in {
                "decision_change_criteria","available_data_sources","ethical_constraints"} else text
    return preview_guide_packet(brief)

def rehearsal_report(payload):
    """Readable rehearsal projection, never a canonical scientific report."""
    from research_machine.application.rehearsal_drafts import validate_draft
    import re
    if (not isinstance(payload,dict) or payload.get("kind")!="non-evidentiary-rehearsal-draft"
        or payload.get("review_status")!="unresolved" or payload.get("scientific_evidence_eligible") is not False):
        raise ValueError("An unresolved rehearsal export is required.")
    draft=validate_draft(payload)
    rows=[]
    for row in draft["rows"]:
        parsed={"id":row["id"]}
        for field in ("shade","sun"):
            raw=row[field]
            if raw=="":parsed[field]=None
            elif re.fullmatch(r"[+-]?(?:\d+\.?\d*|\.\d+)(?:e[+-]?\d+)?",raw,re.IGNORECASE|re.ASCII):
                parsed[field]=float(raw)
            else:raise ValueError("Finish or clear invalid rehearsal readings before reporting.")
        rows.append(parsed)
    return {"report_version":1,"kind":"non-evidentiary-rehearsal-report",
            "draft":draft,"arithmetic":rehearsal_preview({"mode":"rehearsal","unit":"degC","rows":rows}),
            "pathway":pathway(),"review_status":"unresolved","scientific_evidence_eligible":False,
            "canonical_write_performed":False,"independent_backup_verified":False}

DECISIONS = (
    ("audience", "A science educator must review age suitability and adult support."),
    ("safety", "A qualified reviewer must define safe locations and supervision."),
    ("instrument", "Choose a surface-temperature instrument and review its limitations."),
    ("validity", "Define reference checks, calibration criteria and numerical tolerances."),
    ("sampling", "Define independent units, pairing, repeated readings and stopping."),
    ("analysis", "Review the estimator, uncertainty, missingness and claim ceiling."),
    ("custody", "Define observation custody, corrections and required quality gates."),
)
CEILING = ("Rehearsal arithmetic only. No scientific evidence, causal conclusion, "
           "air-temperature estimate, health-risk conclusion or generalization.")

INQUIRY_TITLE = "Faraday investigation — review unresolved"
GENERAL_DECISIONS = (
    ("audience", "Identify who the investigation is for and any support they need."),
    ("safety", "State applicable safety, privacy, rights and ethical constraints."),
    ("instrument", "Describe the observations, existing sources or computational inputs and their limitations."),
    ("validity", "Define how the measurement or model would be checked and what would invalidate it."),
    ("sampling", "Define the units, selection, comparisons, repeated observations and stopping rule."),
    ("analysis", "Specify the method, uncertainty, missingness, competing explanations and claim ceiling."),
    ("custody", "Preserve source provenance, original values, corrections and required checks."),
)


def question_pathway():
    """Generic intake; the historical shade pathway remains an optional example."""
    result = pathway()
    result.update(pathway_id="question-led-investigation", question=None,
                  decisions=[{"id": key, "status": "unresolved", "question": text}
                             for key, text in GENERAL_DECISIONS],
                  alternatives=["What is one possible explanation?",
                                "What other explanation could fit?",
                                "Could measurement, selection or changing conditions account for it?",
                                "What result would change your mind?"],
                  claim_ceiling="Unreviewed investigation notes. No scientific evidence or causal conclusion.")
    return result

def pathway():
    return {
        "pathway_id": "shade-surface-temperature", "version": 1,
        "question": "How does surface temperature differ between a shaded place and a nearby sunny place?",
        "review_status": "unresolved",
        "decisions": [{"id": key, "status": "unresolved", "question": text}
                      for key, text in DECISIONS],
        "alternatives": ["Shade may relate to a temperature difference.",
                         "Surface material, moisture or timing may explain a difference.",
                         "Instrument error may explain a difference.",
                         "There may be no consistent difference."],
        "confirmatory_collection_enabled": False,
        "evidence_admission_enabled": False, "claim_ceiling": CEILING,
        "planning_fields": preview_question_intake({"original_statement":
            "How does surface temperature differ between a shaded place and a nearby sunny place?"})["clarifying_questions"],
    }

def start_inquiry(service, statement):
    if not isinstance(statement, str) or not statement.strip() or statement != statement.strip() or len(statement) > 2000:
        raise ValueError("Write 1–2000 characters without surrounding whitespace; your wording will not be silently changed.")
    inquiry = service.create_inquiry(CreateInquiry(
        title=INQUIRY_TITLE, initial_statement=statement))
    for _, question in GENERAL_DECISIONS:
        service.add_question(AddQuestion(question), inquiry.inquiry_id)
    return {"inquiry_id": inquiry.inquiry_id, "original_statement": statement,
            "review_status": "unresolved", "pathway": question_pathway()}

def inspect_saved_inquiry(service, statement, inquiry_id=None):
    """Inspect only a named or active inquiry; never repair or retry a write."""
    import re
    if not isinstance(statement,str) or not statement.strip() or statement!=statement.strip() or len(statement)>2000:
        raise ValueError("An exact question is required.")
    if inquiry_id is not None and (not isinstance(inquiry_id,str) or re.fullmatch(r"[a-z0-9][a-z0-9-]{0,95}",inquiry_id) is None):
        raise ValueError("Invalid inquiry reference.")
    state=service.show_inquiry(inquiry_id)
    inquiry=state["inquiry"]
    result={"status":"no_match", "lookup_scope":"named_inquiry" if inquiry_id else "active_inquiry_only",
            "canonical_write_performed":False, "review_status":"unresolved",
            "scientific_evidence_eligible":False}
    decisions = (GENERAL_DECISIONS if inquiry["title"] == INQUIRY_TITLE else
                 DECISIONS if inquiry["title"] == "Shade-temperature pathway v1 — review unresolved" else None)
    if inquiry["initial_statement"] != statement or decisions is None:
        return result
    ledger=service.verify_ledger(inquiry["inquiry_id"])
    questions=state["questions"]
    complete=([q["text"] for q in questions]==[text for _,text in decisions]
              and all(q["status"]=="open" for q in questions))
    result["status"]="matching_complete" if complete and ledger.get("valid") else "matching_incomplete"
    if result["status"]=="matching_complete":
        result.update(inquiry_id=inquiry["inquiry_id"],original_statement=statement,
                      ledger_head_sha256=ledger["head_hash"])
    return result

def rehearsal_preview(payload):
    if not isinstance(payload, dict) or set(payload) != {"mode", "unit", "rows"}:
        raise ValueError("Supply only mode, unit and rehearsal rows.")
    if payload["mode"] != "rehearsal":
        raise ValueError("Real-data admission is unavailable pending qualified review.")
    if payload["unit"] != "degC":
        raise ValueError("This rehearsal accepts surface temperatures in degrees Celsius only.")
    rows = payload["rows"]
    if not isinstance(rows, list) or not 1 <= len(rows) <= 200:
        raise ValueError("Supply between 1 and 200 rehearsal pairs.")
    seen, differences, missing = set(), [], []
    for index, row in enumerate(rows):
        if not isinstance(row, dict) or set(row) != {"id", "shade", "sun"}:
            raise ValueError("Each pair needs exactly id, shade and sun.")
        key = row["id"]
        if not isinstance(key, str) or not key.strip() or key != key.strip() or key in seen:
            raise ValueError("Pair labels must be nonempty, unpadded and unique.")
        seen.add(key)
        for field in ("shade", "sun"):
            value = row[field]
            if value is not None and (isinstance(value, bool) or not isinstance(value, (int, float))
                                      or not math.isfinite(value) or not -273.15 <= value <= 1000):
                raise ValueError("Use a finite Celsius number or leave a reading missing.")
        if row["shade"] is None or row["sun"] is None:
            missing.append(key)
        else:
            differences.append({"id": key, "sun_minus_shade_degC": row["sun"] - row["shade"]})
    return {"mode": "rehearsal", "review_status": "unresolved", "unit": "degC",
            "rows_supplied": len(rows), "incomplete_pair_ids": missing,
            "complete_pairs": len(differences), "differences": differences,
            "mean_difference_degC": (math.fsum(x["sun_minus_shade_degC"] / len(differences)
                                              for x in differences) if differences else None),
            "independent_sample_size": None, "uncertainty_estimated": False,
            "canonical_write_performed": False, "scientific_evidence_eligible": False,
            "warning": "Pairs are rehearsal labels, not established independent samples. "
                       "Incomplete pairs are shown and omitted from arithmetic only. "
                       "Numerical input bounds are sanity checks, not instrument validity.",
            "claim_ceiling": CEILING}
