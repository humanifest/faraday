# Set up Faraday

Faraday is a local research notebook with a careful memory. It does not need
an account, a cloud service, or a GPT to run.

## The easy way

You need Python 3.11 or newer.

```bash
git clone https://github.com/humanifest/faraday.git
cd faraday
./bootstrap
./research --workspace .research workspace init
```

That is the whole setup. The first command makes a private `.venv` and checks
that Faraday starts; the second creates your local research workspace. Both
stay on your computer. Faraday has no runtime dependencies, so this works
without an internet connection.

Now ask Faraday to start an inquiry:

```bash
./research inquiry create \
  --id my-first-question \
  --title "My first question" \
  --statement "Does sunlight change how quickly a plant grows?"
```

If a command is unfamiliar, add `--help`:

```bash
./research --help
./research inquiry --help
```

## If you already have Python

The repository-local `./research` launcher works without installation when it
can find Python 3.11 or newer. In that case, this is enough:

```bash
./research --workspace .research workspace init
```

Use `FARADAY_PYTHON=/absolute/path/to/python ./research ...` when you want to
choose a specific interpreter.

## What setup changes

`./bootstrap` creates only `.venv/` and verifies this checkout there. The
workspace command creates `.research/`, which contains the local ledger and
structured research state. These are intentionally separate from the source
code. Do not edit the ledger by hand; use `./research` commands.

## Optional tests

Tests are not needed to use Faraday. Developers can install the test extras
and run them with:

```bash
.venv/bin/python -m pip install --editable '.[test]'
.venv/bin/python -m pytest
```

## Should we include a GPT?

Yes, as an optional helper; no, as a required part of Faraday.

A GPT can help a beginner turn a vague idea into questions, suggest competing
explanations, explain a command, or review a draft for missing assumptions.
It should receive a frozen, read-only context and return suggestions marked
`pending_human_review`. It must not silently write research state, activate a
hypothesis, certify evidence, or replace human review.

This keeps the smallest and safest path working offline while leaving room for
an optional provider adapter later. A model key should never be required by
`./bootstrap` or by the core `research` command.
