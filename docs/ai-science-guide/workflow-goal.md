# AI science guide: usable local workflow

Status: active local implementation goal, 2026-10-08. This follows the
[G00–G09 synthetic software gate](goal.md). It does not activate a live model,
real-data evidence, or scientific approval.

## Outcome

A Codex-like client can ask Faraday for one versioned guide packet from a
literal question, optional design brief, declared analysis specification, and
small CSV. The packet preserves the original wording, names unanswered
decisions and competing-model prompts, previews the proposed design and data,
identifies the supported method and its ceiling, and gives concrete next
commands. The client can then invoke one explicitly pinned exploratory
analysis, inspect a deterministic result explanation, and propose a next
discriminating experiment. Canonical inquiry, dataset, protocol, evidence,
review, and acceptance changes stay with existing `ResearchService` commands.

The final automated state is `local_workflow_fixture_ready`: one command runs a
fresh synthetic client journey, adverse cases, the complete local suite,
workspace audit, ledger verification, and exact artifact/commit checks. It
means the local software path works for its supported fixtures. No unattended
check certifies real data, causal identification, reviewer authority, ethics,
physical experiments, or publication.

## Serial jobs

| Job | Small deliverable | Acceptance check |
| --- | --- | --- |
| W00 | Freeze this plan and characterize current CLI seams. | JSON plan parses; prior G09 gate remains unchanged. |
| W01 | One read-only `guide prepare` packet combining literal intake, optional design preview, CSV inventory, method metadata, competing-model prompts, and next steps. | No workspace write; missing inputs stay unresolved; bad method/scale/bytes fail closed. |
| W02 | Explicit, exact-hash exploratory analysis handoff through the existing add-on route. | A changed specification or input fails before computation; no evidence or confirmatory claim appears. |
| W03 | Deterministic result and next-experiment guidance bound to the execution receipt and open decisions. | Negative, inconclusive, missingness, and alternatives survive; no AI approval or invented discriminating power. |
| W04 | A concise client guide and one-command synthetic checker extending G09. | Full suite, three supported method fixtures, adverse matrix, audit, ledger, and exact-commit receipt pass. |

Each job changes at most four production files, uses existing services and
add-on contracts, and records its base commit, changed files, exact checks,
observed effects, limitations, and TODOs. All tests use disposable synthetic
state with umask 077. A changed test entry point is inspected before execution.
No package installation, network/model call, secret access, migration, or
remote write is part of these jobs. The previously installed test extras in
Faraday's ignored Legion-owned `.venv` are reused.

## Trust boundaries and TODOs

- A guide packet is a read-only projection, not a second store, protocol
  freeze, prospectively authenticated plan, or substitute for the hash-bound
  collaborator proposal and review routes.
- The first analysis path is exploratory. A client-supplied hash alone cannot
  prove a plan predates outcome inspection. Confirmatory execution still
  requires the existing frozen-protocol and dataset gates.
- Generic model prompts are questions, not generated hypotheses or factual
  assertions. The client must present alternatives and falsifiers before any
  explicit `ResearchService` proposal route.
- W03 may emit a candidate next experiment only as review-only guidance. If
  the available data do not discriminate models, it says so rather than
  choosing one.
- Live inference, connectors, instruments, domain-specific validity,
  authenticated review, Metamaps, arbitrary methods, and concurrent writers
  remain in [TODO.md](TODO.md). A usable local client workflow does not clear
  those activation gates.

## W04 implementation receipt (2026-10-08)

Base commit: `3bc32e4`. Changed the one-command workflow checker, fixed
`workflow-inputs.json` fixture, `tests/test_guide_workflow.py`, the
AI client playbook, this guide, `workflow-milestones.json`, and `README.md`.
The W04 path list was expanded
to include the fixed fixture. Its SHA-256 is pinned in the checker. The
fixture exercises the independent two-group route; the prior G00–G09 suite
continues to exercise paired and observational methods through their existing
analysis contracts. The cohesive packet does not yet preview paired designs.

`tests/test_guide_workflow.py` passed 2 tests with umask 077, bytecode and
pytest plugin autoload disabled, no external add-on path, and disposable
synthetic state. The new exact-commit checker is pending a clean candidate
commit. It will invoke the prior G09 gate once for the full suite, audit, and
ledger, then report `local_workflow_fixture_ready` only if its own public
prepare/run/explain replay and adverse checks pass.

## W00 work receipt (2026-10-08)

Base commit: `ba3d394`. Changed only this document and
`workflow-milestones.json`. The plan was parsed with `.venv/bin/python -m
json.tool docs/ai-science-guide/workflow-milestones.json`; `git diff --check`
passed. Existing route inspection found separate `guide intake`, `guide data`,
`design scaffold`, `addon list`, `analysis run`, `synthesis build`, `workspace
audit`, and `workspace verify` paths, but no single user-facing guide packet.
The checks read local source and wrote no workspace, model, network, or remote
state. W01 is the first implementation job.
