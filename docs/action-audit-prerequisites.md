# Action audit prerequisites

Faraday version-3 recommendations distinguish three kinds of proposed work:

- `candidate_advancing` changes which candidate or implementation is permitted
  to advance in the research workflow.
- `exposed_evaluator_development` develops or exercises an evaluator in public
  view without advancing a candidate, claiming hypothesis discrimination, or
  becoming scientific evidence.
- `nonadvancing_information` performs ordinary bounded information work—such as
  literature/source search or infrastructure audit—without advancing candidate
  or implementation bytes, claiming hypothesis discrimination, or becoming
  scientific evidence.

Every new action must carry an `audit_prerequisite_contract`. This removes the
ambiguous states in which evaluator development can be mistaken for candidate
admission, or ordinary research is falsely classified as evaluator development.

## Candidate-advancing actions

A candidate-advancing contract names each exact `candidate` or `implementation`
subject by stable ID, safe relative locator, and SHA-256. At least one audit must
cover every subject. Each audit declaration binds:

- stable audit ID and exact artifact role;
- safe relative locator and exact audit-file SHA-256;
- audited subject role, ID, and SHA-256;
- `favorable`, `pending`, or `adverse` verdict;
- exact scope;
- auditor identity as declared in the artifact;
- timezone-aware audit time; and
- explicit limitations; and
- at least one strict `source_pinned_review_finding` supporting artifact with
  exact role, safe relative locator, and SHA-256.

The audit file is strict JSON containing those audit fields, excluding only its
own locator and byte hash. Its `supporting_artifacts` member may bind detailed
reports, but prose reports cannot stand in for the source-pinned finding. The
finding artifact is strict JSON that must name the audited subject, cite exact
source bytes, retain a bounded disposition matching the audit verdict, state
bounded finding and basis text, list limitations, and use the exact
source-pinned non-evidence ceiling. At recommendation creation Faraday verifies
the current subject, audit JSON, source-pinned finding, cited source bytes, and
any other supporting-artifact bytes, plus exact agreement between the audit JSON
and the prospective contract. It then retains a service-generated receipt.
Authoritative reads repeat every byte check and require the recomputed receipt
to equal the retained receipt.

Only a candidate-advancing contract whose required audits all retain
`favorable` verdicts is workflow-selectable. Pending and adverse audits remain
visible in the recommendation candidate set but are ineligible. A missing root,
missing file, symlink, path escape, changed subject, changed audit or supporting
report, missing source-pinned finding, malformed JSON, changed finding source,
changed scope or identity, or audit/finding scoped to other subject bytes fails
closed before selection.

Use the artifact root option when any candidate-advancing action is present:

```sh
./research --workspace .research next-action portfolio \
  --spec-file actions.json \
  --audit-artifact-root /absolute/path/to/retained-artifacts
```

The root is operational custody metadata. Read-only collaborator context
redacts it while retaining hashes, typed scope, verdict, declared auditor and
time, limitations, and the receipt commitment. Recommendation audit receipts do
not enter a protocol or run replication package and cannot authorize evidence;
a scientific replication must still use Faraday's protocol, dataset, run,
evidence, and replication-package contracts.

## Non-advancing information

A non-advancing information contract has no audited subjects or audit-coverage
claim. It requires its own canonical `nonadvancing_information_statement`, an
empty evaluator-exposure statement, and explicit limitations. It can select
bounded literature/source search, catalog work, or infrastructure audit without
mislabeling that work as evaluator development. It must name no hypothesis
distinction and must keep `expected_discrimination` at zero.

## Exposed evaluator development

An exposed evaluator-development contract has no audited subjects or audit
coverage claim. It requires an explicit evaluator-exposure statement, an empty
non-advancing-information statement, and limitations. It may be selected to
develop or exercise an evaluator, but it must name no hypothesis distinction and
must keep `expected_discrimination` at zero.

Receipts for both non-advancing classes always set
`candidate_advancement_eligible`, `scientific_validity_established`, and
`scientific_evidence_eligible` to false. Every receipt also sets
`replication_authority_established` to false; only the separate scientific
replication contracts can support a replication result.

## Conclusion ceiling

Every contract uses the exact ceiling:

> Workflow eligibility only; does not establish audit truth, auditor identity
> or independence, scientific validity, or evidence eligibility.

The byte checks establish provenance and workflow eligibility under the declared
rule. Even a source-pinned finding and bound detailed report do not authenticate
the named auditor, establish auditor qualifications or independence, prove the
audit judgment correct, validate the candidate, or support any scientific
conclusion.

Version-1 and version-2 recommendations remain readable under their historical
score contracts. They do not acquire this new audit-prerequisite authority; a
new version-3 recommendation is required before candidate or implementation
advancement.
