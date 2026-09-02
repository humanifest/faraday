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
- Attach evidence only after a hypothesis has been reviewed and activated.
- Retire hypotheses without erasing them, including rejection type, limitations,
  lineage, and resurrection conditions.
- Build deterministic, claim-scoped Markdown syntheses.
- Record every state-changing command in a hash-chained append-only ledger and
  detect later tampering.
- Emit stable JSON for Codex today and other clients later.

Protocol freezing, dataset-role enforcement, execution sandboxes, temporal data
adapters, statistical engines, and experiment selection are the next layers.
Their boundaries are reserved in each inquiry workspace, but this version does
not pretend to provide them yet.

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

## Codex-first workflow

1. The person states a curiosity or suspicion in natural language.
2. Codex creates an inquiry and records ambiguity as explicit questions.
3. The person and Codex clarify scope, constructs, population, outcomes, time,
   and what evidence could change the person's mind.
4. Codex creates a claim map and proposes a diverse competing-model set.
5. The person reviews proposals; only operationalized candidates are activated.
6. Available data and analyses produce claim-scoped evidence records. Tests that
   require the physical world become proposed experiments, not simulated facts.
7. Hypotheses are refined, parked, or retired with reasons and resurrection
   conditions. The next experiment should discriminate among survivors.
8. A deterministic synthesis reports what was and was not established.

See [AGENTS.md](AGENTS.md) for the operating contract and
[docs/architecture.md](docs/architecture.md) for the dependency boundaries. The
provider-neutral JSON contracts live in [schemas](schemas), and the fuller
conversational loop is in [docs/codex-playbook.md](docs/codex-playbook.md).

## Workspace layout

```text
.research/
  workspace.json
  inquiries/<inquiry-id>/
    inquiry.json
    questions.json
    claims.json
    drafts/hypotheses/
    hypotheses/{active,parked,retired}/
    datasets/
    protocols/{draft,frozen}/
    runs/
    evidence/
    reports/
    ledger.jsonl
```

JSON files are canonical application state. `ledger.jsonl` is append-only and
must never be hand-edited. Dataset and protocol directories are reserved for the
next implementation phase.

## Development

```bash
pytest
python -m compileall -q src tests
```

The package has no runtime dependencies. It supports Python 3.11 and newer.

## Design principle

> The machine does not search for evidence that its current story is true. It
> maintains multiple explanations, constructs experiments capable of making
> those explanations disagree, and preserves an auditable record of every
> inferential step.
