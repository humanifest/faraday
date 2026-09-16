from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Callable


AnalysisRunner = Callable[[dict[str, Any], list[dict[str, str]]], dict[str, Any]]
InstrumentInspector = Callable[[bytes, dict[str, Any]], dict[str, Any]]
ConnectorFetcher = Callable[[dict[str, Any]], dict[str, Any]]
INFERENCE_LEVELS = frozenset({
    "computation_only", "descriptive", "association", "design_conditional_effect",
})
RANDOMNESS_CONTROLS = frozenset({"deterministic", "seeded"})


@dataclass(frozen=True)
class AnalysisMethod:
    method_id: str
    title: str
    description: str
    required_spec_fields: tuple[str, ...]
    runner: AnalysisRunner = field(repr=False, compare=False)
    maximum_claim_ceiling: str = "Execution establishes only the returned calculation on the hashed input under the declared method; it does not support a scientific claim."
    maximum_inference_level: str = "computation_only"
    randomness_control: str = "deterministic"

    def describe(self) -> dict[str, Any]:
        value = asdict(self)
        value.pop("runner", None)
        value["required_spec_fields"] = list(self.required_spec_fields)
        return value


@dataclass(frozen=True)
class InstrumentAdapter:
    adapter_id: str
    title: str
    description: str
    supported_media_types: tuple[str, ...]
    required_config_fields: tuple[str, ...]
    inspector: InstrumentInspector = field(repr=False, compare=False)
    optional_config_fields: tuple[str, ...] = ()

    def describe(self) -> dict[str, Any]:
        value = asdict(self)
        value.pop("inspector", None)
        value["supported_media_types"] = list(self.supported_media_types)
        value["required_config_fields"] = list(self.required_config_fields)
        value["optional_config_fields"] = list(self.optional_config_fields)
        value["authority"] = "acquisition_metadata_proposal_only"
        return value


@dataclass(frozen=True)
class ScientificConnector:
    connector_id: str
    title: str
    description: str
    supported_source_types: tuple[str, ...]
    required_query_fields: tuple[str, ...]
    fetch: ConnectorFetcher = field(repr=False, compare=False)
    optional_query_fields: tuple[str, ...] = ()

    def describe(self) -> dict[str, Any]:
        return {
            "connector_id": self.connector_id,
            "title": self.title,
            "description": self.description,
            "supported_source_types": list(self.supported_source_types),
            "required_query_fields": list(self.required_query_fields),
            "optional_query_fields": list(self.optional_query_fields),
            "authority": "bounded_source_material_proposal_only",
            "scientific_evidence_eligible": False,
            "can_register_dataset": False,
            "can_clear_custody": False,
        }


@dataclass(frozen=True)
class AddonManifest:
    addon_id: str
    name: str
    version: str
    discipline: str
    description: str
    methods: tuple[AnalysisMethod, ...] = ()
    instrument_adapters: tuple[InstrumentAdapter, ...] = ()
    connectors: tuple[ScientificConnector, ...] = ()
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
            "instrument_adapters": [
                adapter.describe() for adapter in self.instrument_adapters
            ],
            "connectors": [connector.describe() for connector in self.connectors],
            "capabilities": list(self.capabilities),
            "protocol_kinds": list(self.protocol_kinds),
            "dataset_media_types": list(self.dataset_media_types),
            "documentation": self.documentation,
        }
