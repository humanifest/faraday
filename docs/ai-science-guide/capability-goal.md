# AI science guide: deferred capability buildout

Status: active local software goal. This plan covers T01–T11 in [TODO.md](TODO.md)
and extends the completed [local workflow](workflow-goal.md). Each milestone
produces a small reviewable diff and a focused adverse check before the next
begins. A missing contract stays typed as unavailable; a fixture cannot make a
live provider, device, reviewer, graph, method, or campaign authoritative.

## Outcome and acceptance

A user can progress from a question through review-only model proposals,
appropriate design and data previews, pinned computation, bounded
interpretation, and a prospective next-test candidate. Faraday records the
original request and binds requirements, decisions, work items, artifacts,
checks, and evidence to exact versions. The final checker must start from a
clean commit, replay local synthetic and adverse fixtures, run the full suite,
audit and verify a disposable workspace, and emit separate machine-readable
statuses for each T01–T11 software slice and each external activation gate.
Unknown, stale, or failed required checks make software readiness false.

The final software state means that local contracts and fixtures are
implemented and verified. Scientific acceptance, authenticated identity,
physical collection, real data rights, live inference, migrations, and
publication each require their own evidence and authority. T07 remains a
protected boundary: no guide worker may approve confirmatory activation or
evidence. T08 may generate a review-only report but cannot publish it.

## Serial milestones

The machine-readable jobs and path limits are in
[capability-milestones.json](capability-milestones.json). Work order:

1. C00 freezes this scope and verifies the existing route and test boundaries.
2. C01 exposes T10 and T11 through the typed capability route without side
   effects or an implied live implementation.
3. C02 adds paired and observational packet previews using the existing
   analysis contracts; duplicate pairs, missingness, and confounding remain
   visible. C03 adds a hash-bound, review-only model-specific next-test
   candidate with competing predictions, falsifiers, and a stated
   discrimination criterion.
4. C04–C06 add provider, acquisition, and method extension contracts using
   fixed synthetic responses and adverse cases. Their live adapters remain
   unconfigured until the exact provider, rights, and method-review gates pass.
5. C07–C10 add construct-validity, reviewer, Metamaps, and concurrency
   contracts. They reuse existing canonical services and owner interfaces;
   absent cross-project interfaces become explicit TODOs, never local
   substitutes for those owners.
6. C11 preserves the T07 approval boundary and adds a review-only T08 report
   fixture. C12 builds the exact-commit aggregate checker and completion
   receipt, including per-capability unresolved activation gates.

Jobs change at most four production files plus their focused test and receipt.
Each receipt records base commit, changed paths, exact requirement, evaluator,
fixture and artifact versions, command, observed effects, result, and open
TODOs. The aggregate checker verifies those bindings, not scientific truth.

## Execution boundary

Use Legion's checkout and existing environment with umask 077. Inspect a test
entry point before first execution or after it changes. Local tests may write
only disposable state. Package installation, live network/model/device calls,
secret access, migrations, permissions, deployment, and remote Git writes are
separate actions. Do not change protected approval rules to satisfy a test.
Escalate only the specific external action after a concrete contract and
negative fixture make it reviewable.

## C00–C01 receipt (2026-10-08)

Base commit: `b14389badf1ed48cb46755d35012f87842853cef`. Changed this plan,
the milestone JSON, `TODO.md`, `guide.py`, and `test_guide_unavailable.py`.
The plan covers T01–T11. The existing CLI choices derive from the guide
capability map, so T10 and T11 now have typed effect-free responses linked to
their TODO sections. T10 is `review_only`, not a validated specific proposal;
T11 is `unsupported`, pending C02. The unknown-name rejection remains.

Validation: `.venv/bin/python -m json.tool
docs/ai-science-guide/capability-milestones.json` and `git diff --check`
exited 0. The focused command `umask 077; PYTHONDONTWRITEBYTECODE=1
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 RESEARCH_ADDON_PATH= .venv/bin/python -m
pytest -o addopts= -q -p no:cacheprovider tests/test_guide_unavailable.py`
reported 13 passed. Observed effects were process output and disposable
pytest state. No live model, network, device, canonical research state,
approval, or remote Git write occurred. Full-suite and exact-commit checks
remain for C12.

## C02 receipt (2026-10-08)

Base commit: `b14389badf1ed48cb46755d35012f87842853cef` (C00–C02 share
one local change set). Changed `guide.py`, CLI specification alignment,
`test_guide_prepare.py`, `test_guide_unavailable.py`, this plan, the milestone
JSON, and `TODO.md`. The preview now accepts a paired design only with the
paired method, inventories repeated pair identities, and blocks duplicate,
incomplete, or missing outcome pairs. An adjusted independent design lists
covariates, their missingness and complete-case count, and keeps causal
identification unverified. The analysis and data specifications must match
on pair column, covariates, and missingness policy before data preview.

The focused local command with the same environment controls as C01, targeting
`tests/test_guide_prepare.py tests/test_guide_unavailable.py`, reported 17
passed. Test writes were disposable synthetic JSON/CSV. No canonical or
external state changed. The full local suite then reported 3399 passed and
2 optional skips with the same environment controls. Exact-commit capability
replay remains for C12.

## C03 receipt (2026-10-08)

Base commit: `a66d0d6b302af003157495db8323c0e2fd5071c4`. The `guide next`
route replays an exact execution receipt and current method, verifies a
retained collaborator proposal, and rejects a frozen context that no longer
matches the current canonical inquiry. It requires four grounded model
predictions and falsifiers, a separate proposed test, and a discrimination
criterion. It emits only review-only guidance; matching predictions emit no
candidate. The candidate is not prospectively frozen, scientifically
validated, or authorized for execution. Changed `guide.py`, `proposal.py`,
`cli.py`, `test_guide_explain.py`, this plan, the milestone JSON, the client
playbook, and `TODO.md`.

Focused check: `umask 077; PYTHONDONTWRITEBYTECODE=1
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 RESEARCH_ADDON_PATH= .venv/bin/python -m
pytest -o addopts= -q -p no:cacheprovider tests/test_guide_explain.py
tests/test_guide_models.py` reported 8 passed. Effects were disposable
synthetic inquiry, packet, analysis, context, proposal, and output files.
No live model, network, external source, canonical production write,
approval, or remote Git operation occurred. The full local suite reported
3401 passed and 2 optional skips with the same environment controls.
Exact-commit capability replay remains for C12.

## C04 receipt (2026-10-08)

Base commit: `5fb153586cb6539209727509d9070868ada76502`. Added
`collaboration/guide_provider.py` and `tests/test_guide_provider.py`; updated
this plan, milestone JSON, and `TODO.md`. A provider-neutral byte port and a
fixed in-process adapter exercise a bounded redacted synthetic context. The
fixture validates the review-only output through the existing proposal
contract and records exact context, prompt, and output hashes, destination,
zero cost, and no fallback. A provider failure, oversized output, invalid
authority, wrong context hash, or unexpected adapter cannot yield a proposal.
The live Cypher adapter, disclosure approval, backend inspection, telemetry,
and network authority remain TODOs; T01 stays `not_configured`.

Focused check with umask 077, bytecode and plugin autoload disabled, empty
external add-on path, and no pytest cache:
`.venv/bin/python -m pytest -o addopts= -q -p no:cacheprovider
tests/test_guide_provider.py` reported 2 passed. Effects were disposable
synthetic context/fixture files only. The full local suite then reported
3403 passed and 2 optional skips. Exact-commit capability replay remains
for C12.

## C05 receipt (2026-10-08)

Base commit: `367ae846fbcb6e26323e6f4ac85c6c88f028ab6f`. Added
`application/guide_acquisition.py` and `tests/test_guide_acquisition.py`;
updated this plan, milestone JSON, and `TODO.md`. The guide view reuses
Faraday's connector source-proposal verifier and instrument inspection-record
verifier. A synthetic connector case binds current source bytes and the
implementation receipt, retains rights and consent as unverified declarations,
and never clears custody. A fabricated instrument case retains proposed
capture timing and raw-byte identity but blocks a failed, unverified
calibration check. Changed source bytes and mismatched calibration hashes are
rejected. No device, external connector, network, or real source was used.

Focused check: `umask 077; PYTHONDONTWRITEBYTECODE=1
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 RESEARCH_ADDON_PATH= .venv/bin/python -m
pytest -o addopts= -q -p no:cacheprovider tests/test_guide_acquisition.py`
reported 2 passed. Effects were disposable synthetic source files and
receipts only. The full local suite then reported 3405 passed and 2 optional
skips. Exact-commit capability replay remains for C12.
