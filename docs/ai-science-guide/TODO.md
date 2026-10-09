# Deferred AI science guide capabilities

Status: C00–C12 local fixtures verified through the exact-commit capability
checker. The guide includes review-only T10–T11 previews and typed T01–T09
boundaries. Independent design review and external integrations remain open.
No live integration or scientific activation gate is authorized by the goal
plan. The guide returns `not_configured` or `unsupported` where a live
capability remains unavailable.
No unavailable stub may invoke an external service, widen a claim ceiling, or silently fall back to another
provider. Owners below are contract owners, not assigned people.

| ID | Capability and present state | Missing contract or evidence | Owner and first safe fixture | Activation gate |
| --- | --- | --- | --- | --- |
| T01 | Live LLM provider: `not_configured` | Approved provider/data destination and disclosure policy, actual backend and telemetry inspection, live cost/failure behavior | Cypher/provider boundary; in-process fixed adapter returns a review-only proposal and receipt | Separate provider and network authorization; verify actual backend, telemetry, and no cloud fallback before real use |
| T02 | Live connector or instrument: `not_configured` | Independently established source rights, consent and calibration; authorized bounded network/device collection and custody | Domain add-on owner; synthetic verified source receipt and failed-calibration instrument preview | Authorized physical/network acquisition and independent source review |
| T03 | Statistical designs beyond bundled methods: `unsupported` | Further domain methods and independent method review for intended campaigns; arbitrary statistics remain unsupported | Faraday method add-on owner; exact paired sign fixture with exhaustive reference and wrong-design control | Independent method review for the intended campaign |
| T04 | Authenticated independent reviewer: `not_configured` | Identity, expertise, conflict, signed decision, and revocation semantics | system-config/review contract owner; fixture reviewer with explicitly unauthenticated status | Accepted trust contract and independently verified reviewer identity |
| T05 | Real Metamaps projection: `not_configured` | Pinned compiler/API, accepted projection schema, versioned input mapping, invalidation behavior | Metamaps contract owner; projection fixture with changed-source invalidation | Accepted cross-project contract and real compiler comparison; graph findings remain non-authoritative |
| T06 | Concurrent multi-user operation: `unsupported` | Transaction or lock semantics, access control, conflict resolution, recovery, and migration path | Faraday storage owner; two-client conflict fixture against a disposable store | Separate concurrency design, failure recovery evidence, and authorized migration |
| T07 | Automated confirmatory activation or evidence acceptance: `unsupported` | There is no worker grant for scientific approval; current human and domain review gates remain authoritative | Faraday application owner; malicious AI proposal fixture | No automatic activation gate in this goal; any later policy proposal requires separate owner decision |
| T08 | Publication or high-confidence campaign claim: `unsupported` | Real data, domain validation, independent review and replication, disclosure and publication authority | Domain campaign owner; synthetic negative-result report fixture | Separate campaign acceptance and publication authorization |
| T09 | Domain-specific construct validity: `unsupported` | Construct-specific reference, calibration criteria, source-bound validity findings, and independent assessment | Faraday domain researcher; synthetic contradicted-validity check | Reviewed validity evidence and the applicable frozen protocol gates |
| T10 | Model-specific next-experiment candidate: `review_only` | Independent evaluation of the proposed discrimination, prospective design, ethics, and actual model adequacy | Faraday guide and domain reviewer; synthetic null/measurement/confounding proposal with an inconclusive next test | Independent review of the proposed discrimination and existing design/ethics gates before any execution |
| T11 | Paired and observational guide packet preview: `review_only` | Exact-commit workflow replay for both designs and independent assessment of method-specific claim ceilings | Faraday guide maintainer; paired duplicate/missing-pair and observational confounding fixtures | Bounded adverse guide checks plus exact-commit workflow replay for each design |

The modularity and reconciliation branches contain proposals that may inform
T03 and T05. They do not satisfy the activation gates here. Every later TODO
resolution must name the exact artifact, requirement, evaluator, and versioned
evidence it closes, and update the high-confidence readiness audit only when
that evidence changes its status.

## G08 typed capability links

The `research guide capability` route returns only a typed boundary result,
the matching TODO link, and explicit `false` effect and authority fields. The
links below refine the existing register; T07 and T08 remain separate approval
and publication boundaries.

## live-model

T01. Owner: Cypher and Faraday. The C04 in-process fixture binds a redacted
synthetic context, prompt/output hashes, zero-cost ceiling, failure, and no
fallback. It validates a fixed review-only proposal without invoking a model.
Missing: accepted Cypher provider interface, approved destination and scoped
disclosure, verified inference backend, telemetry and fallback inspection,
and live cost/failure behavior. Activation: T01's separate provider and
network gate.

## live-connector

T02. Owner: Faraday connector maintainer and system-config. C05 reuses the
existing connector source proposal verifier for an offline fabricated source.
The guide view retains raw-byte and receipt hashes, query implementation
replay, and declared rights and consent while explicitly withholding custody,
source review, and acquisition authority. Missing: independently established
rights, bounded live retrieval, and immutable custody. Activation: T02's
network/source gate.

## live-instrument

T02. Owner: Faraday measurement maintainer and system-config. C05 reuses the
existing instrument inspection record verifier and checks current raw source
bytes, proposed capture time and basis, and a source-bound failed-calibration
declaration. It blocks the guide handoff without claiming calibration truth.
Missing: approved instrument access, independently reviewed calibration,
time accuracy, custody, and safety stop. Activation: T02's device/ethics gate.

## arbitrary-statistics

T03. Owner: Faraday method registry. C06 adds a bounded exact paired sign
test to the versioned general-science manifest. It requires complete numeric
matched pairs, reports ties and sign counts, and limits the exact two-sided
calculation to 256 pairs. A six-non-tied-pair synthetic case agrees with an
independent exhaustive sign enumeration at 0.03125; wrong design, incomplete
pairs, and non-numeric outcomes fail. It reports sign compatibility without
effect magnitude or causal authority. Missing: further domain methods,
campaign-specific assumption checks, and independent method review.
Arbitrary statistics remain unsupported. Activation: T03's independent
method review.

## domain-specific-validity

T09. Owner: Faraday domain researchers and independent reviewers. C07 now
projects frozen checks and recorded source-bound diagnostics without granting
supportive interpretation. Absent, inconclusive, and contradicted results
block the guide view. Missing: construct-specific validity evidence and
independent assessment. Activation: T09's reviewed validity and protocol
gates.

## authenticated-reviewer

T04. Owner: system-config and Orca. C08 replays Faraday's retained review
record and treats forged bytes, revocation, declared conflicts, and an
unauthenticated identity as blocking. Even an active claim of authentication
waits for an owner verifier and grants no independent-review status. Missing:
accepted identity, role, expertise, signed decision, conflict, and revocation
verification outside the worker. Activation: T04's independent identity gate.

## metamaps-compilation

T05. Owner: Metamaps and Orca. Missing: versioned projection/interface and
real owner comparison. C09 compares an opaque synthetic projection receipt
against supplied source fingerprints and required constraint IDs. Changed
sources or missing constraints make the local view stale; matching pins still
await an accepted owner compiler and do not establish graph semantics.
Activation: T05's accepted cross-project contract.

## concurrent-writes

T06. Owner: Faraday persistence and Orca. Missing: transaction, conflict, and
recovery semantics. C10 uses two service clients on a disposable inquiry:
a ledger-head preflight rejects a stale guide intent and a refreshed intent
can proceed. The preflight is not atomic with a later write, so it provides
no production concurrency guarantee. Activation: T06's reviewed concurrency
design and migration.

## automated-confirmatory-activation

T07. A guide worker has no route to activate a confirmatory plan or accept
scientific evidence. C11's draft-report fixture rejects approve and
accept-evidence requests and keeps both authority flags false. Any future
change to that boundary requires a separate system-config/Orca owner decision;
the worker cannot grant it to itself.

## publication

T08. C11 can shape a synthetic interval-spanning-zero explanation into an
inconclusive review-only report draft. A publish request fails, and the draft
does not claim no effect, independent review, or publication authority.
Missing: accepted real-data campaign, domain review, replication where
applicable, disclosure review, and publication authorization.

## model-specific-next-experiment

T10. Status: `review_only`. Owner: Faraday guide and independent domain
reviewer. `research guide next` now binds a validated proposal record to the
current inquiry and verified execution receipt, requires four competing
predictions and falsifiers, and accepts a proposed discrimination criterion.
Equal predictions remain inconclusive. Missing: independent scientific review
of whether the predictions actually discriminate, prospective protocol
commitment, and ethics/design gates. First safe fixture: synthetic null,
measurement, and confounding proposals with an inconclusive next test.
Activation: independent design and ethics review before any experiment or
canonical transition.

## paired-observational-packet

T11. Status: `review_only`. Owner: Faraday guide maintainer. The local packet
now inventories pair structure, covariates, and missingness with a bounded
claim ceiling. Missing: exact-commit workflow replay for both designs and
independent assessment of method-specific applicability. First safe fixture:
paired duplicate and missing pair plus observational missingness/confounding
cases. Activation: bounded adverse guide checks plus exact-commit replay for
each design.

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
