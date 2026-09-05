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

Add tidy/tabular validation, confidence intervals, linear and generalized-linear
models, paired and repeated-measure comparisons, power/precision planning,
multiple-testing adjustments, random assignment generation, missingness reports,
and publication-quality tables and plots. Every method needs frozen assumptions,
units, deterministic fixtures, adversarial cases, and explicit claim ceilings.

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
confounds, analysis commitments, and stopping rules. It is not yet a
conversational interface, a repository creator, a power calculator, or a
protocol-registration workflow.

Measurement-custody delivery: frozen protocols with calibration requirements
must declare their required custody gates. Before protected datasets bind to
such a protocol, the machine validates an immutable raw-source list, ordered
hash-pinned transformations, passed calibration records, passed gates, and
derived-observation lineage. This is provider-free and can be used through the
CLI today; persisted standalone custody receipts and instrument adapters remain
next work.

Ethics-gate delivery: a human-subject protocol cannot freeze until its consent,
withdrawal, privacy, retention/deletion, and risk plans are explicit and it
records a qualified independent-review receipt. The machine does not judge or
substitute for qualified review; it prevents an absent review record from being
silently treated as clearance.

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
