"""Faux serveurs arXiv (OAI-PMH, RSS) / CERN / INSPIRE pour tester sans réseau.

Formats calqués sur les réponses réelles ; à confronter aux vraies réponses sur le Bixeon.
"""

import json
from datetime import datetime
from urllib.parse import parse_qs, urlparse
from xml.sax.saxutils import escape

from aube.http import FetchError, Response


def oai(records, token=None):
    """records : [(id, datestamp, [(v, datetime)], cats, titre)] — format de oaipmh.arxiv.org."""
    if not records and token is None:
        return ('<?xml version="1.0" encoding="UTF-8"?>'
                '<OAI-PMH xmlns="http://www.openarchives.org/OAI/2.0/">'
                "<error code='noRecordsMatch'>The combination of the values of the from, until, "
                "set and metadataPrefix arguments results in an empty list.</error></OAI-PMH>").encode()
    out = ['<?xml version="1.0" encoding="UTF-8"?>',
           '<OAI-PMH xmlns="http://www.openarchives.org/OAI/2.0/"><ListRecords>']
    for rid, stamp, versions, cats, title in records:
        out.append(
            f"<record><header><identifier>oai:arXiv.org:{rid}</identifier>"
            f"<datestamp>{stamp}</datestamp><setSpec>physics:{cats[0]}</setSpec></header>"
            f'<metadata><arXivRaw xmlns="http://arxiv.org/OAI/arXivRaw/"><id>{rid}</id>'
            + "".join(f'<version version="{v}"><date>{d.strftime("%a, %d %b %Y %H:%M:%S GMT")}'
                      f"</date><size>1kb</size></version>" for v, d in versions)
            + f"<title>{escape(title)}</title><authors>A. Auteur</authors>"
            f"<categories>{' '.join(cats)}</categories></arXivRaw></metadata></record>")
    if token is not None:
        out.append(f"<resumptionToken>{escape(token)}</resumptionToken>")
    out.append("</ListRecords></OAI-PMH>")
    return "".join(out).encode()


def rss(items):
    body = "".join(
        f"<item><title>t</title><guid isPermaLink=\"false\">oai:arXiv.org:{i}{v}</guid>"
        f"<description>arXiv:{i}{v} Announce Type: {t} Abstract: x</description>"
        f"<arxiv:announce_type>{t}</arxiv:announce_type></item>" for i, v, t in items)
    return ('<?xml version="1.0"?><rss xmlns:arxiv="http://arxiv.org/schemas/atom" version="2.0">'
            f"<channel><title>arXiv</title>{body}</channel></rss>").encode()


def cern_rss(items):
    """items : [(guid, titre)] ou [(guid, titre, pubDate)], du plus récent au plus ancien."""
    items = [(*it, "Sat, 03 Oct 2026 10:00:00 +0200")[:3] for it in items]
    body = "".join(f"<item><title>{t}</title><link>https://home.cern/news/{g}</link>"
                   f"<guid>{g}</guid><pubDate>{d}</pubDate>"
                   f"<description>&lt;p&gt;texte&lt;/p&gt;</description></item>" for g, t, d in items)
    return f'<?xml version="1.0"?><rss version="2.0"><channel>{body}</channel></rss>'.encode()


class FakeWeb:
    def __init__(self):
        self.papers = []          # {'id','v','updated','cats','title'}
        self.witness = {}         # cat -> [(id, v, type)]
        self.cern = []            # [(guid, title)]
        self.inspire = []         # [{'control_number', 'updated', 'title'}]
        self.inspire_shift_after_page1 = False
        self.inspire_drop_before_page2 = False
        self.oai_page = 100       # enregistrements par page OAI-PMH
        self.oai_errors = {}      # set -> code d'erreur OAI à renvoyer
        self.oai_forced = []      # réponses OAI imposées, servies dans l'ordre
        self.oai_on_page2 = None  # hook(web) appelé avant la première page suivante
        self.oai_deleted = []     # identifiants servis comme supprimés
        self.down = set()         # préfixes d'URL en panne
        self.calls = []

    def get(self, url):
        self.calls.append(url)
        if any(url.startswith(d) for d in self.down):
            raise FetchError(f"HTTP 503 — {url}")
        u = urlparse(url)
        q = {k: v[0] for k, v in parse_qs(u.query).items()}
        if u.netloc == "oaipmh.arxiv.org":
            return Response(url, 200, self._oai(q), "text/xml")
        if u.netloc == "rss.arxiv.org":
            cat = u.path.rsplit("/", 1)[-1]
            return Response(url, 200, rss(self.witness.get(cat, [])), "application/rss+xml")
        if u.netloc == "home.cern":  # WordPress : 10 items par page, ?paged=N
            page = int(q.get("paged", 1))
            return Response(url, 200, cern_rss(self.cern[(page - 1) * 10: page * 10]),
                            "application/rss+xml")
        if u.netloc == "inspirehep.net":
            size, page = int(q["size"]), int(q["page"])
            if self.inspire_drop_before_page2 and page > 1:
                self.inspire.pop(0)
                self.inspire_drop_before_page2 = False
            if self.inspire_shift_after_page1 and page > 1:
                # un enregistrement de la page 1 est modifié et glisse en page 2
                self.inspire.insert(size, self.inspire.pop(0))
                self.inspire_shift_after_page1 = False
            sel = self.inspire[(page - 1) * size: page * size]
            doc = {"hits": {"total": len(self.inspire), "hits": [
                {"id": r["control_number"], "created": r["updated"], "updated": r["updated"],
                 "metadata": {"control_number": r["control_number"], "titles": [{"title": r["title"]}]}}
                for r in sel]}, "links": {}}
            return Response(url, 200, json.dumps(doc).encode(), "application/json")
        raise FetchError(f"URL inattendue {url}")

    def _oai(self, q):
        """Jetons sans état (set|from|until|skip), comme oaipmh.arxiv.org.

        datestamp d'un enregistrement = champ « stamp » de sa dernière version s'il est donné
        (jour d'annonce ou de modification), sinon le jour de sa date de version (raccourci).
        """
        if self.oai_forced:
            return self.oai_forced.pop(0)
        if "resumptionToken" in q:
            set_spec, a, b, skip = q["resumptionToken"].split("|")
            skip = int(skip)
            if self.oai_on_page2:          # ex. un enregistrement déjà servi change de datestamp
                hook, self.oai_on_page2 = self.oai_on_page2, None
                hook(self)
        else:
            set_spec, a, b, skip = q["set"], q["from"], q["until"], 0
        if set_spec in self.oai_errors:
            return (f'<OAI-PMH xmlns="http://www.openarchives.org/OAI/2.0/">'
                    f"<error code='{self.oai_errors[set_spec]}'>erreur</error></OAI-PMH>").encode()
        cat = set_spec.split(":", 1)[1].replace(":", ".")
        by_id = {}
        for p in self.papers:
            by_id.setdefault(p["id"], []).append(p)
        recs = []
        for rid, ps in by_id.items():
            ps.sort(key=lambda p: int(p["v"][1:]))
            when = [datetime.fromisoformat(p["updated"].replace("Z", "+00:00")) for p in ps]
            stamp = ps[-1].get("stamp") or when[-1].date().isoformat()
            if cat in ps[-1]["cats"] and a <= stamp <= b:
                recs.append((stamp, rid, [(p["v"], w) for p, w in zip(ps, when)],
                             ps[-1]["cats"], ps[-1]["title"]))
        recs.sort()
        page = recs[skip: skip + self.oai_page]
        more = skip + self.oai_page < len(recs)
        token = f"{set_spec}|{a}|{b}|{skip + self.oai_page}" if more else ("" if skip else None)
        body = oai([(rid, st, vs, cats, t) for st, rid, vs, cats, t in page], token)
        for rid in self.oai_deleted:   # enregistrement supprimé : en-tête seul, sans métadonnées
            body = body.replace(b"<ListRecords>", b"<ListRecords><record><header status=\"deleted\">"
                                b"<identifier>oai:arXiv.org:" + rid.encode() + b"</identifier>"
                                b"<datestamp>" + a.encode() + b"</datestamp></header></record>", 1)
        return body
