"""Shared report-language boundaries for retained Faraday prose."""

from __future__ import annotations

import re


_REPORT_OVERCLAIM = re.compile(
    r"\b(?:proved|confirmed|explained|validates?|validated)\b",
    re.IGNORECASE,
)
_LEGAL_INTENT_OVERCLAIM = re.compile(
    r"\b(?:establish(?:es|ed)?|finds?|found|determines?|determined|"
    r"shows?|showed|demonstrates?|demonstrated)\b(?:\s+\w+){0,6}\s+"
    r"\b(?:legal characterization|legal responsibility|legal liability|"
    r"culpability|liability|guilt|negligence|fraudulent intent|criminal intent|"
    r"intentional wrongdoing)\b|"
    r"\b(?:is|are|was|were)\s+(?:legally responsible|liable|guilty|negligent)\b|"
    r"\bcommitted\s+fraud\b",
    re.IGNORECASE,
)


def report_overclaim_terms(value: str) -> list[str]:
    if not isinstance(value, str):
        return []
    terms: list[str] = []
    seen: set[str] = set()
    for pattern in (_REPORT_OVERCLAIM, _LEGAL_INTENT_OVERCLAIM):
        for match in pattern.finditer(value):
            term = match.group(0).casefold()
            if term not in seen:
                seen.add(term)
                terms.append(term)
    return terms
