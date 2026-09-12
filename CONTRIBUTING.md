# Contributing

Faraday is the open-source Research Machine. This repository is the engine, not
a place to store live studies.

## What belongs here

Useful work includes:

- tighter validation, provenance, and fail-closed gates;
- tests for new scientific contracts;
- documentation that makes the current command surface easier to run;
- add-on interfaces that do not create a second evidence store;
- adversarial review of overclaiming language and missing competing models.

Do not commit live hypotheses, study protocols, collected data, experiment
workspaces, credentials, or domain conclusions. Connect those with
`--addon-path` or `RESEARCH_ADDON_PATH` from a separate repository.

## Before opening nontrivial work

1. Open or identify an issue.
2. Keep the change narrow and explainable.
3. Add tests for every new validation gate and provenance-sensitive transition.
4. Disclose AI assistance and retain human responsibility.
5. Do not submit mass formatting, dependency churn, or unsolicited generated
   pull-request reviews.

Use DCO signoff (`Signed-off-by: Name <email>`) unless a later review adopts a
CLA. Contributions are licensed under the [MIT License](LICENSE).

Validate locally with:

```bash
pytest
python -m compileall -q src tests
```

A green suite is engineering evidence. It does not certify a scientific result.
