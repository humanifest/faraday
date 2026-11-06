"""Computational design uses the native freeze preflight without canonical writes."""
import hashlib
from pathlib import Path
import pytest
from research_machine.adapters.filesystem import FileSystemRepository
from research_machine.application.service import ResearchService
from research_machine.application.commands import ProposeHypothesis
from research_machine.application.beginner import start_inquiry
from research_machine.application.beginner_design import DESIGN_FIELDS, preview_notebook_design, validate_design_notes


def setup(tmp_path):
    service=ResearchService(FileSystemRepository(tmp_path));service.init_workspace()
    question='Can this synthetic computation retain its registered contrast?'
    inquiry=start_inquiry(service,question)
    h=service.propose_hypothesis(ProposeHypothesis(statement='The registered software retains the signed synthetic calculation.',
        observable_prediction='Retained outputs match the specification and input bytes.',null_model='The bounded check fails.',
        competing_models=['Changed input bytes alter the result.'],falsification_conditions=['An altered input is accepted as unchanged.'],scope='Synthetic software only.'),inquiry['inquiry_id'])
    design={field:'' for field in DESIGN_FIELDS}
    design.update(data_scope='synthetic',safety_constraints='No physical acquisition, human participants, network or model calls.',
        methodology='Execute the retained fixed synthetic CSV with the registered independent mean-difference method.',
        inputs_required='Retained synthetic CSV and registered specification',quality_requirements='execution-integrity',
        controls='Adverse changed-byte cases retained separately.',expected_outputs='Native result and execution receipt or retained refusal.',
        success_conditions='Retain any valid signed result, including null or negative.',failure_conditions='The registered execution or integrity verification fails.',
        environment_requirements='Existing local Python and bundled registered method.',sample_size_or_stopping_rule='One fixed eight-record synthetic input, executed once.',
        missing_data_policy='No missing observations in this proposed case; refuse missingness rather than silently changing the rule.',
        analysis_code_hash=hashlib.sha256(Path('src/research_machine/addons/general_science.py').read_bytes()).hexdigest())
    payload={'inquiry_id':inquiry['inquiry_id'],'original_statement':question,'hypothesis_id':h.hypothesis_id,
             'hypothesis_sha256':h.scientific_content_sha256,'planning':{'title':'Retain a synthetic registered calculation','outcome':'Synthetic calculation and integrity disposition','unit_of_observation':'One generated software unit'},'design':design}
    return service,payload


def test_unreviewed_hypothesis_blocks_native_preflight_without_writes(tmp_path):
    service,payload=setup(tmp_path);head=service.verify_ledger(payload['inquiry_id'])
    result=preview_notebook_design(service,payload)
    assert result['status']=='blocked' and result['reason']
    assert result['hypothesis_workflow_state']=='unreviewed'
    assert result['protocol_input']['hypotheses_tested']==[payload['hypothesis_id']]
    assert result['hypothesis_sha256']==payload['hypothesis_sha256']
    assert result['protocol_input']['analysis_mode']=='exploratory'
    assert result['protocol_input']['protocol_kind']=='computational'
    assert not result['canonical_write_performed'] and not result['analysis_performed']
    assert not result['scientific_evidence_eligible']
    assert service.verify_ledger(payload['inquiry_id'])==head
    assert not service.list_protocols(payload['inquiry_id'])


def test_provisionally_staged_software_fixture_can_pass_native_check_without_freeze(tmp_path):
    service,payload=setup(tmp_path)
    service.stage_hypothesis(payload['hypothesis_id'],confidence='high',rationale='The software test proposition includes an observable result, competing null and falsifier. Provisional exploratory staging is reversible and does not establish scientific validity or human review.',inquiry_id=payload['inquiry_id'])
    head=service.verify_ledger(payload['inquiry_id'])
    result=preview_notebook_design(service,payload)
    assert result['status']=='ready_at_check_time',result['reason']
    assert result['native_preflight']['would_append_event'] is False
    assert result['native_preflight']['hypothesis_commitments']=={payload['hypothesis_id']:payload['hypothesis_sha256']}
    assert service.verify_ledger(payload['inquiry_id'])==head
    assert not service.list_protocols(payload['inquiry_id'])


@pytest.mark.parametrize('mutation',[{'original_statement':'Different literal question'}, {'hypothesis_sha256':'0'*64}, {'inquiry_id':None}, {'allow_freeze':True}])
def test_mismatched_binding_and_extra_authority_fail_closed(tmp_path,mutation):
    service,payload=setup(tmp_path);head=service.verify_ledger(payload['inquiry_id'])
    with pytest.raises(ValueError):preview_notebook_design(service,{**payload,**mutation})
    assert service.verify_ledger(payload['inquiry_id'])==head
    assert not service.list_protocols(payload['inquiry_id'])


@pytest.mark.parametrize('notes',[{'data_scope':''},{'data_scope':'human_or_unsure'}, {'data_scope':'human'}, {'controls':'Same\nSame'}, {'analysis_code_hash':'unverified-code'}, {'methodology':' padded '}])
def test_unsupported_data_and_invalid_notes_never_get_native_readiness(tmp_path,notes):
    service,payload=setup(tmp_path);head=service.verify_ledger(payload['inquiry_id'])
    payload['design']={**payload['design'],**notes}
    with pytest.raises(ValueError):preview_notebook_design(service,payload)
    assert service.verify_ledger(payload['inquiry_id'])==head


def test_blank_notes_remain_unresolved_not_filled_with_scientific_answers(tmp_path):
    service,payload=setup(tmp_path)
    payload['design']={field:('synthetic' if field=='data_scope' else '') for field in DESIGN_FIELDS}
    result=preview_notebook_design(service,payload)
    assert result['status']=='blocked'
    assert result['protocol_input']['analysis_code_hash']==''
    assert result['protocol_input']['methodology']==''
    assert result['protocol_input']['controls']==[]
    assert 'methodology' in result['unresolved_fields']
    with pytest.raises(ValueError):validate_design_notes({**payload['design'],'approved':True})


def test_data_scope_is_part_of_the_exact_design_context_commitment(tmp_path):
    service,payload=setup(tmp_path)
    synthetic=preview_notebook_design(service,payload)
    payload['design']['data_scope']='existing_nonhuman'
    existing=preview_notebook_design(service,payload)
    assert synthetic['protocol_input']['experiment_id']!=existing['protocol_input']['experiment_id']
    assert {k:v for k,v in synthetic['protocol_input'].items() if k!='experiment_id'}=={k:v for k,v in existing['protocol_input'].items() if k!='experiment_id'}
    assert synthetic['design_input_sha256']!=existing['design_input_sha256']
    assert not service.list_protocols(payload['inquiry_id'])


def test_http_design_preview_is_session_bound_and_never_writes(tmp_path):
    import json
    from http.client import HTTPConnection
    from http.server import HTTPServer
    from threading import Thread
    from research_machine.interfaces.beginner import make_handler
    service,payload=setup(tmp_path)
    before=service.verify_ledger(payload['inquiry_id'])
    server=HTTPServer(('127.0.0.1',0),make_handler(tmp_path,'design-session'))
    thread=Thread(target=server.serve_forever,daemon=True);thread.start()
    def request(token):
        conn=HTTPConnection(*server.server_address)
        headers={'Content-Type':'application/json','Host':f'127.0.0.1:{server.server_port}'}
        if token:headers['X-Faraday-Token']='design-session'
        conn.request('POST','/api/design/preview',json.dumps(payload),headers)
        response=conn.getresponse();value=json.loads(response.read());conn.close()
        return response.status,value
    try:
        assert request(False)[0]==403
        status,result=request(True)
        assert status==200 and result['status']=='blocked'
        assert result['canonical_write_performed'] is False
        assert service.verify_ledger(payload['inquiry_id'])==before
        assert not service.list_protocols(payload['inquiry_id'])
    finally:
        server.shutdown();server.server_close();thread.join()


def checked_draft(service,payload):
    from research_machine.application.beginner_design import notebook_protocol_draft
    preview=preview_notebook_design(service,payload)
    return notebook_protocol_draft,{'request':payload,'design_input_sha256':preview['design_input_sha256']}


def test_save_unready_design_as_draft_only_and_recover_exact_repeat(tmp_path):
    service,payload=setup(tmp_path);save,request=checked_draft(service,payload)
    before=service.verify_ledger(payload['inquiry_id'])
    assert save(service,request)['status']=='not_found'
    assert service.verify_ledger(payload['inquiry_id'])==before
    first=save(service,request,write=True)
    assert first['canonical_write_performed'] is True
    assert first['protocol']['status']=='draft' and first['protocol']['protocol_hash'] is None
    assert first['design']['status']=='blocked'
    assert first['protocol']['hypotheses_tested']==[payload['hypothesis_id']]
    assert service.get_hypothesis(payload['hypothesis_id'],payload['inquiry_id']).workflow_state.value=='unreviewed'
    after=service.verify_ledger(payload['inquiry_id'])
    assert after['events']==before['events']+1 and after['valid']
    for write in (False,True):
        same=save(service,request,write=write)
        assert same['canonical_write_performed'] is False
        assert same['protocol']==first['protocol']
        assert same['draft_payload_sha256']==first['draft_payload_sha256']
        assert service.verify_ledger(payload['inquiry_id'])==after
    assert len(service.list_protocols(payload['inquiry_id']))==1
    state=service.show_inquiry(payload['inquiry_id'])
    assert not state.get('datasets') and not state.get('runs') and not state.get('evidence')


def test_changed_design_requires_new_check_then_creates_separate_draft(tmp_path):
    import copy
    service,payload=setup(tmp_path);save,request=checked_draft(service,payload)
    first=save(service,request,write=True)
    changed=copy.deepcopy(request);changed['request']['design']['methodology']='A different computational method.'
    with pytest.raises(ValueError,match='changed after checking'):save(service,changed,write=True)
    new=preview_notebook_design(service,changed['request'])
    changed['design_input_sha256']=new['design_input_sha256']
    second=save(service,changed,write=True)
    assert second['protocol']['protocol_id']!=first['protocol']['protocol_id']
    assert service.get_protocol(first['protocol']['protocol_id'],payload['inquiry_id']).to_dict()==first['protocol']


def test_partial_protocol_write_never_blindly_retries(tmp_path,monkeypatch):
    service,payload=setup(tmp_path);save,request=checked_draft(service,payload)
    before=service.verify_ledger(payload['inquiry_id']);event=service._event
    monkeypatch.setattr(service,'_event',lambda *a,**k:(_ for _ in ()).throw(RuntimeError('interrupted before protocol event')))
    with pytest.raises(RuntimeError):save(service,request,write=True)
    monkeypatch.setattr(service,'_event',event)
    for write in (False,True):
        with pytest.raises(ValueError,match='Incomplete or ambiguous'):save(service,request,write=write)
    assert len(service.list_protocols(payload['inquiry_id']))==1
    assert service.verify_ledger(payload['inquiry_id'])==before


def test_changed_or_missing_draft_projection_is_not_recreated(tmp_path,monkeypatch):
    from dataclasses import replace
    service,payload=setup(tmp_path);save,request=checked_draft(service,payload)
    first=save(service,request,write=True)
    protocol=service.get_protocol(first['protocol']['protocol_id'],payload['inquiry_id'])
    before=service.verify_ledger(payload['inquiry_id'])
    for projections in ([replace(protocol,title='Changed draft title')],[]):
        monkeypatch.setattr(service.repository,'list_protocols',lambda *a,**k:projections)
        with pytest.raises(ValueError):save(service,request,write=True)
        assert service.verify_ledger(payload['inquiry_id'])==before


@pytest.mark.parametrize('extra',[{'freeze':True},{'approved':True},{'design_input_sha256':'0'*64}])
def test_protocol_request_cannot_add_authority_or_replace_commitment(tmp_path,extra):
    service,payload=setup(tmp_path);save,request=checked_draft(service,payload)
    before=service.verify_ledger(payload['inquiry_id'])
    with pytest.raises(ValueError):save(service,{**request,**extra},write=True)
    assert not service.list_protocols(payload['inquiry_id'])
    assert service.verify_ledger(payload['inquiry_id'])==before


def test_http_protocol_draft_save_and_inspection_preserve_native_boundaries(tmp_path):
    import json
    from http.client import HTTPConnection
    from http.server import HTTPServer
    from threading import Thread
    from research_machine.interfaces.beginner import make_handler
    service,payload=setup(tmp_path);_,request_body=checked_draft(service,payload)
    server=HTTPServer(('127.0.0.1',0),make_handler(tmp_path,'draft-session'))
    thread=Thread(target=server.serve_forever,daemon=True);thread.start()
    def request(path,body,token=True):
        conn=HTTPConnection(*server.server_address)
        headers={'Content-Type':'application/json','Host':f'127.0.0.1:{server.server_port}'}
        if token:headers['X-Faraday-Token']='draft-session'
        conn.request('POST',path,json.dumps(body),headers)
        response=conn.getresponse();value=json.loads(response.read());conn.close()
        return response.status,value
    try:
        assert request('/api/design/save',request_body,False)[0]==403
        status,result=request('/api/design/save',request_body)
        assert status==200 and result['protocol']['status']=='draft'
        head=service.verify_ledger(payload['inquiry_id'])
        assert request('/api/design/inspect',request_body)[1]['canonical_write_performed'] is False
        assert request('/api/design/save',request_body)[1]['canonical_write_performed'] is False
        assert request('/api/design/save',{**request_body,'freeze':True})[0]==400
        assert service.verify_ledger(payload['inquiry_id'])==head
        assert len(service.list_protocols(payload['inquiry_id']))==1
    finally:
        server.shutdown();server.server_close();thread.join()
