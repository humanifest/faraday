# Runtime-promotion audit

A runtime can load a workspace successfully while still differing from the
revision intended for promotion, overlooking newer audit semantics, or changing
a representative run's effective evidence eligibility. The standalone
repository-local `research runtime-promotion audit` command combines the
existing read-only checks under one independently hash-pinned manifest.

This is a runtime compatibility gate, not an evidence or scientific promotion
mechanism.

## Manifest

Keep the manifest outside the candidate runtime repository. A file inside the
candidate cannot both name the commit that contains itself and leave that same
commit clean without a circular revision update.

```json
{
  "schema_version": 1,
  "runtime_repository": "/absolute/path/to/candidate-faraday",
  "expected_runtime_revision": "<exact-40-or-64-character-git-revision>",
  "expected_runtime_clean": true,
  "workspace": {
    "path": "/absolute/path/to/project/.research",
    "inquiry_id": "inquiry-id",
    "expected_ledger_head_sha256": "<exact-ledger-head-sha256>",
    "expected_conclusion_ceiling": "<exact-current-audit-ceiling>"
  },
  "representative_run": {
    "record_path": "/absolute/path/to/prospective-run-record.json",
    "expected_record_sha256": "<exact-record-sha256>",
    "expected_preflight_status": "ready",
    "expected_record_status_if_submitted": "completed",
    "expected_effective_evidence_eligibility": false,
    "artifact_root": "/absolute/path/to/run-artifacts"
  },
  "notebook_freeze_bundle": {
    "path": "/absolute/path/to/notebook-freeze-input-bundle.json",
    "expected_sha256": "<exact-bundle-sha256>"
  }
}
```

`notebook_freeze_bundle` is optional. `artifact_root` is optional when the
representative preflight does not require local output-byte verification. A
replication-shaped record may also supply both `attestation_schema_path` and
`expected_attestation_schema_sha256`; neither can appear alone.

The manifest must require a clean runtime. The run expectation can deliberately
be `false`: reproducing an adverse or exposure-restricted eligibility decision
is often the compatibility behavior under test. The audit compares the exact
prediction; it does not prefer eligibility.

The published schema is
`schemas/runtime-promotion-audit-manifest.schema.json`.

## Run

Review and hash the completed manifest independently, then run:

```bash
./research --json runtime-promotion audit \
  --manifest runtime-promotion-manifest.json \
  --expect-manifest-sha256 <reviewed-manifest-sha256>
```

Use the candidate checkout's own `./research` launcher. The audit rejects a
runtime repository when the loaded audit source is not that checkout's exact
`src/research_machine/interfaces/runtime_promotion.py`; this prevents a
different installed Faraday version from testing the candidate by accident.

The command:

1. requires candidate `HEAD` to equal the manifest revision and checks tracked,
   untracked, and submodule status without optional Git locks;
2. runs the existing ledger verifier at the exact expected head;
3. runs the existing rigor audit with `fail_on=never`, requires structural
   validity, and compares its exact conclusion ceiling;
4. hashes and parses the representative record through the existing run-command
   parser, then calls the existing no-write run preflight and compares status,
   record status, and effective eligibility; and
5. when requested, calls the existing freeze-bundle verifier, which replays the
   source, dependency manifest, dependency bytes, static receipt, and runtime
   receipt.

Exit status is 0 only when every requested check agrees with the manifest, 1
for a completed audit with any mismatch, and 2 for an invalid or untrusted
manifest. The report always states `target_workspace_modified: false` and
`scientific_validity_interpreted: false`. It reports whether manifest
expectations were met while keeping `promotion_authorized: false`; the actual
runtime switch remains a separate owner decision. Tests snapshot target
workspace bytes across the audit to protect that read-only contract.

## Boundary

The command does not write a run, consume an identifier, append a ledger event,
change a workspace pin, merge a branch, or promote a runtime. It does not rerun
scientific analysis and cannot authenticate execution, chronology, independence,
method quality, or truth. A result reports only that one candidate checkout and
one current local workspace snapshot behaved as specified by the exact reviewed
manifest.
