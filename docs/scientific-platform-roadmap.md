# Scientific platform roadmap

The target is one discipline-agnostic, self-contained tool for designing,
executing, auditing, and extending scientific investigations. Add-ons widen its
methods without changing its epistemic rules or canonical state.

## Delivered foundation

- A common inquiry, claim, hypothesis, dataset, protocol, run, evidence,
  replication, synthesis, and provenance lifecycle.
- Typed measurements, frozen protocols, execution-quality gates, chronology
  checks, artifact verification, and conservative claim ceilings.
- A validated add-on registry with a bundled general-science add-on and explicit
  loading of local experiment add-ons without publication.
- Write-once execution receipts binding analysis specification, data,
  implementation, environment, output, and gates.
- Cross-disciplinary CSV summaries, correlation, and seeded permutation testing.
- Separation between machine-development history and external experiment state.

## Phase 1 — complete the general empirical toolkit

Structured-control foundation: new observational and experimental protocol
freezes require `control_definitions`; other protocol kinds validate them when supplied.
Definitions contain
`control_id`, `registered_control`, `family`, `purpose`, `expected_behavior`,
and `evaluation_gate_id`. Families are positive, negative, sham, replay,
random_time, adversarial, reference, and other. Supplied definitions must cover
the registered controls exactly with trimmed-unique identities and link to
required quality gates. Expected
scientific behavior is not itself a quality-gate pass condition. Definitions are
hash-bound; absent definitions preserve legacy commitments without retroactively
claiming a control audit. The provider-free interview collects family, purpose,
and expected behavior for each named control and emits review-only definitions.
For a passed evaluation gate, run intake
requires exact `details.control_results` coverage for every control mapped to the
gate. Each result contains `observed_behavior`, `interpretation`, boolean
`matches_expected`, `evidence_sha256` referencing a run output artifact, and an
exact `evidence_location` within it. Extra or missing control IDs fail intake.
When the result cites Faraday's verified analysis output, the location must be an
absolute JSON Pointer that resolves in those hash-verified bytes. Other formats
retain an exact human-inspectable location without pretending to interpret an
arbitrary artifact. Unexpected observations remain recordable; failed or skipped
evaluation gates remain invalid runs. These declarations do not validate the
interpretation or establish that an unexpected control result permits downstream
inference. Deterministic synthesis preserves each control's family, run, gate
disposition, expected-behavior match, artifact digest, and exact location.
Evidence derived from such a run must retain the frozen control name in
`controls_failed` when `matches_expected` is false and must not list it in
`controls_passed`. This is disclosure of an unmet expectation, not an automatic
causal or validity judgment. Run-derived evidence now has to exactly partition
the complete frozen control set into `controls_passed` and `controls_failed`
according to those structured results; omissions, duplicates, invented controls,
and contradictory classifications fail closed. Existing synthetic-evidence
restrictions still apply.
All passed quality gates now require `details.evidence_sha256` referencing an
artifact emitted by that exact run. Optional `prerequisite_gate_ids` are checked
against the same run: every named gate must exist and pass before the dependent
gate may pass. This turns a pass summary into a hash-linked prerequisite receipt;
it verifies local run linkage and disposition, not the scientific adequacy of the
underlying test or the truth of its interpretation.

Run-deviation delivery: every automatically evidence-eligible run now requires
an explicit `protocol_deviation_disclosure`. Silence is retained as
`legacy_not_declared` and cannot qualify. A no-deviation declaration remains an
unauthenticated assertion. Declared departures preserve a stable ID, stage,
frozen commitment, actual method, reason, timing relative to result access,
potential impact, corrective action, and exact evidence location bound to an
artifact emitted by that run. They remain recordable for transparency but block
automatic evidence promotion. Replication-package verification independently
recomputes the same disclosure-aware eligibility rule.

Run-output and evidence-admission delivery: scientific evidence eligibility now
also requires a passed verification of every declared output under an explicit
local artifact root. Runs lacking that verification remain recordable but cannot
cross the evidence boundary. The canonical run retains its resolved root,
integrity receipt, and any pinned attestation-schema location and commitment.
Evidence admission revalidates the frozen protocol, current protected dataset
bytes and custody, current run-output bytes, and applicable ethics status, then
preserves a bounded admission receipt. Inquiry display, rigor audit, and
synthesis replay eligible run outputs again so post-admission mutation cannot
survive through a stale historical pass. Default replication exports redact
local roots and schema paths. These checks establish byte continuity and local
contract consistency, not execution truth or scientific interpretation. The
receipt hashes the complete immutable evidence payload outside the receipt
itself, making post-admission edits to conclusions, scope, uncertainty,
classification, selectors, or claim linkage semantically detectable.

Canonical run-payload delivery: after run preparation completes, the service now
hashes the full immutable run outside the hash field itself. Caller-supplied
commitments are rejected. Inquiry display and evidence admission recompute the
commitment for every run, so post-record changes to gates, protocol or dataset
links, chronology, deviation disclosures, eligibility, outputs, metadata, or
summary fail before influencing scientific state. This local commitment detects
accidental or out-of-band mutation under the repository trust model; it is not a
signature, external timestamp, or defense against an administrator rewriting
both canonical state and its entire provenance history.

Claim-bound evidence delivery: a scientific evidence admission receipt now
commits the referenced claim’s stable proposition—claim ID, statement, inference
level, creation time, parent structure, and scope. Authoritative reads recompute
that digest against current canonical claims. Reviewable epistemic layer,
disposition, confidence, sources, conflicts, falsification links, review time,
and decision owner remain outside the proposition digest, allowing transparent
later reassessment without changing what the evidence originally addressed.
Changing a claim’s scope, wording, level, or parents after admission therefore
fails closed rather than broadening a conclusion through a stable identifier.

Post-discovery evidence-status delivery: evidence records remain immutable, but
`research evidence record-status` appends a locally artifact-verified `active`,
`qualified`, `withdrawn`, or terminal `retracted` event. Events bind the exact
evidence ID, require timezone-aware chronology and the exact latest predecessor,
and preserve a linear sequence. Current rigor audits and synthesis capability
calculations use only evidence with no status event or a latest `active` event;
restricted evidence and its entire correction history remain visible in the
report. This verifies local review bytes and lifecycle consistency, not reviewer
identity or the scientific correctness of the disposition.
The event retains its local artifact root. Every authoritative read recomputes
the complete integrity receipt from present bytes and rejects missing, moved,
mutated, symlinked, or receipt-inconsistent review material instead of trusting
a historical `passed` flag.

Priority clarification from the original brief: guided design and the design
auditor are the next primary development track, not gated on completing this
statistical-method inventory. Execution edge-case tests alone do not establish
the requested end-to-end science environment.

Prospective hypothesis-content delivery: frozen protocols now retain an exact
SHA-256 commitment for each tested hypothesis’s scientific payload rather than
only its stable ID. The payload includes origin and lineage, statement,
observable prediction, null and competing models, scope, causal direction,
estimand, expected effect direction, time window, covariates, known confounds,
falsification and support conditions, boundary conditions, and replication
requirement. Workflow state, later evidence assessment, replication status, and
retirement metadata are excluded so legitimate scientific lifecycle decisions
remain possible without rewriting the preregistered proposition. Direct protocol
reads, inquiry display, amendment, run intake, and evidence admission fail when
current hypothesis science differs from the frozen commitment. The protocol hash
binds the commitment map itself.

Canonical proposition-seal delivery: claims and hypotheses now receive their own
service-generated scientific-content commitments at creation, before any later
protocol or evidence anchor exists. Claim seals cover identity, statement,
inference level, creation time, parent structure, and scope while permitting
explicit epistemic review fields to change. Hypothesis seals cover the same
scientific payload used by protocol freeze while permitting workflow, evidence
assessment, replication, and retirement transitions. Inquiry and direct
hypothesis reads validate every seal; review, activation, staging, and retirement
validate the source record before moving it. Thus even an unreferenced draft or
claim cannot be silently rewritten through direct state-file mutation.

Causal-identification audit delivery: provider-free `design identify` accepts a
typed DAG, exposure, outcome, assignment type, observed/unobserved declarations,
and proposed adjustment set. It rejects cyclic graphs, unavailable covariates,
exposure descendants, open backdoor connectivity, and randomized-assignment
claims that conflict with supplied causal parents. The deterministic result
retains a hash-bound input snapshot and an explicit graph-conditional claim
ceiling. It does not discover the graph, verify temporal order or positivity,
authenticate randomization, measure variables, or estimate an effect.
For observational graphs, the auditor now enumerates inclusion-minimal observed
adjustment sets when there are at most sixteen eligible covariates, with a hard
one-hundred-result ceiling and an explicit completeness status. Collider-opening
sets are not returned because each candidate is independently d-separation
checked. These are graph-internal candidates, not automated covariate selection
or a claim that adjustment is scientifically advisable.
Guided causal scaffolds now accept the same typed specification, run the audit
automatically, and retain its result as a separate review artifact. Violations
block causal readiness; supplied plain-language confounders must be represented
as graph nodes. A missing graph remains a visible unresolved warning, so the
scaffold never invents causal structure on the user's behalf.
Canonical causal protocols now fail closed at freeze: the service recomputes the
audit, the universal freeze policy requires the exact result, observational
causal protocols require observational assignment and a satisfied backdoor
criterion, and graph plus audit are protocol-hash commitments. Stale, omitted,
or forged audit output is rejected even through a direct policy call. A
non-causal protocol cannot smuggle causal-identification state into its
commitment. These checks establish contract integrity, not the scientific truth
of the asserted DAG or causal assumptions.
The causal contract now includes a typed assumption register. Every assumption
records a category, substantive statement, assessment plan, prespecified
failure response, and assessment kind: empirical diagnostic, design-record
review, external validation, or substantive judgment. Run intake requires the
assessment result to retain the frozen kind, so a judgment cannot become an
empirical diagnostic through later wording. Deterministic synthesis reports the
assessment-kind counts per causal protocol and preserves each recorded run,
category, kind, disposition, artifact digest, and exact evidence location; it
does not describe assumptions as verified. Common coverage requires positivity,
consistency, interference, temporal order, measurement validity, and selection bias;
observational assignment additionally requires exchangeability, while randomized
assignment requires allocation integrity. The auditor and protocol freeze reject
missing, duplicated, unsupported, blank, or assignment-conflicting entries.
This makes assumptions reviewable and falsification responses prospective; it
does not convert plans or diagnostics into proof that identification holds.
Every registered causal assumption now names a protocol quality gate. Freeze
requires that gate among `quality_requirements`. Run intake requires every passed
causal gate to retain a structured result for each mapped assumption: observed
diagnostic, interpretation, the exact `consistent_with_assumption` disposition,
evidence SHA-256 referencing a listed output from that run, and an exact table,
figure, section, record range, or JSON Pointer within that artifact. Missing or failed
gates preserve an invalid run, while contradictory structured results cannot be
presented under a passed gate. The provider-free run template emits these slots
from the frozen protocol. This creates an artifact-linked assessment chain; it
does not turn a diagnostic into proof of an untestable identification assumption
or authenticate the interpretation at the named location.
Non-skipped causal gates now preserve negative and ambiguous assessments with the
same exact artifact linkage. Gate/result semantics are enforced: passed means all
mapped results are `consistent_with_assumption`, warning requires at least one
`inconclusive` result without a contradiction, and failed requires at least one
`contradicted_assumption`. Extra, missing, unsupported, or rhetorically mismatched
results fail intake. These outcomes remain diagnostics, not proof or disproof of
the full real-world identification condition.
When an assessment cites the verified analysis output itself, run intake requires
an absolute JSON Pointer and resolves it against the hash-verified result bytes.
Other artifact formats retain exact human-inspectable locations without pretending
that Faraday can semantically interpret an arbitrary table, figure, or document.
Analysis add-ons now expose a typed maximum inference level alongside their prose
claim ceiling. The registry validates the level and execution binds it into both
result and receipt. Causal evidence requires a `causal_estimate` validation tag
on an exact causal-direction claim, plus `empirical_test`, a non-exploratory
eligible run, matching causal estimand target, frozen analysis contract, verified
execution handoff, and a `design_conditional_effect` method. Lower method classes
cannot cross that boundary. This prevents prose-only ceiling bypass while still
treating the estimator as only one component of causal identification.
Protocol-bound execution now passes the resolved method ceiling into the
canonical design validator before analysis. A causal primary analysis requires
`design_conditional_effect`; the decision and both levels are recorded in a
`method_inference_check`. Run-draft and canonical intake recompute the check, and
tamper tests reject altered nested checks or inconsistent receipt/result levels.
This binds capability metadata to the same implementation/specification/input
chain; it does not authenticate third-party add-on authors or make their
scientific capability declaration self-proving.
Observational causal analysis now freezes an exact ordered adjustment-column
list that must equal the DAG audit's proposed adjustment set. The analysis
specification must execute that same ordered covariate list, and its group and
outcome columns must equal the audited exposure and outcome nodes. Freeze,
handoff, run intake, and causal-evidence validation reject drift. The bundled
`adjusted_linear_effect` method makes this contract executable with OLS and HC1
robust uncertainty while rejecting rank deficiency, constant covariates,
unregistered exclusions, invalid units, and insufficient residual degrees of
freedom. This is conditional estimation under a frozen model, not verification
of the DAG, linearity, positivity, exchangeability, or causal truth.
Executable causal protocols now also require typed `exposure` and `covariate`
measurement definitions. The definitions must cover the audited exposure and
adjustment set exactly and bind each registered DAG target to the exact analysis
column, distinct from the outcome and one another. Guided scaffolds expose the
required definition fields for every observed causal node. This closes the gap
between a graph label and a measured variable while remaining only a provenance
and semantic check, not proof of construct validity, temporal order, or unbiased
measurement.
Guided causal-measurement delivery: the JSON scaffold and provider-free
interview now collect full reproducible contracts for the audited exposure and
each proposed adjustment covariate. Coverage, role, column, scale, domain, and
timing are checked exactly; exposure values must equal the ordered contrast,
exposure ascertainment must be `at_exposure`, and adjustment covariates must be
`pre_exposure`. A dedicated review artifact and proposed covariate columns carry
the commitments forward without claiming that the measurements or DAG are true.
Those definitions now carry typed causal timing. Adjustment covariates must be
`pre_exposure`, exposure ascertainment `at_exposure`, and the causal outcome
`post_exposure`; free-text evaluation points cannot bypass the ordering. This
rejects declared post-treatment adjustment while still treating timing as a
prospective assertion rather than authenticated acquisition chronology.
The same contract now requires a structured causal estimand: target hypothesis,
description, population, two distinct exposure strategies, outcome variable,
time zero, outcome time, contrast, summary measure, and intercurrent-event
policy. The DAG outcome must agree with the estimand. Canonical freeze binds the
estimand to a tested hypothesis's reviewed `primary_estimand` and, when present,
the same primary hypothesis and estimand in the analysis contract. This prevents
an undefined “causal effect,” target switching, and silent disagreement between
design and analysis; it does not establish that the target is scientifically
appropriate or identifiable in the real data-generating process.

Add tidy/tabular validation, confidence intervals, linear and generalized-linear
models, paired and repeated-measure comparisons, power/precision planning,
multiple-testing adjustments, random assignment generation, missingness reports,
and publication-quality tables and plots. Every method needs frozen assumptions,
units, deterministic fixtures, adversarial cases, and explicit claim ceilings.

Multiplicity execution now requires `family_hypothesis_ids` as an exact frozen
member set for Holm adjustment. Missing, substituted, duplicate, extra, blank, or
noncanonical identifiers reject before calculation; row order does not affect the
adjusted values. The result preserves the exact family list and alpha. This closes
selective input omission inside the executable method. Protocols with secondary
outcomes now separately freeze an exact, disjoint confirmatory/exploratory outcome
partition, method, and alpha contract: exploratory studies cannot acquire a
confirmatory family, while confirmatory studies must retain the primary outcome
and use `single_test` or `holm` according to family size. The guided interview is
provider-free and emits the same typed structure. Holm protocols now freeze an
acyclic multi-step workflow that separates the primary estimate from explicit
confirmatory tests. Each test binds exact specification and implementation
hashes, hypothesis, outcome, measurement ID, and p-value selector. The
multiplicity step exactly covers those test steps and family members. A
provider-free materializer verifies every pinned source receipt/result pair,
recomputes the registered selectors, and writes the exact family CSV plus a
receipt. Protocol-bound Holm execution verifies its frozen step, family order and
ID, alpha, implementation, specification, and registered input bytes. The
materialization output hash connects those receipts into a local byte chain;
independent chronology anchoring, executor authentication, and scientific-gate
adjudication remain separate enforcement layers.
Canonical run drafting and intake now understand confirmatory-test and
multiplicity receipts. Intake revalidates the frozen step and local bytes, then
requires exact agreement among the handoff, submitted protocol, sole dataset,
implementation hash, and output artifact. Workflow components are always marked
ineligible for standalone evidence, preventing an unadjusted source p-value or a
bare adjusted-p table from being promoted outside the registered workflow.
A primary-estimate run under a Holm protocol is likewise always a component, so
its estimate cannot bypass family-level adjudication.
The provider-free `analysis adjudicate-holm` command now builds a deterministic
composite result only after verifying exact completed canonical runs, passed
required gates, their byte-pinned execution handoffs, a shared non-synthetic
observation dataset, the family-materialization receipt, and the exact Holm
input/output chain. It emits the registered estimate and uncertainty alongside
one raw and adjusted decision for every frozen member. The artifact remains
non-evidence with `reviewed_composite_run_required`. A separate
`adjudication-run-draft` path now recomputes the artifact from canonical state,
requires one passed receipt per required gate from every component, rejects
scientifically different gate dispositions across components, and derives an
immutable composite gate set whose evidence pointers resolve into the embedded
source receipts. Review may add context but cannot rewrite those results.
Canonical intake recomputes both adjudication and gates before applying ordinary
quality-gate eligibility. Evidence
attachment selects only the adjudicated primary estimate and uncertainty and
cannot claim support unless the exact adjusted primary member rejects. Broader
workflow forms beyond Holm and richer study-level conclusion policies remain to
be built.
All confirmatory empirical analysis contracts now additionally freeze a typed
conclusion contract: primary hypothesis, direct or multiplicity-aware decision
rule, smallest effect size of interest, effect scale and measurement unit,
population, setting, endpoint, non-supporting disposition, permitted claim
level, and explicit unsupported higher conclusions. Provider-free scaffolding
and interviewing collect or visibly leave these items unresolved. One shared
deterministic policy evaluates interval direction and practical significance.
Practical support requires the directional confidence bound to clear the
smallest effect of interest; a large point estimate with an interval containing
trivial effects remains inconclusive. The Holm path additionally requires
adjusted primary rejection. Evidence must retain that
direction and exact scope and attach to a claim at the permitted level, closing
post-result reinterpretation and scope escalation across both workflow classes.
Direct equivalence delivery adds a distinct hypothesis direction, analysis
support rule, and conclusion rule. The deterministic adjudicator supports
equivalence only when the full interval is strictly within a frozen practical
margin around the registered null. It rejects the common error of interpreting
a nonsignificant difference as equivalence and binds the interval level to
`1 - 2α` for the direct TOST-compatible decision. A separate provider-free
`design equivalence-power` planner computes the smallest integer equal-group
sample whose known-variance normal decision probability meets target power for
a supplied true difference strictly inside the margin. It supports explicit
true-difference and SD sensitivity scenarios and is never labeled observed
power or evidence of equivalence. Holm-family equivalence remains unsupported
rather than reusing an invalid multiplicity rule.

Initial delivery: the bundled general-science add-on now provides deterministic
bootstrap confidence intervals and standardized effects for registered,
two-group independent and paired designs. The independent estimator rejects a
paired declaration; the paired estimator requires explicit pair identifiers and
rejects incomplete or duplicate pairs. These methods estimate bounded effects;
they do not establish causality or replace design, measurement, or sampling
gates.

Completion criterion: a small observational or randomized two-group study can be
planned, frozen, analyzed, recorded, audited, and packaged using only the
installed Research Machine distribution.

## Phase 2 — migrate the sleep/acoustic prototype

Analysis-audit checkpoint: the independent estimator optionally checks a
`unit_column` for nonblank, globally unique identifiers, including across groups.
Without it the result explicitly reports identity checking as absent; unique
identifiers do not prove independence. Other methods reject this option rather
than silently ignore it. Independent and permutation comparisons require an
explicit complete-case policy before excluding blank outcomes/group labels.
Exclusion reports retain parsed record numbers, missing fields, group counts,
and unassigned counts. Unregistered nonblank group labels reject the input even
when the outcome is blank. These checks do not establish ignorable missingness.

In a separate experiment repository, port raw-container inspection, versioned event sidecars, clock calibration,
sensor synchronization, association windows, sham/replay/canary controls, and
the five acceptance scenarios from Vindication into a `sleep_acoustic` add-on.
Preserve the old repository as frozen evidence until parity fixtures pass.

Completion criterion: the same synthetic sleep/acoustic scenarios produce
equivalent domain results while all authoritative state resides in Research
Machine contracts.

## Phase 3 — experiment setup and orchestration

Add a guided experiment scaffold that asks for decision, constructs, units,
population, sampling, manipulation, outcomes, controls, confounds, ethics,
stopping rules, and falsifiers; then emits reviewable inquiry, hypothesis,
measurement, protocol, data-dictionary, and run-record drafts. Add a local job
runner for allow-listed add-on methods and a portable replication-package
exporter.

Initial delivery: `research design scaffold` accepts a bounded plain-language
brief and emits review-only hypothesis, protocol, data-dictionary, and
collection-plan drafts plus a deterministic design audit. It fail-closes human
participant work missing consent, privacy, risk, or independent review, and
flags unresolved causal comparisons, measurement units, calibration, controls,
confounds, analysis commitments, and stopping rules. `research design interview`
now collects plain-language answers without JSON authoring or an LLM, including
predictions, alternatives, falsifiers, dependence, controls, and human-data scope.
For causal studies it can also collect the DAG and complete typed assumption
register interactively, validate variable and edge references, and feed the same
deterministic audit used by file-based and canonical workflows. Declining this
step leaves the graph unresolved; the interview never fabricates causal
structure.
Scale-aware measurement-design delivery: the same provider-free paths now ask
for the primary outcome's typed scale and analysis family, preserve categorical
domains, strictly ordered numeric bounds, and missing-value encodings, and emit
a review-only primary measurement-definition draft. The auditor rejects malformed or
colliding domains, invalid ranges, and mean/linear estimators applied to
nominal, ordinal, or time-to-event outcomes. Missing answers remain visible
warnings; the scaffold never invents a scale or silently encodes categories as
numbers.
Complete guided measurement-contract delivery: the scaffold and provider-free
interview now collect the primary measurement's exact observable, input
condition, fixed parameter bindings, evaluation point, coding convention,
aggregation, tolerance, expected behavior, and temporal role in addition to its
typed value domain. The observable and construct-validity plan remain separate;
one cannot satisfy the other. Confirmatory incompleteness blocks the draft,
while exploratory work retains a warning. Causal primary outcomes must be
post-exposure. The emitted measurement-definition draft now mirrors the
canonical contract shape while remaining explicitly unreviewed.
Prospective measurement-validity delivery: confirmatory guided designs now
require at least one structured validity check with a stable ID, evidence type,
specific validity claim, assessment procedure, acceptance criterion, failure
response, and dedicated required gate. The provider-free interview collects the
same contract and emits `measurement-validity-plan-draft.json`. Gate IDs cannot
be reused across validity, control, causal-assumption, or missingness purposes;
the plan never counts as an observed pass or proof of construct validity.
Canonical validity-commitment delivery: `MeasurementValidityCheck` is now a
typed protocol field with an exact target measurement ID. CLI parsing, the
published protocol schema, service construction, serialization, and freeze
validation preserve it. The complete check set participates in the protocol
hash; unknown measurement IDs, unsupported evidence types, absent required
gates, duplicate IDs, and cross-purpose gate reuse fail before freeze. This
protects the prospective plan but does not authenticate reviewer identity or
establish that the chosen check is scientifically sufficient.
Artifact-bound validity-result delivery: run templates and intake now require
exact result coverage for every performed validity gate. Each result separates
the observed diagnostic from interpretation, repeats the frozen evidence type,
uses a status constrained by passed/warning/failed disposition, and cites a
listed run output plus exact location. Inconclusive and contradicted checks are
preserved in invalid runs rather than suppressed; a consistent result does not
prove construct validity. Locally verified JSON evidence receives an additional
content-level check: its location must be an absolute JSON Pointer that resolves
in the cited bytes. This prevents a correct whole-file digest from laundering a
fabricated internal location while leaving non-JSON locations explicitly
human-inspectable.
Validity-reporting delivery: rigor now warns when a protected empirical protocol
has typed measurements but no canonical validity plan, emits a specific warning
for inconclusive validity checks, and emits an error when a frozen validity claim
is contradicted. Deterministic synthesis lists every frozen check and every
reported diagnostic, interpretation, disposition, output digest, and location,
including unavailable results. Numerical success cannot suppress measurement
validity limitations.
Validity-to-evidence binding delivery: each evidence record now carries the
service-derived ordered IDs of frozen measurement-validity checks with
artifact-bound `consistent_with_validity_claim` results. Evidence admission
recomputes and exactly matches this binding, and supporting evidence for a
measurement-validity claim is rejected when no qualifying check exists. The
field remains absent from caller commands so provenance cannot be self-declared.
Executable measurement-column delivery: guided briefs and the provider-free
interview now require an explicit primary outcome column rather than silently
using `outcome`. The scaffold propagates that commitment into the measurement
definition and data dictionary, rejects case-insensitive collisions across all
dataset-backed primary, secondary, and control measurements, and protects the
reserved identity, assignment, and capture-time columns.
Independent-unit schema delivery: whenever a guided design names an independent
unit, it must also name the exact stable identifier column. That name now agrees
across protocol, data dictionary, collection plan, and measurement-collision
audits; confirmatory omission blocks readiness. The proposed data dictionary
also enumerates every dataset-backed secondary and control measurement, closing
the prior gap between measurement-set drafts and the collection schema.
Secondary measurement-coverage delivery: each registered secondary outcome now
requires one ordered, exact-name, full typed measurement contract in guided
briefs. Coverage rejects omissions, duplicates, substitutions, and unregistered
surrogates; secondary domains receive the same categorical, missing-code,
strict numeric-range, non-negativity, and integer-count checks. The provider-free
interview can collect these definitions outcome by outcome and emits an ordered
secondary measurement-set draft without auto-filling skipped answers.
Control measurement-coverage delivery: every guided registered control now
requires one exact ordered reproducible measurement definition in addition to
its control-family rationale. Dataset-column controls receive typed domain
validation that rejects equal or inverted numeric bounds; artifact-evaluated
controls may explicitly omit column-only scale,
unit, range, and missing-code fields. The provider-free interview collects both
forms and emits a separate control measurement-set draft. Expected behavior
remains a prospective commitment, not evidence that the control passed.
Control and confound labels are now checked for case/whitespace-normalized
duplicates before downstream definitions, measurements, gates, or causal graph
roles can treat one repeated label as multiple distinct scientific roles.
Guided sample-size integration delivery: design briefs can carry any supported
deterministic planning input or exact receipt. The scaffold recomputes it,
retains the receipt in both the protocol and a dedicated review artifact, and
rejects invalid calculations, premature canonical target IDs, ordinary
difference power used for a practical-significance conclusion, and mismatched
direction or equivalence strategies. Target binding remains a later reviewed
protocol step; planning assumptions are not achieved power or design validity.
Cross-contract planning-coherence delivery: guided audits now compare a valid
receipt with the declared analysis design, minimum analyzable units, maximum
exclusion fraction, confirmatory alpha, confidence level, effect threshold, and
multiplicity method. Independent-group calculations cannot be attached to
paired or dependent analyses, and direct practical/equivalence power cannot be
presented as family-wise power for Holm decisions.
Causal-assignment classification delivery: causal intent no longer implies an
experimental protocol. Guided drafts derive protocol kind from an explicit
randomized or observational assignment declaration, reject conflicts with the
causal-identification record, require an intervention only for randomized work,
and retain observational exposure language for observational causal studies.
Unresolved assignment stays visibly review-required rather than being upgraded
to an experiment.
Prospective inference-commitment delivery: confirmatory guided designs now
require an explicit primary estimand, signed contrast definition, expected
direction, numeric null, support rule, and confidence level. The scaffold emits
a distinct analysis-commitment draft and retains the estimand and direction in
the hypothesis proposal. It rejects equivalence/difference-rule conflicts and
point-only confirmatory support, preventing favorable contrast reversal or a
post-result choice of the decision event. The artifact remains review-only and
does not substitute for a frozen executable analysis contract.
Canonical guided-commitment delivery: initialization and guided revision now
transfer the primary estimand, signed contrast, and expected direction into the
canonical unreviewed hypothesis. `contrast_definition` is a first-class sealed
hypothesis field and therefore participates in both the proposition commitment
and later protocol hypothesis commitments; it is no longer stranded in a draft
artifact or opaque revision provenance.
Executable contrast-binding delivery: `AnalysisContract` can now retain the
same signed `contrast_definition`; protocol freeze requires exact agreement
whenever either the hypothesis or contract declares it, runtime design checks
require the executable specification to match, and result receipts preserve the
executed contrast. This is backward-readable for older undeclared records while
failing closed against omission or reversal once a contrast is declared.
Structured contrast-order delivery: hypotheses now pair their prose contrast
with exactly two distinct ordered `contrast_groups`. Analysis contracts must
match that list and their executable `groups` order exactly; runtime semantics
and results derive and retain the same order. This makes first-minus-second
orientation machine-checkable instead of trusting a matching prose phrase.
Executable comparison-column delivery: each guided two-level contrast now names
the exact dataset column carrying its ordered levels. The provider-free
interview elicits it, and the protocol draft, data dictionary, and analysis
commitment preserve it. The audit rejects omission, collisions with measurement
or identity fields, and disagreement with a causal-identification record's
exposure node, closing the former hardcoded `condition` handoff gap.
Its optional output creates a separate experiment repository. This is a terminal
interview, not a graphical conversational app, power calculator, or automatic
protocol-registration workflow.

Revision delivery: `design revise` accepts a revised brief, parent hypothesis,
and reason; `design interview --revise-hypothesis` collects fresh answers and
the reason interactively. Both create a new unreviewed, lineage-linked proposal
through the canonical service. Its provenance retains the brief, scaffold audit,
and inquiry-wide IDs of datasets, protocols, runs, and evidence registered before
the revision. Earlier records and initial drafts are untouched. Cancellation
before submission creates no revision. This is neither a frozen-protocol
amendment nor proof of blinding; researcher exposure remains unknown. Review and
evidence are not inherited.
Protocol amendments now require structured timing (`before_collection`,
`during_collection`, `after_collection`, `after_analysis`, or `unknown`) and
evidence exposure (`not_seen`, `aggregate_seen`, `full_data_seen`, or `unknown`).
Rigor audit marks prospective/no-exposure amendments informationally and flags
retrospective, exposed, or uncertain amendments as warnings that cannot be
treated as prospective commitments. Superseded versions remain immutable.
Evidence validation tags from retrospective, exposed, or uncertain amendments
remain visible but no longer raise the synthesis maturity ceiling. The ceiling is
computed from unaffected classified evidence; when only amended evidence exists,
it reads `retrospectively amended evidence only; prospective confirmation
required`. A clean prospective study can still establish its own bounded ceiling.

Run-handoff delivery: `analysis run-draft` verifies pinned receipt/output bytes
and rechecks protocol, dataset, specification, implementation, and input bindings.
It retains the analysis result (including exclusions and unit checks), leaves
quality gates skipped and environment provenance unresolved, and writes no
canonical state. CLI fixtures reject changed bindings even with a newly supplied
receipt hash. This does not authenticate a receipt or verify original code/input
files are still available. The synthetic acceptance workflow now exercises
frozen observational and experimental protocols through registered input,
protocol-bound execution, reviewed run preflight, invalid-run preservation,
rigor audit, replication-package verification, redaction checks, and ledger
verification. It explicitly refuses to approve skipped gates or turn a numerical
result into valid scientific evidence; this proves workflow integration, not a
real scientific finding.
Canonical run intake now independently repeats this verification whenever
`execution_handoff` metadata is present: it requires the artifact root, reloads
the exact receipt and result from the trusted receipt hash, and revalidates the
protocol binding. Execution-backed evidence must bind the output SHA-256 and use
JSON-pointer selectors; stored effect and uncertainty values are derived from the
verified result rather than transcribed. Interpretive direction and summary
remain reviewable human claims rather than machine-inferred conclusions.
Those selectors are part of the frozen analysis contract, must be distinct
absolute JSON Pointers, and therefore cannot be chosen after results are visible.
Execution now requires both pointers to resolve and commits the selected JSON
values by separate hashes in its receipt. Run-draft and canonical intake
recompute those commitments from the pinned result bytes.
The method-enforced claim ceiling and frozen support rule now flow into canonical
evidence and deterministic synthesis. Protocols register a finite numeric null
and choose `point_direction` or `interval_excludes_null`. Execution validates
the selected confidence interval's shape, finiteness, level, and containment of
its point estimate; receipts bind that validation and the rule. Evidence blocks
an explicit `supports` label that fails the registered rule in the frozen
direction. It does not suppress weakening/refuting/inconclusive results or treat
a passed rule as confirmation of the hypothesis.
Analysis contracts now also freeze `minimum_analyzable_units` and
`maximum_excluded_fraction`. Execution uses the smaller independent-group arm
or complete-pair count and checks the structured exclusion report before writing
a completed receipt. Handoff verification recomputes the information check.
This prevents silent continuation after preregistered information loss; it does
not prove power, precision, representativeness, or missing-at-random assumptions.
Two-group contracts now additionally freeze
`maximum_group_excluded_fraction_difference`. Execution reconstructs each arm's
submitted denominator from included and excluded counts, rejects any exclusion
whose registered group cannot be recovered, and stops when the absolute
between-group rate difference exceeds the prospective ceiling. The receipt binds
the per-group rates and observed difference for handoff recomputation. Included
group counts must equal the reported included total, and grouped plus ungrouped
exclusions must equal the reported excluded total, preventing inconsistent
accounting from bypassing the differential threshold. This makes
differential attrition visible and enforceable; it does not identify the missing-
data mechanism or establish absence of selection bias.
Complete-case analysis contracts now additionally freeze a substantive
missingness assumption, assessment plan, assessment kind, failure response, and
dedicated required gate. The gate cannot be reused for control or causal-
assumption evaluation. Performed runs retain one exact artifact-bound assessment;
passed, warning, and failed dispositions must agree with consistent,
inconclusive, and contradicted results. Verified analysis-result citations use a
resolving absolute JSON Pointer. Deterministic synthesis exposes the frozen
assumption and every recorded disposition. This closes an accountability gap but
does not make any diagnostic sufficient to establish ignorability.
The provider-free design interview and scaffold elicit the same minimum count,
maximum total exclusion fraction, and maximum between-group exclusion-rate
difference, as well as the full missingness-assessment contract. Missing answers
remain explicit audit warnings;
supplied numeric thresholds are carried into the reviewable data-dictionary
draft for later analysis-contract freeze and are never selected automatically
from a desired result.

Repository-init delivery: `research design initialize` creates an isolated local
experiment repository with the original brief, review-only drafts, and a new
canonical workspace. It records design findings as open questions and creates
an `unreviewed` hypothesis only. It does not activate the hypothesis, freeze a
protocol, register data, invoke an LLM, or publish anything.
Machine-generated `[REVIEW REQUIRED]` placeholders now block hypothesis
activation, pending-review staging, and protocol freeze, including nested fields.
The scaffold also requires an explicit human-participant/data assessment: omission
blocks the draft and remains `null`, not `false`, in its human-subject field.
Replacing the marker is necessary but not sufficient scientific review: these
checks do not establish that arbitrary replacement prose is a valid prediction,
falsifier, control, or measurement plan.

Dependence-audit delivery: briefs accept `independent_unit`, `repeated_measures`
(boolean), and `analysis_design` (`independent_groups`, `paired`, `clustered`,
`repeated_measures`, or `descriptive`). Declared repeated observations combined
with an independent-groups analysis block the scaffold. Missing declarations
remain warnings; clustered/repeated-measure designs explicitly require method
review. These declarations are preserved in the draft data dictionary. This is
also enforced at canonical protocol freeze. Observational and experimental
protocols must supply the complete declaration; partial declarations and repeated
observations assigned independent analysis fail closed. Other protocol kinds
validate the declaration when supplied. It survives CLI registration and is hash-bound.
Legacy protocols with no declaration retain their prior commitment representation;
absence does not establish that independence was audited. This is not an automatic
assessment of actual sampling independence. Existing frozen records are not
retroactively rewritten or represented as having passed this new gate.
`analysis run --protocol <id> --dataset <id>` checks the declared design,
implementation hash, exact frozen analysis-specification hash, and registered
input bytes/role before execution. It does not establish scientific adequacy or
automatically register a run. Paired, clustered, and repeated-measure protocols
now require a hash-bound `unit_analysis_plan` stating how rows map to the
independent-unit estimand. Guided design asks for it only when dependence is
declared and blocks a dependent draft when it is absent. This records pairing,
clustering, within-unit aggregation, and time-structure commitments; it does not
prove that a chosen model handles dependence correctly. The initial
execution-to-run draft handoff is described above.
Protocols with a pinned analysis specification now also require a structured
`unit_id_column`. Protocol-bound execution binds an independent estimator's
`unit_column`, or a paired estimator's `pair_column`, to that exact frozen name.
The binding is retained in the execution receipt and revalidated during run-draft
handoff. This verifies identifier-column consistency and the estimator's own
duplicate/incomplete-unit checks; it does not prove that source rows were assigned
to the correct real-world units.
Execution now also derives a unit-structure receipt from the exact parsed CSV:
row and unit counts, repeated-unit count, minimum and maximum observations per
unit, and a SHA-256 commitment to the ordered row-to-unit mapping. A protocol
declaring no repeated measures rejects repeated identifiers, while paired
analysis requires exactly two rows per unit. The receipt is revalidated during
run handoff. This verifies data structure, not the truth of real-world identity
assignment.
Empirical protocols with pinned analysis specifications now additionally require
a structured `analysis_contract`: primary hypothesis, method, primary outcome
column, group column, ordered contrast levels, estimand, and missing-data policy.
Freeze requires that named hypothesis to be reviewed and its `primary_estimand`
to match the contract exactly. It must also name a typed primary measurement;
that definition's registered `data_column` must match the contract and executed
outcome column. Protocol-bound
execution compares each parsed field to that frozen contract. The executed
semantics and contract are retained in the receipt and revalidated during run
handoff, preventing an unchanged hash from masking an originally misaligned
method or outcome. This establishes syntactic identity to the registered
estimand; it does not prove that the estimand itself is scientifically appropriate.
Randomization now continues through that same boundary. `design randomize` emits
an order-independent digest of unit/group pairs. Contracts distinguish
observational, randomized-between-unit, nonrandomized, and not-applicable
assignment; randomized contracts require the digest. Execution reconstructs the
mapping from the exact dataset bytes and rejects allocation drift. This detects
recorded reassignment and unit-set changes but does not authenticate enrollment,
conceal allocation, or verify treatment adherence.

Replication-package delivery: `research replication package` exports a frozen
protocol, its dataset-manifest lineage, recorded runs, hashes, and independent
executor instructions. Version 2 additionally hash-covers the complete
protocol-scoped ethics review-event chain and latest recorded status while
explicitly refusing to authorize replication ethics. Its initial mode is metadata-only: raw data files are
not copied, but free-text metadata must be reviewed for secrets before sharing.
Default redaction covers protocol and event artifact-locator fields as well as
nested dataset/run locators. Verification strictly parses version-2 JSON and
recomputes protocol-summary agreement, the complete linear ethics chain, event
IDs, latest status, and the non-authorization invariant instead of trusting
manifest summaries. It also reconstructs an acyclic, closed dataset lineage,
checks exact unique dataset/run summaries, and requires every run to bind the
packaged protocol and included inputs. Run semantics are also recomputed:
analysis mode, dataset roles, synthetic propagation, unique and required gates,
output-bound gate evidence, prerequisites, validity status, workflow-component
status, and evidence eligibility. The verifier applies the same nonblank,
trimmed-unique identity rules to packaged protocol requirements, run gates, and
run-gate prerequisites that canonical intake uses, closing package-only
ambiguity before a package can be trusted independently.
Export self-verifies before atomic publication.
Version-1 packages remain verifiable.
Export itself does not validate a replication
result or publish material. `replication verify` checks included file integrity
against a separately trusted manifest hash; it does not reproduce the experiment.

Provider-boundary delivery: `research collaborator context --output <directory>`
freezes read-only inquiry state, open questions, and scientific constraints for
a future app, local model, user-selected provider, or human reviewer. The
write-once file has a separately reported SHA-256. `research collaborator
validate-proposal` requires that trusted hash and strictly validates an untrusted
human/LLM/hybrid response. Responses must expose uncertainty, alternatives,
disconfirmers, limitations, falsification conditions, and next tests; every
suggestion has `review_only` authority. The context now includes a compact
reference index for inquiry, question, claim, hypothesis, evidence, dataset,
protocol, run, and ethics-review-event records, and proposal `evidence_refs`
must cite only those frozen typed handles; each handle prefix must match its
declared context kind. The resulting record remains `pending_human_review`,
scientifically ineligible, and unable to authorize or write anything. Neither
command invokes a model, so this workflow has no provider or API-cost dependency.
All canonical changes retain the existing domain commands and scientific gates.
`research collaborator review-proposal` adds a second independently hash-bound
human adjudication artifact. It requires exactly one reject, defer, or
advance-to-domain-review disposition for every proposal suggestion and checks
that an advancement route is compatible with the suggestion kind. The reviewer
identity is explicitly unauthenticated, and advancement neither invokes nor
authorizes the route. This prevents omission and default acceptance while
preserving an auditable path from generated suggestion to later manual domain
review.

Literature-snapshot delivery: `research literature snapshot` creates a
write-once, hash-bound record of a search query, screening criteria, and locally
retained source files. Sources are classified but never promoted to facts or
evidence merely by retrieval; claim extraction, citation verification, bias
assessment, and synthesis remain distinct next gates.
Snapshots now group byte-identical retained files by SHA-256 without deleting
source records or resolving conflicting metadata. Unique-content counts are not
unique-study counts; related publications and multiple reports of one study
still require explicit study-level review.
`research literature screen --snapshot-file <snapshot> --expected-snapshot-sha256
<hash> --review-file <review> --output <new-directory>` records screening without
editing the snapshot. Review JSON contains `reviewer` and `decisions`; each decision
contains `source_id`, `decision` (include/exclude/unresolved), `reason`, and
`criterion_refs`. Criterion references such as `inclusion:1` and `exclusion:2`
use one-based positions within the exact pinned snapshot. Include/exclude
decisions require at least one existing criterion; unresolved decisions may use
an empty list. Version 2 screening records retain the criterion text. This does
not validate the reviewer's application of the criteria. Every
source must have exactly one decision. Conflicting decisions for byte-identical
sources remain visible and mark the screening as requiring review. Inclusion
does not accept a claim, authenticate a reviewer, or establish independent studies.
`research literature extract --screening-file <screening>
--expected-screening-sha256 <hash> --review-file <review>
--output <new-directory>` creates a separate write-once extraction record for
every included source. Each extracted claim must identify its source, reviewer-
declared study, exact evidence location, epistemic layer, result direction, and
uncertainty; included sources with no extractable claim remain explicit. The
screening bytes are hash-pinned and excluded sources cannot enter extraction.
These records are reviewer assertions, not accepted facts or scientific evidence.
The machine has not yet verified the cited passage, authenticated the reviewer,
assessed risk of bias, reconciled independent extractors, or synthesized effects.
`research literature verify-citations` adds a second, hash-bound review covering
every extracted claim. The citation reviewer must differ from the extraction
reviewer and must record the checked location, rationale, and a supported,
partially-supported, unsupported, or unclear verdict. Unsupported and unclear
claims remain in the artifact and force `review_required`; they are never silently
dropped. This records independent human citation checking but does not make a
claim true, authenticate reviewer identities, assess study bias, or create
scientific evidence.
`research literature assess-bias` requires a clean citation-review artifact and
a third reviewer distinct from both extraction and citation reviewers. Every
reviewed study must cover all seven documented bias domains, cite locations for
each applicable judgment, and exactly identify all source reports grouped under
that study. Overall judgments are computed conservatively from the domain
judgments; high risk dominates, followed by some concerns and unclear. This is a
generic audit scaffold, not a substitute for a design-specific validated bias
instrument, proof of reviewer expertise, or permission to synthesize effects.
`research literature reconcile-studies` then requires identity metadata for every
bias-assessed study and an explicit judgment for every unordered pair of studies.
Independent, overlapping-cohort, duplicate-report, and unclear relationships are
all preserved. Any non-independent or unclear pair forces `review_required`,
preventing silent double counting. Registration IDs, populations, settings,
recruitment periods, sample sizes, and cited locations support review but do not
prove cohort independence or authorize synthesis.
`research literature evidence-map` verifies every hash link from extraction
through citation review, bias assessment, and reconciled study identities before
joining claims. It assigns deterministic, conservative interpretive ceilings
from citation support, epistemic layer, and study bias. Each mapped claim carries
the extraction location, citation-check location and rationale, and retained
bias-domain judgments with their cited locations, so the ceiling remains tied to
inspectable review anchors. The write-once map cannot authorize a conclusion,
pooled estimate, causal claim, recommendation, or publication; it is the
inspectable input boundary for later registered synthesis.
`research literature plan-synthesis` freezes the research question, primary
outcome, qualitative or quantitative mode, effect measure, contrast definition, statistical model,
minimum independent-study count, eligibility, missing-statistics, heterogeneity,
multiplicity, subgroup, sensitivity, conclusion, and deviation policies against
the completed screening hash. It belongs before extraction. The artifact records
commitments but cannot prove external chronology or that the chosen methods are
appropriate; later synthesis must verify this plan and declare every departure.
`research literature synthesize` now executes the frozen qualitative branch. It
verifies the plan, extraction, and full evidence-map lineage; enforces the frozen
included-source set and minimum independent-study count; and retains every null,
adverse, mixed, hypothesis-only, and high-bias claim while reporting directional
and ceiling counts. The synthesis artifact also preserves the retained citation
and bias-domain provenance for each claim, preventing a later reader from seeing
only an unsupported ceiling label. It never treats claim counts as effect sizes
or authors a substantive conclusion. Quantitative plans fail closed until effect-size extraction,
variance checks, heterogeneity diagnostics, and validated pooling are available.
The quantitative branch begins with `research literature prepare-effects`. It
requires the frozen quantitative plan and its exact evidence-map lineage, then
records exactly one effect measure, standard error, variance, and sample size per
reconciled study. Each effect record also retains the mapped claim IDs, citation
verdicts, citation-check locations, and interpretive ceilings that brought the
study across the evidence-map boundary, and preparation rejects extraction source
sets that do not match the plan's frozen included sources. Unavailable statistics
must remain explicit null records and count against the frozen minimum-study
requirement. This validates finite values, positive variance, coverage, review
provenance, and plan consistency, but does not reproduce source calculations,
prove outcome compatibility, impute missing values, or authorize pooling.
`research literature derive-effects` provides a reproducible alternative for
`mean_difference` and `log_risk_ratio`: it computes estimates and standard errors
from source-reported experimental and comparator arm summaries under the frozen
contrast definition. Zero-event risk-ratio studies fail closed rather than
receiving an undeclared continuity correction. This reproduces arithmetic from
entered summaries, not the source transcription or participant-level analysis.
The exact arm summaries used for reproducible derivation are retained inside the
hashed effect-record artifact, closing the prior gap where computations were
reproducible during execution but their numeric inputs were not persisted.
`research literature verify-effects` requires a reviewer distinct from the
effect reviewer to check both source transcription and reproduced arithmetic for
every available study; unavailable studies receive explicit not-applicable
checks. Any mismatch remains visible and blocks `pool-effects`. This authenticates
neither reviewer nor source content, but closes the cleanly-coded/wrongly-copied
input path in the enforced quantitative workflow.
`research literature pool-effects` performs deterministic inverse-variance
pooling only after the quantitative plan and prepared-effect hashes agree. It
enforces the frozen fixed-effect or random-effects model, requires at least two
available independent-study effects and the frozen minimum, reports Cochran's Q,
I-squared, DerSimonian-Laird tau-squared, a 95% confidence interval, a random-
effects prediction interval when at least three studies exist, leave-one-study-
out estimates, and a study-provenance table spanning available and unavailable
studies. That table retains the mapped claim IDs, study risk of bias, and
independent effect-verification assessment for each record. It also replays the
verification artifact's retained effect status against the effect records, so
available studies require clean transcription and arithmetic checks and
unavailable studies retain not-applicable checks. Unavailable studies remain
disclosed. The executor does not interpret effect direction, reproduce source
calculations, or authorize causal, clinical, practical, or publication
conclusions.
Random-effects confidence and prediction intervals now use a conservative
modified Hartung-Knapp standard error with tabulated Student-t critical values;
the conventional standard error remains reported for auditability. Leave-one-out
intervals are explicitly labeled normal approximations using the full-analysis
tau-squared rather than being presented as independently refitted syntheses.
Quantitative plans now use executable sensitivity identifiers:
`leave_one_study_out`, `exclude_high_or_unclear_bias`,
`alternate_fixed_effect`, and `alternate_random_effects`. Effect records carry
the consistent study-level bias judgment from the evidence map. Pooling must
account for every frozen sensitivity, preserving `not_estimable` results rather
than omitting them; alternate-model and bias-exclusion uncertainties are labeled
normal approximations.
Small-study-effect diagnostics are now thresholded: Egger regression is attempted
only with at least ten available effects and varying precision. It reports the
intercept, standard error, Student-t interval, and degrees of freedom without a
binary publication-bias verdict. Non-estimability and the alternative causes of
funnel asymmetry remain explicit.
`research literature record-deviations` creates an immutable disclosure tied to
the frozen synthesis-plan hash. Each departure identifies its workflow stage,
frozen commitment, actual method, reason, timing, impact, and corrective action.
It also names an inspectable evidence location for the deviation review. Changes
after results were seen—or with unknown timing—force heightened review. The
artifact also retains a compact frozen-plan commitment snapshot, and rejects
synthesis-type-incompatible stages such as qualitative effect preparation. It
cannot amend the plan, retroactively preregister a choice, raise a claim ceiling,
or authenticate the researcher's account.
Both qualitative synthesis and quantitative pooling now require this declaration,
including an immutable `no_deviations_declared` artifact when none are reported.
The declaration hash and frozen-plan snapshot are embedded in the result and
checked against the supplied plan. Retrospective or unknown-timing departures do
not suppress computation, but force a deviation-review status and remain visible
in the synthesis output.

Precision-planning delivery: `research design precision` requires a declared
independent-groups design, a target interval half-width, an assumed standard
deviation, and an attrition estimate before returning analyzable and enrollment
targets. It is explicitly limited to normal-approximation precision planning;
it neither supplies causal identification nor claims power for an unspecified
effect.

Power-planning delivery: provider-free `research design power` now plans equal
independent groups from an explicit smallest effect size of interest, assumed
common standard deviation, alpha, target power, one- or two-sided alternative,
and anticipated attrition. It preserves separately supplied effect and variance
sensitivity scenarios and returns both analyzable and enrollment targets with
the exact input-byte provenance. The calculation is deliberately limited to a
normal-approximation known/common-variance formula for one continuous primary
comparison. It does not handle clustering, repeated measures, multiplicity,
small-sample distributional uncertainty, informative attrition, causal
identification, measurement validity, or achieved power, and a standalone result
does not itself freeze or preregister a protocol.

Protocol-bound sample-size delivery: `sample_size_plan` accepts a reviewed power
or precision specification plus a scientific justification. Evidence-bound
plans explicitly name their target hypothesis, measurement, and unit, which must match
the primary analysis contract; this prevents a calculation for one endpoint
from being silently reused for another or moved across incompatible scales.
Power plans must also use the conclusion contract's exact practical-significance
threshold, and no plan may anticipate more attrition than its analysis contract
allows. Composite workflow adjudication now carries the primary component's
registered information check into canonical run intake, eliminating an
adjudication-only shortcut around sample-size and attrition verification. The application
also records whether a precision-planned study achieved its registered interval
half-width. A miss is retained as scientifically informative evidence and
surfaced as a rigor warning, rather than being suppressed or converted into a
false protocol pass. Structured synthesis exposes the planned-versus-observed
sample, attrition, and precision values for each run. Observed attrition is
classified separately from the hard exclusion gate: exceeding the planning
assumption is disclosed with total and group-specific rates but does not
suppress otherwise admissible evidence when frozen ceilings and analyzable
counts still pass. The application core recomputes the calculation, emits a
versioned receipt with a canonical
specification hash, and binds the full receipt into the frozen protocol hash.
Partially or fully forged receipts fail unless they reproduce exactly. A declared
protocol analysis design must match the supported independent-groups design; if
an analysis contract supplies `minimum_analyzable_units`, it must equal the
calculated analyzable count per group, matching the contract’s independent-group
semantics. Precision planning is bound to the analysis contract's confidence
level and the executed interval; power planning is bound to the frozen
multiplicity alpha and primary-hypothesis direction. This prevents planning and
interpretation from silently using different inferential regimes. Protected
observational and experimental protocols
that retain prose-only planning receive a rigor warning rather than being forced
into an inapplicable formula. Typed census, sequential, clustered,
repeated-measures, simulation-based, and small-sample planning strategies remain
future extensions.

Variance-assumption accountability: evidence-bound two-group precision and
power plans require the registered independent mean-difference estimator. Its
verified output includes pooled within-group standard deviation in the frozen
measurement unit; direct and composite runs retain assumed SD, observed SD, and
their ratio. The ratio is descriptive unless a tolerance was prospectively
registered. Faraday does not compute observed power or manufacture a post hoc
variance pass/fail threshold.
When scientifically justified, either planning specification can register
`maximum_observed_to_assumed_sd_ratio`. Execution then applies that exact
prospective tolerance and rigor flags an exceedance while retaining the result;
the threshold is never selected from the observed data.

Measurement-custody delivery: frozen protocols with calibration requirements
must declare their required custody gates. Before protected datasets bind to
such a protocol, the machine validates an immutable raw-source list, ordered
hash-pinned transformations, passed calibration records, passed gates, and
derived-observation lineage. This is provider-free and can be used through the
CLI today. `measurement record` now publishes a write-once standalone custody
record only after matching an independently supplied receipt hash, the frozen
protocol and its calibration bounds and required gates, and all raw,
implementation, derived, and supporting-evidence bytes under a guarded local
artifact root. The record remains non-evidence and does not register a dataset;
`measurement verify-record` later requires an independently trusted record hash
and recomputes the receipt bytes, current frozen protocol binding, structured
custody checks, and local artifact-integrity result exactly. Canonical dataset
intake still repeats validation.

Protected observation-byte delivery: every non-synthetic confirmatory or
replication dataset now requires an explicit local artifact root at canonical
registration. The service verifies the declared observation hashes and sizes,
records a non-self-attestable receipt bound to the frozen protocol, and replays
the receipt from present bytes before inquiry display, protocol-bound execution,
or run intake. Mutation, removal, relocation, or symlink substitution fails
closed. Synthetic fixtures remain exempt but cannot become scientific evidence;
default replication exports redact local roots.

Canonical dataset-payload delivery: every registered dataset now carries a
service-generated commitment over its complete immutable manifest outside the
commitment field itself. This covers role, derived synthetic status, frozen
protocol binding, source lineage, observation unit, attestations, descriptive
identity, metadata, artifact declarations, and all generated verification
receipts. Caller-supplied commitments are rejected. Inquiry display and run
intake recompute the digest before applying role or evidence rules, preventing a
changed classification or lineage from exploiting otherwise valid artifact
hashes. As with run commitments, this is local mutation detection rather than a
signature or external timestamp; metadata-only exports may redact operational
paths and therefore preserve, but cannot independently replay, the unredacted
canonical commitment.

Instrument-adapter foundation: validated add-on manifests may now register
bounded inspectors with stable IDs, supported media types, and explicit config
fields. `measurement inspect-source` rejects media types outside that declaration,
then gives an inspector an immutable source-byte
snapshot, core-hashes its actual implementation module, rejects mutation of its
config, source, or code, validates its bounded metadata result, and core-hashes a
write-once acquisition proposal. `measurement verify-source-inspection` requires
an independently trusted record hash and exactly re-executes all three inputs.
The proposal
cannot assert calibration, pass gates, register data, or become evidence.
Device-specific adapters and parity fixtures remain experiment-driven work.

New custody submissions require `evidence_artifacts` (locator and SHA-256).
Each calibration and quality gate must cite a listed `evidence_sha256`.
Optional gate `prerequisite_calibration_ids` must name unique, present, passed
calibrations. Previously registered records are not rewritten. These are
reference-consistency checks, not an independent determination that a calibration passed. `measurement validate
--artifact-root` optionally verifies raw-source, transformation-implementation,
derived-output, and supporting-evidence bytes using the
existing safe artifact verifier. Protected dataset registration now requires the
artifact root, repeats that byte verification in the canonical service, and
persists the integrity report with hashes of the receipt and frozen protocol.
Exploratory custody can request the same persisted check but does not require it.
Custody receipts now require offset-aware transformation, gate-evaluation, and
derived-observation timestamps. Validation rejects a transformation before its
input, a gate before its calibration prerequisite, or an observation before its
transformation output. This supplies fail-closed internal chronology while
explicitly remaining an attestation rather than authenticated time evidence.
Provider-free `measurement template --protocol` derives a review-only custody
skeleton from the frozen protocol, including exact required gate IDs and
calibration criteria. It emits only skipped gates and placeholders and writes no
canonical state, giving terminal, form, and future conversational clients one
safe contract without an LLM dependency.
Measurement quality gates now bind nonempty artifact prerequisites by SHA-256,
and derived observations name their clearing gates. A cited gate must include
that observation's exact transformation output among its prerequisites. This
prevents a valid calibration or gate result from floating onto unrelated derived
data while leaving scientific interpretation to review.
Custody-bearing protocols now freeze quantitative calibration acceptance
criteria with stable criterion/calibration IDs, quantity, unit, rationale, and
at least one finite bound. Dataset registration requires every named calibration,
checks its numeric observation and unit against those bounds, and refuses a
declared pass that falls outside them. This supports bounded scalar acceptance;
multivariate calibration policies and device-specific instrument adapters remain missing.
Canonical protected datasets now retain their local custody-artifact root.
Inquiry display, protocol-bound execution, and run intake replay the complete
structured custody validator and present-byte verification from the preserved
receipt, and require exact equality with the service-generated registration
receipt. Mutation or loss of raw sources, transformation implementations,
derived outputs, calibration support, or gate evidence fails closed. Default
replication exports redact the operational root.

Ethics-gate delivery: a human-subject protocol cannot freeze until its consent,
withdrawal, privacy, retention/deletion, and risk plans are explicit and it
also records separate vulnerable-population, data-security, and incidental-
findings plans. These fields are hash-bound and presented alongside the recorded
independent-review scope to downstream clients; the machine does not judge their
substantive adequacy or grant approval. The protocol
records a qualified independent-review receipt plus the reviewer role, decision,
timestamp, scope, artifact SHA-256, and every conditional-approval obligation.
Only approval or approval-with-conditions can clear the freeze gate, and all of
these facts become part of the protocol commitment. The machine does not judge or
substitute for qualified review; it prevents an absent review record from being
silently treated as clearance. Human protocol freeze now additionally requires
an artifact locator plus `--review-artifact-root`, verifies the review decision
bytes against the frozen SHA-256, checks that the decision does not postdate
freeze, and stores a service-generated integrity receipt. This remains local byte
and chronology verification—not authentication of reviewer identity,
qualifications, independence, or substantive adequacy.
The original review verification now retains its local artifact root outside
the scientific protocol hash and is exactly recomputed whenever human-subject
clearance, inquiry display, or local replication export relies on it. Missing,
moved, changed, symlinked, or receipt-inconsistent source review material fails
closed. Default exports redact this operational path; legacy packaged receipts
remain semantically verifiable without claiming the recipient possesses the
originating institution's private file.
Conditional approval now remains enforceable after freeze. Human-subject dataset
intake requires an artifact-backed discharge record that exactly covers every
frozen condition, distinguishes satisfied duties from ongoing active controls,
and binds each disposition to verified bytes and a location. Assessments must
fall between the review decision and registration. Active controls require an
explicit validity horizon; canonical run intake rejects analysis completed after
that horizon and persists its service-generated ethics check. JSON evidence
locations are required to resolve as absolute pointers in the verified bytes and
the selected value is hashed; other media retain explicitly non-machine-resolved
locations. The machine still
does not authenticate assessors or independently establish compliance truth.
Condition-discharge verification now retains its evidence-artifact root and is
fully replayed from the preserved receipt and current bytes before inquiry
display and every run. Replay rechecks exact condition coverage, original
chronology, validity horizons at verification time, media types, JSON Pointers,
selected-value hashes, and the complete integrity report; any difference fails
closed. The operational root is redacted from default replication exports.
Post-freeze review status is now an append-only canonical event chain. Each
active, suspended, withdrawn, or expired event binds the frozen protocol, exact
latest predecessor, effective time, reason, and locally verified review artifact.
Active renewals may expire. Dataset and run intake evaluate the latest applicable
event and fail closed for non-active or expired clearance. Protocol-bound
execution now evaluates review status and conditional-control horizons before
calling the analysis method and binds that check into its design receipt; the
frozen protocol is never rewritten. The provider-neutral collaborator context
exposes this history.
Local ethics decisions now retain each review-artifact root and recompute the
complete integrity receipt from current bytes whenever the chain is used for
inquiry display, dataset intake, execution, or run intake. A missing, moved,
mutated, symlinked, or receipt-inconsistent artifact fails closed. Replication
packages redact the local root by default; their verifier validates the
hash-covered event chain without pretending to possess or authenticate the
originating institution's private review material.
Protected dataset lineage now requires every source to share the exact frozen
protocol, not merely the same confirmatory or replication role. This prevents
human-subject and prospective-analysis commitments from being silently replaced
through cross-protocol derivation; deliberate reuse requires a separately
auditable workflow rather than metadata relabeling.

Completion criterion: a new experiment can be initialized without manually
authoring JSON while no generated hypothesis or protocol silently becomes
approved.

## Phase 4 — additional disciplines

Prioritize add-ons according to real experiments rather than taxonomy alone:

- psychology: randomization, masking, validated instruments, attrition and
  manipulation checks;
- time series and signals: filtering, event detection, synchronization, spectral
  analysis, and leakage controls;
- biology: plate maps, assay calibration, batch effects, detection limits, and
  blinded image/count pipelines;
- surveys and social science: weighting, scale reliability, clustering, and
  design-based uncertainty;
- causal inference: DAG declarations, balance, sensitivity analyses, negative
  controls, and identification audits;
- formal/computational science: simulations, theorem/proof adapters, benchmarks,
  numerical stability, and independent implementations;
- literature synthesis: search snapshots, screening, extraction, bias assessment,
  and meta-analysis.

Each new add-on must exercise the shared contracts and contribute at least one
failure fixture that protects the core from an invalid inference.

## Phase 5 — durable multi-user operation

Add transactional storage, locking, authenticated executor identities, signed
artifacts, managed external timestamps, privacy policies, encrypted sensitive
data packages, and a UI/API over the existing application service.

These improve coordination and trust; they must not redefine previously frozen
experiments or retroactively upgrade evidence.
