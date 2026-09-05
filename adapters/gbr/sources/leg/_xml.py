"""Namespace-agnostic helpers for the site's XML dialects.

The official documentation warns that namespace *prefixes* vary between
documents (``leg:``, ``ukl:`` or a default namespace may all carry the
legislation namespace), so every lookup matches local names against the
resolved namespace URI — never the prefix.
"""

from __future__ import annotations

import re
from xml.etree import ElementTree as ET

__all__ = ["children", "find_deep", "first_child", "iso_date", "localname", "texts"]


def localname(tag: str) -> str:
    """The local part of a possibly namespaced element tag."""
    return tag.rsplit("}", 1)[-1] if "}" in tag else tag


def children(element: ET.Element, name: str) -> list[ET.Element]:
    """Direct children of *element* whose local name is *name*."""
    return [child for child in element if localname(child.tag) == name]


def first_child(element: ET.Element, name: str) -> ET.Element | None:
    for child in element:
        if localname(child.tag) == name:
            return child
    return None


def find_deep(element: ET.Element, name: str) -> ET.Element | None:
    """First element in document order with the local name *name*."""
    for el in element.iter():
        if el is not element and localname(el.tag) == name:
            return el
    return None


def texts(element: ET.Element | None) -> str:
    """All inner text of an element (xhtml-wrapped titles included)."""
    if element is None:
        return ""
    return "".join(element.itertext()).strip()


_MONTHS = {
    "jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6,
    "jul": 7, "aug": 8, "sep": 9, "oct": 10, "nov": 11, "dec": 12,
}
_HUMAN_DATE = re.compile(
    r"(\d{1,2})(?:st|nd|rd|th)?\s+(?:of\s+)?([A-Za-z]+),?\s+(\d{4})"
)


def iso_date(human: str) -> str | None:
    """"31st January 2012" -> "2012-01-31"; None when unparseable.

    The introduction blocks carry dates as human text (``DateText``
    elements); the metadata attributes are already ISO.
    """
    match = _HUMAN_DATE.search(human or "")
    if not match:
        return None
    day, month_name, year = match.groups()
    month = _MONTHS.get(month_name[:3].lower())
    if month is None:
        return None
    return f"{int(year):04d}-{month:02d}-{int(day):02d}"
