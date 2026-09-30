# Faraday modularity assessment

Status: `implemented` for the inventory below; migration decisions remain
`planned` or `blocked` unless explicitly marked otherwise.

## Current purpose and baseline

Faraday is the provider-free Research Machine. Its authoritative application
services preserve inquiry, hypothesis, protocol, dataset, run, evidence, and
ledger state. Scientific-method rules remain Faraday-owned: competing models,
frozen protocol/model references, uncertainty, conclusion ceilings, and
exploratory versus confirmatory distinctions.

The current checkout is `main` at `8d87c07`, with no tracked modifications.
`faraday_migration_prompt.md` is an untracked user-provided instruction file
and is preserved unchanged. This assessment does not claim that the migration
has been accepted or integrated.

## File-backed inventory

| Concern | Existing evidence | Boundary decision |
| --- | --- | --- |
| Canonical records and persistence | `src/research_machine/domain/models.py`, `src/research_machine/ports/repository.py`, `src/research_machine/application/service.py` | Keep Faraday-owned until a shared contract owner accepts a compatible contract. |
| Protocol/model commitments | `src/research_machine/application/policies.py`, `service.py:create_protocol` | Faraday-only methodology; do not move estimators or conclusion rules into a kernel. |
| Runs and receipts | `domain/models.py:ResearchRun`, `service.py:record_run`, `application/run_integrity.py`, `application/artifact_integrity.py` | Candidate integrity seam; preserve existing IDs, hashes, and replay rules. |
| Validation and ledger audit | `application/*_integrity.py`, `service.py:verify_ledger` | Candidate shared validation/provenance contract; acceptance remains application-owned. |
| Synthetic characterization | `tests/test_protocol_migration_compatibility.py`, `test_execution_receipt.py`, `test_artifact_integrity.py`, and related fixtures | Safe local evidence only; not a live experiment or external integration. |
| Metamaps projection | No production Metamaps dependency or adapter was found in the inspected tree. | Fixture-only contract and invalidation test; real integration is blocked. |

## Extraction candidates and uncertainty

The strongest candidate for a future `rigour-core` contract is a narrow,
versioned envelope for stable record references, artifact hashes,
derivation/provenance, and validation findings. The semantics are not yet
demonstrated in two accepted consumers, so this repository must not vendor a
new shared package.

The following remain explicitly out of the first slice: model inference,
statistical estimators, protocol state transitions, evidence eligibility,
provider brokering, job scheduling, authorization, and report interpretation.

Unknowns requiring the contract owner or later authorized work:

- authoritative cross-project contract location and release version;
- actual Metamaps compiler/module API and supported projection format;
- Orca/Cypher/system-config interfaces and grant/effect semantics;
- a saved Faraday end-to-end workflow suitable for old/new shadow comparison.
