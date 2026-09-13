# Source-composability evaluator

Faraday's source-composability evaluator is a prospective public-development
tool for describing whether exact source-backed objects have every directed
compatibility relation needed by a proposed chain. It is domain-neutral: the
contract supplies the mathematical signature, dimension, carrier, and domain
for the overall target and for every node and arrow.

The evaluator is available only with
`development_scope: exposed_evaluator_development`. Its output is ineligible
for candidate advancement and grants no scientific-validity, evidence,
replication, independence, conclusion, or runtime-promotion authority.

## Contract

Use [`schemas/source-composability.schema.json`](../schemas/source-composability.schema.json)
to preflight the exchange shape. The runtime then applies cross-reference and
status rules that JSON Schema cannot express. A complete synthetic contract is
published at
[`examples/source-composability.json`](../examples/source-composability.json).

The contract separates:

- `target_node_ids`, the exact required objects;
- `required_arrow_ids`, the explicit evaluation order for directed
  compatibility requirements;
- `nodes` and `required_arrows`, which bind statements, full mathematical
  scope, a declared status, an assessment, and source references; and
- `source_references`, a canonical citation, locator, source role, and SHA-256
  for every retained source record.

The status vocabulary is deliberately non-binary:

- `exact_support` says the cited primary source is declared to support this
  exact node or arrow;
- `adjacent_ingredient` preserves a useful but non-identical construction;
- `direct_limitation` preserves a source-stated obstruction or scope limit; and
- `not_found_in_bounded_search` reports only the outcome of the cited bounded
  search, never global absence.

Every not-found record must cite the declared bounded-search source. Exact
support must cite a primary source. Other affirmative or limiting source
judgments must cite a primary or secondary source. Every target node must occur
in a required arrow, all arrow endpoints must exist, and an arrow cannot claim
exact support if either endpoint lacks exact support.

The first unclosed arrow is the first non-`exact_support` entry in
`required_arrow_ids`. It therefore does not depend on lexical ID sorting or on
the incidental order of the `required_arrows` objects. Reordering the node,
arrow, or source objects does not change the normalized contract. Relabeling
IDs while retaining the same explicit required-arrow order does not change
which compatibility requirement is first.

## Create and replay

Pin the exact specification bytes before evaluation:

```bash
./research --json literature evaluate-composability \
  --spec-file examples/source-composability.json \
  --expected-spec-sha256 <sha256> \
  --output source-composability-evaluation
```

The command writes a new directory containing
`source-composability-evaluation.json` and refuses to replace an existing
directory. The output embeds the normalized contract, its canonical digest,
the original specification-byte digest, complete status counts, every exact
local node, every unclosed arrow, and the deterministic first unclosed arrow.
An unclosed chain with an exact local node is reported as
`unclosed_with_exact_local_support`; it is never reduced to a generic
missing-formula verdict.

Replay both retained artifacts and their caller-trusted hashes with:

```bash
./research --json literature verify-composability \
  --spec-file examples/source-composability.json \
  --expected-spec-sha256 <sha256> \
  --evaluation-file source-composability-evaluation/source-composability-evaluation.json \
  --expected-evaluation-sha256 <sha256>
```

Replay rejects changed bytes, derived summaries, erased locally supported
nodes, falsely closed chains, or altered authority flags.

## Limits

Faraday checks shape, hashes, cross-references, closure consistency, and output
replay. It does not read a source and decide whether the declared status is
correct, authenticate the assessor, establish source truth, prove that a search
was exhaustive, or show that separately supported ingredients compose. These
semantic judgments require source review and, where applicable, mathematical
proof or empirical tests outside this evaluator.
