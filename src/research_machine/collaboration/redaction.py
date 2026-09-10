"""Shared redaction contract for provider-neutral collaboration artifacts."""

COLLABORATOR_CONTEXT_REDACTION_MARKER = "[redacted: retained in canonical store]"

OPERATIONAL_CONTEXT_KEYS = {
    "artifact_root",
    "attestation_schema_path",
    "custody_artifact_root",
    "ethics_artifact_root",
    "review_artifact_root",
    "run_artifact_root",
    "run_attestation_schema_path",
}
