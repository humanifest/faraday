from __future__ import annotations

import re
from importlib.metadata import entry_points

from research_machine.addons.models import AddonManifest, AnalysisMethod
from research_machine.domain.errors import NotFoundError, ValidationError

_IDENTIFIER = re.compile(r"^[a-z][a-z0-9]*(?:[._-][a-z0-9]+)*$")


class AddonRegistry:
    """Validated registry for bundled and installed scientific extensions."""

    def __init__(self) -> None:
        self._addons: dict[str, AddonManifest] = {}
        self._methods: dict[str, tuple[AddonManifest, AnalysisMethod]] = {}

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
        self._addons[manifest.addon_id] = manifest
        for method in manifest.methods:
            self._methods[method.method_id] = (manifest, method)

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
            seen.add(method.method_id)


def default_registry(*, include_installed: bool = True) -> AddonRegistry:
    from research_machine.addons.general_science import MANIFEST as GENERAL
    from research_machine.addons.physics import MANIFEST as PHYSICS

    registry = AddonRegistry()
    registry.register(GENERAL)
    registry.register(PHYSICS)
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
