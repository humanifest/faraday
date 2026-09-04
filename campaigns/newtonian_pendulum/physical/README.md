# Physical pendulum campaign

This is the empirical successor to the synthetic pendulum calibration. It
creates a frozen confirmatory protocol and a randomized collection kit, but it
does not invent observations, register a dataset, or record a run.

The experiment discriminates among three equal-parameter candidate laws:

- `T = a`;
- `T = aL`;
- `T = a√L`.

It uses six lengths in eight randomized complete blocks, twenty oscillations per
trial, raw-video hashes, before/after clock controls, per-trial length and angle
measurements, blinded repeat scoring for eight prespecified timing audits,
frozen exclusion rules, leave-one-length-out scoring, and an independently
implemented log-log analysis. The physical spec is included in the frozen
analysis-code commitment, and the executor independently reconstructs the
schedule from its committed seed.

## Prepare

Review `physical-spec.json` and the protocol definitions in `prepare.py`, then:

```bash
./campaigns/newtonian_pendulum/physical/run prepare \
  --human-reviewed \
  --output workspaces/newtonian-pendulum-physical
```

The generated `collection-kit/COLLECTION-GUIDE.md` is the operational handoff.
The workspace should contain one frozen protocol and zero datasets, runs, or
evidence records until real collection occurs.

## Analyze

After collection, register the filled kit and every raw video as one
non-synthetic confirmatory dataset bound to the frozen protocol. Then use:

```bash
./campaigns/newtonian_pendulum/physical/run analyze \
  --kit workspaces/newtonian-pendulum-physical/collection-kit \
  --dataset-id ds-newtonian-pendulum-physical-v1 \
  --output workspaces/newtonian-pendulum-physical/analysis
```

The analyzer writes a report and a run-record candidate. Preflight that exact
record through Research Machine before recording it.

Execution gates test provenance, completeness, calibration, boundaries, and
faithful execution. They do not require a Newtonian-looking result. A valid
constant, linear, weakly separated, or analyzer-discordant outcome therefore
remains eligible for honest evidence classification rather than becoming a
“failed experiment.”

The maximum claim is deliberately narrow: a result concerns one apparatus and
the registered length and angle range. It does not validate or refute Universal
Theory as a whole.
