"""Hash validators for literature workflow trust anchors."""
from typing import Any

from research_machine.domain.errors import ValidationError


def require_sha256(value: Any, field: str) -> str:
    if (
        not isinstance(value, str)
        or len(value) != 64
        or any(character not in "0123456789abcdef" for character in value)
    ):
        raise ValidationError(f"{field} must be a lowercase SHA-256 digest")
    return value
