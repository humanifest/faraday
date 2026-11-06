"""Synthetic inquiry recovery checks; standard-library runner supported."""
import hashlib
import json
import tempfile
import unittest
from http.client import HTTPConnection
from http.server import HTTPServer
from pathlib import Path
from threading import Thread

from research_machine.adapters.filesystem import FileSystemRepository
from research_machine.application.service import ResearchService
from research_machine.application.commands import CreateInquiry
from research_machine.application.beginner import inspect_saved_inquiry, start_inquiry
from research_machine.interfaces.beginner import make_handler


def snapshot(root):
    return {str(p.relative_to(root)):hashlib.sha256(p.read_bytes()).hexdigest()
            for p in root.rglob("*") if p.is_file()}


class SaveInspectionTests(unittest.TestCase):
    def test_complete_and_mismatch_are_read_only(self):
        with tempfile.TemporaryDirectory(prefix="faraday-inquiry-fixture-") as directory:
            root=Path(directory);service=ResearchService(FileSystemRepository(root))
            service.init_workspace()
            saved=start_inquiry(service,"Exact synthetic question?")
            before=snapshot(root)
            for identifier in (None,saved["inquiry_id"]):
                result=inspect_saved_inquiry(service,"Exact synthetic question?",identifier)
                self.assertEqual(result["status"],"matching_complete")
                self.assertEqual(result["inquiry_id"],saved["inquiry_id"])
                self.assertFalse(result["canonical_write_performed"])
                self.assertFalse(result["scientific_evidence_eligible"])
            mismatch=inspect_saved_inquiry(service,"Different synthetic question?")
            self.assertEqual(mismatch["status"],"no_match")
            self.assertNotIn("inquiry_id",mismatch)
            self.assertEqual(snapshot(root),before)

    def test_partial_save_does_not_offer_link_or_repair(self):
        with tempfile.TemporaryDirectory(prefix="faraday-partial-fixture-") as directory:
            root=Path(directory);service=ResearchService(FileSystemRepository(root))
            service.init_workspace()
            service.create_inquiry(CreateInquiry(title="Shade-temperature pathway v1 — review unresolved",
                                                initial_statement="Partial fixture?"))
            before=snapshot(root)
            result=inspect_saved_inquiry(service,"Partial fixture?")
            self.assertEqual(result["status"],"matching_incomplete")
            self.assertNotIn("inquiry_id",result)
            self.assertEqual(snapshot(root),before)

    def test_http_inspection_requires_session_and_does_not_initialize_workspace(self):
        with tempfile.TemporaryDirectory(prefix="faraday-inspect-http-") as directory:
            root=Path(directory)
            server=HTTPServer(("127.0.0.1",0),make_handler(root,"fixture-token"))
            thread=Thread(target=server.serve_forever,daemon=True);thread.start()
            def post(payload,authorized=True,path="/api/inquiry/inspect"):
                conn=HTTPConnection("127.0.0.1",server.server_port,timeout=5)
                headers={"Content-Type":"application/json"}
                if authorized:headers["X-Faraday-Token"]="fixture-token"
                conn.request("POST",path,json.dumps(payload),headers)
                response=conn.getresponse();status=response.status;response.read();conn.close();return status
            try:
                payload={"statement":"No inquiry fixture?","inquiry_id":None}
                self.assertEqual(post(payload,False),403)
                self.assertEqual(post(payload),400)
                self.assertEqual(post({**payload,"inquiry_id":"../../outside"}),400)
                self.assertEqual(post({**payload,"retry":True}),400)
                plan={"statement":"Planning fixture?","planning":{}}
                self.assertEqual(post(plan,False,path="/api/planning"),403)
                self.assertEqual(post(plan,path="/api/planning"),200)
                self.assertEqual(post({**plan,"approved":True},path="/api/planning"),400)
                from test_beginner_report import exported
                self.assertEqual(post(exported(),False,path="/api/rehearsal/report"),403)
                self.assertEqual(post(exported(),path="/api/rehearsal/report"),200)
                self.assertEqual(list(root.iterdir()),[])
                service=ResearchService(FileSystemRepository(root));service.init_workspace()
                start_inquiry(service,payload["statement"])
                before=snapshot(root)
                self.assertEqual(post(payload),200)
                self.assertEqual(snapshot(root),before)
            finally:
                server.shutdown();server.server_close();thread.join(timeout=5)


if __name__=="__main__":unittest.main()
