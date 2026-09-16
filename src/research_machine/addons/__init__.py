"""Discipline add-ons and the bundled general-science toolkit."""

from research_machine.addons.models import (
    AddonManifest,
    AnalysisMethod,
    InstrumentAdapter,
    ScientificConnector,
    RANDOMNESS_CONTROLS,
)
from research_machine.addons.registry import (
    AddonRegistry,
    default_registry,
    load_local_addons,
)
from research_machine.addons.connector import (
    fetch_source_proposal,
    verify_source_proposal,
    write_source_proposal,
)

__all__ = [
    "AddonManifest",
    "AddonRegistry",
    "AnalysisMethod",
    "InstrumentAdapter",
    "ScientificConnector",
    "fetch_source_proposal",
    "write_source_proposal",
    "verify_source_proposal",
    "RANDOMNESS_CONTROLS",
    "default_registry",
    "load_local_addons",
]
