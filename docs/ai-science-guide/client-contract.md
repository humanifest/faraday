# G01 guide client contract

Status: G01 locally verified against synthetic fixtures. This document does
not activate a provider or a scientific workflow.

The guide client uses `research --json collaborator context --purpose ...
--output ...` to obtain a version-2, redacted, read-only snapshot and a trusted
`context_sha256`. The snapshot retains the original inquiry statement, open
questions, record references, dataset inventory, scientific constraints, and
the exact write boundary. The client obtains available method IDs separately
from `research --json addon list`; G04 must bind the selected method, manifest,
and analysis specification before execution. A method-list display is not a
protocol commitment.

The client returns the existing version-1 collaborator proposal format and
passes it to `research --json collaborator validate-proposal` with the trusted
context hash. Validation rejects changed context bytes, unknown references,
and any suggestion whose authority is not `review_only`. A successful record
is `pending_human_review`, performs no canonical writes, invokes no model from
Faraday, creates no evidence, and grants no action. Any later question,
hypothesis, design, or analysis operation goes through the existing canonical
service command and its applicable gates. The client must not edit workspace
JSON or the ledger directly.

`tests/test_guide_contract.py` uses the labeled G00 synthetic inquiry to test
the full snapshot, schema, proposal, and verification round-trip. It also
asserts that three adverse proposals leave no output: wrong trusted context
hash, invented record reference, and claimed approval authority. The test
checks that inquiry state and ledger integrity remain unchanged. Existing
collaborator schemas and validators are reused; there is no parallel guide
proposal schema or provider dependency.

## G01 preparation note (gate incomplete at that time)

- Base commit: `ea3f3b1`. Changed paths are this document,
  `tests/test_guide_contract.py`, and the method-catalog wording in `goal.md`.
  No production code changed.
- Planned test effects: a temporary synthetic canonical workspace, a frozen
  collaborator context, a review-only proposal record, and three rejected
  proposal outputs under pytest's temporary directory. No network, model,
  secret, real dataset, or source-tree write is part of the test.
- Observed check: `ast.parse` of `tests/test_guide_contract.py` passed. The
  required `python3 -m pytest -q tests/test_guide_contract.py` remains unrun
  because all available Legion interpreters lack `pytest` and `jsonschema`.
- G01 is prepared, not verified or accepted. G00's exact pytest gate is also
  pending; the G01 acceptance transition remains dependent on it.

## G01 local verification (2026-10-08)

With the authorized test dependencies in Faraday's ignored `.venv`, the
required `python3 -m pytest -q tests/test_guide_contract.py` passed (1 test)
after G00 passed. The environment selected the virtual environment through
`PATH`; umask 077, no bytecode, no plugin autoload, and no pytest cache kept
effects in disposable fixture state. The hash, reference, and authority adverse
cases were exercised by that test. G01 is locally verified, without provider
activation or scientific acceptance.
