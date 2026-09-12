# Reconstruction family stability contract

Use `reconstruction_family_stability_contracts` only when a result will be
compared across resolutions or used toward a refinement or continuum claim. A
single invertible reconstruction matrix is not evidence that a family remains
well posed: its smallest singular value or inf-sup constant may collapse while
every finite member remains invertible.

Each contract links to one exact `duality_reconstruction_contract` and freezes:

- at least two resolution IDs and the family specification hash;
- distinct primal and dual norm IDs;
- one typed stability statistic, comparator, and finite nonnegative threshold;
- the residual test-family span and its specification hash;
- distinct forward and reverse cross-projection maps, their shared
  specification hash, and an error threshold;
- one or more transfer map IDs and their specification hash; and
- an adversarial control that must detect an individually invertible family
  whose registered stability condition fails.

The performed gate must return one finite stability value for every frozen
resolution and finite nonnegative errors for both cross-projection directions.
A passed gate is rejected when any value violates the frozen comparator or
either cross-projection error exceeds its threshold. The result and its exact
selected JSON value remain artifact-bound and are replayed when a replication
package is verified.

Passing is deliberately narrow. It establishes conformance only for the frozen
finite family, norms, statistic, span, transfers, and tolerances. It does not
prove asymptotic convergence, a continuum or renormalization limit, covariance,
or the validity of a downstream scientific model.

The built-in non-physics fixture uses `M_h = diag(1, h)`. Every `M_h` at positive
`h` is invertible, but its smallest singular value is `h` and the inverse norm
is `1/h`. This makes the false inference from per-resolution invertibility to
uniform stability fail visibly.
