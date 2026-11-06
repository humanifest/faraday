"""Explicit unreviewed proposal entry; no activation, protocol, or evidence."""
from dataclasses import replace
import json
from http.client import HTTPConnection
from http.server import HTTPServer
from threading import Thread
import pytest
from research_machine.adapters.filesystem import FileSystemRepository
from research_machine.application.service import ResearchService
from research_machine.domain.errors import ValidationError
from research_machine.application.beginner import start_inquiry
from research_machine.application.beginner_hypotheses import notebook_hypothesis, validate_hypothesis_notes
from research_machine.application.rehearsal_drafts import validate_draft, RehearsalDraftStore
from research_machine.interfaces.beginner import make_handler


def setup(tmp_path):
    service=ResearchService(FileSystemRepository(tmp_path))
    service.init_workspace()
    question="Could a fixed synthetic contrast fail its proposed prediction?"
    inquiry=start_inquiry(service,question)
    proposal={"statement":"A synthetic positive case has a positive signed mean difference.",
              "observable_prediction":"The sun-minus-shade point estimate exceeds zero.",
              "null_model":"The signed point estimate equals zero.",
              "competing_models":"A reversed contrast changes the sign.\nA missing observation changes the calculation.",
              "falsification_conditions":"The valid positive case has a nonpositive point estimate.",
              "scope":"Software proposal only; no physical or causal conclusion.","lineage":""}
    return service,{"inquiry_id":inquiry['inquiry_id'],"original_statement":question,"proposal":proposal}


def test_proposal_sealed_unreviewed_and_exact_retry_is_read_only(tmp_path):
    service,payload=setup(tmp_path)
    before=service.verify_ledger(payload['inquiry_id'])
    assert notebook_hypothesis(service,payload)['status']=='not_found'
    assert service.verify_ledger(payload['inquiry_id'])==before
    first=notebook_hypothesis(service,payload,write=True)
    h=first['hypothesis']
    assert h['workflow_state']=='unreviewed'
    assert len(h['scientific_content_sha256'])==64
    assert h['statement']==payload['proposal']['statement']
    assert first['canonical_write_performed'] is True
    assert first['scientific_evidence_eligible'] is False
    after=service.verify_ledger(payload['inquiry_id'])
    assert after['events']==before['events']+1 and after['valid']
    for write in (False,True):
        read=notebook_hypothesis(service,payload,write=write)
        assert read['canonical_write_performed'] is False
        assert read['hypothesis']==h
        assert service.verify_ledger(payload['inquiry_id'])==after
    assert len(service.list_hypotheses(payload['inquiry_id']))==1
    state=service.show_inquiry(payload['inquiry_id'])
    for name in ('protocols','datasets','runs','evidence'):
        assert not state.get(name)


@pytest.mark.parametrize('mutation',[{'original_statement':'Different question'}, {'inquiry_id':None},
    {'authority':'approved'}, {'proposal':{'statement':'Incomplete'}},
    {'proposal':{'statement':' padded '}}, {'proposal':{'lineage':'unknown-hypothesis'}}])
def test_invalid_or_mismatched_proposals_make_no_write(tmp_path,mutation):
    service,payload=setup(tmp_path)
    before=service.verify_ledger(payload['inquiry_id'])
    bad={**payload,**mutation}
    if 'proposal' in mutation:
        bad['proposal']={**payload['proposal'],**mutation['proposal']}
        if mutation['proposal']=={'statement':'Incomplete'}:bad['proposal']['null_model']=''
    with pytest.raises((ValueError,ValidationError)):
        notebook_hypothesis(service,bad,write=True)
    assert service.verify_ledger(payload['inquiry_id'])==before
    assert not service.list_hypotheses(payload['inquiry_id'])


def test_revision_preserves_explicit_lineage(tmp_path):
    service,payload=setup(tmp_path)
    first=notebook_hypothesis(service,payload,write=True)['hypothesis']
    payload['proposal']={**payload['proposal'],'statement':'A narrowed synthetic software proposition.', 'lineage':first['hypothesis_id']}
    second=notebook_hypothesis(service,payload,write=True)['hypothesis']
    assert second['lineage']==[first['hypothesis_id']]
    assert second['hypothesis_id']!=first['hypothesis_id']
    assert service.get_hypothesis(first['hypothesis_id'],payload['inquiry_id']).to_dict()==first


def test_partial_write_is_not_silently_repeated(tmp_path,monkeypatch):
    service,payload=setup(tmp_path)
    original=service._event
    monkeypatch.setattr(service,'_event',lambda *a,**k:(_ for _ in ()).throw(RuntimeError('interrupted after projection')))
    with pytest.raises(RuntimeError):notebook_hypothesis(service,payload,write=True)
    monkeypatch.setattr(service,'_event',original)
    for write in (False,True):
        with pytest.raises(ValueError):notebook_hypothesis(service,payload,write=write)
    assert len(service.list_hypotheses(payload['inquiry_id']))==1
    assert service.verify_ledger(payload['inquiry_id'])['events']==8


def test_changed_scientific_payload_cannot_be_inspected_as_original(tmp_path,monkeypatch):
    service,payload=setup(tmp_path)
    notebook_hypothesis(service,payload,write=True)
    h=service.list_hypotheses(payload['inquiry_id'])[0]
    monkeypatch.setattr(service.repository,'list_hypotheses',lambda *a,**k:[replace(h,statement='Changed proposition')])
    with pytest.raises(ValidationError,match="service-generated commitment"):notebook_hypothesis(service,payload)


def test_notes_survive_server_restart_history_and_report_validation(tmp_path):
    _,payload=setup(tmp_path/'canonical')
    notes=payload['proposal']
    draft={'statement':'Working question','prediction':'','reflection':'','rows':[{'id':'one','shade':'','sun':''}],
           'hypothesis_notes':notes,'history':[],'inquiry_id':None,'saved_statement':None,'save_state':'draft'}
    (tmp_path/'drafts').mkdir()
    store=RehearsalDraftStore(tmp_path/'drafts','a'*64)
    result=store.save(0,draft)
    draft={**draft,'hypothesis_notes':{**notes,'statement':'Changed draft'},'history':[draft]}
    result=store.save(result['revision'],draft)
    read=RehearsalDraftStore(tmp_path/'drafts','a'*64).load()['draft']
    assert read['hypothesis_notes']['statement']=='Changed draft'
    assert read['history'][0]['hypothesis_notes']==notes
    with pytest.raises(ValueError):validate_hypothesis_notes({**notes,'review_status':'approved'})


def test_http_proposal_is_explicit_session_bound_and_inspection_read_only(tmp_path):
    service,payload=setup(tmp_path)
    server=HTTPServer(('127.0.0.1',0),make_handler(tmp_path,'fixture-session'))
    thread=Thread(target=server.serve_forever,daemon=True);thread.start()
    def request(path,body,session=True):
        conn=HTTPConnection(*server.server_address)
        headers={'Content-Type':'application/json','Host':f'127.0.0.1:{server.server_port}'}
        if session:headers['X-Faraday-Token']='fixture-session'
        conn.request('POST',path,json.dumps(body),headers)
        response=conn.getresponse();result=json.loads(response.read());conn.close()
        return response.status,result
    try:
        assert request('/api/hypothesis/propose',payload,False)[0]==403
        status,result=request('/api/hypothesis/inspect',payload)
        assert status==200 and result['status']=='not_found'
        status,result=request('/api/hypothesis/propose',payload)
        assert status==200 and result['hypothesis']['workflow_state']=='unreviewed'
        head=service.verify_ledger(payload['inquiry_id'])
        assert request('/api/hypothesis/inspect',payload)[1]['canonical_write_performed'] is False
        assert service.verify_ledger(payload['inquiry_id'])==head
    finally:
        server.shutdown();server.server_close();thread.join()
