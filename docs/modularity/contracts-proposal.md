# Faraday modularity contract proposal

Status: `proposed`, not accepted. This document is a local proposal for
reconciliation by the designated shared-contract owner.

## Candidate integrity contract

The smallest candidate shared contract is a versioned, immutable-reference
envelope:

```json
{
  "contract_version": "rigour-record-ref/v0",
  "record_id": "faraday:example-record",
  "record_kind": "protocol|observation|run|receipt|validation",
  "record_revision": "rev-1",
  "artifact_sha256": "<lowercase sha256>",
  "derived_from": ["faraday:prior-record@rev-1"],
  "provenance": {"source": "fixture", "purpose": "projection-only"}
}
```

The eventual contract must define canonical serialization, identifier rules,
revision expectations, artifact-reference semantics, and validation-finding
shape. Hashes establish byte identity/integrity, not scientific truth.

## Proposed operations and ownership

| Operation | Proposed owner | Input | Output | Decision authority |
| --- | --- | --- | --- | --- |
| `emit_record_ref` | Faraday adapter | Existing canonical record and verified artifact | Versioned reference | Faraday retains record ownership. |
| `compile_projection` | Metamaps adapter | Versioned refs plus compiler/module versions | Immutable projection or findings | Metamaps reports structure/findings only. |
| `invalidate_projection` | Metamaps adapter | Changed input revision/hash | New invalidated projection status | Does not delete or rewrite source records. |
| `validate_receipt` | Faraday integrity seam | Run/receipt/artifact refs | Validation findings | Faraday decides scientific/domain status. |

Requested capabilities are not grants. Orca, Cypher, and system-config remain
external ownership boundaries and are not implemented by this slice.

## Compatibility and semantic differences

Faraday's protocol/model commitments, fitting procedures, uncertainty, and
conclusion ceilings are domain semantics. A shared integrity contract must not
turn them into a generic truth score or acceptance state. A Metamaps edge is a
derived explanation of declared lineage/dependency; it is not evidence,
authorization, or a domain review decision.

## Dependencies and blockers

- Shared extraction is blocked until a contract owner accepts the proposal and
  provides a pinned dependency/release.
- Real Metamaps compilation is blocked because no dependency or adapter is
  present in this repository and enabling providers is out of scope.
- The fixture test below intentionally exercises only status/invalidation
  semantics and must not be described as a Metamaps integration test.
