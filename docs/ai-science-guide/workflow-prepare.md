# W01 guide prepare packet

`research --json guide prepare --brief-file BRIEF.json` returns a version-1,
read-only packet. Optional `--design-brief-file DESIGN.json`,
`--analysis-spec-file SPEC.json`, `--data-file DATA.csv`, and
`--expect-data-sha256 HASH` add the existing scaffold, registered method,
and CSV inventory paths. `--data-file` requires a specification. The packet
retains the original question, literal supplied values, unresolved fields,
source-byte hashes, blocking conflicts, four competing-model questions,
method limits, and concrete next routes. It never reads a scientific answer
into an empty field or writes a workspace.

The four model prompts request a null, measurement-error,
selection/confounding, and user explanation with a prediction and falsifier.
They assert no model as true. `ready_for_review` means the supplied preview
fields align and the CSV quality check has no issues. It is not a frozen
protocol, custody finding, evidence, scientific approval, or permission to
run confirmatory analysis. A client must keep the trusted hashes outside the
guide packet if it later requests exploratory execution.

## W01 work receipt (2026-10-08)

- Base commit: `ee468ef`. Changed
  `src/research_machine/application/guide.py`,
  `src/research_machine/interfaces/cli.py`,
  `tests/test_guide_prepare.py`, this document, and the W01 milestone status.
- The existing virtual environment and bundled method registry were reused.
  No package, provider, connector, network, or canonical state was touched.
- With umask 077, bytecode and external pytest plugin loading disabled,
  and an empty external add-on path, `.venv/bin/python -m pytest -o addopts=
  -q -p no:cacheprovider tests/test_guide_prepare.py` passed 2 tests.
  The tests wrote only disposable synthetic JSON and CSV inputs.
- Adverse cases covered absent answers, missing specification, wrong input
  hash, unknown method, conflicting outcome scale, and duplicate independent
  units. No analysis or scientific transition occurred.
