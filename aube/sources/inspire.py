"""INSPIRE-HEP (API REST JSON). Parseur pur."""

import json
from datetime import date
from urllib.parse import urlencode

from ..store import Item

API = "https://inspirehep.net/api/literature"
MAX_DEPTH = 10_000  # INSPIRE refuse la pagination au-delà


class InspireError(Exception):
    pass


def api_url(query_tpl: str, since: date, until: date, size: int, fields: str, page: int = 1) -> str:
    q = query_tpl.format(since=since.isoformat(), until=until.isoformat())
    return API + "?" + urlencode({"q": q, "size": size, "page": page,
                                  "sort": "mostrecent", "fields": fields})


def parse_page(raw: bytes) -> tuple[list[Item], int, str | None]:
    try:
        doc = json.loads(raw)
        hits = doc["hits"]
        total = int(hits["total"])
    except (ValueError, KeyError, TypeError) as e:
        raise InspireError(f"réponse INSPIRE non conforme : {e}") from e
    items = []
    for h in hits.get("hits", []):
        m = h.get("metadata", {})
        cn = str(m.get("control_number") or h.get("id") or "")
        if not cn:
            continue
        titles = m.get("titles") or [{}]
        items.append(Item(
            source="inspire", item_id=cn, version=str(h.get("updated", "")),
            title=" ".join((titles[0].get("title") or "").split()),
            # published = date d'ENTRÉE dans INSPIRE (celle que filtre `da`), pas de publication.
            published=str(h.get("created", "")), updated=str(h.get("updated", "")),
            meta={
                "arxiv": [x.get("value") for x in m.get("arxiv_eprints", []) if x.get("value")],
                "citation_count": m.get("citation_count"),
                "document_type": m.get("document_type", []),
                "n_references": len(m.get("references", []) or []),
            }))
    nxt = (doc.get("links") or {}).get("next")
    return items, total, nxt
