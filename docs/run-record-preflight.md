# Run-record template and preflight

Research Machine intentionally preserves a submitted run with a missing or
failed frozen quality gate as an immutable invalid run. This prevents an
unfavorable execution from disappearing. It also means a clerical mismatch in a
gate label creates permanent append-only noise if it is discovered only during
`run record`.

Two read-only commands expose the frozen contract before submission.

## Generate the exact gate skeleton

```bash
research --workspace .research run template \
  --protocol <frozen-protocol-id>
```

The output copies the frozen `analysis_code_hash` and every
`quality_requirements` string in its original order. It deliberately uses
angle-bracket placeholders, an invalid environment hash, no output artifacts,
and `skipped` gate statuses. It is a construction aid, not a default passing
record.

The response states `template_only: true` and `would_append_event: false`.
Generating it consumes no run ID and writes no canonical file or ledger event.

## Preflight a completed record

```bash
research --workspace .research run preflight \
  --record-file completed-run-record.json
```

The preflight uses the same protocol commitment, code hash, seed, timestamp,
dataset, artifact, quality-gate, and synthetic-status construction as
`run record`, but stops before repository writes. Its report includes:

- the record status and evidence eligibility that submission would produce;
- an explicit-ID conflict that would make submission reject before recording;
- frozen and supplied gate IDs in order;
- missing and additional gate IDs;
- failed supplied-required and frozen-protocol gates;
- exact-set and order comparisons; and
- the SHA-256 and byte count of the exact parsed record file; and
- `would_append_event: false`.

A ready record exits 0. A structurally valid record that would be immutably
recorded as invalid, or whose explicit run ID already exists and would be
rejected, exits 1. Invalid input, an unfrozen or mutated protocol, unknown data,
bad hashes, or other validation errors exit 2. No branch writes a run, consumes
an ID, or appends an event.

Additional passing gates are compatible with the historical `run record`
contract, so a preflight may report `status: ready` while
`exact_quality_gate_set` or `quality_gate_order_matches_protocol` is false. A
client seeking a one-to-one audit should require those fields as an additional
local policy rather than silently changing old recording semantics.

## Boundary and ceiling

The preflight validates a proposed record's structure against canonical state.
It does not re-run code, inspect notebook outputs, hash locator contents, prove
that an execution happened, or establish that gate summaries are truthful.
Submitting after a passing preflight remains a separate explicit command. Bind
the submission to the preflighted bytes when possible:

```bash
research --workspace .research run record \
  --record-file completed-run-record.json \
  --expect-record-sha256 <preflight-record-file-sha256>
```

Without `--expect-record-sha256`, the record file can change between preflight
and submission. With it, Research Machine hashes the bytes it parses and rejects
a different file before constructing or appending the run.
