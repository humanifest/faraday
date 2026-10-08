# W03 result explanation and next experiment boundary

`research --json guide explain` takes the saved guide packet and its trusted
SHA-256, the executable specification, the original CSV, the execution
directory, and an independently held execution-receipt SHA-256. It replays
Faraday's receipt/output validator, rechecks the original specification and
input bytes, and compares the receipt's method implementation digest to the
currently loaded add-on. It then reports the signed effect, interval,
relation of that interval to zero, unit counts, exclusions, assumptions,
and the method's enforced claim ceiling. The result remains exploratory
computation. The interval relation is arithmetic, not a declaration that
the favored hypothesis is true or that the design identifies a causal effect.

The first local guide packet poses four competing-model questions but contains
no reviewed model-specific predictions. In that state `next_experiment` is
`needs_model_specific_predictions_and_review`, with no candidate and no
claim of discriminatory power. A Codex-like client can draft predictions and
a candidate experiment through the existing hash-bound collaborator context
and proposal-validation routes. The host must route any actual hypothesis,
design, or next action through `ResearchService` and its review gates. A
separately validated candidate is still a proposal, not an approved experiment.

## W03 work receipt (2026-10-08)

- Base commit: `4a61272`. Changed the guide application and CLI,
  `tests/test_guide_explain.py`, this document, and the W03 status record.
- `.venv/bin/python -m pytest -o addopts= -q -p no:cacheprovider
  tests/test_guide_explain.py` passed 4 tests with umask 077, bytecode and
  plugin autoload disabled, and no external add-on path. Disposable synthetic
  inputs and analysis outputs were the only writes.
- Positive, negative, and zero-spanning interval cases retained their signed
  estimates and no-discrimination ceiling. Wrong trusted receipt and changed
  input bytes were rejected. No canonical evidence, active hypothesis,
  confirmatory plan, model call, or remote state was created.
