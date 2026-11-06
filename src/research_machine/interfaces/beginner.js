"use strict";
// Browser drafts are untrusted, non-evidentiary working notes.
const key = "faraday-shade-rehearsal-v1:__DRAFT_KEY__";
const practiceKey = key + ":practice-comparison";
let practicePlan = null;
let practiceScope = null;
let practiceBusy = false;
let practiceReference = null;
try {
    practiceReference = JSON.parse(localStorage.getItem(practiceKey));
} catch (error) {
    // A missing or unreadable reference does not prevent a fresh comparison.
}

const $ = id => document.getElementById(id);
const textFields = ["statement", "prediction", "reflection", "recording_notes"];
const clone = value => JSON.parse(JSON.stringify(value));
const freshReviewContext = () => ({reviewer_kind:"unassigned",notes:"",identity_status:"unverified",authority:"review_only"});
const planningKeys = ["title","population","unit_of_observation","outcome","comparison","time_window","decision","minimum_evidence","decision_owner","decision_change_criteria","available_data_sources","ethical_constraints"];
let planningFields = [];
const hypothesisLabels={statement:"Hypothesis statement",observable_prediction:"Observable prediction",null_model:"Null model",competing_models:"Competing explanations (one per line)",falsification_conditions:"Observations that would count against it (one per line)",scope:"Hypothesis scope and limits",lineage:"Earlier hypothesis references revised (optional, one per line)"};
const freshHypothesisNotes=()=>Object.fromEntries(Object.keys(hypothesisLabels).map(field=>[field,""]));
let hypothesisBusy=false,hypothesisUncertain=false,checkedHypothesis=null,designBusy=false,checkedDesign=null,protocolBusy=false,protocolUncertain=false;
let checkedProtocol=null,computation=null,computationBusy=false,computationAttempted=false,computationRevision=0;
let simulationPlan=null,simulationBusy=false,simulationHandoffBusy=false;
let portableStaged=null,portableRetained=null,portableOutcome=null,portableBusy=false,portableReplayUncertain=false;
let assessmentSource=null,assessmentSaved=null,assessmentBusy=false,assessmentRevision=0;
const assessmentLabels={interpretation:"What do the observed numbers or refusal say?",uncertainty:"What uncertainty and assumptions limit the interpretation?",alternatives:"What alternative explanations remain?",limitations:"What is outside this result’s scope?",followup_question:"What question would you investigate next?",decision_change:"What observation would change your interpretation or next decision?"};
const designLabels={data_scope:"Declared data scope",safety_constraints:"Safety, privacy and stop constraints (one per line)",methodology:"Computation methodology",inputs_required:"Required data or inputs (one per line)",sample_size_or_stopping_rule:"Sample size or stopping rule",quality_requirements:"Integrity gate identifiers (one per line)",controls:"Control descriptions (one per line)",missing_data_policy:"Missing-data plan",success_conditions:"Support or success conditions (one per line)",failure_conditions:"Falsification or failure conditions (one per line)",expected_outputs:"Expected outputs (one per line)",environment_requirements:"Environment requirements (one per line)",analysis_code_hash:"Analysis implementation SHA-256 (if known)"};
const freshDesignNotes=()=>Object.fromEntries(Object.keys(designLabels).map(field=>[field,""]));
const workspaceFields=["comparison_a","comparison_b","model_input","model_output","model_relation","source_supports","source_challenges","source_unclear"];
const freshWorkspaceNotes=()=>({version:1,open:false,approach:"",...Object.fromEntries(workspaceFields.map(field=>[field,""]))});
function restoreWorkspaceNotes(value){
    if(!value || typeof value!=="object" || Array.isArray(value) || Object.keys(value).sort().join(",")!==["version","open","approach",...workspaceFields].sort().join(",") || value.version!==1 || typeof value.open!=="boolean" || !["","compare","track","model","sources"].includes(value.approach) || workspaceFields.some(field=>typeof value[field]!=="string" || value[field].length>2000))throw Error("Invalid workspace notes.");
    return clone(value);
}
const freshDraft = () => ({
    statement: "", prediction: "", reflection: "", recording_notes: "",
    rows: [{id: "pair-1", shade: "", sun: ""}], history: [],
    inquiry_id: null, saved_statement: null, save_state: "draft", review_context: freshReviewContext(), planning: {}, hypothesis_notes:freshHypothesisNotes(), design_notes:freshDesignNotes(),workspace_notes:freshWorkspaceNotes()
});
let draft = freshDraft(), revision = 0, previewSerial = 0, inspectedInquiry = null;
let recoveryBytes = null, recoveryLocked = false, editingSnapshot = null;
let bootIssue = null;
let hadLocalDraft = false, inquirySaving = false;
let workspaceEditingLocked=false;

function restoreSnapshot(value) {
    if (!value || typeof value !== "object" || Array.isArray(value)) throw Error("Invalid draft.");
    const out = {};
    if(value.workspace_notes!==undefined)out.workspace_notes=restoreWorkspaceNotes(value.workspace_notes);
    const planning=value.planning===undefined ? {} : value.planning;
    if (!planning || typeof planning!=="object" || Array.isArray(planning) ||
        Object.entries(planning).some(([field,text])=>!planningKeys.includes(field) || typeof text!=="string" || text.length>2000)) throw Error("Invalid planning draft.");
    out.planning=clone(planning);
    const hypothesis=value.hypothesis_notes===undefined?freshHypothesisNotes():value.hypothesis_notes;
    if(!hypothesis || typeof hypothesis!=="object" || Array.isArray(hypothesis) || Object.keys(hypothesis).sort().join(",")!==Object.keys(hypothesisLabels).sort().join(",") || Object.values(hypothesis).some(text=>typeof text!=="string" || text.length>2000))throw Error("Invalid hypothesis notes.");
    out.hypothesis_notes=clone(hypothesis);
    const design=value.design_notes===undefined?freshDesignNotes():value.design_notes;
    if(!design || typeof design!=="object" || Array.isArray(design) || Object.keys(design).sort().join(",")!==Object.keys(designLabels).sort().join(",") || Object.values(design).some(text=>typeof text!=="string" || text.length>2000))throw Error("Invalid design notes.");
    out.design_notes=clone(design);
    const context = value.review_context === undefined ? freshReviewContext() : value.review_context;
    if (!context || typeof context !== "object" || Array.isArray(context) ||
        Object.keys(context).sort().join(",") !== "authority,identity_status,notes,reviewer_kind" ||
        !["unassigned","human","ai","hybrid"].includes(context.reviewer_kind) ||
        typeof context.notes !== "string" || context.notes.length > 10000 ||
        context.identity_status !== "unverified" || context.authority !== "review_only") throw Error("Invalid review context.");
    out.review_context = clone(context);
    for (const field of textFields) {
        if (field === "recording_notes" && value[field] === undefined) {out[field]="";continue;}
        if (typeof value[field] !== "string" || value[field].length > (field === "statement" ? 2000 : 10000)) throw Error("Invalid draft text.");
        out[field] = value[field];
    }
    if (!Array.isArray(value.rows) || !value.rows.length || value.rows.length > 200) throw Error("Invalid draft rows.");
    out.rows = value.rows.map(row => {
        if (!row || typeof row !== "object" || typeof row.id !== "string" || row.id.length > 100) throw Error("Invalid draft pair.");
        const result = {id: row.id};
        for (const field of ["shade", "sun"]) {
            const reading = row[field];
            if (reading === null) result[field] = "";
            else if (typeof reading === "number" && Number.isFinite(reading)) result[field] = String(reading);
            else if (typeof reading === "string" && reading.length <= 100) result[field] = reading;
            else throw Error("Invalid saved reading.");
        }
        return result;
    });
    return out;
}
function restoreDraft(value) {
    const result = restoreSnapshot(value);
    if (!Array.isArray(value.history)) throw Error("Invalid draft history.");
    result.history = value.history.map(restoreSnapshot);
    if (value.inquiry_id !== null &&
        (typeof value.inquiry_id !== "string" || !/^[a-z0-9][a-z0-9-]{0,95}$/.test(value.inquiry_id))) throw Error("Invalid inquiry reference.");
    result.inquiry_id = value.inquiry_id;
    if (value.saved_statement !== undefined && value.saved_statement !== null &&
        (typeof value.saved_statement !== "string" || value.saved_statement.length > 2000)) throw Error("Invalid saved question.");
    result.saved_statement = value.saved_statement || null;
    result.save_state = value.save_state === undefined
        ? (result.inquiry_id ? "saved" : "draft") : value.save_state;
    if (!["draft", "pending", "saved"].includes(result.save_state) ||
        (result.save_state === "saved" && !result.inquiry_id) ||
        (result.save_state === "draft" && result.inquiry_id)) throw Error("Invalid save state.");
    // Ignore caller-supplied review status, evidence flags and other unknown fields.
    return result;
}
function snapshot() {
    return {statement: draft.statement, prediction: draft.prediction,
            reflection: draft.reflection, recording_notes: draft.recording_notes, rows: clone(draft.rows), review_context:clone(draft.review_context), planning:clone(draft.planning), hypothesis_notes:clone(draft.hypothesis_notes),design_notes:clone(draft.design_notes),...(draft.workspace_notes?{workspace_notes:clone(draft.workspace_notes)}:{})};
}
function clearErrors() {
    $("error").replaceChildren();
    $("error").hidden = true;
    for (const input of document.querySelectorAll('[aria-invalid="true"]')) {
        input.removeAttribute("aria-invalid");
        const help = input.id.startsWith("pair-") ? "measurement-help" : "question-help";
        input.setAttribute("aria-describedby", help);
    }
}
function showErrors(items) {
    clearErrors();
    const title = document.createElement("p");
    title.textContent = "Please check the following:";
    $("error").append(title);
    const list = document.createElement("ul");
    for (const item of items) {
        const li = document.createElement("li");
        if (item.field && $(item.field)) {
            const input = $(item.field);
            input.setAttribute("aria-invalid", "true");
            input.setAttribute("aria-describedby", (item.field.startsWith("pair-") ? "measurement-help" : "question-help") + " error");
            const link = document.createElement("a");
            link.href = "#" + item.field;
            link.textContent = item.message;
            link.addEventListener("click", () => input.focus());
            li.append(link);
        } else li.textContent = item.message;
        list.append(li);
    }
    $("error").append(list);
    $("error").hidden = false;
    $("error").focus();
}
function announce(id, message) {
    if ($(id).textContent !== message) $(id).textContent = message;
}
function persist() {
    hadLocalDraft = true;
    renderWorkspace();
    queueNorwaySave();
    if (recoveryLocked) {
        announce("draft-status", "Session-only draft. The unreadable saved draft is unchanged. Download it and your current draft before leaving.");
        return false;
    }
    try {
        localStorage.setItem(key, JSON.stringify(draft));
        announce("draft-status", "Your notes are saved in this browser. Still saving them in Faraday…");
        return true;
    } catch (_) {
        announce("draft-status", "Browser saving failed. Your latest edits are only in this tab. Download the current draft before leaving.");
        return false;
    }
}
function invalidatePreview() {
    revision += 1;
    inspectedInquiry = null; $("link-inquiry").hidden = true;
    $("hypothesis-saved").replaceChildren();
    if(!currentCheckedHypothesis())checkedHypothesis=null;
    checkedDesign=null;checkedProtocol=null;protocolUncertain=false;invalidateComputation();$("protocol-draft-result").replaceChildren();
    announce("protocol-draft-status","Working notes changed. Check the exact design before saving or finding a protocol draft; earlier drafts are unchanged.");
    $("design-result").replaceChildren();announce("design-status","Working notes changed. Recheck readiness; no protocol was created or frozen.");designControls();
    announce("hypothesis-status","Working notes changed. Submit a complete proposal or check its saved version; no hypothesis was activated.");
    invalidateHistory();
    announce("planning-status","Draft changed. Preview the planning questions again.");
    $("planning-unresolved").replaceChildren(); $("planning-models").replaceChildren();
    announce("report-status","Draft changed. Download a new report to include these edits.");
    announce("summary", "Draft changed. Recalculate the rehearsal preview.");
    $("differences").replaceChildren();
}
function rememberBeforeEdit() {
    if (editingSnapshot === null) {
        editingSnapshot = snapshot();
        draft.history.push(clone(editingSnapshot));
    }
}
function recordInput(update) {
    rememberBeforeEdit();
    update();
    invalidatePreview();
    persist();
}
function finishEdit() { editingSnapshot = null; }
function questionErrors() {
    const value = draft.statement;
    return !value.trim() || value !== value.trim() || value.length > 2000
        ? [{field: "statement", message: "Write 1–2000 characters, without spaces before or after your question."}] : [];
}
function measurementPayload() {
    const errors = [], seen = new Set();
    const rows = draft.rows.map((row, index) => {
        if (!row.id.trim() || row.id !== row.id.trim() || seen.has(row.id)) {
            errors.push({field: "pair-" + index + "-id", message: "Pair " + (index + 1) + " needs a unique label without surrounding spaces."});
        }
        seen.add(row.id);
        const out = {id: row.id};
        for (const field of ["shade", "sun"]) {
            const raw = row[field], numeric = Number(raw);
            const blank = raw === "";
            if (!blank && (!/^[+-]?(?:\d+\.?\d*|\.\d+)(?:e[+-]?\d+)?$/i.test(raw) ||
                !Number.isFinite(numeric) || numeric < -273.15 || numeric > 1000)) {
                errors.push({field: "pair-" + index + "-" + field,
                    message: "Pair " + (index + 1) + " " + field + ": enter a Celsius number with a decimal point, or leave it blank. The rehearsal sanity bounds are −273.15 to 1000 °C; these do not validate an instrument."});
            }
            out[field] = blank ? null : numeric;
        }
        return out;
    });
    return {errors, payload: {mode: "rehearsal", unit: "degC", rows}};
}
function savedStatus() {
    renderWorkspace();
    hypothesisControls();
    const uncertain = draft.save_state === "pending";
    $("save").disabled = Boolean(draft.inquiry_id) || uncertain;
    $("statement").readOnly = inquirySaving || Boolean(draft.inquiry_id && draft.saved_statement);
    $("question-save-message").textContent=inquirySaving?"Saving your question…":uncertain?"We could not confirm that your question saved. Keep this page open and check Saved question details and recovery.":draft.inquiry_id?"Your question is saved. Your original words will stay in your notebook.":"You can write a question, then save it when you are ready.";
    if (uncertain) {
        $("saved").textContent = "A save may have reached Faraday. Do not retry. Use “Check existing saved question” below to inspect without writing. Link only if it finds the exact question and seven open review questions. If it cannot, keep your draft and ask for help.";
    } else if (draft.inquiry_id) {
        $("saved").textContent = "Saved inquiry: " + draft.inquiry_id +
            ". Scientific decisions remain unresolved." +
            (draft.saved_statement ? " The original question is read-only here." : " This older browser draft may differ from the canonical question; check Faraday before relying on it.");
    } else $("saved").textContent = "";
}
function renderRows() {
    $("rows").replaceChildren();
    draft.rows.forEach((row, index) => {
        const tr = document.createElement("tr");
        for (const name of ["id", "shade", "sun"]) {
            const td = document.createElement("td"), input = document.createElement("input");
            input.id = "pair-" + index + "-" + name;
            input.type = "text";
            input.maxLength = 100;
            if (name !== "id") input.inputMode = "decimal";
            input.value = row[name];
            const label = name === "id" ? "Pair label" :
                (name === "shade" ? "Shade" : "Sun") + " surface temperature in degrees Celsius";
            input.setAttribute("aria-label", label + ", row " + (index + 1));
            input.setAttribute("aria-describedby", "measurement-help");
            input.addEventListener("input", () => recordInput(() => {draft.rows[index][name] = input.value;}));
            input.addEventListener("change", finishEdit);
            input.addEventListener("blur", finishEdit);
            td.append(input); tr.append(td);
        }
        $("rows").append(tr);
    });
    $("add").disabled = draft.rows.length >= 200;
}
async function request(path, payload) {
    const response = await fetch(path, {method: "POST",
        headers: {"Content-Type": "application/json", "X-Faraday-Token": "__TOKEN__"},
        body: JSON.stringify(payload)});
    const result = await response.json();
    if (!response.ok) throw Error(result.error || "Request failed.");
    return result;
}
function displayTemperature(value) {
    return (Math.abs(value) < 0.005 ? 0 : value).toFixed(2);
}
function showPreview(result, expectedRevision, serial) {
    if (expectedRevision !== revision || serial !== previewSerial) return false;
    const omitted = result.incomplete_pair_ids.join(", ") || "none";
    $("summary").textContent = (result.mean_difference_degC === null
        ? "No complete pairs to compare."
        : "Mean sun minus shade: " + displayTemperature(result.mean_difference_degC) +
          " °C across " + result.complete_pairs + " complete rehearsal pairs.") +
          " Incomplete labels: " + omitted + ". Differences displayed to two decimal places; stored values are unchanged.";
    $("differences").replaceChildren();
    for (const pair of result.differences) {
        const li = document.createElement("li");
        li.textContent = pair.id + ": " + displayTemperature(pair.sun_minus_shade_degC) + " °C";
        $("differences").append(li);
    }
    return true;
}
function download(content, name, mediaType="application/json") {
    const url = URL.createObjectURL(new Blob([content], {type: mediaType}));
    const link = document.createElement("a");
    link.href = url; link.download = name;
    document.body.append(link); link.click(); link.remove();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
}
function retainDraftCopy(reason, bytes) {
    const base=key+":"+reason+":"+Date.now();
    // Single-writer recovery: never replace an already retained copy, including
    // when the clock repeats or moves backwards. Storage failures stop recovery.
    for(let suffix=0;suffix<1000;suffix++) {
        const candidate=base+":"+suffix;
        if(localStorage.getItem(candidate)===null) {
            localStorage.setItem(candidate,bytes);return;
        }
    }
    throw Error("No unused recovery-copy key is available.");
}
function draftExport() {
    return {...clone(draft), kind: "non-evidentiary-rehearsal-draft",
            review_status: "unresolved", scientific_evidence_eligible: false};
}
let stagedImport = null, importSerial = 0, stagedPublishedExample = false, stagedNextQuestion = false;
async function prepareDraftImport(file) {
    const serial = ++importSerial;
    if(stagedPublishedExample)announce("published-example-status","Published example selection replaced. No published example is currently staged.");
    stagedPublishedExample=false;
    if(stagedNextQuestion)announce("next-question-status","Another draft was selected. No new question is currently staged.");
    stagedNextQuestion=false;
    $("import-apply").textContent="Keep current copy and restore selected draft";
    stagedImport = null; $("import-apply").hidden = true;
    if (!file) { announce("import-status", "No draft selected."); return; }
    try {
        if (!Number.isSafeInteger(file.size) || file.size < 1 || file.size > 1048576)
            throw Error("Choose a JSON draft no larger than 1 MiB.");
        const raw = await file.text();
        if (typeof raw !== "string" || raw.length > 1048576) throw Error("Invalid file.");
        const value = JSON.parse(raw);
        if (value.kind !== "non-evidentiary-rehearsal-draft" ||
            value.review_status !== "unresolved" || value.scientific_evidence_eligible !== false ||
            !Array.isArray(value.history) || value.history.length > 1000) throw Error("Not a rehearsal export.");
        const candidate = restoreDraft(value);
        // A downloaded reference cannot establish a successful canonical save.
        if (candidate.inquiry_id || candidate.save_state === "saved") candidate.save_state = "pending";
        if (serial !== importSerial) return;
        stagedImport = candidate; $("import-apply").hidden = false;
        announce("import-status", "Draft checked: " + candidate.rows.length + " rehearsal pairs, " +
            candidate.history.length + " earlier edits. Nothing restored yet. Inquiry references are unverified; scientific review remains unresolved.");
    } catch (_) {
        if (serial === importSerial) announce("import-status", "File rejected. Choose an unresolved, non-evidentiary rehearsal export up to 1 MiB and 1000 history entries. Your current draft is unchanged.");
    }
}
function applyDraftImport() {
    if (!stagedImport) return;
    if(inquirySaving || hypothesisBusy || protocolBusy) {
        announce("import-status","Wait for the current inquiry save, hypothesis request or protocol save to finish before restoring. The selected draft remains staged; your current question is unchanged.");return;
    }
    if(stagedNextQuestion && draft.save_state==="pending") {
        announce("next-question-status","The current inquiry save is uncertain. Check the existing saved question before starting another; your draft is unchanged.");return;
    }
    if (norwaySaving || (!norwayReady && !norwayBlocked && typeof window !== "undefined")) {
        announce("import-status", "Wait for the current server operation to finish before restoring."); return;
    }
    try {
        if (recoveryLocked) throw Error("Recover unreadable bytes first.");
        const startingNextQuestion=stagedNextQuestion;
        const startingBlankQuestion=stagedNextQuestion && stagedImport.statement==="";
        const retained = JSON.stringify(draftExport());
        retainDraftCopy("before-import",retained);
        if(startingBlankQuestion)download("MY PREVIOUS SCIENCE NOTES\n\nMy question\n"+draft.statement+"\n\nMy prediction\n"+draft.prediction+"\n\nWhat I think now\n"+draft.reflection+"\n\nWorkspace notes\n"+workspaceNotesText(draft)+(nativeVerified && simulationResult ? "\n\nWhat the example showed\n"+simulationSummary(simulationResult) : ""),"faraday-previous-notes.txt","text/plain");
        else download(retained, "faraday-before-import.json");
        showRestoredDraft(stagedImport);
        if(startingBlankQuestion){resetSimulation();simulationBusyState(false);announce("simulation-status","Choose an example, then select Look at the example data.");$("simulation-result").textContent="Compare the example temperatures to see a result here.";}
        stagedImport = null; $("import-apply").hidden = true;
        if(stagedPublishedExample)announce("published-example-status","Published example restored with its attribution and limits. The previous draft was kept and a download requested. Published observations remain non-synthetic; no saved inquiry or scientific evidence was changed.");
        stagedPublishedExample=false;
        if(stagedNextQuestion) {
            announce("next-question-status","Your new question is ready. Your previous notes were kept and a download was requested.");
            $("statement").focus();
        }
        stagedNextQuestion=false;
        $("import-apply").textContent="Keep current copy and restore selected draft";
        announce("import-status", startingNextQuestion ? "Your new notebook is ready." : "Selected draft restored. The previous draft was retained locally and a download requested; check your downloads. server protection requires a save confirmation. Scientific review remains unresolved.");
    } catch (_) {
        announce("import-status", "Restore stopped. Keep this tab open and download your current draft and any unreadable stored copy before trying again.");
    }
}
$("import-file").addEventListener("change", () => prepareDraftImport($("import-file").files[0]));
$("import-apply").onclick = applyDraftImport;
$("next-question").onclick=async()=>{
    if(draft.save_state==="pending") {
        announce("next-question-status","The current inquiry save is uncertain. Check the existing saved question before starting another; your draft is unchanged.");return;
    }
    const serial=importSerial+1;
    const raw=JSON.stringify({...freshDraft(),kind:"non-evidentiary-rehearsal-draft",review_status:"unresolved",scientific_evidence_eligible:false});
    await prepareDraftImport({size:new Blob([raw]).size,text:async()=>raw});
    if(serial!==importSerial || !stagedImport)return;
    stagedNextQuestion=true;
    $("import-apply").textContent="Save a copy and start another question";
    announce("next-question-status","Your new question is ready to start. Your current notes will stay here until you choose Save a copy and start another question.");announce("import-status","Ready to start a new question. Keep a copy of your current notes first.");
    $("import-apply").focus();
};
let publishedExampleBusy=false, publishedExampleAvailable=false;
$("published-example-stage").onclick=async()=>{
    if(publishedExampleBusy || !publishedExampleAvailable)return;
    const expectedRevision=revision, serial=++importSerial;
    let ownedSerial=serial;
    if(stagedNextQuestion)announce("next-question-status","Published example selected instead. No new question is currently staged.");
    stagedNextQuestion=false;
    $("import-apply").textContent="Keep current copy and restore selected draft";
    stagedImport=null;stagedPublishedExample=false;$("import-apply").hidden=true;
    publishedExampleBusy=true;$("published-example-stage").disabled=true;
    announce("published-example-status","Checking the local published example and its retained files…");
    try {
        const value=await request("/api/examples/published",{});
        if(serial!==importSerial || expectedRevision!==revision) {
            announce("published-example-status","Your draft or selected file changed while loading. No example was staged; choose Stage again if you still want it.");return;
        }
        if(value.status!=="published_example_checked" || value.data_classification!=="published_observations_not_synthetic" ||
            value.canonical_write_performed!==false || value.scientific_evidence_eligible!==false ||
            typeof value.manifest_sha256!=="string" || !/^[a-f0-9]{64}$/.test(value.manifest_sha256) ||
            !value.source || typeof value.source.citation!=="string" || typeof value.notice!=="string")throw Error("Invalid published example.");
        const raw=JSON.stringify(value.draft);
        ownedSerial=serial+1;
        await prepareDraftImport({size:new Blob([raw]).size,text:async()=>raw});
        if(importSerial!==ownedSerial)return;
        if(!stagedImport)throw Error("Invalid example draft.");
        stagedPublishedExample=true;
        announce("published-example-status","Published example staged; current draft unchanged. "+value.source.citation+" "+value.notice+" Choose Keep current copy and restore selected draft to use it.");
        $("import-apply").focus();
    } catch(_) {
        if(ownedSerial===importSerial) {
            stagedImport=null;$("import-apply").hidden=true;
            announce("published-example-status","Published example could not be checked or staged. Your draft is unchanged. The local example may be unavailable or changed; you can keep rehearsing or use the synthetic cases.");
        }
    } finally {publishedExampleBusy=false;$("published-example-stage").disabled=!publishedExampleAvailable;}
};
try {
    const raw = localStorage.getItem(key);
    if (raw !== null) {
        hadLocalDraft = true;
        recoveryBytes = raw;
        try { draft = restoreDraft(JSON.parse(raw)); recoveryBytes = null; }
        catch (_) {
            recoveryLocked = true;
            bootIssue = "The saved draft could not be restored. Its bytes have been left unchanged. Download the unreadable draft; use the current tab only for a session draft until the saved copy is recovered.";
        }
    }
} catch (_) {
    bootIssue = "Browser storage is unavailable. Keep a downloaded copy before leaving.";
}
function invalidateHistory() {
    $("history-controls").hidden=true;
    $("history-select").replaceChildren();
    $("history-content").replaceChildren();
    announce("history-status","Draft changed. Choose Show earlier drafts to inspect retained values again.");
}
function showHistoricalSnapshot() {
    const selected=$("history-select").value;
    $("history-content").replaceChildren();
    if(!/^(0|[1-9]\d*)$/.test(selected) || Number(selected)>=draft.history.length) {
        announce("history-status","Choose an available earlier draft.");return;
    }
    const index=Number(selected), value=restoreSnapshot(draft.history[index]);
    const content=$("history-content");
    const note=(label,text)=>{
        const heading=document.createElement("h3"),paragraph=document.createElement("p");
        heading.textContent=label;paragraph.textContent=text || "Not recorded in this snapshot.";
        content.append(heading,paragraph);
    };
    note("Earlier question",value.statement);
    note("Earlier prediction",value.prediction);
    for(const [field,label] of Object.entries(designLabels))note("Earlier "+label,value.design_notes[field]);
    for(const [field,label] of Object.entries(hypothesisLabels))note("Earlier "+label,value.hypothesis_notes[field]);
    note("Earlier recording context",value.recording_notes);
    note("Earlier reflection",value.reflection);
    if(value.workspace_notes)note("Earlier workspace",workspaceNotesText(value));
    note("Earlier review contributor (unverified, review-only)",value.review_context.reviewer_kind);
    note("Earlier review notes",value.review_context.notes);
    for(const [field,text] of Object.entries(value.planning)) note("Earlier planning: "+field,text);
    const region=document.createElement("div"),table=document.createElement("table");
    region.className="table-scroll";region.tabIndex=0;region.setAttribute("role","region");
    region.setAttribute("aria-label","Earlier readings; scroll horizontally if needed");
    const caption=document.createElement("caption");caption.textContent="Earlier raw rehearsal readings — degrees Celsius";
    const header=document.createElement("thead"),headerRow=document.createElement("tr");
    for(const label of ["Pair label","Shade °C","Sun °C"]) {
        const th=document.createElement("th");th.setAttribute("scope","col");th.textContent=label;headerRow.append(th);
    }
    header.append(headerRow);const body=document.createElement("tbody");
    for(const row of value.rows) {
        const tr=document.createElement("tr");
        for(const field of ["id","shade","sun"]) {
            const td=document.createElement("td");td.textContent=row[field]==="" ? "Blank" : row[field];tr.append(td);
        }
        body.append(tr);
    }
    table.append(caption,header,body);region.append(table);content.append(region);
    announce("history-status","Showing earlier draft "+(index+1)+" of "+draft.history.length+". Read-only; current values unchanged. Scientific review remains unresolved.");
}
$("history-review").onclick=()=>{
    $("history-select").replaceChildren();$("history-content").replaceChildren();
    if(!draft.history.length) {
        $("history-controls").hidden=true;announce("history-status","No earlier editing snapshots are retained yet.");return;
    }
    for(let index=draft.history.length-1;index>=0;index--) {
        const option=document.createElement("option");option.value=String(index);
        option.textContent="Earlier draft "+(index+1)+(index===draft.history.length-1 ? " (most recent retained)" : "");
        $("history-select").append(option);
    }
    $("history-controls").hidden=false;$("history-select").value=String(draft.history.length-1);
    showHistoricalSnapshot();$("history-select").focus();
};
$("history-select").addEventListener("change",showHistoricalSnapshot);
for (const name of textFields) {
    $(name).value = draft[name];
    $(name).addEventListener("input", () => recordInput(() => {draft[name] = $(name).value;}));
    $(name).addEventListener("change", finishEdit);
    $(name).addEventListener("blur", finishEdit);
}
function hypothesisControls() {
    const ready=Boolean(draft.inquiry_id && draft.saved_statement && draft.save_state==="saved" && !hypothesisBusy && !inquirySaving && !protocolBusy);
    $("hypothesis-save").disabled=!ready || hypothesisUncertain;
    $("hypothesis-inspect").disabled=!ready;
    designControls();
}
function renderHypothesisNotes() {
    $("hypothesis-fields").replaceChildren();
    for(const [field,label] of Object.entries(hypothesisLabels)) {
        const id="hypothesis-"+field,caption=document.createElement("label"),input=document.createElement("textarea");
        caption.htmlFor=id;caption.textContent=label;input.id=id;input.maxLength=2000;
        input.value=draft.hypothesis_notes[field];input.setAttribute("aria-describedby","hypothesis-help");
        input.addEventListener("input",()=>{hypothesisUncertain=false;recordInput(()=>{draft.hypothesis_notes[field]=input.value;});hypothesisControls();});
        input.addEventListener("blur",finishEdit);$("hypothesis-fields").append(caption,input);
    }
    hypothesisControls();
}
async function submitNotebookHypothesis(write) {
    if(hypothesisBusy || inquirySaving || protocolBusy || (write && hypothesisUncertain))return;
    if(!draft.inquiry_id || !draft.saved_statement || draft.save_state!=="saved") {
        announce("hypothesis-status","Save or link the exact original question first.");return;
    }
    const proposal=clone(draft.hypothesis_notes);
    if(Object.entries(proposal).some(([field,text])=>(field!=="lineage" && !text.trim()) || text!==text.trim())) {
        announce("hypothesis-status","Complete the six scientific fields without surrounding spaces. Lineage is optional. Use one nonblank competing explanation or falsifier per line.");return;
    }
    if(write && !persist()) {announce("hypothesis-status","Proposal submission stopped because its working draft could not be retained. Download the draft first.");return;}
    const input={inquiry_id:draft.inquiry_id,original_statement:draft.saved_statement,proposal};
    const expected=revision;hypothesisBusy=true;if(write)hypothesisUncertain=true;hypothesisControls();
    announce("hypothesis-status",write?"Saving an unreviewed hypothesis through Faraday…":"Checking the exact saved proposal without writing…");
    try {
        const value=await request(write?"/api/hypothesis/propose":"/api/hypothesis/inspect",input);
        if(expected!==revision){announce("hypothesis-status","Notes changed during the request. An earlier proposal may be saved; its working notes remain in history. Check the exact proposal before relying on it.");return;}
        if(value.scientific_evidence_eligible!==false || value.inquiry_id!==input.inquiry_id || value.original_statement!==input.original_statement || JSON.stringify(value.proposal)!==JSON.stringify(proposal) || typeof value.request_sha256!=="string" || !/^[a-f0-9]{64}$/.test(value.request_sha256))throw Error("Mismatched proposal response.");
        if(value.status==="not_found" && !write && value.canonical_write_performed===false) {
            hypothesisUncertain=false;announce("hypothesis-status","No saved copy of this exact proposal was found in the verified inquiry history. It remains working notes; you may explicitly submit it.");return;
        }
        const h=value.hypothesis;
        if(value.status!=="unreviewed_hypothesis" || !h || h.statement!==proposal.statement || h.observable_prediction!==proposal.observable_prediction || h.null_model!==proposal.null_model || h.scope!==proposal.scope || JSON.stringify(h.competing_models)!==JSON.stringify(proposal.competing_models.split("\n")) || JSON.stringify(h.falsification_conditions)!==JSON.stringify(proposal.falsification_conditions.split("\n")) || JSON.stringify(h.lineage)!==JSON.stringify(proposal.lineage?proposal.lineage.split("\n"):[]) || h.workflow_state!=="unreviewed" || typeof h.hypothesis_id!=="string" || !/^[a-f0-9]{64}$/.test(h.scientific_content_sha256) || !value.ledger || value.ledger.valid!==true || typeof value.canonical_write_performed!=="boolean" || (!write && value.canonical_write_performed))throw Error("Unverified saved proposal.");
        hypothesisUncertain=false;checkedHypothesis={inquiry_id:input.inquiry_id,original_statement:input.original_statement,hypothesis_id:h.hypothesis_id,hypothesis_sha256:h.scientific_content_sha256,notes:clone(proposal)};
        const container=$("hypothesis-saved");container.replaceChildren();
        const heading=document.createElement("h3");heading.textContent="Unreviewed hypothesis: "+h.statement;container.append(heading);
        const note=document.createElement("p");note.textContent="Reference: "+h.hypothesis_id+". Scientific content sealed by the service; contributor identity unverified. This is not activation, approval or scientific evidence.";container.append(note);
        announce("hypothesis-status",value.canonical_write_performed?"Hypothesis proposal saved as unreviewed. Original question unchanged; no protocol or evidence was created.":"Exact unreviewed proposal and its ledger event verified. Nothing written.");
    } catch(error) {announce("hypothesis-status","Proposal save or inspection could not be confirmed. Keep the working notes and use Check saved hypothesis without writing; do not blindly repeat an uncertain submission.");}
    finally {hypothesisBusy=false;hypothesisControls();}
}
$("hypothesis-save").onclick=()=>submitNotebookHypothesis(true);
$("hypothesis-inspect").onclick=()=>submitNotebookHypothesis(false);
renderHypothesisNotes();
function currentCheckedHypothesis() {
    return checkedHypothesis && checkedHypothesis.inquiry_id===draft.inquiry_id && checkedHypothesis.original_statement===draft.saved_statement && JSON.stringify(checkedHypothesis.notes)===JSON.stringify(draft.hypothesis_notes);
}
function designControls() {
    $("design-preview").disabled=!currentCheckedHypothesis() || designBusy || hypothesisBusy || inquirySaving || protocolBusy;
    const ready=currentCheckedHypothesis() && checkedDesign && checkedDesign.revision===revision && !designBusy && !hypothesisBusy && !inquirySaving && !protocolBusy;
    $("protocol-draft-save").disabled=!ready || protocolUncertain;
    $("protocol-draft-inspect").disabled=!ready;
    computationControls();
}
function renderDesignNotes() {
    $("design-fields").replaceChildren();
    for(const [field,label] of Object.entries(designLabels)) {
        const id="design-"+field,caption=document.createElement("label"),input=document.createElement(field==="data_scope"?"select":"textarea");
        if(field==="data_scope")for(const [value,label] of [["","Choose data scope"],["synthetic","Made-up synthetic data"],["existing_nonhuman","Existing non-human data"],["human_or_unsure","Human-related or uncertain (unsupported here)"]]){const option=document.createElement("option");option.value=value;option.textContent=label;input.append(option);}
        caption.htmlFor=id;caption.textContent=label;input.id=id;input.maxLength=2000;input.value=draft.design_notes[field];
        input.setAttribute("aria-describedby","design-help");input.addEventListener("input",()=>recordInput(()=>{draft.design_notes[field]=input.value;}));input.addEventListener("blur",finishEdit);
        $("design-fields").append(caption,input);
    }
    designControls();
}
$("design-preview").onclick=async()=>{
    if(!currentCheckedHypothesis() || designBusy || hypothesisBusy || inquirySaving || protocolBusy)return;
    const expected=revision,target=clone(checkedHypothesis),planning=clone(draft.planning),design=clone(draft.design_notes);
    if(!["synthetic","existing_nonhuman"].includes(design.data_scope)){announce("design-status","Choose declared synthetic or existing non-human data. Human-related or uncertain data requires a separate reviewed path; no readiness claim is made.");return;}
    const requestInput={inquiry_id:target.inquiry_id,original_statement:target.original_statement,hypothesis_id:target.hypothesis_id,hypothesis_sha256:target.hypothesis_sha256,planning,design};
    designBusy=true;designControls();announce("design-status","Checking the exact hypothesis and computational design through native freeze preflight; nothing is being written…");
    try {
        const value=await request("/api/design/preview",requestInput);
        if(expected!==revision)return;
        if(value.authority!=="review_only" || value.canonical_write_performed!==false || value.analysis_performed!==false || value.scientific_evidence_eligible!==false || value.inquiry_id!==target.inquiry_id || value.original_statement!==target.original_statement || value.hypothesis_id!==target.hypothesis_id || value.hypothesis_sha256!==target.hypothesis_sha256 || JSON.stringify(value.planning)!==JSON.stringify(planning) || JSON.stringify(value.design)!==JSON.stringify(design) || !["blocked","ready_at_check_time"].includes(value.status) || typeof value.reason!=="string" || !value.protocol_input || value.protocol_input.analysis_mode!=="exploratory" || value.protocol_input.protocol_kind!=="computational" || JSON.stringify(value.protocol_input.hypotheses_tested)!==JSON.stringify([target.hypothesis_id]))throw Error("Mismatched design preflight.");
        const lists=["safety_constraints","inputs_required","quality_requirements","controls","success_conditions","failure_conditions","expected_outputs","environment_requirements"];
        const requestDigest=[...new Uint8Array(await crypto.subtle.digest("SHA-256",new TextEncoder().encode(canonicalJson(requestInput))))].map(byte=>byte.toString(16).padStart(2,"0")).join("");
        const expectedProtocol={experiment_id:"notebook-design-"+requestDigest,title:planning.title,analysis_mode:"exploratory",protocol_kind:"computational",hypotheses_tested:[target.hypothesis_id],primary_outcome:planning.outcome,sampling_unit:planning.unit_of_observation || "",human_subjects:false,
            ...Object.fromEntries(Object.entries(design).filter(([key])=>key!=="data_scope").map(([key,text])=>[key,lists.includes(key)?(text?text.split("\n"):[]):text]))};
        if(canonicalJson(value.protocol_input)!==canonicalJson(expectedProtocol) || value.hypothesis_statement!==target.notes.statement ||
            (value.status==="ready_at_check_time" && (!value.native_preflight || value.native_preflight.status!=="ready" || value.native_preflight.would_append_event!==false || !value.native_preflight.hypothesis_commitments || value.native_preflight.hypothesis_commitments[target.hypothesis_id]!==target.hypothesis_sha256 || !["pending_review","active"].includes(value.hypothesis_workflow_state))))throw Error("Native readiness binding differs.");
        const digest=[...new Uint8Array(await crypto.subtle.digest("SHA-256",new TextEncoder().encode(canonicalJson({request:requestInput,protocol_input:value.protocol_input}))))].map(byte=>byte.toString(16).padStart(2,"0")).join("");
        if(digest!==value.design_input_sha256)throw Error("Design input commitment differs.");
        if(expected!==revision)return;
        checkedDesign={request:clone(requestInput),design_input_sha256:value.design_input_sha256,protocol_input:clone(value.protocol_input),revision};
        const container=$("design-result");container.replaceChildren();
        const heading=document.createElement("h3");heading.textContent="Exploratory computational design: "+value.protocol_input.title;container.append(heading);
        const note=(label,text)=>{const h=document.createElement("h4"),p=document.createElement("p");h.textContent=label;p.textContent=text || "Unresolved";container.append(h,p);};
        note("Bound hypothesis",target.hypothesis_id+": "+value.hypothesis_statement+" ("+value.hypothesis_workflow_state+")");
        note("Native preflight",value.reason);note("Primary outcome",value.protocol_input.primary_outcome);note("Observation unit",value.protocol_input.sampling_unit);
        for(const [field,label] of Object.entries(designLabels))note(label,design[field]);
        note("Limits",value.notice);
        announce("design-status",value.status==="blocked"?"Design is not ready to freeze. The first native refusal is shown below. Nothing written or run.":"Native preflight passed at check time. No protocol was created, frozen or executed; this is not scientific approval.");
    } catch(error) {if(expected===revision){$("design-result").replaceChildren();announce("design-status","Design preview could not be checked. Verify the saved hypothesis and enter a planning title/outcome plus unpadded, unique list lines. Nothing written or frozen.");}}
    finally {designBusy=false;designControls();}
};
async function notebookProtocolDraft(write) {
    if(protocolBusy || hypothesisBusy || inquirySaving || designBusy || !checkedDesign || checkedDesign.revision!==revision || !currentCheckedHypothesis() || (write && protocolUncertain))return;
    if(write && !persist()){announce("protocol-draft-status","Draft submission stopped because the working notes could not be retained. Download them first.");return;}
    const checked=clone(checkedDesign),expected=revision;
    protocolBusy=true;checkedProtocol=null;if(write)protocolUncertain=true;hypothesisControls();$("protocol-draft-result").replaceChildren();
    announce("protocol-draft-status",write?"Saving this exact checked proposal as a draft through Faraday…":"Checking the exact saved protocol draft and its history without writing…");
    try {
        const value=await request(write?"/api/design/save":"/api/design/inspect",{request:checked.request,design_input_sha256:checked.design_input_sha256});
        if(expected!==revision){announce("protocol-draft-status","Working notes changed during the request. An earlier design may have been saved; restore its exact notes from history to inspect it. No freeze was requested.");return;}
        if(value.analysis_performed!==false || value.scientific_evidence_eligible!==false || typeof value.canonical_write_performed!=="boolean" || (!write && value.canonical_write_performed) || !value.design || value.design.authority!=="review_only" || value.design.canonical_write_performed!==false || value.design.analysis_performed!==false || value.design.scientific_evidence_eligible!==false || !["blocked","ready_at_check_time"].includes(value.design.status) || typeof value.design.reason!=="string" || value.design.original_statement!==checked.request.original_statement || value.design.design_input_sha256!==checked.design_input_sha256 || canonicalJson(value.design.protocol_input)!==canonicalJson(checked.protocol_input) || value.design.inquiry_id!==checked.request.inquiry_id || value.design.hypothesis_id!==checked.request.hypothesis_id || value.design.hypothesis_sha256!==checked.request.hypothesis_sha256)throw Error("Protocol response binding differs.");
        if(value.status==="not_found" && !write && value.canonical_write_performed===false){protocolUncertain=false;announce("protocol-draft-status","No exact saved draft was found in the verified history. Your design remains working notes; explicitly save it if wanted.");return;}
        const record=value.protocol;
        if(value.status!=="notebook_protocol_draft" || !record || record.status!=="draft" || record.protocol_hash!==null || !value.ledger || value.ledger.valid!==true || typeof record.protocol_id!=="string" || typeof value.draft_payload_sha256!=="string" || !/^[a-f0-9]{64}$/.test(value.draft_payload_sha256) || Object.entries(checked.protocol_input).some(([field,input])=>canonicalJson(record[field])!==canonicalJson(input)))throw Error("Unverified protocol draft.");
        const digest=[...new Uint8Array(await crypto.subtle.digest("SHA-256",new TextEncoder().encode(canonicalJson(record))))].map(byte=>byte.toString(16).padStart(2,"0")).join("");
        if(digest!==value.draft_payload_sha256)throw Error("Stored draft digest differs.");
        if(expected!==revision)return;
        protocolUncertain=false;checkedProtocol={checked_draft:{request:clone(checked.request),design_input_sha256:checked.design_input_sha256},protocol_id:record.protocol_id,draft_payload_sha256:value.draft_payload_sha256,revision};const container=$("protocol-draft-result");container.replaceChildren();
        const heading=document.createElement("h3"),summary=document.createElement("p"),limits=document.createElement("p");
        heading.textContent="Saved protocol draft: "+record.title;
        summary.textContent="Reference: "+record.protocol_id+". Bound hypothesis: "+checked.request.hypothesis_id+". Status: draft; no frozen protocol hash. Native freeze readiness: "+value.design.status+" — "+value.design.reason;
        limits.textContent=value.notice;container.append(heading,summary,limits);
        announce("protocol-draft-status",value.canonical_write_performed?"Protocol draft saved. Freeze, hypothesis status, datasets, runs and evidence were not advanced.":"Exact protocol draft and its creation event verified. Nothing written or frozen.");
    } catch(error) {announce("protocol-draft-status","Protocol draft save or inspection could not be confirmed. Keep the exact working notes and use Check saved protocol draft without writing; do not blindly repeat an uncertain save. Partial records may remain.");}
    finally {protocolBusy=false;hypothesisControls();}
}
$("protocol-draft-save").onclick=()=>notebookProtocolDraft(true);
$("protocol-draft-inspect").onclick=()=>notebookProtocolDraft(false);

function computationControls() {
    const busy=computationBusy || simulationHandoffBusy;
    $("simulation-to-design").disabled=simulationHandoffBusy || simulationBusy || computationBusy || inquirySaving || hypothesisBusy || designBusy || protocolBusy || !simulationPlan || draft.design_notes.data_scope!=="synthetic";
    $("computation-prepare").disabled=busy || protocolBusy || designBusy || hypothesisBusy || inquirySaving || !checkedProtocol || checkedProtocol.revision!==revision;
    $("computation-run").disabled=busy || !computation || computationAttempted;
    $("computation-download").disabled=busy || !computation;
    $("computation-portable-download").disabled=busy || !computation;
    $("computation-assess").disabled=busy || !computation || computation.status==="prepared_computation";
    $("computation-reopen").disabled=busy;
}
$("simulation-to-design").onclick=async()=>{
    if(simulationHandoffBusy || simulationBusy || computationBusy || inquirySaving || hypothesisBusy || designBusy || protocolBusy || !simulationPlan)return;
    if(draft.design_notes.data_scope!=="synthetic"){announce("simulation-to-design-status","Choose Made-up synthetic data explicitly before copying generated inputs. Existing or uncertain data scope was not changed.");return;}
    const plan=simulationPlan,expected=revision,inputRevision=computationRevision;simulationHandoffBusy=true;computationControls();
    try {
        const value=await request("/api/simulation/design",{simulation_id:plan.simulation_id,recipe_sha256:plan.recipe_sha256});
        if(value.status!=="prepared" || value.canonical_write_performed!==false || value.simulation_id!==plan.simulation_id || value.recipe_sha256!==plan.recipe_sha256 || value.recipe?.data_classification!=="synthetic" || value.recipe.scientific_evidence_eligible!==false || canonicalJson(value.recipe)!==canonicalJson(plan.recipe))throw Error("Retained recipe differs.");
        const {spec}=await checkedSimulationDesign(value),identity=value.method_identity;
        if(!identity || identity.method!==spec.method || !/^[a-f0-9]{64}$/.test(identity.implementation_sha256))throw Error("Missing method identity.");
        if(plan!==simulationPlan || expected!==revision || inputRevision!==computationRevision || draft.design_notes.data_scope!=="synthetic")throw Error("Selection changed during inspection.");
        const prior={specification_json:$("computation-spec").value,input_csv:$("computation-data").value,provenance:$("computation-provenance").value,design_notes:clone(draft.design_notes),computation:clone(computation)};
        const raw=JSON.stringify(prior);retainDraftCopy("before-simulation-inputs",raw);
        if(prior.specification_json || prior.input_csv || prior.provenance)download(raw,"faraday-before-simulation-inputs.json");
        finishEdit();recordInput(()=>{draft.design_notes.analysis_code_hash=identity.implementation_sha256;});finishEdit();$("design-analysis_code_hash").value=identity.implementation_sha256;
        $("computation-spec").value=value.design.specification_json;$("computation-data").value=value.design.input_csv;
        $("computation-provenance").value="Made-up "+value.recipe.case+" software fixture. Simulation reference: "+value.simulation_id+"; recipe SHA-256: "+value.recipe_sha256+"; specification SHA-256: "+value.recipe.specification_sha256+"; input SHA-256: "+value.recipe.input_sha256+". Fixed generated units, not physical observations or independent scientific evidence.";
        announce("simulation-to-design-status","Rechecked simulation inputs and bundled implementation identity copied for review. Previous buffers retained. Review the question, hypothesis and design against this case, then recheck and explicitly save a draft. Nothing was frozen or executed.");
    } catch(_){announce("simulation-to-design-status","Simulation handoff could not be confirmed. Check retained bytes, current selection and prior-buffer backup. Inspect the current fields before retrying; no freeze or execution was requested.");}
    finally {simulationHandoffBusy=false;computationControls();}
};
function invalidateComputation() {
    computationRevision++;computation=null;computationAttempted=false;
    $("computation-result").textContent="";
    announce("computation-status","Inputs or notebook changed. Retain a fresh computation; earlier bundles remain on the server.");
    computationControls();
}
async function computationTextDigest(text) {
    return [...new Uint8Array(await crypto.subtle.digest("SHA-256",new TextEncoder().encode(text)))].map(v=>v.toString(16).padStart(2,"0")).join("");
}
async function computationDigest(value) {
    return computationTextDigest(canonicalJson(value));
}
async function checkComputation(value, expectedBundle=null) {
    if(!value || !["prepared_computation","verified_computation","refused_computation"].includes(value.status) || value.canonical_write_performed!==false || value.scientific_evidence_eligible!==false || typeof value.attempted!=="boolean" || !value.bundle || value.bundle.scientific_evidence_eligible!==false || !/^[a-f0-9]{64}$/.test(value.bundle_sha256) || await computationDigest(value.bundle)!==value.bundle_sha256 || (expectedBundle && canonicalJson(value.bundle)!==canonicalJson(expectedBundle)))throw Error("Computation commitment differs.");
    if(typeof value.bundle.specification_json!=="string" || typeof value.bundle.input_csv!=="string" || await computationTextDigest(value.bundle.specification_json)!==value.bundle.specification_sha256 || await computationTextDigest(value.bundle.input_csv)!==value.bundle.input_sha256)throw Error("Input byte commitments differ.");
    if(value.status==="verified_computation" && (!/^[a-f0-9]{64}$/.test(value.receipt_sha256) || !value.result || value.method!==value.bundle.method || !value.environment || typeof value.notice!=="string"))throw Error("Incomplete computation result.");
    if(value.status==="refused_computation" && (!/^[a-f0-9]{64}$/.test(value.failure_sha256) || !value.failure || value.failure.status!=="execution_refused" || value.failure.scientific_evidence_eligible!==false || value.failure.bundle_sha256!==value.bundle_sha256 || value.result))throw Error("Incomplete refusal.");
    return value;
}
function computationReference(value) {
    return value.status==="verified_computation"?{bundle_sha256:value.bundle_sha256,receipt_sha256:value.receipt_sha256}:{bundle_sha256:value.bundle_sha256,failure_sha256:value.failure_sha256};
}
function readableWorkingOutcome(bundle,result,failure) {
    if(failure)return "Execution refused: "+failure.error+"\nNo numerical result or confidence interval is asserted.";
    if(!result)return "No verified numerical result retained in this view.";
    const body=result.result,number=value=>typeof value==="number" && Number.isFinite(value)?String(value):"unavailable";
    if(!body || !Number.isFinite(body.mean_difference_first_minus_second))return "A supported numerical summary is unavailable. Keep the complete private output for inspection.";
    const groups=Array.isArray(body.groups) && body.groups.length===2?body.groups:["first declared group","second declared group"];
    const interval=body.confidence_interval,lines=["Signed comparison: mean "+groups[0]+" minus mean "+groups[1]+".","Mean difference: "+number(body.mean_difference_first_minus_second)+" in the declared outcome's units."];
    const spec=JSON.parse(bundle.specification_json);lines.push("Outcome column: "+(spec.outcome_column || "not declared")+"; unit identifier column: "+(spec.unit_column || "not declared")+".");
    if(interval)lines.push("Bootstrap confidence interval: ["+number(interval.lower)+", "+number(interval.upper)+"], level "+number(interval.level)+".");
    lines.push("Units and scale need the study's measurement definition; this arithmetic does not validate them.");
    if(body.n_by_group)for(const group of groups)lines.push(group+": "+number(body.n_by_group[group])+" included units; mean "+number(body.mean_by_group?.[group])+".");
    lines.push("Missing outcome rows: "+number(body.missing_rows)+".");
    if(body.exclusion_report){const e=body.exclusion_report;lines.push("Input records: "+number(e.input_records)+"; included records: "+number(e.included_records)+"; excluded records: "+(Array.isArray(e.excluded_records)?e.excluded_records.length:"unavailable")+".");if(e.excluded_by_group)for(const [group,count] of Object.entries(e.excluded_by_group))lines.push("Excluded in "+group+": "+number(count)+".");if("excluded_without_registered_group" in e)lines.push("Excluded without a registered group: "+number(e.excluded_without_registered_group)+".");}
    lines.push("Bootstrap resamples: "+number(body.bootstrap_resamples)+"; seed: "+number(body.seed)+".");
    if("pooled_within_group_standard_deviation" in body)lines.push("Pooled within-group standard deviation: "+number(body.pooled_within_group_standard_deviation)+".");
    if("standardized_effect_status" in body)lines.push("Standardized effect: "+body.standardized_effect_status+"; Cohen's d "+number(body.cohen_d)+"; Hedges' g "+number(body.hedges_g)+".");
    lines.push("Assumptions (declared, not established):");for(const assumption of body.assumptions || [])lines.push("• "+assumption);
    for(const warning of body.warnings || [])lines.push("Warning: "+warning);
    lines.push("A signed estimate or interval does not establish causality or scientific validity. The complete output remains in the private bundle.");
    return lines.join("\n");
}
function showComputation(value) {
    const b=value.bundle;
    $("computation-result").textContent="Question: "+b.checked_draft.request.original_statement+"\nDraft protocol: "+b.protocol_id+"\nDeclared scope: "+b.data_scope+"\nSource/generation: "+b.provenance+"\nBundle SHA-256: "+value.bundle_sha256+"\n\n"+b.notice+"\n\n"+readableWorkingOutcome(b,value.result,value.failure);
}
for(const id of ["computation-spec","computation-data","computation-provenance"])$(id).addEventListener("input",invalidateComputation);
$("computation-method").onclick=async()=>{
    try {const response=await fetch("/api/computation/method");if(!response.ok)throw Error();const value=await response.json();if(value.method!=="independent_mean_difference_ci" || !/^[a-f0-9]{64}$/.test(value.implementation_sha256))throw Error();announce("computation-method-status","Bundled method: "+value.method+". Implementation SHA-256: "+value.implementation_sha256+". Enter this identity in the design before checking and saving it.");}
    catch(_){announce("computation-method-status","Method identity unavailable. No computation prepared.");}
};
$("computation-prepare").onclick=async()=>{
    if(computationBusy || simulationHandoffBusy || !checkedProtocol || checkedProtocol.revision!==revision)return;
    const target=clone(checkedProtocol),expected=computationRevision,notebookRevision=revision;
    const payload={checked_draft:target.checked_draft,specification_json:$("computation-spec").value,input_csv:$("computation-data").value,provenance:$("computation-provenance").value};
    computationBusy=true;computation=null;computationControls();
    try {
        const value=await checkComputation(await request("/api/computation/prepare",payload));
        if(expected!==computationRevision || notebookRevision!==revision)throw Error("Inputs changed during preparation; earlier bytes may be retained.");
        const b=value.bundle;
        if(canonicalJson(b.checked_draft)!==canonicalJson(payload.checked_draft) || b.protocol_id!==target.protocol_id || b.draft_payload_sha256!==target.draft_payload_sha256 || b.specification_json!==payload.specification_json || b.input_csv!==payload.input_csv || b.provenance!==payload.provenance || b.data_scope!==target.checked_draft.request.design.data_scope || b.implementation_sha256!==target.checked_draft.request.design.analysis_code_hash)throw Error("Prepared input binding differs.");
        computation=value;computationAttempted=value.attempted;showComputation(value);announce("computation-status","Exact working inputs retained. Download the private bundle before closing. This draft is not frozen or scientific evidence.");
    } catch(_){announce("computation-status","Preparation could not be confirmed. Keep the input text; check the exact draft, method identity, bounded JSON/CSV and source description. Partial files may remain.");}
    finally {computationBusy=false;computationControls();}
};
$("computation-run").onclick=async()=>{
    if(computationBusy || simulationHandoffBusy || !computation || computationAttempted)return;
    const target=clone(computation),expected=computationRevision;computationBusy=true;computationAttempted=true;computationControls();
    try {
        const value=await checkComputation(await request("/api/computation/run",{bundle_sha256:target.bundle_sha256}),target.bundle);
        if(expected!==computationRevision)return;
        if(!["verified_computation","refused_computation"].includes(value.status))throw Error();computation=value;showComputation(value);
        announce("computation-status",value.status==="refused_computation"?"Execution refusal retained and hash-verified. No numerical result is asserted; download the bundle to preserve the refusal.":"Registered exploratory calculation verified against the retained inputs. Inspect uncertainty and assumptions; this is not scientific evidence.");
    } catch(_){if(expected===computationRevision)announce("computation-status","Execution refused or completion was not confirmed. No numerical result is asserted. Retained artifacts remain; this bundle cannot be blindly rerun. Preserve the bundle for inspection.");}
    finally {computationBusy=false;computationControls();}
};
$("computation-download").onclick=async()=>{
    if(computationBusy || simulationHandoffBusy || !computation)return;
    const target=clone(computation),expected=computationRevision;computationBusy=true;computationControls();
    try {
        const verified=target.status!=="prepared_computation";
        const value=await checkComputation(await request(verified?"/api/computation/verify":"/api/computation/inspect",verified?computationReference(target):{bundle_sha256:target.bundle_sha256}),target.bundle);
        if(expected!==computationRevision || (verified && canonicalJson(value)!==canonicalJson(target)))throw Error();
        download(JSON.stringify({format:"faraday-working-computation-v1",computation:value,replay:"Write bundle.specification_json as analysis.json and bundle.input_csv as input.csv without changing bytes. Run: research analysis run --spec-file analysis.json --data-file input.csv --output replay --expect-spec-sha256 "+value.bundle.specification_sha256+" --expect-input-sha256 "+value.bundle.input_sha256+". Replay uses the same method; it is not independent replication."},null,2),"faraday-working-computation.json");
        announce("computation-status","Private computation bundle downloaded with exact input bytes, provenance, draft binding and any verified result. Keep it private.");
    } catch(_){computation=null;$("computation-result").textContent="Current integrity verification failed. Earlier values are not currently verified.";announce("computation-status","Download blocked because retained inputs, draft or execution could not be verified.");}
    finally {computationBusy=false;computationControls();}
};
$("computation-reopen").addEventListener("change",async()=>{
    const file=$("computation-reopen").files[0];if(!file || computationBusy || simulationHandoffBusy)return;
    computationBusy=true;computationControls();const expected=++computationRevision;computation=null;$("computation-result").textContent="";
    try {
        if(file.size>256000)throw Error();const item=JSON.parse(await file.text());if(item.format!=="faraday-working-computation-v1")throw Error();
        const candidate=await checkComputation(item.computation),verified=candidate.status!=="prepared_computation";
        const value=await checkComputation(await request(verified?"/api/computation/verify":"/api/computation/inspect",verified?computationReference(candidate):{bundle_sha256:candidate.bundle_sha256}),candidate.bundle);
        if(expected!==computationRevision || (verified && canonicalJson(value)!==canonicalJson(candidate)))throw Error();
        computation=value;computationAttempted=value.attempted;showComputation(value);announce("computation-status","Retained server computation rechecked against the private bundle. Its question is shown below; your current notebook was not replaced.");
    } catch(_){announce("computation-status","Reopen failed. This operation needs the original retained server artifacts and exact private commitments; no notebook or scientific record was replaced.");}
    finally {computationBusy=false;computationControls();}
});
async function checkPortableEnvelope(envelope) {
    if(!envelope || Object.keys(envelope).sort().join(",")!=="archive_json,archive_sha256,format" || envelope.format!=="faraday-portable-computation-v1" || typeof envelope.archive_json!=="string" || !/^[a-f0-9]{64}$/.test(envelope.archive_sha256) || await computationTextDigest(envelope.archive_json)!==envelope.archive_sha256)throw Error("Portable archive commitment differs.");
    const archive=JSON.parse(envelope.archive_json);
    if(archive.scientific_evidence_eligible!==false || !archive.computation || archive.computation.scientific_evidence_eligible!==false || archive.computation.canonical_write_performed!==false || typeof archive.scope!=="string" || !archive.context)throw Error("Portable archive claims authority.");
    return archive;
}
$("computation-portable-download").onclick=async()=>{
    if(computationBusy || simulationHandoffBusy || !computation)return;
    const target=clone(computation),expected=computationRevision;computationBusy=true;computationControls();
    try {
        const envelope=await request("/api/computation/export",target.status==="prepared_computation"?{bundle_sha256:target.bundle_sha256}:computationReference(target));
        const archive=await checkPortableEnvelope(envelope);
        if(expected!==computationRevision || canonicalJson(archive.computation)!==canonicalJson(target))throw Error("Export context changed.");
        download(JSON.stringify(envelope,null,2),"faraday-portable-computation.json");announce("computation-status","Portable archive downloaded with exact input/output bytes, source context and redacted receipt locators. Hash consistency is not scientific approval.");
    } catch(_){announce("computation-status","Portable download blocked: source context, exact bytes or current integrity could not be confirmed.");}
    finally {computationBusy=false;computationControls();}
};
function portableControls() {
    $("portable-file").disabled=portableBusy;
    $("portable-restore").disabled=portableBusy || !portableStaged;
    $("portable-cancel").disabled=portableBusy || !portableStaged;
    $("portable-replay").disabled=portableBusy || Boolean(portableStaged) || !portableRetained || portableRetained.replay_attempted || portableReplayUncertain;
    $("portable-download").disabled=portableBusy || Boolean(portableStaged) || !portableRetained;
    $("portable-report").disabled=portableBusy || Boolean(portableStaged) || !portableOutcome;
    $("portable-assess-source").disabled=portableBusy || Boolean(portableStaged) || !portableRetained || JSON.parse(portableRetained.envelope.archive_json).computation.status==="prepared_computation";
    $("portable-assess-replay").disabled=portableBusy || Boolean(portableStaged) || !portableOutcome;
}
function showPortable(envelope,outcome=null,staged=false) {
    const source=JSON.parse(envelope.archive_json),b=source.computation.bundle;
    $("portable-result").textContent=(staged?"STAGED FILE — not retained or scientifically accepted":"RETAINED ARCHIVE — source claims unauthenticated")+"\nQuestion: "+b.checked_draft.request.original_statement+"\nSource protocol: "+b.protocol_id+" (archived draft, not recreated)\nSource description: "+b.provenance+"\nArchive SHA-256: "+envelope.archive_sha256+"\n"+source.scope+"\n\nARCHIVED SOURCE OUTCOME\n"+readableWorkingOutcome(b,source.computation.result,source.computation.failure)+(outcome?"\n\nLOCAL REPLAY\n"+outcome.comparison+"\n"+readableWorkingOutcome(b,outcome.result,outcome.refusal):"");
}
$("portable-file").addEventListener("change",async()=>{
    const file=$("portable-file").files[0];if(!file || portableBusy)return;
    portableBusy=true;portableStaged=null;portableControls();$("portable-result").textContent="";
    try {
        if(file.size>1100000)throw Error();const envelope=JSON.parse(await file.text());await checkPortableEnvelope(envelope);
        portableStaged=envelope;showPortable(envelope,null,true);announce("portable-status","File hash checked locally and staged only. Inspect the archived question, then explicitly retain it for full contract/output verification. No server or notebook write yet.");
    } catch(_){if(portableRetained)showPortable(portableRetained.envelope,portableOutcome);announce("portable-status","File could not be staged as a portable working archive. Existing retained archive and notebook are unchanged.");}
    finally {portableBusy=false;portableControls();}
});
$("portable-cancel").onclick=()=>{
    if(portableBusy || !portableStaged)return;portableStaged=null;
    if(portableRetained)showPortable(portableRetained.envelope,portableOutcome);else $("portable-result").textContent="";
    announce("portable-status","Staged file discarded; no server or notebook write performed. Earlier retained archive is unchanged.");portableControls();
};
async function checkRetainedPortable(value,envelope) {
    if(!value || !["retained_portable_computation","verified_portable_replay","verified_portable_refusal"].includes(value.status) || value.canonical_write_performed!==false || value.scientific_evidence_eligible!==false || typeof value.replay_attempted!=="boolean" || value.archive_sha256!==envelope.archive_sha256 || canonicalJson(value.envelope)!==canonicalJson(envelope))throw Error("Portable response differs.");
    await checkPortableEnvelope(value.envelope);return value;
}
$("portable-restore").onclick=async()=>{
    if(portableBusy || !portableStaged)return;const target=clone(portableStaged);portableBusy=true;portableControls();
    try {
        const value=await checkRetainedPortable(await request("/api/portable-computation/restore",target),target);
        if(value.status!=="retained_portable_computation")throw Error();portableRetained=value;portableOutcome=null;portableStaged=null;portableReplayUncertain=false;showPortable(value.envelope);
        try {
            const raw=localStorage.getItem(portableRecoveryKey(value));
            const reference=raw===null?null:checkedPortableRecoveryReference(JSON.parse(raw),value.archive_sha256);
            if(reference && !value.replay_attempted)throw Error("Earlier attempt missing.");
            if(value.replay_attempted) {
                if(!reference)throw Error("Earlier reference unavailable.");
                const recovered=checkedPortableOutcome(await checkRetainedPortable(await request("/api/portable-computation/verify",reference),target),reference);
                portableOutcome=recovered;portableRetained=recovered;showPortable(recovered.envelope,recovered);
                announce("portable-status","Earlier replay rechecked and reopened. No analysis was run again. "+recovered.comparison+" Same-code replay is not independent replication or scientific evidence.");
            } else announce("portable-status","Archive retained and its context/output contracts checked. No canonical inquiry, hypothesis, protocol, run or evidence was created. Replay is a separate action.");
        } catch(_) {
            portableReplayUncertain=true;
            announce("portable-status","Source archive reopened, but the earlier replay could not be rechecked. Its report remains blocked and no analysis will be rerun. Keep the existing reports and retained artifacts.");
        }
    } catch(_){announce("portable-status","Restore not confirmed. Preserve the source file; partial working artifacts may remain. No canonical restoration is inferred.");}
    finally {portableBusy=false;portableControls();}
};
function portableReference(value) {return {archive_sha256:value.archive_sha256,...(value.status==="verified_portable_replay"?{receipt_sha256:value.receipt_sha256}:{refusal_sha256:value.refusal_sha256})};}
function portableRecoveryKey(value) {return key+":portable-replay:"+value.archive_sha256;}
function checkedPortableRecoveryReference(value,archive) {
    if(!value || typeof value!=="object" || Array.isArray(value) || value.archive_sha256!==archive || !/^[a-f0-9]{64}$/.test(archive) ||
        !["archive_sha256,receipt_sha256","archive_sha256,refusal_sha256"].includes(Object.keys(value).sort().join(",")) ||
        !/^[a-f0-9]{64}$/.test(value.receipt_sha256 || value.refusal_sha256))throw Error("Invalid replay recovery reference.");
    return value;
}
function checkedPortableOutcome(value,reference=null) {
    if(!["verified_portable_replay","verified_portable_refusal"].includes(value.status) || value.replay_attempted!==true || typeof value.comparison!=="string" ||
        (value.status==="verified_portable_refusal" ? !value.refusal || Boolean(value.result) : !value.result))throw Error("Invalid replay outcome.");
    const actual=checkedPortableRecoveryReference(portableReference(value),value.archive_sha256);
    if(reference && canonicalJson(actual)!==canonicalJson(reference))throw Error("Replay recovery commitment differs.");
    return value;
}
$("portable-replay").onclick=async()=>{
    if(portableBusy || !portableRetained || portableRetained.replay_attempted || portableReplayUncertain)return;
    const target=clone(portableRetained);portableBusy=true;portableRetained.replay_attempted=true;portableControls();
    try {
        const value=checkedPortableOutcome(await checkRetainedPortable(await request("/api/portable-computation/replay",{archive_sha256:target.archive_sha256}),target.envelope));
        portableOutcome=value;portableRetained=value;portableReplayUncertain=false;showPortable(value.envelope,value);
        let retained=true;try {localStorage.setItem(portableRecoveryKey(value),JSON.stringify(portableReference(value)));}catch(_){retained=false;}
        announce("portable-status",value.comparison+" Same-code replay does not establish independent replication or scientific evidence."+(retained?" Reopen this source archive in the same browser and workspace to recheck this replay later.":" The browser could not keep its recovery reference. Download the replay report before closing."));
    } catch(_){announce("portable-status","Replay failed or completion was not confirmed. Preserve the archive and artifacts; no blind retry. A different current implementation blocks replay while archive viewing remains available.");}
    finally {portableBusy=false;portableControls();}
};
$("portable-download").onclick=async()=>{
    if(portableBusy || !portableRetained)return;const target=clone(portableRetained);portableBusy=true;portableControls();
    try {
        const value=await checkRetainedPortable(await request("/api/portable-computation/inspect",{archive_sha256:target.archive_sha256}),target.envelope);
        download(JSON.stringify(value.envelope,null,2),"faraday-portable-computation.json");announce("portable-status","Retained source archive rechecked and downloaded; local replay has not replaced its original outcome.");
    } catch(_){announce("portable-status","Archive download blocked: retained bytes or contracts could not be verified.");}
    finally {portableBusy=false;portableControls();}
};
$("portable-report").onclick=async()=>{
    if(portableBusy || !portableOutcome)return;const target=clone(portableOutcome);portableBusy=true;portableControls();
    try {
        const value=await checkRetainedPortable(await request("/api/portable-computation/verify",portableReference(target)),target.envelope);
        if(canonicalJson(value)!==canonicalJson(target))throw Error();download(JSON.stringify({format:"faraday-portable-replay-report-v1",report:value},null,2),"faraday-portable-replay-report.json");announce("portable-status","Verified local replay report downloaded with preserved source archive, assumptions, uncertainty and comparison.");
    } catch(_){portableOutcome=null;announce("portable-status","Replay report download blocked because its current artifact binding failed. Source archive remains separate.");}
    finally {portableBusy=false;portableControls();}
};
function assessmentNotes() {return Object.fromEntries(Object.keys(assessmentLabels).map(field=>[field,$("assessment-"+field).value]));}
function assessmentControls() {
    for(const field of Object.keys(assessmentLabels))if($("assessment-"+field))$("assessment-"+field).disabled=assessmentBusy || !assessmentSource;
    $("assessment-save").disabled=assessmentBusy || !assessmentSource;
    $("assessment-download").disabled=assessmentBusy || !assessmentSaved;
    $("assessment-next").disabled=assessmentBusy || !assessmentSaved;
    $("assessment-file").disabled=assessmentBusy;
}
function preserveAssessmentNotes() {
    const notes=assessmentNotes();if(!Object.values(notes).some(Boolean))return;
    const raw=JSON.stringify({source:assessmentSource,notes,assessment_sha256:assessmentSaved?.assessment_sha256 || null});
    retainDraftCopy("assessment-notes",raw);download(raw,"faraday-before-assessment-change.json");
}
function selectAssessmentSource(source,question) {
    if(assessmentBusy)return;
    try {
        if(canonicalJson(source)!==canonicalJson(assessmentSource)){
            preserveAssessmentNotes();for(const field of Object.keys(assessmentLabels))$("assessment-"+field).value="";
            assessmentSaved=null;assessmentRevision++;$("assessment-result").textContent="";
        }
        assessmentSource=clone(source);$("assessment-source").textContent="Selected source question: "+question+". Reference: "+JSON.stringify(source);
        announce("assessment-status","Outcome selected. Enter your interpretation, uncertainty, alternatives, limitations and unreviewed follow-up question. No evidence or action recommendation is created.");assessmentControls();$("assessment-interpretation").focus();
    } catch(_){announce("assessment-status","Source change stopped because earlier assessment notes could not be retained. Download them before changing source.");}
}
for(const [field,label] of Object.entries(assessmentLabels)){
    const caption=document.createElement("label"),input=document.createElement("textarea");input.id="assessment-"+field;caption.htmlFor=input.id;caption.textContent=label;input.maxLength=2000;input.setAttribute("aria-describedby","assessment-help");
    input.addEventListener("input",()=>{assessmentRevision++;assessmentSaved=null;$("assessment-result").textContent="";announce("assessment-status","Working assessment changed. Save a new version; earlier saved notes remain.");assessmentControls();});
    $("assessment-fields").append(caption,input);
}
$("computation-assess").onclick=()=>{if(computation && computation.status!=="prepared_computation" && !computationBusy)selectAssessmentSource({kind:"notebook",...computationReference(computation)},computation.bundle.checked_draft.request.original_statement);};
$("portable-assess-source").onclick=()=>{if(portableRetained && !portableBusy && !portableStaged){const source=JSON.parse(portableRetained.envelope.archive_json).computation;if(source.status!=="prepared_computation")selectAssessmentSource({kind:"portable_source",archive_sha256:portableRetained.archive_sha256},source.bundle.checked_draft.request.original_statement);}};
$("portable-assess-replay").onclick=()=>{if(portableOutcome && !portableBusy && !portableStaged)selectAssessmentSource({kind:"portable_replay",...portableReference(portableOutcome)},JSON.parse(portableOutcome.envelope.archive_json).computation.bundle.checked_draft.request.original_statement);};
async function checkAssessment(value,source=null,notes=null) {
    if(!value || value.status!=="verified_working_assessment" || value.canonical_write_performed!==false || value.scientific_evidence_eligible!==false || value.action_recommendation_created!==false || !/^[a-f0-9]{64}$/.test(value.assessment_sha256) || !value.record || await computationDigest(value.record)!==value.assessment_sha256)throw Error("Assessment commitment differs.");
    const r=value.record;
    if(r.assessment_status!=="unreviewed_working_notes" || r.followup_status!=="unreviewed_user_proposal" || r.scientific_evidence_eligible!==false || r.action_recommendation_created!==false || typeof r.source_snapshot_json!=="string" || await computationTextDigest(r.source_snapshot_json)!==r.source_snapshot_sha256 || (source && canonicalJson(r.source)!==canonicalJson(source)) || (notes && canonicalJson(r.notes)!==canonicalJson(notes)))throw Error("Assessment source or notes differ.");
    const snapshot=JSON.parse(r.source_snapshot_json);if(canonicalJson(snapshot.source)!==canonicalJson(r.source) || snapshot.scientific_evidence_eligible!==false)throw Error("Assessment snapshot differs.");
    return value;
}
function showAssessment(value) {
    const r=value.record,snapshot=JSON.parse(r.source_snapshot_json);
    $("assessment-result").textContent="WORKING ASSESSMENT — unreviewed\nReference: "+value.assessment_sha256+"\nOriginal source question: "+snapshot.bundle.checked_draft.request.original_statement+"\n"+r.notice+"\n\nVERIFIED SOURCE SNAPSHOT\n"+(snapshot.outcome.comparison?snapshot.outcome.comparison+"\n":"")+readableWorkingOutcome(snapshot.bundle,snapshot.outcome.result,snapshot.outcome.failure || snapshot.outcome.refusal)+"\n\nUSER NOTES AND FOLLOW-UP PROPOSAL\n"+Object.entries(assessmentLabels).map(([field,label])=>label+"\n"+r.notes[field]).join("\n\n");
}
$("assessment-save").onclick=async()=>{
    if(assessmentBusy || !assessmentSource)return;const source=clone(assessmentSource),notes=assessmentNotes(),expected=assessmentRevision;
    const missing=Object.keys(notes).filter(field=>!notes[field] || notes[field]!==notes[field].trim() || notes[field].length>2000);
    if(missing.length){announce("assessment-status","Complete these fields without surrounding spaces: "+missing.map(field=>assessmentLabels[field]).join("; "));return;}
    assessmentBusy=true;assessmentControls();
    try {
        const value=await checkAssessment(await request("/api/assessment/save",{source,notes}),source,notes);
        if(expected!==assessmentRevision)return;assessmentSaved=value;showAssessment(value);announce("assessment-status","Result-bound working assessment saved. Follow-up remains an unreviewed user proposal; no evidence or action recommendation was created.");
    } catch(_){announce("assessment-status","Assessment save or source verification could not be confirmed. Keep the exact notes. Changed artifacts block verification; earlier saved versions remain.");}
    finally {assessmentBusy=false;assessmentControls();}
};
async function currentAssessment(target) {
    const value=await checkAssessment(await request("/api/assessment/inspect",{assessment_sha256:target.assessment_sha256}),target.record.source,target.record.notes);
    if(canonicalJson(value)!==canonicalJson(target))throw Error("Changed saved assessment.");return value;
}
$("assessment-download").onclick=async()=>{
    if(assessmentBusy || !assessmentSaved)return;const target=clone(assessmentSaved);assessmentBusy=true;assessmentControls();
    try {const value=await currentAssessment(target);download(JSON.stringify({format:"faraday-working-assessment-v1",assessment:value},null,2),"faraday-working-assessment.json");announce("assessment-status","Assessment report downloaded with exact source snapshot, uncertainty notes and unreviewed follow-up question.");}
    catch(_){assessmentSaved=null;$("assessment-result").textContent="Current assessment source verification failed. Earlier notes remain, but are not currently verified.";announce("assessment-status","Assessment download blocked: saved notes or current source artifacts could not be verified.");}
    finally {assessmentBusy=false;assessmentControls();}
};
$("assessment-file").addEventListener("change",async()=>{
    const file=$("assessment-file").files[0];if(!file || assessmentBusy)return;assessmentBusy=true;assessmentControls();
    try {
        if(file.size>1000000)throw Error();const item=JSON.parse(await file.text());if(item.format!=="faraday-working-assessment-v1")throw Error();
        const candidate=await checkAssessment(item.assessment),value=await currentAssessment(candidate);preserveAssessmentNotes();
        assessmentSource=clone(value.record.source);for(const field of Object.keys(assessmentLabels))$("assessment-"+field).value=value.record.notes[field];assessmentSaved=value;assessmentRevision++;
        const snapshot=JSON.parse(value.record.source_snapshot_json);$("assessment-source").textContent="Selected source question: "+snapshot.bundle.checked_draft.request.original_statement+". Reference: "+JSON.stringify(assessmentSource);
        showAssessment(value);announce("assessment-status","Saved assessment and its current source rechecked. Current notebook unchanged; prior assessment notes retained before replacement.");
    } catch(_){announce("assessment-status","Reopen failed. Keep the private report and its original result artifacts. Current notebook and assessment notes were not replaced.");}
    finally {assessmentBusy=false;assessmentControls();}
});
$("assessment-next").onclick=async()=>{
    if(assessmentBusy || !assessmentSaved || inquirySaving || hypothesisBusy || protocolBusy || draft.save_state==="pending"){announce("assessment-status","Finish or inspect the current scientific-record operation before staging another question.");return;}
    const target=clone(assessmentSaved);assessmentBusy=true;assessmentControls();
    try {
        const value=await currentAssessment(target),r=value.record,snapshot=JSON.parse(r.source_snapshot_json);
        download(JSON.stringify({format:"faraday-working-assessment-v1",assessment:value},null,2),"faraday-working-assessment.json");
        const candidate={...freshDraft(),statement:r.notes.followup_question,recording_notes:"Unreviewed follow-up proposed in working assessment "+value.assessment_sha256+".\nExact source: "+JSON.stringify(r.source)+"\nOriginal question: "+snapshot.bundle.checked_draft.request.original_statement,planning:{decision_change_criteria:r.notes.decision_change},kind:"non-evidentiary-rehearsal-draft",review_status:"unresolved",scientific_evidence_eligible:false};
        const serial=importSerial+1,raw=JSON.stringify(candidate);await prepareDraftImport({size:new Blob([raw]).size,text:async()=>raw});
        if(serial!==importSerial || !stagedImport)return;stagedNextQuestion=true;$("import-apply").textContent="Keep current copy and start proposed follow-up";
        announce("assessment-status","Follow-up question staged for review. The current notebook is unchanged. Choose Keep current copy and start proposed follow-up to retain it and prepare a new draft; Save inquiry remains a separate action.");$("import-apply").focus();
    } catch(_){announce("assessment-status","Follow-up staging blocked: the saved assessment or exact source could not be verified. Current notebook unchanged.");}
    finally {assessmentBusy=false;assessmentControls();}
};
assessmentControls();
portableControls();
renderDesignNotes();
function renderReviewContext() {
    $("reviewer-kind").value = draft.review_context.reviewer_kind;
    $("review-notes").value = draft.review_context.notes;
}
function renderPlanning() {
    $("planning-fields").replaceChildren();
    for(const item of planningFields) {
        if(!planningKeys.includes(item.field)) continue;
        const label=document.createElement("label"),input=document.createElement("textarea");
        input.id="planning-"+item.field;input.maxLength=2000;input.value=draft.planning[item.field] || "";
        input.setAttribute("aria-describedby","planning-help");label.setAttribute("for",input.id);label.textContent=item.text;
        input.addEventListener("input",()=>recordInput(()=>{draft.planning[item.field]=input.value;}));
        input.addEventListener("blur",finishEdit);
        $("planning-fields").append(label,input);
    }
}
renderReviewContext();
$("reviewer-kind").addEventListener("change", () => {
    finishEdit(); recordInput(() => {draft.review_context.reviewer_kind = $("reviewer-kind").value;}); finishEdit();
});
$("review-notes").addEventListener("input", () => recordInput(() => {draft.review_context.notes = $("review-notes").value;}));
$("review-notes").addEventListener("blur", finishEdit);
$("add").onclick = () => {
    clearErrors(); finishEdit();
    if (draft.rows.length >= 200) return;
    draft.history.push(snapshot());
    let number = draft.rows.length + 1;
    const existing = new Set(draft.rows.map(row => row.id));
    while (existing.has("pair-" + number)) number += 1;
    draft.rows.push({id: "pair-" + number, shade: "", sun: ""});
    invalidatePreview(); persist(); renderRows();
    $("pair-" + (draft.rows.length - 1) + "-id").focus();
    $("pair-status").textContent = "Added pair " + draft.rows.length + ".";
};
$("save").onclick = async () => {
    clearErrors();
    if (inquirySaving || draft.inquiry_id || draft.save_state === "pending") { savedStatus(); return; }
    const errors = questionErrors();
    if (errors.length) return showErrors(errors);
    draft.save_state = "pending";
    if (!persist()) {
        draft.save_state = "draft";
        return showErrors([{message: "Saving to Faraday was not attempted because the browser draft could not be retained. Download your draft and restore browser storage before saving."}]);
    }
    const statement = draft.statement;
    inquirySaving=true;
    $("save").disabled = true; $("statement").readOnly = true;
    $("saved").textContent = "Saving your inquiry…";
    try {
        const result = await request("/api/inquiry", {statement});
        draft.inquiry_id = result.inquiry_id; draft.saved_statement = result.original_statement;
        draft.save_state = "saved"; persist();
    } catch (_) {
        showErrors([{message: "The save could not be confirmed. It may have reached Faraday. Do not retry. Download your draft, then use “Check existing saved question” to inspect without writing. If no complete exact match is found, keep the draft and ask for help."}]);
    } finally { inquirySaving=false; savedStatus(); }
};
$("inspect-inquiry").onclick = async () => {
    clearErrors(); inspectedInquiry=null; $("link-inquiry").hidden=true;
    const errors=questionErrors();
    if(errors.length) return showErrors(errors);
    const expectedRevision=revision, statement=draft.statement;
    $("inspect-inquiry").disabled=true;
    announce("inspect-status","Checking the existing saved question without writing…");
    try {
        const result=await request("/api/inquiry/inspect",{statement,inquiry_id:draft.inquiry_id});
        if(expectedRevision!==revision) {
            announce("inspect-status","Draft changed during inspection. Check again before linking.");return;
        }
        if(result.canonical_write_performed!==false || result.review_status!=="unresolved" ||
            result.scientific_evidence_eligible!==false) throw Error("Invalid inspection.");
        if(result.status==="matching_complete" && result.original_statement===statement &&
            typeof result.inquiry_id==="string" && /^[a-z0-9][a-z0-9-]{0,95}$/.test(result.inquiry_id) &&
            typeof result.ledger_head_sha256==="string" && /^[a-f0-9]{64}$/.test(result.ledger_head_sha256)) {
            inspectedInquiry={...result,revision}; $("link-inquiry").hidden=false;
            announce("inspect-status","Exact question and seven open review questions found in "+result.inquiry_id+" with a valid ledger. Link explicitly to use this saved inquiry; this is not scientific approval.");
        } else announce("inspect-status","No complete exact match was established in the named or active inquiry. A partial save or another inquiry may exist. Retry remains blocked for uncertain saves; retain your draft for further inspection.");
    } catch (_) {
        announce("inspect-status","Inspection could not establish a saved question. Nothing was written. Keep your draft; do not retry an uncertain save.");
    } finally {$("inspect-inquiry").disabled=false;}
};
$("link-inquiry").onclick = () => {
    if(!inspectedInquiry || inspectedInquiry.revision!==revision) return;
    const match=inspectedInquiry;
    rememberBeforeEdit();
    draft.inquiry_id=match.inquiry_id; draft.saved_statement=match.original_statement; draft.save_state="saved";
    finishEdit();invalidatePreview();persist();savedStatus();
    announce("inspect-status","Draft linked to the inspected saved inquiry. No canonical write was performed; scientific decisions remain unresolved.");
};
$("planning-preview").onclick = async () => {
    const expected=revision;
    const errors=questionErrors();if(errors.length) return showErrors(errors);
    $("planning-preview").disabled=true;
    announce("planning-status","Checking planning questions without writing scientific records…");
    try {
        const result=await request("/api/planning",{statement:draft.statement,planning:clone(draft.planning)});
        if(expected!==revision) return;
        if(result.authority!=="review_only" || result.canonical_write_performed!==false ||
            result.analysis_performed!==false || result.scientific_evidence_eligible!==false ||
            result.original_statement!==draft.statement) throw Error("Invalid planning preview.");
        $("planning-unresolved").replaceChildren();$("planning-models").replaceChildren();
        for(const item of result.intake.clarifying_questions) {
            const li=document.createElement("li");li.textContent=item.text;$("planning-unresolved").append(li);
        }
        for(const item of result.competing_model_questions) {
            const li=document.createElement("li");li.textContent=item.question+" State a prediction and what would count against it.";$("planning-models").append(li);
        }
        announce("planning-status",result.intake.unresolved_fields.length+" unanswered intake questions. Prospective design, analysis specification and observation data remain unresolved. This preview does not approve a design, run an analysis or change the saved inquiry.");
    } catch (_) {
        if(expected===revision) announce("planning-status","Planning preview failed. Keep unknown answers blank; use unpadded text and one nonblank item per line for lists. Your draft is retained and no scientific record was changed.");
    } finally {$("planning-preview").disabled=false;}
};
$("preview").onclick = async () => {
    clearErrors();
    const prepared = measurementPayload();
    if (prepared.errors.length) return showErrors(prepared.errors);
    const expectedRevision = revision, serial = ++previewSerial;
    $("preview").disabled = true; $("results").setAttribute("aria-busy", "true");
    $("summary").textContent = "Calculating rehearsal differences…";
    try {
        const result = await request("/api/rehearsal", prepared.payload);
        showPreview(result, expectedRevision, serial);
    } catch (_) {
        if (expectedRevision === revision && serial === previewSerial) {
            $("summary").textContent = "No current rehearsal result is available.";
            showErrors([{message: "The rehearsal preview could not be calculated. Your draft remains available. Check the connection and try again."}]);
        }
    } finally {
        if (serial === previewSerial) {
            $("preview").disabled = false; $("results").setAttribute("aria-busy", "false");
        }
    }
};
$("export").onclick = () => {
    clearErrors();
    try {download(JSON.stringify(draftExport(), null, 2), "faraday-rehearsal-draft.json");}
    catch (_) {showErrors([{message: "The draft could not be downloaded. Keep this tab open until you can retain a copy."}]);}
};
function readableRehearsalReport(result) {
    const escape=value=>String(value).replace(/[&<>"']/g,character=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[character]));
    const note=(label,text)=>"<h2>"+escape(label)+"</h2><p>"+escape(text || "Not recorded; unresolved.").replace(/\n/g,"<br>")+"</p>";
    const list=items=>"<ul>"+items.map(text=>"<li>"+escape(text)+"</li>").join("")+"</ul>";
    const value=result.draft, arithmetic=result.arithmetic;
    return '<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">'+
        '<meta http-equiv="Content-Security-Policy" content="default-src \'none\'; base-uri \'none\'; form-action \'none\'">'+
        '<title>Faraday rehearsal report — not scientific evidence</title></head><body><main><h1>Private rehearsal report</h1>'+
        '<p><strong>Rehearsal only: made-up readings or attributed published-data replay. See source and transformation notes below. Scientific review unresolved. Not scientific evidence, a canonical scientific report, or a replication package.</strong></p>'+
        note("Your question",value.statement)+note("Prediction and surprises",value.prediction)+
        '<h2>Rehearsal readings</h2><table><caption>Surface temperature — degrees Celsius</caption><thead><tr><th scope="col">Pair</th><th scope="col">Shade °C</th><th scope="col">Sun °C</th></tr></thead><tbody>'+
        value.rows.map(row=>"<tr><td>"+escape(row.id)+"</td><td>"+escape(row.shade==="" ? "Missing" : row.shade)+"</td><td>"+escape(row.sun==="" ? "Missing" : row.sun)+"</td></tr>").join("")+"</tbody></table>"+
        '<h2>Descriptive rehearsal arithmetic</h2><p>Mean sun minus shade: '+escape(arithmetic.mean_difference_degC===null ? "Unavailable; no complete pairs" : displayTemperature(arithmetic.mean_difference_degC)+" °C")+
        ". Complete pairs: "+escape(arithmetic.complete_pairs)+". Differences displayed to two decimal places; stored values are unchanged.</p>"+
        list(arithmetic.differences.map(pair=>pair.id+": sun minus shade = "+displayTemperature(pair.sun_minus_shade_degC)+" °C"))+
        '<p>Incomplete pairs omitted from arithmetic: '+escape(arithmetic.incomplete_pair_ids.join(", ") || "None")+".</p>"+
        note("Limits",arithmetic.warning+" "+arithmetic.claim_ceiling+" No confidence interval or independent sample size was estimated.")+
        note("Recording notes: timing, missing readings and departures",value.recording_notes)+
        note("Reflection and next checks",value.reflection)+
        '<h2>Computational design working notes (not a frozen protocol)</h2>'+Object.entries(designLabels).map(([field,label])=>note(label,(value.design_notes || {})[field] || "")).join("")+
        '<h2>Hypothesis working notes (not approval)</h2>'+Object.entries(hypothesisLabels).map(([field,label])=>note(label,(value.hypothesis_notes || {})[field] || "")).join("")+
        '<h2>Other explanations to consider</h2>'+list(result.pathway.alternatives)+
        '<h2>Unresolved review decisions</h2>'+list(result.pathway.decisions.map(item=>item.id+" — UNRESOLVED: "+item.question))+
        note("Review contributor (unverified; review-only)",value.review_context ? value.review_context.reviewer_kind : "unassigned")+
        note("Unverified planning/review notes",value.review_context ? value.review_context.notes : "")+
        '<h2>Draft planning answers</h2>'+list(Object.entries(value.planning || {}).map(([field,text])=>field+": "+(text || "Unresolved")))+
        '<p>Earlier editing snapshots retained in the JSON draft: '+escape(value.history.length)+". Download the private JSON draft separately for recovery; this readable report is not an import file.</p>"+
        '<p>This report contains private draft notes. Review it before sharing and ask an adult for help if needed.</p>'+
        '<p>No canonical record was written by report generation. This download does not verify independent backup, reviewer identity, instrument validity or causality. Check the downloaded file before closing the notebook.</p></main></body></html>';
}
$("report").onclick = async () => {
    clearErrors();const prepared=measurementPayload();
    if(prepared.errors.length) return showErrors(prepared.errors);
    const expected=revision, input=draftExport();$("report").disabled=true;
    announce("report-status","Preparing the current private rehearsal report…");
    try {
        const result=await request("/api/rehearsal/report",input);
        if(expected!==revision) return;
        if(result.kind!=="non-evidentiary-rehearsal-report" || result.review_status!=="unresolved" ||
            result.scientific_evidence_eligible!==false || result.canonical_write_performed!==false ||
            result.independent_backup_verified!==false ||
            JSON.stringify(restoreDraft(result.draft))!==JSON.stringify(restoreDraft(input))) throw Error("Invalid report.");
        download(readableRehearsalReport(result),"faraday-rehearsal-report.html","text/html;charset=utf-8");
        announce("report-status","Readable rehearsal report download requested. Check the file before leaving. Scientific review remains unresolved; this is not scientific evidence.");
    } catch (_) {
        if(expected===revision) announce("report-status","Report generation failed. Your draft is retained. Finish invalid readings or download the JSON draft for recovery.");
    } finally {$("report").disabled=false;}
};
$("recover").hidden = recoveryBytes === null;
$("recover").onclick = () => {
    try {download(recoveryBytes, "faraday-unreadable-draft.json");}
    catch (_) {showErrors([{message: "The original draft could not be downloaded. Its stored bytes remain unchanged."}]);}
};
fetch("/api/pathway").then(response => {
    if (!response.ok) throw Error("Pathway unavailable.");
    return response.json();
}).then(pathway => {
    planningFields=pathway.planning_fields || [];renderPlanning();
    for (const text of pathway.alternatives) {
        const li = document.createElement("li"); li.textContent = text; $("alternatives").append(li);
    }
    for (const decision of pathway.decisions) {
        const li = document.createElement("li");
        li.textContent = decision.id + " — UNRESOLVED: " + decision.question;
        $("decisions").append(li);
    }
    $("pathway-status").textContent = "All " + pathway.decisions.length + " scientific decisions remain unresolved.";
    publishedExampleAvailable=pathway.published_example_available===true;
    $("published-example-stage").disabled=!publishedExampleAvailable;
    announce("published-example-status",publishedExampleAvailable ? "A local published example is available. Stage it to inspect its attribution before restoring; your current draft will be kept first." : "No local published example is available in this preview. Your own rehearsal and the synthetic cases are still available.");
}).catch(() => {
    $("pathway-status").textContent = "Review questions could not be loaded. Scientific review remains unresolved; real collection and evidence admission are unavailable.";
});
renderRows(); savedStatus();
if (bootIssue) showErrors([{message: bootIssue}]);
else $("draft-status").textContent = "Your notebook is ready.";

/* Norway autosave is a separate draft transport, never scientific admission. */
let norwayRevision = 0, norwayAck = "", norwayReady = false, norwaySaving = false;
let norwayTimer = null, norwayBlocked = false;
const syncKey = key + ":norway-sync";
function currentDraftBytes() { return JSON.stringify(restoreDraft(draft)); }
function canonicalJson(value) {
    const ordered=value=>Array.isArray(value)?value.map(ordered):value && typeof value==="object"?
        Object.fromEntries(Object.keys(value).sort().map(key=>[key,ordered(value[key])])):value;
    return JSON.stringify(ordered(value));
}
function acknowledgedDraftBytes(value) {return canonicalJson(restoreDraft(value));}
function rememberNorwayAck() {
    try { localStorage.setItem(syncKey, JSON.stringify({revision:norwayRevision, ack:norwayAck})); } catch (_) {}
}
function queueNorwaySave() {
    if (typeof window === "undefined" || !norwayReady || norwayBlocked) return;
    if (norwayTimer !== null) window.clearTimeout(norwayTimer);
    announce("draft-status", "Draft changed. Server autosave pending; keep this tab open until it confirms.");
    norwayTimer = window.setTimeout(() => {norwayTimer=null; saveNorwayDraft();}, 750);
}
async function saveNorwayDraft() {
    if (!norwayReady || norwayBlocked || norwaySaving) return;
    const bytes=currentDraftBytes(),expectedServerRevision=norwayRevision;
    if (bytes===norwayAck) return;
    norwaySaving=true;
    try {
        const result=await request("/api/draft/save", {expected_revision:expectedServerRevision,draft:JSON.parse(bytes)});
        if (!Number.isSafeInteger(result.revision) || result.revision!==expectedServerRevision+1 ||
            result.review_status!=="unresolved" || result.scientific_evidence_eligible!==false ||
            !result.draft || acknowledgedDraftBytes(result.draft)!==acknowledgedDraftBytes(JSON.parse(bytes)))
            throw Error("Draft acknowledgement did not retain the exact submitted scientific notes.");
        norwayRevision=result.revision; norwayAck=bytes; rememberNorwayAck();
        if (currentDraftBytes()===bytes) announce("draft-status", "Your notes are saved in Faraday.");
    } catch (error) {
        norwayBlocked=true;
        announce("draft-status", "Server autosave failed or conflicted. Your edits remain in this tab/browser. Download a copy, then use Retry server autosave.");
        $("retry-draft").hidden=false;
    } finally {
        norwaySaving=false;
        if (!norwayBlocked && currentDraftBytes()!==norwayAck) queueNorwaySave();
    }
}
function showRestoredDraft(value) {
    if(inquirySaving || hypothesisBusy || protocolBusy)throw Error("Wait for the scientific record operation before replacing its draft.");
    draft=restoreDraft(value); editingSnapshot=null; hypothesisUncertain=false; checkedHypothesis=null; checkedDesign=null; protocolUncertain=false;
    for (const field of textFields) $(field).value=draft[field];
    renderReviewContext();
    renderHypothesisNotes();
    renderDesignNotes();
    renderPlanning();
    renderRows(); savedStatus(); invalidatePreview();
    persist();
}
function editingEnabled(enabled) {
    workspaceEditingLocked=!enabled;renderWorkspace();
    for (const id of ["statement","prediction","reflection","recording_notes","reviewer-kind","review-notes","add","save","next-question","hypothesis-save","hypothesis-inspect","design-preview","protocol-draft-save","protocol-draft-inspect","preview","inspect-inquiry","link-inquiry","planning-preview","report"]) $(id).disabled=!enabled;
    for(const field of Object.keys(designLabels))if($("design-"+field))$("design-"+field).disabled=!enabled;
    for(const field of Object.keys(hypothesisLabels))if($("hypothesis-"+field))$("hypothesis-"+field).disabled=!enabled;
    for(const item of planningFields) {if($("planning-"+item.field)) $("planning-"+item.field).disabled=!enabled;}
    for (const input of document.querySelectorAll("#rows input")) input.disabled=!enabled;
    if (enabled) { $("add").disabled=draft.rows.length>=200; savedStatus(); }
}
async function recoverNorwayDraft(force=false) {
    if(inquirySaving || hypothesisBusy || protocolBusy) {
        announce("draft-status","Wait for the current inquiry save to finish before recovering a server draft. Your current question is unchanged.");return;
    }
    norwayReady=false; editingEnabled(false);
    announce("draft-status", "Checking server for a saved rehearsal draft…");
    try {
        const result=await request("/api/draft/load", {});
        if (!Number.isSafeInteger(result.revision) || result.revision<0 ||
            result.review_status!=="unresolved" || result.scientific_evidence_eligible!==false) throw Error("Invalid saved draft.");
        const server=result.draft===null ? null : restoreDraft(result.draft);
        const serverBytes=server===null ? "" : JSON.stringify(server);
        let meta=null;
        try { meta=JSON.parse(localStorage.getItem(syncKey)); } catch (_) {}
        const localBytes=currentDraftBytes();
        // An empty browser restores the server; a diverged browser is never silently replaced.
        if (server && (force || !hadLocalDraft || recoveryLocked ||
            localBytes===serverBytes || (meta && meta.ack===localBytes))) {
            showRestoredDraft(server);
            norwayAck=serverBytes;
        } else if (server && (!meta || meta.revision!==result.revision)) {
            norwayBlocked=true;
            $("restore-draft").hidden=false;
            throw Error("Different browser and server drafts need explicit recovery.");
        } else {
            norwayAck=serverBytes;
        }
        norwayRevision=result.revision; norwayReady=true; norwayBlocked=false;
        rememberNorwayAck();
        $("retry-draft").hidden=true; $("restore-draft").hidden=true;
        if (currentDraftBytes()!==norwayAck && (hadLocalDraft || revision>0)) queueNorwaySave();
        else announce("draft-status", server ? "Your saved notes are back. You can keep exploring." : "Your notes will save while you write.");
    } catch (_) {
        norwayBlocked=true;
        announce("draft-status", "Server draft recovery is unavailable or conflicted. Local edits were retained. Download a copy; retry to reconnect or explicitly restore the server's draft. If the server restarted, reload this page to reconnect; browser-saved edits will be retained.");
        $("retry-draft").hidden=false;
    } finally { editingEnabled(true); }
}
if (typeof window !== "undefined") {
    $("retry-draft").onclick=() => recoverNorwayDraft();
    $("restore-draft").onclick=async () => {
        try {
            // Retain a separate local copy before replacing any divergent browser draft.
            retainDraftCopy("conflict",JSON.stringify(draftExport()));
            download(JSON.stringify(draftExport(),null,2),"faraday-before-norway-restore.json");
            await recoverNorwayDraft(true);
        } catch (_) {
            showErrors([{message:"Could not retain your local draft. It was not replaced. Download it before recovering the server's version."}]);
        }
    };
    recoverNorwayDraft();
}

// Simulation artifacts use the registered executor and an isolated fixture service.
let simulationResult=null;
let nativeAttempted=false, nativeVerified=false, canonicalAttempted=false, canonicalVerified=false, canonicalReplayAllowed=false;
let savedSimulationReference=null, stagedSimulationReference=null;
const simulationReferenceKey=key+":saved-simulation-reference";
function simulationBusyState(value) {
    simulationBusy=value;computationControls();
    for(const id of ["simulation-case","simulation-prepare","simulation-run","simulation-verify","simulation-download","simulation-technical-download","simulation-canonical","simulation-resume","simulation-export","simulation-replay","simulation-reference-file","simulation-reference-apply","simulation-reference-download","simulation-reference-clear"]) $(id).disabled=value;
    if(!value) {
        $("simulation-run").disabled=!simulationPlan || nativeAttempted;
        $("simulation-verify").disabled=!simulationResult;
        $("simulation-download").disabled=!nativeVerified;$("simulation-technical-download").disabled=!nativeVerified;
        $("simulation-canonical").disabled=!simulationPlan || canonicalAttempted;
        $("simulation-resume").disabled=!savedSimulationReference;
        $("simulation-export").disabled=!canonicalVerified;
        $("simulation-replay").disabled=!canonicalVerified || !canonicalReplayAllowed;
        $("simulation-reference-apply").disabled=!stagedSimulationReference;
        $("simulation-reference-download").disabled=!savedSimulationReference;
        $("simulation-reference-clear").disabled=!savedSimulationReference;
    }
}
function resetSimulation() {
    simulationPlan=null;simulationResult=null;nativeAttempted=false;nativeVerified=false;canonicalAttempted=false;canonicalVerified=false;canonicalReplayAllowed=false;
    for(const id of ["simulation-design","simulation-result","simulation-identifiers","simulation-canonical-status","simulation-canonical-report","simulation-replay-status"]) $(id).textContent="";
}
// Render only the native report's headings, lists and inline emphasis as safe DOM.
// Source Markdown is retained unchanged by the service/export; raw HTML stays text.
function renderSavedSimulationReport(text) {
    const container=$("simulation-canonical-report");container.replaceChildren();
    const headings=[], stack=[];let paragraph=[];
    function inline(parent,value) {
        for(const part of value.split(/(\*\*[^*\n]+\*\*|`[^`\n]+`)/g)) {
            if(!part)continue;
            const bold=part.startsWith("**") && part.endsWith("**");
            const code=part.startsWith("`") && part.endsWith("`");
            const node=document.createElement(bold?"strong":code?"code":"span");
            node.textContent=bold?part.slice(2,-2):code?part.slice(1,-1):part;parent.append(node);
        }
    }
    function flush() {
        if(!paragraph.length)return;
        const node=document.createElement("p");inline(node,paragraph.join("\n"));container.append(node);paragraph=[];
    }
    for(const line of String(text).split(/\r?\n/)) {
        if(!line.trim()) {flush();stack.length=0;continue;}
        const heading=line.match(/^(#{1,6})\s+(.+)$/), item=line.match(/^(\s*)-\s+(.+)$/);
        if(heading) {
            flush();stack.length=0;
            const node=document.createElement("h"+Math.min(6,heading[1].length+2));
            node.id="simulation-report-heading-"+headings.length;node.tabIndex=-1;
            inline(node,heading[2]);container.append(node);headings.push(node);
        } else if(item) {
            flush();const indent=item[1].length;
            while(stack.length && stack[stack.length-1].indent>indent)stack.pop();
            if(!stack.length || stack[stack.length-1].indent<indent) {
                const list=document.createElement("ul");
                const parent=stack.length && stack[stack.length-1].lastItem ? stack[stack.length-1].lastItem : container;
                parent.append(list);stack.push({indent,list,lastItem:null});
            }
            const node=document.createElement("li");inline(node,item[2]);
            stack[stack.length-1].list.append(node);stack[stack.length-1].lastItem=node;
        } else {stack.length=0;paragraph.push(line);}
    }
    flush();
    if(headings.length) {
        const details=document.createElement("details"),summary=document.createElement("summary"),nav=document.createElement("nav"),list=document.createElement("ul");
        summary.textContent="Jump to a report section";nav.setAttribute("aria-label","Saved simulation report sections");
        for(const heading of headings) {
            const item=document.createElement("li"),link=document.createElement("a");
            link.textContent=heading.textContent;link.href="#"+heading.id;
            link.addEventListener("click",()=>heading.focus());item.append(link);list.append(item);
        }
        nav.append(list);details.append(summary,nav);
        // Insert navigation first without interpreting any report text as HTML.
        const content=Array.from(container.children);container.replaceChildren(details,...content);
    }
}
async function checkedSimulationDesign(value) {
    const design=value.design;
    if(!design || typeof design.specification_json!=="string" || typeof design.input_csv!=="string" ||
        design.specification_json.length>65536 || design.input_csv.length>65536)throw Error("Missing retained design.");
    const digest=async text=>[...new Uint8Array(await crypto.subtle.digest("SHA-256",new TextEncoder().encode(text)))].map(byte=>byte.toString(16).padStart(2,"0")).join("");
    const hashes=await Promise.all([digest(design.specification_json),digest(design.input_csv)]);
    if(hashes[0]!==value.recipe.specification_sha256 || hashes[1]!==value.recipe.input_sha256)throw Error("Design bytes differ from recipe.");
    const spec=JSON.parse(design.specification_json);
    const comparison = value.recipe.case === "comparison";
    const outcomeColumn = comparison ? "value" : "temperature";
    const groups = comparison ? ["first", "second"] : ["sun", "shade"];
    if(spec.method!=="independent_mean_difference_ci" || spec.study_design!=="independent_groups" ||
        spec.outcome_column!==outcomeColumn || spec.group_column!=="group" || spec.unit_column!=="unit" ||
        JSON.stringify(spec.groups)!==JSON.stringify(groups) ||
        spec.seed!==17 || spec.bootstrap_resamples!==1000 || spec.confidence_level!==0.95 ||
        ![undefined,"complete_case"].includes(spec.missing_data_policy))throw Error("Unsupported retained design.");
    if((value.recipe.case==="missing")!==(spec.missing_data_policy==="complete_case"))throw Error("Case and missingness rule differ.");
    const lines=design.input_csv.trimEnd().split("\n");
    if(lines.shift()!=="unit,group,"+outcomeColumn)throw Error("Unsupported input columns.");
    const rows=lines.map(line=>line.split(","));
    if(rows.length!==8 || rows.some(row=>row.length!==3 || !row[0] || !spec.groups.includes(row[1])) ||
        new Set(rows.map(row=>row[0])).size!==rows.length)throw Error("Invalid generated units.");
    return {spec,rows};
}
async function renderSimulationDesign(value) {
    const {spec,rows}=await checkedSimulationDesign(value);
    const container=$("simulation-design");container.replaceChildren();
    const heading=document.createElement("h3");heading.textContent="Look at these made-up temperatures";container.append(heading);
    const note=text=>{const p=document.createElement("p");p.textContent=text;container.append(p);};
    note("These numbers were made for this example. Compare the sunny and shaded readings. A reading marked Missing has no temperature recorded.");
    const region=document.createElement("div");region.className="table-scroll";region.tabIndex=0;region.setAttribute("role","region");region.setAttribute("aria-label","Example readings; scroll sideways if needed");
    const table=document.createElement("table"),caption=document.createElement("caption");caption.textContent=rows.length+" made-up readings — temperature in °C";table.append(caption);
    const head=document.createElement("thead"),tr=document.createElement("tr");
    for(const label of ["Reading","Place","Temperature °C"]){const th=document.createElement("th");th.setAttribute("scope","col");th.textContent=label;tr.append(th);}head.append(tr);table.append(head);
    const body=document.createElement("tbody");for(const row of rows){const tr=document.createElement("tr");for(const text of row){const td=document.createElement("td");td.textContent=text===""?"Missing":text;tr.append(td);}body.append(tr);}table.append(body);region.append(table);container.append(region);
    const details=document.createElement("details"),summary=document.createElement("summary"),technical=document.createElement("p");summary.textContent="More about these example numbers";
    technical.textContent="Signed contrast: mean sun temperature minus mean shade temperature, in degrees Celsius. Generated independent units; this does not establish independence of real observations. The "+(spec.confidence_level*100)+"% bootstrap interval uses "+spec.bootstrap_resamples+" resamples and seed "+spec.seed+". "+(spec.missing_data_policy==="complete_case"?"Incomplete rows are left out and reported; this does not explain why they are missing.":"Missing or invalid readings stop the calculation.")+" Input and specification bytes were checked against the retained recipe. This is software practice, without scientific approval or evidence.";
    details.append(summary,technical);container.append(details);
}
function simulationSummary(value) {
    const body=value.result.result, interval=body.confidence_interval;
    const excluded=body.exclusion_report ? body.exclusion_report.excluded_records.length : 0;
    const difference=body.mean_difference_first_minus_second;
    const result=difference===0?"The sunny and shaded averages are the same in this made-up example.":difference>0?"The sunny readings average "+displayTemperature(difference)+" °C more than the shaded readings in this made-up example.":"The shaded readings average "+displayTemperature(-difference)+" °C more than the sunny readings in this made-up example.";
    return result+"\nSunny average minus shaded average: "+displayTemperature(difference)+" °C."+
        "\nEstimated range for the sunny-minus-shaded difference: "+displayTemperature(interval.lower)+" to "+displayTemperature(interval.upper)+" °C. Different samples could give different answers. This estimated range depends on the calculation’s assumptions."+
        "\nReadings left out: "+excluded+(excluded ? ". The calculation skips missing readings; that may change the comparison." : ". All readings were used.")+
        "\nThese made-up numbers do not prove what happens in real places, or what caused a difference.";
}
function showSimulationReference() {
    $("simulation-saved-identifiers").textContent=savedSimulationReference ? Object.entries(savedSimulationReference).map(([field,value])=>field+": "+value).join("; ") : "No retained study reference.";
}
function retainSimulationReference(value) {
    savedSimulationReference=Object.fromEntries(["simulation_id","recipe_sha256","report_sha256","package_manifest_sha256"].map(field=>[field,value[field]]));
    showSimulationReference();
    try {
        retainDraftCopy("simulation-reference",JSON.stringify(savedSimulationReference));
        localStorage.setItem(simulationReferenceKey,JSON.stringify(savedSimulationReference));
        return true;
    } catch(error) {return false;}
}
try {
    const value=JSON.parse(localStorage.getItem(simulationReferenceKey));
    if(value && /^[a-f0-9]{32}$/.test(value.simulation_id) && ["recipe_sha256","report_sha256","package_manifest_sha256"].every(field=>/^[a-f0-9]{64}$/.test(value[field]))) {
        savedSimulationReference=value;
        announce("simulation-canonical-status","A saved simulation reference is available. Reopen to verify its current bytes; browser storage alone does not establish a valid result.");
    }
} catch(error) {}
showSimulationReference();
$("simulation-case").addEventListener("change",()=>{
    if(simulationBusy)return;
    resetSimulation();simulationBusyState(false);
    announce("simulation-status","You chose a different example. Select Look at the example data to see its readings. Earlier examples are kept.");
});
$("simulation-prepare").onclick=async()=>{
    if(simulationBusy)return;
    resetSimulation();simulationBusyState(true);
    announce("simulation-status","Getting the made-up example ready…");
    try {
        const value=await request("/api/simulation/prepare",{case:$("simulation-case").value});
        if(value.status!=="prepared" || value.recipe.case!==$("simulation-case").value || value.recipe.scientific_evidence_eligible!==false || value.canonical_write_performed!==false)throw Error("Invalid recipe.");
        await renderSimulationDesign(value);
        simulationPlan=value;$("simulation-identifiers").textContent="Recipe SHA-256: "+value.recipe_sha256;
        announce("simulation-status","The example is ready. Look at its readings, make your prediction, then choose Compare the temperatures.");
    } catch(error) {$("simulation-design").replaceChildren();announce("simulation-status","We could not get this example ready. Your notes are still here. Try again or ask an adult to help.");}
    finally {simulationBusyState(false);}
};
$("simulation-run").onclick=async()=>{
    if(!simulationPlan || simulationBusy || nativeAttempted)return;
    nativeAttempted=true;nativeVerified=false;simulationBusyState(true);
    announce("simulation-status","Comparing the example temperatures…");
    try {
        const value=await request("/api/simulation/run",{simulation_id:simulationPlan.simulation_id,recipe_sha256:simulationPlan.recipe_sha256});
        if(value.status!=="verified" || value.simulation_id!==simulationPlan.simulation_id || value.recipe_sha256!==simulationPlan.recipe_sha256 || value.scientific_evidence_eligible!==false || value.canonical_write_performed!==false)throw Error("Invalid result.");
        simulationResult=value;nativeVerified=true;$("simulation-result").textContent=simulationSummary(value);
        $("simulation-identifiers").textContent="Recipe SHA-256: "+value.recipe_sha256+". Receipt SHA-256: "+value.receipt_sha256;
        announce("simulation-status","The comparison is ready in step 4. What do you think the numbers tell you?");$("simulation-result").focus();
    } catch(error) {announce("simulation-status",simulationPlan.recipe.case==="invalid"?"This example has a broken reading, so no calculation is shown. Choose another example to keep exploring.":"We could not confirm this calculation. Your notes are still here. Choose another example, or ask an adult to help.");}
    finally {simulationBusyState(false);}
};
$("simulation-verify").onclick=async()=>{
    if(!simulationResult || simulationBusy)return;
    nativeVerified=false;simulationBusyState(true);
    try {
        const value=await request("/api/simulation/verify",{simulation_id:simulationResult.simulation_id,recipe_sha256:simulationResult.recipe_sha256,receipt_sha256:simulationResult.receipt_sha256});
        if(JSON.stringify(value)!==JSON.stringify(simulationResult))throw Error("Changed result.");
        nativeVerified=true;$("simulation-result").textContent=simulationSummary(value);
        announce("simulation-status","The saved example and calculation still match. These are made-up practice numbers.");
    } catch(error) {$("simulation-result").textContent="We could not check this result. Choose the example again to try a new calculation.";announce("simulation-status","We could not check the saved calculation, so downloading is paused. Your notes are still here. Choose the example again and compare it.");}
    finally {simulationBusyState(false);}
};
async function downloadSimulationNotes(technical=false){
    if(!nativeVerified || simulationBusy)return;
    const plan=simulationPlan,result=simulationResult,noteRevision=revision;
    const notes={question:draft.statement,prediction:draft.prediction,reflection:draft.reflection};
    await $("simulation-verify").onclick();
    if(!nativeVerified || plan!==simulationPlan || result!==simulationResult)return;
    simulationBusyState(true);
    try {
        const {spec,rows}=await checkedSimulationDesign(plan);
        if(plan!==simulationPlan || result!==simulationResult || !nativeVerified || noteRevision!==revision)throw Error("Changed selection or notes.");
        if(result.method!==spec.method || typeof result.implementation_sha256!=="string" ||
            !/^[a-f0-9]{64}$/.test(result.implementation_sha256) || !result.addon ||
            typeof result.addon.addon_id!=="string" || typeof result.addon.version!=="string" ||
            !result.environment || typeof result.environment.python!=="string" || typeof result.environment.platform!=="string")throw Error("Missing execution identity.");
        const text="MY SCIENCE NOTES — MADE-UP DATA PRACTICE\n\nMy question\n"+(notes.question || "Not written yet.")+"\n\nMy prediction\n"+(notes.prediction || "Not written yet.")+"\n\nWhat the example showed\n"+simulationSummary(result)+"\n\nWhat I think now and what I would try next\n"+(notes.reflection || "Not written yet.")+"\n\nSynthetic case: "+plan.recipe.case+"\n"+result.notice+
            "\n\nRETAINED DESIGN\nSigned contrast: mean "+spec.groups[0]+" minus mean "+spec.groups[1]+", in degrees Celsius."+
            "\nGenerated independent software units; no physical independence or causal claim."+
            "\nMissing-data rule: "+(spec.missing_data_policy || "no_missing_observations")+
            "\nConfidence level: "+spec.confidence_level+"; bootstrap resamples: "+spec.bootstrap_resamples+"; seed: "+spec.seed+
            "\nAssumptions: "+result.result.result.assumptions.join("; ")+
            "\n\nEXECUTION IDENTITY\nMethod: "+result.method+"; add-on: "+result.addon.addon_id+" "+result.addon.version+
            "\nImplementation SHA-256: "+result.implementation_sha256+
            "\nRecorded Python: "+result.environment.python+"; platform: "+result.environment.platform+
            "\nRecipe SHA-256: "+result.recipe_sha256+"\nReceipt SHA-256: "+result.receipt_sha256+
            "\nSpecification SHA-256: "+plan.recipe.specification_sha256+"\nInput SHA-256: "+plan.recipe.input_sha256+
            "\n\nEXACT ANALYSIS SPECIFICATION (UTF-8)\n"+plan.design.specification_json+
            "\n\nEXACT INPUT CSV (UTF-8; blank cells are missing)\n"+plan.design.input_csv+
            "\nREPLAY\nWith a matching Faraday installation, retain the exact specification and CSV bytes as analysis.json and input.csv. Verify their hashes and the method module hash against this report.\n"+
            "research analysis run --spec-file analysis.json --data-file input.csv --output replay --expect-spec-sha256 "+plan.recipe.specification_sha256+" --expect-input-sha256 "+plan.recipe.input_sha256+
            "\nCompare the signed estimate, interval and exclusions above. This is same-code numerical replay, not independent replication or complete environment verification.\n"+
            "This readable report is not the full native receipt or a scientific evidence package. Use Save a complete simulated study and its private package export to retain canonical fixture metadata and native outputs.\n";
        const readable=text.split("\n\nSynthetic case:")[0]+"\n\nExample readings (degrees Celsius)\n"+rows.map(row=>row.map(cell=>cell===""?"Missing":cell).join(" | ")).join("\n")+"\n\nThese readings were made up for practice. They cannot answer questions about real places.\n";
        download(technical?text:readable,technical?"faraday-reproducibility-details.txt":"faraday-simulation-report.txt","text/plain");
        announce("simulation-status","Your science notes were downloaded, including your question, prediction, example and thoughts. Keep the file private.");
    } catch(error) {
        nativeVerified=false;
        announce("simulation-status","We could not check these notes, so no file was saved. Your writing is still here. Choose an example again, compare it, then try saving.");
    } finally {simulationBusyState(false);}
}
$("simulation-download").onclick=()=>downloadSimulationNotes(false);
$("simulation-technical-download").onclick=()=>downloadSimulationNotes(true);

$("simulation-canonical").onclick=async()=>{
    if(!simulationPlan || simulationBusy || canonicalAttempted)return;
    canonicalAttempted=true;canonicalVerified=false;simulationBusyState(true);
    announce("simulation-canonical-status","Creating an isolated synthetic study through ResearchService…");
    try {
        const value=await request("/api/simulation/canonical",{simulation_id:simulationPlan.simulation_id,recipe_sha256:simulationPlan.recipe_sha256});
        if(value.canonical_write_performed!==true || !["completed","invalid"].includes(value.run_status) || value.package_verification.status!=="passed" || value.recipe_sha256!==simulationPlan.recipe_sha256 || value.status!=="canonical_fixture_recorded" || value.simulation_id!==simulationPlan.simulation_id || value.workspace_scope!=="isolated_synthetic_fixture" || value.scientific_evidence_eligible!==false || value.evidence_count!==0 || value.hypothesis_status!=="pending_review" || !value.ledger.valid)throw Error("Invalid fixture response.");
        renderSavedSimulationReport(value.report);canonicalVerified=true;canonicalReplayAllowed=value.run_status==="completed";
        const retained=retainSimulationReference(value);
        announce("simulation-canonical-status","Saved synthetic protocol, dataset, run and report. Run status: "+value.run_status+". Hypothesis pending review; scientific evidence records: 0. Ledger verified. Original inquiry unchanged."+(retained?"":" Browser reference retention failed; keep the exported package before closing."));
    } catch(error) {announce("simulation-canonical-status","Saved simulation failed or could not be confirmed. Partial records remain. Do not retry this recipe; prepare a fresh one. No scientific acceptance is inferred.");}
    finally {simulationBusyState(false);}
};
$("simulation-resume").onclick=async()=>{
    if(!savedSimulationReference || simulationBusy)return;
    canonicalVerified=false;simulationBusyState(true);
    try {
        const value=await request("/api/simulation/inspect",savedSimulationReference);
        if(value.simulation_id!==savedSimulationReference.simulation_id || value.recipe_sha256!==savedSimulationReference.recipe_sha256 || value.status!=="verified_canonical_fixture" || value.scientific_evidence_eligible!==false || value.report_sha256!==savedSimulationReference.report_sha256 || value.package_manifest_sha256!==savedSimulationReference.package_manifest_sha256)throw Error("Invalid read-back.");
        renderSavedSimulationReport(value.report);canonicalVerified=true;canonicalReplayAllowed=value.run_status==="completed";
        announce("simulation-canonical-status","Saved simulation report, run artifacts, ledger and redacted metadata package reverified. No canonical write was performed. Simulation only.");
    } catch(error) {$("simulation-canonical-report").textContent="";announce("simulation-canonical-status","Saved simulation could not be verified. Export blocked; retained files were not replaced.");}
    finally {simulationBusyState(false);}
};
$("simulation-export").onclick=async()=>{
    if(!savedSimulationReference || simulationBusy || !canonicalVerified)return;
    simulationBusyState(true);
    try {
        const value=await request("/api/simulation/export",savedSimulationReference);
        if(value.scientific_evidence_eligible!==false || value.filename!=="faraday-synthetic-study.zip")throw Error("Invalid export.");
        const bytes=Uint8Array.from(atob(value.archive_base64),character=>character.charCodeAt(0));
        const hash=[...new Uint8Array(await crypto.subtle.digest("SHA-256",bytes))].map(byte=>byte.toString(16).padStart(2,"0")).join("");
        if(hash!==value.archive_sha256)throw Error("Archive hash differs.");
        download(bytes,value.filename,"application/zip");
        showSimulationReference();$("simulation-saved-identifiers").textContent+="; last archive SHA-256: "+value.archive_sha256;
        announce("simulation-canonical-status","Private synthetic package downloaded after current-byte verification. Metadata is redacted; synthetic inputs and outputs are included separately. Not independent replication.");
    } catch(error) {canonicalVerified=false;announce("simulation-canonical-status","Export failed integrity checks. Nothing downloaded; retained files remain.");}
    finally {simulationBusyState(false);}
};
simulationBusyState(false);

$("simulation-replay").onclick=async()=>{
    if(!savedSimulationReference || simulationBusy || !canonicalVerified || !canonicalReplayAllowed)return;
    simulationBusyState(true);
    announce("simulation-replay-status","Replaying the retained synthetic inputs with the same registered method…");
    try {
        const value=await request("/api/simulation/replay",savedSimulationReference);
        if(value.status!=="replay_completed" || typeof value.matches!=="boolean" || value.scientific_evidence_eligible!==false || value.canonical_write_performed!==false)throw Error("Invalid replay response.");
        announce("simulation-replay-status",(value.matches?"Same-code numerical replay matched.":"Replay completed but differed; both outputs remain retained.")+" This is not independent replication or complete environment verification. Replay receipt: "+value.receipt_sha256);
    } catch(error) {announce("simulation-replay-status","Replay failed its execution or integrity checks. Retained study files were not replaced.");}
    finally {simulationBusyState(false);}
};

$("simulation-reference-download").onclick=()=>{
    if(!savedSimulationReference || simulationBusy)return;
    download(JSON.stringify({kind:"faraday-simulation-reference-v1",workspace_fingerprint:"__DRAFT_KEY__",reference:savedSimulationReference},null,2),"faraday-simulation-reference.json");
    announce("simulation-reference-status","Recovery reference downloaded. It points to local artifacts; it is not a scientific record, approval or a backup of the study data.");
};
$("simulation-reference-clear").onclick=()=>{
    if(!savedSimulationReference || simulationBusy)return;
    try {
        retainDraftCopy("simulation-reference-before-clear",JSON.stringify(savedSimulationReference));
        localStorage.setItem(simulationReferenceKey,"null");
    } catch(error) {announce("simulation-reference-status","Reference was not cleared because its previous copy could not be retained.");return;}
    savedSimulationReference=null;canonicalVerified=false;canonicalReplayAllowed=false;
    $("simulation-canonical-report").textContent="";showSimulationReference();simulationBusyState(false);
    announce("simulation-canonical-status","No saved simulation reference is selected in this browser. Retained local study files are unchanged.");
    announce("simulation-reference-status","Browser reference cleared; a previous reference copy and the local study artifacts remain. Load your recovery reference to reverify. Your question and rehearsal draft were not changed.");
};
async function prepareSimulationReferenceImport(file) {
    if(simulationBusy)return;
    stagedSimulationReference=null;simulationBusyState(true);
    try {
        if(!file || !Number.isSafeInteger(file.size) || file.size<1 || file.size>8192)throw Error("Reference size.");
        const raw=await file.text();if(typeof raw!=="string" || raw.length>8192)throw Error("Reference text.");
        const value=JSON.parse(raw);
        if(Object.keys(value).sort().join(",")!=="kind,reference,workspace_fingerprint" || value.kind!=="faraday-simulation-reference-v1" || value.workspace_fingerprint!=="__DRAFT_KEY__")throw Error("Wrong reference scope.");
        const ref=value.reference;
        if(!ref || Object.keys(ref).sort().join(",")!=="package_manifest_sha256,recipe_sha256,report_sha256,simulation_id" || !/^[a-f0-9]{32}$/.test(ref.simulation_id) || ["recipe_sha256","report_sha256","package_manifest_sha256"].some(field=>typeof ref[field]!=="string" || !/^[a-f0-9]{64}$/.test(ref[field])))throw Error("Invalid commitments.");
        stagedSimulationReference=clone(ref);
        announce("simulation-reference-status","Reference format and workspace checked. Nothing loaded or approved. Choose Keep current reference and verify selected study to inspect its retained bytes.");
    } catch(error) {announce("simulation-reference-status","Reference rejected. Choose this workspace's recovery-reference JSON up to 8 KiB. The current study reference is unchanged.");}
    finally {$("simulation-reference-file").value="";simulationBusyState(false);}
}
$("simulation-reference-file").addEventListener("change",()=>prepareSimulationReferenceImport($("simulation-reference-file").files[0]));
$("simulation-reference-apply").onclick=async()=>{
    if(!stagedSimulationReference || simulationBusy)return;
    const candidate=clone(stagedSimulationReference);simulationBusyState(true);
    try {
        const value=await request("/api/simulation/inspect",candidate);
        if(value.status!=="verified_canonical_fixture" || value.simulation_id!==candidate.simulation_id || value.recipe_sha256!==candidate.recipe_sha256 || value.report_sha256!==candidate.report_sha256 || value.package_manifest_sha256!==candidate.package_manifest_sha256 || value.scientific_evidence_eligible!==false)throw Error("Reference could not be verified.");
        if(savedSimulationReference)retainDraftCopy("simulation-reference-before-import",JSON.stringify(savedSimulationReference));
        const retained=retainSimulationReference(value);canonicalVerified=true;canonicalReplayAllowed=value.run_status==="completed";
        renderSavedSimulationReport(value.report);stagedSimulationReference=null;
        announce("simulation-canonical-status","Imported saved simulation reverified: current report, run outputs, ledger and metadata package checked. No canonical write was performed.");
        announce("simulation-reference-status","Imported reference reverified against current local study artifacts. No canonical write or scientific approval."+(retained?"":" Browser retention failed; keep the recovery file."));
    } catch(error) {announce("simulation-reference-status","Selected reference could not be verified. Previous reference and study artifacts were not replaced.");}
    finally {simulationBusyState(false);}
};

/* Question-led presentation reuses the same draft, history and service contracts. */
function workspaceLocked(){return workspaceEditingLocked || inquirySaving || hypothesisBusy || protocolBusy;}
function workspaceNotes(){return draft.workspace_notes || freshWorkspaceNotes();}
function recordWorkspaceInput(update){
    // Canvas selection/working labels are not the registered scientific design.
    // Keep checked computation/replay references when only these notes change.
    rememberBeforeEdit();update();invalidateHistory();persist();
}
function workspaceNotesText(value){
    const notes=value.workspace_notes || freshWorkspaceNotes();
    const labels={comparison_a:"First comparison group",comparison_b:"Second comparison group",model_input:"Model input",model_output:"Predicted model outcome",model_relation:"Proposed relation",source_supports:"Sources that might support",source_challenges:"Sources that might challenge",source_unclear:"Unclear source notes"};
    return "Approach: "+(notes.approach || "Not chosen")+"\n"+workspaceFields.filter(field=>notes[field]).map(field=>labels[field]+": "+notes[field]).join("\n");
}
function notebookNotesText(){
    const practice = $("practice-result")?.textContent;
    const practiceSection = practice ? "\n\nMade-up comparison\n" + Array.from($("practice-readings").children, line => line.textContent).join("\n") + "\n" + practice : "";
    const planning=Object.entries(draft.planning).filter(([,value])=>value).map(([field,value])=>field.replaceAll("_"," ")+": "+value).join("\n");
    return "MY INVESTIGATION NOTES\n\nMy question\n"+draft.statement+"\n\nMy explanation or prediction\n"+(draft.prediction || "Not recorded.")+"\n\nOther possibilities\n"+(draft.hypothesis_notes.competing_models || "Not recorded.")+"\n\nWhat would change my mind\n"+(draft.hypothesis_notes.falsification_conditions || "Not recorded.")+"\n\nWorkspace\n"+workspaceNotesText(draft)+"\n\nPlanning notes\n"+(planning || "Not recorded.")+"\n\nReflection and next question\n"+(draft.reflection || "Not recorded.")+practiceSection+"\n\nThese are unreviewed working notes. Source notes are unverified. Keep separately verified analysis and replay reports with their inputs.\n";
}
// The beginner comparison uses the registered executor with a fixed synthetic
// recipe. Notebook labels describe the practice groups without changing inputs.
function comparisonScope() {
    const notes = workspaceNotes();
    return JSON.stringify([draft.statement, notes.comparison_a, notes.comparison_b, draft.planning.outcome || ""]);
}

function renderPractice() {
    if (!$("practice-comparison")) return;
    const scope = comparisonScope();
    if (scope !== practiceScope) {
        practiceScope = scope;
        practicePlan = null;
        $("practice-readings").textContent = "";
        $("practice-result").textContent = "";
        announce("practice-status", "");
    }
    const locked = workspaceLocked() || practiceBusy;
    $("practice-comparison").hidden = workspaceNotes().approach !== "compare";
    $("practice-preview").disabled = locked;
    $("practice-run").disabled = locked || !practicePlan;
    $("practice-replay").disabled = locked || practiceReference?.scope !== scope;
}

async function preparePractice() {
    const plan = await request("/api/simulation/prepare", {case: "comparison"});
    if (plan.status !== "prepared" || plan.recipe.case !== "comparison" ||
        plan.canonical_write_performed !== false) throw Error("Unexpected recipe.");
    const {rows} = await checkedSimulationDesign(plan);
    return {plan, rows};
}

function practiceInputs(plan) {
    return {simulation_id: plan.simulation_id, recipe_sha256: plan.recipe_sha256};
}

function showPracticeReadings(rows) {
    const notes = workspaceNotes();
    const names = [notes.comparison_a || "First group", notes.comparison_b || "Second group"];
    $("practice-readings").replaceChildren();
    for (const [index, group] of ["first", "second"].entries()) {
        const line = document.createElement("p");
        line.textContent = names[index] + ": " + rows.filter(row => row[1] === group).map(row => row[2]).join(", ");
        $("practice-readings").append(line);
    }
}

async function practiceAction(action) {
    if (workspaceLocked() || practiceBusy) return;
    const scope = comparisonScope();
    practiceBusy = true;
    renderPractice();
    announce("practice-status", "Getting the comparison ready…");
    try {
        const previous = action === "replay" ? practiceReference : null;
        const original = previous && await request("/api/simulation/verify", previous.inputs);
        const prepared = action === "run" ? practicePlan : await preparePractice();
        if (!prepared || scope !== comparisonScope()) return;
        showPracticeReadings(prepared.rows);
        if (action === "preview") {
            practicePlan = prepared;
            $("practice-result").textContent = "";
            announce("practice-status", "What do you predict? Then choose Compare the averages.");
            return;
        }
        practicePlan = null;
        const result = await request("/api/simulation/run", practiceInputs(prepared.plan));
        if (scope !== comparisonScope()) return;
        if (result.status !== "verified" || result.scientific_evidence_eligible !== false ||
            result.recipe_sha256 !== prepared.plan.recipe_sha256 ||
            result.simulation_id !== prepared.plan.simulation_id) throw Error("Unexpected result.");
        const outcome = result.result.result;
        if (original && JSON.stringify(original.result.result) !== JSON.stringify(outcome)) {
            throw Error("Replay differs.");
        }
        const difference = outcome.mean_difference_first_minus_second;
        const notes = workspaceNotes();
        const first = notes.comparison_a || "First group";
        const second = notes.comparison_b || "Second group";
        const means = outcome.mean_by_group;
        const description = difference === 0 ? "The two averages are equal." :
            "The " + (difference > 0 ? "first" : "second") + " group averaged " +
            Math.abs(difference).toLocaleString() + " more.";
        $("practice-result").textContent = first + " average: " + means.first.toLocaleString() +
            ". " + second + " average: " + means.second.toLocaleString() + ". " +
            description + " This result describes only the made-up readings.";
        practiceReference = {scope, inputs: {...practiceInputs(result), receipt_sha256: result.receipt_sha256}};
        let retained = true;
        try {
            localStorage.setItem(practiceKey, JSON.stringify(practiceReference));
        } catch (error) {
            retained = false;
        }
        announce("practice-status", (original ? "The new calculation matched the saved result. " : "Comparison complete. ") +
            (retained ? "You can run it again from this notebook." : "Keep this tab open to run it again."));
    } catch (error) {
        if (scope === comparisonScope()) {
            announce("practice-status", "Faraday couldn’t finish that comparison. Show the made-up readings to start again.");
        }
    } finally {
        practiceBusy = false;
        renderPractice();
    }
}

function renderWorkspace(){
    if(!$("workspace-start"))return; // Older fixture/export clients remain supported.
    renderPractice();
    const notes=workspaceNotes(),opened=notes.open && Boolean(draft.statement.trim());
    $("workspace-shell").hidden=!opened;$("question-intro").hidden=opened;
    $("question").classList?.toggle("compact",opened);
    $("workspace-question-title").textContent=draft.statement;
    $("workspace-start").textContent=opened?"Continue investigation ↗":"Explore this question ↗";
    $("workspace-start").disabled=workspaceLocked();
    $("workspace-edit").textContent=draft.inquiry_id?"View original question":"Edit question";
    $("workspace-edit").disabled=workspaceLocked();
    $("workspace-save").disabled=workspaceLocked() || Boolean(draft.inquiry_id) || draft.save_state==="pending";
    announce("workspace-save-status",draft.inquiry_id?"Original question saved. Notebook notes continue to autosave.":draft.save_state==="pending"?"Save not yet confirmed. Open question recovery above before retrying.":"Your notebook autosaves. Save your question to begin a research record.");
    for(const approach of ["compare","track","model","sources"]){
        $("route-"+approach).setAttribute("aria-pressed",String(notes.approach===approach));
        $("route-"+approach).disabled=workspaceLocked();$("canvas-"+approach).hidden=notes.approach!==approach;
    }
    for(const field of workspaceFields){const el=$("workspace-"+field);if(el.value!==notes[field])el.value=notes[field];el.disabled=workspaceLocked();}
    for(const [id,value] of [["workspace-outcome",draft.planning.outcome || ""],["workspace-time",draft.planning.time_window || ""],["workspace-alternative",draft.hypothesis_notes.competing_models],["workspace-rethink",draft.hypothesis_notes.falsification_conditions]]){
        const el=$(id);if(el){if(el.value!==value)el.value=value;el.disabled=workspaceLocked();}
    }
    $("workspace-measurement").hidden=!["compare","track","model"].includes(notes.approach);
    $("workspace-comparison-summary").textContent=(notes.comparison_a || notes.comparison_b)?(notes.comparison_a || "First group")+" compared with "+(notes.comparison_b || "second group"):"";
    $("workspace-model-input-label").textContent=notes.model_input || "Your input";
    $("workspace-model-output-label").textContent=notes.model_output || "Your predicted outcome";
    const prompts={compare:"Keep selection, missingness and other group differences in view.",track:"Keep observation times and changing conditions in view.",model:"Which result would contradict your proposed relation?",sources:"Keep references, disagreements and uncertainty with each claim."};
    announce("workspace-status",prompts[notes.approach] || "Choose an approach. Your question stays in your words.");
    for(const id of ["workspace-plan","workspace-analysis","workspace-download","example-buses","example-model","example-shade"])$(id).disabled=workspaceLocked();
}
function openWorkspaceTools(targetId){
    if(workspaceLocked())return;
    renderPlanning();$("advanced-tools").open=true;
    const target=$(targetId);
    for(let parent=target?.parentElement;parent;parent=parent.parentElement)if(parent.tagName==="DETAILS")parent.open=true;
    target?.scrollIntoView?.({block:"start"});target?.focus();
}
async function stageWorkspaceExample(statement,approach){
    if(workspaceLocked())return;
    if(draft.save_state==="pending"){announce("workspace-example-status","Confirm the uncertain saved question before starting an example. Your notebook is unchanged.");return;}
    const next={...freshDraft(),statement,workspace_notes:{...freshWorkspaceNotes(),open:true,approach},kind:"non-evidentiary-rehearsal-draft",review_status:"unresolved",scientific_evidence_eligible:false};
    const raw=JSON.stringify(next);
    const serial=importSerial+1;
    await prepareDraftImport({size:new Blob([raw]).size,text:async()=>raw});
    if(serial!==importSerial || !stagedImport || stagedImport.statement!==statement)return;
    stagedNextQuestion=true;
    $("import-apply").textContent="Keep current copy and open example question";
    announce("workspace-example-status","Example question staged. Your current notebook stays unchanged until you keep a copy and open the example.");
    // The shared restore control must be reachable even before opening a workspace.
    $("import-apply").hidden=false;$("import-apply").focus();
}
if($("workspace-start")){
    $("workspace-save").onclick=()=>{if(!$("workspace-save").disabled)return $("save").onclick();};
    $("workspace-start").onclick=()=>{
        if(workspaceLocked())return;
        const errors=questionErrors();if(errors.length){showErrors(errors);return;}
        finishEdit();recordWorkspaceInput(()=>{draft.workspace_notes={...workspaceNotes(),open:true};});finishEdit();
        $("workspace").scrollIntoView?.({block:"start"});
    };
    $("workspace-edit").onclick=()=>{if(workspaceLocked())return;finishEdit();recordWorkspaceInput(()=>{draft.workspace_notes={...workspaceNotes(),open:false};});finishEdit();$("statement").focus();};
    for(const approach of ["compare","track","model","sources"])$("route-"+approach).onclick=()=>{
        if(workspaceLocked())return;finishEdit();recordWorkspaceInput(()=>{draft.workspace_notes={...workspaceNotes(),approach};});finishEdit();
    };
    for(const field of workspaceFields){const input=$("workspace-"+field);input.addEventListener("input",()=>{if(workspaceLocked())return;recordWorkspaceInput(()=>{draft.workspace_notes={...workspaceNotes(),[field]:input.value};});});input.addEventListener("blur",finishEdit);}
    for(const [id,group,field] of [["workspace-outcome","planning","outcome"],["workspace-time","planning","time_window"],["workspace-alternative","hypothesis_notes","competing_models"],["workspace-rethink","hypothesis_notes","falsification_conditions"]]){
        const input=$(id);input.addEventListener("input",()=>{if(workspaceLocked())return;recordInput(()=>{draft[group][field]=input.value;});});input.addEventListener("blur",finishEdit);
    }
    $("workspace-plan").onclick=()=>openWorkspaceTools("plan");
    $("workspace-analysis").onclick=()=>openWorkspaceTools("computation-spec");
    $("workspace-download").onclick=()=>{if(workspaceLocked())return;download(notebookNotesText(),"faraday-investigation-notes.txt","text/plain");announce("workspace-download-status","Notebook notes downloaded.");};
    $("example-buses").onclick=()=>stageWorkspaceExample("Are buses getting less reliable?","track");
    $("example-model").onclick=()=>stageWorkspaceExample("How does a pendulum’s length change its swing?","model");
    $("example-shade").onclick=()=>stageWorkspaceExample("Does shade change surface temperature?","compare");
    renderWorkspace();
}

if ($("practice-comparison")) {
    $("practice-preview").onclick = () => practiceAction("preview");
    $("practice-run").onclick = () => practiceAction("run");
    $("practice-replay").onclick = () => practiceAction("replay");
    renderPractice();
}
