# Mathematical predicate contract

Status: prospective machine contract; it does not decide mathematical truth or
upgrade earlier results.

Use `mathematical_predicate_contracts` when a protocol will report a property
such as rank, nullity, invertibility, positivity, conservation, tangency, or
equivalence. Each contract freezes:

- the exact `object_id` and `object_kind`;
- its domain, codomain, quotient convention, and construction;
- the predicate and its operational definition;
- the IDs of objects from which the tested object is derived;
- for equivalence only, the one comparison object and every condition under
  which equivalence is claimed; and
- a shared required gate plus an adversarial control that attempts a
  wrong-object attribution or removes a necessary equivalence condition.

The run gate must repeat the frozen typing and lineage exactly. Its selected
JSON evidence is hash-bound to a run output artifact. A result for a pullback,
restriction, quotient, or projected operator therefore cannot be submitted as
if it were a result for its source operator merely by changing prose.

For example, if

```text
M = J^T D J
```

then `D`, `J`, and `M` require distinct object IDs. A nullity or positivity
result for `M` may name `D` and `J` in `derived_from_object_ids`, but its
`object_id` must remain `M`. Invertibility of `D` does not imply
invertibility of `M`; singularity of `M` does not imply singularity of `D`.

An `equivalent` predicate is rejected unless it names exactly one comparison
object and at least one frozen condition. Typical conditions include equality
on a declared common domain, a named intertwiner, preservation of a specified
form or measure, and the gauge or quotient assumptions under which the
comparison is made.

Passing this gate means only that the recorded result was attributed to the
frozen typed object and retained as matching JSON evidence. Faraday does not
prove the predicate, validate the implementation that computed it, or establish
that the frozen types model the intended physics.
