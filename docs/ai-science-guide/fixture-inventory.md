# G00 fixture inventory

`guide-independent-v1` is a fabricated four-row, two-group CSV with one row
per unique unit. The immutable source fixture is
`tests/fixtures/guide/independent-two-group.csv`; its analysis specification is
`independent-analysis.json`, and `inquiry-plan.json` retains the original
question, the proposed signed contrast, and unresolved decisions. None of these
files are a canonical dataset or evidence of a real study.

| Step | Existing route | Record or artifact | Ceiling |
| --- | --- | --- | --- |
| Preserve wording and decision | `ResearchService.create_inquiry` | Canonical inquiry and ledger event in a temporary workspace | User wording only |
| Keep a clarification open | `ResearchService.add_question` | Canonical open question and ledger event | Unanswered |
| Inspect model-safe state | `ResearchService.collaborator_context` | Read-only redacted context with empty canonical dataset inventory | No model call or authority |
| Check ledger | `ResearchService.verify_ledger` | Local verification result | Integrity, not scientific truth |
| Run bounded analysis | `research analysis run` via the CLI | Output and input-byte-bound receipt in temporary state | Synthetic computation, never evidence |
| Reject duplicate identity | `research analysis run` via the CLI | Error; no output directory | Validation failure remains a failure |

The baseline gate is `python3 -m pytest -q tests/test_guide_baseline.py` from
`docs/ai-science-guide/milestones.json`. The test creates only disposable
workspace and analysis output under pytest's `tmp_path`; it does not register a
dataset, freeze a protocol, admit evidence, or mutate the source fixture.
Passing this characterization will not complete the later guide contract or
scientific journey.

## G00 preparation note (gate incomplete at that time)

- Base commit: `236390a`. This preparation may be committed, but the required
  pytest gate has not run successfully and G00 remains incomplete.
- Fixture ID: `guide-independent-v1`. CSV SHA-256:
  `0191fb3821e9746f0e7fe4bbee46d39b7786c5d090a8a2edfacf157f1698843d`.
  Analysis spec SHA-256:
  `918da3201e425522b085849c64a3fa59bf061add590fc4d41c0fc6bd26570535`.
  Inquiry plan SHA-256:
  `298b32ed8952619810c55e5d0d7ba54a0e78432aa200f9ca9c1fc393df3e6ea3`.
- Planned effects: read the three source fixtures; write only a temporary
  canonical workspace, temporary analysis output, and temporary adverse CSV.
  Actual manual probe effects stayed within that disposable state; no source
  fixture or production code changed.
- Required command attempted with bytecode and pytest cache disabled:
  `umask 077; PYTHONDONTWRITEBYTECODE=1 python3 -m pytest -q -p no:cacheprovider tests/test_guide_baseline.py`.
  Exit 1: `No module named pytest`. The exact milestone command remains
  unverified.
- A separate local `python3 -c` probe exercised the same service and CLI
  routes with a disposable temporary workspace. The analysis exited 0,
  matched the input SHA-256, and reported scientific evidence ineligible.
  The duplicate-unit case exited 2 with `repeated independent-unit identifier`
  and left no output directory. This is a fixture probe, not the pytest gate.
- Remaining prerequisite: provision the declared `pytest>=8` and
  `jsonschema>=4.23` test extras without changing this goal's install boundary;
  then run the exact G00 acceptance command and record its observed result.

## G00 local verification (2026-10-08)

After the user authorized the two declared test dependencies, `pytest 9.1.1`
and `jsonschema 4.26.0` were installed as binary packages in the ignored,
Legion-owned `.venv`. With `PATH` selecting that interpreter, umask 077,
bytecode disabled, plugin autoload disabled, and pytest cache disabled,
`python3 -m pytest -q tests/test_guide_baseline.py` passed (1 test). The
observed effect was disposable pytest state only. G00 is locally verified;
this does not grant scientific acceptance or live data authority.
