# Typed measurement contracts

Protocol prose can name a control while omitting the evaluation time or another
choice needed to reproduce its number. `measurement_definitions` closes that
gap prospectively without changing historical protocols.

When a protocol supplies any measurement definitions, the freeze gate requires
exactly one entry for its primary outcome, every secondary outcome, and every
registered control. `registered_target` must exactly equal the corresponding
protocol string. Every entry has these fields:

- `measurement_id`: unique stable identifier;
- `role`: `primary`, `secondary`, or `control`;
- `registered_target`: exact primary, secondary, or control text;
- `observable`: mathematical or empirical quantity measured;
- `input_condition`: the input, state, or dataset slice;
- `parameter_values`: a nonempty string-to-string map, with units or an explicit
  `not applicable` binding;
- `evaluation_point`: time, scale, iteration, or other evaluation location;
- `convention`: sign, ordering, basis, normalization, or coordinate convention;
- `aggregation`: reduction from observations to the reported value;
- `tolerance`: the fixed acceptance or comparison tolerance; and
- `expected_behavior`: the prospectively expected control or outcome behavior.

The machine checks completeness, roles, exact target coverage, unique IDs, and
nonempty fields at freeze. It does not decide whether a chosen observable,
tolerance, or expectation is scientifically justified. That remains part of
review, source comparison, and falsification design.

Omitting the entire field remains supported for backward compatibility and does
not imply that an old protocol was complete. New sealed numerical replication
protocols should use the typed contract.
