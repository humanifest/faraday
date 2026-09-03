# Notebook runtime preflight

The static notebook dependency preflight authenticates bytes without importing
the optional notebook stack or starting a kernel. It therefore cannot detect an
interpreter without `nbclient`, a missing kernelspec, a denied process or socket
boundary, a kernel that never becomes ready, or a wrong kernel working
directory. Discovering those failures only after a scientific protocol is
frozen wastes a registered execution and can create amendment pressure.

The runtime preflight is a separate, explicitly non-scientific capability
check. It must run before a protected scientific protocol is frozen. It accepts
no analysis source path and no user-supplied code:

```bash
research-notebook-runtime-preflight \
  --result-json runtime-preflight.json \
  --working-directory /absolute/project/root \
  --kernel-name python3 \
  --timeout 30
```

## Fixed probe

Version 1 performs only these operations:

1. resolve an existing requested working directory;
2. locate the fixed `jupyter-client`, `nbclient`, and `nbformat` distributions;
3. resolve the requested kernelspec;
4. start one Jupyter kernel in the requested working directory;
5. execute one built-in Python marker cell containing only `json`, `os`, and a
   fixed printed payload;
6. verify the exact marker and resolved working directory; and
7. shut the kernel down.

The report commits to the built-in cell with `smoke_code_sha256`. The command
does not have a source-notebook positional argument, a code option, an import
list, or an environment-setup hook. The report always states:

```json
{
  "analysis_source_loaded": false,
  "analysis_code_executed": false,
  "network_access_requested": false
}
```

Those fields describe the adapter's behavior. They do not establish that the
host or kernel startup files performed no unrelated activity.

## Fail-closed diagnostics

An operational failure exits with status 1 and preserves a report. Stable codes
separate:

- `RUNTIME_DEPENDENCY_UNAVAILABLE`
- `KERNEL_SPEC_UNAVAILABLE`
- `KERNEL_START_FAILED`
- `KERNEL_NOT_READY`
- `SMOKE_CELL_FAILED`
- `SMOKE_OUTPUT_INVALID`
- `WORKING_DIRECTORY_MISMATCH`
- `KERNEL_SHUTDOWN_FAILED`

Invalid arguments or report I/O exit with status 2. An existing report is never
overwritten and prevents a second probe at that path. The caller should preserve
failed reports rather than delete or relabel them.

## Relationship to protected execution

The runtime preflight complements but does not replace the static dependency
preflight. A sound order is:

1. author and developer-test the analysis;
2. run the static dependency preflight;
3. run this fixed runtime preflight;
4. freeze the scientific protocol and exact source/dependency hashes; and
5. let the protected runner repeat static authentication immediately before its
   one scientific execution.

The protected runner intentionally starts a fresh kernel. Reusing the smoke
kernel would blur the execution boundary and could carry state into the
analysis.

## Conclusion ceiling

A pass shows only that one fixed cell completed through one named kernel, in one
working directory, at one time. It does not:

- authenticate an analysis source or any dependency;
- prove that the environment will remain unchanged or available;
- validate a notebook's implementation, method, result, or scientific claim;
- prove the absence of network activity by the host, kernel, startup hooks, or
  imported packages; or
- create evidence for any research hypothesis.

Pin the report and adapter hashes when runtime provenance matters. Repeat the
probe when the interpreter, kernel, process policy, or machine changes, while
retaining prior failures as operational history.
