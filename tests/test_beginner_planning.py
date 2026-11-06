"""Read-only guide integration on synthetic planning inputs."""
import tempfile
import unittest
from pathlib import Path
from research_machine.application.beginner import pathway, planning_preview
from research_machine.application.rehearsal_drafts import RehearsalDraftStore


class PlanningTests(unittest.TestCase):
    def test_unknowns_are_not_filled_or_treated_as_a_ready_design(self):
        packet=planning_preview({"statement":"Could material explain this synthetic difference?","planning":{}})
        self.assertEqual(packet["status"],"needs_clarification")
        self.assertEqual(len(packet["intake"]["clarifying_questions"]),12)
        self.assertIsNone(packet["intake"]["supplied_fields"]["outcome"])
        self.assertFalse(packet["analysis_performed"])
        self.assertFalse(packet["canonical_write_performed"])
        self.assertFalse(packet["scientific_evidence_eligible"])
        self.assertEqual({item["role"] for item in packet["competing_model_questions"]},
                         {"null","measurement_error","selection_or_confounding","user_explanation"})

    def test_literal_answers_reuse_existing_intake_contract(self):
        planning={item["field"]:"Synthetic answer" for item in pathway()["planning_fields"]}
        planning["decision_change_criteria"]="Precise null result\nOpposite pattern"
        packet=planning_preview({"statement":"Exact synthetic question?","planning":planning})
        self.assertEqual(packet["original_statement"],"Exact synthetic question?")
        self.assertEqual(packet["intake"]["supplied_fields"]["decision_change_criteria"],
                         ["Precise null result","Opposite pattern"])
        self.assertEqual(packet["intake"]["unresolved_fields"],[])
        self.assertEqual(packet["unresolved_fields"],["prospective_design","analysis_specification","observation_data"])
        self.assertEqual(packet["status"],"needs_clarification")
        self.assertEqual(packet["authority"],"review_only")

    def test_malformed_answers_fail_closed(self):
        for planning in ({"approved":"yes"},{"outcome":"x"*2001},{"decision":True},
                         {"decision":" padded "},{"decision_change_criteria":"Same\nsame"},
                         {"ethical_constraints":"One\n\nTwo"},{"original_statement":"replacement"}):
            with self.subTest(fields=list(planning)):
                with self.assertRaises(ValueError):
                    planning_preview({"statement":"Fixture?","planning":planning})

    def test_draft_and_history_preserve_unresolved_planning_answers(self):
        from test_beginner_review_context import sample
        draft=sample();draft["planning"]={"decision":"Fixture decision","outcome":""}
        earlier={key:draft[key] for key in ("statement","prediction","reflection","rows")}
        earlier["planning"]={"decision":"Earlier fixture decision"};draft["history"]=[earlier]
        with tempfile.TemporaryDirectory(prefix="faraday-planning-fixture-") as directory:
            root=Path(directory);store=RehearsalDraftStore(root,"a"*64)
            saved=store.save(0,draft)
            self.assertEqual(store.load(),saved)
            self.assertEqual(store.load()["draft"],draft)
            self.assertFalse((root/"workspace.json").exists())


if __name__=="__main__":unittest.main()
