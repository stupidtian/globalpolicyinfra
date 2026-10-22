"""Task type ``rg_item``: one gazette item, one request, one document.

GET the item's own file under ``/eskiler/`` and store the response bytes
verbatim as the document's primary file. Three probed forms:

- **htm** (per-item era) — a Word-exported HTML in the **Windows-1254**
  code page. Its header block repeats the issue date, ``Sayı : 33382``,
  the native type word, the issuing authority line (``Ticaret
  Bakanlığından:``) and an uppercase title. The block enriches the record
  (authority is otherwise unavailable) and cross-checks the seed: a
  mismatching issue number means the wrong file came back and fails
  loudly. A headerless htm is tolerated (old-era shapes) — the seed's
  fields stand.
- **pdf** (per-item era) — the original typeset. No metadata inside;
  every bibliographic field comes from the seed. The bytes must start
  with ``%PDF-``; an html body under a ``.pdf`` name is the source lying
  and fails loudly (the sibling mevzuat file endpoint is known to answer
  200+html for missing files, so the magic check is deliberate).
- **dayfile mode** (anchor era, 2000-06-28…2004-12; user-ruled
  2026-09-28) — the whole day's items share ONE file addressed by
  ``<a name=…>`` anchors (fihrist links ``…/20021114.htm#13``). One
  request per day; parse slices the file at the anchor markers into
  **contiguous byte ranges** (zero re-encoding), producing one document
  row + one slice file per fihrist entry plus the unsliced day file
  stored once as the raw-bytes voucher (no doc_id — path recorded in
  every entry's meta). Entry identity = the site's own fragment URL
  (``…htm#13``); the rare shared anchor (two fihrist entries pointing at
  the same section, probed 1-in-27 on 2002-11-14) gets an occurrence
  suffix (``…htm#13-2``) so the two rows keep distinct doc_ids — the
  framework's INSERT OR IGNORE would otherwise fold them into one.
  Missing markers, duplicate marker names or a mismatching issue number
  in the day file's masthead all fail loudly.

The title always comes from the fihrist anchor text (readable mixed
case, uniform across forms); the htm header's uppercase title is kept in
meta as ``native_title`` when parseable. Document reference numbers are
scraped from the title with two conservative patterns only (a leading
``2014/7021`` BKK number and an explicit ``Karar Sayısı: 11752``);
anything else stays unparsed for the analysis side.
"""

from __future__ import annotations

import re
from typing import Any

from adapters.base import FileOut, RequestSpec, Response, TaskResult, TaskSeed, TaskView
from adapters.tur.sources.resmigazete import API_BASE
from adapters.tur.sources.resmigazete.day import _ITEM_FILE_RE
from core.document import DocumentRecord, compute_doc_id

__all__ = ["RgItemHandler", "dayfile_url", "map_doc_type"]

_PDF_MAGIC = b"%PDF-"

#: anchor-era marker tag: ``<a name="13">`` opens each entry's slice inside
#: the whole-day file (names are ASCII, so the byte-level regex is safe on
#: the Windows-1254 payload; probed 2026-09-28, sample 20021114.htm — and
#: UPPERCASE ``<A NAME=…>`` spelling occurs, probed 2000-07-06/11).
_MARKER_RE = re.compile(rb'<a[^>]*name=["\']?([A-Za-z0-9_.]+)["\']?[^>]*>', re.IGNORECASE)

_TYPE_TO_DOC_TYPE: dict[str, str] = {
    "KANUNLAR": "STATUTE",
    "KANUN": "STATUTE",
    "KANUN HÜKMÜNDE KARARNAMELER": "DECREE",
    "KANUN HÜKMÜNDE KARARNAME": "DECREE",
    "CUMHURBAŞKANLIĞI KARARNAMELERİ": "DECREE",
    "CUMHURBAŞKANLIĞI KARARNAMESİ": "DECREE",
    "CUMHURBAŞKANI KARARLARI": "DECREE",
    "CUMHURBAŞKANI KARARI": "DECREE",
    "BAKANLAR KURULU KARARLARI": "DECREE",
    "BAKANLAR KURULU KARARI": "DECREE",
    "TÜZÜKLER": "REGULATION",
    "TÜZÜK": "REGULATION",
    "YÖNETMELİKLER": "REGULATION",
    "YÖNETMELİK": "REGULATION",
    "TEBLİĞLER": "ORDER",
    "TEBLİĞ": "ORDER",
}


def _fold(text: str) -> str:
    """Upper-case fold tolerating dotted/diacritic drift (İ/I, Â/A …)."""
    table = str.maketrans("çğıöşüÇĞİÖŞÜâÂ", "cgiosuCGIOSUaA")
    return text.translate(table).upper()


def map_doc_type(native_type: str) -> str:
    """Native type word → controlled doc_type (native always kept in meta;
    cross-country typology is analysis-side, not collection-side)."""
    folded = _fold(native_type)
    for key, value in _TYPE_TO_DOC_TYPE.items():
        if _fold(key) == folded:
            return value
    return "OTHER"


def dayfile_url(date_iso: str, mukerrer: int) -> str:
    """The whole-day file of the anchor era (probed shape:
    ``/eskiler/2002/11/20021114.htm``; a mükerrer day would carry ``M{k}``)."""
    ymd = date_iso.replace("-", "")
    mark = f"M{mukerrer}" if mukerrer > 0 else ""
    return f"{API_BASE}/eskiler/{ymd[:4]}/{ymd[4:6]}/{ymd}{mark}.htm"


_BKK_NO_RE = re.compile(r"^(\d{4}/\d+)\s")
_KARAR_NO_RE = re.compile(r"Karar Say[ıi]s[ıi]\s*:\s*(\d+)")
#: a *gazette-issue* Sayı line — 5-6 bare digits. 2005-era files carry no
#: gazette masthead; their "Sayı: 2005/1" lines are the document's own
#: reference number and must not feed the cross-check (probed sample 43).
_GAZETTE_SAYI_RE = re.compile(r"Say[ıi]\s*:\s*(\d{5,6})(?!\d)")
_CHARSET_RE = re.compile(rb'charset=["\']?([\w-]+)', re.IGNORECASE)
_TAG_RE = re.compile(r"<[^>]+>")


def _sniff_charset(raw: bytes) -> str:
    match = _CHARSET_RE.search(raw[:4000])
    if match:
        codec = match.group(1).decode("ascii", errors="replace").lower()
        if codec == "windows-1254" or codec == "cp1254":
            return "cp1254"
        return codec
    return "cp1254"  # probed default for gazette htm items


def _plain_lines(raw: bytes) -> list[str]:
    html = raw.decode(_sniff_charset(raw), errors="replace")
    body = re.sub(r"<(script|style)[^>]*>.*?</\1>", " ", html, flags=re.DOTALL)
    text = _TAG_RE.sub("\n", body)
    text = text.replace("&nbsp;", " ")
    lines = [re.sub(r"\s+", " ", line).strip() for line in text.split("\n")]
    return [line for line in lines if line]


def _header_lines(lines: list[str]) -> dict[str, str]:
    """Read the htm header block. Gazette-masthead files (probed 2026
    shape): the ``Sayı : 33382`` line anchors type → authority: → title.
    Masthead-less 2005-era files: no gazette Sayı exists — the authority
    is a ':'-ending line near the top (probed sample 43: "Türkiye
    Cumhuriyet Merkez Bankasından:")."""
    out: dict[str, str] = {}
    for i, line in enumerate(lines):
        if i > 12:
            # the gazette masthead sits at the top; deeper "Sayı : 19400"
            # lines are court-decision reference numbers, not issues
            break
        sayi = _GAZETTE_SAYI_RE.search(line)
        if not sayi:
            continue
        out["sayi"] = sayi.group(1)
        rest = lines[i + 1 : i + 9]
        for j, line_j in enumerate(rest):
            if line_j.endswith(":") and len(line_j) > 3:
                out["authority"] = line_j[:-1].strip()
                title_parts = []
                for line_k in rest[j + 1 :]:
                    if line_k.startswith(("MADDE", "Amaç", "BİRİNCİ", "GENEL", "I.")):
                        break
                    if line_k.upper() == line_k and len(line_k) > 3:
                        title_parts.append(line_k)
                    elif title_parts:
                        break
                if title_parts:
                    out["native_title"] = " ".join(title_parts)
                break
            if line_j.upper() == line_j and len(line_j) > 2 and "native_type" not in out:
                out["native_type"] = line_j
        break
    if "sayi" not in out:
        # masthead-less files (2005-era): the authority is a ':'-ending line
        # near the top, past the Word metadata junk (probed sample 43 —
        # junk lines never end with ':', so the filter alone is safe). The
        # name itself may wrap: a single-word ':'-ending line joins its
        # predecessor ("Türkiye Cumhuriyet Merkez" + "Bankasından:").
        for idx in range(min(25, len(lines))):
            line = lines[idx]
            if not line.endswith(":") or not 3 < len(line) < 80 or line.startswith(
                ("Sayı", "Karar", "Tarih", "No", "Kuruluş")
            ):
                continue
            authority = line[:-1].strip()
            if (
                " " not in authority
                and idx > 0
                and lines[idx - 1]
                and not lines[idx - 1].endswith(":")
                and len(lines[idx - 1]) > 3
            ):
                authority = f"{lines[idx - 1]} {authority}"
            out["authority"] = authority
            break
    return out


def _marker_sections(raw: bytes) -> dict[str, tuple[int, int]]:
    """name → (start, end) byte range of the slice opened by its ``<a
    name=…>`` marker, bounded by the next marker of any name (probed:
    marker order in the file is NOT numeric — 1, 25, 2, 26, … — ranges are
    positional, addressing is by name). Word-export artifacts re-emit the
    same bookmark several times (probed 2001-08-01: '11' thrice, plus
    OLE_LINK/RANGE internals): every occurrence still bounds its
    predecessor, and the FIRST occurrence owns the named section — never
    an error."""
    markers = [(m.group(1).decode("ascii"), m.start()) for m in _MARKER_RE.finditer(raw)]
    sections: dict[str, tuple[int, int]] = {}
    for idx, (name, start) in enumerate(markers):
        end = markers[idx + 1][1] if idx + 1 < len(markers) else len(raw)
        sections.setdefault(name, (start, end))
    return sections


def _section_for(
    sections: dict[str, tuple[int, int]], anchor: str
) -> tuple[str, tuple[int, int]] | None:
    """Resolve an entry's anchor. Numeric anchors fall back to the nearest
    preceding numeric marker when the source dropped one (probed
    2001-11-14: marker 7 absent from a 1…15 day — the entry's text sits
    inside the previous section, the same sharing shape as the probed
    double-listed anchors). Non-numeric anchors (probed ``T.C.`` opening
    2001-03-23) resolve exactly or fail. Returns the key actually used plus
    its range; None when no resolution exists."""
    if anchor in sections:
        return anchor, sections[anchor]
    if not anchor.isdigit():
        return None
    prev = int(anchor) - 1
    while prev >= 1:
        if str(prev) in sections:
            return str(prev), sections[str(prev)]
        prev -= 1
    return None


def _slice_header(slice_bytes: bytes) -> tuple[str | None, str | None]:
    """The entry's own head lines inside a day-file slice: the authority
    line sits immediately after the anchor marker ("Devlet Bakanlığından :",
    probed 2026-10-08 on 20021114.htm markers 3/5), the native title in the
    next centered block — mixed case in this era, unlike the per-item
    era's uppercase heads. Image-only slices (kadro decisions embedded as
    scanned GIFs, probed marker 2) carry neither → (None, None)."""
    lines = _plain_lines(slice_bytes)
    if not lines or not lines[0].endswith(":") or not 3 < len(lines[0]) < 80:
        return None, None
    authority = lines[0][:-1].strip()
    native_title = None
    if len(lines) > 1 and len(lines[1]) > 15:
        native_title = lines[1]
    return authority, native_title



def _alt_mark_form(name: str, mukerrer: int) -> str:
    """Toggle the mükerrer mark of a numbered file name (insert M{k} or
    strip it) — the other candidate address of an ambiguous item."""
    m = _ITEM_FILE_RE.fullmatch(name)
    if m is None:
        return name
    ymd, mark, seq, part, ext = m.groups()
    if mark:
        new_mark = ""
    else:
        new_mark = f"M{mukerrer}"
    return f"{ymd}{new_mark}-{seq}{'-' + part if part else ''}.{ext}"


class RgItemHandler:
    def build_request(self, task: TaskView) -> RequestSpec:
        if task.params.get("mode") == "dayfile":
            return RequestSpec(
                url=dayfile_url(str(task.params["date"]), int(task.params.get("mukerrer", 0)))
            )
        params = task.params
        if params.get("rel"):
            # unmarked-on-mükerrer links are ambiguous (the probed tail has
            # BOTH kinds: some days' marked file exists, some days' literal
            # unmarked one does) — a 404 on the first form chains to the
            # other (§ one request per task kept; loop capped by alt_tried)
            eligible = (
                int(params.get("mukerrer", 0)) > 0
                and not params.get("alt_tried")
            )
            return RequestSpec(url=f"{API_BASE}/{params['rel']}", accept_not_found=eligible)
        if params.get("name"):
            name = str(params["name"])
        else:  # legacy seeds: reconstruct the canonical name
            mukerrer = int(params.get("mukerrer", 0))
            mark = f"M{mukerrer}" if mukerrer > 0 else ""
            ymd = str(params["date"]).replace("-", "")
            name = f"{ymd}{mark}-{int(params['seq'])}.{str(params['ext']).lower()}"
        return RequestSpec(url=f"{API_BASE}/eskiler/{name[:4]}/{name[4:6]}/{name}")

    def parse(self, response: Response, task: TaskView) -> TaskResult:
        if task.params.get("mode") == "dayfile":
            return self._parse_dayfile(response, task)
        return self._parse_item(response, task)

    # -- anchor era: one fetch per day, sliced per entry --------------------------

    def _parse_dayfile(self, response: Response, task: TaskView) -> TaskResult:
        params = task.params
        date = str(params["date"])
        mukerrer = int(params.get("mukerrer", 0))
        sayi = str(params["sayi"])
        entries: list[dict[str, Any]] = list(params["entries"])
        raw = response.content

        sections = _marker_sections(raw)
        if not sections:
            raise ValueError(
                f"rg_item dayfile {date}: no anchor markers in the day file "
                f"({len(raw)} bytes) — not the known anchor-era shape"
            )

        # masthead cross-check (soft-locate: only enforced when present)
        head_text = raw[:4000].decode(_sniff_charset(raw), errors="replace")
        head_sayi = _GAZETTE_SAYI_RE.search(re.sub(r"\s+", " ", _TAG_RE.sub(" ", head_text)))
        if head_sayi and head_sayi.group(1) != sayi:
            raise ValueError(
                f"rg_item dayfile {date}: masthead says issue "
                f"{head_sayi.group(1)}, seed says {sayi}"
            )

        ymd = date.replace("-", "")
        mark = f"M{mukerrer}" if mukerrer > 0 else ""
        day_name = f"{ymd}{mark}.htm"
        day_path = f"01_raw/resmigazete/{ymd[:4]}/D{ymd}/{day_name}"
        base_url = dayfile_url(date, mukerrer)

        documents: list[DocumentRecord] = []
        files: list[FileOut] = [FileOut(path=day_path, content=raw)]
        seen_anchor: dict[str, int] = {}
        last_resolved: tuple[str, tuple[int, int]] | None = None
        for entry in entries:
            ordinal = int(entry["i"])
            anchor = str(entry["k"])
            title = str(entry["title"])
            bolum = str(entry.get("bolum", "") or "")
            tip = str(entry.get("tip", "") or "")
            if str(entry.get("ext", "htm")).lower() != "htm":
                raise ValueError(
                    f"rg_item dayfile {date}: entry #{ordinal} claims a ."
                    f"{entry['ext']} slice — only the htm day file was probed"
                )
            resolved = _section_for(sections, anchor)
            if resolved is None and last_resolved is not None and not anchor.isdigit():
                # footnote-addressed rows (probed _ftn7 on 2005-04-18):
                # footnotes ride at section bottoms — use the last resolved
                # section rather than dropping the entry or failing the day
                resolved = last_resolved
            if resolved is None:
                raise ValueError(
                    f"rg_item dayfile {date}: fihrist entry #{ordinal} addresses "
                    f"anchor {anchor}, absent from the day file with no preceding "
                    f"fallback (markers: {sorted(sections)[:10]}…)"
                )
            section_key, (start, end) = resolved
            last_resolved = resolved
            slice_bytes = raw[start:end]
            authority, native_title = _slice_header(slice_bytes)

            occurrence = seen_anchor.get(anchor, 0) + 1
            seen_anchor[anchor] = occurrence
            fragment = str(anchor) if occurrence == 1 else f"{anchor}-{occurrence}"

            slice_name = f"{ymd}{mark}-{ordinal}.htm"
            meta: dict[str, str] = {
                "sayi": sayi,
                "seq": str(ordinal),
                "anchor": str(anchor),
                "day_file": day_name,
            }
            if occurrence > 1:
                meta["anchor_occurrence"] = str(occurrence)
            if section_key != str(anchor):
                meta["anchor_fallback"] = f"{anchor}->{section_key}"
            if mukerrer > 0:
                meta["mukerrer"] = str(mukerrer)
            if bolum:
                meta["bolum"] = bolum
            if tip:
                meta["native_type"] = tip
            if native_title:
                meta["native_title"] = native_title
            bkk = _BKK_NO_RE.search(title)
            if bkk:
                meta["kanun_karar_no"] = bkk.group(1)
            karar = _KARAR_NO_RE.search(title)
            if karar:
                meta["kanun_karar_no"] = karar.group(1)
            meta["files"] = slice_name

            source_url = f"{base_url}#{fragment}"
            documents.append(
                DocumentRecord(
                    title=title,
                    source_url=source_url,
                    publication_date=date,
                    issuing_authority=authority,
                    doc_type=map_doc_type(tip),
                    language="tur",
                    raw_metadata=meta,
                )
            )
            files.append(
                FileOut(
                    path=f"01_raw/resmigazete/{ymd[:4]}/D{ymd}/{slice_name}",
                    content=slice_bytes,
                    doc_id=compute_doc_id("TUR", source_url, date),
                )
            )
        return TaskResult(documents=documents, files=files)

    # -- per-item era (2005-01…) ---------------------------------------------------

    def _parse_item(self, response: Response, task: TaskView) -> TaskResult:
        params = task.params
        if response.status_code in (404, 410) and not params.get("alt_tried"):
            mukerrer = int(params.get("mukerrer", 0))
            if mukerrer > 0:
                rel = str(params.get("rel") or "")
                name = rel.rsplit("/", 1)[-1]
                alt = _alt_mark_form(name, mukerrer)
                alt_params = dict(params)
                alt_params["name"] = alt
                alt_params["rel"] = rel.rsplit("/", 1)[0] + "/" + alt
                alt_params["siblings"] = [
                    _alt_mark_form(n, mukerrer) for n in params.get("siblings", [])
                ]
                alt_params["alt_tried"] = True
                return TaskResult(
                    expected_empty=(
                        f"rg_item {params['date']} M{mukerrer}: {name} answers "
                        f"{response.status_code} — chaining to the {alt} form"
                    ),
                    next_tasks=[TaskSeed(type="rg_item", params=alt_params)],
                )
        date = str(params["date"])
        mukerrer = int(params.get("mukerrer", 0))
        seq = int(params["seq"])
        ext = str(params["ext"]).lower()
        title = str(params["title"])
        sayi = str(params["sayi"])
        bolum = str(params.get("bolum", ""))
        tip = str(params.get("tip", ""))
        # literal file name (widened attachment model); legacy seeds without
        # one reconstruct the canonical name — identical URL to before
        ymd = date.replace("-", "")
        if params.get("name"):
            name = str(params["name"])
        else:
            mark = f"M{mukerrer}" if mukerrer > 0 else ""
            name = f"{ymd}{mark}-{seq}.{ext}"
        siblings = [str(n) for n in params.get("siblings", [])]

        is_pdf = ext == "pdf"
        if is_pdf != response.content.startswith(_PDF_MAGIC):
            raise ValueError(
                f"rg_item {date} M{mukerrer}-{seq}: body does not match the "
                f"addressed .{ext} form "
                f"(magic={response.content[:8]!r}, {len(response.content)} bytes)"
            )

        authority: str | None = None
        meta: dict[str, str] = {"sayi": sayi, "seq": str(seq)}
        if mukerrer > 0:
            meta["mukerrer"] = str(mukerrer)
        if bolum:
            meta["bolum"] = bolum
        if tip:
            meta["native_type"] = tip
        bkk = _BKK_NO_RE.search(title)
        if bkk:
            meta["kanun_karar_no"] = bkk.group(1)
        karar = _KARAR_NO_RE.search(title)
        if karar:
            meta["kanun_karar_no"] = karar.group(1)

        # header enrichment only for the html family; doc/xls/gif attachments
        # carry no machine-readable header
        if ext in ("htm", "html"):
            header = _header_lines(_plain_lines(response.content))
            if header.get("sayi") and header["sayi"] != sayi:
                raise ValueError(
                    f"rg_item {date} M{mukerrer}-{seq}: file header says issue "
                    f"{header['sayi']}, seed says {sayi}"
                )
            if header.get("authority"):
                authority = header["authority"]
            if header.get("native_title"):
                meta["native_title"] = header["native_title"]
            if header.get("native_type") and not tip:
                meta["native_type"] = header["native_type"]

        rel = str(params.get("rel") or f"eskiler/{ymd[:4]}/{ymd[4:6]}/{name}")
        if rel.startswith("eskiler/"):
            path = f"01_raw/resmigazete/{ymd[:4]}/D{ymd}/{name}"
        else:  # İLÂN category files (scope=all): keep their own directory
            path = f"01_raw/resmigazete/{rel}"
        meta["files"] = name
        if siblings:
            meta["sibling_files"] = ";".join(siblings)  # recorded, not fetched

        source_url = f"{API_BASE}/{rel}"
        document = DocumentRecord(
            title=title,
            source_url=source_url,
            publication_date=date,
            issuing_authority=authority,
            doc_type=map_doc_type(tip),
            language="tur",
            raw_metadata=meta,
        )
        doc_id = compute_doc_id("TUR", source_url, date)
        return TaskResult(
            documents=[document],
            files=[FileOut(path=path, content=response.content, doc_id=doc_id)],
        )
