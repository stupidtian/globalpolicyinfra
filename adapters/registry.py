"""Country-pack registry (section 6.3/6.4).

Each country subpackage declares ``COUNTRY_CODE`` and ``SOURCES`` — a dict
``{source_name: SourceDefinition}``. The registry only scans subpackages and
builds the lookup: adding or removing a country means adding or removing a
directory, never editing central code.
"""

from __future__ import annotations

import importlib
import pkgutil
from typing import Any

from adapters.base import SourceDefinition

__all__ = ["RegistryError", "discover", "get_source"]


class RegistryError(Exception):
    """A country pack is malformed or a country/source is unknown."""


def discover() -> dict[tuple[str, str], SourceDefinition]:
    """Scan ``adapters/`` subpackages into ``{(ISO3, source): SourceDefinition}``."""
    import adapters

    found: dict[tuple[str, str], SourceDefinition] = {}
    for module_info in pkgutil.iter_modules(adapters.__path__):
        if not module_info.ispkg:
            continue
        module: Any = importlib.import_module(f"adapters.{module_info.name}")
        country = getattr(module, "COUNTRY_CODE", None)
        sources = getattr(module, "SOURCES", None)
        if not country or not isinstance(sources, dict) or not sources:
            raise RegistryError(
                f"adapters/{module_info.name}/__init__.py must declare "
                "COUNTRY_CODE and a non-empty SOURCES (convention-based "
                "self-registration)."
            )
        for name, definition in sources.items():
            if not isinstance(definition, SourceDefinition):
                raise RegistryError(
                    f"adapters/{module_info.name} source {name!r} is not a "
                    "SourceDefinition."
                )
            if not definition.task_types:
                raise RegistryError(
                    f"adapters/{module_info.name} source {name!r} declares no "
                    "task types; broken packs fail at scan time, not silently."
                )
            found[(country.upper(), str(name))] = definition
    return found


def get_source(country: str, source: str) -> SourceDefinition:
    """Look up one country × source."""
    catalog = discover()
    key = (country.upper(), source.lower())
    if key not in catalog:
        available = ", ".join(f"{c}/{s}" for c, s in sorted(catalog)) or "(none)"
        raise RegistryError(
            f"No adapter for country {country!r} source {source!r}. Available: {available}."
        )
    return catalog[key]
