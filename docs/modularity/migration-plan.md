# Faraday migration plan

Status: `planned`; first slice is a safe scaffold, not a cutover.

## Ordered slices

1. **Baseline and contract proposal — implemented locally.** Inventory the
   existing protocol/run/receipt/integrity seams and record the proposed
   shared boundary. No production behavior changes.
2. **Fixture-only projection seam — scaffolded locally.** Represent a versioned
   lineage/assumption projection and its invalidation when a source revision or
   artifact hash changes. The JSON fixture and test are deterministic and have
   no provider or network dependency.
3. **Faraday adapter — blocked.** Add a narrow adapter around an existing
   canonical workflow only after a saved workflow and accepted shared contract
   are identified. Preserve old command/API behavior and shadow-compare bytes
   and typed findings.
4. **Metamaps integration — blocked.** Reconcile the actual compiler API,
   pinned version, projection schema, and invalidation mechanism. Run a
   fixture-only comparison before any authorized integration work.
5. **Cutover/rollback — not started.** A future cutover requires explicit
   mapping, dry-run output, backup/restore evidence, compatibility checks, and
   separate authorization. Until then the current Faraday path remains the
   supported route.

## Compatibility, risks, and rollback

Preserve existing record IDs, hashes, timestamps, protocol/model versions,
exploratory labels, negative results, and uncertainty. Never rewrite historical
records to fit a new canonicalizer. The principal risks are semantic contract
drift, accidentally treating graph structure as scientific validity, and
confusing a fixture double with an integration.

Rollback for this scaffold is deletion/revert of only the newly added
`docs/modularity/` files, `tests/test_modularity_fixture_contract.py`, and
`tests/fixtures/modularity/metamaps-projection-v0.json`; no canonical state is
written and no existing route is altered. Any future adapter must be disabled
by configuration or compatibility routing before removal.

## Handoffs and TODOs

- TODO: contract owner to accept/revise `rigour-record-ref/v0`.
- TODO: Faraday maintainer to select a real saved synthetic workflow and define
  old/new shadow comparison tolerances.
- TODO: obtain the authorized Metamaps fixture/compiler contract and pin its
  version.
- TODO: define Orca job/lease receipt mapping without duplicating scheduling.
- TODO: define Cypher/provider disclosure mapping without enabling a provider.
- TODO: define system-config authorization/effect checks at the actual effect
  boundary.
- TODO: add revision-impact extraction from canonical Faraday records once the
  shared projection input shape is accepted.
