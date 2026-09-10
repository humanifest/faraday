# Faraday Consumer Integration For Sherlock

This directory is the Faraday side of a Sherlock adoption. It is a bridge, not a
merger:

```text
Faraday owns scientific protocol/run/evidence state.
Sherlock owns source preservation, investigative assertions, annotations, and reports.
Bridge receipts own translation links between the two.
```

Sherlock must stay an external investigation workbench. It can preserve source
material, source-derived assertions, unresolved contradictions, provenance gaps,
and review questions about Faraday work. It must not edit Faraday canonical
state or bypass Faraday's dataset, protocol, run, evidence, rigor, or synthesis
gates.

## Adoption Status

This skeleton is not a completed runtime adoption. Before running
`project_launcher.py`, a reviewer must supply:

- `runtime-lock.json`, copied from `runtime-lock.example.json` and populated
  with the reviewed local Sherlock wheel, digest, Python version, and dependency
  versions;
- a decision to keep `workspace/` as the local Sherlock workspace for this
  Faraday checkout;
- a reviewed `project.json` update if the charter changes.

The launcher comes from Sherlock's pinned consumer integration contract. It
installs only the exact local wheel named in `runtime-lock.json`, using
`--no-index --no-deps --no-compile`, then verifies the staged runtime before
importing Sherlock.

## Boundary Rules

- Faraday IDs are external references in Sherlock, not duplicated canonical
  records.
- Sherlock artifacts, assertions, annotations, or reports are not Faraday
  evidence.
- Faraday may admit a source or note only through its own canonical commands and
  admission gates.
- Bridge receipts are immutable summaries of a translation event. They are not
  review approval, scientific support, or publication authorization.
- Runtime directories, workspaces, wheel files, local source material, and
  generated Sherlock records stay out of public source control.

## Cross-Link Receipts

Use `schemas/sherlock-bridge-link.schema.json` for the narrow export/import
contract between the tools. A receipt should name one Faraday reference, one
Sherlock reference, the exported immutable summary hash, and the explicit
authority boundary.

The first example is in `examples/sherlock-bridge-link.json`. It links a
Faraday evidence record summary to a Sherlock assertion while preserving that
Sherlock cannot promote or mutate Faraday state.

## Initial Commands

After creating a reviewed `runtime-lock.json`:

```bash
python3 project_launcher.py setup
python3 project_launcher.py doctor
python3 project_launcher.py bootstrap
python3 project_launcher.py status
```

The restricted Sherlock workbench can then be served locally:

```bash
python3 project_launcher.py serve --port 8766
```

The server policy is agent-only and local. Review acceptance, publication, and
Faraday state mutation remain outside this integration.
