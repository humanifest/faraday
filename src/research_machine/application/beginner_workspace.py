"""Presentation/planning notes only; never an executable analysis or review grant."""
WORKSPACE_FIELDS = (
    "comparison_a", "comparison_b", "model_input", "model_output", "model_relation",
    "source_supports", "source_challenges", "source_unclear",
)


def validate_workspace_notes(value):
    if (not isinstance(value, dict)
        or set(value) != {"version", "open", "approach", *WORKSPACE_FIELDS}
        or type(value["version"]) is not int or value["version"] != 1
        or type(value["open"]) is not bool
        or value["approach"] not in ("", "compare", "track", "model", "sources")
        or any(not isinstance(value[field], str) or len(value[field]) > 2000
               for field in WORKSPACE_FIELDS)):
        raise ValueError("Workspace notes require a supported approach and bounded text only.")
    return dict(value)
