# Research Machine

Research Machine is a headless, provenance-first engine for turning curiosity
into testable inquiries. For now, a person collaborates with Codex and Codex
operates the machine through a stable command interface. A later UI, HTTP API,
or model provider can call the same application services without changing the
domain model.

The machine is deliberately not a claim-confirmation engine. It keeps competing
explanations alive, separates levels of inference, records scoped evidence, and
preserves rejected hypotheses with the conditions under which they should be
reconsidered.

## What works now

- Create and select inquiries from an initial statement such as “I think …”.
- Record and answer clarifying questions.
- Build a claim hierarchy from measurement validity through attribution/intent.
- Propose structured hypotheses as unreviewed candidates.
- Prevent incomplete hypotheses from entering the active model set.
- Support an auditable `pending_review` lane for delegated autonomous
  exploration without representing agent confidence as human approval.
- Register immutable, content-hashed datasets with roles that prevent
  exploratory/confirmatory leakage.
- Draft, amend, and hash-freeze observational, experimental, computational,
  formal, literature, and synthesis protocols.
- Record code-, environment-, input-, output-, and quality-gate-bound runs.
- Prevent failed or synthetic runs from becoming confirmatory evidence.
- Rank feasible, safety-approved next actions with an explicit utility function.
- Attach evidence only after a hypothesis has been reviewed and activated;
  confirmatory evidence must trace to an eligible recorded run.
- Require every new evidence record to state its scope, uncertainty, explicit
  claim ceiling, and machine-validated capability tags.
- Reject unsupported replication, known-result reproduction, novel-prediction,
  and empirical-test labels rather than accepting them as self-attestations.
- Publish a deterministic epistemic audit and conservative conclusion ceiling in
  every synthesis.
- Retire hypotheses without erasing them, including rejection type, limitations,
  lineage, and resurrection conditions.
- Build deterministic, claim-scoped Markdown syntheses.
- Record every state-changing command in a hash-chained append-only ledger and
  detect later tampering.
- Statically compare a notebook's literal dependency mapping, a strict JSON
  manifest, and actual file bytes before a protected kernel is launched.
- Probe the selected interpreter, Jupyter kernel, and working directory with one
  fixed generated marker cell before protocol freeze, without accepting or
  loading an analysis notebook.
- Emit stable JSON for Codex today and other clients later.

The core deliberately does not implement a statistical package, proof checker,
sensor pipeline, literature retriever, or execution sandbox. Those are adapters
and executors. The core records their inputs, commitments, gates, and outputs
under one provenance model.

An optional domain-neutral notebook executor is included for protected local
calculations. Unlike `nbconvert`'s default failure path, it atomically writes the
partially executed notebook and an execution receipt when a later cell raises,
then exits nonzero. A failure before runtime or kernel launch writes a
`pre_execution_failure` receipt with `kernel_started: false` and no executed
notebook. It refuses to overwrite prior output or receipts and can enforce the
frozen source hash:

```bash
pip install -e '.[notebook]'
research-notebook frozen-source.ipynb executed.ipynb \
  --result-json execution-receipt.json \
  --expect-source-sha256 <frozen-sha256> \
  --dependency-manifest notebook-dependencies.json \
  --expect-dependency-manifest-sha256 <manifest-sha256> \
  --working-directory <project-root>
```

The same dependency check should run before protocol freeze. It parses one
literal `EXPECTED_HASHES` assignment with Python's AST but never executes a
notebook cell, then compares that mapping with the manifest and the actual
files:

```bash
research-notebook-preflight frozen-source.ipynb \
  --manifest notebook-dependencies.json \
  --workspace-root <project-root> \
  --expect-source-sha256 <frozen-sha256> \
  --expect-manifest-sha256 <manifest-sha256> \
  --result-json preflight-report.json
```

The manifest schema, fail-closed rules, and scope limits are documented in
[docs/notebook-dependency-preflight.md](docs/notebook-dependency-preflight.md).

Static integrity does not prove that the interpreter has the notebook extras or
that the process boundary permits a kernel. Run the separate runtime preflight
before freezing a scientific protocol:

```bash
research-notebook-runtime-preflight \
  --result-json runtime-preflight.json \
  --working-directory <project-root> \
  --kernel-name python3 \
  --timeout 30
```

This command accepts no source notebook and no arbitrary code. It starts the
requested kernel, runs one built-in marker cell, verifies the kernel working
directory, shuts the kernel down, and writes a non-overwriting report. Its
contract and limitations are documented in
[docs/notebook-runtime-preflight.md](docs/notebook-runtime-preflight.md).

The receipt is an executor artifact, not canonical evidence. A client still
records the resulting hashes and quality gates through `research run record`.

## Quick start

No installation or network access is required during development:

```bash
cd /Users/admin/dev/SEEDZ/research-machine
./research --workspace .research workspace init
./research --workspace .research inquiry create \
  --id ai-hiring-bias \
  --title "AI hiring bias" \
  --statement "I suspect persistent group disparities in AI hiring decisions."
./research --workspace .research question add \
  --text "Which hiring stage, population, outcome, and period are in scope?"
./research --workspace .research --json inquiry show
```

Global flags (`--workspace`, `--actor`, and `--json`) precede the command group.
Use `./research --help` and `./research <group> --help` for the complete command
surface.

For a structured hypothesis:

```bash
./research --workspace .research --json hypothesis propose \
  --proposal-file examples/hypothesis-proposal.json
./research --workspace .research --json hypothesis list --state unreviewed
```

Activation is a distinct review gate:

```bash
./research --workspace .research hypothesis activate <hypothesis-id>
```

An activatable hypothesis must define an observable prediction, at least one
falsification condition, and either a null model or competing model. Generated
proposals are never activated automatically.

When a person delegates provisional exploratory review, a complete hypothesis
may be staged without activation:

```bash
./research --workspace .research hypothesis stage <hypothesis-id> \
  --confidence high \
  --rationale "Complete competing hypothesis; exploratory work is reversible."
```

`pending_review` hypotheses may anchor frozen **exploratory** protocols and
receive exploratory evidence. Confirmatory or replication protocol freezes and
confirmatory evidence still require activation after human review.

The general execution loop uses JSON contracts:

```bash
./research --workspace .research protocol create --spec-file examples/formal-protocol.json
./research --workspace .research protocol freeze <protocol-id>
./research --workspace .research run record --record-file examples/run-record.json
./research --workspace .research evidence record \
  --hypothesis <hypothesis-id> --direction supports \
  --summary "The registered check passed." --run <run-id> \
  --scope "The registered bounded system only." \
  --uncertainty "Limited to the pinned implementation." \
  --control-passed "The registered negative control failed as expected." \
  --higher-conclusion-unsupported "The model is empirically correct." \
  --validation-tag internal_consistency \
  --validation-tag controlled_benchmark --confirmatory
./research --workspace .research next-action recommend \
  --spec-file examples/next-actions.json
./research --workspace .research workspace audit --fail-on error
```

Replace the placeholder IDs and hashes in the examples with values from the
active inquiry and the actual code, environment, and artifacts.

## Codex-first workflow

1. The person states a curiosity or suspicion in natural language.
2. Codex creates an inquiry and records ambiguity as explicit questions.
3. The person and Codex clarify scope, constructs, population, outcomes, time,
   and what evidence could change the person's mind.
4. Codex creates a claim map and proposes a diverse competing-model set.
5. The person reviews proposals before activation. If autonomous exploratory
   review was delegated, Codex may stage complete candidates as `pending_review`
   under the restrictions above.
6. Freeze a protocol before protected data are inspected, then record the actual
   run with code/environment hashes, input roles, output hashes, and quality gates.
   Tests that require the physical world remain proposed work until an external
   executor returns real artifacts.
7. Hypotheses are refined, parked, or retired with reasons and resurrection
   conditions. The next experiment should discriminate among survivors.
8. A deterministic synthesis reports what was and was not established, including
   the highest defensible conclusion ceiling and missing maturity capabilities.

See [AGENTS.md](AGENTS.md) for the operating contract and
[docs/architecture.md](docs/architecture.md) for the dependency boundaries. The
provider-neutral JSON contracts live in [schemas](schemas), and the fuller
conversational loop is in [docs/codex-playbook.md](docs/codex-playbook.md).

The first end-to-end known-result calibration is the synthetic
[Newtonian pendulum campaign](campaigns/newtonian_pendulum/README.md). It tests
competing laws, an independent analysis path, registered exclusions, and
fail-closed behavior on planted defects while remaining explicitly ineligible
as scientific evidence.

## Workspace layout

```text
.research/
  workspace.json
  inquiries/<inquiry-id>/
    inquiry.json
    questions.json
    claims.json
    drafts/hypotheses/
    hypotheses/{pending_review,active,parked,retired}/
    datasets/
    protocols/{draft,frozen}/
    runs/
    recommendations/
    evidence/
    reports/
    ledger.jsonl
```

JSON files are canonical application state. `ledger.jsonl` is append-only and
must never be hand-edited. Registered datasets, protocols, runs, evidence, and
recommendations are immutable records; amendments create new protocol versions.

## Development

```bash
pytest
python -m compileall -q src tests
```

The package has no runtime dependencies. It supports Python 3.11 and newer.

## Epistemic validation tags

Evidence is classified by what it actually tests: `source_assessment`,
`calibration`, `internal_consistency`, `controlled_benchmark`,
`independent_replication`, `known_result_reproduction`, `novel_prediction`, or
`empirical_test`. Higher tags have enforceable prerequisites. In particular,
independent replication must name an eligible earlier run through
`metadata.replicates_run_id`, use a different executor identity, and use a
different analysis-code hash. It must also declare a clean-room design with
executor and implementation independence, an explicit prior-code-access status,
a hashed allowed-input manifest, contamination disclosures, and a hashed output
artifact carrying `artifact_role=independence_attestation`. A different actor
string plus a cosmetic code edit is therefore insufficient. Known-result
reproduction requires a passed `known-result-reproduction` quality gate. Novel
predictions and empirical tests require active hypotheses and protected
non-exploratory runs; empirical tests also require non-synthetic observational
or experimental data.

`workspace audit` reports errors, warnings, the capability vector, and a
conservative conclusion ceiling. Use `--fail-on error` in CI. Warnings remain
visible for scientifically missing capabilities—such as absent independent
replication—without making unfinished research impossible to commit.
`structurally_valid=true` means only that no internal audit contradiction was
found; it is not a scientific-success flag.

## Design principle

> The machine does not search for evidence that its current story is true. It
> maintains multiple explanations, constructs experiments capable of making
> those explanations disagree, and preserves an auditable record of every
> inferential step.
