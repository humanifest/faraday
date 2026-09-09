"""Discipline add-ons and the bundled general-science toolkit."""

from research_machine.addons.models import (
    AddonManifest,
    AnalysisMethod,
    InstrumentAdapter,
    RANDOMNESS_CONTROLS,
)
from research_machine.addons.registry import (
    AddonRegistry,
    default_registry,
    load_local_addons,
)

__all__ = [
    "AddonManifest",
    "AddonRegistry",
    "AnalysisMethod",
    "InstrumentAdapter",
    "RANDOMNESS_CONTROLS",
    "default_registry",
    "load_local_addons",
]
