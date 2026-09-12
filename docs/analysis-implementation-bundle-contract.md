# Analysis implementation bundle contract

Use `analysis_implementation_bundle_contracts` when one analysis depends on
more than a single content-addressed implementation byte stream, especially
for formal and computational runs outside the notebook-specific freeze-bundle
path.

Each contract freezes:

- the protocol `analysis_code_hash` that selects the contract;
- one or more safe relative entrypoint locators;
- a locator-sorted, duplicate-free list of code members, roles, byte sizes, and
  SHA-256 values;
- a machine-recomputed canonical aggregate over the complete member records;
- the closure method and its exact specification;
- explicit closure limitations;
- the allowed external-dependency boundary and its specification;
- the expected observed-member receipt format; and
- an adversarial omission control evaluated at the same required gate.

Supported closure methods are `static_import_graph`, `runtime_trace`, and
`static_plus_runtime_trace`. None is silently treated as perfect. Static
analysis can miss dynamic imports, generated code, subprocesses, plugins, or
external services. Runtime tracing observes only the executed paths. Every
contract must therefore state at least one limitation.

## Run result

A performed gate returns one exact
`analysis_implementation_bundle_results[contract_id]` object. It repeats the
frozen fields and reports the observed entrypoints, member locators and member
hash map, bundle aggregate, closure method, external dependencies, and a
Boolean closure decision. It also cites an exact JSON object in one listed run
artifact. Run intake derives `selected_value_sha256` from that object.

A passed gate is rejected unless:

1. the observed entrypoints, ordered member set, member hashes, aggregate,
   closure method, and external dependency set exactly match the contract;
2. `observed_closure_complete` is true;
3. the linked adverse-omission control matches its expectation; and
4. the retained artifact-selected JSON exactly equals the submitted result.

Replication-package verification replays the same metadata boundary. Safe
relative analysis-member locators remain in a redacted replication package so
the member set can still be verified; general artifact and filesystem
locators remain redacted.

## Required adverse fixture

The minimum useful control has an entrypoint import a helper. Removing the
helper from a submitter-defined manifest can leave that manifest's own scalar
aggregate unchanged. The closure receipt must nevertheless observe the helper
and reject the incomplete exact set. A second mutation changes one member's
bytes and must fail both its member hash and the aggregate.

## Ceiling

This contract establishes only consistency between a frozen declared code
surface and an artifact-bound observed closure receipt within its stated
method. Hashes prove byte identity, not semantic correctness. A closure receipt
does not prove that the tracing or static-analysis implementation was honest,
complete outside its stated scope, or scientifically appropriate. Independent
review, controls, result validation, and conclusion ceilings remain necessary.
