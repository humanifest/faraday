from __future__ import annotations

import hashlib
import importlib.util
import re
from collections.abc import Iterable
from importlib.metadata import entry_points
from pathlib import Path

from research_machine.addons.contracts import ANALYSIS_SPEC_FIELDS
from research_machine.addons.models import (
    AddonManifest,
    AnalysisMethod,
    InstrumentAdapter,
    ScientificConnector,
    INFERENCE_LEVELS,
    RANDOMNESS_CONTROLS,
)
from research_machine.application.policies import require_canonical_bounded_report_text
from research_machine.domain.errors import NotFoundError, ValidationError

_IDENTIFIER = re.compile(r"^[a-z][a-z0-9]*(?:[._-][a-z0-9]+)*$")


def _canonical_values(
    values: tuple[str, ...], field: str, owner: str, *, allow_empty: bool = False
) -> tuple[str, ...]:
    if not values and not allow_empty:
        raise ValidationError(f"{field} are required canonical non-blank strings: {owner}")
    if any(
        not isinstance(value, str) or not value.strip() or value != value.strip()
        for value in values
    ):
        raise ValidationError(f"{field} are required canonical non-blank strings: {owner}")
    if len(set(values)) != len(values):
        raise ValidationError(f"{field} must not contain duplicates: {owner}")
    return values


def _canonical_text(
    value: str, field: str, owner: str, *, allow_empty: bool = False
) -> str:
    if not isinstance(value, str):
        raise ValidationError(f"{field} is required canonical text: {owner}")
    if value != value.strip():
        raise ValidationError(f"{field} is required canonical text: {owner}")
    if not allow_empty and not value:
        raise ValidationError(f"{field} is required canonical text: {owner}")
    return value


class AddonRegistry:
    """Validated registry for bundled and installed scientific extensions."""

    def __init__(self) -> None:
        self._addons: dict[str, AddonManifest] = {}
        self._methods: dict[str, tuple[AddonManifest, AnalysisMethod]] = {}
        self._instrument_adapters: dict[
            str, tuple[AddonManifest, InstrumentAdapter]
        ] = {}
        self._connectors: dict[str, tuple[AddonManifest, ScientificConnector]] = {}

    def register(self, manifest: AddonManifest) -> None:
        self._validate(manifest)
        if manifest.addon_id in self._addons:
            raise ValidationError(f"duplicate add-on id: {manifest.addon_id}")
        for method in manifest.methods:
            if method.method_id in self._methods:
                owner = self._methods[method.method_id][0].addon_id
                raise ValidationError(
                    f"duplicate analysis method {method.method_id}; already provided by {owner}"
                )
        for adapter in manifest.instrument_adapters:
            if adapter.adapter_id in self._instrument_adapters:
                owner = self._instrument_adapters[adapter.adapter_id][0].addon_id
                raise ValidationError(
                    f"duplicate instrument adapter {adapter.adapter_id}; already provided by {owner}"
                )
        for connector in manifest.connectors:
            if connector.connector_id in self._connectors:
                owner = self._connectors[connector.connector_id][0].addon_id
                raise ValidationError(
                    f"duplicate scientific connector {connector.connector_id}; already provided by {owner}"
                )
        self._addons[manifest.addon_id] = manifest
        for method in manifest.methods:
            self._methods[method.method_id] = (manifest, method)
        for adapter in manifest.instrument_adapters:
            self._instrument_adapters[adapter.adapter_id] = (manifest, adapter)
        for connector in manifest.connectors:
            self._connectors[connector.connector_id] = (manifest, connector)

    def list(self) -> list[AddonManifest]:
        return [self._addons[key] for key in sorted(self._addons)]

    def get(self, addon_id: str) -> AddonManifest:
        try:
            return self._addons[addon_id]
        except KeyError as exc:
            raise NotFoundError(f"add-on not found: {addon_id}") from exc

    def resolve_method(self, method_id: str) -> tuple[AddonManifest, AnalysisMethod]:
        try:
            return self._methods[method_id]
        except KeyError as exc:
            raise NotFoundError(f"analysis method not found: {method_id}") from exc

    def resolve_instrument_adapter(
        self, adapter_id: str
    ) -> tuple[AddonManifest, InstrumentAdapter]:
        try:
            return self._instrument_adapters[adapter_id]
        except KeyError as exc:
            raise NotFoundError(f"instrument adapter not found: {adapter_id}") from exc

    def resolve_connector(self, connector_id: str) -> tuple[AddonManifest, ScientificConnector]:
        try:
            return self._connectors[connector_id]
        except KeyError as exc:
            raise NotFoundError(f"scientific connector not found: {connector_id}") from exc

    @staticmethod
    def _validate(manifest: AddonManifest) -> None:
        if not _IDENTIFIER.fullmatch(manifest.addon_id):
            raise ValidationError("add-on id must be a stable lowercase identifier")
        for field in ("name", "version", "discipline", "description"):
            value = getattr(manifest, field)
            _canonical_text(value, f"add-on {field}", manifest.addon_id)
        _canonical_text(
            manifest.documentation, "add-on documentation", manifest.addon_id,
            allow_empty=True,
        )
        _canonical_values(
            manifest.capabilities,
            "add-on capabilities",
            manifest.addon_id,
            allow_empty=True,
        )
        _canonical_values(
            manifest.protocol_kinds,
            "add-on protocol_kinds",
            manifest.addon_id,
            allow_empty=True,
        )
        _canonical_values(
            manifest.dataset_media_types,
            "add-on dataset_media_types",
            manifest.addon_id,
            allow_empty=True,
        )
        seen: set[str] = set()
        for method in manifest.methods:
            if not _IDENTIFIER.fullmatch(method.method_id):
                raise ValidationError(
                    f"analysis method id must be a stable lowercase identifier: {method.method_id}"
                )
            if method.method_id in seen:
                raise ValidationError(f"duplicate method in add-on: {method.method_id}")
            _canonical_text(method.title, "method title", method.method_id)
            _canonical_text(
                method.description, "method description", method.method_id
            )
            _canonical_values(
                method.required_spec_fields,
                "method required_spec_fields",
                method.method_id,
                allow_empty=True,
            )
            unsupported = sorted(set(method.required_spec_fields) - ANALYSIS_SPEC_FIELDS)
            if unsupported:
                raise ValidationError(
                    "method required_spec_fields are not supported analysis "
                    f"specification fields: {method.method_id}: "
                    + ", ".join(unsupported)
                )
            require_canonical_bounded_report_text(
                method.maximum_claim_ceiling,
                "method maximum_claim_ceiling",
            )
            if method.maximum_inference_level not in INFERENCE_LEVELS:
                raise ValidationError(
                    f"method maximum_inference_level is unsupported: {method.method_id}"
                )
            if method.randomness_control not in RANDOMNESS_CONTROLS:
                raise ValidationError(
                    f"method randomness_control is unsupported: {method.method_id}"
                )
            if (
                method.randomness_control == "seeded"
                and "seed" not in method.required_spec_fields
            ):
                raise ValidationError(
                    f"seeded method must require a committed seed: {method.method_id}"
                )
            seen.add(method.method_id)
        adapter_ids: set[str] = set()
        for adapter in manifest.instrument_adapters:
            if not _IDENTIFIER.fullmatch(adapter.adapter_id):
                raise ValidationError(
                    "instrument adapter id must be a stable lowercase identifier: "
                    f"{adapter.adapter_id}"
                )
            if adapter.adapter_id in adapter_ids:
                raise ValidationError(
                    f"duplicate instrument adapter in add-on: {adapter.adapter_id}"
                )
            _canonical_text(
                adapter.title, "instrument adapter title", adapter.adapter_id
            )
            _canonical_text(
                adapter.description,
                "instrument adapter description",
                adapter.adapter_id,
            )
            _canonical_values(
                adapter.supported_media_types,
                "instrument adapter supported_media_types",
                adapter.adapter_id,
            )
            required_config_fields = _canonical_values(
                adapter.required_config_fields,
                "instrument adapter required_config_fields",
                adapter.adapter_id,
                allow_empty=True,
            )
            optional_config_fields = _canonical_values(
                adapter.optional_config_fields,
                "instrument adapter optional_config_fields",
                adapter.adapter_id,
                allow_empty=True,
            )
            if set(optional_config_fields) & set(required_config_fields):
                raise ValidationError(
                    f"instrument adapter optional_config_fields are invalid: {adapter.adapter_id}"
                )
            adapter_ids.add(adapter.adapter_id)
        connector_ids: set[str] = set()
        for connector in manifest.connectors:
            if not _IDENTIFIER.fullmatch(connector.connector_id):
                raise ValidationError(
                    "scientific connector id must be a stable lowercase identifier: "
                    f"{connector.connector_id}"
                )
            if connector.connector_id in connector_ids:
                raise ValidationError(
                    f"duplicate scientific connector in add-on: {connector.connector_id}"
                )
            _canonical_text(connector.title, "connector title", connector.connector_id)
            _canonical_text(connector.description, "connector description", connector.connector_id)
            _canonical_values(connector.supported_source_types, "connector supported_source_types", connector.connector_id)
            required = _canonical_values(connector.required_query_fields, "connector required_query_fields", connector.connector_id, allow_empty=True)
            optional = _canonical_values(connector.optional_query_fields, "connector optional_query_fields", connector.connector_id, allow_empty=True)
            if set(required) & set(optional):
                raise ValidationError(f"connector optional_query_fields are invalid: {connector.connector_id}")
            connector_ids.add(connector.connector_id)


def default_registry(*, include_installed: bool = True) -> AddonRegistry:
    from research_machine.addons.general_science import MANIFEST as GENERAL

    registry = AddonRegistry()
    registry.register(GENERAL)
    if include_installed:
        discovered = entry_points(group="research_machine.addons")
        for entry_point in sorted(discovered, key=lambda item: item.name):
            loaded = entry_point.load()
            manifest = loaded() if callable(loaded) else loaded
            if not isinstance(manifest, AddonManifest):
                raise ValidationError(
                    f"add-on entry point {entry_point.name} did not return AddonManifest"
                )
            registry.register(manifest)
    return registry


def load_local_addons(registry: AddonRegistry, paths: Iterable[Path]) -> AddonRegistry:
    """Load explicitly named local add-ons without requiring package installation."""
    for supplied in paths:
        root = supplied.expanduser().resolve()
        source = root / "research_addon.py" if root.is_dir() else root
        if not source.is_file():
            raise ValidationError(
                f"local add-on must be a research_addon.py file or containing directory: {supplied}"
            )
        digest = hashlib.sha256(str(source).encode()).hexdigest()[:16]
        module_name = f"research_machine_local_addon_{digest}"
        specification = importlib.util.spec_from_file_location(module_name, source)
        if specification is None or specification.loader is None:
            raise ValidationError(f"could not load local add-on: {source}")
        module = importlib.util.module_from_spec(specification)
        try:
            specification.loader.exec_module(module)
        except Exception as exc:
            raise ValidationError(f"local add-on failed to import {source}: {exc}") from exc
        loaded = getattr(module, "MANIFEST", None)
        if loaded is None:
            factory = getattr(module, "get_manifest", None)
            loaded = factory() if callable(factory) else None
        if not isinstance(loaded, AddonManifest):
            raise ValidationError(
                f"local add-on {source} must expose MANIFEST or get_manifest() returning AddonManifest"
            )
        registry.register(loaded)
    return registry
