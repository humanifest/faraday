# Bounded negative-search contract

Use `bounded_negative_search_contracts` when a literature, source, registry, or
catalog search will be used to say that no matching record was found. This is a
domain-neutral custody contract for a finite search record, not an exhaustive
review or a truth oracle.

Each contract freezes:

- the exact search question and explicit inclusion and exclusion scope;
- the calendar date of the search;
- every database/interface name, interface identity, and version;
- every exact query and the interface against which it was submitted;
- a prose stop rule plus numeric maxima for queries and screened candidates;
- every screened candidate, its source identity and query lineage;
- `in_scope_target`, `retained_context`, or `excluded` screening decisions;
- a SHA-256 digest for every retained source and a reason for every exclusion;
- the fixed `bounded_retrieval_record_only` conclusion ceiling and explicit
  rejection of universal absence, mathematical impossibility, theorem/proof,
  and absence beyond the frozen interfaces, queries, date, and stop rule; and
- an adverse omission/truncation control evaluated at the same required gate.

An empty `screened_candidates` list is valid when the frozen queries returned
no candidates. An excluded candidate has an exclusion reason and no retained
source hash. An `in_scope_target` or `retained_context` candidate has a retained
source hash and no exclusion reason. These rules preserve the review record but
do not determine whether a human screening judgment was substantively correct.

## Run result

A performed gate returns one exact
`bounded_negative_search_results[contract_id]` object. It repeats the frozen
record and reports exact executed query, searched interface, and screened
candidate IDs; exact retained-source hashes and exclusion reasons; Boolean stop
rule and record-completeness outcomes; and an assessment. The result cites an
exact JSON object in one listed output artifact, and run intake derives
`selected_value_sha256` from that selected object.

A passed gate is rejected unless:

1. all repeated search fields equal the frozen contract;
2. the observed query, interface, and candidate lists equal the frozen order;
3. retained-source hashes and exclusion reasons equal the frozen records;
4. the stop rule was satisfied and the search record was complete;
5. the linked adverse omission/truncation control matched expectation; and
6. the artifact-selected JSON exactly equals the submitted result.

Replication-package verification replays the same typed equality checks.
Stable `source_id` values and source hashes remain available for metadata
replay, while normal operational artifact locators remain redacted.

## Required adverse fixture

The minimum useful generic fixture contains at least two screened candidates.
Delete the final candidate from a copied observed record while leaving the rest
plausible. Exact candidate coverage must reject that truncated record. A second
mutation changes one retained source hash and must also reject.

The adverse control detects the tested omission or truncation. It does not prove
that the chosen databases indexed every source, that the queries had adequate
recall, that the interface returned complete results, or that screening
decisions were correct.

## Ceiling

When no candidate is classified `in_scope_target`, the strongest permitted
statement is: no in-scope target was recorded within the exact frozen search
bounds. “No source exists,” “the construction is impossible,” and “this is a
theorem/proof” are forbidden upgrades. A broader date, database, interface,
query family, language, source type, citation-chain search, or screening rule
requires a new protocol version and produces a new bounded record.
