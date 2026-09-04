"""Task type ``lt_pack``: one bulk package, one request, every entry.

GET ``https://api.lovdata.no/v1/publicData/get/{file}`` — a tar.bz2 whose
members are the gazette entries of Lovtidend Del I, laid out as
``lti/{year}/{nl|sf}-{YYYYMMDD}-{seq}.xml`` (nl = lov/law, sf = sentral
forskrift/central regulation). Each member is one promulgated document as
well-formed XHTML (probed 2026-09-03: 39,143 members across both
packages, zero exceptions — samples archived in the task folder): a
``<dl class="data-document-key-info">`` header carrying the native
metadata plus ``<main class="documentBody">`` with the full text. The
member bytes are stored verbatim as the primary file.

Native fields that shape this handler (dt/dd class names are the field
keys; values are text or ``ul > li`` lists):

- three dates kept apart, never derived from each other: **adoption**
  (the LOV-/FOR- number's date segment — equal to the member's filename
  date in all 39,143 probed entries, asserted here as an integrity
  guard), **publication** (``kunngjort`` — the timeline anchor; date-only
  through ~2008, datetime after, both shapes probed; often 1–11 days
  after adoption), **entry into force** (``dateInForce`` — a plain ISO
  date, or free text such as "Kongen bestemmer" (set by the King, i.e.
  announced separately) in 7,384/39,143 entries, kept raw);
- ``legacyID`` (e.g. LOV-2026-01-23-1) is unique across the whole
  25-year corpus — duplicates inside one package are an unknown shape and
  fail loudly; ``dokid`` (LTI/lov/2026-01-23-1) builds the canonical
  document URL;
- doc_type follows the filename prefix (nl → STATUTE, sf →
  SECONDARY_LEGISLATION): in six corpus entries (2026-09-03 full scan)
  the LOV-/FOR- word of the number contradicts the prefix — e.g.
  sf-20140404-0634.xml titled "Forskrift om…" carrying LOV-2014-04-04-634
  — and in all six the prefix agrees with the document's own title while
  the number word does not; the mismatch is recorded in
  meta.typeConflict instead of failing, and the dokid's type segment
  stays verbatim in meta.nativeType;
- the header vocabulary is wider than any single era shows (corpus
  counts 2026-09-03): appliesTo (27,680), lastupdated (1,922),
  eeaReferences (90 — the native EEA-agreement/EU-act linkage, e.g.
  "EØS-avtalen vedlegg XI nr. 5e (forordning (EU) 2016/679)"),
  numberOfPages (2), note (1) — every known key is captured losslessly;
- revision relations (``changesToDocuments``), legal basis
  (``basedOn``), legal areas and the parliamentary journey inside
  ``miscInformation`` are raw fields into meta — graph building is
  analysis-side work.

An empty package (zero matching members) is an explained empty — e.g. a
current-year package on January 1 before the first promulgation.
"""

from __future__ import annotations

import io
import re
import tarfile
import xml.etree.ElementTree as ET

from adapters.base import FileOut, RequestSpec, Response, TaskResult, TaskView
from core.document import DocumentRecord, compute_doc_id

__all__ = ["LtPackHandler", "map_doc_type"]

_PACK_URL = "https://api.lovdata.no/v1/publicData/get/"

_MEMBER_RE = re.compile(r"^lti/(\d{4})/(nl|sf)-(\d{8})-(\d+)\.xml$")
_LEGACY_RE = re.compile(r"^(LOV|FOR)-(\d{4}-\d{2}-\d{2})-(\d+)$")
_ISO_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")

#: filename prefix -> controlled doc_type. The prefix is the package's own
#: classification and agrees with the document's title in every probed
#: entry, including the six numbering anomalies (see module docstring).
#: Native words always kept in meta; cross-country typology is
#: analysis-side, not collection-side.
_PREFIX_TO_TYPE: dict[str, str] = {
    "nl": "STATUTE",
    "sf": "SECONDARY_LEGISLATION",
}

#: filename prefix -> the dokid type segment it normally accompanies;
#: a mismatch (6/39,143, corpus-scanned 2026-09-03) is recorded, not fatal.
_PREFIX_TO_NATIVE: dict[str, str] = {"nl": "lov", "sf": "forskrift"}

_KNOWN_KEYS = (
    "legacyID",
    "dokid",
    "refid",
    "ministry",
    "subunit",
    "dateInForce",
    "changesToDocuments",
    "basedOn",
    "legalArea",
    "dateOfPublication",
    "journalNumber",
    "a11yStatus",
    "titleShort",
    "title",
    "miscInformation",
    "publishedIn",
    "appliesTo",
    "lastupdated",
    "eeaReferences",
    "numberOfPages",
    "note",
)

_LIST_KEYS = ("ministry", "subunit", "changesToDocuments", "basedOn", "legalArea")


def map_doc_type(prefix: str) -> str:
    return _PREFIX_TO_TYPE.get(prefix.strip(), "OTHER")


def _norm(text: str) -> str:
    return " ".join(text.split())


def _dd_value(dd: ET.Element) -> str:
    """A dd's value: ';'-joined list-item texts when it wraps a ul, else text."""
    items = [li for ul in dd.findall("ul") for li in ul.findall("li")]
    if items:
        return ";".join(_norm("".join(li.itertext())) for li in items if _norm("".join(li.itertext())))
    return _norm("".join(dd.itertext()))


def _header_fields(root: ET.Element, member: str) -> dict[str, str]:
    """The key-info dl as a {dt class: dd value} dict."""
    dl = next(
        (d for d in root.iter("dl") if d.get("class") == "data-document-key-info"),
        None,
    )
    if dl is None:
        raise ValueError(f"{member}: no data-document-key-info header (unknown shape)")
    fields: dict[str, str] = {}
    pending_key: str | None = None
    for child in dl:
        if child.tag == "dt":
            pending_key = child.get("class") or _norm("".join(child.itertext()))
        elif child.tag == "dd" and pending_key:
            value = _dd_value(child)
            if value:
                fields[pending_key] = value
            pending_key = None
    return fields


def _required(fields: dict[str, str], key: str, member: str) -> str:
    value = fields.get(key, "")
    if not value:
        raise ValueError(f"{member}: no {key} in header (unknown shape)")
    return value


def _parse_member(
    member: str, content: bytes, package_file: str
) -> tuple[DocumentRecord, str]:
    """One gazette entry -> (document record, file path). doc_id via caller."""
    match = _MEMBER_RE.match(member)
    if match is None:  # caller filters; defensive double check
        raise ValueError(f"{member}: member name does not match the package layout")
    year_dir, prefix, name_date, _seq = match.groups()

    try:
        root = ET.fromstring(content)
    except ET.ParseError as exc:
        raise ValueError(f"{member}: body is not XML: {exc}") from exc

    fields = _header_fields(root, member)
    legacy_id = _required(fields, "legacyID", member)
    dokid = _required(fields, "dokid", member)
    _required(fields, "refid", member)
    title = _required(fields, "title", member)
    kunngjort = _required(fields, "dateOfPublication", member)

    legacy_match = _LEGACY_RE.match(legacy_id)
    if legacy_match is None:
        raise ValueError(f"{member}: legacyID {legacy_id!r} is not LOV-/FOR- shaped")
    _legacy_word, adoption_date, _legacy_seq = legacy_match.groups()
    if adoption_date != f"{name_date[:4]}-{name_date[4:6]}-{name_date[6:]}":
        raise ValueError(
            f"{member}: filename date {name_date} differs from adoption date "
            f"{adoption_date} in {legacy_id} (probed invariant: always equal)"
        )
    if adoption_date[:4] != year_dir:
        raise ValueError(
            f"{member}: sits in year directory {year_dir} but its number says "
            f"{adoption_date[:4]} (unknown shape)"
        )

    kunngjort_date = kunngjort[:10]
    if not _ISO_DATE_RE.match(kunngjort_date):
        raise ValueError(f"{member}: kunngjort {kunngjort!r} carries no ISO date")

    dokid_parts = dokid.split("/")
    if len(dokid_parts) < 2 or not dokid_parts[-2]:
        raise ValueError(f"{member}: dokid {dokid!r} carries no type segment")
    native_type = dokid_parts[-2]
    # Six corpus entries carry a number whose LOV/FOR word contradicts the
    # prefix and the title; record the conflict, never fail on it.
    type_conflict = (
        None if native_type == _PREFIX_TO_NATIVE[prefix]
        else f"prefix={prefix},dokid={native_type}"
    )

    meta: dict[str, str] = {
        "legacyID": legacy_id,
        "dokid": dokid,
        "refid": fields["refid"],
        "nativeType": native_type,
        "prefix": prefix,
        "kunngjort": kunngjort,
        "adoption_date": adoption_date,
        "package_file": package_file,
        "member_path": member,
        "files": "doc.xml",
    }
    if type_conflict is not None:
        meta["typeConflict"] = type_conflict
    for key in _KNOWN_KEYS:
        if key in fields and key not in ("legacyID", "dokid", "refid", "title", "dateOfPublication"):
            meta[key] = fields[key]
    in_force = fields.get("dateInForce", "")
    if _ISO_DATE_RE.match(in_force):
        meta["in_force_date"] = in_force
    html_lang = root.get("lang") or ""
    if html_lang:
        meta["htmlLang"] = html_lang

    record = DocumentRecord(
        title=title,
        source_url=f"https://lovdata.no/dokument/{dokid}",
        publication_date=kunngjort_date,
        issuing_authority=fields.get("ministry") or None,
        doc_type=map_doc_type(prefix),
        language="nor",
        raw_metadata=meta,
    )
    path = f"01_raw/lovtidende/{year_dir}/{legacy_id}/doc.xml"
    return record, path


class LtPackHandler:
    def build_request(self, task: TaskView) -> RequestSpec:
        return RequestSpec(url=f"{_PACK_URL}{task.params['file']}")

    def parse(self, response: Response, task: TaskView) -> TaskResult:
        package_file = str(task.params["file"])
        try:
            with tarfile.open(fileobj=io.BytesIO(response.content), mode="r:bz2") as tar:
                return self._walk(tar, package_file)
        except tarfile.TarError as exc:  # corrupt or non-tar body, open or mid-stream
            raise ValueError(
                f"package {package_file}: body is not a readable tar.bz2: {exc}"
            ) from exc

    def _walk(self, tar: tarfile.TarFile, package_file: str) -> TaskResult:
        documents: list[DocumentRecord] = []
        files: list[FileOut] = []
        seen: set[str] = set()
        for member in tar:
            if not member.isfile():
                continue
            name = member.name.lstrip("./")
            if _MEMBER_RE.match(name) is None:
                raise ValueError(
                    f"package {package_file}: member {member.name!r} does not match "
                    "the lti/{year}/{nl|sf}-*.xml layout (unknown shape)"
                )
            stream = tar.extractfile(member)
            if stream is None:  # regular files always stream; mypy guard
                raise ValueError(f"{name}: cannot be read from the package")
            content = stream.read()

            record, path = _parse_member(name, content, package_file)
            legacy_id = record.raw_metadata["legacyID"]
            if legacy_id in seen:
                raise ValueError(
                    f"package {package_file}: legacyID {legacy_id} appears twice "
                    "(corpus-wide uniqueness probed; unknown shape)"
                )
            seen.add(legacy_id)

            doc_id = compute_doc_id("NOR", record.source_url, record.publication_date)
            documents.append(record)
            files.append(FileOut(path=path, content=content, doc_id=doc_id))

        if not documents:
            return TaskResult(
                expected_empty=(
                    f"package {package_file} carries no gazette entry "
                    "(a current-year package before the first promulgation looks like this)"
                )
            )
        return TaskResult(documents=documents, files=files)
