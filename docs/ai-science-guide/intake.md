# G02 literal question intake

Status: G02 locally verified against synthetic fixtures. This is a read-only
intake preview, not a completed inquiry or scientific finding.

Run `research --json guide intake --brief-file brief.json` with a JSON object
containing an exact `original_statement` and optional `title`, `population`,
`unit_of_observation`, `outcome`, `comparison`, `time_window`, `decision`,
`minimum_evidence`, `decision_owner`, `decision_change_criteria` (array),
`available_data_sources` (array), and `ethical_constraints` (array). An absent
field stays `null` in `supplied_fields`; the preview returns a corresponding
clarifying question. It does not extract supposed answers from the statement.
Blank or padded values, unknown fields, and duplicate decision criteria fail
instead of becoming generated assertions. The source statement must be
non-blank and unpadded so that an explicitly routed `CreateInquiry` round-trip
retains it byte for byte.

When a title is supplied, `proposed_commands` maps exact supplied values to
the existing `CreateInquiry` command and suggested open questions to
`AddQuestion`. The CLI does not execute these commands. A separate explicit
service or CLI operation is needed to create canonical state. Without a title,
the preview has no command proposal and asks for one. Dataset provenance,
measurement validity, and ethics remain unresolved until independently
recorded and reviewed through their established paths.

## G02 preparation note (gate incomplete at that time)

- Base commit: `7c9a7bd`. Changed paths: this document,
  `src/research_machine/application/guide.py`, `src/research_machine/interfaces/cli.py`,
  and `tests/test_guide_intake.py`.
- Planned effects: read a local JSON brief and produce a JSON preview without
  touching a workspace; focused test explicitly writes a synthetic inquiry,
  open questions, and ledger events only under pytest's temporary directory.
  No model, network, secret, real dataset, or source-tree write is needed.
- Observed checks: Python AST parse passed. The required pytest attempt,
  `umask 077; PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src RESEARCH_ADDON_PATH=
  python3 -m pytest -q -p no:cacheprovider tests/test_guide_intake.py`, exited
  1 before collection with `No module named pytest`.
- A first shell heredoc probe could not create its shell temporary file under
  the current sandbox. A second, narrowly escalated `python3 -c` probe using
  `TemporaryDirectory` passed: the CLI made no workspace, explicit service
  routing preserved the original statement, created ten open questions, and
  verified the ledger. This probe does not replace the pytest gate.
- G02 remains prepared and unverified. G00 and G01 acceptance dependencies
  remain pending. The one-time test-dependency authorization request is still
  unanswered; no package was installed.

## G02 local verification (2026-10-08)

After G00 and G01 passed, `python3 -m pytest -q tests/test_guide_intake.py`
passed (2 tests) with `PATH` selecting the authorized `.venv`, umask 077,
bytecode disabled, plugin autoload disabled, and pytest cache disabled. The
preview made no workspace; the test's explicit service routing wrote only to
disposable fixture state and verified the ledger. G02 is locally verified.
