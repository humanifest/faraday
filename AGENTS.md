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
  Record dataset, analysis identity, uncertainty, controls, and unsupported
  higher-level conclusions.
- Never promote support at one claim level to a higher one. Association does not
  imply causal direction; causality does not establish mechanism or intent.
- Preserve exploratory/confirmatory separation. Until protocol registration and
  dataset-role enforcement are implemented, label evidence conservatively and
  do not claim that the machine enforced preregistration.
- Do not manufacture physical observations, dataset access, validation results,
  citations, or replications. Propose out-of-reach work as an experiment for a
  human or external system.
- Prefer “supported against these alternatives on this dataset” over “confirmed”
  or “proved.” Build a synthesis after material changes and verify the ledger.

## Engineering boundaries

- Domain and application modules must not import Codex, OpenAI, an LLM SDK, the
  CLI, HTTP frameworks, or storage implementations.
- Codex is a client/orchestrator, not a hidden dependency. Future agents and UIs
  must use the same commands/application services.
- Keep provider-specific generation outside the core. LLM hypothesis generation
  is a proposal source and remains TODO until a port and explicit policy exist.
- Keep reports deterministic from stored state. Generative prose may supplement
  them later but must not replace or silently mutate canonical evidence.
- Add tests for every new validation gate and every provenance-sensitive state
  transition. Run `pytest` and ledger verification before declaring completion.
