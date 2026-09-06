from __future__ import annotations

import hashlib
import importlib.util
import re
from collections.abc import Iterable
from importlib.metadata import entry_points
from pathlib import Path

from research_machine.addons.models import (
    AddonManifest,
    AnalysisMethod,
    InstrumentAdapter,
    INFERENCE_LEVELS,
)
from research_machine.domain.errors import NotFoundError, ValidationError

_IDENTIFIER = re.compile(r"^[a-z][a-z0-9]*(?:[._-][a-z0-9]+)*$")


class AddonRegistry:
    """Validated registry for bundled and installed scientific extensions."""

    def __init__(self) -> None:
        self._addons: dict[str, AddonManifest] = {}
        self._methods: dict[str, tuple[AddonManifest, AnalysisMethod]] = {}
        self._instrument_adapters: dict[
            str, tuple[AddonManifest, InstrumentAdapter]
        ] = {}

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
        self._addons[manifest.addon_id] = manifest
        for method in manifest.methods:
            self._methods[method.method_id] = (manifest, method)
        for adapter in manifest.instrument_adapters:
            self._instrument_adapters[adapter.adapter_id] = (manifest, adapter)

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

    @staticmethod
    def _validate(manifest: AddonManifest) -> None:
        if not _IDENTIFIER.fullmatch(manifest.addon_id):
            raise ValidationError("add-on id must be a stable lowercase identifier")
        if not manifest.name.strip() or not manifest.version.strip():
            raise ValidationError("add-on name and version are required")
        seen: set[str] = set()
        for method in manifest.methods:
            if not _IDENTIFIER.fullmatch(method.method_id):
                raise ValidationError(
                    f"analysis method id must be a stable lowercase identifier: {method.method_id}"
                )
            if method.method_id in seen:
                raise ValidationError(f"duplicate method in add-on: {method.method_id}")
            if not method.title.strip() or not method.description.strip():
                raise ValidationError(f"method metadata is incomplete: {method.method_id}")
            if (not isinstance(method.maximum_claim_ceiling, str)
                    or not method.maximum_claim_ceiling.strip()):
                raise ValidationError(
                    f"method maximum_claim_ceiling must be non-blank text: {method.method_id}"
                )
            if method.maximum_inference_level not in INFERENCE_LEVELS:
                raise ValidationError(
                    f"method maximum_inference_level is unsupported: {method.method_id}"
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
            if not adapter.title.strip() or not adapter.description.strip():
                raise ValidationError(
                    f"instrument adapter metadata is incomplete: {adapter.adapter_id}"
                )
            if not adapter.supported_media_types or any(
                not isinstance(value, str) or not value.strip()
                for value in adapter.supported_media_types
            ):
                raise ValidationError(
                    f"instrument adapter supported_media_types are required: {adapter.adapter_id}"
                )
            if len(set(adapter.required_config_fields)) != len(
                adapter.required_config_fields
            ) or any(
                not isinstance(value, str) or not value.strip()
                for value in adapter.required_config_fields
            ):
                raise ValidationError(
                    f"instrument adapter required_config_fields are invalid: {adapter.adapter_id}"
                )
            if len(set(adapter.optional_config_fields)) != len(
                adapter.optional_config_fields
            ) or any(
                not isinstance(value, str) or not value.strip()
                for value in adapter.optional_config_fields
            ) or set(adapter.optional_config_fields) & set(adapter.required_config_fields):
                raise ValidationError(
                    f"instrument adapter optional_config_fields are invalid: {adapter.adapter_id}"
                )
            adapter_ids.add(adapter.adapter_id)


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
