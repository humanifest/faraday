# Deep Research brief: empirical QM-relativity reconciliation readiness

Status: `research-input`, not a scientific protocol, implementation plan, or
authorization to execute code, access protected data, or change Faraday state.

## Research objective

Produce a cited, comparison-first research packet that Faraday can use to
refine its contracts and controlled fixtures for distinguishing, in principle,
among empirical reconciliation candidates for quantum mechanics and
relativity. The research must identify what would be required to turn a theory
claim into a prospective, detector-level, falsifiable comparison. It must not
claim to solve quantum gravity, certify a proof, select a winning theory, or
represent literature review as empirical validation.

Use the program definition and contracts in this directory as the governing
context:

- `README.md`
- `program-gates.json`
- `theory-candidate-contract.schema.json`
- `theory-candidate-fixture.json`
- `obligation-evaluation.schema.json`
- `obligation-evaluation-fixture.json`

The context should be exported to a frozen, redacted snapshot before being
given to any remote research system. The returned packet must identify the
snapshot digest it used.

## Questions to answer

### 1. Candidate and baseline portfolio

Identify a small, scientifically defensible portfolio containing:

- at least three structurally different reconciliation approaches;
- the registered QM/QFT and GR baselines each must recover in its claimed
  regime;
- a conventional no-new-physics or effective-field-theory baseline;
- at least one measurement, calibration, selection, or astrophysical
  systematics alternative for every proposed empirical signature.

For each candidate, report scope and maturity, mathematical commitments,
required limits, unique or shared observables, known degeneracies, strongest
published objections, and what evidence would not discriminate it.

### 2. Mathematical obligation map

For each candidate, propose a finite obligation registry rather than a generic
claim of consistency. Each obligation should state:

- exact claim and assumptions;
- whether it is analytic, symbolic, numerical, formal, or empirical;
- expected witness and adverse control;
- suitable independent evaluator or proof assistant, if one exists;
- known limitations and the maximum conclusion permitted by a pass;
- downstream predictions invalidated by failure or changed assumptions.

Distinguish theorem-level obligations from consistency checks and numerical
evidence. Explicitly state when the literature does not provide a settled or
machine-checkable proof.

### 3. Empirical distinguishability channels

Compare candidate channels such as precision laboratory measurements,
interferometry, clock or equivalence-principle tests, high-energy or
astrophysical propagation, gravitational-wave observations, cosmology, or
other justified channels. Do not assume these examples are suitable.

For each viable channel, report:

- candidate-specific detector-level predictions and null predictions;
- the complete theory-to-observation transformation chain;
- accessible public data, calibration products, covariance information, data
  rights, release cadence, and stable primary-source location;
- expected signal scale, nuisance parameters, dominant systematics, current
  resolution, and the minimum meaningful separation between candidates;
- prospective or blinded use options and leakage risks;
- the exact outcome that should be returned if available resolution cannot
  separate the registered predictions.

Rank channels for a first controlled acceptance campaign using scientific
discriminating power, data accessibility, transformation-chain tractability,
cost, reproducibility, and risk of post-hoc inference. This ranking is a
proposal for human review, not authorization to ingest data.

### 4. Notebook and checker plan

Propose a notebook suite that maps one notebook or independently checkable
artifact to one frozen obligation or prediction. For every proposed notebook,
include:

- inputs, outputs, units, conventions, parameter domain, tolerances, and seeds;
- analytic benchmarks, limiting cases, negative controls, and planted defects;
- stable machine-readable result selectors;
- dependency and runtime requirements;
- an independent computational route or formal checker where warranted;
- the result status (`passed`, `failed`, `inconclusive`, or `not_applicable`)
  that each fixture is expected to exercise.

Return notebook source only as review material. Do not execute it and do not
represent remote code-interpreter output as a Faraday run or proof receipt.

### 5. Counterfactual and systemic implications

For each candidate, identify separately:

- logical implications that follow within stated assumptions;
- causal counterfactuals about the measurement or observation system;
- speculative consequences that cannot yet be operationalized;
- changes to assumptions, calibration, preprocessing, or external constraints
  that would require prediction or evidence revalidation.

Propose typed relationships using `assumes`, `depends_on`,
`entails_within_scope`, `contradicts`, `refines`, `predicts`, `measured_by`,
`confounded_by`, `invalidates`, and `requires_revalidation`. Flag relations that
are symmetric, uncertain, disputed, or valid only within a declared regime.

### 6. Metamaps projection proposal

Propose a derived graph projection with versioned nodes and edges for:

- original requirements and research questions;
- candidate and baseline revisions;
- assumptions and mathematical obligations;
- source artifacts and citation claims;
- observables, transformations, measurements, and datasets;
- notebook/checker bundles, runs, and findings;
- predictions, adjudications, counterfactuals, and revalidation requirements.

Every projected element must retain a canonical Faraday record reference,
revision, and hash. Identify cycle rules, invalidation propagation, coverage
findings, uncertain edges, and conflicts. The graph must remain rebuildable and
discardable; it cannot become scientific or authorization state.

## Required sources and evidence discipline

- Prefer primary papers, official experiment/data documentation, instrument
  papers, standards, and authoritative software or proof-assistant manuals.
- Use reviews to orient the search, but trace important factual claims to
  primary sources where possible.
- Give a stable URL, DOI or archival identifier, publication/version date,
  accessed date, and the specific claim supported by each citation.
- Separate source statements from synthesis and speculation.
- Record contradictory results and credible criticism rather than silently
  resolving them.
- Do not transmit repository content, non-public data, credentials, or local
  paths beyond the explicitly exported frozen context.

## Required return package

Return a review-only package with these artifacts:

1. `research-summary.md` — executive synthesis, uncertainties, and recommended
   first controlled campaign;
2. `candidate-matrix.json` — normalized candidate, baseline, limit, objection,
   and discriminating-observable comparison;
3. `obligation-proposals.json` — proposed obligation records and dependency
   links, without pass/fail claims;
4. `empirical-channel-matrix.json` — public sources, transformation stages,
   systematics, resolution, and distinguishability assessment;
5. `notebook-plan.json` — one bounded notebook/checker job per obligation or
   prediction, including adverse fixtures;
6. `counterfactual-proposals.json` — baseline, intervention, held-fixed
   quantities, validity regime, propagation method, and affected predictions;
7. `metamaps-projection-proposal.json` — typed, versioned, non-authoritative
   nodes and edges;
8. `source-register.json` — citation metadata and claim-level source mapping;
9. `open-questions.md` — unresolved conflicts, missing evidence, and items that
   require domain-expert adjudication.

Every artifact must contain the frozen context digest, generation timestamp,
research-system identity/version if available, and status
`pending_human_review`. Unknown facts must be `unknown`; absence of a cited
counterexample must not be encoded as proof of consistency.

## Acceptance checks for the research packet

The packet is ready for human review only if:

- every substantive factual claim has a claim-level citation;
- candidate comparisons use the same declared dimensions and baselines;
- at least one serious alternative explanation accompanies each empirical
  signature;
- obligations distinguish proof, computation, and empirical testing;
- empirical proposals reach detector-level records and include systematics;
- notebook proposals include adverse fixtures and conclusion ceilings;
- counterfactuals are separated from logical implication;
- Metamaps elements bind canonical record references and declare uncertainty;
- unresolved and not-distinguishable cases remain first-class outcomes;
- no artifact claims execution, validation, activation, or scientific
  acceptance.

Failure of any check returns the package for revision; it does not block other
Faraday work or change scientific state.
