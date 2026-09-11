# Codex operating contract

This repository is the current interface to Research Machine. Treat the human
conversation as the exploratory front end and the `research` command as the
canonical write path.

## Start of an inquiry

1. Translate “I think …” into an inquiry without strengthening it.
2. Identify the practical decision, minimum evidence, decision owner, and
   observations that would change the decision. If these are not yet known,
   leave them visibly unresolved rather than inventing them.
3. Record important ambiguity as questions before proposing a preferred answer.
4. Clarify population, setting, construct, outcome, time window, comparison,
   available data, ethical constraints, and what observation would change the
   user's mind.
5. Separate observation from statistical association, causality, mechanism,
   adaptation, attribution, and intent by creating claim-level nodes.

## Hypotheses

- Give every new claim and hypothesis a service-generated scientific-content
  seal. For claims, protect identity, statement, level, creation time, parents,
  and scope while leaving explicit epistemic review fields mutable. For
  hypotheses, protect the full scientific payload while leaving workflow,
  evidence assessment, replication status, and retirement mutable. Validate
  seals before review or lifecycle transitions and on authoritative reads.
- Generate competing model sets, including measurement error, selection,
  confounding, mundane process, and the user's favored explanation where
  relevant. Do not optimize for novelty or excitement.
- Submit generated candidates as `unreviewed`. Never activate one merely because
  Codex generated it.
- When the user delegates autonomous exploratory review, Codex may move a
  complete proposal to `pending_review` only with an explicit high-confidence
  rationale. Pending hypotheses may receive exploratory evidence and may anchor
  frozen exploratory protocols, but they are not active, human-reviewed, or
  eligible for confirmatory/replication protocol freezes or evidence.
- Before activation, require an observable prediction, falsification condition,
  and a null or competing model. Prefer explicit scope, estimand, confounds,
  controls, and boundary conditions.
- At protocol freeze, commit the scientific payload of every tested hypothesis,
  including provenance, statement, observable prediction, null and competing
  models, scope, estimand, expected direction, covariates/confounds, and
  falsification/support/boundary conditions. Exclude only legitimate workflow,
  evidence-assessment, replication, and retirement lifecycle fields. Validate
  these commitments on frozen-protocol reads, amendment, run intake, and evidence
  admission; an identifier alone is not a prospective hypothesis commitment.
- Use `lineage` when a proposal revises, narrows, or replaces another hypothesis.
- Never delete a rejected hypothesis. Retire it with a typed reason, limitations,
  and concrete resurrection conditions. Use `superseded_by` when applicable.

## Evidence and reporting

- Use the CLI/application service for all canonical changes. Do not edit state
  JSON by hand and never edit `ledger.jsonl`.
- Use `design precision` for a prespecified interval-width target and `design
  power` only for its declared equal-independent-group normal approximation.
  Power inputs must include a smallest effect of interest and explicit variance,
  alpha, target-power, alternative, and attrition assumptions. Preserve
  researcher-supplied sensitivity scenarios; never portray either calculator as
  causal identification, measurement validation, achieved power, or automatic
  authorization to freeze a protocol.
- Do not treat conventional difference-test power as power for a practical-
  significance conclusion. Use `design practical-power`, supply a true effect
  strictly beyond the frozen threshold, and power the registered directional
  confidence bound clearing that threshold. Bind it only to a direct
  `single_test`; preserve its conditional assumption and sensitivity scenarios.
- Guided designs must distinguish a measurement unit from its scale type and
  retain the observed-value domain separately from missing-value codes. Reject
  overlapping encodings, invalid binary/range declarations, and structured
  analysis families that are incompatible with the declared outcome scale;
  never infer a numeric scale from labels or free-text units.
- Guided primary measurements must also preserve input condition, fixed
  string-valued parameters, evaluation point, coding convention, aggregation,
  tolerance, expected behavior, and temporal role. Treat missing confirmatory
  fields as blocking and require causal primary outcomes to be post-exposure;
  an emitted draft is not evidence that the measurement is valid.
- Keep the exact primary observable separate from the construct-validity plan.
  Require both; never populate `observable` with prose about calibration,
  agreement with a reference, or other evidence that the measurement is valid.
- Confirmatory guided designs must give primary-measurement validity a typed
  prospective plan: stable check ID, evidence type, exact validity claim,
  assessment procedure, acceptance criterion, failure response, and dedicated
  required gate. Never treat the plan itself as a passed validity assessment,
  and never reuse its gate for controls, causal assumptions, or missingness.
- Canonical measurement-validity checks must bind the exact protocol
  `measurement_id`, survive protocol serialization, participate in the frozen
  protocol hash, and name a unique required gate. Reject unknown measurements,
  unsupported evidence types, duplicate checks, and cross-purpose gate reuse.
- Every performed measurement-validity gate must report exact results for its
  frozen checks: observed diagnostic, interpretation, constrained disposition,
  frozen evidence type, output digest, and exact location. Passed requires
  `consistent_with_validity_claim`, warning requires `inconclusive`, and failed
  requires `contradicted_validity_claim`; preserve all outcomes and never call
  consistency proof that the construct is valid. When the cited, locally
  verified output is JSON, require the exact location to be an absolute JSON
  Pointer that resolves in those bytes; a correct file hash cannot excuse a
  fabricated internal location.
- Rigor and deterministic synthesis must expose frozen validity claims,
  assessment dispositions, observed diagnostics, interpretations, artifact
  locations, and failure responses. Flag protected empirical protocols lacking
  typed validity checks, inconclusive checks as warnings, and contradicted
  validity claims as errors; never let a numerical result hide them.
- Evidence records must derive, never accept from callers, the ordered IDs of
  frozen measurement-validity checks whose artifact-bound run results were
  `consistent_with_validity_claim`. Replay that binding during admission, and
  reject supporting evidence for a measurement-validity claim when no exact
  consistent frozen check is attached.
- Never hardcode or infer the primary outcome's dataset column. Require every
  executable primary, secondary, and control measurement column to be explicit,
  case-insensitively unique, and distinct from identity, assignment, and
  capture-time columns.
- When an independent unit is declared, require its exact stable identifier
  column and propagate that same name through the protocol, data dictionary,
  collection plan, and later analysis contract. Never let a display default
  silently disagree with the executable unit binding.
- Require exact ordered typed-measurement coverage for every guided secondary
  outcome before treating its multiplicity plan as design-complete. Reject
  omissions, duplicate targets, renamed or invented surrogates, malformed value
  domains, and missing scientific semantics; never infer secondary measurement
  contracts from outcome labels.
- Require one exact ordered measurement definition for every guided control in
  addition to its family, purpose, expectation, and evaluation gate. Permit an
  explicit artifact-evaluated form without a data column, but reject partial
  column typing. Never treat expected control behavior as an observed pass.
- Keep causal intent separate from assignment mechanism. Only explicit
  randomized assignment may yield an experimental scaffold; observational
  causal designs must remain observational, define the measured exposure, and
  preserve their identification assumptions. Never infer randomization from a
  causal question or from the presence of a comparison group.
- Confirmatory guided designs must freeze the intended estimand, signed contrast
  order, expected direction, numeric null, uncertainty-aware support rule, and
  interval level as separate structured fields. Reject point-only support and
  equivalence/difference-rule conflicts; free-text analysis prose must never be
  allowed to conceal post-result contrast reversal or decision-rule selection.
- Preserve guided estimand, contrast, and expected-direction fields when creating
  or revising canonical hypotheses. The signed contrast is part of the sealed
  scientific proposition; do not leave it only in a draft artifact or bury it
  in free-text provenance.
- Once a hypothesis or analysis contract declares `contrast_definition`, require
  the other to declare the exact same signed contrast and require the executable
  specification to match it. Preserve it in execution results and receipts;
  never infer or reverse group order after observing outcomes.
- Pair every newly declared prose contrast with exactly two distinct ordered
  `contrast_groups`. At protocol freeze, require hypothesis contrast order,
  analysis-contract contrast order, and executable `groups` order to be exactly
  identical; derive runtime receipt order from the executed groups.
- Pair every guided two-level contrast with an explicit comparison or exposure
  data column. Propagate it into the protocol draft, data dictionary, and
  analysis commitment; reject collisions with measurement or identity fields
  and require causal designs to use the audited exposure column exactly.
- A guided `sample_size_plan` must be deterministically recomputed and remain
  untargeted until canonical hypothesis, measurement, and unit IDs exist. Reject
  invalid receipts, premature target claims, conventional difference power used
  for practical-significance conclusions, and direction/equivalence mismatch.
  Cross-check analysis design, analyzable count, attrition/exclusion thresholds,
  alpha, confidence level, effect threshold, and multiplicity method. Never
  present a planning receipt as achieved power or design validity.
- A protocol `sample_size_plan` must be rebuilt by the core from its strategy,
  specification, and justification. Bind the versioned receipt into the protocol
  hash. Evidence-bound plans must name the analysis contract's exact primary
  hypothesis, measurement, and unit. Reject altered calculations, target or
  unit mismatches, disagreement with the conclusion contract's smallest effect,
  anticipated attrition above the frozen exclusion ceiling, or any composite
  adjudication that lacks the primary execution's registered information check;
  also reject planning/inference alpha, direction, or confidence-level conflicts,
  analysis-design conflicts, and disagreement between its analyzable per-group count and
  `analysis_contract.minimum_analyzable_units` for independent groups.
  For precision plans, compute achieved half-width only from the verified
  registered primary interval. Preserve a miss as evidence, flag it in rigor,
  disclose it in synthesis, and never equate planned precision with achieved
  precision.
  Treat attrition above the planning assumption but within frozen total and
  group-difference ceilings as an observed planning miss: retain the evidence,
  emit a rigor warning, and disclose group-specific rates in synthesis.
  Evidence-bound two-group plans require the registered independent mean-
  difference estimator. Preserve its observed pooled SD and the
  observed-to-assumed ratio, but never label the variance assumption adequate
  or compute observed power without a prospectively registered rule. If a plan
  declares `maximum_observed_to_assumed_sd_ratio`, apply that exact threshold,
  retain exceedances as evidence, and surface them in rigor and synthesis.
  Warn when a protected empirical protocol has only prose planning, because
  unsupported census, sequential, clustered, or repeated-measures designs need
  future typed strategies rather than a fabricated two-group calculation.
- Evidence belongs to an exact hypothesis and, when possible, an exact claim.
  Record the run (or exploratory dataset), analysis identity, uncertainty,
  controls, unsupported higher-level conclusions, and at least one validation
  tag. New evidence without a scope, uncertainty statement, claim ceiling, or
  validation tag must fail closed.
- Treat validation tags as claims with prerequisites, not labels of convenience.
  Independent replication requires a named earlier run, a different executor,
  and a different code hash. Empirical tests require non-synthetic observations
  under an observational or experimental confirmatory protocol.
- Never promote support at one claim level to a higher one. Association does not
  imply causal direction; causality does not establish mechanism or intent.
- When scientific evidence references a claim, include a digest of the claim’s
  immutable proposition in the admission receipt: ID, statement, inference
  level, creation time, parent claims, and scope. Exclude reviewable epistemic
  layer, disposition, confidence, sources, conflicts, falsifiers, review time,
  and decision owner. Recompute the proposition digest on authoritative reads so
  review can evolve without allowing post-admission claim drift.
- Multiple-testing adjustment must operate on an exact prespecified family, not
  whatever rows happen to be supplied. Require stable unique family member IDs
  and reject missing, substituted, duplicate, or extra members before adjustment.
  Treat adjusted values as arithmetic conditional on the supplied valid tests and
  family; they do not establish prospective chronology or a correct family choice.
- Keep a claim's epistemic layer separate from its disposition. A source's claim
  is not a documented fact, and an accepted project interpretation does not
  become one through repetition. Record conflicts rather than reconciling them
  rhetorically; accepted conflicting claims must fail the rigor audit.
- Preserve exploratory/confirmatory separation. Register artifact hashes once;
  do not relabel them. Freeze protected protocols before their observations are
  registered. Confirmatory evidence must trace to an eligible quality-gated run.
- Seal every canonical dataset after its derived synthetic status, verified
  artifact/custody/ethics receipts, role, protocol binding, lineage, and other
  fields are final. Exclude only the seal from its own digest, reject
  caller-supplied seals, and replay it on authoritative reads and before any run
  uses the dataset. An artifact hash does not protect scientific classification.
- A run may not predate its canonical protocol registration unless it is
  explicitly accessioned from an external pre-execution freeze. Preserve and
  locally verify the external protocol, analysis source, and zero-execution
  freeze manifest; record that their chronology remains an attestation rather
  than a cryptographically authenticated timestamp.
- Seal every run payload after all service-generated checks are attached, while
  excluding only the seal itself from the digest. Reject caller-supplied seals
  and validate the retained commitment for every run on authoritative reads and
  again before evidence admission. Artifact receipts alone do not protect gate,
  chronology, dataset-link, eligibility, deviation, or summary fields.
- Keep execution quality separate from scientific direction. Required quality
  gates cover integrity, provenance, measurement availability, controls being
  evaluated, and faithful application of the frozen decision rule. Desired
  values or hypothesis-supporting outcomes belong in success and falsification
  conditions; a valid null, adverse, or partial result must remain eligible for
  evidence with the appropriate direction.
- Never infer protocol adherence from silence. Every evidence-eligible run must
  explicitly declare either no deviations or a typed, complete deviation list.
  Preserve each departure's frozen commitment, actual method, reason, timing,
  potential impact, corrective action, and exact output-bound evidence. Any
  declared departure remains recordable but blocks automatic evidence promotion;
  a no-deviation declaration is still an unauthenticated assertion, not proof.
- A passed gate and declared output hash are insufficient for evidence
  eligibility. Require a local artifact root, verify every run-output byte, and
  retain the service-generated root and exact integrity receipt. Recompute that
  receipt before evidence admission, inquiry display, rigor audit, or synthesis;
  missing, moved, symlinked, or changed outputs fail closed. Evidence must retain
  the protocol, dataset, output, and current ethics checks performed at admission.
  Bind the receipt to the complete immutable evidence payload so later edits to
  its direction, scope, uncertainty, classification, selectors, or prose fail.
  Redact local roots and attestation-schema paths from default exports.
- For executable two-group analyses, freeze both a total-exclusion ceiling and a
  maximum absolute difference between group-specific exclusion fractions.
  Recompute both from the structured result, reject exclusions whose comparison
  group is unavailable, require conservation between total, included, grouped,
  and ungrouped counts, and bind the observed rates into the receipt. Passing
  these thresholds does not establish ignorable missingness or absence of
  selection bias.
- A complete-case analysis contract must state the scientific missingness
  assumption, prospective assessment plan, typed assessment kind, failure
  response, and a dedicated required gate that is not reused for controls or
  causal assumptions. Every performed gate must retain an exact artifact-bound
  result whose disposition agrees with passed/warning/failed status. Treat
  `consistent_with_assumption` as a bounded diagnostic outcome, never proof that
  missingness is ignorable.
- A passed quality gate must cite `details.evidence_sha256` for an output artifact
  of that exact run. If it declares `prerequisite_gate_ids`, every referenced gate
  must exist and pass. A summary or downstream assertion is not a prerequisite
  receipt.
- A passed control-evaluation gate must preserve exact results for every mapped
  control, including an artifact digest and exact evidence location. When the
  cited artifact is the verified Faraday analysis result, require an absolute
  JSON Pointer that resolves in those bytes. Preserve unexpected control behavior
  as a scientific outcome and require downstream disclosure; do not redefine it
  as an execution-gate failure.
- When a control's conclusion depends on one quantitative comparison, optionally
  freeze a scalar `witness_contract` with the exact intervention, CONTROL-role
  measurement, comparator, and finite non-Boolean reference value. Require the
  selected JSON object to repeat those identities, carry the finite observed
  value, and retain a decision recomputed by the core and equal to
  `matches_expected`. A bare Boolean is not a witness. Collapse a compound
  condition into one prospectively defined signed scalar margin or register
  multiple named controls. This strengthens observable custody and
  inspectability; it cannot prove that producing code was not hardcoded.
- Evidence derived from a run with typed controls must exactly partition every
  frozen registered control into `controls_passed` or `controls_failed` according
  to that run's structured `matches_expected` results. Reject omissions,
  duplicates, invented names, and contradictory classifications.
- Never rewrite or delete accepted evidence when a flaw is discovered later.
  Append an artifact-verified status event (`active`, `qualified`, `withdrawn`,
  or terminal `retracted`) bound to the exact evidence record. Require a linear
  sequence, exact latest predecessor, timezone-aware effective time, and local
  review-artifact hash verification. Qualified, withdrawn, and retracted records
  remain visible but must not contribute to current rigor capabilities or
  conclusion ceilings. These events do not authenticate the reviewer or prove
  that the judgment is substantively correct.
  Retain the local review-artifact root and recompute the complete integrity
  receipt on authoritative reads; a missing, changed, symlinked, or relocated
  artifact must fail closed rather than leaving a stale `passed` receipt trusted.
- A standalone measurement-custody record must bind independently supplied
  receipt bytes to the exact frozen protocol, calibration criteria, required
  gates, and locally verified raw, implementation, derived, and supporting
  artifacts. Publish it write-once and fail before creating output on any
  mismatch. It remains non-evidence and cannot replace canonical dataset intake,
  which must repeat custody validation. Standalone verification must start from
  an independently trusted record hash and recompute the original receipt bytes,
  current frozen protocol commitments, custody validation, and local artifact
  integrity; do not treat a self-consistent retained record as independent proof.
- Canonical protected datasets must retain their local custody-artifact root.
  Before inquiry display, protocol-bound execution, or run intake, replay the
  complete structured custody validator and current-byte artifact verification
  from the dataset's preserved receipt; require the recomputed verification to
  equal the service-generated registration receipt exactly. A stale `passed`
  result cannot authorize scientific use. Redact custody roots from default
  replication exports.
- Require every non-synthetic confirmatory or replication dataset to verify its
  declared observation bytes under an explicit local artifact root at
  registration. Retain the service-generated root and integrity receipt, bind it
  to the frozen protocol hash, and exactly replay current-byte verification on
  inquiry display, protocol-bound execution, and run intake. Never accept a
  caller-supplied verification receipt. Synthetic datasets may omit this only
  while they remain categorically non-evidentiary. Redact operational roots from
  default replication exports.
- Instrument adapters are low-authority acquisition inspectors. Pass immutable
  source bytes only after exact declared media-type matching and with committed
  explicit configuration; reject source/config
  mutation and unbounded output, and let the core compute source and actual
  implementation-module hashes. Independent verification must exactly reproduce
  the retained record from current source, config, and code bytes against a
  separately trusted record hash. Adapter
  output may propose acquisition metadata only; it cannot certify calibration,
  clear a gate, establish custody, register data, or authorize evidence.
- For a sealed numerical comparison, require a public measurement definition
  for every hidden target: observable, input, parameters, evaluation point or
  time, convention, aggregation, and tolerance. The sealed value must not depend
  on an undisclosed implementation choice. Use the typed
  `measurement_definitions` contract for new protocols so the freeze gate checks
  exact primary, secondary, and control coverage.
- A `pending_review` label must remain visible in synthesis. Never describe it as
  approval, validation, confirmation, or human review.
- Synthetic data and runs may test plumbing, but must never be presented as
  scientific evidence. Failed or skipped required gates fail closed.
- Human-subject protocol freeze requires local byte verification of the exact
  independent-review artifact named and hashed in the protocol. The recorded
  review decision must not postdate canonical freeze. This does not authenticate
  reviewer identity, establish qualifications, or validate substantive adequacy.
- Conditional human-subject approval is not discharged by recording condition
  prose. Before dataset intake, require exact condition coverage with satisfied
  or active-control status, rationale, evidence hash, inspectable location, and
  verified local evidence bytes. Bind the receipt to the frozen protocol and
  review decision. Active controls require a validity horizon, and runs must fail
  if they complete after it. Resolve JSON evidence locations inside the exact
  verified bytes and hash the selected value; label other media locations as
  human-inspectable rather than machine-verified. These checks do not authenticate assessors or prove
  compliance truth.
  Retain the condition-evidence artifact root in the service-generated dataset
  verification. Before inquiry display or any run, replay the entire original
  discharge validator from the preserved receipt and current bytes—including
  coverage, chronology, validity horizons at the original verification time,
  media types, JSON Pointers, selected-value hashes, and the integrity report—and
  require exact equality. Redact this operational root from default exports.
- The original independent-review artifact is the root of later human-subject
  clearance. Retain its local artifact root in the machine-issued freeze receipt
  and exactly recompute that receipt whenever clearance or local export is used.
  Missing, moved, modified, symlinked, or receipt-inconsistent original review
  material fails closed. The root is operational custody metadata, not part of
  the scientific protocol hash, and must be redacted from default exports.
- Never treat a frozen human-subject approval as permanently current. Record
  later active, suspended, withdrawn, or expired review decisions as a linear,
  append-only, artifact-verified event chain bound to the protocol. Require exact
  supersession and monotone sequence/effective time. Dataset and run intake must
  reject the latest applicable non-active or expired status without rewriting the
  original protocol. Protocol-bound executors must perform the same review-status
  and condition-horizon check before method invocation and bind it into their
  receipt. Read-only collaborator context must expose the history.
  Retain each local status-review artifact root and recompute the exact integrity
  receipt whenever the chain informs inquiry display, dataset intake, execution,
  or run intake. Missing, moved, changed, symlinked, or receipt-inconsistent
  review material fails closed. Redact the retained root from replication
  packages by default and never require external replicas to possess local ethics
  review files merely to verify the package's hash-covered history.
- Keep model collaboration provider-neutral and outside the scientific authority
  boundary. Freeze the exact read-only context as a write-once, hash-bound
  artifact before external review. Strictly validate returned human, LLM, or
  hybrid proposals against that independently trusted hash. Require uncertainty,
  competing explanations, disconfirmers, limitations, falsification conditions,
  and next tests. Proposals remain `pending_human_review`, have only
  `review_only` authority, perform no canonical writes, and are never scientific
  evidence or authorization. Core commands must not require or invoke a provider.
  Review every suggestion through a separately hash-bound adjudication artifact;
  require exact coverage and an explicit reject, defer, or compatible
  advance-to-domain-review disposition. Advancement is triage only, never an
  executed command or scientific acceptance, and reviewer identity remains
  unauthenticated unless a later trust layer proves otherwise.
- Keep protected dataset lineage protocol-closed. A confirmatory or replication
  derivative may use only sources bound to the exact same frozen protocol; role
  equality cannot authorize cross-protocol reuse or launder human-subject,
  consent, review, measurement, or analysis commitments.
- Replication packages for human-subject work must hash-cover the append-only
  ethics review-event history and visibly retain the latest recorded status.
  Never imply that original or renewed approval authorizes another site or
  replication. Redact protocol and review-event artifact locators by default,
  while preserving separately trusted package-hash verification and legacy
  package readability. For current packages, recompute protocol-summary and
  linear-event-chain agreement, exact event IDs, latest status, and the explicit
  non-authorization invariant; file hashes alone are insufficient. Reconstruct
  dataset lineage as an acyclic closed graph, reject duplicate or unrelated
  records, and require exact manifest IDs plus run-to-protocol and run-to-input
  bindings. Recompute run mode/role compatibility, synthetic propagation,
  required gates, output-bound passed-gate evidence, prerequisites, validity,
  workflow role, and evidence eligibility. Self-verify the staged package before
  atomic publication.
- Do not manufacture physical observations, dataset access, validation results,
  citations, or replications. Propose out-of-reach work as an experiment for a
  human or external system.
- Prefer “supported against these alternatives on this dataset” over “confirmed”
  or “proved.” Build a synthesis after material changes, run `workspace audit`,
  and verify the ledger.

## Engineering boundaries

- This repository develops the Research Machine, not any substantive research
  project. Do not place live hypotheses, study protocols, collected data,
  experiment workspaces, or domain conclusions here. Keep those in a separate
  experiment repository and connect them with `--addon-path` or
  `RESEARCH_ADDON_PATH`.
- Machine tests may contain synthetic fixtures that test software invariants.
  They must be labeled as fixtures and must not become a parallel research
  record. Domain acceptance campaigns belong with their experiment/add-on.

- Domain and application modules must not import Codex, OpenAI, an LLM SDK, the
  CLI, HTTP frameworks, or storage implementations.
- Codex is a client/orchestrator, not a hidden dependency. Future agents and UIs
  must use the same commands/application services.
- Keep provider-specific generation outside the core. LLM hypothesis generation
  is a proposal source and remains TODO until a port and explicit policy exist.
- Keep reports deterministic from stored state. Generative prose may supplement
  them later but must not replace or silently mutate canonical evidence.
- Treat `causal_claim` as an enforceable protocol commitment. A causal protocol
  must freeze an exact deterministic audit of its supplied DAG; never invent the
  graph, accept unresolved identification violations, or represent a passing
  graph-internal audit as proof that causal assumptions are true.
- Require causal assumption registers to state an assessment plan and failure
  response, and classify the assessment as `empirical_diagnostic`,
  `design_record_review`, `external_validation`, or `substantive_judgment`.
  The run result must preserve that frozen classification without upgrading it.
  Treat complete coverage as design provenance only, never as evidence
  that exchangeability, allocation integrity, positivity, consistency,
  non-interference, temporality, measurement validity, or selection validity is
  true in the study.
- Bind every causal assumption to a required protocol gate. A passed gate must
  carry its structured diagnostic result, cite an exact run output hash, and
  identify the exact table, figure, section, record range, or JSON Pointer inside
  that artifact where the assessment can be inspected. When the cited artifact
  is the verified analysis result, require an absolute JSON Pointer that actually
  resolves in those hash-verified result bytes.
  Preserve failed assessments as invalid runs; never translate “not contradicted
  by this diagnostic” into verification of the causal assumption.
- Preserve disconfirming evidence, not only successful checks. Every non-skipped
  causal assessment gate must carry exact artifact-bound results for all of its
  mapped assumptions. A passed gate permits only `consistent_with_assumption`,
  a warning requires at least one `inconclusive` result and no contradiction,
  and a failed gate requires at least one `contradicted_assumption` result.
  Gate labels and structured outcomes must never disagree.
- An executable causal protocol must measurement-custody its outcome, exposure,
  and every adjustment covariate as distinct typed definitions. Require exact
  agreement among DAG node, registered target, analysis-contract column, and
  measurement `data_column`; a bare column name is not a scientific construct.
  Require typed causal timing: adjustment covariates are `pre_exposure`, the
  exposure is `at_exposure`, and the outcome is `post_exposure`.
  Treat definition completeness as provenance, never as proof of construct
  validity, temporal correctness, or absence of measurement error.
- Guided causal designs with an identification record must collect one complete
  exposure measurement followed by one complete measurement for every proposed
  adjustment covariate. Enforce exact target and column coverage and ordered
  exposure categories; never generate measurement semantics from DAG labels.
- Every executable measurement column must freeze its scale type, unit,
  categorical domain or numeric bounds, and exact missing-value encodings.
  Validate actual source values against that contract before method execution,
  retain the check in the receipt, and reject method/scale incompatibility.
  Domain conformance is not construct validity or calibration evidence.
- Enforce add-on inference ceilings as typed data, not by reading persuasive
  prose. Causal evidence requires an exact causal claim, causal protocol,
  analysis contract, verified handoff, eligible run, and a method whose maximum
  is `design_conditional_effect`; that level remains conditional and never means
  causal proof, mechanism, or unrestricted generalization.
- Never accept an unspecified “causal effect.” Require a structured causal
  estimand with population, strategies, timing, outcome, contrast, summary
  measure, and intercurrent-event policy, bound to the reviewed target
  hypothesis and any frozen analysis contract. Treat exact agreement as
  provenance integrity, not evidence that the chosen estimand is appropriate.
- When secondary outcomes exist, require `confirmatory_outcomes` and
  `exploratory_outcomes` to partition all registered outcomes exactly.
  Exploratory protocols use `exploratory_only` without alpha; confirmatory
  protocols retain the primary outcome, use `single_test` for one confirmatory
  member or `holm` for more than one, and freeze a finite
  `multiplicity_alpha` strictly between zero and one.
- A Holm protocol must freeze an acyclic `analysis_steps` workflow. Keep the
  `primary_estimate` distinct from one `confirmatory_test` per family outcome;
  freeze each test's specification, implementation, hypothesis, measurement,
  outcome, and p-value selector. Materialize Holm input only from pinned,
  byte-verified source receipts, and preserve the materialization receipt.
  Protocol-bound Holm execution must match its frozen step, family order and ID,
  alpha, and registered input bytes. The connected local byte chain does not
  authenticate chronology, executor independence, scientific gates, or truth.
- Canonical workflow-component runs require the byte-verified execution handoff.
  Require exact protocol, dataset, implementation, and output agreement; never
  accept a non-primary step hash through manual run metadata. Preserve
  `workflow_component_only` and standalone evidence ineligibility even when all
  component gates pass. Only an explicit composite workflow contract may later
  adjudicate the family with its effect estimate and scientific gates.
  Treat the primary estimate under a Holm protocol as a component too; never let
  the unadjusted primary path bypass family-level adjudication.
- Composite Holm adjudication must require exact completed canonical component
  runs, passed required gates, verified execution handoffs, one shared
  non-synthetic observation dataset for the estimate and tests, the pinned
  materialization receipt, and proof that Holm consumed those exact family
  bytes. Preserve one decision per frozen member and the registered estimate
  and uncertainty. The local adjudication artifact remains non-evidence until a
  dedicated reviewed composite run is canonically recorded. Composite run
  drafting and intake must recompute the adjudication against current canonical
  state, require the exact output and observation dataset, and derive composite
  gates immutably from one passed receipt per required gate from every component.
  Reject component disagreement on a gate's scientific disposition; never let a
  reviewer re-enter or revise inherited gate results after seeing the composite.
  Composite evidence must select the exact
  adjudicated primary estimate and uncertainty; `supports` also requires the
  frozen multiplicity-adjusted primary decision to reject.
- Confirmatory empirical analysis contracts must freeze a typed conclusion
  contract before execution. Bind the primary hypothesis, appropriate direct or
  multiplicity-aware rule, smallest effect size of interest, effect scale and
  registered unit, population, setting, time window, non-supporting disposition,
  permitted claim level, and explicit unsupported conclusions. Direct and
  composite evidence must exactly retain the adjudicated direction and scope and
  attach to a claim at that level; never choose a friendlier interpretation after
  observing results. Practical significance requires the directional confidence
  bound to clear the smallest effect of interest; a point estimate alone never
  establishes practical importance.
  Equivalence is a separate prospective mode: require direction `equivalence`,
  `interval_within_equivalence_margin`,
  `equivalence_interval_within_margin`, a positive frozen margin, direct
  `single_test`, and confidence level `1 - 2α`. Never infer equivalence from a
  nonsignificant difference test or reuse ordinary power calculations for it.
  Use only the separate equivalence-power planner, whose decision event is the
  complete `1 - 2α` interval lying inside the symmetric margin; keep its
  known-variance normal assumptions and conditional, non-evidentiary status
  explicit.
- Keep discipline-specific semantics in validated add-ons. Research Machine must
  remain one self-contained tool: it ships a general-science execution toolkit,
  discovers installed or explicitly supplied local add-ons through
  `research_machine.addons`, and receives all
  add-on outputs through the same dataset, protocol, run, evidence, and ledger
  contracts.
- An add-on may provide readers, instrument adapters, analysis methods,
  simulations, quality gates, and protocol templates. It must not create a
  competing canonical store, weaken core review rules, promote claims, or treat
  successful execution as evidence eligibility.
- Put universally applicable concepts and validation rules in the core. Put
  physics-, psychology-, biology-, or instrument-specific assumptions in an
  add-on. When two disciplines need copied logic, generalize it into the core
  and retain acceptance tests in both disciplines.
- Every executable add-on method must expose a stable identifier, required
  specification fields, versioned manifest, hash-locatable implementation, claim
  ceiling, deterministic behavior when randomness is used, and adversarial
  fail-closed tests. Update `docs/addons.md` when the extension contract changes.
- Add tests for every new validation gate and every provenance-sensitive state
  transition. Run `pytest` and ledger verification before declaring completion.

## Publishing safety

- Default every newly created remote repository, release artifact, dataset, and
  hosted project to **private** visibility.
- Public visibility requires an explicit instruction from the project owner for
  that specific publication. Do not infer public authorization from an existing
  open-source repository, a prior publication, or a request merely to “push.”
- Verify the destination and visibility before the first upload.
