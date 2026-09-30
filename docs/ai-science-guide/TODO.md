# Deferred AI science guide capabilities

Status: proposed TODO register. None of these integrations is implemented or
authorized by the goal plan. `G08` must add typed `not_configured` or
`unsupported` responses and negative tests for each applicable entry. No stub
may call a service, widen a claim ceiling, or silently fall back to another
provider. Owners below are contract owners, not assigned people.

| ID | Capability and present stub | Missing contract or evidence | Owner and first safe fixture | Activation gate |
| --- | --- | --- | --- | --- |
| T01 | Live LLM provider: `not_configured` | Approved provider/data destination, disclosure policy, prompt/output receipt, cost and failure behavior | Cypher/provider boundary; fixture adapter returns a fixed review-only proposal | Separate provider and network authorization; verify actual backend, telemetry, and no cloud fallback before real use |
| T02 | Live connector or instrument: `not_configured` | Source rights, consent, calibration, timing, custody, bounded query/collection policy | Domain add-on owner; synthetic source bytes and failed-calibration receipt | Authorized physical/network acquisition and independent source review |
| T03 | Statistical designs beyond bundled methods: `unsupported` | Method manifest, assumptions, reference implementation, numerical and adverse validation, claim ceiling | Faraday method add-on owner; known-result synthetic dataset plus wrong-design fixture | Independent method review for the intended campaign |
| T04 | Authenticated independent reviewer: `not_configured` | Identity, expertise, conflict, signed decision, and revocation semantics | system-config/review contract owner; fixture reviewer with explicitly unauthenticated status | Accepted trust contract and independently verified reviewer identity |
| T05 | Real Metamaps projection: `not_configured` | Pinned compiler/API, accepted projection schema, versioned input mapping, invalidation behavior | Metamaps contract owner; projection fixture with changed-source invalidation | Accepted cross-project contract and real compiler comparison; graph findings remain non-authoritative |
| T06 | Concurrent multi-user operation: `unsupported` | Transaction or lock semantics, access control, conflict resolution, recovery, and migration path | Faraday storage owner; two-client conflict fixture against a disposable store | Separate concurrency design, failure recovery evidence, and authorized migration |
| T07 | Automated confirmatory activation or evidence acceptance: `unsupported` | There is no worker grant for scientific approval; current human and domain review gates remain authoritative | Faraday application owner; malicious AI proposal fixture | No automatic activation gate in this goal; any later policy proposal requires separate owner decision |
| T08 | Publication or high-confidence campaign claim: `unsupported` | Real data, domain validation, independent review and replication, disclosure and publication authority | Domain campaign owner; synthetic negative-result report fixture | Separate campaign acceptance and publication authorization |

The modularity and reconciliation branches contain proposals that may inform
T03 and T05. They do not satisfy the activation gates here. Every later TODO
resolution must name the exact artifact, requirement, evaluator, and versioned
evidence it closes, and update the high-confidence readiness audit only when
that evidence changes its status.
