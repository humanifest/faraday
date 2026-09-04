# From competing machines to one general research engine

The generic Research Machine is canonical. The Vindication machine is retained
as a domain prototype and acceptance-test source, not developed as a second
platform.

## Ideas retained from each

From the original generic machine:

- inquiry, question, claim-level, and competing-hypothesis structure;
- explicit unreviewed/pending-review/active/retired hypothesis lifecycle;
- narrow evidence records and no automatic claim promotion;
- deterministic synthesis and a hash-chained provenance ledger;
- ports-and-adapters boundaries and a stable CLI/service interface.

From the Vindication prototype:

- immutable, content-hashed artifact registration;
- calibration, exploratory, training, confirmatory, and replication roles;
- protocol hash commitments and amendments instead of mutation;
- run manifests binding code, environment, inputs, outputs, and executor;
- required quality gates and synthetic-data exclusion;
- evidence validation tags with machine-enforced prerequisites and a
  deterministic conclusion ceiling;
- deterministic, discrimination-oriented next-action selection.

## What stays outside the core

Sleep-stage semantics, acoustic controls, event-window construction, sensor
synchronization, and domain statistical models become installable add-ons to the
one Research Machine distribution. Their outputs enter the core through dataset,
protocol, run, gate, and evidence contracts. This preserves their value without
baking one campaign's ontology into every future inquiry or creating a second
research system.

New domains should extend through three surfaces:

1. a versioned add-on manifest and executor that implements a frozen protocol;
2. named quality gates whose results can be recorded in a run;
3. example campaigns used as end-to-end acceptance tests.

The central rule is simple: improve one engine. A domain prototype may incubate
an idea, but the idea is complete only after it is generalized into the canonical
contracts and tested in at least one unrelated domain.
