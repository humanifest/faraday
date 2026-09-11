# Typed measurement contracts

Measurement roles include `primary`, `secondary`, `control`, `exposure`, and
`covariate`. When a causal protocol carries an executable analysis contract,
freeze requires exactly one typed definition for the audited exposure and for
every member of the audited adjustment set, in addition to the ordinary outcome
and control coverage. Each exposure or covariate definition must bind its DAG
node and registered target to the exact analysis data column; modeled outcome,
exposure, and covariate columns must be distinct. Guided causal scaffolds list
these requirements explicitly even before the definitions are complete.
They also require a typed `temporal_role`: `pre_exposure` for adjustment
covariates, `at_exposure` for the exposure, and `post_exposure` for the causal
outcome. Other definitions may declare `time_varying` or `not_applicable` when
scientifically appropriate. Free text remains available in `evaluation_point`,
but cannot substitute for the causal ordering check.

This establishes semantic and provenance custody. It does not demonstrate that
an observable validly measures a construct, that measurement precedes exposure,
that error is nondifferential, or that an asserted DAG node exists as described.

Protocol prose can name a control while omitting the evaluation time or another
choice needed to reproduce its number. `measurement_definitions` closes that
gap prospectively without changing historical protocols.

When a protocol supplies any measurement definitions, the freeze gate requires
exactly one entry for its primary outcome, every secondary outcome, and every
registered control. `registered_target` must exactly equal the corresponding
protocol string. Every entry has these fields:

- `measurement_id`: unique stable identifier;
- `role`: `primary`, `secondary`, `control`, `exposure`, or `covariate`;
- `registered_target`: exact primary, secondary, or control text;
- `temporal_role`: optional generally, but mandatory and role-constrained for
  executable causal outcome, exposure, and adjustment measurements;
- `observable`: mathematical or empirical quantity measured;
- `input_condition`: the input, state, or dataset slice;
- `parameter_values`: a nonempty string-to-string map, with units or an explicit
  `not applicable` binding;
- `evaluation_point`: time, scale, iteration, or other evaluation location;
- `convention`: sign, ordering, basis, normalization, or coordinate convention;
- `aggregation`: reduction from observations to the reported value;
- `tolerance`: the fixed acceptance or comparison tolerance; and
- `expected_behavior`: the prospectively expected control or outcome behavior.
- `data_column`: the exact dataset column carrying that measurement when the
  definition is selected by an executable analysis contract.
- `scale_type`: for every executable column, one of `binary`, `nominal`,
  `ordinal`, `interval`, `ratio`, `count`, or `time_to_event`;
- `unit`: the physical unit or an explicit semantic unit such as `category`,
  `count`, or `unitless`;
- `admissible_values`: the complete registered domain for categorical variables;
- `valid_min` and `valid_max`: optional inclusive finite bounds for numeric
  variables; and
- `missing_value_codes`: the exact allowed missing encodings, using `<blank>`
  to register an empty CSV field.

The machine checks completeness, roles, exact target coverage, unique IDs, and
nonempty fields at freeze. It does not decide whether a chosen observable,
tolerance, or expectation is scientifically justified. That remains part of
review, source comparison, and falsification design.

Every measurement definition with a `data_column` must carry this typed value
contract. Freeze rejects malformed categorical domains, binary domains that do
not contain exactly two values, nonfinite or inverted numeric bounds, negative
bounds for ratio/count/time-to-event variables, noninteger count bounds,
overlapping missing and admissible values, and mean/linear-effect analyses whose
primary scale is nominal, ordinal, or time-to-event. In adjusted causal analyses,
the exposure domain must exactly match the frozen contrast groups in order and
adjustment covariates must use supported numeric scales.

Protocol-bound execution then checks every source value before invoking the
analysis method. Unregistered blank or coded missing values, out-of-domain
categories, nonnumeric or nonfinite numeric values, out-of-range observations,
and fractional counts fail closed. The receipt records per-measurement observed
and missing counts. Passing proves conformance to the frozen encoding contract;
it does not establish calibration, construct validity, independence, or absence
of measurement error.

An empirical protocol with a pinned executable analysis must provide the typed
measurement set. Its `analysis_contract.primary_measurement_id` must select the
registered primary-outcome definition, and that definition's `data_column` must
exactly match the executed `outcome_column`. This prevents silent substitution
of a secondary measure or surrogate column; it does not establish construct
validity or prove that source rows contain truthful measurements.

Omitting the entire field remains supported for backward compatibility and does
not imply that an old protocol was complete. New sealed numerical replication
protocols should use the typed contract.

## Named-component subset invariants

Vector-, graph-, tensor-, channel-, and other component-valued measurements can
optionally add `named_component_contracts`. This addresses a narrower failure
mode than measurement validity: code may select positions that happened to
carry the intended labels in one ordering, then silently select different
components after an input reorder.

Each contract freezes a unique `contract_id`, an exact `measurement_id`, the
complete ordered `component_ids`, the intended `selected_component_ids`, a
nontrivial `relabeled_component_ids` permutation, and an adversarial
`relabeling_control_id` sharing its required `evaluation_gate_id`. Freeze
rejects unknown measurements or controls, duplicate labels, non-subsets,
non-permutations, and relabelings that do not move at least one selected
component. Scalar measurements need no such contract.

A performed gate records both observed component orders, both zero-based index
maps, and the names those maps actually selected. Faraday derives the selected
names from each recorded order and index map. A passing gate requires both maps
to recover the frozen named subset and requires the linked adversarial control
to match expectation. A positional map that selects decoys after relabeling can
be retained as `contradicted_named_selection` only under a failed gate; it
cannot be represented as a pass. Run evidence must cite a declared output
artifact and an exact JSON location containing the six reported order, index,
and selected-name arrays. Intake compares those arrays with the retained bytes;
replication-package verification replays the frozen mapping invariant over the
packaged metadata.

This proves only that the recorded subset map is invariant under the frozen
permutation. It does not prove that the labels denote the right scientific
objects, that all necessary components were included, or that the downstream
mathematics is correct.

## Raw-to-derived custody

Every transformation in a new custody receipt names a stable ID and version,
an offset-aware `performed_at`, `implementation_locator` and
`implementation_sha256`, its input digest, and
`output_locator` and `output_sha256`. Inputs must resolve to an immutable raw
source or an earlier transformation output. Outputs must be new, unique artifact
identities; reusing an input or earlier output digest is rejected.

Chronology is checked within the receipt: a transformation cannot predate its
input, a measurement-quality gate cannot predate a named calibration
prerequisite, and a derived observation cannot predate its transformation
output. Gates use `evaluated_at`; observations use `derived_at`. These are
internally consistent timestamp attestations, not trusted timestamps or proof
that work happened when claimed.

Each passed measurement gate also lists nonempty
`prerequisite_artifact_sha256s`. Every digest must identify an available raw or
transformation output and must exist by `evaluated_at`. A derived observation
lists the passed `quality_gate_ids` that clear it, and each named gate must cite
that observation's exact transformation output as a prerequisite. Thus a free-
floating calibration or gate cannot authorize an unrelated dataset.

With an artifact root, validation verifies the bytes of raw sources,
transformation implementations, transformation outputs, and calibration/gate
evidence. Protected dataset registration requires this complete byte check and
stores its scope and integrity report. Registered dataset artifacts must be
exactly the outputs selected by derived observations. These checks prove local
byte identity and lineage, not that an algorithm is scientifically valid or
that a raw capture truthfully represents the physical process.

`research measurement template --protocol PROTOCOL_ID` provides the same
contract without JSON invention or an LLM. It reads a frozen protocol, copies
its exact custody gate IDs and quantitative calibration criteria into a review-
only skeleton, and leaves every observation, digest, timestamp, prerequisite,
and disposition unresolved. Template generation writes no canonical state.
