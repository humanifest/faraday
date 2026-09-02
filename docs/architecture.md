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

- `domain` defines inquiry, claim, hypothesis, evidence, and their vocabularies.
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

The filesystem adapter uses atomic replacement for JSON state. Single-writer use
is assumed in version 0.1. Concurrent clients will require repository-level
locking or a transactional database before an API is exposed.

## Workflow state versus evidence state

These are intentionally orthogonal:

- Workflow: `unreviewed`, `active`, `parked`, `retired`.
- Evidence assessment: `unassessed`, `supported`, `weakened`, `refuted`,
  `inconclusive`.
- Replication: `untested`, `pending`, `replicated`, `failed`, `mixed`.

A hypothesis may leave the active model set for many reasons that are not
empirical refutation: it may be redundant, out of scope, unidentifiable,
insufficiently measured, currently untestable, or ethically prohibited. The
retirement record retains this distinction and states when reconsideration is
warranted.

## Roadmap boundaries

The following capabilities should be added behind new application commands and
ports, in this order:

1. Immutable experiment protocols with versioning and hash commitments.
2. Dataset manifests with mutually exclusive calibration, discovery, training,
   confirmation, and replication roles.
3. Run manifests that bind inputs, protocol, code, environment, seeds, outputs,
   validation results, and executor identity.
4. Quality gates and adapters for synchronized multimodal data.
5. Registered and exploratory execution namespaces with reproducibility checks.
6. Evidence aggregation without automatic claim-level promotion.
7. Experiment selection by expected discrimination, uncertainty reduction, cost,
   burden, safety, ethics, and ambiguity risk.
8. Provider adapters that may suggest questions or hypotheses as unreviewed
   proposals, never as canonical conclusions.

The sleep/acoustic campaign remains a useful eventual acceptance suite, not a
privileged domain model.
