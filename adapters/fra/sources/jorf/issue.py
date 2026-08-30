"""Task type ``jorf_issue``: unpack one day's issue archive into documents.

One request = one complete daily issue (the day's earliest tar.gz, probed
2026-08-28: exactly one ``conteneur`` + that issue's texts). The archive is
opened in memory and yields, per ``texte``:

- a ``documents`` row — the TEXTE_VERSION metadata (title, NOR, nature,
  issue number, dates, ministry…) with ``source_url`` built from the stable
  JORFTEXT id;
- a policy folder ``01_raw/jorf/{year}/N{issue}/{id}/`` holding the source
  XMLs verbatim: ``version.xml`` (the document's primary file, carrying the
  doc_id), ``struct.xml`` (article order) and ``articles/*.xml`` (bodies).

Articles find their text through their own ``CONTEXTE/TEXTE @cid`` attribute
(self-contained — no cross-file mapping needed; 204/204 resolved on the
probe day). ``section_ta`` and ``eli`` members are skipped (see the source
doc's boundaries section).
"""

from __future__ import annotations

import html as html_mod
import io
import re
import tarfile

from adapters.base import FileOut, RequestSpec, Response, TaskResult, TaskView
from adapters.fra.sources.jorf import BASE_URL, CURSOR_KEY, USER_AGENT
from core.document import DocumentRecord, compute_doc_id

__all__ = ["JorfIssueHandler"]

_LEGIFRANCE_ID_URL = "https://www.legifrance.gouv.fr/jorf/id/"

#: Everything below ``{ts}/jorf/global/`` inside the daily archives.
_MARKER = "/jorf/global/"

_ID_RE = re.compile(r"<ID>(JORFTEXT\d+)</ID>")
_CID_RE = re.compile(r'<TEXTE cid="(JORFTEXT\d+)"')
_SAFE_NAME_RE = re.compile(r"^[A-Za-z0-9_.\-]+$")

_TAG_CACHE: dict[str, re.Pattern[str]] = {}


def _field(xml: str, tag: str) -> str:
    """Inner text of the first ``<tag>…</tag>`` (probed flat shapes), stripped."""
    pattern = _TAG_CACHE.get(tag)
    if pattern is None:
        pattern = re.compile(rf"<{tag}>(.*?)</{tag}>", re.DOTALL)
        _TAG_CACHE[tag] = pattern
    match = pattern.search(xml)
    return match.group(1).strip() if match else ""


def _plain(raw: str) -> str:
    """Tag-stripped, entity-decoded text (titles carry &amp; / accents)."""
    return html_mod.unescape(re.sub(r"<[^>]+>", "", raw)).strip()


def _issue_folder(num_parution: str, publication_date: str, task_date: str) -> str:
    """Shard segment for the raw tree: the issue number, or the date when an
    old-style issue carries none (observed in the stock archive, not in the
    daily increments)."""
    if num_parution:
        return f"N{num_parution}"
    return "D" + (publication_date or task_date).replace("-", "")


class JorfIssueHandler:
    def build_request(self, task: TaskView) -> RequestSpec:
        return RequestSpec(
            url=f"{BASE_URL}/{task.params['filename']}",
            headers={"User-Agent": USER_AGENT},
        )

    def parse(self, response: Response, task: TaskView) -> TaskResult:
        filename = str(task.params["filename"])

        versions: dict[str, bytes] = {}
        structs: dict[str, bytes] = {}
        articles: dict[str, list[tuple[str, bytes]]] = {}
        try:
            with tarfile.open(fileobj=io.BytesIO(response.content), mode="r:gz") as archive:
                for member in archive.getmembers():
                    if not member.isfile():
                        continue
                    name = member.name
                    marker = name.find(_MARKER)
                    if marker < 0:
                        continue
                    rel = name[marker + len(_MARKER) :]
                    stream = archive.extractfile(member)
                    if stream is None:  # pragma: no cover - odd members
                        continue
                    data = stream.read()

                    if rel.startswith("texte/version/"):
                        match = _ID_RE.search(data.decode("utf-8", errors="replace"))
                        if match:
                            versions[match.group(1)] = data
                    elif rel.startswith("texte/struct/"):
                        match = _ID_RE.search(data.decode("utf-8", errors="replace"))
                        if match:
                            structs[match.group(1)] = data
                    elif rel.startswith("article/"):
                        base = name.rsplit("/", 1)[-1]
                        if not _SAFE_NAME_RE.fullmatch(base):
                            continue
                        match = _CID_RE.search(data.decode("utf-8", errors="replace"))
                        if match:
                            articles.setdefault(match.group(1), []).append((base, data))
                    # conteneur / section_ta / eli members are skipped by design.
        except tarfile.TarError as exc:
            raise ValueError(f"{filename} is not a readable tar.gz: {exc}") from exc

        if not versions:
            return TaskResult(
                expected_empty=f"{filename} holds no texte/version member "
                f"(date {task.params['date']})"
            )

        # Safety net: a real issue archive carries texts published on the
        # task date (81/81 and 101/101 on the probe days). A maintenance
        # diff carries texts of any age but none of the nominal date —
        # register nothing then rather than polluting the window.
        task_date = str(task.params["date"])
        issue_texts = {
            text_id: data
            for text_id, data in versions.items()
            if _field(data.decode("utf-8"), "DATE_PUBLI") == task_date
        }
        if not issue_texts:
            return TaskResult(
                expected_empty=(
                    f"{filename} holds no text published on {task_date} "
                    "(maintenance diff, not an issue archive)"
                )
            )

        documents: list[DocumentRecord] = []
        files: list[FileOut] = []
        for text_id in sorted(issue_texts):
            xml = issue_texts[text_id].decode("utf-8")
            publication_date = _field(xml, "DATE_PUBLI")
            num_parution = _field(xml, "NUM_PARUTION")
            year = (publication_date or task_date)[:4]
            folder = (
                f"01_raw/jorf/{year}/"
                f"{_issue_folder(num_parution, publication_date, task_date)}/{text_id}"
            )

            title = _plain(_field(xml, "TITREFULL")) or _plain(_field(xml, "TITRE"))
            if not title:
                title = text_id
            ministere = _plain(_field(xml, "MINISTERE"))
            autorite = _plain(_field(xml, "AUTORITE"))
            keywords = re.findall(r"<MC>([^<]+)</MC>", xml)

            meta: dict[str, str] = {}
            for key, tag in (
                ("nature", "NATURE"),
                ("num", "NUM"),
                ("nor", "NOR"),
                ("num_sequence", "NUM_SEQUENCE"),
                ("date_texte", "DATE_TEXTE"),
                ("origine_publi", "ORIGINE_PUBLI"),
                ("page_deb_publi", "PAGE_DEB_PUBLI"),
                ("page_fin_publi", "PAGE_FIN_PUBLI"),
                ("titre_court", "TITRE"),
                ("cid", "CID"),
                ("ancien_id", "ANCIEN_ID"),
            ):
                value = _field(xml, tag)
                if value:
                    meta[key] = value
            if num_parution:
                meta["num_parution"] = num_parution
            if ministere:
                meta["ministere"] = ministere
            if autorite:
                meta["autorite"] = autorite
            if keywords:
                meta["mcs"] = ";".join(_plain(k) for k in keywords)

            text_articles = sorted(articles.pop(text_id, []))
            meta["n_articles"] = str(len(text_articles))
            siblings = ["version.xml"]
            source_url = f"{_LEGIFRANCE_ID_URL}{text_id}"
            doc_id = compute_doc_id("FRA", source_url, publication_date or None)
            files.append(
                FileOut(
                    path=f"{folder}/version.xml",
                    content=issue_texts[text_id],
                    doc_id=doc_id,
                )
            )
            if text_id in structs:
                siblings.append("struct.xml")
                files.append(
                    FileOut(path=f"{folder}/struct.xml", content=structs[text_id], doc_id=None)
                )
            for base, data in text_articles:
                siblings.append(f"articles/{base}")
                files.append(FileOut(path=f"{folder}/articles/{base}", content=data))
            meta["files"] = ";".join(siblings)

            documents.append(
                DocumentRecord(
                    title=title,
                    source_url=source_url,
                    publication_date=publication_date or None,
                    issuing_authority=ministere or autorite or None,
                    doc_type="OTHER",
                    language="fra",
                    raw_metadata=meta,
                )
            )

        return TaskResult(
            documents=documents,
            files=files,
            cursor_updates={CURSOR_KEY: task_date},
        )
