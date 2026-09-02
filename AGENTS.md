# Codex operating contract

This repository is the current interface to Research Machine. Treat the human
conversation as the exploratory front end and the `research` command as the
canonical write path.

## Start of an inquiry

1. Translate “I think …” into an inquiry without strengthening it.
2. Record important ambiguity as questions before proposing a preferred answer.
3. Clarify population, setting, construct, outcome, time window, comparison,
   available data, ethical constraints, and what observation would change the
   user's mind.
4. Separate observation from statistical association, causality, mechanism,
   adaptation, attribution, and intent by creating claim-level nodes.

## Hypotheses

- Generate competing model sets, including measurement error, selection,
  confounding, mundane process, and the user's favored explanation where
  relevant. Do not optimize for novelty or excitement.
- Submit generated candidates as `unreviewed`. Never activate one merely because
  Codex generated it.
- When the user delegates autonomous exploratory review, Codex may move a
  complete proposal to `pending_review` only with an explicit high-confidence
  rationale. Pending hypotheses may receive exploratory evidence and may anchor
  frozen exploratory protocols, but they are not active, human-reviewed, or
  eligible for confirmatory/replication protocol freezes or evidence.
- Before activation, require an observable prediction, falsification condition,
  and a null or competing model. Prefer explicit scope, estimand, confounds,
  controls, and boundary conditions.
- Use `lineage` when a proposal revises, narrows, or replaces another hypothesis.
- Never delete a rejected hypothesis. Retire it with a typed reason, limitations,
  and concrete resurrection conditions. Use `superseded_by` when applicable.

## Evidence and reporting

- Use the CLI/application service for all canonical changes. Do not edit state
  JSON by hand and never edit `ledger.jsonl`.
- Evidence belongs to an exact hypothesis and, when possible, an exact claim.
  Record the run (or exploratory dataset), analysis identity, uncertainty,
  controls, unsupported higher-level conclusions, and at least one validation
  tag. New evidence without a scope, uncertainty statement, claim ceiling, or
  validation tag must fail closed.
- Treat validation tags as claims with prerequisites, not labels of convenience.
  Independent replication requires a named earlier run, a different executor,
  and a different code hash. Empirical tests require non-synthetic observations
  under an observational or experimental confirmatory protocol.
- Never promote support at one claim level to a higher one. Association does not
  imply causal direction; causality does not establish mechanism or intent.
- Preserve exploratory/confirmatory separation. Register artifact hashes once;
  do not relabel them. Freeze protected protocols before their observations are
  registered. Confirmatory evidence must trace to an eligible quality-gated run.
- A `pending_review` label must remain visible in synthesis. Never describe it as
  approval, validation, confirmation, or human review.
- Synthetic data and runs may test plumbing, but must never be presented as
  scientific evidence. Failed or skipped required gates fail closed.
- Do not manufacture physical observations, dataset access, validation results,
  citations, or replications. Propose out-of-reach work as an experiment for a
  human or external system.
- Prefer “supported against these alternatives on this dataset” over “confirmed”
  or “proved.” Build a synthesis after material changes, run `workspace audit`,
  and verify the ledger.

## Engineering boundaries

- Domain and application modules must not import Codex, OpenAI, an LLM SDK, the
  CLI, HTTP frameworks, or storage implementations.
- Codex is a client/orchestrator, not a hidden dependency. Future agents and UIs
  must use the same commands/application services.
- Keep provider-specific generation outside the core. LLM hypothesis generation
  is a proposal source and remains TODO until a port and explicit policy exist.
- Keep reports deterministic from stored state. Generative prose may supplement
  them later but must not replace or silently mutate canonical evidence.
- Keep domain executors outside the core. They return hashed run records; the
  application service validates and records them.
- Add tests for every new validation gate and every provenance-sensitive state
  transition. Run `pytest` and ledger verification before declaring completion.
