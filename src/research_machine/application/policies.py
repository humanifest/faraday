from collections.abc import Sequence

from research_machine.domain.errors import ValidationError
from research_machine.domain.models import Hypothesis, HypothesisWorkflowState


def normalize_text(value: str, field_name: str) -> str:
    if not isinstance(value, str):
        raise ValidationError(f"{field_name} must be text")
    return value.strip()


def require_text(value: str, field_name: str) -> str:
    normalized = normalize_text(value, field_name)
    if not normalized:
        raise ValidationError(f"{field_name} must not be empty")
    return normalized


def require_text_list(values: Sequence[str], field_name: str) -> list[str]:
    if isinstance(values, (str, bytes)) or not isinstance(values, Sequence):
        raise ValidationError(f"{field_name} must be a list of text values")
    return [require_text(value, f"{field_name} item") for value in values]


def validate_hypothesis_activation(hypothesis: Hypothesis) -> None:
    if hypothesis.workflow_state not in {
        HypothesisWorkflowState.UNREVIEWED,
        HypothesisWorkflowState.PARKED,
    }:
        raise ValidationError(
            f"hypothesis {hypothesis.hypothesis_id} cannot be activated from "
            f"{hypothesis.workflow_state.value}"
        )
    missing: list[str] = []
    if not hypothesis.observable_prediction.strip():
        missing.append("observable_prediction")
    if not hypothesis.falsification_conditions:
        missing.append("falsification_conditions")
    if not hypothesis.null_model.strip() and not hypothesis.competing_models:
        missing.append("null_model or competing_models")
    if missing:
        raise ValidationError(
            "hypothesis cannot be activated until it defines: " + ", ".join(missing)
        )


def validate_evidence_target(hypothesis: Hypothesis) -> None:
    if hypothesis.workflow_state is HypothesisWorkflowState.UNREVIEWED:
        raise ValidationError(
            "evidence cannot be attached to an unreviewed proposal; activate it first"
        )
