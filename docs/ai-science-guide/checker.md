# G09 synthetic checker and work receipt

The one-command gate is `./.venv/bin/python scripts/check_ai_science_guide_goal.py --json`
from a clean Faraday checkout with the declared `test` extras already installed.
It refuses a missing dependency, missing guide test, dirty checkout, failed
journey, failed adverse test, or failed full suite. A JSON response with
`software_fixture_ready: true` is a software fixture result for its exact
commit, not scientific acceptance.

The checker creates a temporary synthetic workspace outside the repository.
It uses the public CLI to clarify the original question; create an inquiry;
retain an open measurement question; propose and stage an exploratory,
unreviewed hypothesis; inventory exact CSV bytes; run a pinned independent
two-group analysis twice; build synthesis twice; audit with `--fail-on error`;
and verify the ledger. It inspects the receipt's input, specification,
implementation and output hashes, the report bytes, the method and claim
ceiling, the audit capabilities, and the final hypothesis state. Staging
remains `pending_review`; no evidence is admitted or activated.

The focused adverse matrix names the test for each required case in the
checker. The three supported methods share the analysis contract but retain
distinct assumptions and claim ceilings. The complete local suite then runs
with external pytest plugins disabled. Its optional notebook integration
tests may skip; the required guide matrix may not skip. Only disposable test
directories are written. The checker does not install dependencies, contact a
provider, use live data, or change a remote repository.

## G09 implementation receipt (2026-10-08)

- Base commit: `898a173`. Changed paths: `scripts/check_ai_science_guide_goal.py`,
  `tests/test_guide_end_to_end.py`, `tests/test_research_launcher.py`, this
  document, `milestones.json`, and `README.md`.
- The G09 path allowance was expanded to `tests/test_research_launcher.py` after
  the complete suite found one environment-dependent test. That test assumed
  the repository had no usable `.venv`. It now copies the launcher to a
  disposable root without a virtual environment, preserving the intended
  no-interpreter failure case after the user-authorized installation.
- Exact precommit checks: `.venv/bin/python -m pytest -o addopts= -q -p
  no:cacheprovider tests/test_research_launcher.py
  tests/test_guide_end_to_end.py` passed (9 tests); the same command over
  `tests` passed (3383 tests, 2 optional integration skips) after the launcher
  fixture repair. Both used umask 077, no bytecode, no external add-on path,
  and disabled pytest plugin autoload. Observed writes stayed in disposable
  pytest workspaces. The exact-commit checker remains the final G09 gate.
- Remaining limits: no real model, source or instrument ingestion, authenticated
  reviewer, real Metamaps compilation, domain-specific validity, general
  method support, or concurrent writers. See [TODO.md](TODO.md). Neither a
  passing worker test nor this receipt grants scientific/editorial acceptance.
