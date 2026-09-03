# External protocol freeze accession

Research Machine normally freezes a protocol before its run begins. A clean-room
executor or outside laboratory may instead freeze and execute in another system,
then return its packet after completion. Canonical intake must preserve that
distinction: registering the returned protocol today cannot be described as a
local preregistration yesterday.

## Required protocol anchor

Create the canonical protocol from the externally frozen specification and give
it a non-empty `external_anchor` that identifies the external commitment. Freeze
the canonical protocol without changing the external method. Its canonical
registration timestamp will truthfully be the later intake time.

## Required run metadata

When the returned run starts before that canonical timestamp, its record must
include:

```json
{
  "metadata": {
    "external_protocol_freeze": {
      "declared_frozen_at": "2026-09-03T10:00:00Z",
      "canonicalized_after_execution": true,
      "protocol_artifact": "independent/protocol/frozen-protocol.md",
      "analysis_source_artifact": "independent/src/analysis.py",
      "freeze_manifest_artifact": "independent/freeze/freeze-manifest.json"
    }
  }
}
```

Each locator must appear exactly once in `output_artifacts` with, respectively,
these `metadata.artifact_role` values:

- `external_frozen_protocol`
- `analysis_source`
- `external_freeze_manifest`

Supply `--artifact-root` during both `run preflight` and `run record`. The normal
safe-path, regular-file, size, and SHA-256 checks apply to all returned outputs.

## Freeze-manifest contract

The external freeze manifest must be strict JSON and contain:

- `frozen_at`, exactly matching `declared_frozen_at` and not later than run start;
- `scientific_execution_count_at_freeze: 0`;
- `analysis_code_sha256`, matching the run and frozen protocol code hash;
- `protocol_sha256`, matching the returned protocol artifact; and
- an `artifacts` array committing to both the protocol and analysis-source
  locators and hashes.

Duplicate keys, non-finite numbers, missing commitments, role ambiguity, hash or
size mismatches, a postdated declaration, or an absent protocol external anchor
fail before a run is appended. `metadata.protocol_chronology` is machine-reserved
and cannot be supplied by the caller.

On success, the run receives a receipt with
`status=externally_attested_pre_execution_freeze`, both canonical and external
times, artifact locators, the external anchor, and
`chronology_cryptographically_verified=false`. The rigor audit keeps an
`EXTERNAL_PROTOCOL_FREEZE_ATTESTED` warning visible.

## Epistemic boundary

This proves that the received artifact bytes agree with each other and that the
declared chronology is internally coherent. It does not authenticate the
executor, prove that no earlier version existed, or supply a trusted timestamp.
Use a signed transparency log, trusted timestamp service, or independently
witnessed registry when stronger temporal authentication matters.
