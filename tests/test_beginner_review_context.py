"""Synthetic draft checks runnable with the Python standard library only."""
import copy
import tempfile
import unittest
from pathlib import Path

from research_machine.application.rehearsal_drafts import RehearsalDraftStore, validate_draft


def sample():
    return {"statement":"Fixture question", "prediction":"", "reflection":"",
            "rows":[{"id":"fixture-pair", "shade":"", "sun":""}],
            "history":[], "inquiry_id":None, "saved_statement":None, "save_state":"draft"}


class ReviewContextTests(unittest.TestCase):
    def test_legacy_payload_stays_unchanged(self):
        self.assertEqual(validate_draft(sample()), sample())

    def test_review_notes_and_history_survive_reopen_without_authority(self):
        value=sample()
        context={"reviewer_kind":"ai", "notes":"Synthetic review: check alternatives.",
                 "identity_status":"unverified", "authority":"review_only"}
        value["review_context"]=context
        earlier={key:copy.deepcopy(value[key]) for key in
                 ("statement","prediction","reflection","rows","review_context")}
        earlier["review_context"]["notes"]="Earlier synthetic note"
        value["history"]=[earlier]
        with tempfile.TemporaryDirectory(prefix="faraday-review-fixture-") as directory:
            root=Path(directory)
            saved=RehearsalDraftStore(root,"a"*64).save(0,value)
            restored=RehearsalDraftStore(root,"a"*64).load()
            self.assertEqual(restored,saved)
            self.assertEqual(restored["draft"],value)
            self.assertFalse(restored["scientific_evidence_eligible"])
            self.assertEqual(restored["review_status"],"unresolved")
            self.assertEqual(sorted(path.name for path in root.iterdir()),["rehearsal-drafts.sqlite3"])

    def test_authority_injection_fails_before_storage(self):
        context={"reviewer_kind":"human", "notes":"Fixture",
                 "identity_status":"unverified", "authority":"review_only"}
        for patch in ({"authority":"approve"},{"identity_status":"verified"},
                      {"reviewer_kind":"qualified"},{"notes":"x"*10001},
                      {"approved":True},{"notes":None}):
            for historical in (False,True):
                with self.subTest(patch=list(patch),historical=historical):
                    value=sample()
                    bad={**context,**patch}
                    if historical:
                        value["history"]=[{**sample(),"review_context":bad}]
                    else:
                        value["review_context"]=bad
                    with tempfile.TemporaryDirectory(prefix="faraday-review-rejection-") as directory:
                        root=Path(directory)
                        with self.assertRaises(ValueError):
                            RehearsalDraftStore(root,"a"*64).save(0,value)
                        self.assertEqual(list(root.iterdir()),[])


if __name__ == "__main__":
    unittest.main()
