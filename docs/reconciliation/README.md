# QM–relativity reconciliation readiness program

Status: `defined`, not implemented or accepted.

This program specifies what Faraday must implement and verify before it may be
described as capable, in principle, of discriminating among candidate empirical
reconciliations of quantum mechanics and relativity. It does not assert that a
reconciliation exists, that Faraday has found one, or that computational
agreement establishes mathematical or physical truth.

The machine-readable gate inventory is [`program-gates.json`](program-gates.json).
That inventory records current evidence and missing work; its status values are
not scientific acceptance states.

## Program goal

Faraday should be able to:

1. retain a reviewed portfolio of competing theory candidates, including
   conventional baselines and measurement/systematics alternatives;
2. freeze candidate-specific mathematical obligations and empirical
   distinguishability claims before protected observations are inspected;
3. compose review-only Jupyter notebook drafts, then execute only reviewed,
   hash-bound sources with exact dependency and runtime receipts;
4. admit independently checkable symbolic, numerical, or proof-assistant
   findings without treating notebook execution as theorem proof;
5. connect theory-level observables to instrument-level records through a
   versioned measurement and transformation chain;
6. ingest provenance-, custody-, calibration-, timing-, ethics-, and
   role-bounded datasets through existing canonical Faraday services;
7. adjudicate prospective predictions against explicit competitors and return
   `supported_against_registered_alternatives`, `weakened`, `refuted`,
   `inconclusive`, or `not_distinguishable_by_this_design` without upgrading
   those outcomes into proof;
8. evaluate versioned counterfactual interventions and propagate bounded
   systemic implications;
9. compile invalidatable Metamaps projections of requirements, hypotheses,
   assumptions, obligations, artifacts, predictions, data, runs, and evidence;
10. expose a frozen read-only context to deep-research clients and accept only
    cited, review-only proposals in return.

## Authority and ownership

- Faraday owns scientific workflow state, domain validation, evidence admission,
  conclusion ceilings, and the canonical ledger.
- Metamaps compiles derived graph projections and findings. Graph topology is
  not evidence, authorization, or scientific acceptance.
- A deep-research system may discover sources, propose hypotheses, draft
  derivations, suggest counterfactuals, or compose notebook source. It may not
  activate a hypothesis, freeze a protocol, execute protected computation,
  clear a gate, admit evidence, or approve a conclusion.
- Jupyter is an execution and exposition medium. Formal proof authority belongs
  to an explicitly named checker and exact checker receipt; empirical authority
  belongs to a frozen protocol, registered data, eligible run, and reviewed
  evidence record.
- system-config remains the execution/disclosure authority, Orca remains the
  lifecycle/acceptance owner where integrated, and Cypher remains the permitted
  inference broker. This program grants none of those permissions.

## Required canonical chain

```text
original requirement
  -> candidate theory and competing models
  -> assumption and proof-obligation registry
  -> reviewed derivation/notebook/checker bundle
  -> frozen empirical prediction and distinguishability rule
  -> registered measurement and dataset custody
  -> quality-gated execution
  -> narrowly scoped evidence
  -> counterfactual and implication findings
  -> deterministic synthesis and next action
```

Every link must identify exact record revisions, artifact hashes, evaluator
versions, and applicable Metamaps compiler/module versions. A changed upstream
record must invalidate dependent projections and require the appropriate
revalidation; historical records are never rewritten.

## Candidate-theory record

The proposed non-production input shape is published as
[`theory-candidate-contract.schema.json`](theory-candidate-contract.schema.json),
with a deliberately synthetic
[`theory-candidate-fixture.json`](theory-candidate-fixture.json). The schema
defines proposal structure only; no current service consumes it or seals it into
canonical hypothesis state.

A reconciliation candidate requires, at minimum:

- statement, provenance, scope, domain of validity, and unresolved assumptions;
- mathematical objects, state/configuration spaces, equations or action,
  parameters, units, boundary conditions, and observable definitions;
- applicable symmetries, gauge/coordinate structure, constraints, and
  conservation claims;
- declared quantum/QFT, relativistic/GR, classical, and low-energy limits;
- null and competing models, including ordinary measurement, selection,
  calibration, preprocessing, and instrument-systematics alternatives;
- explicit predictions, non-predictions, falsifiers, boundary conditions, and
  parameter regimes where candidates are observationally indistinguishable;
- a sealed scientific payload, revision lineage, and review state.

No universal checklist can prove an arbitrary candidate consistent. Each
candidate must instantiate an obligation registry whose entries identify the
claim, assumptions, method, evaluator, inputs, expected witness, adverse
control, limitations, and permitted conclusion ceiling.

## Minimum obligation families

When applicable to the candidate, the obligation registry must address:

- dimensional, type, tensor-index, and domain/codomain consistency;
- symmetry, gauge, coordinate, and representation invariance;
- constraint closure and conservation;
- existence, uniqueness, well-posedness, and stability;
- anomaly, ghost, causality, boundedness, and unitarity conditions;
- recovery of registered limiting theories and benchmark solutions;
- equivalence between analytic definitions and executable discretizations;
- convergence, reconstruction stability, sensitivity, and numerical error;
- parameter identifiability, degeneracy, and empirical distinguishability;
- the complete theory-to-observation transformation chain.

`not_applicable` is permitted only with a reviewed rationale. A missing or
failed required obligation blocks dependent readiness, not unrelated work.

## Notebook and checker requirements

Before a checker result can influence readiness, it should conform to the
proposed non-production
[`obligation-evaluation.schema.json`](obligation-evaluation.schema.json). The
paired [`obligation-evaluation-fixture.json`](obligation-evaluation-fixture.json)
shows the intended candidate/obligation binding, evaluator identity boundary,
artifact-selected witness, adverse control, findings, limitations, and false
authority flags. No current application service consumes this shape.

Generated notebook source is always a proposal. Before execution it must have:

- one frozen target obligation or empirical prediction;
- exact source, dependency-manifest, environment, kernel, and working-directory
  commitments;
- no hidden network, filesystem, or provider dependencies;
- declared units, conventions, tolerances, seeds, and parameter domains;
- analytic benchmarks, limiting cases, negative controls, and planted adverse
  fixtures;
- machine-readable results with stable JSON selectors;
- explicit unresolved obligations and conclusion ceilings.

Important computational claims require either an independently checkable formal
artifact or two frozen computational routes with declared sharing boundaries.
Agreement may establish bounded implementation consistency; it cannot establish
independent reasoning, theorem truth, or physical correctness.

## Theory-to-observation and prediction requirements

Every empirical test must freeze a chain from theory parameters to recorded
variables:

```text
theory quantity
  -> source/emission model
  -> propagation model
  -> detector response
  -> calibration and preprocessing
  -> registered measurement
  -> statistical prediction
```

Each transformation must bind its implementation, units, coordinate/time
system, uncertainty, applicability conditions, nuisance parameters, and failure
fixtures. The final prediction contract must name the exact hypotheses,
datasets, estimand, observable selectors, uncertainty model, comparison rule,
minimum meaningful separation, result-exposure protection, and claim ceiling.

If the registered predictions overlap at achievable resolution, the required
outcome is `not_distinguishable_by_this_design`, not arbitrary support or
rejection.

## Counterfactual and systemic implications

Logical implication and causal counterfactuals are separate projections.

A counterfactual query must bind the baseline model revision, intervention or
changed assumption, quantities held fixed, validity regime, time horizon,
propagation method, uncertainty, and affected predictions. It must distinguish
an intervention on a modeled measurement system from a speculative change to a
fundamental theory.

Implication edges use typed relations such as `assumes`, `depends_on`,
`entails_within_scope`, `contradicts`, `refines`, `predicts`, `measured_by`,
`confounded_by`, `invalidates`, and `requires_revalidation`. Symmetric semantic
relations must not be mistaken for the acyclic derivation/provenance spine.

## Metamaps projection boundary

The current repository contains only a proposed fixture contract. Production
use requires an accepted shared record-reference contract, an authorized and
pinned Metamaps compiler/API, a Faraday adapter, shadow comparison against a
saved workflow, invalidation tests, and rollback evidence.

At minimum, a projection must include source record IDs/revisions and hashes,
compiler/module versions, typed nodes and edges, coverage/findings, projection
status, and rebuild requirements. Faraday remains authoritative when a graph and
canonical domain state disagree.

## Deep-research boundary

The first integration should be read-only. A frozen context may expose the
inquiry boundary, source register, candidate theories, unresolved questions,
obligation status, dataset inventory, prior evidence, and current Metamaps
projection. Returned proposals must cite the context digest and sources and
remain `pending_human_review`.

The bounded research assignment, required artifacts, and packet-level review
checks are defined in
[`deep-research-brief.md`](deep-research-brief.md). It is suitable for a Pro
Deep Research run only after an operator has created and approved a redacted,
frozen context snapshot; it is not a request to expose this repository.

Remote code-interpreter output is not imported as an eligible run. Proposed
notebooks and calculations must be transferred as source artifacts, reviewed,
frozen, and executed through Faraday's local protected execution path.

## First acceptance campaign

The first acceptance campaign is deliberately controlled and must live in a
separate experiment repository. It should contain:

- one conventional baseline and two deliberately distinguishable toy
  reconciliation candidates;
- one intentionally inconsistent candidate or derivation;
- analytic benchmark solutions and a registered obligation set;
- two code-separated implementations for one decisive quantity;
- planted sign, unit, gauge/coordinate, hidden-helper, and data-transformation
  defects;
- signal, null, confounded, insufficient-resolution, and tampered synthetic
  datasets;
- one registered public empirical dataset after the synthetic campaign passes;
- prospective prediction adjudication before protected observations are read;
- counterfactual and systemic-implication projections;
- Metamaps invalidation after a source assumption or artifact revision changes;
- a portable replication package independently replayed from current bytes.

## Program completion criterion

Faraday may be described as capable of pursuing the stated goal only when all
required gates in `program-gates.json` are `accepted` with current artifact-bound
evidence. The controlled campaign must complete at least two full hypothesis
iterations, preserve negative and inconclusive outcomes, reject every planted
defect at its intended boundary, return `not_distinguishable_by_this_design`
for the insufficient-resolution case, pass workspace audit and ledger
verification, and be independently reproduced.

That readiness establishes a process capable of evaluating scoped candidates.
It does not establish that any candidate reconciliation is true.
