# Newtonian pendulum calibration

This campaign asks a deliberately easy scientific question in order to test a
harder engineering one: can Research Machine recover a bounded known result,
distinguish it from equally simple alternatives, and refuse attractive results
when the data-production contract is violated?

It is a **synthetic software calibration**, not a new test of Newtonian physics.
The machine must therefore retain the run while marking it ineligible for
scientific evidence.

## Registered comparison

The primary analyzer fits three one-parameter laws with no intercept:

- period is constant;
- period is proportional to length;
- period is proportional to the square root of length.

An independent implementation estimates the log-log exponent from median period
at each length. It does not call the primary template-fitting code. The clean
case passes only when both implementations select the square-root law and the
primary fit beats its runner-up by the frozen RMSE ratio.

The suite also includes constant and linear generator controls, so an analyzer
that simply returns `square_root` cannot pass.

## Fail-closed cases

Six fixtures plant one defect apiece: excessive clock drift, a mislabeled
length, angles outside the small-angle regime, an unflagged timing outlier,
incomplete acquisition, and excessive damping. Each must make the case invalid
through its predeclared gate. A seventh control contains a registered sensor
dropout and must remain valid after the frozen exclusion rule is applied.

Fixture generation lives in `fixtures.py`; the primary and independent
analyzers live in separate modules. `campaign-spec.json` fixes the cases,
thresholds, sample size, and seed commitment before fixture generation.
The protocol's `external_anchor` records the spec's local content hash; that is
tamper evidence, not an independent timestamp. A real confirmatory campaign
should replace it with a third-party or otherwise independently witnessed
registration anchor.

## Run it

From the repository root:

```bash
./campaigns/newtonian_pendulum/run \
  --human-reviewed \
  --output workspaces/newtonian-pendulum
```

Use `--human-reviewed` only after a person has inspected the three candidate
laws and authorized the frozen comparison; generated hypotheses may not
self-activate. The command refuses to overwrite a non-empty output directory.
It creates a normal `.research` workspace through the application service,
freezes the protocol before generating or registering protected fixtures,
records the content-hashed synthetic dataset and run, builds a synthesis,
audits rigor, and verifies the provenance ledger.

Inspect `run-summary.json`, `artifacts/suite-report.json`, and the generated
`.research` workspace. A correct run has every suite gate marked `passed`, while
`scientific_evidence_eligible` remains `false`.

The next stage is the [physical pendulum campaign](physical/README.md), which
prepares a separately frozen experimental protocol and raw-source-backed
collection kit. Its observations must be collected after registration,
registered as non-synthetic confirmatory data, and analyzed without changing
the frozen rules.
