# Duality and reconstruction contract

Status: prospective machine contract; it records a choice of pairing and
weak-to-strong reconstruction without treating that choice as mathematically or
physically privileged.

A variational derivative is naturally a covector: it acts on admissible
variations. It is not automatically a vector, pointwise tensor, matrix, or
kernel argument. Converting it into one requires extra structure. Use
`duality_reconstruction_contracts` whenever a tested predicate depends on such
a conversion.

Each contract freezes:

- distinct primal and dual space IDs;
- the pairing and its definition;
- the reconstruction map and a hash of its complete specification;
- hashes for the basis and quadrature specifications;
- whether those choices are source-derived, engineering assumptions, or mixed;
- references supporting or declaring those choices;
- any optional transfer map and its specification hash;
- objects that the reconstruction is forbidden to depend on; and
- a shared required gate with an adversarial circularity control.

The contract links to one exact `mathematical_predicate_contract`. A performed
gate must repeat all frozen fields, enumerate the observed dependency closure,
and bind the selected JSON result to a run output artifact. The dependency list
must include the two spaces, pairing, reconstruction map, and optional transfer
map. A passed gate is rejected when that closure includes a forbidden object or
when its linked circularity control does not match expectation.

For a finite-dimensional pairing matrix `G` and covector `r`, the Riesz lift is
`v = G^-1 r`. Under a nonorthogonal coordinate change `x = A x'`, the correct
transforms are `r' = A^T r`, `G' = A^T G A`, and `v' = A^-1 v`. Simply setting
`v = r` is coordinate-dependent unless an identity pairing has been separately
justified. Faraday includes an exact-rational regression fixture for this
generic failure, independent of any quantum-gravity vocabulary.

This contract prevents a downstream tested form or kernel from silently
defining the lift used to feed itself. It does not select a canonical pairing,
prove that a reconstruction exists or is stable, validate a discretization, or
establish a physical interpretation. Those remain scientific obligations.
