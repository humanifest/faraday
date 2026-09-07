# Notebook dependency preflight

Protected notebook execution authenticates the source notebook, but a source
can still contain a mistyped dependency hash. If that check runs inside the
notebook, the error is discovered only after a kernel has started and a
registered execution may already have been consumed.

The dependency preflight is a deterministic, no-kernel check intended to run
before protocol freeze and again immediately before protected execution.

## Manifest contract

The manifest is JSON with this exact logical shape:

```json
{
  "schema_version": 1,
  "dependencies": [
    {
      "locator": "research/input/source.pdf",
      "sha256": "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef"
    }
  ]
}
```

The dependency list must be nonempty. Locators must be unique, relative paths;
SHA-256 values must be 64 lowercase hexadecimal characters. Parent-relative
paths are allowed because a protocol may pin a sibling tool repository, but
the preflight only hashes the explicitly listed file and never discovers files
recursively. Distinct locators that resolve to the same path are rejected.

## Notebook contract

The source notebook must contain exactly one top-level assignment to a named
hash mapping, `EXPECTED_HASHES` by default. The assigned value must be a literal
dictionary whose string keys and values exactly match the manifest. The parser
uses Python's AST and `literal_eval`; it never imports or executes notebook
code. Dynamic expressions, duplicate keys, multiple assignments, or a mapping
inside conditional code fail closed.

A frozen source must also be clean: every code cell has a null execution count
and no outputs.

## Three-way validation

One pass checks all of the following:

1. the source and manifest bytes match optional preregistered hashes;
2. the manifest mapping exactly equals the notebook's literal mapping; and
3. every explicitly listed file exists and matches the declared hash.

The JSON report includes stable finding codes and one observation per
dependency. A non-passing report exits nonzero. An optional report path is
written atomically and is never overwritten.

```bash
research-notebook-preflight frozen-source.ipynb \
  --manifest notebook-dependencies.json \
  --workspace-root /absolute/project/root \
  --expect-source-sha256 <source-sha256> \
  --expect-manifest-sha256 <manifest-sha256> \
  --result-json preflight-report.json
```

The protected runner accepts the same manifest and hash options. When present,
it performs the static preflight before loading the notebook runtime or
starting a kernel. Expected source and manifest hashes must already be canonical
lowercase SHA-256 values; uppercase, padded, or malformed values fail as input
errors rather than being normalized.

## Scope

This is an integrity and provenance check, not a scientific result. It does not
prove that a source is authoritative, a notebook implements the registered
method, or the declared dependencies are sufficient. Those remain protocol,
review, and evidence-classification obligations. It also does not lock files
against changes after the check; protected execution should repeat the
preflight immediately before kernel launch and use an immutable snapshot or an
in-notebook check when concurrent mutation is a realistic risk.
