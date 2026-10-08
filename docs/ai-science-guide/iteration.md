# G07 bounded interpretation and next-action gate

Status: locally verified with synthetic exploratory records. No recommendation
or scientific conclusion was accepted by the fixture.

`ResearchService.build_synthesis` remains the deterministic report path. The
G07 fixture records a weakening observation and an inconclusive observation
against one provisionally staged synthetic hypothesis, then builds the report
twice. The report content is stable and retains both observations, the open
measurement question, scope, uncertainty, and unsupported higher-level
conclusions. The pending-review section now also displays that hypothesis's
prediction, null model, competing model, and falsification condition. This
closes a visibility gap without changing its workflow state or treating
declared controls as independently verified.

A version-1 non-advancing information candidate proposes a future measurement
check through the existing next-action contract. Its prerequisite and safety
states are false, so `recommend_next_action` rejects it and leaves no
recommendation. The service also requires an audit-prerequisite contract.
The failure is a useful answer: there is no currently eligible next action.
**TODO:** A later milestone should create a reviewed, source-bound positive
candidate fixture with exact prerequisite and safety evidence and test the
full recommendation score and replay path. Real next experiments require
their existing approval and stop controls.

## G07 work receipt (2026-10-08)

- Base commit: `0b3a1fd`. Changed paths: this note,
  `src/research_machine/reporting/synthesis.py`, `tests/test_guide_iteration.py`,
  and the G07 status in `milestones.json`.
- Fixture: `guide-iteration-v1`, a fabricated inquiry, pending-review
  hypothesis, synthetic exploratory dataset, two labeled observations, and a
  non-advancing information candidate. Planned and observed writes were only
  temporary canonical fixture records, reports, and ledger events under
  pytest's temporary directory. No real data, provider, network, or effect.
- Acceptance command: `python3 -m pytest -q tests/test_guide_iteration.py`
  with `PATH` selecting Faraday's `.venv`, umask 077, bytecode disabled,
  plugin autoload disabled, pytest cache disabled, and no external add-on path.
  Result: 1 passed.
- An initial test exposed the missing alternatives in pending-review synthesis;
  the focused report change repaired that gap. The next-action service
  rejected missing audit context, then rejected the candidate's unsatisfied
  prerequisite and safety gates. No recommendation was created. This is local
  fixture verification, not scientific acceptance or a human approval.
