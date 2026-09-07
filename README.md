# Research Machine

`./research --json design randomize --spec-file assignment-plan.json` generates
deterministic, balanced fixed-block assignments from explicit unit IDs, groups,
block size, and integer seed. The result binds the exact input bytes and assignment
sequence. It also emits an order-independent `allocation_sha256` over unit/group pairs.
Store that digest in a randomized empirical analysis contract; protocol-bound
execution derives the same mapping from the registered dataset and rejects
missing, added, crossed-over, or reassigned units. A disclosed seed and fixed
blocks may be predictable: generation does
not establish allocation concealment, blinding, enrollment order, or adherence.
An optional `strata` object must map every unit ID to a nonblank stratum; each
stratum must form complete blocks. Output reports balance within every stratum.
This balances declared strata but does not eliminate within-stratum confounding
or validate how strata were chosen.

Precision-plan specifications may include `sensitivity_standard_deviations`,
for example `[1, 2, 4]`, to compare sample targets under explicit hypothetical
variability assumptions. Other inputs stay fixed. Scenarios do not estimate
uncertainty in the standard deviation or automatically choose an enrollment target.
CLI results retain the supplied assumptions and the exact input-file hash and byte
count. This is planning provenance, not preregistration or scientific evidence.

`holm_adjustment` requires the exact prespecified `family_hypothesis_ids`, a
stable family name, and alpha. The input must contain every member exactly once;
missing, substituted, or extra hypotheses fail before adjustment. The result
retains the family and returns deterministic monotone Holm-adjusted p-values.
This protects the arithmetic family boundary but does not prove that the family,
tests, alpha, or chronology are scientifically appropriate.

Protocols with secondary outcomes must also freeze a typed outcome-role plan.
`confirmatory_outcomes` and `exploratory_outcomes` must partition the primary and
secondary outcomes exactly, without overlap, omission, or invention. Confirmatory
protocols use `single_test` for one confirmatory outcome or `holm` for a larger
family and must record `multiplicity_alpha`; exploratory protocols must classify
every outcome as exploratory and use `exploratory_only` without an alpha. The
provider-free design interview creates this structure before protocol review.

For Holm-controlled protocols, that outcome plan is now backed by a frozen
multi-step analysis workflow. The primary effect estimate is distinct from each
explicit `confirmatory_test`; every test binds its method, exact specification
and implementation hashes, hypothesis, outcome, measurement, and p-value JSON
Pointer. The Holm step freezes an acyclic dependency set and one-to-one family
mapping. `research analysis materialize-holm` verifies pinned upstream receipt
and result bytes, rechecks each registered p-value selector, rejects missing or
substituted source steps, and writes the exact family CSV plus a provenance
receipt. Protocol-bound Holm execution then accepts only the frozen Holm
specification, implementation, ordered family, family ID, alpha, and registered
input bytes. The paired materialization and execution receipts establish a local
byte chain; they do not authenticate chronology, executors, scientific gates, or
the truth of source observations.

Executable measurement definitions now freeze the data column's scale type,
unit, categorical domain or strictly ordered numeric validity bounds, and exact
missing-value codes. Protocol-bound execution validates the actual CSV values
against those
commitments before analysis and records the check in its receipt. This prevents
silent recoding, out-of-domain categories, out-of-range values, fractional
counts, and unregistered missing encodings; it does not prove measurement
validity or calibration.

`./research --workspace PATH analysis run-draft --execution-directory OUTPUT
--expected-receipt-sha256 TRUSTED_HASH` returns a review-only run draft from a
protocol-bound execution. It verifies the pinned receipt/result bytes and checks
the binding against canonical records. Scientific gates remain skipped and the
environment hash remains unresolved. Review the `record` and use run preflight
before recording; output artifact locators are relative to the execution directory.
Canonical run intake repeats receipt/output-byte verification and the complete
protocol binding; callers cannot bypass this by constructing
`metadata.execution_handoff` themselves. This command writes no canonical state
and does not authenticate the executor.
It also supports frozen `confirmatory_test` and `multiplicity` workflow receipts.
Their run drafts use the step's implementation hash, and canonical intake
requires the verified handoff to match the submitted protocol, sole dataset,
implementation, and output artifact exactly. Non-primary step hashes are rejected
without that handoff. Recorded workflow components remain categorically
ineligible for standalone scientific evidence—even if their gates later pass—so
raw p-values or adjusted values cannot bypass the composite workflow conclusion.
The same restriction applies to a primary-estimate run under a Holm protocol;
its unadjusted estimator cannot become standalone evidence before family-level
adjudication.

`research analysis adjudicate-holm` performs that provider-free composite
check from a hash-pinned manifest. It requires the exact completed canonical
run and verified execution receipt for the primary estimate, every frozen
confirmatory test, and the Holm step; all required component gates must pass.
It also re-verifies the family-materialization receipt, requires one shared
non-synthetic observation dataset across the estimate and tests, and proves
that Holm consumed the exact materialized bytes. The output combines the
registered estimate and uncertainty with one bounded adjusted decision per
frozen family member. It remains explicitly non-evidence until
`research analysis adjudication-run-draft` recomputes it from canonical state
and exposes an immutable composite gate review derived from the exact passed
gate receipts of every component. Components must agree on each gate's scientific
disposition; the composite draft binds those source receipts into the adjudication
artifact instead of allowing their results to be re-entered after the combined
result is known. A researcher may add review context but cannot alter the inherited
gate results. Canonical intake recomputes the handoff and derived gates again,
pins the exact adjudication artifact, and only then applies ordinary eligibility
rules. Evidence attached
to the composite must select its exact registered estimate and uncertainty; a
`supports` direction is rejected unless the adjusted primary decision also
rejects. Successful local assembly therefore cannot promote itself into a
scientific claim.

Confirmatory empirical analyses must also freeze a typed
`conclusion_contract` before data are interpreted. It binds the primary
hypothesis, decision rule, smallest effect size of interest, effect scale and
unit, population, setting, time window, non-supporting disposition, permitted
claim level, and conclusions that remain unsupported. Direct analyses require
the registered interval's directional confidence bound—not merely its point
estimate—to reach the smallest effect of interest; Holm composites additionally
require adjusted primary rejection. Both paths use the same deterministic
adjudicator. Evidence must reproduce its direction, scope, and
unsupported-conclusion list and attach to an exact claim at the permitted level.
For bounded claims of equivalence, use hypothesis direction `equivalence`,
analysis support rule `interval_within_equivalence_margin`, and conclusion rule
`equivalence_interval_within_margin`. Support requires the entire confidence
interval to lie strictly inside the frozen null ± margin; failure to reject a
difference is never treated as evidence of equivalence. At alpha `0.05`, the
registered interval must be `0.90` (`1 - 2α`). Equivalence currently supports a
direct `single_test`; Holm-family equivalence remains intentionally unsupported.
Use `research design equivalence-power --spec-file <json>` for a distinct
known-variance normal approximation based on the probability that the complete
`1 - 2α` interval lies within the symmetric margin. It requires a margin,
assumed true difference strictly inside that margin, assumed SD, alpha, target
power, and optional attrition, variance-tolerance, and sensitivity assumptions.
Its output is conditional planning evidence—not observed power or evidence that
the groups are equivalent.

Passed control-evaluation gates must include an exact result for every control
mapped to that gate: observed behavior, interpretation, whether the frozen
expectation was met, an output-artifact SHA-256, and an exact table, figure,
section, record range, or JSON Pointer inside that artifact. When the cited
artifact is Faraday's verified analysis result, the location must be an absolute
JSON Pointer that resolves in those bytes. Synthesis retains this provenance and
keeps unexpected control behavior visible. A passed gate means the control was
evaluated as required; it does not mean the scientific outcome was favorable.
Evidence derived from that run must then account for the complete frozen control
set: each registered control appears exactly once in `controls_passed` or
`controls_failed`, as determined by its structured result. Omissions, duplicates,
overlap between passed and failed controls, invented controls, and favorable
relabeling are rejected.

Evidence attached to an execution-backed run must supply the verified analysis
output SHA-256 plus the effect-estimate and uncertainty JSON Pointers frozen in
the analysis contract. Faraday resolves and stores those values directly from the hashed
result. Free-text summaries and interpretations remain human assertions, but the
numeric substrate cannot be retyped or silently changed.
Execution itself fails if either frozen selector does not resolve, the selected
effect is non-finite, or the selected confidence interval lacks finite
`lower`, `upper`, and `level` values, excludes its own point estimate, or uses
an invalid confidence level. The receipt stores separate hashes for the selected effect and uncertainty, and both
`run-draft` and canonical run intake recompute them from the verified result.
Execution-backed evidence also carries the add-on method's enforced claim
ceiling. The frozen contract declares a numeric null and either a
`point_direction` or `interval_excludes_null` support rule. A `supports` label
must satisfy that rule in the hypothesis's frozen direction. These checks enforce
the preregistered interpretation boundary; they do not establish truth.
The contract also freezes a minimum analyzable-unit count and maximum excluded-
record fraction. Execution rejects results below either information threshold;
for independent groups the count is the smaller arm, and for paired studies it
is the complete-pair count. The receipt binds the observed values for handoff
recomputation. Two-group contracts additionally freeze the maximum allowed
absolute difference between group-specific exclusion fractions. Execution
reconstructs each group denominator from included and excluded counts, rejects
excluded rows whose group is unavailable, and stops when the differential ceiling
is exceeded. Included group counts must conserve the included total, while grouped
plus ungrouped exclusions must conserve the excluded total. Passing these gates
does not establish that missingness is ignorable,
that retention is representative, or that selection bias is absent.
The same contract must state the missingness assumption that would make the
complete-case analysis interpretable, how it will be assessed, whether that
assessment is an empirical diagnostic, design-record review, external validation,
or substantive judgment, what happens if it fails, and a dedicated required gate.
Run intake requires an exact artifact-bound result. Passed, warning, and failed
gates correspond respectively to `consistent_with_assumption`, `inconclusive`,
and `contradicted_assumption`; the classification cannot be upgraded after
freeze. Synthesis preserves the assumption, kind, disposition, artifact, and
location while explicitly avoiding a claim that ignorability was proved.

To revise through questions without JSON or an LLM, use `./research --workspace
PATH design interview --revise-hypothesis HYPOTHESIS_ID`. The interview asks for
the reason and fresh study answers; cancellation records nothing. Prior answers
are not automatically copied. The resulting proposal retains registered-record
chronology, but does not claim to establish what results the researcher has seen.

For causal-design review, `research design identify --spec-file causal.json`
audits a supplied directed acyclic graph and proposed adjustment set. It checks
the backdoor criterion, unobserved adjustment variables, descendants of the
exposure, and conflicts between asserted randomization and graph parents. The
input bytes are hashed and retained in the output; no model, network service, or
canonical write is involved. Passing is conditional on the supplied graph and
does not establish that its causal assumptions are true.
For observational DAGs with at most sixteen eligible observed covariates, the
audit also enumerates up to one hundred inclusion-minimal adjustment sets that
satisfy the supplied graph. Enumeration is deterministic and explicitly reports
when it is bounded or truncated. These are graph-valid candidates for review,
not recommendations: measurement quality, positivity, efficiency, feasibility,
and domain plausibility still govern the choice.
Every causal-identification specification also carries a structured assumption
register. Each entry must state the assumption, how it will be assessed, and
what happens if it is not defensible. Observational designs must cover
exchangeability; randomized designs must cover allocation integrity. Both must
cover positivity, consistency, interference, temporal order, measurement
validity, and selection bias. Missing, duplicate, blank, unsupported, or
assignment-inconsistent entries block the audit. Coverage is a preregistration
check, not evidence that an assumption holds.
Each assumption also names a frozen protocol quality gate. The gate must be a
declared `quality_requirement`; a passed run must include an exact
`causal_assumption_results` entry with the observed diagnostic, interpretation,
`consistent_with_assumption` status, and a SHA-256 reference to one of that
run's output artifacts. Missing or failed gates make the run invalid. A failed
assessment remains recordable as an invalid run; a contradictory result cannot
be mislabeled as a passed gate. “Consistent with” means only that the registered
diagnostic did not trigger its failure response—it does not verify the assumption.
Every assumption also freezes its assessment kind as `empirical_diagnostic`,
`design_record_review`, `external_validation`, or `substantive_judgment`.
Run intake requires the result to preserve that classification, preventing a
record review or expert judgment from being relabeled as an empirical test.
Deterministic synthesis reports the frozen count of each assessment kind and,
for recorded results, preserves the run, category, kind, disposition, artifact
hash, and exact evidence location. It never summarizes these as “assumptions
verified.”
Each passed causal-assumption result must also name the exact location of its
diagnostic inside the cited output artifact. A whole-file hash without an
inspectable table, figure, section, record range, or JSON Pointer is insufficient.
When the cited artifact is Faraday's verified analysis result, the location must
be an absolute JSON Pointer that resolves in the hash-verified result bytes;
rehashing a receipt cannot make a missing diagnostic exist.
Failed and warning causal-assumption gates retain the same exact, artifact-bound
result structure instead of collapsing into a summary. Passed gates accept only
`consistent_with_assumption`; warning gates require at least one `inconclusive`
result and no contradiction; failed gates require at least one
`contradicted_assumption`. Skipped means the assessment was not performed. This
preserves disconfirming and ambiguous results while preventing a gate label from
misrepresenting the recorded diagnostic outcomes.
Analysis methods now publish a machine-readable maximum inference level:
`computation_only`, `descriptive`, `association`, or
`design_conditional_effect`. The level is validated in the add-on manifest and
bound into both the result and execution receipt. A `causal_estimate` evidence
tag requires an exact causal-direction claim node, the accompanying
`empirical_test` tag, an eligible confirmatory or replication run, a frozen
causal protocol and analysis contract, the registered target hypothesis, a
verified execution handoff, and a method capped at `design_conditional_effect`.
Descriptive and associational methods cannot be promoted to causal evidence.
Even the highest method level is conditional on the design and assumptions; it
does not authorize mechanism, generalization beyond scope, or causal proof.
For protocol-bound execution, the resolved add-on supplies this level directly
to the canonical design check before its runner executes. Causal primary analyses
reject any level below `design_conditional_effect`. The design receipt retains an
exact `method_inference_check`, and run-draft plus canonical run intake recompute
it from the frozen protocol and receipt. Editing the nested check, result level,
or receipt level breaks verification even if a new receipt digest is supplied.
It must also define one structured causal estimand: the canonical target
hypothesis, a one-sentence estimand description, target population, exactly two
distinct exposure strategies, DAG outcome variable, time zero, outcome time,
causal contrast, population summary measure, and intercurrent-event policy.
The outcome must match the graph; canonical freeze requires the target to be a
tested, reviewed hypothesis whose `primary_estimand` exactly matches the
description. If an analysis contract is present, it must select that same
hypothesis and estimand. These are identity and completeness checks, not an
endorsement of the target estimand or an effect estimate.
For observational causal analysis, the contract must also freeze an exact
ordered `adjustment_columns` list equal to the DAG audit's
`proposed_adjustment_set`; its group and outcome columns must name the audited
exposure and outcome nodes. Execution requires the specification's
`covariate_columns` to match exactly. The bundled `adjusted_linear_effect`
method executes this commitment using OLS with HC1 robust uncertainty and
fail-closed checks for unit identity, exclusions, numeric covariates, rank, and
residual degrees of freedom. This prevents silent adjustment drift but does not
validate the DAG, model form, identification assumptions, or causal truth.
Executable causal protocols must additionally define typed measurements for the
audited exposure and every adjustment covariate, alongside the primary outcome
and controls. DAG targets and exact analysis columns must agree, and modeled
columns must be distinct. The guided data-dictionary draft exposes these missing
definitions. Completeness establishes measurement provenance, not construct
validity, temporal correctness, or freedom from measurement error.
The guided scaffold and provider-free interview now collect these definitions
directly. They require exact ordered coverage of the audited exposure and
adjustment set, bind exposure categories to the signed contrast, and emit a
separate `causal-measurement-definitions-draft.json`. Skipped answers remain a
blocker; DAG names are never expanded into plausible procedures automatically.
The same definitions carry a typed temporal role: causal adjustment covariates
must be measured `pre_exposure`, the exposure `at_exposure`, and the outcome
`post_exposure`. This blocks declared post-treatment adjustment; it records the
reviewed ordering but does not verify timestamps or make the ordering true.
When a causal-identification specification is embedded in a guided design brief,
the scaffold runs this audit automatically and emits
`causal-identification-audit.json` beside the protocol draft. Open backdoor paths
or other violations block a causal scaffold, and every plain-language confound
must appear as a graph node. Omitting the graph remains an explicit unresolved
warning rather than an invented model.
Canonical protocols that set `causal_claim: true` must carry a complete causal
identification specification. Freeze recomputes the audit, rejects unresolved
violations, and binds both the supplied graph and exact deterministic audit into
the protocol hash. Direct policy callers cannot omit or forge that audit.
Non-causal protocols cannot carry causal-identification state. This enforces
internal consistency and provenance; it still does not validate the truth of the
graph or registered assumptions, establish positivity or consistency,
authenticate randomization, or
estimate a causal effect.

Record a guided revision with `./research --workspace PATH design revise
--brief-file revised-brief.json --hypothesis HYPOTHESIS_ID --reason "Why the design changed"`
(optionally `--inquiry INQUIRY_ID`). This creates a new unreviewed, lineage-linked
hypothesis and retains the revised brief and design audit in its provenance. It
does not amend frozen protocols, inherit approval or evidence, retire the original,
or overwrite the initial drafts.

For local custody-file checks, use `./research measurement validate --receipt-file
custody.json --artifact-root /path/to/artifacts`. This verifies listed raw sources
and supporting evidence bytes with relative-path and symlink safeguards. Without
the artifact root, only reference consistency is checked. Neither mode proves
measurement validity or authentic acquisition.

Start a provider-free, plain-language study interview with
`./research design interview`. No JSON authoring or LLM API is required. Optional
answers may remain unresolved and appear in the design audit. To retain the brief
and drafts in a new, separate local experiment repository, use
`./research design interview --output /path/to/new-experiment`. This creates only
an unreviewed hypothesis and review-only drafts, even when the audit is blocked;
it does not approve collection, freeze a protocol, or publish anything. Without
`--output`, results are printed and no experiment is created. Prompts use stderr
so `--json` keeps stdout machine-readable. This is a guided terminal workflow,
not a model-backed chat. For a causal study, the interview optionally collects
the graph variable names, observed status, directed edges, adjustment set,
structured causal estimand, and each required assumption statement, assessment
plan, and failure response. It
rejects malformed edge syntax and unknown adjustment variables before producing
the review artifact; users may decline and leave causal identification visibly
unresolved instead of accepting an invented graph.
It is not yet a graphical conversational application or a substitute for method review.

Research Machine is a headless, provenance-first engine for turning curiosity
into testable inquiries. For now, a person collaborates with Codex and Codex
operates the machine through a stable command interface. A later UI, HTTP API,
or model provider can call the same application services without changing the
domain model.

The machine is deliberately not a claim-confirmation engine. It keeps competing
explanations alive, separates levels of inference, records scoped evidence, and
preserves rejected hypotheses with the conditions under which they should be
reconsidered.

## Guided design scaffold

`research design scaffold` turns a small, plain-language JSON brief into
review-only hypothesis, protocol, typed primary-measurement, data-dictionary,
and collection-plan drafts.
It also gives plain-language structural findings for causal identification,
measurement units and calibration, controls, confounds, stopping rules, and
human-participant safeguards. It never creates canonical state, activates a
hypothesis, freezes a protocol, or authorizes data collection.

The provider-free interview and JSON scaffold distinguish measurement units
from scale type. They preserve categorical admissible values, numeric ranges,
and missing-value codes, and reject overlapping missing/observed encodings,
malformed binary domains, invalid ranges, and a mean/linear analysis selected
for nominal, ordinal, or time-to-event outcomes. The selected analysis family
remains a reviewable design commitment, not an automatic method choice.
The primary-measurement draft also carries the canonical contract’s reproducible
semantics: the exact recorded observable, input condition, fixed parameter
bindings, evaluation point, coding convention, aggregation, tolerance, expected
behavior, and temporal role. The observable is distinct from the separately
retained construct-validity plan; evidence that a ruler or instrument is valid
does not define which quantity was recorded.
Confirmatory work must also define at least one structured prospective validity
check with its evidence type, validity claim, assessment procedure, acceptance
criterion, failure response, and dedicated quality gate. These checks are
emitted in `measurement-validity-plan-draft.json` and added to the protocol’s
required gates. They remain plans—not evidence that validity has been shown.
Validity gates cannot be reused for control, causal-assumption, or missingness
assessments.
During canonical protocol construction, each check must be bound to the exact
reviewed `measurement_id`; stable check and assessment-gate IDs must be unique
after trimming whitespace. The typed checks survive serialization and are part
of the frozen protocol commitment, so later changes to a validity claim,
criterion, procedure, failure response, or gate invalidate the protocol hash.
Older protocols without this optional typed field remain readable; guided
confirmatory designs do not pass readiness without it.
Run templates expose the exact required result shape for each validity check.
Every performed validity gate must bind its observed diagnostic and
interpretation to a listed output artifact and exact location. Its disposition
must agree with the gate: `consistent_with_validity_claim` for passed,
`inconclusive` for warning, and `contradicted_validity_claim` for failed.
Warnings and failures remain recordable but cannot become eligible scientific
evidence; consistency remains a bounded diagnostic statement, not proof of
validity. For any locally verified JSON output, the location must be an absolute
JSON Pointer that actually resolves in the hash-verified bytes. Other artifact
formats retain an exact human-inspectable location without claiming automatic
content interpretation.
Deterministic rigor and synthesis carry the validity layer through reporting.
The synthesis lists frozen checks and each run’s observed diagnostic,
interpretation, disposition, and artifact location. Rigor warns on inconclusive
checks, errors on contradicted validity claims, and warns when a protected
empirical protocol has typed measurements but no canonical validity plan. A
numerically favorable estimate therefore cannot make a failed measurement check
disappear from the scientific record.
Admitted evidence also retains the ordered IDs of the exact frozen validity
checks whose artifact-bound results were consistent. Faraday derives this
binding from the protocol and run rather than accepting it from the caller,
replays it during evidence admission, and will not admit supporting evidence for
a measurement-validity claim without at least one such check.
Its dataset column is an explicit researcher commitment, never a generated
`outcome` default. Across primary, secondary, and dataset-backed control
measurements, column names must be case-insensitively unique and may not reuse
the scaffold's identity, assignment, or capture-time columns.
When repeated rows or any separately declared independent unit are present, the
exact stable unit-ID column is also required and shared by the protocol, data
dictionary, and collection plan. Secondary and column-backed control
measurements are included in the proposed dictionary rather than existing only
in detached measurement drafts.
Confirmatory designs with any of these unresolved are blocked; exploratory
designs retain a warning. A causal primary outcome explicitly declared at or
before exposure is rejected rather than treated as a post-exposure outcome.
Every registered secondary outcome must likewise have exactly one complete typed
measurement contract in the same order. The scaffold rejects missing,
duplicated, renamed, or invented secondary targets and malformed value domains,
including equal or inverted numeric bounds, then emits an ordered
`secondary-measurement-definitions-draft.json`. The
provider-free interview can collect each contract; skipped answers remain an
explicit coverage blocker rather than generating a plausible surrogate.
Registered controls now require the same exact ordered measurement coverage.
Each control measurement preserves its observable, input condition, parameters,
evaluation point, convention, aggregation, tolerance, expected behavior, and
timing. Controls stored in dataset columns must carry a complete typed value
domain with strictly ordered numeric bounds; controls evaluated through retained
artifacts may explicitly omit the
column-specific fields. The interview and scaffold never treat a control-family
label or expected behavior as proof that the control was reproducibly measured.
The design auditor also rejects duplicate control and confound labels after
case/whitespace normalization, so a repeated scientific role cannot receive
multiple definitions, measurements, gates, or causal-graph meanings.

Guided JSON briefs may also carry a supported `sample_size_plan`. Faraday
recomputes the deterministic receipt and embeds the review copy in the protocol
and `sample-size-plan-draft.json`; hand-edited calculations fail. The auditor
rejects conventional null-rejection power as justification for the scaffold’s
practical-significance conclusion, mismatched direction/equivalence strategies,
and premature target IDs. Canonical hypothesis, measurement, and unit IDs are
bound later during executable protocol construction. Absence of a machine plan
remains visible and may instead be accompanied by an honest feasibility-limited
justification; no planner establishes validity or guarantees achieved power.
The guided audit also cross-checks the receipt against the rest of the design:
analysis dependence structure, minimum analyzable count, exclusion ceiling,
confirmatory alpha, interval level, practical/equivalence threshold, and
multiplicity method. A locally correct calculation attached to a scientifically
different protocol is therefore rejected before freeze.

Causal intent is also separate from exposure assignment. A causal scaffold must
classify assignment as randomized or observational (directly or in its causal
identification record). Only randomized assignment produces an experimental
protocol draft; observational causal work remains observational and must define
the measured exposure. If assignment is unresolved, the draft keeps an explicit
review marker instead of inferring “experimental” from causal language.

Confirmatory causal and correlational scaffolds must also state the exact
primary estimand, signed contrast order, expected direction, numeric null,
support rule, and confidence level. Faraday emits these in a separate
`analysis-commitment-draft.json` and carries the estimand and direction into the
hypothesis proposal. Equivalence intent cannot use a difference-support rule,
and a confirmatory point-direction rule is rejected because it ignores
uncertainty. These remain review artifacts until stable IDs and executable
specifications are frozen canonically.
When `design initialize` or guided revision creates the canonical unreviewed
hypothesis, the estimand, signed contrast, and expected direction are preserved
as first-class hypothesis fields rather than being left only in draft files or
provenance prose. The service-generated scientific-content seal covers the
contrast, so later out-of-band reversal fails integrity validation.
When that hypothesis is used by an executable protocol, the analysis contract
must carry the same `contrast_definition`, and the runtime specification must
match it exactly. Execution receipts retain the contrast alongside the estimand.
Legacy hypotheses and contracts that never declared a contrast remain readable,
but a contrast declared on either side cannot be omitted or changed on the
other.
The contrast also carries an ordered two-level `contrast_groups` commitment.
Protocol freeze requires it to equal both the hypothesis order and the analysis
contract’s executable `groups` order. Thus a shared prose label cannot conceal
that the implementation computed B-minus-A instead of A-minus-B; the derived
order is retained in execution semantics and results.
Guided designs additionally name the exact comparison or exposure column whose
values carry those levels. The data dictionary and analysis-commitment draft use
that same field, and causal designs must match the audited DAG exposure node. A
hardcoded `condition` placeholder cannot silently become the executable grouping
variable.

```bash
./research --json design scaffold --brief-file examples/design-brief.json
```

Create an isolated local experiment repository—without publishing it, calling
an LLM, activating a hypothesis, freezing a protocol, or registering data:

```bash
./research --json design initialize --brief-file examples/design-brief.json \
  --output ../experiments/seedling-light-trial
```

The created repository is a local Git repository with no configured remote. It
includes the original brief, review-only drafts, and a private local `.research`
workspace. Its generated hypothesis is explicitly `unreviewed`; design-audit
findings become canonical open questions. Pass `--no-git` only when Git is not
desired for that experiment.

## Replication packages

Export a frozen protocol's commitments, dataset lineage, recorded runs,
append-only ethics review history, and
independent-executor instructions without copying raw data files. Free-text
metadata can contain sensitive information; review it before sharing:

```bash
./research replication package --protocol <frozen-protocol-id> \
  --output replication-package
```

Retain the returned `package_manifest_sha256` separately through a trusted
channel. Verify a received package with:

```bash
./research replication verify --package replication-package \
  --expected-manifest-sha256 <trusted-export-hash>
```

This checks included file integrity, not the truth of the study or successful
replication. A hash supplied only by the package sender alongside a modified
package is not an independent authenticity check.

The initial package mode is deliberately `metadata_only`. It is a sealed,
hash-listed handoff for an independent executor, not a publication action or a
claim that a result has replicated. Artifact locators are redacted by default;
use `--include-locators` only when those paths are safe to disclose. Package
version 2 must declare `privacy_mode` as `metadata_only` and
`artifact_locator_policy` as either `redacted` or `included`. It hash-covers
`ethics-review-events.json`, reports the latest recorded status, and always sets
`replication_ethics_authorized` false: original approval or renewal never
authorizes a new site, population, or replication. Protocol and review-event
locator fields are included in default redaction. Verification does more than
rehash files: it strictly parses version-2 JSON, validates the linear
ethics-event chain against `protocol.json`, derives the latest status, checks the
manifest's exact event IDs, and rejects any claimed ethics authorization or
unsupported package policy. The manifest limitations must also match Faraday's
non-evidentiary replication contract, so a package cannot claim to include raw
data, validate replication results, or authorize human-subject reuse by editing
summary text. `INSTRUCTIONS.md` must match the same contract exactly, preventing
the human-facing replication handoff from weakening those warnings while keeping
file hashes internally consistent. Export and verification receipts report the
package version and applied verification contract, so downstream clients can
distinguish v1 file-integrity checks from v2 guardrail replay.
It also reconstructs dataset lineage, rejects duplicate IDs, missing ancestors,
cycles, and unrelated extras, requires manifest dataset/run IDs to match the
records exactly, and verifies that every run binds the packaged protocol and
uses only included datasets.
It normalizes the packaged protocol's required-gate identities and rejects
duplicates before run checks. For every run it also recomputes analysis-mode and
dataset-role compatibility, synthetic propagation, unique quality gates, required
protocol-gate coverage, passed-gate output evidence, prerequisite satisfaction,
run validity, and final scientific-evidence eligibility. Gate IDs and
prerequisite references are normalized with the same nonblank, trimmed-unique
rules used by canonical run intake, so malformed package metadata cannot survive
independent verification. Packages exported with `--include-locators` also
replay the packaged protocol, dataset, and run frozen hash commitments from the
unredacted bytes; redacted packages preserve the original commitments but cannot
independently replay locator-bearing hashes. The exporter runs this verifier
against its staging directory before atomically publishing a package.

## Evidence corrections and retractions

When later review changes how an existing evidence record should be used, keep
the original record and append an artifact-backed status event:

```bash
./research --json evidence record-status \
  --evidence <evidence-id> --status qualified \
  --effective-at 2026-09-06T14:00:00Z \
  --reason "A preprocessing discrepancy requires bounded reinterpretation." \
  --review-artifact-locator correction-review.json \
  --review-artifact-sha256 <sha256> \
  --review-artifact-root /path/to/review-files

./research --json evidence status-history --evidence <evidence-id>
```

Statuses are `active`, `qualified`, `withdrawn`, and terminal `retracted`.
Every later event must name the exact latest event with `--supersedes-event`.
Qualified, withdrawn, and retracted evidence remains in the report and history
but cannot contribute to current rigor capabilities or conclusion ceilings.
Faraday verifies the local review artifact and chronology; it does not
authenticate the reviewer or decide whether the scientific judgment is correct.
It retains the local artifact root and re-hashes the review bytes whenever the
status history is used for inquiry display, rigor audit, or synthesis. Missing,
moved, changed, or symlinked review material therefore fails closed.

## Optional model or app collaboration

The scientific core does not call a model. An app or researcher can freeze a
provider-neutral, read-only context payload for a local model, user-selected
provider, or human reviewer:

```bash
./research --json collaborator context --purpose "Help clarify the design" \
  --inquiry <inquiry-id> --output collaborator-context
```

The result reports the SHA-256 of `collaborator-context.json`. Supply that hash
separately when preserving a structured response:

```bash
./research --json collaborator validate-proposal \
  --context-file collaborator-context/collaborator-context.json \
  --expected-context-sha256 <trusted-context-sha256> \
  --proposal-file proposal.json --output validated-proposal
```

Proposal JSON must identify its human, LLM, or hybrid generator and include
uncertainty, competing explanations, disconfirming evidence, limitations, and
review-only suggestions with falsification conditions and a next test. Faraday
strictly parses it, binds it to the exact frozen context, and stores it
write-once as `pending_human_review`. The frozen context also carries a compact
reference index such as `question:<id>`, `claim:<id>`, `hypothesis:<id>`,
`evidence:<id>`, `protocol:<id>`, `run:<id>`, and
`ethics_review_event:<id>`; proposal
`evidence_refs` must cite only those typed, prefix-checked handles, so an
optional collaborator cannot smuggle uncited external claims across the provider
boundary. Context handles, suggestion IDs, evidence references, and review
decisions are checked after trimming, so whitespace padding cannot create a
second apparent citation or review obligation. It does not call a provider, modify the inquiry, accept a finding,
create evidence, or authorize an action. Any accepted idea must still be
translated deliberately through the normal question, hypothesis, protocol-freeze,
ethics, custody, run, and evidence commands.

Adjudicate every returned suggestion explicitly using a review JSON file rather
than treating the generated response as accepted by default:

```bash
./research --json collaborator review-proposal \
  --proposal-record-file validated-proposal/collaborator-proposal.json \
  --expected-proposal-record-sha256 <trusted-proposal-record-sha256> \
  --review-file proposal-review.json --output reviewed-proposal
```

Each suggestion must be rejected, deferred, or advanced to a compatible named
domain review such as `question.add`, `hypothesis.propose`, `design.revise`, or
`protocol.amend`. Advancement is triage, not acceptance: the review record
authenticates neither reviewer identity nor scientific adequacy, authorizes no
action, and does not execute the named command.

## Literature snapshots

Capture a reproducible local record of a literature search without trusting a
search tool as evidence authority:

```bash
./research literature snapshot --manifest-file literature-search.json \
  --output literature-snapshot
```

Each source in the manifest names a locally retained file. The snapshot hashes
that file, records its primary/secondary/registry/preprint classification and
screening criteria, and states that claims still require separate extraction,
verification, and bias assessment.

Downstream literature evidence maps retain the extraction location, independent
citation-review location and rationale, and study-level bias-domain judgments
with their cited locations for every mapped claim. Qualitative synthesis now
requires the extraction source set to match the synthesis plan's frozen included
sources, and preserves those provenance anchors instead of carrying only a ceiling
label. This makes the review trail inspectable while still refusing to turn
retrieved or reviewer-entered source claims into Faraday scientific evidence.

Quantitative effect preparation also binds each study-level effect record to the
mapped literature claims that justified including the study, including the claim
IDs and citation-review anchors, after checking the extraction source set against
the synthesis plan's frozen included sources. Meta-analysis requires those links
and reports a compact `study_provenance` table for available and unavailable
studies, so a pooled estimate cannot shed the reviewed claim boundary or hide
studies with missing compatible statistics. The same table retains the independent
source-transcription and arithmetic verification status for each effect record,
and pooling replays the retained effect-status contract: available effects must
carry clean source and calculation checks, while unavailable effects must remain
not-applicable rather than acquiring after-the-fact numeric-looking verification.
Literature deviation declarations retain a compact snapshot of the frozen
synthesis-plan commitments, and qualitative synthesis or quantitative pooling
must match that snapshot before recording a result. Each declared departure
also names an inspectable evidence location for the review of that deviation.

## Precision, difference-power, practical-power, and equivalence-power planning

Before collecting an independent two-group study, plan a target confidence-
interval half-width from an explicit assumed standard deviation and attrition
rate:

```bash
./research design precision --spec-file precision-plan.json

./research design power --spec-file power-plan.json

./research design practical-power --spec-file practical-power-plan.json

./research design equivalence-power --spec-file equivalence-power-plan.json
```

This reports separate analyzable and enrollment targets. It is a bounded
normal-approximation precision calculation—not a causal-design check, a power
calculation, or a substitute for measurement validation.

The conventional power planner requires an explicit smallest effect size of interest,
assumed standard deviation, alpha, target power, directional alternative, and
attrition fraction. It reports analyzable and enrollment targets plus optional
researcher-supplied effect-size and variance sensitivity scenarios. The bounded
formula assumes equal independent groups, a continuous outcome, common known
variance, and one primary comparison. It does not account for multiplicity,
small-sample distributional uncertainty, clustering, repeated measures,
informative attrition, causal identification, or measurement validity. Its
byte-bound input provenance is review material, not preregistration or evidence.
It powers rejection of a point null and therefore cannot govern Faraday's
stronger practical-significance conclusion. For that decision, use
`practical-power`: it requires a researcher-supplied true effect strictly beyond
the practical threshold and powers the event that the registered directional
confidence bound clears that threshold. The conditional true-effect assumption
is explicit and must be sensitivity-tested; it is not observed power.
To make a reviewed calculation prospective, place it in a protocol as
`sample_size_plan` with `strategy`, `specification`, and `justification`.
Faraday recomputes the calculation, stores a versioned receipt, and includes it
in the protocol hash. Evidence-bound plans must also name the exact
`target_hypothesis_id`, `target_measurement_id`, and measurement unit selected
by the analysis contract; an un-targeted plan remains usable only where no executable analysis
contract exists. A supplied full receipt must reproduce exactly. When an
analysis contract declares `minimum_analyzable_units`, it must equal the plan’s
analyzable count per group—the contract’s exact independent-groups meaning; an
incompatible protocol analysis design also fails freeze.
Precision plans additionally require a matching analysis-contract
`confidence_level`, and execution rejects intervals reported at another level.
Evidence-bound practical-power alpha, interval level, direction, and threshold
must match the frozen single-test analysis and conclusion contracts. Conventional
difference-power remains review-only and cannot be attached to that conclusion.
Anticipated attrition may not exceed the analysis contract's maximum permitted
exclusion fraction. Direct and composite executions preserve the observed
analyzable count and exclusion fraction in the run's sample-plan check; a
workflow adjudication is not a substitute for those verified observations.
For precision designs, the same run check compares the verified primary
interval's observed half-width with the frozen target. Missing the target does
not erase or relabel the result—it remains potentially admissible evidence—but
Faraday emits a rigor warning and forbids describing planned precision as
achieved. Structured synthesis reports planned and observed analyzable counts,
attrition, group-specific exclusion imbalance, and interval half-width for every
plan-bearing run. Attrition above the planning assumption but below the hard
exclusion ceiling remains admissible and receives a distinct rigor warning.
The registered independent-groups estimator also exposes pooled within-group
standard deviation, allowing synthesis to report the observed-to-assumed
variability ratio. Faraday does not turn that ratio into post hoc “observed
power” or infer an adequacy threshold that was never preregistered. Evidence-
bound two-group plans therefore require the matching
`independent_mean_difference_ci` primary estimator.
Researchers may prospectively add
`maximum_observed_to_assumed_sd_ratio` (at least `1`) to either plan. Faraday
then classifies observed variability as within or beyond that registered
tolerance and raises a non-suppressive rigor warning when it is exceeded.
Protected empirical protocols without such a receipt remain possible for designs
not yet supported by these formulas, but receive an explicit rigor warning.

The output is deliberately marked `review_required` even when no structural
blocker is found. Human-participant drafts fail closed until consent, privacy,
risk, and qualified independent-review fields are supplied.

For human-subject protocols, the freeze gate separately requires a consent
plan, withdrawal plan, privacy plan, retention/deletion plan, risk assessment,
and a structured qualified independent-review decision: stable receipt,
reviewer role, decision status, timestamp, review scope, artifact SHA-256, and
any approval conditions. These fields are committed into the frozen protocol;
pending, withdrawn, or adverse decisions cannot clear the gate. These are scientific and safety
requirements, not a declaration that the machine can grant ethical approval.
Human protocols also require distinct frozen plans for vulnerable-population
eligibility and protections, encryption/access/security response, and incidental
or safety-relevant findings. Generic privacy or risk prose cannot silently stand
in for these decisions.
They must also name the independent-review artifact locator and hash. Freezing a
human protocol requires `--review-artifact-root`; Faraday verifies the local file
bytes and that the recorded decision does not postdate freeze, then stores a
service-generated verification receipt. This does not authenticate the reviewer
or determine whether the review was adequate.
The receipt retains the local review-artifact root. Inquiry display, clearance
checks, and local replication export re-hash the original review bytes and
recompute the receipt exactly; missing, moved, changed, symlinked, or
receipt-inconsistent material fails closed. The operational root is excluded
from the protocol's scientific commitment and redacted from default exports.
For `approved_with_conditions`, human-subject dataset registration additionally
requires `metadata.ethics_condition_discharge` and `--ethics-artifact-root`.
The discharge must cover every frozen condition exactly, bind each satisfied
condition or active control to verified evidence bytes and an inspectable
location, and cannot predate review or postdate registration. Active controls
must declare `valid_through`; run intake refuses analyses completed after that
horizon. Evidence artifacts declare a media type; for `application/json`, the
location must be an absolute JSON Pointer that resolves in the verified bytes
and Faraday records a digest of the selected value. Other formats retain an exact
human-inspectable location without pretending to parse them. These checks enforce documented obligations without claiming the
assessor's identity or the truth of the compliance judgment.
The service-generated dataset verification retains the condition-evidence root.
Inquiry display and every run replay the complete original discharge validation
from the preserved receipt and present bytes, including coverage, chronology,
media types, JSON Pointers, selected-value hashes, and the integrity report.
Anything that no longer reproduces exactly fails closed. Default replication
exports redact this operational root.
Later review changes are append-only rather than edits to the frozen protocol:

```bash
./research --workspace /path/to/experiment --json ethics record-status \
  --protocol PROTOCOL_ID --status suspended \
  --effective-at 2026-09-06T14:00:00Z \
  --reason "Safety review pending" \
  --review-artifact-locator suspension.json \
  --review-artifact-sha256 TRUSTED_HASH \
  --review-artifact-root /path/to/review-events
```

Statuses are `active`, `suspended`, `withdrawn`, or `expired`; an active renewal
may declare `--expires-at`. Every event verifies its evidence bytes, binds the
frozen protocol, receives a monotone sequence, and must supersede the exact
latest event. Dataset and run intake recompute current clearance and reject
non-active or expired states. Protocol-bound execution performs the same check
before invoking an analysis method and embeds the resulting ethics receipt in
the execution design check. Provider-neutral collaborator context includes the
event history so an app or optional LLM cannot silently overlook a suspension.
Every local use re-hashes each status-review artifact and recomputes its complete
integrity receipt; a stale `passed` flag is insufficient. Default replication
exports redact both the artifact locator and retained local root, while package
verification checks the hash-covered event semantics without claiming access to
the originating institution's private review files.
Protected dataset derivation is also protocol-closed: confirmatory or replication
sources must be bound to the exact same frozen protocol as the derived dataset.
Matching roles alone are insufficient. This prevents human data, consent scope,
review conditions, or prospective analysis commitments from being laundered
through another protocol or amendment.

Non-synthetic confirmatory and replication datasets must also prove that their
declared observation artifacts exist at registration. Supply `--artifact-root`;
Faraday hashes the current bytes, checks size commitments, and stores a
service-generated verification receipt containing the resolved local root,
artifact-set digest, frozen protocol hash, actor, and time. Inquiry display,
protocol-bound execution, and run intake recompute that receipt from current
bytes and require exact equality. Missing, replaced, relocated, or symlinked
observations fail closed. Synthetic fixtures remain exempt only because they are
categorically ineligible to support scientific evidence. Default replication
exports redact the operational root.

## Measurement custody

Instrument add-ons may expose bounded `InstrumentAdapter` inspectors. Run one
with `measurement inspect-source --adapter ADAPTER_ID --source-file FILE
--media-type TYPE --config-file CONFIG --output DIRECTORY`. Faraday requires the
type to match the adapter's declared supported media types, snapshots and hashes the bytes,
hashes the actual adapter implementation module, rejects source, implementation,
or config mutation during inspection, validates the adapter's declared output
shape, and writes a non-evidentiary acquisition-metadata proposal.
Adapters cannot pass calibration, clear gates, register a dataset, or authorize
evidence; their proposed raw-source entry must still enter the custody workflow
below. `measurement verify-source-inspection` takes an independently trusted
record hash and exactly reproduces the record from current source, config, and
adapter-code bytes. No model or network service is involved.

Protected datasets may bind a raw-to-derived custody receipt to a frozen
protocol. A receipt names immutable raw-source hashes, ordered and
implementation-hashed transformations, passed calibration results, passed
quality gates, and the exact transformation output behind each derived
observation. Custody-bearing protocols freeze quantitative calibration criteria
(criterion and calibration IDs, quantity, unit, rationale, and lower and/or
upper bounds). Registration checks the observed value and unit against those
bounds; a written `passed` status alone is insufficient. A protocol with calibration requirements must name the custody
gates that clear registration. Protected registration now also requires
`--custody-artifact-root`: each transformation names its implementation and
output locators, and Faraday verifies raw-source, implementation, derived-output,
and supporting-evidence bytes. It persists the resulting integrity report, receipt hash, protocol hash,
actor, and verification time inside the immutable dataset manifest.
Stable protocol quality-gate, required custody-gate, calibration criterion,
calibration, transformation, gate, and derived-observation IDs must be unique
after trimming whitespace, so cosmetic padding cannot split one custody node
into apparently separate provenance records.
Offset-aware transformation, gate-evaluation, and derived-observation times must
also follow their declared input and calibration prerequisites. This establishes
internal chronology, not an externally authenticated timestamp.
Measurement gates must cite the exact raw or derived artifact hashes they
evaluate, and every derived observation must name the passed gates that clear its
specific transformation output. A valid gate from another artifact cannot be
reused as authorization. Calibration-prerequisite and clearing-gate references
are normalized before uniqueness and coverage checks, so whitespace padding
cannot create a second apparent prerequisite or gate link. Required custody-gate
and frozen calibration IDs are normalized at the same boundary before receipt
coverage is accepted.
The receipt can be inspected before registration without any network service
or LLM:

```bash
./research --workspace /path/to/experiment --json measurement template \
  --protocol PROTOCOL_ID

./research --json measurement validate --receipt-file custody-receipt.json \
  --require-gate clock-sync --artifact-root /path/to/custody-artifacts

./research --workspace /path/to/experiment --json measurement record \
  --protocol PROTOCOL_ID --receipt-file custody-receipt.json \
  --expected-receipt-sha256 TRUSTED_HASH \
  --artifact-root /path/to/custody-artifacts --output custody-record

./research --workspace /path/to/experiment --json measurement verify-record \
  --protocol PROTOCOL_ID \
  --record-file custody-record/measurement-custody-record.json \
  --expected-record-sha256 TRUSTED_RECORD_HASH \
  --receipt-file custody-receipt.json \
  --artifact-root /path/to/custody-artifacts

./research --json dataset register --manifest-file dataset.json \
  --artifact-root /path/to/registered-observations \
  --custody-artifact-root /path/to/custody-artifacts
```
The template command derives required gate IDs, calibration IDs, units, and
acceptance bounds from the frozen protocol. It emits skipped gates and explicit
placeholders, writes no state, and never converts expected behavior into an
observed result. The record command creates a write-once artifact only after
matching the independently supplied receipt hash, the exact frozen protocol,
its gate and calibration commitments, and every referenced local byte. It does
not register data or create scientific evidence; later dataset registration
still repeats the custody checks against canonical state. `verify-record`
requires an independently trusted record hash and recomputes the original
receipt-byte binding, frozen protocol commitments, structured custody rules,
and present artifact bytes; merely retaining the generated record is not treated
as proof that its inputs remain intact.
Canonical protected dataset registration also retains the local custody root.
Inquiry display, protocol-bound execution, and run intake replay the complete
custody validator and current-byte verification from the preserved receipt, then
require exact equality with the original service-generated result. Changes to
raw data, transformation code, derived output, calibration evidence, or gate
evidence therefore fail closed. Default replication exports redact the root.

## What works now

- Create and select inquiries from an initial statement such as “I think …”.
- State the practical decision an inquiry should support, its minimum evidence,
  decision owner, and observations that would change the decision.
- Record and answer clarifying questions.
- Build a claim hierarchy from measurement validity through attribution/intent.
- Seal each claim’s stable proposition and each hypothesis’s scientific content
  when created. Explicit review, staging, activation, assessment, and retirement
  fields may evolve, but out-of-band edits to the underlying proposition fail
  even before a protocol or evidence record references it.
- Keep documented facts, source claims, project interpretations, reasonable
  inferences, and unresolved claims in explicit epistemic layers, with source,
  conflict, falsification, confidence, and review metadata.
- Propose structured hypotheses as unreviewed candidates.
- Prevent incomplete hypotheses from entering the active model set.
- Support an auditable `pending_review` lane for delegated autonomous
  exploration without representing agent confidence as human approval.
- Register immutable, content-hashed datasets with roles that prevent
  exploratory/confirmatory leakage.
- Seal each complete dataset manifest with a service-generated commitment, not
  only its artifact list. Authoritative reads and run intake reject later edits
  to role, synthetic status, protocol binding, lineage, observation unit,
  attestations, metadata, artifact declarations, or descriptive identity.
- Draft, amend, and hash-freeze observational, experimental, computational,
  formal, literature, and synthesis protocols.
- Bind each frozen protocol to the complete scientific content of every tested
  hypothesis, not merely its ID. Later retirement and evidence-assessment changes
  remain possible, but changing the registered prediction, null, competitors,
  estimand, scope, expected direction, confounds, or decision boundaries fails.
- Optionally bind every primary, secondary, and control outcome to a typed
  measurement contract whose parameters, evaluation point, convention,
  aggregation, tolerance, and expected behavior are freeze-validated.
- Record code-, environment-, input-, output-, and quality-gate-bound runs.
- Seal every canonical run with a service-generated commitment over the complete
  immutable payload. Authoritative reads reject later edits to its protocol or
  dataset links, chronology, gates, deviation disclosure, eligibility, outputs,
  metadata, or summary before those changes can affect evidence or synthesis.
- Require an explicit protocol-deviation disclosure before a run can become
  evidence-eligible; preserve declared departures with output-bound support and
  block their automatic promotion without erasing the run.
- Generate exact frozen quality-gate templates and preflight complete run
  records without consuming a run ID or appending a ledger event.
- Re-hash returned run artifacts, validate a hash-pinned clean-room attestation
  schema, and cross-check the attestation against the proposed run before an
  independent-replication record can enter the ledger.
- Treat current output bytes as a prerequisite for scientific evidence, not an
  optional archival check. Runs without a passed local artifact verification may
  be recorded for audit but remain evidence-ineligible. Faraday retains the run
  artifact root and replays the exact receipt before evidence admission,
  inquiry display, rigor audit, and synthesis. Evidence records preserve the
  admission-time protocol, dataset, output, and ethics checks without claiming
  that these checks validate scientific interpretation. The receipt also
  commits every immutable evidence field, so later changes to direction, scope,
  uncertainty, tags, selectors, claim linkage, or wording invalidate it.
- Reject runs that predate their canonical protocol registration unless a
  hash-verified external protocol, analysis source, and zero-execution freeze
  manifest establish an explicitly attested external-freeze accession.
- Prevent failed or synthetic runs from becoming confirmatory evidence.
- Rank feasible, safety-approved next actions with an explicit utility function.
- Attach evidence only after a hypothesis has been reviewed and activated;
  confirmatory evidence must trace to an eligible recorded run.
- Bind admitted scientific evidence to the referenced claim’s immutable
  proposition—statement, inference level, scope, parent structure, identity, and
  creation time. Later epistemic review, confidence, source, conflict,
  falsification, disposition, and ownership updates remain possible, but cannot
  silently rewrite what the evidence was admitted to support or challenge.
- Append artifact-backed qualifications, withdrawals, and terminal retractions
  without altering original evidence; current syntheses exclude restricted
  records from capability and conclusion calculations while displaying the full
  correction history.
- Require every new evidence record to state its scope, uncertainty, explicit
  claim ceiling, and machine-validated capability tags.
- Reject unsupported replication, known-result reproduction, novel-prediction,
  and empirical-test labels rather than accepting them as self-attestations.
- Publish a deterministic epistemic audit and conservative conclusion ceiling in
  every synthesis.
- Retire hypotheses without erasing them, including rejection type, limitations,
  lineage, and resurrection conditions.
- Build deterministic, claim-scoped Markdown syntheses.
- Record every state-changing command in a hash-chained append-only ledger and
  detect later tampering.
- Statically compare a notebook's literal dependency mapping, a strict JSON
  manifest, and actual file bytes before a protected kernel is launched.
- Probe the selected interpreter, Jupyter kernel, and working directory with one
  fixed generated marker cell before protocol freeze, without accepting or
  loading an analysis notebook.
- Emit stable JSON for Codex today and other clients later.
- Discover validated scientific add-ons without creating a second evidence
  system, and execute bundled cross-disciplinary analyses with hash-bound,
  write-once receipts.

The distribution is self-contained for the scientific lifecycle and includes a
small general-science execution toolkit. Specialized statistics, proof checkers,
sensor pipelines, and literature retrieval extend it as add-ons. They do not
replace its canonical inputs, commitments, gates, evidence rules, or provenance
model.

Inspect extensions with `research addon list`. Local experiment repositories can
be connected without publishing or installing a package by passing
`--addon-path /path/to/addon`. Run a bundled, deterministic CSV analysis with
`research analysis run`; see [scientific add-ons](docs/addons.md)
and the [scientific platform roadmap](docs/scientific-platform-roadmap.md).

An optional domain-neutral notebook executor is included for protected local
calculations. Unlike `nbconvert`'s default failure path, it atomically writes the
partially executed notebook and an execution receipt when a later cell raises,
then exits nonzero. A failure before runtime or kernel launch writes a
`pre_execution_failure` receipt with `kernel_started: false` and no executed
notebook. It refuses to overwrite prior output or receipts and can enforce the
frozen source hash:

```bash
pip install -e '.[notebook]'
research-notebook frozen-source.ipynb executed.ipynb \
  --result-json execution-receipt.json \
  --expect-source-sha256 <frozen-sha256> \
  --dependency-manifest notebook-dependencies.json \
  --expect-dependency-manifest-sha256 <manifest-sha256> \
  --working-directory <project-root>
```

The same dependency check should run before protocol freeze. It parses one
literal `EXPECTED_HASHES` assignment with Python's AST but never executes a
notebook cell, then compares that mapping with the manifest and the actual
files:

```bash
research-notebook-preflight frozen-source.ipynb \
  --manifest notebook-dependencies.json \
  --workspace-root <project-root> \
  --expect-source-sha256 <frozen-sha256> \
  --expect-manifest-sha256 <manifest-sha256> \
  --result-json preflight-report.json
```

The manifest schema, fail-closed rules, and scope limits are documented in
[docs/notebook-dependency-preflight.md](docs/notebook-dependency-preflight.md).

Static integrity does not prove that the interpreter has the notebook extras or
that the process boundary permits a kernel. Run the separate runtime preflight
before freezing a scientific protocol:

```bash
research-notebook-runtime-preflight \
  --result-json runtime-preflight.json \
  --working-directory <project-root> \
  --kernel-name python3 \
  --timeout 30
```

This command accepts no source notebook and no arbitrary code. It starts the
requested kernel, runs one built-in marker cell, verifies the kernel working
directory, shuts the kernel down, and writes a non-overwriting report. Its
contract and limitations are documented in
[docs/notebook-runtime-preflight.md](docs/notebook-runtime-preflight.md).

The receipt is an executor artifact, not canonical evidence. A client still
records the resulting hashes and quality gates through `research run record`.

Independent-replication returns receive an additional fail-closed intake. The
same local artifact root and pinned attestation schema must be supplied to both
preflight and record commands; details and the supported schema profile are in
[docs/replication-return-intake.md](docs/replication-return-intake.md).

## Quick start

No installation or network access is required during development:

```bash
cd /Users/admin/dev/faraday
./research --workspace .research workspace init
./research --workspace .research inquiry create \
  --id ai-hiring-bias \
  --title "AI hiring bias" \
  --statement "I suspect persistent group disparities in AI hiring decisions." \
  --decision "Whether to commission an independent audit." \
  --decision-owner "project owner" \
  --minimum-evidence "Reproducible outcome disparities on independently checked records." \
  --change-criterion "Do not commission if a powered audit excludes the decision-relevant disparity."
./research --workspace .research question add \
  --text "Which hiring stage, population, outcome, and period are in scope?"
./research --workspace .research --json inquiry show
```

Global flags (`--workspace`, `--actor`, and `--json`) precede the command group.
Use `./research --help` and `./research <group> --help` for the complete command
surface.

For a structured hypothesis:

```bash
./research --workspace .research --json hypothesis propose \
  --proposal-file examples/hypothesis-proposal.json
./research --workspace .research --json hypothesis list --state unreviewed
```

Activation is a distinct review gate:

```bash
./research --workspace .research hypothesis activate <hypothesis-id>
```

An activatable hypothesis must define an observable prediction, at least one
falsification condition, and either a null model or competing model. Generated
proposals are never activated automatically.

When a person delegates provisional exploratory review, a complete hypothesis
may be staged without activation:

```bash
./research --workspace .research hypothesis stage <hypothesis-id> \
  --confidence high \
  --rationale "Complete competing hypothesis; exploratory work is reversible."
```

`pending_review` hypotheses may anchor frozen **exploratory** protocols and
receive exploratory evidence. Confirmatory or replication protocol freezes and
confirmatory evidence still require activation after human review.

The general execution loop uses JSON contracts:

```bash
./research --workspace .research protocol create --spec-file examples/formal-protocol.json
./research --workspace .research protocol freeze <protocol-id>
./research --workspace .research run template --protocol <protocol-id>
./research --workspace .research run preflight --record-file examples/run-record.json
./research --workspace .research run record --record-file examples/run-record.json
./research --workspace .research evidence record \
  --hypothesis <hypothesis-id> --direction supports \
  --summary "The registered check passed." --run <run-id> \
  --scope "The registered bounded system only." \
  --uncertainty "Limited to the pinned implementation." \
  --control-passed "The registered negative control failed as expected." \
  --higher-conclusion-unsupported "The model is empirically correct." \
  --validation-tag internal_consistency \
  --validation-tag controlled_benchmark --confirmatory
./research --workspace .research next-action recommend \
  --spec-file examples/next-actions.json
./research --workspace .research next-action portfolio \
  --spec-file examples/next-action-portfolio.json
./research --workspace .research cross-lane-lesson record \
  --spec-file examples/cross-lane-lesson.json
./research --workspace .research workspace audit --fail-on error
```

Replace the placeholder IDs and hashes in the examples with values from the
active inquiry and the actual code, environment, and artifacts.

Use `next-action portfolio` when independent workstreams must advance in the
same cycle. It validates explicit action dependencies, selects one safe and
currently feasible action per active lane, and fails rather than borrowing a
second action from another lane. Externally blocked lanes must be marked
`blocked` with a nonempty `blocked_on` reason. Infrastructure actions may name
typed `information_targets` instead of pretending to distinguish a scientific
hypothesis. The resulting recommendation remains an immutable, ledgered record;
it does not establish scientific independence or satisfy a promotion gate.

Use `cross-lane-lesson record` before an observed machine or substantive
failure changes later work. A lesson must preserve the origin hash, strongest
alternative explanation, failure class, challenged invariant, first permitted
future versions, prohibited retroactive targets, proposed repair, falsifier,
and conclusion ceiling. The future and prohibited version sets must be
disjoint. A lesson is process state only: recording one does not create
evidence, change an old verdict, or raise a synthesis conclusion ceiling.

`run template` and `run preflight` are read-only. The template deliberately
contains invalid placeholders and skipped gates so it cannot be mistaken for an
observed result. The preflight uses the same validation and status construction
as `run record`, predicts whether submission would be completed or invalid, and
exits nonzero for a would-be invalid record. See
[docs/run-record-preflight.md](docs/run-record-preflight.md).

## Codex-first workflow

1. The person states a curiosity or suspicion in natural language.
2. Codex creates an inquiry and records ambiguity as explicit questions.
3. The person and Codex clarify scope, constructs, population, outcomes, time,
   and what evidence could change the person's mind.
4. Codex creates a claim map and proposes a diverse competing-model set.
5. The person reviews proposals before activation. If autonomous exploratory
   review was delegated, Codex may stage complete candidates as `pending_review`
   under the restrictions above.
6. Freeze a protocol before protected data are inspected, then record the actual
   run with code/environment hashes, input roles, output hashes, and quality gates.
   Tests that require the physical world remain proposed work until an external
   executor returns real artifacts.
7. Hypotheses are refined, parked, or retired with reasons and resurrection
   conditions. The next experiment should discriminate among survivors.
8. A deterministic synthesis reports what was and was not established, including
   the highest defensible conclusion ceiling and missing maturity capabilities.

See [AGENTS.md](AGENTS.md) for the operating contract and
[docs/architecture.md](docs/architecture.md) for the dependency boundaries. The
provider-neutral JSON contracts live in [schemas](schemas), and the fuller
conversational loop is in [docs/codex-playbook.md](docs/codex-playbook.md).
The design ideas recovered indirectly from probably deleted Cursor histories,
and the limits of that provenance, are recorded in
[docs/recovered-cursor-method.md](docs/recovered-cursor-method.md).

Substantive experiments and domain acceptance campaigns live in separate
repositories. This repository contains only the machine, discipline-neutral
tools, schemas, and synthetic software-invariant fixtures.

## Workspace layout

```text
.research/
  workspace.json
  inquiries/<inquiry-id>/
    inquiry.json
    questions.json
    claims.json
    drafts/hypotheses/
    hypotheses/{pending_review,active,parked,retired}/
    datasets/
    protocols/{draft,frozen}/
    runs/
    recommendations/
    cross_lane_lessons/
    evidence/
    reports/
    ledger.jsonl
```

JSON files are canonical application state. `ledger.jsonl` is append-only and
must never be hand-edited. Registered datasets, protocols, runs, evidence, and
recommendations are immutable records; amendments create new protocol versions.

## Development

```bash
pytest
python -m compileall -q src tests
```

The package has no runtime dependencies. It supports Python 3.11 and newer.

## Epistemic validation tags

Evidence is classified by what it actually tests: `source_assessment`,
`calibration`, `internal_consistency`, `controlled_benchmark`,
`independent_replication`, `known_result_reproduction`, `novel_prediction`, or
`empirical_test`. Higher tags have enforceable prerequisites. In particular,
independent replication must name an eligible earlier run through
`metadata.replicates_run_id`, use a different executor identity, and use a
different analysis-code hash. It must also declare a clean-room design with
executor and implementation independence, an explicit prior-code-access status,
a hashed allowed-input manifest, contamination disclosures, and a hashed output
artifact carrying `artifact_role=independence_attestation`. Before recording,
the local artifact bytes and sizes must match the declarations, the attestation
must satisfy a committed schema, and its core fields must agree with the run.
A different actor string plus a cosmetic code edit is therefore insufficient. Known-result
reproduction requires a passed `known-result-reproduction` quality gate. Novel
predictions and empirical tests require active hypotheses and protected
non-exploratory runs; empirical tests also require non-synthetic observational
or experimental data.

`workspace audit` reports errors, warnings, the capability vector, and a
conservative conclusion ceiling. Use `--fail-on error` in CI. Warnings remain
visible for scientifically missing capabilities—such as absent independent
replication—without making unfinished research impossible to commit.
`structurally_valid=true` means only that no internal audit contradiction was
found; it is not a scientific-success flag.

## Design principle

> The machine does not search for evidence that its current story is true. It
> maintains multiple explanations, constructs experiments capable of making
> those explanations disagree, and preserves an auditable record of every
> inferential step.
