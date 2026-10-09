# AI client playbook for the local science guide

This playbook is for a client such as Codex working with a person on a small
local CSV inquiry. It uses Faraday's public commands; Faraday does not call a
model. Keep temporary question, packet, and analysis files outside the source
repository. Use only data the person is authorized to provide, and do not send
raw CSV bytes to a model unless that disclosure is separately authorized.

1. Preserve the person's exact question in `brief.json` as
   `original_statement`. Ask for the decision, population, independent unit,
   outcome, comparison, time window, evidence threshold, owner, change
   criteria, available data, and ethical constraints. Leave unknown fields
   absent. Do not infer them from a favorable result.
2. Draft a `design.json` using `research --json design scaffold` and a separate
   executable `analysis.json`. Put typed measurement definitions in
   `data-spec.json`; make its method, design, columns, and ordered groups agree
   with the executable specification. Use `research --json addon list` to
   inspect method assumptions and claim ceilings. Do this before outcome
   inspection when the person intends a prospective analysis.
3. Run `research --json guide prepare --brief-file brief.json
   --design-brief-file design.json --analysis-spec-file analysis.json
   --data-spec-file data-spec.json --data-file observations.csv
   --expect-data-sha256 HASH` and save its JSON output as `packet.json`. Show
   every unresolved field and blocking issue. A `ready_for_review` packet is
   not a protocol freeze or data-custody approval.
4. Develop a null, measurement-error, selection/confounding, and user-favored
   explanation. State a prediction and an observation that would weaken each.
   For an AI-authored proposal against a canonical inquiry, first export a
   hash-bound `collaborator context`, then use `collaborator validate-proposal`.
   Keep the proposal `review_only`; route any actual question, hypothesis, or
   design change through the existing service commands and review steps.
5. Only for an exploratory computation, keep trusted SHA-256 digests of the
   packet, executable specification, and CSV outside the files being checked.
   Run `research --json guide run` with its required packet, specification,
   data, expected-hash, and output arguments. A newly supplied hash cannot
   establish that the plan preceded outcome inspection. Confirmatory work
   uses the separate frozen-protocol and registered-dataset route.
6. Run `research --json guide explain` with the trusted packet and execution
   receipt hashes, source specification, source CSV, and output directory.
   Show the signed estimate, uncertainty, exclusions, assumptions, alternatives,
   and claim ceiling. Treat a negative or zero-spanning result as reportable.
   If models lack distinct predictions, report that a discriminating next
   experiment is not yet specified. Draft its measurement, assignment,
   stopping, missingness, safety, and falsification choices as review-only
   proposals rather than silently selecting a favorable next method.
7. For a model-specific next test, validate the collaborator proposal against
   a frozen context from the current canonical inquiry. Give `research --json
   guide next` the inquiry ID and context purpose, trusted packet/context/
   proposal-record/receipt hashes, execution directory, and a candidate JSON
   file. The candidate must map four distinct hypothesis suggestions to the
   null, measurement-error, selection/confounding, and user-explanation roles,
   name a separate next-action or design-revision suggestion, and state a
   proposed discrimination criterion. Distinct text predictions produce a
   `review_only_candidate`; matching predictions produce `inconclusive_predictions`
   with no candidate. Neither result validates scientific discrimination,
   freezes a plan, or authorizes an experiment.
8. If canonical inquiry state was changed through `ResearchService`, build its
   synthesis and run `workspace audit --fail-on error` and `workspace verify`.
   Do not interpret ledger integrity or a passing fixture checker as proof of
   source truth, causal identification, consent, replication, or publication
   authority.

The exact-commit cohesive workflow checker still exercises an independent
two-group CSV. The packet now previews paired and adjusted observational
designs with visible pair, covariate, and missingness limits; exact-commit
workflow replay for those designs remains open. Live model, connector,
instrument, reviewer, Metamaps, and domain-validity capabilities remain typed
unavailable stubs in
[TODO.md](TODO.md).
