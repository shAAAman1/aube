"""Faux serveurs arXiv / CERN / INSPIRE pour tester sans réseau.

Formats calqués sur les réponses réelles ; à confronter aux vraies réponses sur le Bixeon.
"""

import json
import re
from datetime import datetime, timezone
from urllib.parse import parse_qs, urlparse
from xml.sax.saxutils import escape

from aube.http import FetchError, Response


def atom(entries, total, start):
    out = ['<?xml version="1.0" encoding="UTF-8"?>',
           '<feed xmlns="http://www.w3.org/2005/Atom" '
           'xmlns:opensearch="http://a9.com/-/spec/opensearch/1.1/" '
           'xmlns:arxiv="http://arxiv.org/schemas/atom">',
           f"<opensearch:totalResults>{total}</opensearch:totalResults>",
           f"<opensearch:startIndex>{start}</opensearch:startIndex>"]
    for p in entries:
        out.append(
            f"<entry><id>http://arxiv.org/abs/{p['id']}{p['v']}</id>"
            f"<updated>{p['updated']}</updated><published>{p['updated']}</published>"
            f"<title>{escape(p['title'])}</title><summary>résumé</summary>"
            f"<author><name>A. Auteur</name></author>"
            f'<arxiv:primary_category term="{p["cats"][0]}"/>'
            + "".join(f'<category term="{c}"/>' for c in p["cats"]) + "</entry>")
    out.append("</feed>")
    return "\n".join(out).encode()


def rss(items):
    body = "".join(
        f"<item><title>t</title><guid isPermaLink=\"false\">oai:arXiv.org:{i}{v}</guid>"
        f"<description>arXiv:{i}{v} Announce Type: {t} Abstract: x</description>"
        f"<arxiv:announce_type>{t}</arxiv:announce_type></item>" for i, v, t in items)
    return ('<?xml version="1.0"?><rss xmlns:arxiv="http://arxiv.org/schemas/atom" version="2.0">'
            f"<channel><title>arXiv</title>{body}</channel></rss>").encode()


def cern_rss(items):
    body = "".join(f"<item><title>{t}</title><link>https://home.cern/news/{g}</link>"
                   f"<guid>{g}</guid><pubDate>Sat, 03 Oct 2026 10:00:00 +0200</pubDate>"
                   f"<description>&lt;p&gt;texte&lt;/p&gt;</description></item>" for g, t in items)
    return f'<?xml version="1.0"?><rss version="2.0"><channel>{body}</channel></rss>'.encode()


class FakeWeb:
    def __init__(self):
        self.papers = []          # {'id','v','updated','cats','title'}
        self.witness = {}         # cat -> [(id, v, type)]
        self.cern = []            # [(guid, title)]
        self.inspire = []         # [{'control_number', 'updated', 'title'}]
        self.flaky_once = set()   # urls renvoyant une page vide une fois
        self.down = set()         # préfixes d'URL en panne
        self.calls = []

    def get(self, url):
        self.calls.append(url)
        if any(url.startswith(d) for d in self.down):
            raise FetchError(f"HTTP 503 — {url}")
        u = urlparse(url)
        q = {k: v[0] for k, v in parse_qs(u.query).items()}
        if u.netloc == "export.arxiv.org":
            m = re.match(r"cat:(\S+) AND lastUpdatedDate:\[(\d{12}) TO (\d{12})\]", q["search_query"])
            cat, a, b = m.groups()
            fmt = lambda s: datetime.strptime(s, "%Y%m%d%H%M").replace(tzinfo=timezone.utc)
            lo, hi = fmt(a), fmt(b)
            sel = sorted((p for p in self.papers if cat in p["cats"]
                          and lo <= datetime.fromisoformat(p["updated"].replace("Z", "+00:00")) <= hi),
                         key=lambda p: p["updated"])
            start, size = int(q["start"]), int(q["max_results"])
            if url in self.flaky_once:
                self.flaky_once.discard(url)
                return Response(url, 200, atom([], len(sel), start), "application/atom+xml")
            return Response(url, 200, atom(sel[start:start + size], len(sel), start), "application/atom+xml")
        if u.netloc == "rss.arxiv.org":
            cat = u.path.rsplit("/", 1)[-1]
            return Response(url, 200, rss(self.witness.get(cat, [])), "application/rss+xml")
        if u.netloc == "home.cern":
            return Response(url, 200, cern_rss(self.cern), "application/rss+xml")
        if u.netloc == "inspirehep.net":
            size, page = int(q["size"]), int(q["page"])
            sel = self.inspire[(page - 1) * size: page * size]
            doc = {"hits": {"total": len(self.inspire), "hits": [
                {"id": r["control_number"], "created": r["updated"], "updated": r["updated"],
                 "metadata": {"control_number": r["control_number"], "titles": [{"title": r["title"]}]}}
                for r in sel]}, "links": {}}
            return Response(url, 200, json.dumps(doc).encode(), "application/json")
        raise FetchError(f"URL inattendue {url}")
