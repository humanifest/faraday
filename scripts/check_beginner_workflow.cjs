// Actual app client + actual loopback HTTP. DOM fixture only; not a rendered browser or human pilot.
const fs=require("node:fs"),assert=require("node:assert/strict");
globalThis.crypto ||= require("node:crypto").webcrypto;
(async()=>{
    const target=new URL(process.argv[2]);
    if(target.protocol!=="http:" || target.hostname!=="127.0.0.1" || target.username || target.password)throw Error("A plain loopback fixture origin is required.");
    const origin=target.origin,requests=[];
    const sourceReply=await fetch(origin+"/beginner.js");assert.equal(sourceReply.status,200);
    const source=await sourceReply.text(); // Session bootstrap stays inside this process; never print it.
    let harness=fs.readFileSync("scripts/check_beginner_client.js","utf8");
    harness=harness.slice(0,harness.indexOf('    check("syntax-and-initial-review-boundary"'))+"    return boot;\n}";
    harness=harness.replace("function boot(saved, storageFailure) {","function boot(saved, storageFailure, fetchOverride) {");
    harness=harness.replace('const fetch = (path, options) => {','const fetch = fetchOverride || ((path, options) => {');
    harness=harness.replace('}, null);\n        };\n        class BlobFixture','}, null);\n        });\n        class BlobFixture');
    harness=harness.replace('"setTimeout",\n            source','"setTimeout", "window",\n            source');
    harness=harness.replace('getDraft:()=>draft, restoreDraft','flush:saveNorwayDraft, sync:()=>({ready:norwayReady,blocked:norwayBlocked}), getDraft:()=>draft, restoreDraft');
    harness=harness.replace('callback => callback());','callback => callback(), {setTimeout:()=>1,clearTimeout:()=>{}});');
    harness=harness.replace('"error", "draft-status", "recover",','"error", "draft-status", "recover", "retry-draft", "restore-draft",');
    const boot=new Function("ObjC","$",harness+";return run([]);")({import:()=>{},unwrap:v=>v},{NSString:{stringWithContentsOfFileEncodingError:()=>source},NSUTF8StringEncoding:0});
    const ui=boot(undefined,false,async(path,options)=>{requests.push(path);return fetch(origin+path,options);});
    async function until(predicate){const deadline=Date.now()+10000;while(!predicate()){if(Date.now()>deadline)throw Error("Fixture did not reach expected readiness.");await new Promise(resolve=>setTimeout(resolve,20));}}
    await until(()=>ui.api.sync().ready && ui.document.getElementById("planning-title"));
    if(process.argv[3]==="--activity"){
        const question="Do sunny and shaded places have different temperatures?",prediction="I predict the sunny readings will be warmer.";
        ui.input("statement",question);ui.input("prediction",prediction);await ui.elements.save.onclick();
        assert.equal(ui.api.getDraft().saved_statement,question);assert.match(ui.elements["question-save-message"].textContent,/Your question is saved/);
        const inquiry=ui.api.getDraft().inquiry_id,readings=[];
        for(const [caseName,expected] of [["positive",/sunny readings average 4.00/],["null",/averages are the same/],["missing",/sunny readings average 1.00/],["invalid",null],["negative",/shaded readings average 4.00/]]){
            ui.elements["simulation-case"].value=caseName;ui.elements["simulation-case"].dispatch("change");
            await ui.elements["simulation-prepare"].onclick();assert.match(ui.elements["simulation-design"].textContent,/made-up readings/);
            await ui.elements["simulation-run"].onclick();
            if(caseName==="invalid"){assert.match(ui.elements["simulation-status"].textContent,/broken reading/);assert.equal(ui.elements["simulation-download"].disabled,true);readings.push(ui.elements["simulation-status"].textContent);continue;}
            assert.match(ui.elements["simulation-result"].textContent,expected);readings.push(ui.elements["simulation-result"].textContent);
            assert.equal(ui.active().id,"simulation-result");
        }
        const reflection="These are made-up numbers. I would check other explanations before making a claim about real places.";
        ui.input("reflection",reflection);await ui.api.flush();await ui.elements["simulation-download"].onclick();
        const report=ui.downloads.at(-1);assert.equal(report.name,"faraday-simulation-report.txt");
        for(const text of [question,prediction,reflection,"Example readings","These readings were made up for practice"])assert.ok(report.content.includes(text));
        assert.doesNotMatch(report.content,/SHA-256|EXACT ANALYSIS|research analysis run|\{"method"/);
        await ui.elements["next-question"].onclick();assert.equal(ui.api.getDraft().statement,question);ui.api.applyDraftImport();assert.equal(ui.api.getDraft().statement,"");
        assert.equal(ui.elements["simulation-download"].disabled,true);assert.match(ui.elements["simulation-status"].textContent,/Choose an example/);assert.match(ui.elements["simulation-result"].textContent,/Compare the example/);assert.equal(ui.downloads.at(-1).name,"faraday-previous-notes.txt");assert.ok(ui.downloads.at(-1).content.includes(question));await ui.api.flush();assert.equal(ui.api.sync().blocked,false);
        console.log(JSON.stringify({status:"passed",mode:"primary_practice_activity",rendered_browser:false,transport:"actual_loopback_http",inquiry_id:inquiry,
            original_question:question,cases:["positive","null","missing","invalid","negative"],readings,notes_in_private_report:true,previous_notebook_preserved:true,
            advanced_routes_used:requests.filter(path=>/^\/api\/(design|hypothesis|computation|assessment|portable-computation)\//.test(path))}));return;
    }
    const question="SOFTWARE FIXTURE: can a retained null calculation lead to an honest follow-up question?";
    ui.input("statement",question);ui.elements["workspace-start"].onclick();ui.elements["route-track"].onclick();ui.input("workspace-time","A declared software time window");ui.elements["route-model"].onclick();ui.input("workspace-model_input","An explicitly chosen input");await ui.api.flush();await ui.elements.save.onclick();
    assert.equal(ui.elements["workspace-question-title"].textContent,question);assert.equal(ui.api.getDraft().workspace_notes.approach,"model");
    const inquiry=ui.api.getDraft().inquiry_id;assert.equal(typeof inquiry,"string");assert.equal(ui.api.getDraft().saved_statement,question);
    const hypothesis={statement:"The null software case retains a zero signed mean difference.",observable_prediction:"The registered sun-minus-shade point estimate equals zero for the fixed null case.",null_model:"The retained estimate differs from zero.",competing_models:"A reversed comparison changes the sign.\nMissing values alter the arithmetic.",falsification_conditions:"The verified null-case point estimate is nonzero.",scope:"Synthetic software fixture only; no empirical or causal inference.",lineage:""};
    for(const [field,text] of Object.entries(hypothesis))ui.input("hypothesis-"+field,text);
    await ui.elements["hypothesis-save"].onclick();assert.match(ui.elements["hypothesis-status"].textContent,/saved as unreviewed/);
    for(const [field,text] of Object.entries({title:"Retain a null software contrast",outcome:"Generated mean difference",unit_of_observation:"One generated software unit"}))ui.input("planning-"+field,text);
    const design={data_scope:"synthetic",safety_constraints:"No physical collection, participants or external service calls.",methodology:"Execute the retained fixed synthetic comparison and retain its native result.",inputs_required:"Retained synthetic CSV and specification",quality_requirements:"execution-integrity",controls:"Changed bytes and invalid readings are separate adverse fixture checks.",sample_size_or_stopping_rule:"One fixed eight-record generated dataset.",missing_data_policy:"No missing observations in the null case.",success_conditions:"Retain valid zero and adverse outcomes.",failure_conditions:"Execution or artifact integrity fails.",expected_outputs:"Native output and receipt or retained refusal.",environment_requirements:"Existing local Python and bundled method."};
    for(const [field,text] of Object.entries(design))ui.input("design-"+field,text);
    ui.elements["simulation-case"].value="null";await ui.elements["simulation-prepare"].onclick();await ui.elements["simulation-to-design"].onclick();
    assert.match(ui.elements["simulation-to-design-status"].textContent,/copied for review/);
    assert.match(ui.api.getDraft().design_notes.analysis_code_hash,/^[a-f0-9]{64}$/);
    // The user did not enter JSON, CSV or a hash. Exact inputs came from the explicit retained recipe handoff.
    await ui.elements["design-preview"].onclick();assert.match(ui.elements["design-status"].textContent,/not ready to freeze/);
    await ui.elements["protocol-draft-save"].onclick();assert.match(ui.elements["protocol-draft-status"].textContent,/draft saved/);
    await ui.elements["computation-prepare"].onclick();assert.equal(ui.elements["computation-run"].disabled,false);
    await ui.elements["computation-run"].onclick();assert.match(ui.elements["computation-result"].textContent,/Mean difference: 0/);
    const retainedResult=ui.elements["computation-result"].textContent;
    ui.elements["route-sources"].onclick();ui.input("workspace-source_unclear","A working source note, not evidence.");
    assert.equal(ui.elements["computation-result"].textContent,retainedResult);assert.equal(ui.elements["computation-download"].disabled,false);
    await ui.api.flush();
    assert.match(ui.elements["computation-result"].textContent,/Bootstrap confidence interval/);
    await ui.elements["computation-portable-download"].onclick();
    const portable=JSON.parse(ui.downloads.at(-1).content);assert.equal(portable.format,"faraday-portable-computation-v1");
    ui.elements["computation-assess"].onclick();
    const followup="SOFTWARE FIXTURE: what happens when the registered group order is reversed?";
    const notes={interpretation:"The retained null case has a zero signed estimate.",uncertainty:"The bootstrap interval is conditional on independent generated units.",alternatives:"Other input choices, dependence and missingness remain relevant alternatives.",limitations:"Synthetic software fixture only, without empirical or causal interpretation.",followup_question:followup,decision_change:"A verified signed result that differs from the retained expected calculation would change this working interpretation."};
    for(const [field,text] of Object.entries(notes))ui.input("assessment-"+field,text);
    await ui.elements["assessment-save"].onclick();assert.match(ui.elements["assessment-status"].textContent,/assessment saved/);
    await ui.elements["assessment-download"].onclick();const assessment=JSON.parse(ui.downloads.at(-1).content);
    assert.equal(assessment.format,"faraday-working-assessment-v1");
    await ui.api.flush();await ui.elements["assessment-next"].onclick();assert.equal(ui.api.getDraft().statement,question);
    assert.match(ui.elements["assessment-status"].textContent,/staged for review/);
    ui.api.applyDraftImport();assert.equal(ui.api.getDraft().statement,followup);assert.equal(ui.api.getDraft().inquiry_id,null);
    assert.match(ui.api.getDraft().recording_notes,new RegExp(assessment.assessment.assessment_sha256));
    const previous=JSON.parse(ui.downloads.at(-1).content);assert.equal(previous.statement,question);assert.equal(previous.inquiry_id,inquiry);
    await ui.api.flush();assert.equal(ui.api.sync().blocked,false);
    // Retain and replay the browser-produced archive, then recover after a client restart.
    const archiveFile={size:Buffer.byteLength(JSON.stringify(portable)),text:async()=>JSON.stringify(portable)};
    ui.elements["portable-file"].files=[archiveFile];await ui.elements["portable-file"].listeners.change[0]();await ui.elements["portable-restore"].onclick();await ui.elements["portable-replay"].onclick();
    assert.match(ui.elements["portable-result"].textContent,/Byte-identical result replay/);
    const replayCalls=requests.filter(path=>path==="/api/portable-computation/replay").length;assert.equal(replayCalls,1);
    const resumed=boot(JSON.stringify(ui.api.draftExport()),false,async(path,options)=>{requests.push(path);return fetch(origin+path,options);});
    for(const [key,value] of ui.stored)resumed.stored.set(key,value);
    await until(()=>resumed.api.sync().ready);resumed.elements["portable-file"].files=[archiveFile];await resumed.elements["portable-file"].listeners.change[0]();await resumed.elements["portable-restore"].onclick();
    assert.equal(resumed.elements["portable-report"].disabled,false);assert.equal(resumed.elements["portable-replay"].disabled,true);assert.match(resumed.elements["portable-status"].textContent,/Earlier replay rechecked/);assert.equal(resumed.api.getDraft().statement,followup);
    await resumed.elements["portable-report"].onclick();const resumedReport=JSON.parse(resumed.downloads.at(-1).content);assert.equal(resumedReport.format,"faraday-portable-replay-report-v1");assert.equal(resumedReport.report.archive_sha256,portable.archive_sha256);assert.equal(requests.filter(path=>path==="/api/portable-computation/replay").length,replayCalls);
    console.log(JSON.stringify({status:"passed",rendered_browser:false,transport:"actual_loopback_http",specification_hand_editing:false,
        question_first_workspace_verified:true,canvas_switch_preserved_computation:true,inquiry_id:inquiry,portable_archive_sha256:portable.archive_sha256,portable_replay_recovered_after_reload:true,portable_replay_requests:replayCalls,assessment_sha256:assessment.assessment.assessment_sha256,
        original_question_preserved:previous.statement,followup_question:ui.api.getDraft().statement,followup_saved_as_inquiry:false,
        request_paths:[...new Set(requests)]}));
})().catch(error=>{console.error(error.message);process.exitCode=1;});
