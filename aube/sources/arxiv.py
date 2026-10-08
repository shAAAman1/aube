"""arXiv : API Atom (collecte) et RSS quotidien (témoin indépendant). Parseurs purs."""

import re
from datetime import datetime
from urllib.parse import urlencode

from defusedxml import ElementTree as ET

from ..store import Item

NS = {
    "a": "http://www.w3.org/2005/Atom",
    "os": "http://a9.com/-/spec/opensearch/1.1/",
    "arxiv": "http://arxiv.org/schemas/atom",
}
API = "https://export.arxiv.org/api/query"
RSS = "https://rss.arxiv.org/rss/{cat}"

_ID_RE = re.compile(r"(?:abs/|arXiv\.org:|arXiv:)([a-z\-\.]+/\d{7}|\d{4}\.\d{4,5})(v\d+)?", re.I)


class ArxivError(Exception):
    pass


def split_id(s: str) -> tuple[str, str]:
    """'http://arxiv.org/abs/2610.01234v2' -> ('2610.01234', 'v2'). Version '' si absente."""
    m = _ID_RE.search(s or "")
    if not m:
        raise ArxivError(f"identifiant arXiv illisible : {s!r}")
    return m.group(1).lower(), (m.group(2) or "").lower()


def _fmt(dt: datetime) -> str:
    return dt.strftime("%Y%m%d%H%M")


def api_url(cat: str, since: datetime, until: datetime, start: int, size: int) -> str:
    # La borne 'until' est figée dans la requête : le total ne bouge pas pendant la pagination.
    q = f"cat:{cat} AND lastUpdatedDate:[{_fmt(since)} TO {_fmt(until)}]"
    return API + "?" + urlencode({
        "search_query": q, "start": start, "max_results": size,
        "sortBy": "lastUpdatedDate", "sortOrder": "ascending",
    })


def _text(el, path):
    x = el.find(path, NS)
    return " ".join((x.text or "").split()) if x is not None else ""


def parse_api(raw: bytes) -> tuple[list[Item], int]:
    root = ET.fromstring(raw)
    total_el = root.find("os:totalResults", NS)
    if total_el is None:
        raise ArxivError("totalResults absent : réponse non conforme")
    total = int(total_el.text)
    items = []
    for e in root.findall("a:entry", NS):
        eid = _text(e, "a:id")
        if "api/errors" in eid:
            raise ArxivError(f"erreur API arXiv : {_text(e, 'a:summary')}")
        item_id, version = split_id(eid)
        prim = e.find("arxiv:primary_category", NS)
        items.append(Item(
            source="arxiv", item_id=item_id, version=version,
            title=_text(e, "a:title"),
            published=_text(e, "a:published"), updated=_text(e, "a:updated"),
            meta={
                "primary": prim.get("term") if prim is not None else "",
                "categories": sorted({c.get("term") for c in e.findall("a:category", NS)}),
                "authors": [_text(a, "a:name") for a in e.findall("a:author", NS)],
                "doi": _text(e, "arxiv:doi"),
                "journal_ref": _text(e, "arxiv:journal_ref"),
            }))
    return items, total


def parse_rss(raw: bytes) -> list[tuple[str, str, str]]:
    """Témoin : [(item_id, version, announce_type)] annoncés ce jour-là."""
    root = ET.fromstring(raw)
    out = []
    for it in root.iter("item"):
        guid = (it.findtext("guid") or "").strip()
        desc = it.findtext("description") or ""
        atype = (it.findtext("arxiv:announce_type", namespaces=NS) or "").strip()
        try:
            item_id, version = split_id(guid)
        except ArxivError:
            item_id, version = split_id(desc[:200])
        if not version:  # certains guid omettent la version, la description la donne
            try:
                _, v2 = split_id(desc[:200])
                version = v2
            except ArxivError:
                pass
        out.append((item_id, version, atype))
    return out
