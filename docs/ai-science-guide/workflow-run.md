# W02 pinned exploratory guide run

Save the JSON output of `research --json guide prepare ...` as a packet. The
`research --json guide run` route requires `--packet-file`,
`--expect-packet-sha256`, `--spec-file`, `--expect-spec-sha256`, `--data-file`,
`--expect-input-sha256`, and an empty `--output` directory. Trusted hashes
must be held by the caller independently of the files being checked. The
route verifies that the packet is versioned, review-only, complete for the
local preview, free of declared quality issues, and bound to the exact method,
analysis specification, and CSV bytes. It reuses `execute_analysis` and its
normal result and receipt files. It does not create an inquiry, dataset,
protocol, run, evidence record, or synthesis.

The result is `exploratory_computation_only`. Even exact hashes supplied at
execution time cannot prove that a plan predates outcome inspection. A
confirmatory claim requires the existing frozen-protocol and registered
dataset route, along with the applicable review and quality gates. The saved
packet may still be self-authored; its hash protects byte identity, not the
truth or authority of its statements.

## W02 work receipt (2026-10-08)

- Base commit: `48d6cc3`. Changed the guide application and CLI, the W01
  preparation fixture/document to separate measurement and executable specs,
  `tests/test_guide_run.py`, this document, and the W02 path/status record.
  The path expansion is needed because the old W01 packet carried measurement
  definitions in a file that the executable analysis contract rejects.
- `.venv/bin/python -m pytest -o addopts= -q -p no:cacheprovider
  tests/test_guide_prepare.py tests/test_guide_run.py` passed 4 synthetic
  tests with umask 077, bytecode off, plugin autoload off, and no external
  add-on path. Tests wrote disposable packet and analysis files only.
- The output receipt was independently replayed. A wrong packet hash,
  forged approval claim, changed input bytes, and post-result method switch
  exited without an analysis output directory. No canonical write occurred.
