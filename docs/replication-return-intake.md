# Replication-return intake

A run record normally carries artifact locators and hashes without requiring
the Research Machine process to possess those files. That is appropriate for
many remote datasets, but it is too weak for an `independent_replication`
claim: the same record could otherwise self-declare an attestation locator,
digest, and clean-room metadata without the machine reading any returned byte.

When a run contains `metadata.replication_independence`, Research Machine now
requires a local, fail-closed intake before it can be recorded:

```bash
research --workspace .research --actor <independent-executor> run preflight \
  --record-file returned-run.json \
  --artifact-root returned-artifacts \
  --attestation-schema independence-attestation.schema.json \
  --expect-attestation-schema-sha256 <pinned-schema-sha256>
```

The preflight performs these checks without writing canonical state:

1. Every output locator is relative, contains no parent traversal, crosses no
   symbolic link, resolves below the supplied root, and names a regular file.
2. Every file's observed SHA-256 and optional byte count match the run record.
3. Exactly one artifact matches the declared attestation locator and carries
   `artifact_role=independence_attestation`.
4. The attestation-schema commitment is a canonical lowercase SHA-256 digest,
   and only then do the attestation-schema bytes have to match it.
5. The schema uses only the machine's fail-closed Draft 2020-12 attestation
   profile, and the attestation satisfies every constraint in that schema.
6. The attestation agrees with the run on executor identity, replicated run,
   analysis-code hash, design, independence dimensions, prior implementation
   access, allowed-input manifest, and contamination disclosures. The core
   agreement check also rejects duplicate attested independence dimensions even
   when the pinned schema omits `uniqueItems`.

Any failure produces `status=would_reject`, an `artifact_integrity` report with
stable finding codes, and no run ID or ledger event. Recording must repeat the
same checks against the current bytes and bind the immutable record file:

```bash
research --workspace .research --actor <independent-executor> run record \
  --record-file returned-run.json \
  --expect-record-sha256 <preflight-record-sha256> \
  --artifact-root returned-artifacts \
  --attestation-schema independence-attestation.schema.json \
  --expect-attestation-schema-sha256 <pinned-schema-sha256>
```

The resulting run stores a machine-reserved `metadata.artifact_integrity`
receipt. A caller cannot supply that field itself. Evidence carrying the
`independent_replication` tag is rejected unless the receipt shows matching
artifacts, a matching and valid schema, and a consistent attestation.
The run's clean-room metadata handles are exact: independence dimensions,
allowed-input locators, contamination disclosures, and the attestation artifact
locator must be canonical without surrounding whitespace before evidence can use
the replication tag. Dimensions, allowed-input entries, and contamination
disclosures must also be duplicate-free, so repeated declarations cannot make a
replication record appear broader or better disclosed. Attestation dimensions
are checked again during local artifact intake, independent of the schema's
optional array-uniqueness rule.

## Supported schema profile

The core package retains zero runtime dependencies. Its attestation validator
therefore implements a deliberately bounded Draft 2020-12 profile:

- local JSON Pointer `$ref` and `$defs`;
- `type`, `required`, `properties`, and `additionalProperties`;
- `const`, `enum`, `allOf`, and `not`;
- string `minLength`, `pattern`, and strict `date-time` format;
- array `items`, `minItems`, `uniqueItems`, and `contains`.

An unknown keyword, external reference, unsupported format, malformed schema,
duplicate JSON key, non-finite JSON number, or cyclic reference rejects intake.
Patterns use Python `re`; the commissioner must keep them within the common
Python/ECMA-262 subset. The machine never silently ignores a constraint it
cannot evaluate.

## Epistemic boundary

This verifies local bytes, a pinned schema, and agreement between two returned
records. It does not authenticate the human or system making the attestation,
prove that the implementation was independently created, re-run the analysis,
or validate a scientific conclusion. Authentication remains an external trust
boundary, and scientific acceptance remains governed by the frozen protocol
and its controls.
