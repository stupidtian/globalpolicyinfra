"""Task type ``nn_index``: one year's inventory CSV, one request.

``GET /get_index_file.aspx?year={Y}&type=csv`` — the source's own
"Popis svih propisa" (list of all regulations) export, tab-separated
UTF-8 with a BOM, one row per gazette item:

    Izdanje            issue label, e.g. "NN 124/2026"
    Broj dokumenta     global item ordinal (continuous across years)
    Naziv dokumenta    title
    Vrsta dokumenta    native type (zakon, uredba, odluka, presuda, ...)
    Podvrsta ...       subtype (when the type is "ostalo"), else "-"
    Cjeloviti ...      relation marker: cjeloviti akt / izmjene /
                       dopune / ukidanje / ispravak (kept verbatim —
                       section 5.3 collects amendment fields, builds
                       no graph)
    Donositelj ...     issuing authority
    Poveznica          canonical ELI link

Probed 2026-11-01: the CSV exists for every archive year 1990+,
a year outside the archive answers 404 (permanent — correct, the
adapter's seed validation already rejects such years), and the export
always covers the Službeni dio only (kategorija-style parameters are
ignored). An inventory that parses but has zero rows — or an
issues-window that keeps zero rows — is a loud error: a published year
always has items, so emptiness can only be a shape change or a
misconfigured window, never a legitimate empty partition.
"""

from __future__ import annotations

import csv
import io
import re

from adapters.base import RequestSpec, Response, TaskResult, TaskSeed, TaskView
from adapters.hrv.sources.nn import (
    API_BASE,
    is_court_issuer,
    site_url_for,
)

__all__ = ["REQUIRED_COLUMNS", "IndexHandler"]

_ISSUE_RE = re.compile(r"^NN\s+(\d+)/(\d{4})$")

REQUIRED_COLUMNS = (
    "Izdanje",
    "Broj dokumenta",
    "Naziv dokumenta",
    "Vrsta dokumenta",
    "Podvrsta dokumenta (ako je dokument razvrstan u vrstu ostalo)",
    "Cjeloviti dokument/izmjene/dopune/ukinut",
    "Donositelj dokumenta",
    "Poveznica",
)


class IndexHandler:
    def build_request(self, task: TaskView) -> RequestSpec:
        return RequestSpec(
            url=f"{API_BASE}/get_index_file.aspx",
            params={"year": str(task.params["year"]), "type": "csv"},
        )

    def parse(self, response: Response, task: TaskView) -> TaskResult:
        year = int(task.params["year"])
        scope = str(task.params.get("scope", "policy"))
        label = f"nn_index {year}"

        try:
            text = response.content.decode("utf-8-sig")
        except UnicodeDecodeError as exc:
            raise ValueError(f"{label}: inventory is not UTF-8: {exc}") from exc

        reader = csv.DictReader(io.StringIO(text), delimiter="\t")
        fieldnames = [name.strip() for name in (reader.fieldnames or [])]
        missing = [name for name in REQUIRED_COLUMNS if name not in fieldnames]
        if missing:
            raise ValueError(
                f"{label}: inventory columns {missing} missing "
                f"(got {fieldnames}) — export shape may have changed"
            )

        issues_param = str(task.params.get("issues", "")).strip()
        issues_window: tuple[int, int] | None = None
        if issues_param:
            lo, _, hi = issues_param.partition(":")
            issues_window = (int(lo), int(hi))

        seeds: list[TaskSeed] = []
        for row in reader:
            issue_label = (row.get("Izdanje") or "").strip()
            match = _ISSUE_RE.match(issue_label)  # \s in the pattern already tolerates NBSP padding
            if match is None:
                raise ValueError(
                    f"{label}: unparseable issue label {issue_label!r} — "
                    "inventory shape may have changed"
                )
            issue_no, label_year = int(match.group(1)), int(match.group(2))
            if label_year != year:
                raise ValueError(
                    f"{label}: row of issue {issue_label!r} inside the "
                    f"{year} export — cross-year row is an explained shape"
                )
            raw_ordinal = (row.get("Broj dokumenta") or "").strip()
            try:
                ordinal = int(raw_ordinal)
            except ValueError:
                raise ValueError(
                    f"{label}: unparseable item ordinal {raw_ordinal!r}"
                ) from None
            link = (row.get("Poveznica") or "").strip()
            expected_link = site_url_for(year, issue_no, ordinal)
            if link != expected_link:
                raise ValueError(
                    f"{label}: link column {link!r} does not match the "
                    f"ELI form {expected_link!r} — identity basis drift"
                )
            if issues_window is not None and not (
                issues_window[0] <= issue_no <= issues_window[1]
            ):
                continue
            issuer = (row.get("Donositelj dokumenta") or "").strip()
            if scope == "policy" and is_court_issuer(issuer):
                continue

            native_type = (row.get("Vrsta dokumenta") or "").strip()
            subtype = (row.get("Podvrsta dokumenta (ako je dokument razvrstan u vrstu ostalo)") or "").strip()
            relation = (row.get("Cjeloviti dokument/izmjene/dopune/ukinut") or "").strip()
            title = (row.get("Naziv dokumenta") or "").strip()
            seeds.append(
                TaskSeed(
                    type="nn_doc",
                    params={
                        "year": year,
                        "issue": issue_no,
                        "art": ordinal,
                        "title": title,
                        "native_type": native_type,
                        "subtype": subtype,
                        "relation": relation,
                        "issuer": issuer,
                    },
                )
            )

        if not seeds:
            if issues_window is not None:
                raise ValueError(
                    f"{label}: issues window {issues_param} kept zero rows of "
                    f"the {year} inventory — misconfigured window"
                )
            raise ValueError(
                f"{label}: inventory parsed but kept zero rows — a published "
                "year always has items; export shape may have changed"
            )
        return TaskResult(next_tasks=seeds)
