# Codex inquiry playbook

This playbook is the conversational layer for the current product. It is a guide,
not hidden state: durable research state belongs in the workspace.

## 1. Capture curiosity faithfully

Create the inquiry using the person's own level of confidence. Convert a broad
suspicion into questions; do not quietly rewrite it as a finding.

Useful first clarifications include:

- What exactly is being observed or alleged?
- Who or what is the population, comparator, setting, and time period?
- What decision or outcome matters, and how is it measured?
- Is the concern disparity, measurement quality, causality, mechanism, or intent?
- What data exist, who controls them, and what cannot be observed?
- What result would weaken the suspicion? What would merely fail to resolve it?
- Which experiments are ethically or practically unavailable?

Record material questions and answers with `question add` and `question answer`.

## 2. Build a claim map

Create small claims at the lowest defensible level. Give higher-level claims
explicit parent dependencies. Start with measurement validity before attempting
association, causal direction, robustness, mechanism, adaptation, or intent.

## 3. Generate a competing-model set

Seek models that make different predictions. Include, where relevant:

- data corruption or measurement invalidity;
- sampling, selection, missingness, or label construction;
- preprocessing or implementation artifacts;
- confounding or reverse causation;
- heterogeneous or context-specific effects;
- a mundane operational process;
- the user's proposed explanation;
- a null/equivalence model.

Submit each candidate as a JSON proposal. Keep it unreviewed until the person can
see what would support and falsify it. LLM generation is currently a manual Codex
activity; an automated generator remains TODO and must use this same proposal
contract.

## 4. Design discriminatory tests

Prefer a test whose possible outcomes change the relative credibility of several
models. Identify available data first. If a valid test requires unavailable
records, new measurement, field intervention, informed consent, or physical
instrumentation, describe it as proposed human work and state the blocker.

Do not invent generic `p < 0.05`, sample-size, or replication thresholds. Derive
them from an explicit estimand, uncertainty/precision target, data structure,
burden, and decision context.

## 5. Record evidence narrowly

Evidence records must name the hypothesis, dataset, analysis, direction,
uncertainty, control outcomes, exploratory status, and conclusions the record
does not support. “Inconclusive” is a real result, distinct from null evidence or
refutation.

## 6. Iterate without erasing mistakes

After evidence, revise the model set. Retire explanations using typed decisions
and resurrection conditions. A retired item remains searchable and can be an
ancestor of a new proposal. Then select the next test for discrimination rather
than confirmation.

Build the synthesis and verify the ledger at useful checkpoints:

```bash
./research --workspace <path> synthesis build
./research --workspace <path> workspace verify
```
