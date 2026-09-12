# Codex inquiry playbook

This playbook is the conversational layer for the current product. It is a guide,
not hidden state: durable research state belongs in the workspace.

## 1. Capture curiosity faithfully

Create the inquiry using the person's own level of confidence. Convert a broad
suspicion into questions; do not quietly rewrite it as a finding.

Name the practical decision the inquiry is intended to support, the minimum
evidence required to make that decision, who owns it, and observations that
would change it. These fields may remain visibly unresolved during early
clarification; Codex must not fill them with plausible-sounding inventions.

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

For every claim, distinguish its epistemic layer—documented fact, source claim,
project interpretation, reasonable inference, or unresolved—from its project
disposition. Attach sources to facts and source claims, connect inferences to
their dependencies, and record conflicts without smoothing them into a single
narrative. Confidence is a review annotation, not automatically a calibrated
probability.

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

If the person has explicitly delegated autonomous exploratory review, Codex may
stage an operationalized candidate as `pending_review` with a recorded
high-confidence rationale. This permits exploratory protocols, datasets,
evidence, and next-action selection while keeping human ratification visibly
open. It does not authorize confirmatory or replication protocol freezes,
confirmatory evidence, or language implying human approval.

## 4. Design discriminatory tests

Prefer a test whose possible outcomes change the relative credibility of several
models. Identify available data first. If a valid test requires unavailable
records, new measurement, field intervention, informed consent, or physical
instrumentation, describe it as proposed human work and state the blocker.

Do not invent generic `p < 0.05`, sample-size, or replication thresholds. Derive
them from an explicit estimand, uncertainty/precision target, data structure,
burden, and decision context.

Represent proposed work as candidate next actions. Exclude any action whose
prerequisites are unmet or whose safety/ethics approval is absent. Treat the
utility score as an auditable decision aid, not a substitute for human judgment.

## 5. Freeze before protected execution

Choose a protocol kind that matches the work. Empirical protocols must define
sampling and analysis policies; experiments must additionally define
randomization and blinding (including justified “not applicable” plans). Formal
and computational work must define a reproducible environment. Every frozen
protocol must also name required quality gates, at least one comparator or
negative control, and an explicit sample-size or stopping rule.

Freeze the protocol before inspecting confirmatory or replication observations.
Register each dataset once under a role. Never relabel an artifact digest to move
it from exploration or training into confirmation.

Required quality gates answer whether the execution and measurement are usable:
hashes and provenance match, inputs are admissible, controls were evaluated, and
the frozen classification rule was applied. Put the result that would support or
falsify the hypothesis in `success_conditions` and `failure_conditions`, not in
a required quality gate. Otherwise a valid adverse result becomes an invalid run
and cannot enter evidence.

For blinded or sealed numerical comparisons, publish a complete measurement
definition before execution even when the target value stays hidden. Each target
needs its observable, input, parameter values, evaluation point or time,
convention, aggregation, and tolerance. A sealed value that relies on an omitted
choice tests guesswork about the original implementation rather than
reproducibility of the public method.

Use `measurement_definitions` when those choices need machine enforcement. Once
the list is nonempty, the freeze gate requires exactly one typed definition for
the primary outcome, every secondary outcome, and every registered control. See
`measurement-contract.md`.

For mathematical or computational work, freeze
`mathematical_predicate_contracts` before reporting rank, nullity,
invertibility, positivity, conservation, tangency, or equivalence. See
`mathematical-predicate-contract.md`. The contract keeps results attached to
the exact source, restriction, quotient, pullback, or comparator object on
which they were evaluated.

An exploratory protocol may be frozen against `pending_review` hypotheses.
Confirmatory and replication protocols require every tested hypothesis to be
active after human review.

An executor returns a run record that binds the frozen protocol hash, exact code
and environment hashes, registered input IDs, hashed outputs, and gate results.
Required gate failures make the run invalid. Synthetic inputs remain useful for
testing but cannot become scientific evidence.

## 6. Record evidence narrowly

Evidence records must name the hypothesis, run or exploratory dataset, direction,
scope, uncertainty, control outcomes, exploratory status, conclusions the record
does not support, and one or more validation tags. Confirmatory evidence must
reference an eligible confirmatory or replication run. “Inconclusive” is a real
result, distinct from null evidence or refutation.

Use the lowest applicable validation tag. `internal_consistency` and
`controlled_benchmark` do not imply recovery, prediction, or empirical contact.
The machine checks advanced tags against provenance. Do not use
`independent_replication` unless the run names an eligible earlier run and has a
different executor and code hash. The run must also carry a clean-room
independence declaration, a hash-pinned allowed-input manifest, contamination
disclosures, and a hashed independence-attestation output. Do not use
`empirical_test` for synthetic data, formal calculations, or exploratory
analyses.

## 7. Iterate without erasing mistakes

After evidence, revise the model set. Retire explanations using typed decisions
and resurrection conditions. A retired item remains searchable and can be an
ancestor of a new proposal. Then select the next test for discrimination rather
than confirmation.

Build the synthesis and verify the ledger at useful checkpoints:

```bash
./research --workspace <path> synthesis build
./research --workspace <path> workspace audit --fail-on error
./research --workspace <path> workspace verify
```
