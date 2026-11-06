"""Synthetic fixtures for the offline published-data replay adapter."""
import datetime as dt
import tempfile
import unittest
from pathlib import Path

from scripts.prepare_vine_replay import first_complete_day, read_source, replay_draft
from research_machine.application.rehearsal_drafts import validate_draft
from research_machine.application.beginner import rehearsal_report


def records(day, sun=30., shade=20.):
    return [{"time":dt.datetime.combine(day,dt.time())+dt.timedelta(minutes=15*i),
             "source_row":i+2,"sun":sun,"shade":shade,"cached_sun":str(sun),"cached_shade":str(shade)}
            for i in range(96)]


class VineReplayTests(unittest.TestCase):
    def test_day_selection_is_chronological_not_effect_selected(self):
        first=dt.date(2000,1,1);second=first+dt.timedelta(days=1)
        earlier=records(first,sun=10.,shade=20.)
        day, selected=first_complete_day(records(second,sun=90.,shade=20.)+earlier)
        self.assertEqual(day,first)
        draft,lineage,_=replay_draft(day,selected)
        self.assertEqual(len(draft["rows"]),24)
        self.assertEqual(lineage[0]["source_rows"],[2,3,4,5])
        validate_draft(draft)
        result=rehearsal_report(draft)
        self.assertEqual(result["arithmetic"]["mean_difference_degC"],-10.)
        self.assertFalse(result["scientific_evidence_eligible"])
        self.assertFalse(result["canonical_write_performed"])

    def test_missing_intervals_cannot_masquerade_as_a_complete_day(self):
        day=dt.date(2000,1,1)
        for value in (records(day)[:-1],records(day)[1:]+[records(day)[-1]]):
            with self.assertRaises(ValueError):first_complete_day(value)
        value=records(day);value[15]["shade"]=None
        with self.assertRaises(ValueError):first_complete_day(value)

    def test_summary_mismatch_blocks_without_choosing_another_day(self):
        first=dt.date(2000,1,1);value=records(first)
        value[0]["cached_sun"]="999"
        day,selected=first_complete_day(value+records(first+dt.timedelta(days=1)))
        self.assertEqual(day,first)
        with self.assertRaises(ValueError):replay_draft(day,selected)

    def test_changed_or_symlinked_source_is_rejected(self):
        with tempfile.TemporaryDirectory(prefix="faraday-replay-fixture-") as directory:
            path=Path(directory)/"changed.xlsx";path.write_bytes(b"synthetic changed source")
            with self.assertRaises(ValueError):read_source(path)
            link=Path(directory)/"link.xlsx";link.symlink_to(path)
            with self.assertRaises(ValueError):read_source(link)


if __name__=="__main__":unittest.main()
