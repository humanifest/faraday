# Scientific add-ons

Research Machine is one self-contained scientific system. Add-ons extend its
instruments and methods; they do not create alternate evidence stores, ledgers,
hypothesis rules, or standards of proof.

## Boundary

The core owns the discipline-independent scientific lifecycle:

```text
question -> claims -> competing hypotheses -> measurements -> frozen protocol
         -> data -> execution -> quality gates -> evidence -> synthesis
```

An add-on may provide data readers, analysis methods, simulations, instrument
adapters, domain quality gates, protocol templates, and acceptance campaigns.
Every output returns through the core dataset, protocol, run, evidence, and
provenance contracts. Add-ons cannot promote a claim or bypass review.

Research Machine includes:

- `general_science`: dependency-free CSV summaries, Pearson correlation, and a
  seeded two-group permutation test;
- `physics`: a packaged pendulum/gravity method plus the synthetic and physical
  pendulum acceptance campaigns in the source distribution.

Use `research addon list` and `research addon show ADDON_ID` to inspect the
active capability surface.

## Run a bundled analysis

Create a JSON specification from `examples/general-analysis.json`, then run:

```bash
research analysis run \
  --spec-file analysis.json \
  --data-file observations.csv \
  --output artifacts/analysis-001
```

The output directory is write-once. It contains `analysis-result.json` and an
`execution-receipt.json` binding the specification, input, implementation,
environment, output, and quality gates by hash.

This command deliberately reports `scientific_evidence_eligible: false`.
Execution is not evidence by itself. For confirmatory work:

1. create the inquiry and competing hypotheses;
2. register the dataset role and freeze the complete protocol before inspecting
   protected outcomes;
3. freeze the exact analysis specification and implementation hash;
4. execute the add-on method;
5. construct and preflight a run record using the returned hashes and gates;
6. record narrowly scoped evidence only after the run is accepted;
7. build synthesis, audit rigor, and verify the ledger.

Exploratory execution can happen earlier, but its data and conclusions remain
exploratory and cannot later be relabeled as confirmatory.

## Third-party add-ons

Python packages may publish an entry point in the
`research_machine.addons` group. The loaded object (or zero-argument factory)
must return `research_machine.addons.AddonManifest`. Identifiers are stable and
globally unique; duplicate add-on or method identifiers fail closed.

An add-on should contain:

- a manifest with version, discipline, capabilities, methods, media types, and
  supported protocol kinds;
- deterministic runners whose source file can be hashed;
- explicit required specification fields;
- domain quality gates and adversarial fixtures;
- documentation stating assumptions, units, applicability boundaries, missing
  data behavior, and the maximum claim its result can support;
- tests showing that malformed, incomplete, and out-of-domain inputs fail.

Do not use add-ons for provider-specific prose generation or as a route around
canonical application services.

## Planned bundled add-ons

The next add-on should be `sleep_acoustic`, migrated from the frozen Vindication
prototype. Later candidates include psychology experiment design and
randomization, time-series and signal processing, biological assays,
survey/psychometric validation, causal inference, and literature synthesis.
Each should be added only with a second-domain regression check so shared logic
is generalized into the core rather than copied.
