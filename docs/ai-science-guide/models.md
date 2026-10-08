# G03 competing-model draft

Status: locally verified with synthetic fixtures. No model provider is called,
and no generated hypothesis is activated.

The client can submit several `hypothesis` suggestions in one existing
collaborator proposal. The G03 fixture uses four named candidates: null,
measurement error, selection/confounding, and the user's favored explanation.
Each suggestion carries an observable, prospective prediction in `next_test`,
at least one falsification condition, uncertainty, a frozen-context reference,
and `review_only` authority. The proposal also names competing explanations,
disconfirming evidence, and limitations. Faraday freezes and validates this
proposal against the exact context hash without changing inquiry state.

If a host explicitly chooses to route a candidate, it must use the existing
`ProposeHypothesis` command. The G03 fixture routes only the user-favored
candidate and copies the null and other two candidates into its competing
model fields. The resulting hypothesis is sealed and `unreviewed`. The
collaborator record itself grants no canonical write or activation authority.

The existing validator rejects an empty competing-explanations list, unknown
context references, and suggestions that claim approval. It does not know
whether a candidate labeled as measurement error is scientifically adequate.
**TODO:** A later version of the collaborator proposal should give each model
an explicit typed role and prediction field; a domain validator should check
role coverage and distinguish the predicted observation from the test plan.
Until then, a host must inspect candidate semantics before canonical routing.

## G03 work receipt (2026-10-08)

- Base commit: `c9a4927`. Changed paths: this note, the G03 status in
  `milestones.json`, and `tests/test_guide_models.py`. No production code or
  authority contract was changed.
- Fixture: `guide-models-synthetic-v1`, using a fabricated inquiry and fixed
  proposal payload. Planned and observed effects: temporary canonical inquiry,
  context, proposal, review record, and explicitly routed unreviewed hypothesis
  under pytest's temporary directory. No network, live model, real data,
  secret, or source-tree output.
- Acceptance command: `python3 -m pytest -q tests/test_guide_models.py` with
  `PATH` selecting Faraday's `.venv`, umask 077, bytecode disabled, plugin
  autoload disabled, and pytest cache disabled. Result: 2 passed.
- Adverse cases: an empty alternatives list and claimed approval both raise
  validation errors and create no proposal output. Ledger verification passes;
  no hypothesis is active. This is local fixture verification, not scientific
  or editorial acceptance.
