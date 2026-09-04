# Architecture

Research Machine uses a ports-and-adapters boundary so the current Codex-driven
experience is temporary without being throwaway.

```text
person
  |
  v
Codex conversation (current client)       future UI / HTTP API / agent
  |                                                |
  +---------------- structured commands ----------+
                           |
                           v
                 application services
                  /       |        \
            policies    domain    reports
                           |
                    repository port
                           |
                 filesystem adapter today
                 database adapter later
```

## Dependency rule

Dependencies point inward:

- `domain` defines decision-oriented inquiries; layered claims; hypotheses;
  datasets; protocols; runs; evidence; and action-selection vocabularies.
- `application` defines commands, validation policies, and use cases.
- `ports` defines capabilities the application needs from the outside world.
- `adapters` implement ports, currently with a transparent filesystem workspace.
- `reporting` deterministically projects canonical state into a synthesis.
- `interfaces` translates CLI input/output; it owns no research rules.

The inner layers know nothing about Codex, LLM providers, HTTP, or the
filesystem. A UI should call `ResearchService` (or a thin API over it), rather
than reproduce workflow rules in the front end.

## State and provenance

Each command first validates against current canonical state, writes the new
aggregate, and appends a provenance event. Ledger events contain sequence,
actor, command, aggregate identity, payload, a previous-event hash, and their own
SHA-256 hash. `workspace verify` recomputes the entire chain.

This makes later mutation detectable. It does not prove that a sensor was
accurate, a source was truthful, or an analysis was well designed; calibration,
chain of custody, and methodological review are separate gates.

New run records also bind protocol chronology. Local runs must not predate the
canonical freeze. An externally frozen run can be accessioned later only when
its protocol, analysis source, and zero-execution freeze manifest are preserved
as hash-verified artifacts. The machine labels that chronology externally
attested: hashes prove the bytes received, not when an external party first
created them.

The filesystem adapter uses atomic replacement for JSON state. Single-writer use
is assumed in version 0.5. Concurrent clients will require repository-level
locking or a transactional database before an API is exposed.

## Epistemic audit and conclusion ceiling

Provenance integrity is necessary but not sufficient: a perfectly hashed toy
calculation may still be scientifically weak. Evidence therefore carries one or
more validation tags. Application policy validates those tags against the
actual protocol, run, dataset role, executor identity, code hash, and quality
gates. A client cannot obtain an `empirical_test` label for a synthetic formal
run or an `independent_replication` label from only a changed actor string and
code hash. Replication runs must also declare clean-room executor and
implementation independence, pin their allowed inputs, disclose contamination,
and preserve a hashed attestation artifact.

The read-only rigor audit checks legacy and current evidence for scope,
uncertainty, controls, claim ceilings, classification, protocol stop rules, and
eligibility consistency. It also checks that the inquiry names its decision and
change criteria, that claim references form a valid acyclic spine, that factual
and sourced claims retain sources, and that accepted claims do not carry an
unresolved contradiction. Synthesis reports a conservative conclusion ceiling
derived only from validation tags whose prerequisites pass. Missing capabilities
remain visible instead of being filled by generated narrative.

These checks validate recorded provenance, not the world. An executor identity
or clean-room declaration is not independently authenticated merely because it
is recorded, and the machine cannot by itself establish that the declaration is
truthful, an instrument is accurate, or a derivation is sound. Those remain
external review and replication obligations.

## Workflow state versus evidence state

These are intentionally orthogonal:

- Workflow: `unreviewed`, `pending_review`, `active`, `parked`, `retired`.
- Evidence assessment: `unassessed`, `supported`, `weakened`, `refuted`,
  `inconclusive`.
- Replication: `untested`, `pending`, `replicated`, `failed`, `mixed`.

A hypothesis may leave the active model set for many reasons that are not
empirical refutation: it may be redundant, out of scope, unidentifiable,
insufficiently measured, currently untestable, or ethically prohibited. The
retirement record retains this distinction and states when reconsideration is
warranted.

`pending_review` is a constrained research state, not a weaker synonym for
`active`. It records a high-confidence agent review after the person has
delegated exploratory autonomy. It permits only exploratory protocol freezes
and exploratory evidence. Human activation remains necessary before protected
confirmation or replication.

## General execution model

An inquiry is the campaign boundary. Within it, the causal chain is:

```text
hypothesis -> review state -> frozen protocol -> role-locked inputs -> quality-gated run
           -> narrowly scoped evidence -> synthesis -> next action
```

Protocol kinds make this chain domain-neutral. Empirical protocols add sampling,
randomization, blinding, preprocessing, and statistical requirements. Formal and
computational protocols instead require reproducible environments. All kinds
share hash commitments, expected outputs, success/failure conditions, controls,
and safety constraints.

The application records runs; it does not execute arbitrary code. Executors may
be local processes, workflow systems, proof assistants, lab instruments, or human
teams. They cross the boundary by returning a run record with content hashes and
gate results.

`research-notebook` is one optional executor adapter, not an application-service
command. It runs a hash-pinned notebook, refuses output overwrites, and writes
both the notebook and a receipt atomically. If a cell raises, the notebook keeps
all completed outputs plus the error cell and the process exits nonzero. This
lets a failed run remain diagnosable without rerunning protected computation.
If source authentication, dependency preflight, or optional runtime loading
fails before the kernel starts, the executor writes a non-overwriting
`pre_execution_failure` receipt and no executed notebook.
The executor does not decide whether a failure is infrastructure, scientific,
or evidence-eligible; the frozen protocol and recorded run gates decide that.

Next-action selection is transparent and deterministic. Unsafe candidates and
candidates with unmet prerequisites fail closed. Eligible candidates are ranked
by expected discrimination and uncertainty reduction minus cost, burden, safety
risk, and ambiguity risk. The candidates, weights, and ranking are all persisted.

## Remaining adapter boundaries

- execution sandbox and workflow-runner adapters;
- domain quality gates, including synchronized multimodal data;
- statistics, simulation, theorem-proving, and literature-analysis executors;
- repository locking or transactional storage for concurrent clients;
- provider adapters that can suggest only unreviewed hypotheses and actions.

The sleep/acoustic campaign remains a useful eventual acceptance suite, not a
privileged domain model.
