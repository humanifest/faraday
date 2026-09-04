"""Discipline add-ons and the bundled general-science toolkit."""

from research_machine.addons.models import AddonManifest, AnalysisMethod
from research_machine.addons.registry import AddonRegistry, default_registry

__all__ = ["AddonManifest", "AddonRegistry", "AnalysisMethod", "default_registry"]
