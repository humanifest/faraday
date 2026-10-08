# G06 pinned synthetic analysis

Status: locally verified for three synthetic two-group variants. Analysis
execution alone remains ineligible for canonical scientific evidence.

`research --json analysis run` now accepts optional `--expect-spec-sha256` and
`--expect-input-sha256`. The host should retain these hashes from a prospective
plan and source snapshot. Execution checks them against the same spec and CSV
bytes it parses before invoking a method. A changed method, seed, contrast, or
other spec byte changes the spec hash; changed data bytes change the input
hash. A caller supplying new hashes after seeing an outcome has not preserved
a prospective choice. Protected evidence still requires the existing frozen
protocol and dataset checks, run intake, and applicable quality gates.

The G06 fixture exercises the bundled independent mean-difference CI, paired
mean-difference CI, and covariate-adjusted observational method. The results
retain effect estimates, intervals, exclusions or missing-row counts,
method-specific diagnostics/warnings, assumptions, and enforced claim
ceilings. The analysis receipt binds the method/add-on version, exact spec and
input bytes, implementation hash, output hash, randomness control, and
non-evidence status. `verify_execution_output` checks the trusted receipt and
result bytes, but its scope expressly does not recheck current input/code
bytes, environment, chronology, or scientific gates. The fixture independently
compares those local hashes; G09 must repeat that external check.

## G06 work receipt (2026-10-08)

- Base commit: `ce3f4f6`. Changed paths: this note,
  `src/research_machine/addons/execution.py`,
  `src/research_machine/interfaces/cli.py`, `tests/test_guide_analysis.py`,
  and the G06 status in `milestones.json`.
- Fixtures: `guide-independent-v1`, temporary complete pairs, and temporary
  observational groups with a prespecified covariate. Planned and observed
  effects: local CSV/spec reads and write-once analysis outputs under pytest's
  temporary directory. No real data, canonical evidence, network, provider,
  secret, or source-tree output.
- Acceptance command: `python3 -m pytest -q tests/test_guide_analysis.py`
  with `PATH` selecting Faraday's `.venv`, umask 077, bytecode disabled,
  plugin autoload disabled, pytest cache disabled, and no external add-on path.
  Result: 2 passed.
- Adverse cases: a method switch after the first result, changed input bytes,
  repeated pair IDs under an independence claim, a nonnumeric outcome, and an
  altered receipt all failed; rejected executions left no output directory.
  Replaying the independent fixture gave identical scientific result content.
  This is local software verification, not acceptance of the assumptions or
  permission to analyze protected observations.
