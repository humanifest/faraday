class ResearchMachineError(Exception):
    """Base class for expected, user-actionable failures."""


class ValidationError(ResearchMachineError):
    """A command would create invalid research state."""


class NotFoundError(ResearchMachineError):
    """A referenced research object does not exist."""


class ConflictError(ResearchMachineError):
    """A command conflicts with existing research state."""


class IntegrityError(ResearchMachineError):
    """Stored state or the provenance ledger failed verification."""
