from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Callable


AnalysisRunner = Callable[[dict[str, Any], list[dict[str, str]]], dict[str, Any]]


@dataclass(frozen=True)
class AnalysisMethod:
    method_id: str
    title: str
    description: str
    required_spec_fields: tuple[str, ...]
    runner: AnalysisRunner = field(repr=False, compare=False)

    def describe(self) -> dict[str, Any]:
        value = asdict(self)
        value.pop("runner", None)
        return value


@dataclass(frozen=True)
class AddonManifest:
    addon_id: str
    name: str
    version: str
    discipline: str
    description: str
    methods: tuple[AnalysisMethod, ...] = ()
    capabilities: tuple[str, ...] = ()
    protocol_kinds: tuple[str, ...] = ()
    dataset_media_types: tuple[str, ...] = ()
    documentation: str = ""

    def describe(self) -> dict[str, Any]:
        return {
            "addon_id": self.addon_id,
            "name": self.name,
            "version": self.version,
            "discipline": self.discipline,
            "description": self.description,
            "methods": [method.describe() for method in self.methods],
            "capabilities": list(self.capabilities),
            "protocol_kinds": list(self.protocol_kinds),
            "dataset_media_types": list(self.dataset_media_types),
            "documentation": self.documentation,
        }
