// Non-rendering interaction checks using JavaScriptCore via macOS JXA.
// No browser, application automation, network, or persistent draft state is used.
function run(argv) {
    ObjC.import("Foundation");
    const source = ObjC.unwrap($.NSString.stringWithContentsOfFileEncodingError(argv[0], $.NSUTF8StringEncoding, null));
    if (typeof source !== "string") throw Error("Could not read notebook client.");
    const checks = [];
    function check(name, test) {
        test(); checks.push(name);
    }
    function assert(value, message) { if (!value) throw Error(message); }
    function equal(left, right, message) {
        assert(JSON.stringify(left) === JSON.stringify(right), message || "Values differ.");
    }
    function throws(callback) { let failed = false; try { callback(); } catch (_) {failed = true;} assert(failed, "Expected invalid draft rejection."); }
    function boot(saved, storageFailure) {
        const elements = {}, downloads = [], writes = [], calls = [];
        const stored = new Map();
        let active = null, lastBlob = null;
        class Element {
            constructor(tag) { this.tagName = tag; this.children = []; this.attributes = {}; this.listeners = {}; this.value = ""; this.id = ""; this.hidden = false; this.disabled = false; this.readOnly = false; this._text = ""; }
            set textContent(value) { this.textWrites = (this.textWrites || 0) + 1; this._text = value; this.children = []; }
            get textContent() { return this._text + this.children.map(child => child.textContent).join(""); }
            append(...nodes) { for (const node of nodes) {node.parent = this; this.children.push(node);} }
            replaceChildren(...nodes) { this.children = []; this._text = ""; this.append(...nodes); }
            setAttribute(name, value) { this.attributes[name] = value; }
            removeAttribute(name) { delete this.attributes[name]; }
            addEventListener(name, callback) { (this.listeners[name] ||= []).push(callback); }
            dispatch(name) { for (const callback of this.listeners[name] || []) callback({}); }
            focus() { active = this; }
            click() { if (this.tagName === "a") downloads.push({name: this.download, content: lastBlob}); }
            remove() { if (this.parent) this.parent.children = this.parent.children.filter(child => child !== this); }
        }
        const body = new Element("body");
        for (const id of ["error", "draft-status", "recover", "statement", "prediction", "reflection", "recording_notes",
            "question-save-message", "simulation-to-design", "simulation-to-design-status", "assessment-fields", "assessment-source", "assessment-save", "assessment-download", "assessment-next", "assessment-file", "assessment-status", "assessment-result", "computation-assess", "portable-assess-source", "portable-assess-replay", "computation-portable-download", "portable-cancel", "portable-file", "portable-restore", "portable-replay", "portable-download", "portable-report", "portable-status", "portable-result", "computation-method", "computation-method-status", "computation-spec", "computation-data", "computation-provenance", "computation-prepare", "computation-run", "computation-download", "computation-reopen", "computation-status", "computation-result", "protocol-draft-save", "protocol-draft-inspect", "protocol-draft-status", "protocol-draft-result", "design-fields", "design-preview", "design-status", "design-result", "hypothesis-fields", "hypothesis-save", "hypothesis-inspect", "hypothesis-status", "hypothesis-saved", "save", "saved", "next-question", "next-question-status", "published-example-stage", "published-example-status", "inspect-inquiry", "inspect-status", "link-inquiry", "rows", "add", "preview", "results", "summary", "differences", "reviewer-kind", "review-notes",
            "simulation-reference-file", "simulation-reference-apply", "simulation-reference-download", "simulation-reference-clear", "simulation-reference-status", "simulation-saved-identifiers", "simulation-replay", "simulation-replay-status", "simulation-resume", "simulation-export", "simulation-canonical", "simulation-canonical-status", "simulation-canonical-report", "simulation-identifiers", "simulation-case", "simulation-prepare", "simulation-run", "simulation-verify", "simulation-download", "simulation-technical-download", "simulation-status", "simulation-design", "simulation-result", "history-review", "history-status", "history-controls", "history-select", "history-content", "export", "report", "report-status", "import-file", "import-apply", "import-status", "planning-fields", "planning-preview", "planning-status", "planning-unresolved", "planning-models", "pathway-status", "alternatives", "decisions", "pair-status", "workspace-start", "workspace-save", "workspace-save-status", "workspace", "workspace-shell", "question-intro", "question", "workspace-question-title", "workspace-edit", "workspace-status", "workspace-measurement", "workspace-comparison-summary", "workspace-model-input-label", "workspace-model-output-label", "workspace-outcome", "workspace-time", "workspace-alternative", "workspace-rethink", "workspace-plan", "workspace-analysis", "workspace-download", "workspace-download-status", "example-buses", "example-model", "example-shade", "workspace-example-status", "advanced-tools", "plan", "route-compare", "route-track", "route-model", "route-sources", "canvas-compare", "canvas-track", "canvas-model", "canvas-sources", "workspace-comparison_a", "workspace-comparison_b", "workspace-model_input", "workspace-model_output", "workspace-model_relation", "workspace-source_supports", "workspace-source_challenges", "workspace-source_unclear"]) {
            const element = new Element("div"); element.id = id; elements[id] = element; body.append(element);
        }
        const all = () => {
            const result = [];
            function visit(element) {result.push(element); for (const child of element.children) visit(child);}
            visit(body); return result;
        };
        const document = {
            body,
            getElementById: id => all().find(element => element.id === id) || null,
            createElement: tag => new Element(tag),
            querySelectorAll: () => all().filter(element => element.attributes["aria-invalid"] === "true")
        };
        const storageKey = "faraday-shade-rehearsal-v1:__DRAFT_KEY__";
        if (saved !== undefined) stored.set(storageKey, saved);
        const localStorage = {
            getItem: key => stored.has(key) ? stored.get(key) : null,
            setItem: (key, value) => {
                if (storageFailure) throw Error("Quota exceeded");
                stored.set(key, value); writes.push(value);
            }
        };
        // Synchronous fixture chain only for the initial read-only pathway request.
        function chain(value, failure) {
            return {
                then: callback => {if (failure) return chain(null, failure); try {return chain(callback(value), null);} catch (error) {return chain(null, error);}},
                catch: callback => {if (failure) callback(failure); return chain(value, null);}
            };
        }
        const fetch = (path, options) => {
            calls.push({path, options});
            return chain({ok: true, json: () => ({alternatives:["A competing explanation"],
                decisions:[{id:"instrument",question:"Choose instrument."}]})}, null);
        };
        class BlobFixture { constructor(parts) { lastBlob = parts.join(""); this.size=unescape(encodeURIComponent(lastBlob)).length; } }
        const url = {createObjectURL: () => "blob:fixture", revokeObjectURL: () => {}};
        const create = new Function("document", "localStorage", "fetch", "URL", "Blob", "setTimeout",
            source + "\nreturn {readableWorkingOutcome, renderSavedSimulationReport, prepareSimulationReferenceImport, prepareDraftImport, applyDraftImport, getDraft:()=>draft, restoreDraft, recordInput, measurementPayload, questionErrors, showErrors, clearErrors, renderRows, showPreview, draftExport, persist, getRevision:()=>revision, setSerial:value=>{previewSerial=value;}};");
        const api = create(document, localStorage, fetch, url, BlobFixture, callback => callback());
        return {api, elements, document, writes, calls, downloads, stored, storageKey,
            active: () => active,
            input: (id, value) => {const element = document.getElementById(id); element.value = value; element.dispatch("input");},
            saved: () => JSON.parse(stored.get(storageKey))};
    }
    check("syntax-and-initial-review-boundary", () => {
        const ui = boot();
        assert(ui.elements["pathway-status"].textContent.includes("unresolved"), "Review status missing.");
        equal(ui.writes.length, 0, "Opening a draft must not write browser storage.");
        equal(ui.calls.map(call => call.path), ["/api/pathway"], "Unexpected initial network request.");
    });
    check("typing-saves-before-blur-and-retains-original-edit", () => {
        const ui = boot();
        ui.input("statement", "First");
        equal(ui.saved().statement, "First", "Typing was not immediately saved.");
        ui.input("statement", "First question?");
        equal(ui.saved().statement, "First question?");
        equal(ui.saved().history[0].statement, "");
        equal(ui.saved().history.length, 1);
        ui.elements.statement.dispatch("blur");
        ui.input("statement", "Changed question?");
        equal(ui.saved().history[1].statement, "First question?");
        const resumed = boot(JSON.stringify(ui.saved()));
        equal(resumed.elements.statement.value, "Changed question?", "Restart lost latest typing.");
    });
    check("readings-retain-incomplete-numeric-input", () => {
        const ui = boot();
        ui.input("pair-0-shade", "1e");
        equal(ui.saved().rows[0].shade, "1e", "Invalid input was silently converted to missing.");
        const prepared = ui.api.measurementPayload();
        equal(prepared.errors[0].field, "pair-0-shade");
        ui.input("pair-0-shade", "-3.5"); ui.input("pair-0-sun", "");
        equal(ui.api.measurementPayload().payload.rows, [{id:"pair-1",shade:-3.5,sun:null}]);
    });
    check("duplicate-label-errors-focus-and-association", () => {
        const ui = boot();
        ui.elements.add.onclick();
        ui.input("pair-1-id", "pair-1");
        const errors = ui.api.measurementPayload().errors;
        equal(errors[0].field, "pair-1-id");
        ui.api.showErrors(errors);
        equal(ui.active().id, "error", "Error summary did not receive focus.");
        equal(ui.document.getElementById("pair-1-id").attributes["aria-invalid"], "true");
        assert(ui.document.getElementById("pair-1-id").attributes["aria-describedby"].includes("error"), "Error is not associated with input.");
        ui.api.clearErrors();
        assert(ui.elements.error.hidden, "Old error remained visible.");
    });
    check("new-pair-label-does-not-collide-and-focus-moves", () => {
        const ui = boot();
        ui.input("pair-0-id", "pair-2"); ui.elements.add.onclick();
        equal(ui.saved().rows.map(row => row.id), ["pair-2", "pair-3"]);
        equal(ui.active().id, "pair-1-id");
        assert(ui.document.getElementById("pair-1-shade").attributes["aria-label"].includes("degrees Celsius"), "Reading label lacks measurement unit.");
    });
    check("stale-preview-cannot-overwrite-new-edits", () => {
        const ui = boot();
        const revision = ui.api.getRevision(); ui.api.setSerial(1);
        const result = {incomplete_pair_ids:[], mean_difference_degC:5, complete_pairs:1,
            differences:[{id:"pair-1",sun_minus_shade_degC:5}]};
        assert(ui.api.showPreview(result, revision, 1), "Current result rejected.");
        ui.input("pair-0-shade", "99");
        assert(!ui.api.showPreview(result, revision, 1), "Stale result was accepted.");
        assert(ui.elements.summary.textContent.includes("Recalculate"), "Stale result remained visible.");
        equal(ui.elements.differences.children.length, 0);
    });
    check("display-rounding-preserves-arithmetic-and-draft", () => {
        const ui = boot(); ui.api.setSerial(1);
        const before = JSON.stringify(ui.api.draftExport());
        const result = {incomplete_pair_ids:[], mean_difference_degC:1.23456789, complete_pairs:2,
            differences:[{id:"a",sun_minus_shade_degC:1.23456789},{id:"b",sun_minus_shade_degC:-1e-12}]};
        const arithmetic = JSON.stringify(result);
        ui.api.showPreview(result, 0, 1);
        assert(ui.elements.summary.textContent.includes("1.23 °C"), "Mean formatting missing.");
        equal(ui.elements.differences.children.map(item=>item.textContent), ["a: 1.23 °C", "b: 0.00 °C"]);
        equal(JSON.stringify(result), arithmetic, "Display changed arithmetic.");
        equal(JSON.stringify(ui.api.draftExport()), before, "Display changed stored draft.");
    });
    check("historical-values-are-readable-without-restoring-or-writing", () => {
        const ui=boot();
        ui.elements["history-review"].onclick();
        assert(ui.elements["history-status"].textContent.includes("No earlier"), "Empty history was not explained.");
        ui.input("statement","<script>earlier question</script>");ui.elements.statement.dispatch("blur");
        ui.input("pair-0-shade","1e");ui.document.getElementById("pair-0-shade").dispatch("blur");
        ui.input("recording_notes","Earlier timezone unknown");ui.elements.recording_notes.dispatch("blur");
        ui.input("pair-0-shade","25");
        const before=JSON.stringify(ui.api.draftExport()), writes=ui.writes.length, calls=ui.calls.length;
        ui.elements["history-review"].onclick();
        const text=ui.elements["history-content"].textContent;
        assert(text.includes("<script>earlier question</script>"), "Literal question missing.");
        assert(text.includes("1e"), "Unfinished raw value was coerced.");
        assert(text.includes("Earlier timezone unknown"), "Original context missing.");
        equal(JSON.stringify(ui.api.draftExport()),before,"Browsing changed the draft.");
        equal(ui.writes.length,writes,"Browsing wrote storage.");equal(ui.calls.length,calls,"Browsing made a request.");
        equal(ui.active().id,"history-select");
        ui.input("reflection","A later edit");
        assert(ui.elements["history-controls"].hidden,"A stale selection stayed available.");
        equal(ui.elements["history-content"].children.length,0);
    });
    check("saved-report-exposes-safe-headings-lists-and-section-navigation", () => {
        const ui=boot(),before=JSON.stringify(ui.api.draftExport()),writes=ui.writes.length,calls=ui.calls.length;
        ui.api.renderSavedSimulationReport("# Synthetic report\n\n## Pending human review\n\n**Status:** `pending_review`\n\n- Main limitation\n  - Nested limitation\n\n<img src=x onerror=alert(1)>");
        const all=[];function visit(node){all.push(node);for(const child of node.children)visit(child);}
        visit(ui.elements["simulation-canonical-report"]);
        equal(all.filter(node=>/^h[1-6]$/.test(node.tagName)).map(node=>node.tagName),["h3","h4"]);
        assert(all.some(node=>node.tagName==="ul") && all.some(node=>node.tagName==="strong") && all.some(node=>node.tagName==="code"),"Semantic content missing.");
        assert(!all.some(node=>node.tagName==="img"),"Report text was interpreted as HTML.");
        const links=all.filter(node=>node.tagName==="a");
        assert(links.every(node=>/^#simulation-report-heading-\d+$/.test(node.href)),"External or unsafe report navigation.");
        links[1].dispatch("click");equal(ui.active().id,"simulation-report-heading-1");
        equal(JSON.stringify(ui.api.draftExport()),before);equal(ui.writes.length,writes);equal(ui.calls.length,calls);
    });
    check("all-incomplete-pairs-still-disclose-omitted-labels", () => {
        const ui = boot(); ui.api.setSerial(1);
        ui.api.showPreview({mean_difference_degC:null, incomplete_pair_ids:["pair-1"], differences:[]}, 0, 1);
        assert(ui.elements.summary.textContent.includes("pair-1"), "Omitted labels were hidden.");
    });
    check("unreadable-draft-is-not-overwritten-and-can-be-downloaded", () => {
        for (const raw of ["{bad", JSON.stringify({rows:[null],history:[]})]) {
            const ui = boot(raw);
            assert(!ui.elements.recover.hidden, "Recovery action unavailable.");
            ui.input("statement", "New session-only wording");
            equal(ui.stored.get(ui.storageKey), raw, "Unreadable bytes were overwritten.");
            ui.elements.recover.onclick();
            equal(ui.downloads[0].content, raw, "Recovery changed original bytes.");
            ui.elements.export.onclick();
            equal(JSON.parse(ui.downloads[1].content).statement, "New session-only wording");
        }
    });
    check("malformed-draft-history-and-inquiry-reference-rejected", () => {
        const ui = boot();
        const value = ui.api.getDraft();
        throws(() => ui.api.restoreDraft({...value,history:[null]}));
        throws(() => ui.api.restoreDraft({...value,inquiry_id:"../../other"}));
        throws(() => ui.api.restoreDraft({...value,save_state:"approved"}));
    });
    check("untrusted-authority-flags-are-discarded-on-restore-and-export", () => {
        const initial = boot().api.getDraft();
        const ui = boot(JSON.stringify({...initial,review_status:"approved",
            scientific_evidence_eligible:true,kind:"scientific-evidence"}));
        const result = ui.api.draftExport();
        equal(result.review_status, "unresolved");
        equal(result.scientific_evidence_eligible, false);
        equal(result.kind, "non-evidentiary-rehearsal-draft");
        assert(!Object.hasOwn(ui.api.getDraft(), "review_status"), "Injected review flag was retained.");
    });
    check("legacy-numeric-draft-restores-without-coercing-missing-values", () => {
        const value = boot().api.getDraft();
        delete value.save_state; delete value.saved_statement;
        value.rows = [{id:"legacy",shade:20,sun:null}];
        const ui = boot(JSON.stringify(value));
        equal(ui.elements.statement.value, "");
        equal(ui.api.measurementPayload().payload.rows, [{id:"legacy",shade:20,sun:null}]);
    });
    check("ambiguous-save-blocks-blind-retry-on-resume", () => {
        const value = boot().api.getDraft(); value.save_state = "pending";
        const ui = boot(JSON.stringify(value));
        assert(ui.elements.save.disabled, "An ambiguous save can be retried.");
        assert(ui.elements.saved.textContent.includes("Do not retry"), "Recovery instructions missing.");
        assert(ui.elements.saved.textContent.includes("Check existing saved question"), "In-app recovery route missing.");
    });
    check("saved-original-is-read-only-and-not-saved-twice", () => {
        const value = boot().api.getDraft();
        value.inquiry_id = "test-inquiry"; value.saved_statement = "Original question?";
        value.statement = "Original question?"; value.save_state = "saved";
        const ui = boot(JSON.stringify(value));
        assert(ui.elements.save.disabled && ui.elements.statement.readOnly, "Original question can be rewritten or duplicated.");
    });
    check("storage-quota-failure-keeps-latest-input-and-warns", () => {
        const ui = boot(undefined, true);
        ui.input("statement", "Unsaved latest wording");
        equal(ui.api.getDraft().statement, "Unsaved latest wording");
        assert(ui.elements["draft-status"].textContent.includes("Download"), "Quota failure has no recovery instruction.");
        equal(ui.writes.length, 0);
    });

    check("unchanged-autosave-status-does-not-repeat-live-region-mutations", () => {
        const ui = boot();
        ui.input("statement", "A");
        const savedWrites = ui.elements["draft-status"].textWrites;
        const resultWrites = ui.elements.summary.textWrites;
        ui.input("statement", "A question");
        equal(ui.elements["draft-status"].textWrites, savedWrites, "Autosave repeats the same live-region message.");
        equal(ui.elements.summary.textWrites, resultWrites, "Each keystroke repeats the same result warning.");
        equal(ui.saved().statement, "A question", "Suppressing announcements suppressed autosave.");
    });
    check("private-export-preserves-current-input-and-earlier-edit", () => {
        const ui = boot(); ui.input("statement", "Download this question?");
        ui.elements.export.onclick();
        equal(ui.downloads[0].name, "faraday-rehearsal-draft.json");
        const result = JSON.parse(ui.downloads[0].content);
        equal(result.statement, "Download this question?");
        equal(result.history[0].statement, "");
        equal(result.review_status, "unresolved");
        equal(result.scientific_evidence_eligible, false);
    });
    check("question-first-workspace-retains-literal-question-and-every-approach", () => {
        const ui=boot(); const question="Why do some train journeys take longer?";
        ui.input("statement",question);ui.elements["workspace-start"].onclick();
        equal(ui.elements["workspace-question-title"].textContent,question);
        equal(ui.saved().workspace_notes.open,true);equal(ui.saved().workspace_notes.approach,"");
        ui.elements["route-track"].onclick();ui.input("workspace-time","Week by week");ui.input("workspace-outcome","Journey time in minutes");
        ui.elements["route-model"].onclick();ui.input("workspace-model_input","Service frequency");ui.input("workspace-model_output","Journey duration");
        ui.elements["route-sources"].onclick();ui.input("workspace-source_unclear","A quoted claim still needs checking.");
        equal(ui.saved().planning.time_window,"Week by week");equal(ui.saved().planning.outcome,"Journey time in minutes");
        const resumed=boot(JSON.stringify(ui.saved()));
        equal(resumed.elements["workspace-question-title"].textContent,question);
        equal(resumed.elements["workspace-model_input"].value,"Service frequency");
        equal(resumed.elements["canvas-sources"].hidden,false);equal(resumed.elements["canvas-track"].hidden,true);
        resumed.elements["workspace-download"].onclick();const report=resumed.downloads[0];
        equal(report.name,"faraday-investigation-notes.txt");
        for(const text of [question,"Week by week","Service frequency","quoted claim","unreviewed working notes"])assert(report.content.includes(text),"Notebook report omitted retained context.");
        equal(resumed.api.getDraft().inquiry_id,null);assert(!report.content.includes("SHA-256"),"Simple notebook requires technical identity.");
    });
    check("workspace-corrections-retain-history-and-reject-authority", () => {
        const ui=boot();ui.input("statement","A question about numbers?");ui.elements["workspace-start"].onclick();
        ui.input("workspace-model_relation","First proposed relation");ui.elements["workspace-model_relation"].dispatch("blur");
        ui.input("workspace-model_relation","Revised proposed relation");
        assert(ui.saved().history.some(value=>value.workspace_notes.model_relation==="First proposed relation"),"Original relation disappeared.");
        const value=ui.api.getDraft();throws(()=>ui.api.restoreDraft({...value,workspace_notes:{...value.workspace_notes,approved:true}}));
        throws(()=>ui.api.restoreDraft({...value,workspace_notes:{...value.workspace_notes,open:"true"}}));
        throws(()=>ui.api.restoreDraft({...value,workspace_notes:{...value.workspace_notes,approach:"empirical-approval"}}));
    });
    return JSON.stringify({status:"passed", engine:"JavaScriptCore through JXA",
        check_count:checks.length, checks, rendered_browser:false, screen_reader_tested:false});
}
