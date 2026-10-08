# AI science guide: goal-ready implementation plan

Status: software fixture ready, 2026-10-08. G00–G09 have local synthetic
verification through the one-command checker. The
milestones in [`milestones.json`](milestones.json) record the local software
checks, not scientific acceptance or live integration readiness. Do not merge
the separate modularity or reconciliation proposal branches to run this gate.

## Objective and completion ceiling

Enable a person to bring a question and a small CSV study to an AI client such
as Codex, and have that client guide one complete scientific loop: clarify the
question, organize the data, propose competing explanations, design a study,
run a supported analysis, explain the result and its limits, and propose the
next discriminating experiment. The guide owns the work of tracking missing
inputs, preparing drafts, calling existing Faraday services, checking results,
and showing what remains unresolved. The person owns the question, data rights,
and scientific decisions that require judgment or approval.

The automated completion state is `software_fixture_ready`. It means the local
workflow and its adverse synthetic fixtures passed at one exact commit. It is
not evidence that a real study is valid, a reviewer is qualified, a physical
experiment ran, a live model is safe, or Faraday is adequate for every domain.
Use the existing high-confidence readiness audit for those separate claims.

## Existing seams to reuse

- `ResearchService`, the `research` CLI, and canonical workspace records own
  changes. The guide must not create a second inquiry database or edit JSON or
  `ledger.jsonl` by hand.
- `design interview` and scaffold/revision services already collect many of the
  study-design commitments. The add-on registry supplies bounded CSV methods.
- Collaborator context and proposal validation already provide a read-only,
  hash-bound way for an AI client to suggest work. A model response is an
  untrusted proposal; it never activates a hypothesis, freezes a confirmatory
  protocol, admits evidence, or authorizes an effect.
- Dataset custody, run receipts, rigor, synthesis, next-action selection, and
  ledger verification remain authoritative. Extend these paths instead of
  implementing their rules in the conversational client.
- The repository is currently single-writer. Keep this goal local and serial;
  a multi-user service needs a later transaction/locking design.

## AI client boundary

The guide context is a versioned, read-only projection of existing records. It
must retain the original request, record references, open questions, evidence
and conclusion limits, and a digest of the disclosed context. Available method
IDs come from the add-on registry and are pinned when a design is selected.
Reuse collaborator redaction: raw datasets, private locators, and
secrets are not sent to a model by default. A client response is a versioned
proposal bound to that digest. It may contain next questions, candidate models,
design or analysis drafts, interpretations, and proposed commands, each with
its source references and uncertainty. The host validates and routes any
canonical command through `ResearchService`; the proposal itself changes no
scientific state. Codex can use this contract without Faraday calling a model.
The live provider port remains a typed stub until T01's separate gate is met.

## First supported user journey

1. The user gives a question, decision, population, and available CSV (or says
   which are unknown). The guide preserves the original wording and asks for
   missing outcome, unit, comparison, time, measurement, ethics, and change
   criteria without inventing answers.
2. The guide presents a small competing-model set: null, measurement or data
   error, selection/confounding where relevant, and the user's explanation.
   Each candidate has a prediction and an observation that would weaken it.
3. The guide drafts a prospective design and analysis choice. It shows the
   independent unit, measurement column and scale, signed contrast, estimand,
   missingness and multiplicity policy, outcome-exposure timing, assumptions,
   stopping rule, and uncertainty target. Unsupported designs stop with a
   specific explanation.
4. The guide inventories raw input bytes, typed columns, row/unit counts,
   missing and invalid values, role, source and custody status. Transformations
   create derived artifacts with provenance; raw data remain intact. Real data
   do not become evidentiary merely because they were parsed.
5. For a supported method, the guide uses the pinned add-on execution path and
   reports the effect estimate, uncertainty, diagnostics, exclusions, controls,
   and method ceiling. It never selects a favorable analysis after inspecting
   the protected outcome. A p-value threshold alone cannot decide the report.
6. The guide builds the existing deterministic synthesis and a next-action
   proposal. It labels exploratory revisions, inconclusive or negative results,
   unmet gates, and alternatives still compatible with the data. It audits and
   verifies the workspace before displaying a completion receipt.

For the initial vertical slice, use synthetic independent two-group CSV data.
Add paired and observational two-group fixture variants through the same
contract, using existing methods and their distinct claim ceilings. Do not
claim support for arbitrary designs or modalities.

## Milestone execution contract

Execute `G00` through `G09` in dependency order. One worker may implement one
milestone at a time and commit a small diff. Luna may write only that job's
`allowed_paths`. If a job needs more than four production files or a different
contract, split it into smaller numbered jobs and update this plan with the
reason before continuing within the same local scope. Stop when the change
would expand effects, disclosure, or authorization. Inspect the relevant
entry point and test configuration before its first execution or any change to
it. Run only local, disposable synthetic checks. Do not install dependencies,
call a live model or connector, start services, migrate data, or change remote
state under this goal. The user separately authorized installation of the two
declared test extras into Faraday's ignored, Legion-owned `.venv` on
2026-10-08; that narrow installation is complete. A missing test dependency
remains a failed prerequisite, not a reason to skip the check or report a pass.

Each job receipt records: job ID, base and resulting commit, files changed,
planned and actual effects, exact commands and observed results, fixture IDs,
remaining TODOs, and any blocked or deviating behavior. A passed worker test
means implementation verification only; it is not scientific or editorial
acceptance. Failed, stale, missing, or inconclusive required checks keep that
job incomplete. Continue independent jobs when possible.

| Job | Incremental deliverable | Observable gate |
| --- | --- | --- |
| G00 | Characterize existing service, CLI, collaborator, analysis, and ledger seams with one labeled synthetic journey. | Baseline tests pass and a fixture inventory names each reused command and record. |
| G01 | Versioned, read-only guide context and proposal contract for a Codex-like client. | Changed context hash, unknown references, and attempted authority claims fail closed. |
| G02 | Question intake and clarification from original wording. | Missing details stay unresolved; no generated finding or hidden canonical write. |
| G03 | Competing-model drafts through existing proposal and hypothesis routes. | Alternatives and falsifiers survive round-trip; generated candidates stay unreviewed. |
| G04 | Supported design and method preview using existing design services. | Unit, timing, scale, contrast, estimand, and plan mismatch cases are rejected before outcome use. |
| G05 | CSV inventory and data-quality handoff into existing dataset custody. | Raw bytes remain immutable; invalid or missing values and custody gaps are visible. |
| G06 | Pinned execution of supported analyses and bounded result explanation. | Correct method/receipt binding; paired-as-independent, post-result selection, and incompatible scale fail. |
| G07 | Synthesis and next-action guidance after a result. | Null, adverse, and inconclusive outcomes remain visible; no claim ceiling widens. |
| G08 | Explicit integration stubs and user-facing limitations for live providers and out-of-scope science. | Stubs have typed unavailable results, no side effects, and linked TODOs. |
| G09 | One-command synthetic end-to-end checker, documentation, and regression pass. | Full suite, adverse matrix, audit, ledger verification, and exact-artifact receipt pass. |

The machine-readable file specifies each job's dependency, allowed paths,
required fixture, check, and completion evidence. If the implementation makes
a documented path obsolete, revise the job and its check in the same commit.

## Final automated gate

`G09` implements `scripts/check_ai_science_guide_goal.py --json`. It must create
temporary synthetic workspaces outside the source tree, run the complete local
test suite, execute the guide journey through public CLI/service boundaries,
run `workspace audit --fail-on error` and `workspace verify`, and independently
inspect the generated report and receipts. It exits nonzero for any absent
tool, missing check, drifted hash, unauthorized state transition, unsupported
method silently selected, or unsafe claim. It outputs a bounded JSON result
with commit SHA, fixture versions, command results, ledger head, report hashes,
and `software_fixture_ready: true` only when all required checks pass. The
checker never sets scientific acceptance or activation status.

Positive fixtures must cover independent, paired, and observational two-group
designs with their distinct method assumptions and claim ceilings. The adverse
matrix must include: no usable data, wrong outcome scale, duplicate
unit IDs, paired rows misdeclared independent, missingness and exclusions,
changed input bytes, incorrect receipt or context hash, failed quality gate,
contradictory/negative result, no discriminating next experiment, an AI attempt
to approve its own hypothesis, and post-result confirmatory plan changes.
Tests must assert behavior at the authoritative service boundary, not just
inspect a fixture's declared status. A second replay from the same frozen
inputs must produce the same scientific result and stable report content.

The runner must have Python 3.11+ and the repository's declared test extras
already available. The checker may use `pytest` and the standard library, but
must not install packages, download data, or call a provider. Faraday's
ignored `.venv` has the declared test extras as of 2026-10-08; select that
interpreter explicitly before running the checker. If the extras are absent,
the checker must fail before starting an unattended goal. Their presence is
not evidence that the goal's tests passed.

## Stub and TODO boundary

G08 must expose typed `not_configured` or `unsupported` results, with no silent
fallback, for live model invocation, live connectors or instruments, arbitrary
statistics, domain-specific validity, authenticated independent reviewers,
real Metamaps compilation, and concurrent multi-user writes. Its TODO register
must name the missing contract or evidence, owner, first safe fixture, and
activation gate. Existing modularity and reconciliation proposals can inform
later work, but their fixture status cannot be promoted to integration.

The AI may organize and execute approved local computation. It cannot certify
source truth, consent, calibration, a causal assumption, a proof, replication,
or its own review. Confirmatory activation, protected external effects, ethics
decisions, and publication retain their existing authorization gates. The
software goal can finish unattended because it verifies bounded behavior with
synthetic data; it does not remove those gates from real science.

## Paste-ready goal objective

> Implement `docs/ai-science-guide/milestones.json` in dependency order from
> this plan's commit. Use Faraday's existing ResearchService, CLI, custody,
> analysis, collaborator, synthesis, and ledger contracts. Keep each change
> small, local, and reversible. Use synthetic fixtures and the job's exact
> adverse check; record an evidence receipt after each job. Stub unsupported
> external/domain capabilities with typed unavailable results and TODOs. Do not
> install dependencies or use Faraday runtime network/model/physical effects.
> Finish only when
> `scripts/check_ai_science_guide_goal.py --json` passes at the final commit and
> reports `software_fixture_ready: true`; report scientific and live-integration
> readiness separately.
