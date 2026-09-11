# Notebook freeze-input bundle

Static notebook preflight, runtime preflight, and protocol freeze protect
different boundaries. Repeatedly copying source, manifest, receipt,
interpreter, kernel, working-directory, and digest values creates avoidable
transcription sites. A freeze-input bundle reduces those sites without
weakening any underlying check.

## Create the bundle

Create it only after a clean static dependency preflight and a passed
no-analysis runtime preflight exist:

```bash
research-notebook-freeze-bundle create frozen-source.ipynb \
  --manifest notebook-dependencies.json \
  --workspace-root /absolute/project/root \
  --static-preflight-receipt static-preflight.json \
  --runtime-preflight-receipt runtime-preflight.json \
  --result-json notebook-freeze-input-bundle.json
```

Optional expected-digest arguments can pin the source, manifest, retained
static-preflight receipt, and runtime receipt. Creation recomputes the static
preflight and requires the retained static receipt to match it exactly. It also
verifies that the notebook is clean, its one literal dependency mapping
matches the manifest, every dependency byte matches, and the runtime receipt
satisfies the complete passed no-analysis contract. It starts no kernel,
executes no analysis, requests no network access, refuses to overwrite an
existing output, and writes nothing when verification fails.

## Verify current bytes

Verification starts from an independently trusted bundle digest and replays
the underlying files instead of trusting stored `passed` fields:

```bash
research-notebook-freeze-bundle verify notebook-freeze-input-bundle.json \
  --expect-bundle-sha256 <bundle-sha256>
```

Changing, moving, or removing the source, manifest, a dependency, either
preflight receipt, or the bundle makes verification fail. Noncanonical JSON
and changes to the stored runtime context also fail.

## Bind a protocol

Copy the bundle's `runtime_preflight_requirement` into the protocol and add the
bundle digest as `notebook_freeze_input_bundle_sha256`:

```json
{
  "runtime_preflight_requirement": {
    "receipt_sha256": "<runtime-receipt-sha256>",
    "probe_id": "research-machine-runtime-preflight-v1",
    "interpreter_path": "/absolute/path/to/python",
    "kernel_name": "python3",
    "working_directory": "/absolute/project/root"
  },
  "notebook_freeze_input_bundle_sha256": "<bundle-sha256>"
}
```

Pass the bundle through readiness and freeze:

```bash
research protocol preflight --spec-file protocol.json \
  --notebook-freeze-input-bundle notebook-freeze-input-bundle.json
research protocol freeze <protocol-id> \
  --notebook-freeze-input-bundle notebook-freeze-input-bundle.json
```

Both the CLI and application service enforce the relationship. Omitting the
bundle, supplying only its digest, calling the service directly, or pairing the
bundle with another runtime receipt fails. The bundle digest and typed runtime
context participate in the frozen protocol hash. Human-readable
`inputs_required` hashes do not substitute for the typed fields; new freeze
attempts that describe runtime or freeze-bundle inputs only in prose fail
closed. Historical protocols remain byte-for-byte readable and are not
retroactively upgraded.

## Authority boundary

The bundle is local workflow-integrity metadata. It does not authenticate a
scientific method, establish chronology or independence, guarantee later
kernel availability, validate an output, or create scientific evidence. The
protected executor must still authenticate source and dependencies immediately
before its one execution, and resulting artifacts must enter through normal
run gates.
