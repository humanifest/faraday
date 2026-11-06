// Simulated asynchronous transport tests; no browser, network or packages.
const fs=require("node:fs"),assert=require("node:assert/strict");
globalThis.crypto ||= require("node:crypto").webcrypto;
const source=fs.readFileSync(process.argv[2],"utf8");
let harness=fs.readFileSync(process.argv[3],"utf8");
harness=harness.slice(0,harness.indexOf('    check("syntax-and-initial-review-boundary"'))+"    return boot;\n}";
harness=harness.replace("function boot(saved, storageFailure) {","function boot(saved, storageFailure, fetchOverride) {");
harness=harness.replace('const fetch = (path, options) => {','const fetch = fetchOverride || ((path, options) => {');
harness=harness.replace('        class BlobFixture', '        class BlobFixture'); // Fixture body remains shared.
harness=harness.replace('}, null);\n        };\n        class BlobFixture','}, null);\n        });\n        class BlobFixture');
harness=harness.replace('"setTimeout",\n            source', '"setTimeout", "window",\n            source');
harness=harness.replace('getDraft:()=>draft, restoreDraft', 'flush:saveNorwayDraft, recover:recoverNorwayDraft, sync:()=>({revision:norwayRevision,blocked:norwayBlocked,ready:norwayReady}), getDraft:()=>draft, restoreDraft');
harness=harness.replace('callback => callback());','callback => callback(), {setTimeout:()=>1,clearTimeout:()=>{}});');
harness=harness.replace('"error", "draft-status", "recover",','"error", "draft-status", "recover", "retry-draft", "restore-draft",');
const ObjC={import:()=>{},unwrap:value=>value};
const $={NSString:{stringWithContentsOfFileEncodingError:()=>source},NSUTF8StringEncoding:0};
const boot=new Function("ObjC","$",harness+";return run([]);")(ObjC,$);
const settle=async()=>{for(let i=0;i<20;i++)await Promise.resolve();};
const clone=value=>JSON.parse(JSON.stringify(value));
function remote(){
    const state={revision:0,draft:null,offline:false,lose:false,hold:false,release:null,saves:0};
    const result=()=>({revision:state.revision,draft:clone(state.draft),review_status:"unresolved",scientific_evidence_eligible:false});
    state.fetch=async(path,options)=>{
        if(path==="/api/pathway")return{ok:true,json:async()=>({alternatives:[],decisions:[],published_example_available:state.published===true,planning_fields:[{field:"decision",text:"What decision?"}]})};
        if(state.offline)throw Error("Offline");
        if(path==="/api/examples/published")return{ok:true,json:async()=>await state.example()};
        if(path==="/api/inquiry/inspect")return{ok:true,json:async()=>state.inspect ? await state.inspect() : state.inspection};
        if(path==="/api/planning")return{ok:true,json:async()=>state.planning ? await state.planning() : state.planningResult};
        if(path==="/api/rehearsal/report")return{ok:true,json:async()=>state.report(JSON.parse(options.body))};
        if(path==="/api/draft/load")return{ok:true,json:async()=>result()};
        assert.equal(path,"/api/draft/save");
        const payload=JSON.parse(options.body);
        if(payload.expected_revision!==state.revision)return{ok:false,json:async()=>({error:"Conflict"})};
        state.revision++;state.draft=payload.draft;state.saves++;
        const value=result();
        if(state.lose){state.lose=false;throw Error("Acknowledgement lost");}
        if(state.hold){state.hold=false;await new Promise(resolve=>{state.release=resolve;});}
        return{ok:true,json:async()=>value};
    };
    return state;
}
(async()=>{
    let checks=0;
    // Actual client load, save, empty-browser restore and second edit/revision.
    const server=remote(),a=boot(undefined,false,server.fetch);await settle();
    assert.equal(a.api.sync().ready,true);
    a.input("statement","Keep my question");await a.api.flush();
    assert.equal(server.draft.statement,"Keep my question");
    assert.match(a.elements["draft-status"].textContent,/notes are saved in Faraday/);
    const b=boot(undefined,false,server.fetch);await settle();
    assert.equal(b.elements.statement.value,"Keep my question");
    assert.equal(b.api.getDraft().rows[0].shade,"");
    b.input("pair-0-shade","1e");await b.api.flush();
    assert.equal(server.draft.rows[0].shade,"1e");
    checks++;
    // No success claim while disconnected, no local-data loss.
    server.offline=true;b.input("reflection","Offline thought");await b.api.flush();
    assert.equal(b.api.getDraft().reflection,"Offline thought");
    assert.match(b.elements["draft-status"].textContent,/failed or conflicted/);
    server.offline=false;await b.api.recover();await b.api.flush();
    assert.equal(server.draft.reflection,"Offline thought");checks++;
    // A second active browser cannot silently overwrite a newer revision.
    const c=boot(undefined,false,server.fetch);await settle();
    b.input("prediction","Newer server thought");await b.api.flush();
    c.input("prediction","Stale browser thought");await c.api.flush();
    assert.equal(c.api.sync().blocked,true);
    assert.equal(server.draft.prediction,"Newer server thought");
    assert.equal(c.api.getDraft().prediction,"Stale browser thought");checks++;
    // Recovery reconciles a committed write whose acknowledgement was lost.
    const d=boot(undefined,false,server.fetch);await settle();
    d.input("reflection","Saved despite lost reply");server.lose=true;await d.api.flush();
    const count=server.saves;assert.equal(d.api.sync().blocked,true);
    await d.api.recover();await d.api.flush();
    assert.equal(d.api.sync().blocked,false);assert.equal(server.saves,count);checks++;
    // An older acknowledgement never marks newly typed text as protected.
    const e=boot(undefined,false,server.fetch);await settle();
    e.input("reflection","First in-flight edit");server.hold=true;
    const pending=e.api.flush();await settle();
    e.input("reflection","Later edit");
    server.release();await pending;
    assert.doesNotMatch(e.elements["draft-status"].textContent,/notes are saved in Faraday/);
    await e.api.flush();assert.equal(server.draft.reflection,"Later edit");checks++;
    // Download/import round trip preserves the current working copy before replacement.
    const imported=clone(b.api.draftExport());
    imported.statement="Recovered download";
    const file=value=>{const raw=JSON.stringify(value);return{size:Buffer.byteLength(raw),text:async()=>raw};};
    const f=boot(undefined,false,server.fetch);await settle();
    f.input("reflection","Preserve before import");
    const before=clone(f.api.getDraft());
    await f.api.prepareDraftImport(file(imported));
    assert.deepEqual(f.api.getDraft(),before);
    assert.equal(f.elements["import-apply"].hidden,false);
    f.api.applyDraftImport();
    assert.equal(f.api.getDraft().statement,"Recovered download");
    assert.equal(JSON.parse(f.downloads[0].content).reflection,"Preserve before import");
    assert.ok([...f.stored.keys()].some(key=>key.includes(":before-import:")));
    await f.api.flush();assert.equal(server.draft.statement,"Recovered download");checks++;
    // An import cannot attest canonical saving or approve science.
    await f.api.prepareDraftImport(file({...imported,inquiry_id:"existing-inquiry",save_state:"saved",saved_statement:"Original"}));
    f.api.applyDraftImport();
    assert.equal(f.api.getDraft().save_state,"pending");
    assert.equal(f.elements.save.disabled,true);
    assert.match(f.elements.saved.textContent,/Do not retry/);checks++;
    const unchanged=clone(f.api.getDraft());
    for(const bad of [
        {size:1048577,text:async()=>{throw Error("Must not read oversized file");}},
        {size:4,text:async()=>"{bad"},
        file({...imported,review_status:"approved"}),
        file({...imported,scientific_evidence_eligible:true}),
        file({...imported,history:Array(1001).fill(imported.history[0]||{})}),
        file({...imported,inquiry_id:"../../outside"})
    ]){
        await f.api.prepareDraftImport(bad);f.api.applyDraftImport();
        assert.deepEqual(f.api.getDraft(),unchanged);
        assert.equal(f.elements["import-apply"].hidden,true);
    }checks++;
    // Failed retention must leave the current draft untouched.
    const g=boot(undefined,true,server.fetch);await settle();
    const kept=clone(g.api.getDraft());
    await g.api.prepareDraftImport(file(imported));g.api.applyDraftImport();
    assert.deepEqual(g.api.getDraft(),kept);assert.equal(g.downloads.length,0);checks++;
    // A slow previous selection cannot replace the latest validated selection.
    let releaseFile;
    const pendingFile=f.api.prepareDraftImport({size:10,text:()=>new Promise(resolve=>{releaseFile=resolve;})});
    await f.api.prepareDraftImport(file({...imported,statement:"Latest selection"}));
    releaseFile(JSON.stringify({...imported,statement:"Older selection"}));await pendingFile;
    f.api.applyDraftImport();assert.equal(f.api.getDraft().statement,"Latest selection");checks++;
    // Restoring is blocked during an in-flight save; no old acknowledgement may win.
    await f.api.flush();f.input("reflection","In-flight original");server.hold=true;
    const activeSave=f.api.flush();await settle();
    await f.api.prepareDraftImport(file(imported));f.api.applyDraftImport();
    assert.equal(f.api.getDraft().reflection,"In-flight original");
    assert.match(f.elements["import-status"].textContent,/Wait/);
    server.release();await activeSave;f.api.applyDraftImport();
    assert.equal(f.api.getDraft().statement,"Recovered download");checks++;
    // Recording context retains original edits across autosave, reopen and import.
    const notesServer=remote(), notesUI=boot(undefined,false,notesServer.fetch);await settle();
    notesUI.input("recording_notes","pair-1: source time 09:00, timezone unknown; sun unavailable.");
    notesUI.elements.recording_notes.dispatch("blur");
    notesUI.input("recording_notes","pair-1: source time 09:15; recorded late; effect unknown.");
    await notesUI.api.flush();
    const notesReopened=boot(undefined,false,notesServer.fetch);await settle();
    assert.equal(notesReopened.elements.recording_notes.value,"pair-1: source time 09:15; recorded late; effect unknown.");
    assert.ok(notesReopened.api.getDraft().history.some(item=>item.recording_notes.includes("09:00")));
    const notesExport=notesReopened.api.draftExport();
    await notesReopened.api.prepareDraftImport(file(notesExport));notesReopened.api.applyDraftImport();
    assert.equal(notesReopened.api.getDraft().recording_notes,notesExport.recording_notes);
    assert.equal(notesReopened.api.draftExport().scientific_evidence_eligible,false);checks++;
    // Review notes are retained, restored and exported without acquiring authority.
    const h=boot(undefined,false,server.fetch);await settle();
    h.elements["reviewer-kind"].value="ai";h.elements["reviewer-kind"].dispatch("change");
    h.input("review-notes","Consider material and timing as alternatives.");
    h.elements["review-notes"].dispatch("blur");
    h.input("review-notes","Check the instrument too.");
    assert.ok(h.api.getDraft().history.some(item=>item.review_context.notes.includes("material")));
    await h.api.flush();
    const i=boot(undefined,false,server.fetch);await settle();
    assert.equal(i.elements["reviewer-kind"].value,"ai");
    assert.equal(i.elements["review-notes"].value,"Check the instrument too.");
    assert.equal(i.api.draftExport().review_context.authority,"review_only");
    assert.equal(i.api.draftExport().review_context.identity_status,"unverified");
    for(const patch of [{authority:"approve"},{identity_status:"verified"},{approved:true},{reviewer_kind:"expert"}]){
        const bad={...i.api.draftExport(),review_context:{...i.api.getDraft().review_context,...patch}};
        await i.api.prepareDraftImport(file(bad));
        assert.equal(i.elements["import-apply"].hidden,true);
    }checks++;
    // Inspection is read-only and only explicit matching adoption clears a pending draft.
    const j=boot(undefined,false,server.fetch);await settle();
    j.input("statement","Recover uncertain question?");
    j.api.getDraft().save_state="pending";
    const matching={status:"matching_complete",canonical_write_performed:false,
        review_status:"unresolved",scientific_evidence_eligible:false,
        inquiry_id:"fixture-existing",original_statement:"Recover uncertain question?",ledger_head_sha256:"a".repeat(64)};
    server.inspection=matching;
    await j.elements["inspect-inquiry"].onclick();
    assert.equal(j.api.getDraft().save_state,"pending");
    assert.equal(j.elements["link-inquiry"].hidden,false);
    j.elements["link-inquiry"].onclick();
    assert.equal(j.api.getDraft().save_state,"saved");
    assert.equal(j.api.getDraft().inquiry_id,"fixture-existing");
    assert.equal(j.elements.statement.readOnly,true);checks++;
    for(const response of [{...matching,status:"matching_incomplete"},
        {...matching,status:"no_match"},{...matching,canonical_write_performed:true},
        {...matching,original_statement:"Wrong question"},{...matching,ledger_head_sha256:"bad"}]){
        server.inspection=response;await j.elements["inspect-inquiry"].onclick();
        assert.equal(j.elements["link-inquiry"].hidden,true);
    }checks++;
    let finishInspection;
    server.inspect=()=>new Promise(resolve=>{finishInspection=resolve;});
    const inspection=j.elements["inspect-inquiry"].onclick();await settle();
    j.input("reflection","Edit while inspecting");finishInspection(matching);await inspection;
    assert.equal(j.elements["link-inquiry"].hidden,true);
    assert.match(j.elements["inspect-status"].textContent,/changed/);checks++;
    // Lost canonical acknowledgement stays blocked until read-only inspection and explicit linking.
    const lostServer=remote(); let inquiryWrites=0;
    const lostQuestion="Exact question after a lost acknowledgement?";
    const lostFetch=async(path,options)=>{
        if(path==="/api/inquiry") {inquiryWrites++;throw Error("Acknowledgement lost after save");}
        if(path==="/api/inquiry/inspect") return {ok:true,json:async()=>({...matching,
            inquiry_id:"lost-ack-fixture",original_statement:lostQuestion})};
        return lostServer.fetch(path,options);
    };
    const recovered=boot(undefined,false,lostFetch);await settle();
    recovered.input("statement",lostQuestion);
    await recovered.elements.save.onclick();
    assert.equal(inquiryWrites,1);assert.equal(recovered.api.getDraft().save_state,"pending");
    assert.equal(recovered.elements.save.disabled,true);
    assert.match(recovered.elements.saved.textContent,/Check existing saved question/);
    assert.match(recovered.elements.error.textContent,/Check existing saved question/);
    await recovered.elements.save.onclick();assert.equal(inquiryWrites,1);
    await recovered.elements["inspect-inquiry"].onclick();
    assert.equal(recovered.api.getDraft().save_state,"pending");
    recovered.elements["link-inquiry"].onclick();
    assert.equal(recovered.api.getDraft().save_state,"saved");
    assert.equal(recovered.api.getDraft().statement,lostQuestion);
    assert.equal(recovered.elements.statement.readOnly,true);
    await recovered.elements.save.onclick();assert.equal(inquiryWrites,1);
    assert.equal(recovered.api.draftExport().scientific_evidence_eligible,false);checks++;
    // A late canonical save response must never attach to a replacement draft.
    const savingServer=remote();let releaseInquirySave;
    const savingFetch=async(path,options)=>{
        if(path==="/api/inquiry")return new Promise(resolve=>{releaseInquirySave=()=>resolve({ok:true,json:async()=>({inquiry_id:"in-flight-original",original_statement:"Original in-flight question?"})});});
        return savingServer.fetch(path,options);
    };
    const savingUI=boot(undefined,false,savingFetch);await settle();
    savingUI.input("statement","Original in-flight question?");await savingUI.api.flush();
    const savingRequest=savingUI.elements.save.onclick();await settle();await savingUI.api.flush();
    await savingUI.api.recover(true);
    assert.equal(savingUI.api.getDraft().statement,"Original in-flight question?");
    assert.equal(savingUI.elements.statement.readOnly,true);
    assert.match(savingUI.elements["draft-status"].textContent,/inquiry save/);
    const replacement={...clone(imported),statement:"Replacement selected during save",inquiry_id:null,saved_statement:null,save_state:"draft"};
    await savingUI.api.prepareDraftImport(file(replacement));savingUI.api.applyDraftImport();
    assert.equal(savingUI.api.getDraft().statement,"Original in-flight question?");
    assert.equal(savingUI.downloads.length,0);
    assert.match(savingUI.elements["import-status"].textContent,/inquiry save/);
    releaseInquirySave();await savingRequest;
    assert.equal(savingUI.api.getDraft().inquiry_id,"in-flight-original");
    assert.equal(savingUI.api.getDraft().saved_statement,"Original in-flight question?");
    await savingUI.api.flush();savingUI.api.applyDraftImport();
    assert.equal(savingUI.api.getDraft().statement,replacement.statement);
    assert.equal(savingUI.api.getDraft().inquiry_id,null);
    assert.equal(JSON.parse(savingUI.downloads.at(-1).content).inquiry_id,"in-flight-original");checks++;
    // A terminal lost acknowledgement releases the transient lock, while retaining uncertainty.
    const failedSave=boot(undefined,false,lostFetch);await settle();
    failedSave.input("statement",lostQuestion);await failedSave.elements.save.onclick();await failedSave.api.flush();
    assert.equal(failedSave.api.getDraft().save_state,"pending");
    await failedSave.api.prepareDraftImport(file(replacement));failedSave.api.applyDraftImport();
    assert.equal(failedSave.api.getDraft().statement,replacement.statement);
    assert.equal(JSON.parse(failedSave.downloads.at(-1).content).save_state,"pending");checks++;
    // Guided planning is literal, persisted and invalidated by later edits.
    const k=boot(undefined,false,server.fetch);await settle();
    k.input("statement","Planning fixture?");k.input("planning-decision","Consider a later reviewed study");
    await k.api.flush();
    const l=boot(undefined,false,server.fetch);await settle();
    assert.equal(l.document.getElementById("planning-decision").value,"Consider a later reviewed study");
    const plan={authority:"review_only",canonical_write_performed:false,analysis_performed:false,
        scientific_evidence_eligible:false,original_statement:"Planning fixture?",
        intake:{unresolved_fields:["outcome"],clarifying_questions:[{field:"outcome",text:"What outcome?"}]},
        competing_model_questions:[{question:"Could measurement error explain it?"}]};
    server.planningResult=plan;await l.elements["planning-preview"].onclick();
    assert.equal(l.elements["planning-unresolved"].children[0].textContent,"What outcome?");
    assert.match(l.elements["planning-status"].textContent,/does not approve/);
    l.input("planning-decision","Revised fixture decision");
    assert.equal(l.elements["planning-unresolved"].children.length,0);
    assert.ok(l.api.getDraft().history.some(item=>item.planning.decision==="Consider a later reviewed study"));checks++;
    let finishPlan;server.planning=()=>new Promise(resolve=>{finishPlan=resolve;});
    const pendingPlan=l.elements["planning-preview"].onclick();await settle();
    l.input("reflection","Changed during planning preview");finishPlan(plan);await pendingPlan;
    assert.equal(l.elements["planning-unresolved"].children.length,0);checks++;
    // The readable download escapes learner text and never implies scientific evidence.
    const m=boot(undefined,false,server.fetch);await settle();
    m.input("pair-0-shade","");m.input("pair-0-sun","");
    m.input("statement",'<script>alert("fixture")</script>');
    m.input("reflection","<img src=https://invalid.example>");
    m.input("recording_notes","pair-1: <b>timezone unknown</b>\nTiming departure, effect unresolved.");
    const report=input=>({kind:"non-evidentiary-rehearsal-report",review_status:"unresolved",
        scientific_evidence_eligible:false,canonical_write_performed:false,independent_backup_verified:false,
        draft:clone(input),arithmetic:{mean_difference_degC:null,complete_pairs:0,differences:[],
            incomplete_pair_ids:["pair-1"],warning:"Missing readings",claim_ceiling:"Rehearsal only"},
        pathway:{alternatives:["Measurement error"],decisions:[{id:"validity",question:"Check validity"}]}});
    server.report=report;await m.elements.report.onclick();
    const html=m.downloads[0].content;
    assert.equal(m.downloads[0].name,"faraday-rehearsal-report.html");
    assert.ok(html.includes("&lt;script&gt;"));assert.ok(!html.includes("<script>"));
    assert.ok(html.includes("&lt;b&gt;timezone unknown&lt;/b&gt;<br>Timing departure"));
    assert.ok(!html.includes("<img"));assert.match(html,/Not scientific evidence/);
    assert.match(html,/Unavailable; no complete pairs/);assert.match(html,/Content-Security-Policy/);checks++;
    server.report=input=>({...report(input),draft:{...input,statement:"Wrong bytes"}});
    await m.elements.report.onclick();assert.equal(m.downloads.length,1);checks++;
    let finishReport;
    server.report=input=>new Promise(resolve=>{finishReport=()=>resolve(report(input));});
    const pendingReport=m.elements.report.onclick();await settle();
    m.input("reflection","Changed after request");finishReport();await pendingReport;
    assert.equal(m.downloads.length,1);checks++;
    // Multiple recovery actions at the same clock time must retain distinct copies.
    const n=boot(undefined,false,server.fetch);await settle();
    const originalNow=Date.now;Date.now=()=>123456789;
    try {
        n.input("reflection","First original to preserve");
        await n.api.prepareDraftImport(file(imported));n.api.applyDraftImport();
        n.input("reflection","Second original to preserve");
        await n.api.prepareDraftImport(file(imported));n.api.applyDraftImport();
        const retained=[...n.stored.entries()].filter(([key])=>key.includes(":before-import:123456789"));
        assert.equal(retained.length,2);
        assert.deepEqual(retained.map(([,bytes])=>JSON.parse(bytes).reflection),
            ["First original to preserve","Second original to preserve"]);
    } finally {Date.now=originalNow;}
    checks++;
    // Simulation is staged, invalidates on case changes and reverifies before download.
    const labServer=remote();let verifyFails=false;
    const prepared={status:"prepared",simulation_id:"a".repeat(32),recipe_sha256:"b".repeat(64),
        recipe:{case:"positive",scientific_evidence_eligible:false},canonical_write_performed:false};
    const designSpec=JSON.stringify({method:"independent_mean_difference_ci",study_design:"independent_groups",outcome_column:"temperature",group_column:"group",groups:["sun","shade"],unit_column:"unit",seed:17,bootstrap_resamples:1000,confidence_level:0.95});
    const designCsv="unit,group,temperature\n"+["sun","shade"].flatMap(group=>[20,22,24,26].map((n,i)=>group+"-"+(i+1)+","+group+","+(n+(group==="sun"?4:0)))).join("\n")+"\n";
    const designHash=text=>require("node:crypto").createHash("sha256").update(text).digest("hex");
    prepared.design={specification_json:designSpec,input_csv:designCsv};
    prepared.recipe.specification_sha256=designHash(designSpec);prepared.recipe.input_sha256=designHash(designCsv);
    const simulated={status:"verified",simulation_id:prepared.simulation_id,recipe_sha256:prepared.recipe_sha256,
        receipt_sha256:"c".repeat(64),scientific_evidence_eligible:false,canonical_write_performed:false,
        notice:"Synthetic only",method:"independent_mean_difference_ci",implementation_sha256:"d".repeat(64),
        addon:{addon_id:"general_science",version:"fixture"},environment:{python:"fixture",platform:"fixture"},result:{result:{mean_difference_first_minus_second:4,
            confidence_interval:{lower:1,upper:7},exclusion_report:{excluded_records:[]},assumptions:["Synthetic independent units"]}}};
    const labFetch=async(path,options)=>{
        if(path.startsWith("/api/simulation/")) {
            if(path.endsWith("/verify")&&verifyFails)throw Error("Changed output");
            return {ok:true,json:async()=>path.endsWith("/prepare")?prepared:simulated};
        }
        return labServer.fetch(path,options);
    };
    const lab=boot(undefined,false,labFetch);await settle();lab.elements["simulation-case"].value="positive";
    await lab.elements["simulation-prepare"].onclick();assert.equal(lab.elements["simulation-run"].disabled,false);
    await lab.elements["simulation-run"].onclick();assert.match(lab.elements["simulation-result"].textContent,/4.00/);
    await lab.elements["simulation-technical-download"].onclick();assert.equal(lab.downloads.length,1);
    assert.ok(lab.downloads[0].content.includes(designCsv));
    assert.ok(lab.downloads[0].content.includes(designSpec));
    assert.match(lab.downloads[0].content,/mean sun minus mean shade/);
    assert.match(lab.downloads[0].content,/Implementation SHA-256: d{64}/);
    assert.match(lab.downloads[0].content,/research analysis run.*--expect-input-sha256/);
    assert.match(lab.downloads[0].content,/not independent replication/);
    verifyFails=true;await lab.elements["simulation-download"].onclick();assert.equal(lab.downloads.length,1);
    assert.equal(lab.elements["simulation-download"].disabled,true);
    // A later successful read-only retry must restore the visible verified values.
    verifyFails=false;await lab.elements["simulation-verify"].onclick();
    assert.equal(lab.elements["simulation-download"].disabled,false);
    assert.match(lab.elements["simulation-result"].textContent,/4.00/);
    assert.doesNotMatch(lab.elements["simulation-result"].textContent,/Verification failed/);
    assert.equal(lab.downloads.length,1);
    lab.elements["simulation-case"].value="negative";lab.elements["simulation-case"].dispatch("change");
    assert.equal(lab.elements["simulation-run"].disabled,true);assert.equal(lab.elements["simulation-result"].textContent,"");checks++;
    assert.equal(lab.elements["simulation-design"].textContent,"");
    // The pre-run view is byte-bound; changed inputs cannot silently define another design.
    for(const mutate of [value=>{value.design.input_csv+="sun-5,sun,99\n";},
        value=>{const spec=JSON.parse(value.design.specification_json);spec.groups=["shade","sun"];value.design.specification_json=JSON.stringify(spec);value.recipe.specification_sha256=designHash(value.design.specification_json);}]) {
        const corrupt=clone(prepared);mutate(corrupt);
        const badDesignFetch=async(path,options)=>path==="/api/simulation/prepare"?{ok:true,json:async()=>corrupt}:labServer.fetch(path,options);
        const badDesignUI=boot(undefined,false,badDesignFetch);await settle();badDesignUI.elements["simulation-case"].value="positive";
        await badDesignUI.elements["simulation-prepare"].onclick();
        assert.equal(badDesignUI.elements["simulation-run"].disabled,true);
        assert.equal(badDesignUI.elements["simulation-design"].textContent,"");
        assert.match(badDesignUI.elements["simulation-status"].textContent,/could not get this example ready/);checks++;
    }
    const inspectedDesign=boot(undefined,false,labFetch);await settle();inspectedDesign.elements["simulation-case"].value="positive";
    await inspectedDesign.elements["simulation-prepare"].onclick();
    assert.match(inspectedDesign.elements["simulation-design"].textContent,/mean sun temperature minus mean shade/);
    assert.match(inspectedDesign.elements["simulation-design"].textContent,/95%.*1000.*17/);
    assert.match(inspectedDesign.elements["simulation-design"].textContent,/sun-1/);
    assert.match(inspectedDesign.elements["simulation-design"].textContent,/Missing or invalid readings stop the calculation/);checks++;
    // Changing the previously inspected design must block a later report even with a valid result.
    await inspectedDesign.elements["simulation-run"].onclick();
    const originalCsv=prepared.design.input_csv;prepared.design.input_csv+="sun-5,sun,99\n";
    await inspectedDesign.elements["simulation-download"].onclick();
    assert.equal(inspectedDesign.downloads.length,0);
    assert.match(inspectedDesign.elements["simulation-status"].textContent,/We could not check these notes/);
    prepared.design.input_csv=originalCsv;checks++;
    // Saved simulation creation is single-attempt; resume is read-only and failures block export.
    let canonicalWrites=0, inspectFail=false;
    const savedFixture={status:"canonical_fixture_recorded",simulation_id:prepared.simulation_id,
        recipe_sha256:prepared.recipe_sha256,report_sha256:"d".repeat(64),package_manifest_sha256:"e".repeat(64),
        canonical_write_performed:true,package_verification:{status:"passed"},workspace_scope:"isolated_synthetic_fixture",
        scientific_evidence_eligible:false,evidence_count:0,hypothesis_status:"pending_review",ledger:{valid:true},
        run_status:"completed",report:"Synthetic null fixture. Pending human review; zero evidence."};
    const savedFetch=async(path,options)=>{
        if(path==="/api/simulation/canonical"){canonicalWrites++;return{ok:true,json:async()=>savedFixture};}
        if(path==="/api/simulation/inspect"){
            if(inspectFail)throw Error("Changed canonical artifact");
            return{ok:true,json:async()=>({...savedFixture,status:"verified_canonical_fixture"})};
        }
        return labFetch(path,options);
    };
    const savedUI=boot(undefined,false,savedFetch);await settle();savedUI.elements["simulation-case"].value="positive";
    await savedUI.elements["simulation-prepare"].onclick();await savedUI.elements["simulation-canonical"].onclick();
    await savedUI.elements["simulation-canonical"].onclick();assert.equal(canonicalWrites,1);
    assert.equal(savedUI.elements["simulation-export"].disabled,false);
    assert.ok([...savedUI.stored.keys()].some(key=>key.endsWith(":saved-simulation-reference")));
    await savedUI.elements["simulation-resume"].onclick();assert.equal(canonicalWrites,1);
    assert.match(savedUI.elements["simulation-canonical-status"].textContent,/No canonical write/);
    inspectFail=true;await savedUI.elements["simulation-resume"].onclick();
    assert.equal(savedUI.elements["simulation-export"].disabled,true);
    assert.equal(savedUI.elements["simulation-canonical-report"].textContent,"");checks++;
    // Recovery files are staged, scope-bound and reverified without canonical writes.
    inspectFail=false;const originalDraftBytes=JSON.stringify(savedUI.api.draftExport());
    savedUI.elements["simulation-reference-download"].onclick();
    const recoveryReference=JSON.parse(savedUI.downloads.at(-1).content);
    savedUI.elements["simulation-reference-clear"].onclick();
    assert.equal(savedUI.elements["simulation-resume"].disabled,true);
    assert.match(savedUI.elements["simulation-canonical-status"].textContent,/No saved simulation reference/);
    await savedUI.api.prepareSimulationReferenceImport(file(recoveryReference));
    assert.equal(savedUI.elements["simulation-resume"].disabled,true);
    await savedUI.elements["simulation-reference-apply"].onclick();
    assert.equal(savedUI.elements["simulation-export"].disabled,false);assert.equal(canonicalWrites,1);
    assert.match(savedUI.elements["simulation-canonical-status"].textContent,/Imported saved simulation reverified/);
    assert.equal(JSON.stringify(savedUI.api.draftExport()),originalDraftBytes);checks++;
    for(const malformed of [{...recoveryReference,workspace_fingerprint:"other"},
        {...recoveryReference,approved:true},{...recoveryReference,reference:{...recoveryReference.reference,report_sha256:"bad"}}]) {
        await savedUI.api.prepareSimulationReferenceImport(file(malformed));
        assert.equal(savedUI.elements["simulation-reference-apply"].disabled,true);
    }
    await savedUI.api.prepareSimulationReferenceImport({size:8193,text:async()=>"{}"});
    assert.equal(savedUI.elements["simulation-reference-apply"].disabled,true);checks++;
    // Published examples stage through existing recovery without touching current data.
    const exampleServer=remote();exampleServer.published=true;
    const publishedDraft={...clone(imported),statement:"Published fixture replay",rows:[{id:"published-pair",shade:"20",sun:"18"}],
        history:[],inquiry_id:null,saved_statement:null,save_state:"draft"};
    const publishedReply={status:"published_example_checked",manifest_sha256:"f".repeat(64),draft:publishedDraft,
        data_classification:"published_observations_not_synthetic",source:{citation:"Fixture attribution"},
        notice:"Published observations, not synthetic data.",canonical_write_performed:false,scientific_evidence_eligible:false};
    exampleServer.example=async()=>publishedReply;
    const exampleUI=boot(undefined,false,exampleServer.fetch);await settle();
    exampleUI.input("statement","Original draft to preserve");await exampleUI.api.flush();
    const beforeExample=JSON.stringify(exampleUI.api.draftExport());
    await exampleUI.elements["published-example-stage"].onclick();
    assert.equal(JSON.stringify(exampleUI.api.draftExport()),beforeExample);
    assert.equal(exampleUI.downloads.length,0);assert.equal(exampleUI.elements["import-apply"].hidden,false);
    assert.equal(exampleUI.active().id,"import-apply");
    assert.match(exampleUI.elements["published-example-status"].textContent,/Fixture attribution/);
    exampleUI.api.applyDraftImport();
    assert.equal(exampleUI.api.getDraft().statement,publishedDraft.statement);
    assert.match(exampleUI.elements["published-example-status"].textContent,/Published example restored/);
    assert.equal(JSON.parse(exampleUI.downloads.at(-1).content).statement,"Original draft to preserve");
    await exampleUI.api.flush();assert.equal(exampleServer.draft.statement,publishedDraft.statement);checks++;
    // A late response must not stage after the learner edits the draft.
    let releaseExample;exampleServer.example=()=>new Promise(resolve=>{releaseExample=resolve;});
    const pendingExample=exampleUI.elements["published-example-stage"].onclick();await settle();
    exampleUI.input("reflection","Edit during example load");releaseExample(publishedReply);await pendingExample;
    assert.equal(exampleUI.elements["import-apply"].hidden,true);
    assert.match(exampleUI.elements["published-example-status"].textContent,/changed while loading/);checks++;
    // An older failed example request cannot clear a newer staged file import.
    let rejectExample;exampleServer.example=()=>new Promise((resolve,reject)=>{rejectExample=reject;});
    const olderExample=exampleUI.elements["published-example-stage"].onclick();await settle();
    await exampleUI.api.prepareDraftImport(file({...publishedDraft,statement:"Newer selected file"}));
    rejectExample(Error("Old request failed"));await olderExample;
    assert.equal(exampleUI.elements["import-apply"].hidden,false);
    await exampleUI.api.flush();exampleUI.api.applyDraftImport();
    assert.equal(exampleUI.api.getDraft().statement,"Newer selected file");checks++;
    exampleServer.example=async()=>({...publishedReply,canonical_write_performed:true});
    const unchangedExample=JSON.stringify(exampleUI.api.draftExport());
    await exampleUI.elements["published-example-stage"].onclick();
    assert.equal(exampleUI.elements["import-apply"].hidden,true);
    assert.equal(JSON.stringify(exampleUI.api.draftExport()),unchangedExample);checks++;
    const unavailableExample=boot(undefined,false,remote().fetch);await settle();
    assert.equal(unavailableExample.elements["published-example-stage"].disabled,true);
    assert.match(unavailableExample.elements["published-example-status"].textContent,/No local published example/);checks++;
    // The journey can begin another question without JSON or changing the saved inquiry.
    const nextServer=remote();
    const priorQuestion={...clone(imported),statement:"Saved original question?",inquiry_id:"saved-original",saved_statement:"Saved original question?",save_state:"saved"};
    const nextUI=boot(JSON.stringify(priorQuestion),false,nextServer.fetch);await settle();await nextUI.api.flush();
    const priorBytes=JSON.stringify(nextUI.api.draftExport());
    await nextUI.elements["next-question"].onclick();
    assert.equal(JSON.stringify(nextUI.api.draftExport()),priorBytes);
    assert.equal(nextUI.downloads.length,0);assert.equal(nextUI.active().id,"import-apply");
    assert.match(nextUI.elements["import-apply"].textContent,/start another question/);
    nextUI.api.applyDraftImport();
    assert.equal(nextUI.api.getDraft().statement,"");assert.equal(nextUI.api.getDraft().inquiry_id,null);
    assert.equal(nextUI.elements.statement.readOnly,false);assert.equal(nextUI.active().id,"statement");
    assert.equal(nextUI.downloads.at(-1).name,"faraday-previous-notes.txt");
    assert.ok(nextUI.downloads.at(-1).content.includes("Saved original question?"));
    assert.ok([...nextUI.stored.entries()].some(([key,value])=>key.includes(":before-import:") && JSON.parse(value).inquiry_id==="saved-original"));
    await nextUI.api.flush();assert.equal(nextServer.draft.statement,"");
    const nextReload=boot(undefined,false,nextServer.fetch);await settle();
    assert.equal(nextReload.api.getDraft().statement,"");assert.equal(nextReload.api.getDraft().inquiry_id,null);checks++;
    // An uncertain save may not be abandoned, including one begun after staging.
    const pendingUI=boot(JSON.stringify({...priorQuestion,inquiry_id:null,save_state:"pending"}),false,remote().fetch);await settle();
    pendingUI.elements["import-apply"].hidden=true; // Match the initial HTML state.
    await pendingUI.elements["next-question"].onclick();
    assert.equal(pendingUI.elements["import-apply"].hidden,true);
    assert.match(pendingUI.elements["next-question-status"].textContent,/uncertain/);
    await nextUI.elements["next-question"].onclick();nextUI.api.getDraft().save_state="pending";
    const beforeBlocked=JSON.stringify(nextUI.api.draftExport());nextUI.api.applyDraftImport();
    assert.equal(JSON.stringify(nextUI.api.draftExport()),beforeBlocked);checks++;
    // A newer file selection wins and resets the new-question affordance.
    nextUI.api.getDraft().save_state="draft";
    await nextUI.api.prepareDraftImport(file({...publishedDraft,statement:"Chosen file instead"}));
    assert.equal(nextUI.elements["import-apply"].textContent,"Keep current copy and restore selected draft");
    await nextUI.api.flush();nextUI.api.applyDraftImport();
    assert.equal(nextUI.api.getDraft().statement,"Chosen file instead");checks++;
    // Failure to retain the previous copy stops replacement.
    const blockedNext=boot(JSON.stringify(priorQuestion),true,remote().fetch);await settle();
    await blockedNext.elements["next-question"].onclick();blockedNext.api.applyDraftImport();
    assert.equal(blockedNext.api.getDraft().statement,priorQuestion.statement);
    assert.equal(blockedNext.downloads.length,0);checks++;
    // Beginning another question leaves the independent saved-study reference usable.
    const referenceEntries=[...savedUI.stored.entries()].filter(([key])=>key.endsWith(":saved-simulation-reference"));
    const writesBeforeNext=canonicalWrites;
    await savedUI.elements["next-question"].onclick();await savedUI.api.flush();savedUI.api.applyDraftImport();
    assert.deepEqual([...savedUI.stored.entries()].filter(([key])=>key.endsWith(":saved-simulation-reference")),referenceEntries);
    assert.equal(canonicalWrites,writesBeforeNext);
    assert.equal(savedUI.elements["simulation-resume"].disabled,false);checks++;
    // Literal falsifiable proposal notes persist, retain corrections and survive restart/import.
    const hypothesisServer=remote();
    const modelUI=boot(undefined,false,hypothesisServer.fetch);await settle();
    const modelFields={statement:"A literal model <not HTML>",observable_prediction:"An observable numerical contrast.",null_model:"No contrast.",competing_models:"Measurement error.\nSelection.",falsification_conditions:"A valid contradictory result.",scope:"Synthetic demonstration only.",lineage:""};
    for(const [field,text] of Object.entries(modelFields))modelUI.input("hypothesis-"+field,text);
    await modelUI.api.flush();
    assert.deepEqual(hypothesisServer.draft.hypothesis_notes,modelFields);
    modelUI.document.getElementById("hypothesis-statement").dispatch("blur");modelUI.input("hypothesis-statement","A corrected model");
    assert.ok(modelUI.api.getDraft().history.some(item=>item.hypothesis_notes.statement==="A literal model <not HTML>"));
    await modelUI.api.flush();const modelReload=boot(undefined,false,hypothesisServer.fetch);await settle();
    assert.equal(modelReload.document.getElementById("hypothesis-statement").value,"A corrected model");
    assert.equal(modelReload.elements["hypothesis-save"].disabled,true);checks++;
    const modelInquiry={...clone(imported),statement:"Exact saved model question?",saved_statement:"Exact saved model question?",inquiry_id:"model-inquiry",save_state:"saved",hypothesis_notes:modelFields};
    const modelReply=body=>({status:"unreviewed_hypothesis",request_sha256:"9".repeat(64),inquiry_id:body.inquiry_id,original_statement:body.original_statement,proposal:body.proposal,
        hypothesis:{hypothesis_id:"hyp-fixture",scientific_content_sha256:"a".repeat(64),workflow_state:"unreviewed",statement:body.proposal.statement,observable_prediction:body.proposal.observable_prediction,null_model:body.proposal.null_model,competing_models:body.proposal.competing_models.split("\n"),falsification_conditions:body.proposal.falsification_conditions.split("\n"),scope:body.proposal.scope,lineage:[]},ledger:{valid:true},canonical_write_performed:true,scientific_evidence_eligible:false});
    const writeServer=remote();let modelWrites=0,loseModelReply=false;
    const modelFetch=async(path,options)=>{
        if(path.startsWith("/api/hypothesis/")) {
            const body=JSON.parse(options.body),value=modelReply(body);
            if(path.endsWith("/propose")){modelWrites++;if(loseModelReply)throw Error("Lost acknowledgement");}
            else value.canonical_write_performed=false;
            return {ok:true,json:async()=>value};
        }
        return writeServer.fetch(path,options);
    };
    const canonicalModel=boot(JSON.stringify(modelInquiry),false,modelFetch);await settle();await canonicalModel.api.flush();
    await canonicalModel.elements["hypothesis-save"].onclick();
    assert.equal(modelWrites,1);assert.match(canonicalModel.elements["hypothesis-status"].textContent,/saved as unreviewed/);
    assert.match(canonicalModel.elements["hypothesis-saved"].textContent,/literal model <not HTML>/);
    assert.equal(canonicalModel.api.getDraft().statement,modelInquiry.statement);
    await canonicalModel.elements["hypothesis-inspect"].onclick();assert.equal(modelWrites,1);
    assert.match(canonicalModel.elements["hypothesis-status"].textContent,/Nothing written/);checks++;
    loseModelReply=true;await canonicalModel.elements["hypothesis-save"].onclick();
    assert.equal(canonicalModel.elements["hypothesis-save"].disabled,true);
    await canonicalModel.elements["hypothesis-save"].onclick();assert.equal(modelWrites,2);
    await canonicalModel.elements["hypothesis-inspect"].onclick();assert.equal(modelWrites,2);
    assert.equal(canonicalModel.elements["hypothesis-save"].disabled,false);checks++;
    // An authority-bearing or different scientific payload is rejected as an unverified response.
    const badModelFetch=async(path,options)=>{
        if(path.startsWith("/api/hypothesis/")){const value=modelReply(JSON.parse(options.body));value.hypothesis.workflow_state="active";return {ok:true,json:async()=>value};}
        return remote().fetch(path,options);
    };
    const badModel=boot(JSON.stringify(modelInquiry),false,badModelFetch);await settle();
    await badModel.elements["hypothesis-save"].onclick();
    assert.equal(badModel.elements["hypothesis-saved"].textContent,"");
    assert.match(badModel.elements["hypothesis-status"].textContent,/could not be confirmed/);checks++;
    // A revision is not a content receipt: every known scientific note must survive the acknowledgement.
    for(const corrupt of [reply=>{delete reply.draft.hypothesis_notes;},
        reply=>{reply.draft.hypothesis_notes.scope="Silently substituted scope";},
        reply=>{reply.draft.history=[];},reply=>{reply.draft=null;},
        reply=>{reply.revision+=5;}]) {
        const ackServer=remote();
        const ackFetch=async(path,options)=>{
            const response=await ackServer.fetch(path,options);
            if(path!=="/api/draft/save")return response;
            const reply=await response.json();corrupt(reply);return {ok:true,json:async()=>reply};
        };
        const ackUI=boot(undefined,false,ackFetch);await settle();
        ackUI.input("hypothesis-statement","A literal proposition worth preserving.");
        ackUI.input("hypothesis-scope","Original scope, not silently changed.");
        const beforeAck=clone(ackUI.api.getDraft());await ackUI.api.flush();
        assert.equal(ackUI.api.sync().blocked,true);
        assert.deepEqual(ackUI.api.getDraft(),beforeAck);
        assert.doesNotMatch(ackUI.elements["draft-status"].textContent,/notes are saved in Faraday/);
        assert.equal(ackUI.api.sync().revision,0);checks++;
    }
    // Harmless JSON object ordering differences are not content changes.
    const reorderServer=remote();
    const reorder=value=>Array.isArray(value)?value.map(reorder):value&&typeof value==="object"?Object.fromEntries(Object.keys(value).sort().reverse().map(key=>[key,reorder(value[key])])):value;
    const reordered=boot(undefined,false,async(path,options)=>{
        const response=await reorderServer.fetch(path,options);
        return {ok:response.ok,json:async()=>reorder(await response.json())};
    });await settle();
    reordered.input("hypothesis-statement","Order does not change my proposition.");await reordered.api.flush();
    assert.equal(reordered.api.sync().blocked,false);
    assert.match(reordered.elements["draft-status"].textContent,/notes are saved in Faraday/);checks++;
    // Computational design is bound to the checked sealed hypothesis and native readiness response.
    const designServer=remote();let lastDesign=null,designAuthority=false,releaseDesign=null;
    const designReply=body=>{
        const sorted=value=>Array.isArray(value)?value.map(sorted):value&&typeof value==="object"?Object.fromEntries(Object.keys(value).sort().map(key=>[key,sorted(value[key])])):value;
        const lists=["safety_constraints","inputs_required","quality_requirements","controls","success_conditions","failure_conditions","expected_outputs","environment_requirements"];
        const protocol_input={experiment_id:"notebook-design-"+designHash(JSON.stringify(sorted(body))),title:body.planning.title,primary_outcome:body.planning.outcome,sampling_unit:body.planning.unit_of_observation || "",human_subjects:false,analysis_mode:"exploratory",protocol_kind:"computational",hypotheses_tested:[body.hypothesis_id],
            ...Object.fromEntries(Object.entries(body.design).filter(([key])=>key!=="data_scope").map(([key,text])=>[key,lists.includes(key)?(text?text.split("\n"):[]):text]))};
        return {status:"blocked",authority:"review_only",canonical_write_performed:designAuthority,analysis_performed:false,scientific_evidence_eligible:false,
            inquiry_id:body.inquiry_id,original_statement:body.original_statement,hypothesis_id:body.hypothesis_id,hypothesis_sha256:body.hypothesis_sha256,
            planning:body.planning,design:body.design,hypothesis_statement:modelFields.statement,hypothesis_workflow_state:"unreviewed",protocol_input,
            design_input_sha256:designHash(JSON.stringify(sorted({request:body,protocol_input}))),
            reason:"Native check refuses an unreviewed hypothesis.",notice:"No protocol created, frozen, executed or approved."};
    };
    const designFetch=async(path,options)=>{
        if(path==="/api/hypothesis/inspect"){const value=modelReply(JSON.parse(options.body));value.canonical_write_performed=false;return {ok:true,json:async()=>value};}
        if(path==="/api/design/preview"){lastDesign=JSON.parse(options.body);return {ok:true,json:async()=>releaseDesign?await new Promise(resolve=>{releaseDesign=()=>resolve(designReply(lastDesign));}):designReply(lastDesign)};}
        return designServer.fetch(path,options);
    };
    const designUI=boot(JSON.stringify({...modelInquiry,planning:{title:"A retained computational design",outcome:"A bounded signed calculation",unit_of_observation:"A generated software unit"}}),false,designFetch);await settle();
    assert.equal(designUI.elements["design-preview"].disabled,true);
    await designUI.elements["hypothesis-inspect"].onclick();assert.equal(designUI.elements["design-preview"].disabled,false);
    designUI.input("design-data_scope","synthetic");designUI.input("design-methodology","Retain every generated input and the signed calculation.");
    await designUI.api.flush();assert.equal(designServer.draft.design_notes.methodology,"Retain every generated input and the signed calculation.");
    await designUI.elements["design-preview"].onclick();assert.equal(lastDesign.hypothesis_id,"hyp-fixture");
    assert.match(designUI.elements["design-status"].textContent,/not ready to freeze/);
    assert.match(designUI.elements["design-result"].textContent,/unreviewed/);
    assert.match(designUI.elements["design-result"].textContent,/Retain every generated input/);checks++;
    designAuthority=true;await designUI.elements["design-preview"].onclick();
    assert.equal(designUI.elements["design-result"].textContent,"");assert.match(designUI.elements["design-status"].textContent,/could not be checked/);checks++;
    designAuthority=false;releaseDesign=true;
    const pendingDesign=designUI.elements["design-preview"].onclick();await settle();
    designUI.input("design-methodology","Changed during native readiness check.");releaseDesign();await pendingDesign;
    assert.equal(designUI.elements["design-result"].textContent,"");checks++;
    const designReload=boot(undefined,false,designServer.fetch);await settle();
    assert.equal(designReload.api.getDraft().design_notes.methodology,"Retain every generated input and the signed calculation.");
    assert.equal(designReload.elements["design-preview"].disabled,true);checks++;
    // A self-consistent but substituted protocol cannot replace the user's exact design.
    const changedProtocolFetch=async(path,options)=>{
        if(path==="/api/design/preview") {
            const body=JSON.parse(options.body),value=designReply(body);
            value.protocol_input.methodology="A substituted computation.";
            const sorted=value=>Array.isArray(value)?value.map(sorted):value&&typeof value==="object"?Object.fromEntries(Object.keys(value).sort().map(key=>[key,sorted(value[key])])):value;
            value.design_input_sha256=designHash(JSON.stringify(sorted({request:body,protocol_input:value.protocol_input})));
            return {ok:true,json:async()=>value};
        }
        return designFetch(path,options);
    };
    const changedProtocol=boot(JSON.stringify(designUI.api.draftExport()),false,changedProtocolFetch);await settle();
    await changedProtocol.elements["hypothesis-inspect"].onclick();await changedProtocol.elements["design-preview"].onclick();
    assert.equal(changedProtocol.elements["design-result"].textContent,"");
    assert.match(changedProtocol.elements["design-status"].textContent,/could not be checked/);checks++;
    const beforeUnsupported=lastDesign;
    designUI.input("design-data_scope","human_or_unsure");await designUI.elements["design-preview"].onclick();
    assert.equal(lastDesign,beforeUnsupported);
    assert.match(designUI.elements["design-status"].textContent,/separate reviewed path/);checks++;
    // Checked designs can be saved as drafts even when freeze readiness is blocked.
    const sortedProtocol=value=>Array.isArray(value)?value.map(sortedProtocol):value&&typeof value==="object"?Object.fromEntries(Object.keys(value).sort().map(key=>[key,sortedProtocol(value[key])])):value;
    function protocolFixture() {
        const base=remote(),state={writes:0,record:null,lose:false,frozen:false,hold:false,release:null};
        state.fetch=async(path,options)=>{
            if(path==="/api/hypothesis/inspect"){const value=modelReply(JSON.parse(options.body));value.canonical_write_performed=false;return {ok:true,json:async()=>value};}
            if(path==="/api/design/preview")return {ok:true,json:async()=>designReply(JSON.parse(options.body))};
            if(path==="/api/design/save" || path==="/api/design/inspect") {
                const body=JSON.parse(options.body),design=designReply(body.request);let created=false;
                assert.equal(body.design_input_sha256,design.design_input_sha256);
                if(!state.record && path.endsWith("/save")){state.writes++;created=true;state.record={...clone(design.protocol_input),protocol_id:"prt-fixture-v1",status:"draft",protocol_hash:null};}
                if(state.lose && path.endsWith("/save")){state.lose=false;throw Error("Draft saved, acknowledgement lost");}
                const record=state.record?clone(state.record):null;
                if(record && state.frozen){record.status="frozen";record.protocol_hash="f".repeat(64);}
                const value={status:record?"notebook_protocol_draft":"not_found",design,protocol:record,
                    draft_payload_sha256:record?designHash(JSON.stringify(sortedProtocol(record))):null,ledger:{valid:true},canonical_write_performed:created,analysis_performed:false,scientific_evidence_eligible:false,notice:"Draft only. No freeze or scientific approval."};
                if(state.hold){state.hold=false;await new Promise(resolve=>{state.release=resolve;});}
                return {ok:true,json:async()=>value};
            }
            return base.fetch(path,options);
        };return state;
    }
    const protocolDraft={...clone(designUI.api.draftExport()),design_notes:{...designUI.api.getDraft().design_notes,data_scope:"synthetic"}};
    async function checkedProtocolUI(state){
        const ui=boot(JSON.stringify(protocolDraft),false,state.fetch);await settle();await ui.api.flush();
        await ui.elements["hypothesis-inspect"].onclick();await ui.elements["design-preview"].onclick();return ui;
    }
    releaseDesign=null;designAuthority=false;
    const protocolState=protocolFixture(),protocolUI=await checkedProtocolUI(protocolState);
    assert.equal(protocolUI.elements["protocol-draft-save"].disabled,false);
    await protocolUI.elements["protocol-draft-save"].onclick();assert.equal(protocolState.writes,1);
    assert.match(protocolUI.elements["protocol-draft-result"].textContent,/Status: draft; no frozen protocol hash/);
    await protocolUI.elements["protocol-draft-inspect"].onclick();assert.equal(protocolState.writes,1);
    assert.match(protocolUI.elements["protocol-draft-status"].textContent,/Nothing written or frozen/);checks++;
    const lostProtocolState=protocolFixture(),lostProtocolUI=await checkedProtocolUI(lostProtocolState);
    lostProtocolState.lose=true;await lostProtocolUI.elements["protocol-draft-save"].onclick();
    assert.equal(lostProtocolUI.elements["protocol-draft-save"].disabled,true);
    await lostProtocolUI.elements["protocol-draft-save"].onclick();assert.equal(lostProtocolState.writes,1);
    await lostProtocolUI.elements["protocol-draft-inspect"].onclick();assert.equal(lostProtocolState.writes,1);
    assert.equal(lostProtocolUI.elements["protocol-draft-save"].disabled,false);checks++;
    protocolState.frozen=true;await protocolUI.elements["protocol-draft-inspect"].onclick();
    assert.equal(protocolUI.elements["protocol-draft-result"].textContent,"");
    assert.match(protocolUI.elements["protocol-draft-status"].textContent,/could not be confirmed/);checks++;
    const holdingState=protocolFixture(),holdingUI=await checkedProtocolUI(holdingState);
    holdingState.hold=true;const pendingProtocol=holdingUI.elements["protocol-draft-save"].onclick();await settle();
    await holdingUI.api.prepareDraftImport(file(imported));holdingUI.api.applyDraftImport();
    assert.equal(holdingUI.api.getDraft().statement,protocolDraft.statement);
    assert.match(holdingUI.elements["import-status"].textContent,/protocol save/);
    holdingState.release();await pendingProtocol;assert.equal(holdingState.writes,1);checks++;
    holdingUI.input("design-methodology","Changed after the checked draft.");
    assert.equal(holdingUI.elements["protocol-draft-save"].disabled,true);
    assert.equal(holdingUI.elements["protocol-draft-result"].textContent,"");checks++;
    // Draft-bound computations retain exact inputs and reject substituted or stale replies.
    async function computationFixture(){
        const state=protocolFixture(),previous=state.fetch;
        Object.assign(state,{prepared:null,outcome:null,runs:0,bad:false,holdComputation:false,releaseComputation:null,refuse:false,failVerify:false});
        const digest=value=>designHash(JSON.stringify(sortedProtocol(value)));
        state.fetch=async(path,options)=>{
            if(path.startsWith("/api/assessment/") && state.assessmentFetch)return state.assessmentFetch(path,options);
            if(path.startsWith("/api/simulation/") && state.simulationFetch)return state.simulationFetch(path,options);
            if(!path.startsWith("/api/computation/"))return previous(path,options);
            const body=options?.body?JSON.parse(options.body):{};let value;
            if(path.endsWith("/prepare")){
                const design=designReply(body.checked_draft.request);
                const bundle={version:1,checked_draft:body.checked_draft,protocol_id:state.record.protocol_id,
                    draft_payload_sha256:digest(state.record),data_scope:body.checked_draft.request.design.data_scope,
                    specification_json:body.specification_json,input_csv:body.input_csv,provenance:body.provenance,
                    method:"independent_mean_difference_ci",implementation_sha256:design.protocol_input.analysis_code_hash,
                    input_sha256:designHash(body.input_csv),specification_sha256:designHash(body.specification_json),
                    notice:"Exploratory only. Draft not frozen.",scientific_evidence_eligible:false};
                value={status:"prepared_computation",bundle_sha256:digest(bundle),bundle,attempted:false,canonical_write_performed:false,scientific_evidence_eligible:false};state.prepared=clone(value);
                if(state.bad){value.bundle.input_csv="substituted data";value.bundle_sha256=digest(value.bundle);}
                if(state.holdComputation)await new Promise(resolve=>{state.releaseComputation=resolve;});
            } else if(path.endsWith("/run")){
                state.runs++;value={...clone(state.prepared),attempted:true,notice:"Exploratory only."};
                if(state.refuse)Object.assign(value,{status:"refused_computation",failure_sha256:"f".repeat(64),failure:{status:"execution_refused",bundle_sha256:value.bundle_sha256,error:"Invalid numeric input",scientific_evidence_eligible:false}});
                else Object.assign(value,{status:"verified_computation",receipt_sha256:"a".repeat(64),method:value.bundle.method,environment:{python:"fixture",platform:"fixture"},result:{result:{mean_difference_first_minus_second:0,confidence_interval:{lower:-1,upper:1},assumptions:["Independent groups are declared, not established."]}}});
                state.outcome=clone(value);
            } else if(path.endsWith("/verify")){if(state.failVerify)throw Error("Changed artifacts");value=clone(state.outcome);}
            else value={...clone(state.prepared),attempted:state.runs>0};
            return {ok:true,json:async()=>value};
        };
        const ui=await checkedProtocolUI(state);await ui.elements["protocol-draft-save"].onclick();
        ui.input("computation-spec",'{"method":"independent_mean_difference_ci"}');ui.input("computation-data","unit,group,value\na,A,1\nb,B,1\n");ui.input("computation-provenance","Synthetic fixture, no observations.");
        return {state,ui};
    }
    const compute=await computationFixture();assert.equal(compute.ui.elements["computation-prepare"].disabled,false);
    await compute.ui.elements["computation-prepare"].onclick();assert.equal(compute.ui.elements["computation-run"].disabled,false);checks++;
    await compute.ui.elements["computation-download"].onclick();const preparedDownload=compute.ui.downloads.at(-1);assert.equal(JSON.parse(preparedDownload.content).computation.status,"prepared_computation");checks++;
    await compute.ui.elements["computation-run"].onclick();assert.equal(compute.state.runs,1);assert.match(compute.ui.elements["computation-result"].textContent,/Mean difference: 0/);
    await compute.ui.elements["computation-run"].onclick();assert.equal(compute.state.runs,1);checks++;
    await compute.ui.elements["computation-download"].onclick();const computationDownload=compute.ui.downloads.at(-1);assert.equal(JSON.parse(computationDownload.content).computation.status,"verified_computation");checks++;
    const originalQuestion=compute.ui.api.getDraft().statement;compute.ui.elements["computation-reopen"].files=[file(JSON.parse(computationDownload.content))];await compute.ui.elements["computation-reopen"].listeners.change[0]();assert.match(compute.ui.elements["computation-status"].textContent,/rechecked/);assert.equal(compute.ui.api.getDraft().statement,originalQuestion);checks++;
    compute.state.failVerify=true;const downloadsBefore=compute.ui.downloads.length;await compute.ui.elements["computation-download"].onclick();assert.equal(compute.ui.downloads.length,downloadsBefore);assert.equal(compute.ui.elements["computation-run"].disabled,true);assert.match(compute.ui.elements["computation-status"].textContent,/blocked/);checks++;
    const substituted=await computationFixture();substituted.state.bad=true;await substituted.ui.elements["computation-prepare"].onclick();assert.equal(substituted.ui.elements["computation-run"].disabled,true);checks++;
    const staleCompute=await computationFixture();staleCompute.state.holdComputation=true;const pendingCompute=staleCompute.ui.elements["computation-prepare"].onclick();await settle();staleCompute.ui.input("computation-data","Edited while preparing");staleCompute.state.releaseComputation();await pendingCompute;assert.equal(staleCompute.ui.elements["computation-run"].disabled,true);checks++;
    const refusedCompute=await computationFixture();refusedCompute.state.refuse=true;await refusedCompute.ui.elements["computation-prepare"].onclick();await refusedCompute.ui.elements["computation-run"].onclick();assert.match(refusedCompute.ui.elements["computation-result"].textContent,/Execution refused: Invalid numeric input/);await refusedCompute.ui.elements["computation-download"].onclick();assert.equal(JSON.parse(refusedCompute.ui.downloads.at(-1).content).computation.status,"refused_computation");checks++;
    // Portable files are exact text bytes: stage locally, explicitly retain, then replay.
    const portableCompute=await computationFixture();await portableCompute.ui.elements["computation-prepare"].onclick();await portableCompute.ui.elements["computation-run"].onclick();
    const portableSource={version:1,computation:clone(portableCompute.state.outcome),context:{protocol:{status:"draft"}},source_outcome:{},scope:"Hash consistency only; source unauthenticated; no scientific evidence.",scientific_evidence_eligible:false};
    const portableText=JSON.stringify(portableSource),portableEnvelope={format:"faraday-portable-computation-v1",archive_json:portableText,archive_sha256:designHash(portableText)};
    const portablePrior=portableCompute.state.fetch;let portableWrites=0,portableRuns=0,portableReplay=null,portableFailVerify=false;
    const portableRetained=()=>({status:"retained_portable_computation",archive_sha256:portableEnvelope.archive_sha256,envelope:clone(portableEnvelope),replay_attempted:portableRuns>0,canonical_write_performed:false,scientific_evidence_eligible:false,scope:portableSource.scope});
    portableCompute.state.fetch=async(path,options)=>{
        if(path==="/api/computation/export")return {ok:true,json:async()=>clone(portableEnvelope)};
        if(path.startsWith("/api/portable-computation/")){
            let value=portableRetained();
            if(path.endsWith("/restore")){portableWrites++;assert.deepEqual(JSON.parse(options.body),portableEnvelope);}
            if(path.endsWith("/replay")){portableRuns++;value={...portableRetained(),status:"verified_portable_replay",receipt_sha256:"b".repeat(64),result:clone(portableSource.computation.result),comparison:"Byte-identical result replay."};portableReplay=clone(value);}
            if(path.endsWith("/verify")){if(portableFailVerify)throw Error("Changed local output");value=clone(portableReplay);}
            return {ok:true,json:async()=>value};
        }
        return portablePrior(path,options);
    };
    // The harness closes over the original fetch function; delegate its new portable routes.
    const portableUI=await checkedProtocolUI({fetch:(path,options)=>portableCompute.state.fetch(path,options)});
    await portableUI.elements["protocol-draft-inspect"].onclick();portableUI.input("computation-spec",'{"method":"independent_mean_difference_ci"}');portableUI.input("computation-data","unit,group,value\na,A,1\nb,B,1\n");portableUI.input("computation-provenance","Synthetic fixture, no observations.");
    await portableUI.elements["computation-prepare"].onclick();await portableUI.elements["computation-run"].onclick();
    await portableUI.elements["computation-portable-download"].onclick();assert.equal(JSON.parse(portableUI.downloads.at(-1).content).archive_json,portableText);checks++;
    const portableQuestion=portableUI.api.getDraft().statement;
    portableUI.elements["portable-file"].files=[file(portableEnvelope)];await portableUI.elements["portable-file"].listeners.change[0]();
    assert.equal(portableWrites,0);assert.equal(portableUI.elements["portable-restore"].disabled,false);assert.match(portableUI.elements["portable-result"].textContent,/STAGED FILE/);checks++;
    portableUI.elements["portable-cancel"].onclick();assert.equal(portableWrites,0);assert.equal(portableUI.elements["portable-restore"].disabled,true);checks++;
    await portableUI.elements["portable-file"].listeners.change[0]();await portableUI.elements["portable-restore"].onclick();assert.equal(portableWrites,1);assert.equal(portableUI.api.getDraft().statement,portableQuestion);assert.equal(portableUI.elements["portable-replay"].disabled,false);checks++;
    await portableUI.elements["portable-replay"].onclick();assert.equal(portableRuns,1);assert.match(portableUI.elements["portable-result"].textContent,/Byte-identical result replay/);await portableUI.elements["portable-replay"].onclick();assert.equal(portableRuns,1);checks++;
    await portableUI.elements["portable-report"].onclick();assert.equal(JSON.parse(portableUI.downloads.at(-1).content).format,"faraday-portable-replay-report-v1");checks++;
    // Reopening an archive after reload must recover its pinned replay without executing again.
    const replayStorageKey=[...portableUI.stored.keys()].find(key=>key.includes(":portable-replay:"));
    assert.ok(replayStorageKey,"Successful replay must retain its exact recovery reference.");
    async function reopenedPortableUI(referenceOverride=undefined,omitReference=false){
        const ui=boot(JSON.stringify(portableUI.api.draftExport()),false,(path,options)=>portableCompute.state.fetch(path,options));await settle();
        for(const [key,value] of portableUI.stored)ui.stored.set(key,value);
        if(omitReference)ui.stored.delete(replayStorageKey);else if(referenceOverride!==undefined)ui.stored.set(replayStorageKey,referenceOverride);
        ui.elements["portable-file"].files=[file(portableEnvelope)];await ui.elements["portable-file"].listeners.change[0]();await ui.elements["portable-restore"].onclick();return ui;
    }
    const reopenedPortable=await reopenedPortableUI();assert.equal(portableRuns,1);assert.equal(reopenedPortable.elements["portable-report"].disabled,false);assert.equal(reopenedPortable.elements["portable-replay"].disabled,true);assert.match(reopenedPortable.elements["portable-result"].textContent,/LOCAL REPLAY/);assert.equal(reopenedPortable.api.getDraft().statement,portableQuestion);await reopenedPortable.elements["portable-report"].onclick();assert.equal(JSON.parse(reopenedPortable.downloads.at(-1).content).format,"faraday-portable-replay-report-v1");checks++;
    portableFailVerify=true;const brokenReopen=await reopenedPortableUI();assert.equal(brokenReopen.elements["portable-report"].disabled,true);assert.equal(brokenReopen.elements["portable-replay"].disabled,true);assert.match(brokenReopen.elements["portable-result"].textContent,/ARCHIVED SOURCE OUTCOME/);assert.doesNotMatch(brokenReopen.elements["portable-result"].textContent,/LOCAL REPLAY/);assert.equal(portableRuns,1);portableFailVerify=false;checks++;
    for(const ref of ["not JSON",JSON.stringify({archive_sha256:"f".repeat(64),receipt_sha256:"b".repeat(64)}),JSON.stringify({archive_sha256:portableEnvelope.archive_sha256,receipt_sha256:"c".repeat(64)})]){
        const badReopen=await reopenedPortableUI(ref);assert.equal(badReopen.elements["portable-report"].disabled,true);assert.equal(badReopen.elements["portable-replay"].disabled,true);assert.equal(portableRuns,1);checks++;
    }
    const missingReopen=await reopenedPortableUI(undefined,true);assert.equal(missingReopen.elements["portable-report"].disabled,true);assert.equal(missingReopen.elements["portable-replay"].disabled,true);assert.equal(portableRuns,1);checks++;
    portableRuns=0;const missingAttempt=await reopenedPortableUI();assert.equal(missingAttempt.elements["portable-report"].disabled,true);assert.equal(missingAttempt.elements["portable-replay"].disabled,true);await missingAttempt.elements["portable-replay"].onclick();assert.equal(portableRuns,0);portableRuns=1;checks++;
    const successReplay=clone(portableReplay);portableReplay={...clone(successReplay),status:"verified_portable_refusal",refusal_sha256:"d".repeat(64),refusal:{error:"Invalid example data."},comparison:"No numerical result; archived source preserved."};delete portableReplay.result;delete portableReplay.receipt_sha256;
    const refusalReopen=await reopenedPortableUI(JSON.stringify({archive_sha256:portableEnvelope.archive_sha256,refusal_sha256:"d".repeat(64)}));assert.equal(refusalReopen.elements["portable-report"].disabled,false);assert.match(refusalReopen.elements["portable-result"].textContent,/No numerical result/);assert.equal(portableRuns,1);portableReplay=successReplay;checks++;
    portableRuns=0;const quotaPortable=boot(undefined,true,(path,options)=>portableCompute.state.fetch(path,options));await settle();quotaPortable.elements["portable-file"].files=[file(portableEnvelope)];await quotaPortable.elements["portable-file"].listeners.change[0]();await quotaPortable.elements["portable-restore"].onclick();await quotaPortable.elements["portable-replay"].onclick();assert.equal(portableRuns,1);assert.equal(quotaPortable.elements["portable-report"].disabled,false);assert.match(quotaPortable.elements["portable-status"].textContent,/could not keep its recovery reference/);checks++;

    const portableCount=portableUI.downloads.length;portableFailVerify=true;await portableUI.elements["portable-report"].onclick();assert.equal(portableUI.downloads.length,portableCount);assert.equal(portableUI.elements["portable-report"].disabled,true);checks++;
    const writesBeforeChangedPortable=portableWrites;const changedPortable=clone(portableEnvelope);changedPortable.archive_json+=" ";portableUI.elements["portable-file"].files=[file(changedPortable)];await portableUI.elements["portable-file"].listeners.change[0]();assert.equal(portableWrites,writesBeforeChangedPortable);assert.equal(portableUI.elements["portable-restore"].disabled,true);checks++;
    // A working assessment binds the current result, preserves earlier notes, and stages a question without replacing the notebook.
    const assessmentCompute=await computationFixture();await assessmentCompute.ui.elements["computation-prepare"].onclick();await assessmentCompute.ui.elements["computation-run"].onclick();
    const assessmentRecords=new Map();let assessmentWrites=0,assessmentBroken=false;
    assessmentCompute.state.assessmentFetch=async(path,options)=>{
        const body=JSON.parse(options.body);if(assessmentBroken)throw Error("Changed source artifact");let value;
        if(path.endsWith("/save")){
            const snapshot={source:body.source,bundle:clone(assessmentCompute.state.outcome.bundle),outcome:{status:"verified_computation",result:clone(assessmentCompute.state.outcome.result)},scientific_evidence_eligible:false,notice:"Unreviewed working assessment only."};
            const text=JSON.stringify(sortedProtocol(snapshot)),record={version:1,source:body.source,source_snapshot_json:text,source_snapshot_sha256:designHash(text),notes:body.notes,assessment_status:"unreviewed_working_notes",followup_status:"unreviewed_user_proposal",action_recommendation_created:false,scientific_evidence_eligible:false,notice:"Unreviewed working assessment only."};
            const digest=designHash(JSON.stringify(sortedProtocol(record)));
            value={status:"verified_working_assessment",assessment_sha256:digest,record,canonical_write_performed:false,scientific_evidence_eligible:false,action_recommendation_created:false};
            if(!assessmentRecords.has(digest))assessmentWrites++;assessmentRecords.set(digest,clone(value));
        } else value=clone(assessmentRecords.get(body.assessment_sha256));
        return {ok:true,json:async()=>value};
    };
    const assessmentUI=await checkedProtocolUI({fetch:(path,options)=>assessmentCompute.state.fetch(path,options)});await assessmentUI.elements["protocol-draft-inspect"].onclick();
    assessmentUI.input("computation-spec",'{"method":"independent_mean_difference_ci"}');assessmentUI.input("computation-data","unit,group,value\na,A,1\nb,B,1\n");assessmentUI.input("computation-provenance","Synthetic fixture, no observations.");await assessmentUI.elements["computation-prepare"].onclick();await assessmentUI.elements["computation-run"].onclick();
    assessmentUI.elements["computation-assess"].onclick();assert.equal(assessmentUI.elements["assessment-save"].disabled,false);await assessmentUI.elements["assessment-save"].onclick();assert.equal(assessmentWrites,0);assert.match(assessmentUI.elements["assessment-status"].textContent,/Complete these fields/);checks++;
    const assessmentNotes={interpretation:"The retained point estimate is zero.",uncertainty:"The interval spans both directions under declared assumptions.",alternatives:"Input selection and dependence remain alternatives.",limitations:"Synthetic software fixture only.",followup_question:"How does reversing group order change this software output?",decision_change:"A retained result differing from the expected sign would change the interpretation."};
    for(const [field,text] of Object.entries(assessmentNotes))assessmentUI.input("assessment-"+field,text);
    const assessmentQuestion=assessmentUI.api.getDraft().statement;await assessmentUI.elements["assessment-save"].onclick();assert.equal(assessmentWrites,1);assert.match(assessmentUI.elements["assessment-result"].textContent,/WORKING ASSESSMENT/);assert.equal(assessmentUI.api.getDraft().statement,assessmentQuestion);checks++;
    await assessmentUI.elements["assessment-save"].onclick();assert.equal(assessmentWrites,1);await assessmentUI.elements["assessment-download"].onclick();const assessmentDownload=assessmentUI.downloads.at(-1);assert.equal(JSON.parse(assessmentDownload.content).format,"faraday-working-assessment-v1");checks++;
    await assessmentUI.elements["assessment-next"].onclick();assert.equal(assessmentUI.api.getDraft().statement,assessmentQuestion);assert.equal(assessmentUI.elements["import-apply"].hidden,false);assert.match(assessmentUI.elements["assessment-status"].textContent,/staged for review/);checks++;
    assessmentUI.api.applyDraftImport();assert.equal(assessmentUI.api.getDraft().statement,assessmentNotes.followup_question);assert.equal(assessmentUI.api.getDraft().inquiry_id,null);assert.equal(assessmentUI.api.getDraft().hypothesis_notes.statement,"");assert.match(assessmentUI.api.getDraft().recording_notes,/working assessment/);assert.equal(assessmentUI.api.getDraft().planning.decision_change_criteria,assessmentNotes.decision_change);checks++;
    assessmentUI.input("assessment-interpretation","A revised assessment, retained separately.");assert.equal(assessmentUI.elements["assessment-download"].disabled,true);await assessmentUI.elements["assessment-save"].onclick();assert.equal(assessmentWrites,2);checks++;
    assessmentUI.elements["assessment-file"].files=[file(JSON.parse(assessmentDownload.content))];await assessmentUI.elements["assessment-file"].listeners.change[0]();assert.equal(assessmentUI.document.getElementById("assessment-interpretation").value,assessmentNotes.interpretation);assert.equal(assessmentUI.api.getDraft().statement,assessmentNotes.followup_question);checks++;
    assessmentBroken=true;const assessmentBefore=assessmentUI.downloads.length;await assessmentUI.elements["assessment-download"].onclick();assert.equal(assessmentUI.downloads.length,assessmentBefore);assert.equal(assessmentUI.elements["assessment-next"].disabled,true);assert.match(assessmentUI.elements["assessment-status"].textContent,/blocked/);checks++;
    // Retained synthetic inputs enter the user's design without hand-authored JSON or a silent scope change.
    async function handoffFixture(){
        const value=await computationFixture(),plan={...clone(prepared),recipe:{...clone(prepared.recipe),data_classification:"synthetic"}};
        Object.assign(value.state,{handoffPlan:plan,handoffBad:false,handoffHold:false,handoffRelease:null,handoffReads:0});
        value.state.simulationFetch=async(path,options)=>{
            if(path.endsWith("/prepare"))return {ok:true,json:async()=>clone(plan)};
            if(path.endsWith("/design")){
                value.state.handoffReads++;const result={...clone(plan),method_identity:{method:"independent_mean_difference_ci",implementation_sha256:"d".repeat(64)}};
                if(value.state.handoffBad)result.design.input_csv+="changed";
                if(value.state.handoffHold)await new Promise(resolve=>{value.state.handoffRelease=resolve;});
                return {ok:true,json:async()=>result};
            }
            throw Error("Handoff must not run a simulation");
        };
        value.ui.elements["simulation-case"].value="positive";await value.ui.elements["simulation-prepare"].onclick();return value;
    }
    const handoff=await handoffFixture(),handoffQuestion=handoff.ui.api.getDraft().statement,handoffPrevious=handoff.ui.elements["computation-data"].value;
    assert.equal(handoff.ui.elements["simulation-to-design"].disabled,false);await handoff.ui.elements["simulation-to-design"].onclick();
    assert.equal(handoff.ui.elements["computation-data"].value,designCsv);assert.equal(handoff.ui.elements["computation-spec"].value,designSpec);assert.equal(handoff.ui.api.getDraft().design_notes.analysis_code_hash,"d".repeat(64));
    assert.equal(handoff.ui.api.getDraft().statement,handoffQuestion);assert.equal(handoff.state.writes,1);assert.equal(handoff.state.runs,0);assert.equal(handoff.ui.elements["computation-prepare"].disabled,true);assert.match(handoff.ui.elements["simulation-to-design-status"].textContent,/Nothing was frozen or executed/);checks++;
    assert.equal(JSON.parse(handoff.ui.downloads.at(-1).content).input_csv,handoffPrevious);assert.match(handoff.ui.elements["computation-provenance"].value,/Made-up positive software fixture/);checks++;
    const realScope=await handoffFixture();realScope.ui.input("design-data_scope","existing_nonhuman");const realBefore=realScope.ui.elements["computation-data"].value;await realScope.ui.elements["simulation-to-design"].onclick();assert.equal(realScope.state.handoffReads,0);assert.equal(realScope.ui.api.getDraft().design_notes.data_scope,"existing_nonhuman");assert.equal(realScope.ui.elements["computation-data"].value,realBefore);checks++;
    const badHandoff=await handoffFixture();badHandoff.state.handoffBad=true;const badBefore=badHandoff.ui.elements["computation-data"].value;await badHandoff.ui.elements["simulation-to-design"].onclick();assert.equal(badHandoff.ui.elements["computation-data"].value,badBefore);assert.match(badHandoff.ui.elements["simulation-to-design-status"].textContent,/could not be confirmed/);checks++;
    const staleHandoff=await handoffFixture();staleHandoff.state.handoffHold=true;const staleBefore=staleHandoff.ui.elements["computation-data"].value,pendingHandoff=staleHandoff.ui.elements["simulation-to-design"].onclick();await settle();staleHandoff.ui.input("reflection","Edited during inspection");staleHandoff.state.handoffRelease();await pendingHandoff;assert.equal(staleHandoff.ui.elements["computation-data"].value,staleBefore);checks++;
    const readable=handoff.ui.api.readableWorkingOutcome({specification_json:designSpec},{result:{groups:["sun","shade"],mean_difference_first_minus_second:-4,confidence_interval:{lower:-6,upper:-2,level:0.95},n_by_group:{sun:3,shade:4},mean_by_group:{sun:19,shade:23},missing_rows:1,bootstrap_resamples:1000,seed:17,exclusion_report:{input_records:8,included_records:7,excluded_records:[{}],excluded_by_group:{sun:1,shade:0},excluded_without_registered_group:0},assumptions:["Independent units are assumed."],warnings:["Conditional software interval."]}},null);
    assert.match(readable,/mean sun minus mean shade/);assert.match(readable,/Mean difference: -4/);assert.match(readable,/Bootstrap confidence interval: \[-6, -2\], level 0.95/);assert.match(readable,/sun: 3 included units/);assert.match(readable,/Excluded in sun: 1/);assert.match(readable,/Assumptions \(declared, not established\)/);assert.match(readable,/Warning: Conditional/);assert.doesNotMatch(readable,/\"mean_difference_first_minus_second\"/);checks++;
    // Primary activity report retains the learner's words, without a technical appendix.
    const activityUI=boot(undefined,false,labFetch);await settle();activityUI.input("statement","Which example has warmer sunny readings?");activityUI.input("prediction","I think sunny readings will be warmer.");activityUI.input("reflection","Other explanations still matter.");activityUI.elements["simulation-case"].value="positive";
    await activityUI.elements["simulation-prepare"].onclick();await activityUI.elements["simulation-run"].onclick();await activityUI.elements["simulation-download"].onclick();
    const activityReport=activityUI.downloads.at(-1).content;for(const text of ["MY SCIENCE NOTES","Which example has warmer sunny readings?","I think sunny readings will be warmer.","Other explanations still matter.","Example readings","These readings were made up for practice"])assert.ok(activityReport.includes(text));assert.doesNotMatch(activityReport,/SHA-256|EXACT ANALYSIS|research analysis run|\{"method"/);assert.match(activityUI.elements["simulation-result"].textContent,/sunny readings average 4.00/);checks++;
    let activityRelease=null,activityHold=false;
    const slowActivity=boot(undefined,false,async(path,options)=>{if(activityHold && path==="/api/simulation/verify")await new Promise(resolve=>{activityRelease=resolve;});return labFetch(path,options);});await settle();slowActivity.elements["simulation-case"].value="positive";await slowActivity.elements["simulation-prepare"].onclick();await slowActivity.elements["simulation-run"].onclick();activityHold=true;
    const activityPending=slowActivity.elements["simulation-download"].onclick();await settle();slowActivity.input("reflection","New thought while the file was being checked.");activityRelease();await activityPending;
    assert.equal(slowActivity.downloads.length,0);assert.equal(slowActivity.api.getDraft().reflection,"New thought while the file was being checked.");assert.match(slowActivity.elements["simulation-status"].textContent,/We could not check these notes/);checks++;
    // Question-first canvas notes survive the actual client save/recovery transport.
    const workspaceServer=remote(),workspaceUI=boot(undefined,false,workspaceServer.fetch);await settle();
    workspaceUI.input("statement","Why does my route take longer on some days?");workspaceUI.elements["workspace-start"].onclick();workspaceUI.elements["route-track"].onclick();workspaceUI.input("workspace-time","Week by week");workspaceUI.input("workspace-outcome","Travel time in minutes");workspaceUI.elements["route-sources"].onclick();workspaceUI.input("workspace-source_unclear","A timetable is not an observed journey.");await workspaceUI.api.flush();
    assert.equal(workspaceUI.api.sync().blocked,false);assert.equal(workspaceServer.draft.workspace_notes.source_unclear,"A timetable is not an observed journey.");
    const workspaceReopen=boot(undefined,false,workspaceServer.fetch);await settle();
    assert.equal(workspaceReopen.elements["workspace-question-title"].textContent,workspaceUI.api.getDraft().statement);assert.equal(workspaceReopen.elements["canvas-sources"].hidden,false);assert.equal(workspaceReopen.elements["workspace-time"].value,"Week by week");checks++;
    // Choosing an optional example does not replace the current question or notes before confirmation.
    const priorWorkspace=clone(workspaceReopen.api.getDraft());await workspaceReopen.elements["example-model"].onclick();
    assert.deepEqual(workspaceReopen.api.getDraft(),priorWorkspace);assert.equal(workspaceReopen.elements["import-apply"].hidden,false);
    workspaceReopen.api.applyDraftImport();assert.equal(workspaceReopen.api.getDraft().statement,"How does a pendulum’s length change its swing?");assert.equal(workspaceReopen.api.getDraft().workspace_notes.approach,"model");
    assert.ok([...workspaceReopen.stored.entries()].some(([key,value])=>key.includes(":before-import:") && JSON.parse(value).statement===priorWorkspace.statement && JSON.parse(value).workspace_notes.source_unclear===priorWorkspace.workspace_notes.source_unclear));checks++;
    // A later import owns the shared confirmation; an older example selection cannot hijack it.
    const raceWorkspace=boot(undefined,false,remote().fetch);await settle();raceWorkspace.input("statement","Keep this question.");
    const pendingWorkspaceExample=raceWorkspace.elements["example-buses"].onclick();
    const chosenDraft={...raceWorkspace.api.draftExport(),statement:"A different chosen draft"};
    await raceWorkspace.api.prepareDraftImport(file(chosenDraft));await pendingWorkspaceExample;
    assert.equal(raceWorkspace.elements["import-apply"].textContent,"Keep current copy and restore selected draft");raceWorkspace.api.applyDraftImport();assert.equal(raceWorkspace.api.getDraft().statement,"A different chosen draft");checks++;
    console.log(JSON.stringify({status:"passed",asynchronous_checks:checks,rendered_browser:false}));
})().catch(error=>{console.error(error);process.exitCode=1;});
