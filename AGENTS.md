# Codex operating contract

This repository is the current interface to Research Machine. Treat the human
conversation as the exploratory front end and the `research` command as the
canonical write path.

## Start of an inquiry

1. Translate “I think …” into an inquiry without strengthening it.
2. Identify the practical decision, minimum evidence, decision owner, and
   observations that would change the decision. If these are not yet known,
   leave them visibly unresolved rather than inventing them.
3. Record important ambiguity as questions before proposing a preferred answer.
4. Clarify population, setting, construct, outcome, time window, comparison,
   available data, ethical constraints, and what observation would change the
   user's mind.
5. Separate observation from statistical association, causality, mechanism,
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
- Keep a claim's epistemic layer separate from its disposition. A source's claim
  is not a documented fact, and an accepted project interpretation does not
  become one through repetition. Record conflicts rather than reconciling them
  rhetorically; accepted conflicting claims must fail the rigor audit.
- Preserve exploratory/confirmatory separation. Register artifact hashes once;
  do not relabel them. Freeze protected protocols before their observations are
  registered. Confirmatory evidence must trace to an eligible quality-gated run.
- A run may not predate its canonical protocol registration unless it is
  explicitly accessioned from an external pre-execution freeze. Preserve and
  locally verify the external protocol, analysis source, and zero-execution
  freeze manifest; record that their chronology remains an attestation rather
  than a cryptographically authenticated timestamp.
- Keep execution quality separate from scientific direction. Required quality
  gates cover integrity, provenance, measurement availability, controls being
  evaluated, and faithful application of the frozen decision rule. Desired
  values or hypothesis-supporting outcomes belong in success and falsification
  conditions; a valid null, adverse, or partial result must remain eligible for
  evidence with the appropriate direction.
- For a sealed numerical comparison, require a public measurement definition
  for every hidden target: observable, input, parameters, evaluation point or
  time, convention, aggregation, and tolerance. The sealed value must not depend
  on an undisclosed implementation choice. Use the typed
  `measurement_definitions` contract for new protocols so the freeze gate checks
  exact primary, secondary, and control coverage.
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

- This repository develops the Research Machine, not any substantive research
  project. Do not place live hypotheses, study protocols, collected data,
  experiment workspaces, or domain conclusions here. Keep those in a separate
  experiment repository and connect them with `--addon-path` or
  `RESEARCH_ADDON_PATH`.
- Machine tests may contain synthetic fixtures that test software invariants.
  They must be labeled as fixtures and must not become a parallel research
  record. Domain acceptance campaigns belong with their experiment/add-on.

- Domain and application modules must not import Codex, OpenAI, an LLM SDK, the
  CLI, HTTP frameworks, or storage implementations.
- Codex is a client/orchestrator, not a hidden dependency. Future agents and UIs
  must use the same commands/application services.
- Keep provider-specific generation outside the core. LLM hypothesis generation
  is a proposal source and remains TODO until a port and explicit policy exist.
- Keep reports deterministic from stored state. Generative prose may supplement
  them later but must not replace or silently mutate canonical evidence.
- Keep discipline-specific semantics in validated add-ons. Research Machine must
  remain one self-contained tool: it ships a general-science execution toolkit,
  discovers installed or explicitly supplied local add-ons through
  `research_machine.addons`, and receives all
  add-on outputs through the same dataset, protocol, run, evidence, and ledger
  contracts.
- An add-on may provide readers, instrument adapters, analysis methods,
  simulations, quality gates, and protocol templates. It must not create a
  competing canonical store, weaken core review rules, promote claims, or treat
  successful execution as evidence eligibility.
- Put universally applicable concepts and validation rules in the core. Put
  physics-, psychology-, biology-, or instrument-specific assumptions in an
  add-on. When two disciplines need copied logic, generalize it into the core
  and retain acceptance tests in both disciplines.
- Every executable add-on method must expose a stable identifier, required
  specification fields, versioned manifest, hash-locatable implementation, claim
  ceiling, deterministic behavior when randomness is used, and adversarial
  fail-closed tests. Update `docs/addons.md` when the extension contract changes.
- Add tests for every new validation gate and every provenance-sensitive state
  transition. Run `pytest` and ledger verification before declaring completion.

## Publishing safety

- Default every newly created remote repository, release artifact, dataset, and
  hosted project to **private** visibility.
- Public visibility requires an explicit instruction from the project owner for
  that specific publication. Do not infer public authorization from an existing
  open-source repository, a prior publication, or a request merely to “push.”
- Verify the destination and visibility before the first upload.
