"""Actualités du CERN (RSS 2.0 ou Atom). Parseur pur.

Un flux d'actualités ne garde que ses N derniers éléments : la perte est possible si
plus de N articles paraissent entre deux runs. L'audit le détecte (chevauchement).
"""

import hashlib

from defusedxml import ElementTree as ET

from ..store import Item

ATOM = "{http://www.w3.org/2005/Atom}"


def _clean(s):
    return " ".join((s or "").split())


def parse_feed(raw: bytes, feed_url: str) -> list[Item]:
    root = ET.fromstring(raw)
    items = []
    entries = list(root.iter("item")) or list(root.iter(ATOM + "entry"))
    for e in entries:
        if e.tag == "item":
            title, link = _clean(e.findtext("title")), _clean(e.findtext("link"))
            guid = _clean(e.findtext("guid")) or link
            date, body = _clean(e.findtext("pubDate")), e.findtext("description") or ""
        else:
            title = _clean(e.findtext(ATOM + "title"))
            l = e.find(ATOM + "link")
            link = l.get("href", "") if l is not None else ""
            guid = _clean(e.findtext(ATOM + "id")) or link
            date = _clean(e.findtext(ATOM + "updated"))
            body = e.findtext(ATOM + "summary") or e.findtext(ATOM + "content") or ""
        if not guid:
            continue
        # Version = empreinte du contenu : une correction éditoriale devient une révision
        # visible plutôt qu'un écrasement silencieux.
        version = hashlib.sha256("\x1f".join([title, link, date, body]).encode()).hexdigest()[:16]
        items.append(Item(source="cern", item_id=guid, version=version, title=title,
                          published=date, updated=date,
                          meta={"link": link, "feed": feed_url}))
    return items
