"""Non-evidentiary rehearsal drafts. Never writes canonical research records."""
from __future__ import annotations
import json
import os
from pathlib import Path
import sqlite3
from research_machine.application.beginner import validate_planning_notes
from research_machine.application.beginner_hypotheses import validate_hypothesis_notes
from research_machine.application.beginner_design import validate_design_notes
from research_machine.application.beginner_workspace import validate_workspace_notes

class DraftConflict(ValueError):
    pass

def validate_draft(value):
    if not isinstance(value, dict):
        raise ValueError("A draft object is required.")
    if value.get("review_status", "unresolved") != "unresolved" or value.get("scientific_evidence_eligible", False) is not False:
        raise ValueError("Drafts cannot grant scientific authority.")
    def snapshot(item):
        if not isinstance(item, dict):
            raise ValueError("Invalid draft snapshot.")
        result = {}
        if "workspace_notes" in item:
            result["workspace_notes"] = validate_workspace_notes(item["workspace_notes"])
        for key, limit in (("statement",2000),("prediction",10000),("reflection",10000)):
            text = item.get(key)
            if not isinstance(text,str) or len(text)>limit:
                raise ValueError("Invalid draft text.")
            result[key]=text
        if "recording_notes" in item:
            notes=item["recording_notes"]
            if not isinstance(notes,str) or len(notes)>10000:
                raise ValueError("Recording notes must be text of at most 10000 characters.")
            result["recording_notes"]=notes
        if "design_notes" in item:
            result["design_notes"] = validate_design_notes(item["design_notes"])
        if "hypothesis_notes" in item:
            result["hypothesis_notes"] = validate_hypothesis_notes(item["hypothesis_notes"])
        if "planning" in item:
            result["planning"]=validate_planning_notes(item["planning"])
        if "review_context" in item:
            context=item["review_context"]
            if (not isinstance(context,dict)
                or set(context)!={"reviewer_kind","notes","identity_status","authority"}
                or context["reviewer_kind"] not in ("unassigned","human","ai","hybrid")
                or not isinstance(context["notes"],str) or len(context["notes"])>10000
                or context["identity_status"]!="unverified"
                or context["authority"]!="review_only"):
                raise ValueError("Review context must remain unverified and review-only.")
            result["review_context"]=dict(context)
        rows=item.get("rows")
        if not isinstance(rows,list) or not 1<=len(rows)<=200:
            raise ValueError("Invalid rehearsal rows.")
        result["rows"]=[]
        for row in rows:
            if not isinstance(row,dict) or not isinstance(row.get("id"),str) or len(row["id"])>100:
                raise ValueError("Invalid rehearsal label.")
            clean={"id":row["id"]}
            for name in ("shade","sun"):
                reading=row.get(name)
                if reading is None:
                    reading=""
                # Current client retains raw text, including incomplete numeric input.
                if not isinstance(reading,str) or len(reading)>100:
                    raise ValueError("Rehearsal readings must be draft text.")
                clean[name]=reading
            result["rows"].append(clean)
        return result
    result=snapshot(value)
    history=value.get("history")
    if not isinstance(history,list) or len(history)>1000:
        raise ValueError("Draft history exceeds 1000 editing sessions. Download a copy.")
    result["history"]=[snapshot(item) for item in history]
    identifier=value.get("inquiry_id")
    import re
    if identifier is not None and (not isinstance(identifier,str) or re.fullmatch(r"[a-z0-9][a-z0-9-]{0,95}",identifier) is None):
        raise ValueError("Invalid inquiry reference.")
    result["inquiry_id"]=identifier
    text=value.get("saved_statement")
    if text is not None and (not isinstance(text,str) or len(text)>2000):
        raise ValueError("Invalid saved statement.")
    result["saved_statement"]=text
    state=value.get("save_state","draft")
    if state not in ("draft","pending","saved") or (state=="saved" and not identifier) or (state=="draft" and identifier):
        raise ValueError("Invalid inquiry save state.")
    result["save_state"]=state
    return result

class RehearsalDraftStore:
    def __init__(self, workspace, namespace):
        self.root=Path(workspace)
        self.path=self.root/"rehearsal-drafts.sqlite3"
        self.namespace=namespace

    def _check(self):
        if self.root.is_symlink() or self.path.is_symlink():
            raise ValueError("Symlinked draft storage is not supported.")

    def load(self):
        self._check()
        if not self.path.exists():
            return self._result(0,None)
        with sqlite3.connect(self.path) as db:
            row=db.execute("SELECT revision,payload FROM drafts WHERE namespace=? ORDER BY revision DESC LIMIT 1",(self.namespace,)).fetchone()
        return self._result(row[0],validate_draft(json.loads(row[1]))) if row else self._result(0,None)

    def _result(self, revision, draft):
        return {"revision":revision,"draft":draft,"kind":"non-evidentiary-rehearsal-draft",
                "review_status":"unresolved","scientific_evidence_eligible":False}

    def save(self, expected_revision, draft):
        if type(expected_revision) is not int or expected_revision<0:
            raise ValueError("Invalid draft revision.")
        clean=validate_draft(draft)
        payload=json.dumps(clean,sort_keys=True,separators=(",",":"),allow_nan=False)
        if len(payload.encode())>1048576:
            raise ValueError("Draft exceeds 1 MiB. Download a copy; no history was discarded.")
        self._check()
        if not self.root.is_dir():
            raise OSError("Persistent workspace is unavailable; no replacement was created.")
        # Explicit private file creation, independent of the GUI process umask.
        fd=os.open(self.path,os.O_CREAT|os.O_RDWR|os.O_NOFOLLOW,0o600)
        os.close(fd)
        with sqlite3.connect(self.path) as db:
            db.execute("PRAGMA synchronous=FULL")
            db.execute("CREATE TABLE IF NOT EXISTS drafts(namespace TEXT NOT NULL,revision INTEGER NOT NULL,payload TEXT NOT NULL,PRIMARY KEY(namespace,revision))")
            db.execute("BEGIN IMMEDIATE")
            row=db.execute("SELECT revision,payload FROM drafts WHERE namespace=? ORDER BY revision DESC LIMIT 1",(self.namespace,)).fetchone()
            current=row[0] if row else 0
            # Idempotent retry of the exact last write after a lost response.
            if row and current==expected_revision+1 and row[1]==payload:
                return self._result(current,clean)
            if expected_revision!=current:
                raise DraftConflict("A newer server draft exists. Local edits were retained; download them before reloading.")
            current+=1
            db.execute("INSERT INTO drafts VALUES(?,?,?)",(self.namespace,current,payload))
        return self._result(current,clean)
