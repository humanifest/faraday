# Deferred AI science guide capabilities

Status: G08 typed stubs locally verified. None of these integrations is
implemented or authorized by the goal plan. The guide returns `not_configured`
or `unsupported` responses with negative tests for each applicable entry. No stub
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
| T09 | Domain-specific construct validity: `unsupported` | Construct-specific reference, calibration criteria, source-bound validity findings, and independent assessment | Faraday domain researcher; synthetic contradicted-validity check | Reviewed validity evidence and the applicable frozen protocol gates |

The modularity and reconciliation branches contain proposals that may inform
T03 and T05. They do not satisfy the activation gates here. Every later TODO
resolution must name the exact artifact, requirement, evaluator, and versioned
evidence it closes, and update the high-confidence readiness audit only when
that evidence changes its status.

## G08 typed capability links

The `research guide capability` route returns only a typed unavailable result,
the matching TODO link, and explicit `false` effect and authority fields. The
links below refine the existing register; T07 and T08 remain separate approval
and publication boundaries.

## live-model

T01. Owner: Cypher and Faraday. Missing: verified inference backend and scoped
disclosure contract. First safe fixture: fixed local response to a redacted
synthetic context. Activation: T01's provider and network gate.

## live-connector

T02. Owner: Faraday connector maintainer and system-config. Missing: source
rights, bounded retrieval, and immutable custody. First safe fixture: offline
fabricated connector replay. Activation: T02's network/source gate.

## live-instrument

T02. Owner: Faraday measurement maintainer and system-config. Missing:
calibration, time, raw-byte custody, and safety stop. First safe fixture:
simulated failed-calibration stream. Activation: T02's device/ethics gate.

## arbitrary-statistics

T03. Owner: Faraday method registry. Missing: exact design and scale contract,
implementation closure, adverse controls, and claim ceiling. First safe
fixture: one new method with wrong-scale and post-result-selection cases.
Activation: T03's independent method review.

## domain-specific-validity

T09. Owner: Faraday domain researchers and independent reviewers. Missing:
construct-specific validity evidence. First safe fixture: contradicted
validity check that blocks interpretation. Activation: T09's reviewed
validity and protocol gates.

## authenticated-reviewer

T04. Owner: system-config and Orca. Missing: identity, role, decision receipt,
and separation from the worker. First safe fixture: forged reviewer receipt.
Activation: T04's independent identity gate.

## metamaps-compilation

T05. Owner: Metamaps and Orca. Missing: versioned projection/interface and
stale-dependency replay. First safe fixture: changed-source invalidation.
Activation: T05's accepted cross-project contract.

## concurrent-writes

T06. Owner: Faraday persistence and Orca. Missing: transaction, conflict, and
recovery semantics. First safe fixture: two-worker conflict on a disposable
inquiry. Activation: T06's reviewed concurrency design.

## G08 work receipt (2026-10-08)

- Base commit: `c41cbc7`. Changed paths: this register,
  `src/research_machine/application/guide.py`,
  `src/research_machine/interfaces/cli.py`, `tests/test_guide_unavailable.py`,
  and the G08 status in `milestones.json`.
- Fixture: eight typed unavailable capability responses. Planned and observed
  effects: in-process JSON output and disposable pytest state only. No model,
  connector, instrument, browser, network, canonical workspace, or fallback.
- Acceptance command: `python3 -m pytest -q tests/test_guide_unavailable.py`
  with `PATH` selecting Faraday's `.venv`, umask 077, bytecode disabled,
  plugin autoload disabled, pytest cache disabled, and no external add-on path.
  Result: 9 passed.
- Every response links to a TODO naming its owner, missing contract/evidence,
  first safe fixture, and activation gate. This verifies the stub behavior,
  not the unavailable capability.
