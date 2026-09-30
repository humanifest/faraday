# Faraday migration verification

Status: `verified` only for the read-only inspection and fixture contract
scaffold below. No migration acceptance, live integration, provider enablement,
or deployment is claimed.

## Read-only inspection performed

- `git status --short --branch`, `git remote -v`, and `git log -1 --oneline`:
  checkout is `main` at `8d87c07`; only the user-provided migration prompt was
  untracked before this scaffold; origin is GitHub over SSH; no remote action
  was taken.
- `rg --files` and targeted `rg` searches across `src/`, `tests/`, `schemas/`,
  `docs/`, `README.md`, `AGENTS.md`, and the migration prompt: existing
  protocol/run/receipt/integrity seams were identified; no Metamaps production
  dependency or adapter was found.
- `sed` inspection of `AGENTS.md`, `README.md`, `docs/architecture.md`, and
  `faraday_migration_prompt.md`: repository boundaries and required artifacts
  were read before editing.

## Fixture verification

Command to run locally without installing dependencies:

```text
python -m pytest -q tests/test_modularity_fixture_contract.py
```

Expected fixture count: 3 tests covering projection version metadata,
changed-input invalidation, and unchanged-input validity. This is a pure local
contract test, not a Metamaps integration test. On 2026-09-30,
`PYTHONDONTWRITEBYTECODE=1 PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python3 -m pytest
-p no:cacheprovider -q tests/test_modularity_fixture_contract.py` could not
start: the available Python 3.14 reported `No module named pytest`. No
dependency was installed, and the fixture test remains unverified.

The same review parsed all seven new JSON files in `docs/modularity/`,
`docs/reconciliation/`, and `tests/fixtures/modularity/` with Python's
standard-library `json` parser; all parsed successfully. That check does not
validate either proposal schema or the fixture's behavior.

Additional planned check:

```text
git diff --check
```

## Known gaps and blockers

- Real Metamaps compiler/API/version is unavailable in this repository.
- No accepted cross-project `rigour-core` contract or contract owner handoff
  is available.
- No selected saved Faraday end-to-end workflow has yet been authorized for
  old/new shadow execution.
- Orca, Cypher, and system-config interfaces are not implemented or enabled by
  this scaffold.
- The fixture does not establish substantive truth, scientific validity,
  authorization, or successful external execution.
