"""Policy extraction schema definitions."""

from enum import Enum


class PolicyInstrument(str, Enum):
    """Taxonomy of policy instruments."""

    REGULATION = "regulation"
    SUBSIDY = "subsidy"
    TAX = "tax"
    INFORMATION = "information"
    VOLUNTARY = "voluntary_agreement"
    OTHER = "other"


class ExtractionSchema:
    """Placeholder for the structured extraction schema."""

    fields: tuple[str, ...] = (
        "instrument",
        "goal",
        "sector",
        "target_date",
        "obligations",
        "responsible_actor",
    )
