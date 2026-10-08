"""arXiv : OAI-PMH arXivRaw (collecte), RSS quotidien (témoin indépendant) et API Atom
(collecte jusqu'au 2026-10-04, parseur conservé pour rejouer les blobs archivés). Parseurs purs.

Pourquoi OAI-PMH (constaté le 2026-10-04) : l'API Atom n'a qu'un filtre de date, submittedDate.
Un filtre `lastUpdatedDate:[…]` est réécrit en silence en submittedDate : les remplacements
d'articles anciens (0/20 dans l'annonce hep-th du 2 octobre) et les annonces tardives
n'étaient jamais collectés, alors que le total annoncé « collait ». En OAI-PMH, la datestamp
d'un enregistrement est la date (UTC) de son annonce ou de sa dernière modification, et
arXivRaw liste toutes ses versions : 35/35 nouveaux, 20/20 cross, 20/20 remplacements.
"""

import re
from datetime import date, datetime
from email.utils import parsedate_to_datetime
from urllib.parse import urlencode

from defusedxml import ElementTree as ET

from ..store import Item

NS = {
    "a": "http://www.w3.org/2005/Atom",
    "os": "http://a9.com/-/spec/opensearch/1.1/",
    "arxiv": "http://arxiv.org/schemas/atom",
    "o": "http://www.openarchives.org/OAI/2.0/",
    "r": "http://arxiv.org/OAI/arXivRaw/",
}
OAI = "https://oaipmh.arxiv.org/oai"
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


def oai_url(set_spec: str, since: date, until: date, token: str | None = None) -> str:
    """ListRecords arXivRaw sur des jours de datestamp CLOS, bornes incluses (UTC).

    Le resumptionToken est opaque : on le ré-encode comme toute valeur de paramètre
    (vérifié le 2026-10-04 : encodé ou brut, le serveur rend la même page).
    """
    if token:
        return OAI + "?" + urlencode({"verb": "ListRecords", "resumptionToken": token})
    return OAI + "?" + urlencode({"verb": "ListRecords", "metadataPrefix": "arXivRaw",
                                  "set": set_spec, "from": since.isoformat(),
                                  "until": until.isoformat()})


def _rfc822_iso(s: str) -> str:
    """'Thu, 01 Oct 2026 09:23:39 GMT' -> '2026-10-01T09:23:39Z' (format des dates de l'API)."""
    try:
        return parsedate_to_datetime(s).strftime("%Y-%m-%dT%H:%M:%SZ")
    except (TypeError, ValueError) as e:
        raise ArxivError(f"date de version illisible : {s!r}") from e


def parse_oai(raw: bytes) -> tuple[list[Item], str | None, int]:
    """Une page ListRecords -> (éléments, resumptionToken ou None, nombre d'enregistrements).

    Un élément par VERSION listée (clé id+version) : une v2 annoncée puis dépassée par une v3
    avant notre passage reste ainsi archivée. Les enregistrements supprimés sont comptés mais
    ne produisent aucun élément.
    """
    root = ET.fromstring(raw)
    err = root.find("o:error", NS)
    if err is not None:
        if err.get("code") == "noRecordsMatch":   # jour sans annonce (week-end, férié)
            return [], None, 0
        raise ArxivError(f"erreur OAI-PMH {err.get('code')} : {' '.join((err.text or '').split())}")
    lr = root.find("o:ListRecords", NS)
    if lr is None:
        raise ArxivError("ListRecords absent : réponse OAI-PMH non conforme")
    items, n = [], 0
    for rec in lr.findall("o:record", NS):
        n += 1
        header = rec.find("o:header", NS)
        if header is None or header.get("status") == "deleted":
            continue
        md = rec.find("o:metadata/r:arXivRaw", NS)
        if md is None:
            raise ArxivError(f"arXivRaw absent : {header.findtext('o:identifier', '', NS)}")
        item_id = " ".join((md.findtext("r:id", "", NS)).split()).lower()
        if not item_id:
            raise ArxivError("enregistrement sans <id>")
        versions = [((v.get("version") or "").lower(), _rfc822_iso(v.findtext("r:date", "", NS)))
                    for v in md.findall("r:version", NS)]
        if not versions or not all(re.fullmatch(r"v\d+", v) for v, _ in versions):
            raise ArxivError(f"versions illisibles pour {item_id} : {versions}")
        cats = (md.findtext("r:categories", "", NS)).split()
        meta = {
            # Primaire = première de <categories> : non spécifié, mais identique au
            # primary_category de l'API pour 315/315 identifiants communs (2026-10-04).
            "primary": cats[0] if cats else "",
            "categories": sorted(set(cats)),
            "authors": " ".join((md.findtext("r:authors", "", NS)).split()),
            "doi": " ".join((md.findtext("r:doi", "", NS)).split()),
            "journal_ref": " ".join((md.findtext("r:journal-ref", "", NS)).split()),
            "datestamp": header.findtext("o:datestamp", "", NS).strip(),
        }
        title = " ".join((md.findtext("r:title", "", NS)).split())
        for v, when in versions:
            items.append(Item(source="arxiv", item_id=item_id, version=v, title=title,
                              published=versions[0][1], updated=when, meta=meta))
    tok = lr.find("o:resumptionToken", NS)
    token = (tok.text or "").strip() if tok is not None else ""
    return items, token or None, n


def _text(el, path):
    x = el.find(path, NS)
    return " ".join((x.text or "").split()) if x is not None else ""


def parse_api(raw: bytes) -> tuple[list[Item], int]:
    """Ancienne collecte (API Atom). Ne sert plus qu'au rejeu des blobs `arxiv_api` archivés."""
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
