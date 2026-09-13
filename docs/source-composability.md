# Source-composability evaluator

Faraday's source-composability evaluator is a prospective public-development
tool for describing whether exact source-backed objects have every directed
compatibility relation needed by a proposed dependency graph. It is
domain-neutral: the
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

- `target_node_ids`, the exact required objects in a topological order with
  every arrow source before its target;
- `required_arrow_ids`, the explicit evaluation order for directed
  compatibility requirements;
- `nodes` and `required_arrows`, which bind statements, full mathematical
  scope, a declared status, an assessment, and source references; and
- `source_references`, a canonical citation, safe relative artifact locator,
  source role, and SHA-256 for every retained source record.

The status vocabulary is deliberately non-binary:

- `exact_support` says the cited primary source is declared to support this
  exact node or arrow;
- `adjacent_ingredient` preserves a useful but non-identical construction;
- `direct_limitation` preserves a source-stated obstruction or scope limit; and
- `not_found_in_bounded_search` reports only the outcome of the cited bounded
  search, never global absence.

Every not-found record must cite the declared bounded-search source. Exact
support must cite a primary source. Other affirmative or limiting source
judgments must cite a primary or secondary source. The required directed graph
must be weakly connected and acyclic, every arrow endpoint must exist, and an
arrow cannot claim exact support if either endpoint lacks exact support. Every
node and arrow must exactly match the target signature and dimension. Carrier
and domain transitions remain explicit in arrow text for human review; Faraday
does not semantically validate them.

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
  --source-artifact-root examples/source-composability-sources \
  --output source-composability-evaluation
```

The source root is a separately trusted local directory. Each locator must name
a relative regular file beneath it; absolute paths, path traversal, symlinks,
missing files, directories, NUL, newline, and other control characters are
rejected. `O_NOFOLLOW` and directory-descriptor support are mandatory; Faraday
fails closed on a platform that cannot provide them. Creation opens every path
relative to a held source-root descriptor, hashes each source, and compares
device, inode, size, modification time, and change time before and after the
read. The retained receipt includes its declared and observed SHA-256, observed
byte size, and `matched` status.

The command writes a new directory containing
`source-composability-evaluation.json` and refuses to replace an existing
directory. Reservation and publication are descriptor-relative: Faraday holds
the parent descriptor, creates and opens the reserved directory relative to it,
creates the child with exclusive no-follow flags relative to the reserved
descriptor, flushes and syncs the bytes, and then verifies that the parent entry
still names the same non-symlink directory inode. A concurrently created empty
destination is not replaced. Rename-and-substitute attacks cannot redirect the
JSON and cause reported success; an entry substitution or write failure fails
closed and may leave the reserved or partially written artifact for diagnosis.
The output embeds the normalized contract, its canonical digest,
the original specification-byte digest, complete status counts, every exact
node, every unclosed arrow, and the deterministic first unclosed arrow. A graph
with an exact node and an unclosed arrow is reported as
`required_graph_has_unclosed_arrows_with_exact_node_support`; it is never
reduced to a generic missing-formula verdict.

Replay both retained artifacts and their caller-trusted hashes with:

```bash
./research --json literature verify-composability \
  --spec-file examples/source-composability.json \
  --expected-spec-sha256 <sha256> \
  --source-artifact-root examples/source-composability-sources \
  --evaluation-file source-composability-evaluation/source-composability-evaluation.json \
  --expected-evaluation-sha256 <sha256>
```

Replay reopens and re-hashes all source artifacts. It rejects source mutation,
deletion, substitution by symlink, path escape, changed specification or
evaluation bytes, derived-summary changes, erased exactly supported nodes,
false graph-support claims, or altered authority flags.

## Limits

Faraday verifies that observed file bytes match the contract and checks shape,
cross-references, graph topology, exact signature/dimension equality, and output
replay. It does not interpret source semantics, validate internal source or
bounded-search schemas, decide whether a declared status is correct,
authenticate the assessor, prove search exhaustiveness, semantically validate
carrier/domain transitions, or show that separately supported ingredients
compose. Those judgments require source review and, where applicable,
mathematical proof or empirical tests outside this evaluator.

The filesystem threat model covers hostile path components below the trusted
source root and rename/symlink substitution of the output entry during the
command. It relies on the local kernel's descriptor, no-follow, exclusive-create,
metadata, and synchronization semantics. It does not claim to prevent an actor
with filesystem write access from altering an artifact after the command has
returned; replay and trusted hashes detect such later changes.
