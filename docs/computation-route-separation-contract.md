# Computation route separation contract

Use `computation_route_separation_contracts` when one registered result compares
exactly two computational routes and the scientific argument depends on those
routes not silently sharing analysis code.

This is stricter than comparing two scalar outputs. Equal outputs can arise from
two entrypoints that both call the same hidden solver. It also composes with,
rather than replaces, `analysis_implementation_bundle_contracts`: each route
must reference one complete frozen bundle.

## Frozen boundary

Each contract freezes:

- exactly two distinct `route_ids` and two distinct, positionally corresponding
  `implementation_bundle_contract_ids`;
- a nonempty sorted list of approved shared input-object IDs;
- the exact sorted intersection of the two bundle member sets as
  `approved_shared_member_locators`, with identical hashes and byte sizes in
  both bundles;
- the complete sorted set of forbidden edges from each route to every
  route-exclusive member in the other bundle;
- one mathematical predicate contract and its exact comparison domain;
- hashes for the comparison domain, output alignment, and norm specifications;
- the norm ID, unit, comparator, and finite nonnegative tolerance;
- one supported static method and specification hash;
- one supported runtime method and specification hash;
- explicit separation limitations; and
- an adversarial shared-helper control attached to the same required gate.

Supported static methods are `static_import_graph` and
`static_dependency_graph`. Supported runtime methods are
`runtime_import_trace` and `runtime_call_trace`. These names select a frozen
receipt method; Faraday does not silently infer that either method has complete
coverage.

The two referenced bundles must each retain at least one route-exclusive member.
Their declared intersection must equal the approved shared-member list exactly.
This prospective check catches a shared solver that is honestly present in both
bundle manifests but omitted from the claimed sharing boundary. If a solver is
omitted from the bundle manifests too, the implementation-bundle closure gate is
responsible for rejecting that separate defect.

See the synthetic [protocol fragment](../examples/computation-route-separation-contract.json).

## Run receipt

The performed gate returns one exact
`computation_route_separation_results[contract_id]` object. It repeats every
frozen scientific and code-boundary field, then reports:

- the observed route IDs, bundle IDs, and shared input IDs;
- separately observed static and runtime shared-member sets;
- separately observed static and runtime directed dependency edges;
- whether each static and runtime receipt was complete;
- the separation decision deterministically recomputed for each method;
- the finite comparison value and the comparator decision recomputed from the
  frozen tolerance;
- a constrained assessment status, witness, and interpretation; and
- an exact JSON-object location in a listed output artifact.

Run intake derives `selected_value_sha256` from the artifact-selected JSON. A
passed gate requires both receipts to be complete, both observed shared-member
sets to equal the approved set, no frozen forbidden edge to appear, and the
adverse shared-helper control to match expectation. Replication-package
verification replays the same metadata boundary and preserves safe relative
member locators needed to interpret the directed edges.

The comparison predicate is intentionally separate from execution quality. A
comparison value that misses the frozen tolerance is a valid disconfirming or
inconclusive scientific result when the separation receipts are otherwise
faithful; it is not rewritten as a gate failure.

## Required adverse fixture

The decisive fixture has `route_a.py` and `route_b.py` both consume the approved
`shared_fixture.py` but also import `shared_solver.py`. Each individual bundle
can be complete and internally hash-consistent, and the two outputs can agree.
The route contract must still reject a sharing declaration that lists only
`shared_fixture.py`. Faraday's test fixture retains this case under
`tests/fixtures/computation_routes/`.

## Ceiling

A passed contract establishes only consistency between the frozen code-sharing
boundary and the artifact-bound static and runtime receipts within their stated
coverage. It does not authenticate the executor, prove that tracing is globally
complete, establish independent reasoning or authorship, or show that either
route or the shared scientific specification is correct. Common conceptual
errors, copied formulas, shared external services, compiler defects, and
unexercised dynamic paths can survive this check.
