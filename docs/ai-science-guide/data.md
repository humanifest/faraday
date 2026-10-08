# G05 CSV preview and custody handoff

Status: locally verified with synthetic fixtures. The preview is not a
registered dataset or evidence.

`research --json guide data --file INPUT.csv --spec-file SPEC.json` reads one
CSV byte snapshot, computes its SHA-256 and size, and reports row/unit counts,
declared column roles and measurement scales, observed and missing counts, and
quality issues. `--expect-sha256` fails if the bytes changed. The bounded
preview accepts at most 16 MiB and currently supports declared independent
groups. It reuses Faraday's CSV parser, unit-structure check, and executable
measurement-domain validator. It does not copy, transform, register, or expose
raw rows in its output. The spec must provide exact unit, group, and outcome
columns, two ordered group labels, and executable measurement definitions.

Every preview reports `unregistered_input` and explicit gaps for canonical
registration, source authority, measurement custody, and measurement validity.
Invalid values and repeated independent-unit identifiers add quality gaps.
A blank value counts as missing only when its code is declared. Unvalidated
columns retain an unresolved type. A preview never claims scientific evidence
eligibility, even when its local checks pass.

A later explicit `dataset register` through `ResearchService` can retain the
previewed hash and a role/lineage manifest. G05's fixture registers only a
synthetic exploratory dataset. Its canonical inventory identifies the
synthetic observation-access ceiling and unverified measurement custody.
Real source rights, consent, calibration, and scientific interpretation need
their existing review paths. The preview cannot promote them.

## G05 work receipt (2026-10-08)

- Base commit: `c61808e`. Changed paths: this note,
  `src/research_machine/application/guide.py`,
  `src/research_machine/interfaces/cli.py`, `tests/test_guide_data.py`, and
  the G05 status in `milestones.json`.
- Fixture: `guide-independent-v1`, plus temporary duplicate-unit, invalid
  numeric, and declared-missing variants. Planned and observed effects:
  read-only preview of source bytes; temporary adverse CSV/spec files; and a
  separate synthetic service registration under pytest's temporary directory.
  No real data, source-tree output, model, network, or secret access.
- Acceptance command: `python3 -m pytest -q tests/test_guide_data.py` with
  `PATH` selecting Faraday's `.venv`, umask 077, bytecode disabled, plugin
  autoload disabled, pytest cache disabled, and no external add-on path.
  Result: 2 passed.
- The exact source fixture bytes remained unchanged. Changed bytes failed the
  expected-hash check; duplicate identity and an invalid outcome were reported
  as quality issues. Registration retained the hash but did not establish
  custody or scientific validity. This is local fixture verification only.
