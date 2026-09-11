# Result-exposure disclosure

Protocol adherence and artifact integrity do not establish that an analysis was
prospective. A run may follow a frozen protocol exactly after favorable
development output was already visible. Faraday therefore accepts a typed
`metadata.result_exposure_disclosure` on new run records and requires it for
automatic scientific-evidence eligibility.

## Contract

The disclosure has exactly two input fields:

```json
{
  "status": "no_relevant_output_seen",
  "exposures": []
}
```

Allowed statuses are `no_relevant_output_seen`, `favorable_output_seen`,
`full_output_seen`, and `unknown`. The no-output status requires an empty list.
Favorable and full exposure require at least one exact reference. `unknown` may
retain known references but fails closed even when none can be reconstructed.
Each exposure has exactly:

```json
{
  "exposure_id": "development-pass",
  "artifact_locator": "development/output.json",
  "artifact_sha256": "<64 lowercase hexadecimal characters>",
  "seen_at": "2026-09-09T08:00:00Z",
  "description": "A favorable development result was reviewed before registration."
}
```

The service validates canonical identifiers and locators, exact digests,
bounded report prose, and a timezone-bearing timestamp at or before canonical
protocol registration. It retains the normalized disclosure before computing
the whole-run payload seal. Changing any retained exposure field therefore
breaks current run-integrity replay.

## Eligibility and migration boundary

Only `no_relevant_output_seen` permits automatic scientific-evidence
eligibility, assuming every other run condition passes. Favorable, full,
unknown, or omitted disclosure preserves the completed run and internal result
but blocks automatic evidence promotion. The disclosure is an unauthenticated
assertion and does not prove blinding or honest code.

New run intake retains an absent disclosure as an explicit, ineligible
`legacy_not_declared` marker. Existing canonical runs are not rewritten.
Confirmatory evidence admission requires the complete normalized no-output
form and deterministic synthesis uses that same effective boundary instead of
trusting a stored eligibility bit alone.

Two exact historical boolean fields are recognized only as compatibility
quarantine signals:

- `favorable_development_output_seen_before_registration: true`
- `favorable_prototype_output_seen_before_registration: true`

If either field is present, effective eligibility is false even when an
immutable historical run stores `scientific_evidence_eligible: true`. Rigor and
synthesis surface the conflict; evidence admission rejects it. Faraday does not
search narrative prose for equivalent phrases, and new callers must use the
typed disclosure. This narrowly neutralizes known structured migration gaps
without treating arbitrary wording as authority.

Replication-package verification revalidates normalized fields and recomputes
eligibility. Truly historical packages without the typed field remain readable,
but an exact legacy favorable-exposure flag cannot coexist with an eligible run
in a verified package.

This mechanism does not judge whether exposed output is correct or useful. It
separates that question from automatic evidence admission and prevents
artifact/protocol conformance from being mistaken for prospective protection.
