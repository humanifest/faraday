# G04 prospective design preview

Status: locally verified with a synthetic, review-only two-group design. This
preview does not register, freeze, or execute a protocol.

The guide reuses `research --json design scaffold --brief-file ...` and
`research --json addon list`. The first route retains the independent unit and
column, outcome scale and post-exposure timing, signed contrast, estimand,
stopping rule, missingness gate, exploratory multiplicity policy, interval
level, and a deterministic precision target. The second route displays
registered method IDs, required specification fields, and claim ceilings.
The synthetic draft remains `review_required` with unresolved scientific
validity commitments. Listing a method is not selecting or pinning it; G06
must bind an exact method and executable specification before outcome use.

The existing scaffold returns `blocked` for an incompatible outcome scale,
identity/outcome column collision, analysis-family/design conflict, causal
outcome measured before exposure, repeated contrast group, missing causal
estimand, and precision-plan information or interval mismatch. These are
structural safeguards. They do not prove assignment, measurement validity,
missingness assumptions, ethics, or causal identification. The result must
retain review-required placeholders rather than silently fill them.

## G04 work receipt (2026-10-08)

- Base commit: `c7f8f6f`. Changed paths: this note, the G04 status in
  `milestones.json`, and `tests/test_guide_design.py`. No production code or
  existing validator was changed.
- Fixture: inline synthetic independent-group brief with a prospective
  precision target. Planned and observed effects: only a JSON brief and pytest
  state in a temporary directory; the public CLI made no canonical workspace.
  No raw outcome, model, network call, real dataset, or source-tree output.
- Acceptance command: `python3 -m pytest -q tests/test_guide_design.py` with
  `PATH` selecting Faraday's `.venv`, umask 077, bytecode disabled, plugin
  autoload disabled, pytest cache disabled, and no external add-on path.
  Result: 2 passed.
- The registered `independent_mean_difference_ci` catalog entry was displayed
  and its required fields and causal claim ceiling were checked. This is
  method discovery, not an execution commitment or scientific acceptance.
