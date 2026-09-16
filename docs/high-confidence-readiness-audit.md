# High-confidence readiness audit

This is a living audit of Faraday's seven campaign-readiness requirements. It
is deliberately stricter than a passing test suite. A capability is not
campaign-ready merely because its schema, receipt, or synthetic fixture is
implemented.

| Requirement | Current evidence | Status | What is still required |
| --- | --- | --- | --- |
| Domain add-ons | Validated add-on registry, general empirical toolkit, mathematical predicate and computation-route contracts, instrument inspectors, and local-plugin loading | Partial | Campaign-specific validated methods for formal physics, structural/fire analysis, video/geometry, and source-document handling, each with real-domain failure fixtures and independent review |
| Trusted datasets and custody | Canonical dataset seals, observation-byte verification, measurement custody, source-authority routes, connector proposals, atomic proposal artifacts, and replay checks | Partial | Real experiment or connector collections must be registered, independently inspected, and bound to protocols, custody artifacts, ethics state, and usable artifact roots; connector access alone remains insufficient |
| Validated methods | Typed method ceilings, implementation hashes, runtime receipts, measurement-validity gates, stability and sensitivity contracts, and explicit missingness/multiplicity rules | Partial | Domain experts must review assumptions, calibration, numerical validity, and applicability on the actual campaign methods; successful execution must not be confused with method adequacy |
| Adversarial competing models | Competing hypotheses, falsifiers, controls, sensitivity analysis, and typed `hypothesis_reactivity_plan` with disclosure and likelihood rules | Partial | Each campaign needs a complete alternative set, blinded or otherwise protected assessment, disconfirming observations, and a reviewed model-comparison design |
| Independent review | Artifact-bound review records, chronology checks, review-only collaborator proposals, ethics status chains, and explicit unauthenticated-reviewer boundaries | Partial | Independent domain, method, ethics, and adversarial reviewers must actually inspect the frozen materials; Faraday does not authenticate identity or expertise yet |
| Replication campaigns | Portable replication packages, protocol-closed lineage, independent executor/code requirements, clean-room declarations, and replayable receipts | Partial | At least one real independent re-execution per substantive campaign, with non-reproductions retained and interpreted under the frozen claim ceiling |
| Disciplined claim ceilings | Separate claim levels for observation, calculation, association, causality, mechanism, attribution, intent, and legal characterization; rigor and synthesis blockers | Substantially implemented | Apply the ceilings to reviewed real campaigns and ensure no report, connector, plugin, or external attestation widens them |

## Adequacy decision

Faraday is **not yet adequate for high-confidence scientific conclusions** about
reconciling quantum mechanics with relativity, WTC 7, or any comparably
consequential campaign. It is an increasingly mature provenance-first research
engine and can support review-only design, bounded computation, and controlled
data intake. The missing evidence is primarily external and scientific: real
datasets, domain-validated methods, independent review, and independent
replication.

## Connector boundary

`ScientificConnector` is an acquisition port, not a scientific authority. The
CLI can fetch a bounded source proposal, persist its bytes and receipt, and
replay the source, connector identity, add-on identity, implementation hash,
and receipt hash. The proposal remains non-evidentiary and cannot register a
dataset or clear custody. This is sufficient to preserve a source handoff; it
is not sufficient to establish source truth, consent, calibration, or scientific
validity.

## Audit rule

This document must be updated only when current repository evidence changes a
requirement's status. A green suite demonstrates implementation consistency for
the tested paths; it does not discharge the real-data, reviewer, expertise, or
replication requirements above.
