# Scientific add-ons

Add-ons may declare `InstrumentAdapter` inspectors with stable IDs, supported
media types, and explicit required and optional configuration fields. Adapter
media-type and configuration-field handles must be canonical without surrounding
whitespace, duplicate-free, and split cleanly between required and optional
fields. The core rejects undeclared media types, passes an immutable source-byte snapshot and a committed configuration, then
accepts only bounded acquisition metadata. It independently hashes the source,
binds the actual implementation-module bytes, rejects source/config/code mutation
and unknown or non-JSON output, and publishes a write-once non-evidence inspection
record. `measurement verify-source-inspection` requires a separately trusted
record hash and exactly reproduces the record from the current three inputs.
An adapter has no authority to assert
calibration, pass a quality gate, create custody, register a dataset, or promote
evidence. Device-specific adapters must preserve that boundary.

Analysis result contract version 2 separates `declared_claim_ceiling` from the
method's enforced `claim_ceiling`. Researcher text is retained for audit but
cannot widen the method maximum. Every add-on method exposes its maximum in the
manifest; undeclared local methods receive a conservative calculation-only
default. Successful execution still creates no canonical evidence by itself.
Registry validation rejects blank or non-text method ceilings, and the published
add-on manifest schema requires the same field. An add-on cannot enter the
execution registry with an omitted conclusion bound.
Methods also declare a typed `maximum_inference_level`: `computation_only`,
`descriptive`, `association`, or `design_conditional_effect`. This value is
included in the result and receipt. During protocol-bound execution the resolved
method passes it into the canonical design check before running; causal primary
analyses require `design_conditional_effect`. The resulting
`method_inference_check` is recomputed at handoff and run intake. This is a
machine-enforced capability boundary, not proof that a third-party declaration
is scientifically correct or that a compatible estimator establishes causality.

Toolkit 6.0.0 adds `adjusted_linear_effect`, a dependency-free ordinary least
squares estimator for an exact, ordered, non-empty covariate set. It codes the
first registered group against the second, standardizes adjustment covariates
internally for numerical stability, and returns the adjusted contrast with an
HC1 heteroskedasticity-consistent normal confidence interval, coefficients,
leverage and residual diagnostics, independent-unit checks, and a complete-case
exclusion report. It rejects missing or repeated unit identifiers, unknown group
levels, nonnumeric or constant covariates, rank-deficient designs, insufficient
residual degrees of freedom, and unregistered missing-data exclusions. HC1 is an
asymptotic approximation; passing computation does not validate linearity,
positivity, independence, the DAG, the adjustment set, or causal identification.

For observational causal protocols, `AnalysisContract.adjustment_columns` must
exactly equal the audited DAG's ordered `proposed_adjustment_set`. The analysis
specification's `covariate_columns` must then exactly equal that frozen contract,
and the contract's group and outcome columns must equal the audited exposure and
outcome nodes. Freeze, execution, handoff, run intake, and causal-evidence
validation preserve or recompute these bindings. This prevents silent estimator
drift; it does not prove that the chosen graph or adjustment set is scientifically
correct.

Toolkit 8.0.0 retains the 7.0.0 `holm_adjustment` family boundary and adds
independent-unit identity checking to `permutation_mean_difference`, enabling it
to serve as a frozen confirmatory-test workflow step without silently ignoring
the registered unit column. `holm_adjustment` requires an exact non-empty
`family_hypothesis_ids` list alongside the family name and predeclared alpha.
Input rows must contain that complete set exactly once; omitted, substituted, or
extra hypotheses reject before adjustment. Row order remains immaterial, and the
result preserves the frozen family list plus monotone Holm-adjusted p-values.
This prevents selective row omission from silently shrinking the denominator; it
does not choose a scientifically valid family or repair invalid underlying tests,
outcome switching, dependence violations, or post-outcome specification.

When Holm runs under `analysis run --protocol ... --dataset ...`, the protocol
must contain a frozen `analysis_steps` workflow. A `primary_estimate` remains
distinct from the `confirmatory_test` for each family outcome. Every test freezes
its exact specification and implementation hashes, hypothesis, outcome,
measurement, and p-value JSON Pointer. The Holm step must depend on and map that
complete test set exactly. Before Holm execution, use:

```bash
research analysis materialize-holm \
  --protocol PROTOCOL_ID \
  --manifest-file dependencies.json \
  --expected-manifest-sha256 TRUSTED_HASH \
  --output materialized-family
```

The command verifies every pinned source receipt and result, recomputes its
registered p-value selection, rejects missing/substituted sources, and emits
`holm-family.csv` with `family-materialization.json`. Holm execution verifies its
own frozen step, ordered member IDs, family ID, alpha, implementation,
specification, and registered input bytes. The two receipts connect through the
family CSV hash. This proves local byte identity, not chronology, executor
independence, scientific-gate success, or validity of the underlying tests.

`analysis run-draft` and canonical run intake accept these frozen workflow-step
receipts through the same verified handoff boundary used for primary estimates.
The submitted run must name exactly the receipt-bound protocol and dataset, use
the step implementation hash, and include the exact verified result artifact.
A non-primary workflow hash without its verified handoff is rejected. Such runs
are retained as `workflow_component_only` and can never become standalone
scientific evidence. After all component runs and gates are recorded, use:

```bash
research analysis adjudicate-holm \
  --protocol PROTOCOL_ID \
  --manifest-file workflow-adjudication.json \
  --expected-manifest-sha256 TRUSTED_HASH \
  --output adjudicated-workflow
```

The manifest pins a canonical run ID, execution directory, and receipt hash for
the primary estimate, every confirmatory test, and the multiplicity step, plus
the family-materialization directory and receipt hash. The adjudicator rejects
incomplete families, invalid or gate-failing runs, synthetic observation
sources, divergent source datasets, changed receipts/results, and Holm inputs
that differ from the materialized family. Its deterministic output combines the
registered effect estimate and uncertainty with raw and Holm-adjusted decisions.
That output is review-only. `analysis adjudication-run-draft` recomputes the
adjudication against current canonical components and creates a reviewable run
record whose scientific gate results are immutable derivations of the exact
passed component-gate receipts. Every component must have one passed receipt for
each required gate and must agree on its scientific disposition. The researcher
may add review context but cannot rewrite those inherited results. Canonical run
intake recomputes the adjudication and derived gates once more, requires the exact
output artifact and sole observation dataset, and only then permits normal run
eligibility. Evidence from that run is bound to
`/primary_estimate/effect_estimate` and `/primary_estimate/uncertainty`; a
supporting direction additionally requires the adjusted primary family member
to reject at the frozen alpha.

The protocol's typed `conclusion_contract` makes interpretation prospective.
Any confirmatory empirical analysis contract now requires an exact primary
hypothesis, appropriate decision rule, non-negative smallest effect size of
interest, registered effect unit, effect scale, target population, setting,
endpoint, non-supporting disposition, permitted claim level, and explicit
higher-level exclusions. Direct analyses combine the registered
confidence-interval rule with practical significance; Holm adjudication also
requires adjusted primary rejection. Canonical evidence must use the resulting
direction verbatim and attach to an exact claim whose level and scope match the
contract; statistical success cannot be repackaged as a broader claim.

Protocol-bound `independent_mean_difference_ci` execution now requires a
`unit_column` in the exact frozen specification. Missing or repeated identifiers
reject execution. Standalone analyses may omit it and report checking as absent.
Existing frozen specifications are not rewritten; a missing unit commitment
requires a separately reviewed new protocol before using this stricter path.
Unique IDs still do not establish sampling independence or rule out clustering.

Execution result wrappers retain the declared `missing_data_policy`, or JSON
`null` when omitted. They no longer assign `complete_case` to every method.
This field records a specification setting, not proof that exclusions occurred
or were statistically justified; method-level results describe actual handling.

Toolkit 4.0.0 represents `missingness_patterns` as records with `missing_columns`
(an array of exact column names) and `row_count`. This replaces delimiter-joined
map keys, which could merge different patterns when column names contained the
delimiter. Empty input rejects rather than reporting an undefined fraction.

Two-group comparison results include an exclusion report: one-based parsed data
record numbers, missing columns, counts by registered group, and unassigned-group
counts. Record numbers refer to the hashed input's parsed records, not physical
CSV lines (quoted fields may contain newlines). This reports selection, not an
assurance that complete-case analysis is unbiased.

General Science Toolkit 3.0.0 requires an explicit `missing_data_policy:
"complete_case"` when independent mean-difference or permutation comparisons
encounter blank outcomes or group labels. Without that declaration they reject
the input rather than silently remove rows. Complete-case execution reports the
number removed; it does not establish that missingness is ignorable. Paired
comparisons continue to reject incomplete observations rather than drop pairs.

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

- `general_science`: dependency-free CSV summaries, Pearson correlation, a
  seeded two-group permutation test, missingness reports, design-bound bootstrap
  estimation for independent or paired two-group comparisons, and a
  covariate-adjusted linear estimator with HC1 uncertainty;
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
3. freeze the exact analysis specification and implementation hash, plus the
   semantic analysis contract (primary hypothesis, method, outcome column,
   group variable, ordered contrast levels, exact ordered adjustment columns,
   estimand, missing-data policy, and
   exact result selectors for the effect and uncertainty, a numeric null value,
   the rule used to classify directional support, a minimum analyzable-unit
   count, and a maximum excluded-record fraction);
4. execute the add-on method;
5. construct and preflight a run record using the returned hashes and gates;
6. record narrowly scoped evidence only after the run is accepted, selecting
   estimates and uncertainty directly from the verified output by JSON Pointer;
7. build synthesis, audit rigor, and verify the ledger.

Protocol-bound execution resolves both frozen result selectors immediately and
validates that the selected effect and confidence interval are finite and
coherent. It stores a digest for each selected JSON value plus the frozen null
and support rule in the execution receipt. A missing path or malformed interval
cannot produce a completed execution. Handoff verification and run intake
recompute both digests, so rehashing a modified receipt cannot substitute another
statistic while leaving the analysis-result file unchanged.

`point_direction` requires a supporting point estimate to lie on the registered
side of the null. `interval_excludes_null` additionally requires the registered
confidence interval to exclude that null in the expected direction. This is a
frozen decision rule, not a general claim of statistical significance.

Protocol-bound two-group methods also enforce frozen information thresholds.
`minimum_analyzable_units` applies to the smaller independent arm or the number
of complete pairs; `maximum_excluded_fraction` is calculated from the method's
structured exclusion report. The receipt records the registered and observed
values, and verification recomputes them from the hashed result. The frozen
`maximum_group_excluded_fraction_difference` additionally caps the absolute
difference between group-specific exclusion rates. Add-on exclusion reports must
therefore provide exact `excluded_by_group` counts and
`excluded_without_registered_group`; any ungrouped exclusion prevents this check.
Included group counts must sum to `included_records`, while grouped plus ungrouped
exclusions must equal the total exclusions; inconsistent accounting rejects before
threshold evaluation. Receipts bind the reconstructed rates and observed difference. Passing these
limits does not demonstrate adequate power, representative retention, an
ignorable missing-data mechanism, or absence of selection bias.
Every complete-case analysis contract also carries a prospective missingness
assumption, assessment plan and kind, failure response, and dedicated required
gate. A performed gate's structured result must cite an exact output artifact and
location; verified add-on output citations use a resolvable absolute JSON Pointer.
Passed, warning, and failed gate statuses bind respectively to consistent,
inconclusive, and contradicted assessment results. This preserves how missingness
was examined without treating an add-on diagnostic as proof of ignorability.

Exploratory execution can happen earlier, but its data and conclusions remain
exploratory and cannot later be relabeled as confirmatory.

The bundled estimators require an explicit `study_design`. An
`independent_mean_difference_ci` refuses an undeclared or paired design; a
`paired_mean_difference_ci` requires one observation for each registered group
per pair identifier and refuses incomplete or duplicate pairs. Every submitted
paired-analysis row must contain a nonblank pair identifier, group, and outcome;
implicit missing-row exclusions are rejected, including entirely missing pairs.
This estimator does not implement a missing-data exclusion or imputation policy.
Their bootstrap
intervals and standardized effects quantify uncertainty but do not establish
causality, generalizability, or mechanism.

For protocol-bound empirical execution, matching bytes are necessary but no
longer sufficient. Faraday compares the parsed specification to the frozen
semantic contract and refuses method substitution, outcome switching, changed
group variables or contrast order, estimand drift, and missing-data-policy drift.
Protocol freeze also requires the contract's primary hypothesis to be among the
tested hypotheses and its reviewed `primary_estimand` to match exactly. The
contract must also select a typed primary measurement whose registered dataset
column matches the analysis outcome column.

The analysis contract classifies assignment as `observational`,
`randomized_between_units`, `nonrandomized`, or `not_applicable`. A randomized
between-unit contract must contain the allocation digest produced by `design
randomize`. Execution hashes the observed unit/group mapping and refuses any
drift. This checks recorded allocation identity; it does not establish allocation
concealment, enrollment integrity, treatment delivery, adherence, or blinding.
The executed semantics are retained in the receipt and checked again when a run
draft is created.

General Science Toolkit 2.0.0 preserves raw mean differences when the observed
variance used for standardization is zero. Standardized effects are then JSON
`null`, with `standardized_effect_status: undefined_zero_variance` and an explicit
warning. The empirical bootstrap interval may collapse to a point; this is not
evidence of zero population uncertainty. Null, negative, and positive constant
effects receive the same handling. Consumers must handle nullable standardized
effects and retain the warnings in reports.

## Local experiment add-ons

`research analysis run --protocol <id> --dataset <id>` optionally checks the actual specification's
`study_design`, resolved implementation hash, and exact specification-byte hash against a canonical frozen
protocol before calling the method. The receipt records the checked protocol hash.
Set `analysis_specification_sha256` in the protocol to the SHA-256 of the reviewed
analysis JSON file before freezing. Even whitespace changes require the original
bytes or a prospective protocol amendment. Protocols without structured design
or a specification commitment cannot pass this check. It does not
validate the scientific plan or make an
execution scientific evidence; canonical run and evidence gates still apply.
Without `--protocol`, execution remains an unbound calculation.
If a passed canonical control gate cites an add-on result as its evidence
artifact, its `evidence_location` must be an absolute JSON Pointer that resolves
inside the verified result bytes. Add-on authors should therefore expose control
diagnostics as stable structured result fields rather than prose-only logs.
Faraday verifies pointer existence and artifact identity, not whether the
diagnostic or its human interpretation is scientifically adequate.
The paired options are required together. The input snapshot must match a
registered artifact's hash and declared size, and the dataset must satisfy the
canonical protocol association and exploration/confirmation role rules. The
receipt preserves the dataset's synthetic flag. This check does not authenticate
acquisition, establish measurement validity, or check every artifact in a
multi-file dataset; it identifies the single CSV supplied for this execution.

Execution rejects non-JSON results and non-finite numeric outputs (including
nested NaN or infinities) before publishing a result or completion receipt.
Represent an undefined statistic as `null` with an explicit reason, not NaN.
Add-ons receive an isolated specification copy; changes to it, including nested
parameters, cause execution to fail before publication. Compute derived settings
in separate local variables. This detects accidental specification mutation; it
is not a security sandbox for hostile Python add-ons.

CSV execution parses and hashes one in-memory byte snapshot. Receipt input hashes,
byte sizes, and row counts identify that snapshot even if the source path changes
during execution. The locator is not an immutable archive: retain the original
input separately for reproduction. This does not authenticate acquisition or
establish that a dataset matches a frozen protocol.

An experiment repository does not need to publish or install a Python package.
Place a `research_addon.py` file in its add-on directory and expose either an
`AddonManifest` named `MANIFEST` or a zero-argument `get_manifest()` function.
Load it explicitly:

```bash
research --addon-path /path/to/experiment/addons/example addon list
research --addon-path /path/to/experiment/addons/example analysis run \
  --spec-file analysis.json --data-file observations.csv --output artifacts/run-001
```

Multiple paths may be supplied. `RESEARCH_ADDON_PATH` accepts the platform path
separator for persistent local configuration. Supplying a path authorizes local
Python code execution from that exact add-on, so never load an unreviewed path.

## Installed add-ons

Later, Python packages may publish an entry point in the
`research_machine.addons` group. The loaded object (or zero-argument factory)
must return `research_machine.addons.AddonManifest`. Identifiers are stable and
globally unique; duplicate add-on, method, media-type, or adapter configuration
identifiers fail closed. Registry validation rejects padded adapter contract
handles instead of normalizing them.

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

The next external add-on should be `sleep_acoustic`, migrated from the frozen
Vindication prototype into its own experiment repository. Later candidates include psychology experiment design and
randomization, time-series and signal processing, biological assays,
survey/psychometric validation, causal inference, and literature synthesis.
Each should be added only with a second-domain regression check so shared logic
is generalized into the core rather than copied.
# Independent-unit identity check

The general toolkit's independent mean-difference estimator accepts `unit_column`.
When supplied, every row must have a nonblank, globally unique unit identifier;
repeated identifiers across or within groups fail before estimation. The result
reports whether identities were checked. Omission remains explicitly unchecked,
and unique labels alone do not establish independence or exclude shared clusters.
