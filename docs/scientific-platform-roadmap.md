# Scientific platform roadmap

The target is one discipline-agnostic, self-contained tool for designing,
executing, auditing, and extending scientific investigations. Add-ons widen its
methods without changing its epistemic rules or canonical state.

## Delivered foundation

- A common inquiry, claim, hypothesis, dataset, protocol, run, evidence,
  replication, synthesis, and provenance lifecycle.
- Typed measurements, frozen protocols, execution-quality gates, chronology
  checks, artifact verification, and conservative claim ceilings.
- A validated add-on registry with bundled general-science and physics add-ons.
- Write-once execution receipts binding analysis specification, data,
  implementation, environment, output, and gates.
- Cross-disciplinary CSV summaries, correlation, and seeded permutation testing.
- Synthetic and physical pendulum acceptance paths.

## Phase 1 — complete the general empirical toolkit

Add tidy/tabular validation, confidence intervals, linear and generalized-linear
models, paired and repeated-measure comparisons, power/precision planning,
multiple-testing adjustments, random assignment generation, missingness reports,
and publication-quality tables and plots. Every method needs frozen assumptions,
units, deterministic fixtures, adversarial cases, and explicit claim ceilings.

Completion criterion: a small observational or randomized two-group study can be
planned, frozen, analyzed, recorded, audited, and packaged using only the
installed Research Machine distribution.

## Phase 2 — migrate the sleep/acoustic prototype

Port raw-container inspection, versioned event sidecars, clock calibration,
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
