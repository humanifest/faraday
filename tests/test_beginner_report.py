"""Synthetic, non-evidentiary rehearsal report checks."""
import unittest
from research_machine.application.beginner import rehearsal_report
from test_beginner_review_context import sample


def exported():
    return {**sample(),"kind":"non-evidentiary-rehearsal-draft",
            "review_status":"unresolved","scientific_evidence_eligible":False}


class RehearsalReportTests(unittest.TestCase):
    def test_negative_zero_and_missing_results_keep_their_limits(self):
        value=exported()
        value["rows"]=[{"id":"negative","shade":"25","sun":"20"},
                       {"id":"zero","shade":"20","sun":"20"},
                       {"id":"missing","shade":"","sun":"22"}]
        result=rehearsal_report(value)
        self.assertEqual(result["arithmetic"]["mean_difference_degC"],-2.5)
        self.assertEqual(result["arithmetic"]["incomplete_pair_ids"],["missing"])
        self.assertEqual(result["draft"]["rows"],value["rows"])
        self.assertEqual(len(result["pathway"]["decisions"]),7)
        self.assertTrue(all(item["status"]=="unresolved" for item in result["pathway"]["decisions"]))
        self.assertFalse(result["canonical_write_performed"])
        self.assertFalse(result["scientific_evidence_eligible"])
        self.assertFalse(result["independent_backup_verified"])
        self.assertFalse(result["arithmetic"]["uncertainty_estimated"])

    def test_all_missing_is_not_reported_as_zero(self):
        result=rehearsal_report(exported())
        self.assertIsNone(result["arithmetic"]["mean_difference_degC"])
        self.assertEqual(result["arithmetic"]["complete_pairs"],0)

    def test_invalid_inputs_and_authority_claims_are_rejected(self):
        for text in ("1e"," 20","Infinity","NaN","١","-274","1e999"):
            value=exported();value["rows"][0]["shade"]=text
            with self.subTest(text=text),self.assertRaises(ValueError):rehearsal_report(value)
        for patch in ({"kind":"scientific-evidence"},{"review_status":"approved"},
                      {"scientific_evidence_eligible":True}):
            with self.subTest(patch=patch),self.assertRaises(ValueError):rehearsal_report({**exported(),**patch})

    def test_recording_context_survives_report_without_becoming_a_gate(self):
        value=exported()
        value["recording_notes"]="pair-1: timezone unknown; late entry; impact unresolved."
        result=rehearsal_report(value)
        self.assertEqual(result["draft"]["recording_notes"],value["recording_notes"])
        self.assertFalse(result["scientific_evidence_eligible"])
        self.assertFalse(result["canonical_write_performed"])


if __name__=="__main__":unittest.main()
