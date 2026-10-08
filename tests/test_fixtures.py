"""Parseurs contre des réponses RÉELLES, tronquées (extraites des blobs de data/).

Seuls des éléments entiers ont été retirés : les fixtures XML gardent les octets d'origine des
éléments conservés, les fixtures JSON sont ré-sérialisées (contenu identique). Les totaux
annoncés restent ceux de la réponse complète : ne pas réutiliser ces fixtures pour tester la
boucle de pagination de collect.py.
"""

from pathlib import Path

from aube.sources import arxiv, cern, inspire

FIX = Path(__file__).resolve().parent / "fixtures"


def test_cern_wordpress_reel():
    # blob 9b05fdff…, run 20261004T0237Z, https://home.cern/feed/
    items = cern.parse_feed((FIX / "cern_feed_20261004.xml").read_bytes(), "https://home.cern/feed/")
    assert [(it.item_id, it.version) for it in items] == [
        ("https://home.cern/?p=27548", "b4ac17ea0c12343e"),
        ("https://home.cern/?p=25536", "be8c26ce418ad0a0"),
    ]
    first = items[0]
    assert first.title == "Want to develop your skills?"
    assert first.published == "Thu, 01 Oct 2026 13:05:59 +0000"
    assert first.meta == {"link": "https://home.cern/want-to-develop-your-skills/",
                          "feed": "https://home.cern/feed/"}


def test_cern_empreinte_ignore_le_calendrier_dynamique():
    """Deux lectures de home.cern ne diffèrent que par stringDate dans content:encoded."""
    raw = (FIX / "cern_feed_20261004.xml").read_bytes()
    assert raw.count(b'"stringDate":"') == 1
    i = raw.index(b'"stringDate":"') + len(b'"stringDate":"')
    other = raw[:i] + b"2099-01-01" + raw[i + 10:]
    assert other != raw
    v = lambda b: [(it.item_id, it.version) for it in cern.parse_feed(b, "f")]
    assert v(other) == v(raw)


def test_inspire_page_reelle():
    # blob 4bec82e2…, run 20261004T0240Z, page 1 de « da >= 2026-09-30 and da <= 2026-10-03 »
    items, total, nxt = inspire.parse_page((FIX / "inspire_literature_p1_20261004.json").read_bytes())
    assert total == 1480
    assert nxt and "page=2" in nxt
    assert [it.item_id for it in items] == ["3210329", "3209432", "3209397"]
    a = items[0]
    assert a.version == a.updated == "2026-10-03T02:22:36.301957+00:00"
    assert a.published == "2026-10-02T03:30:19.463176+00:00"   # `created` = ce que filtre `da`
    assert a.meta["arxiv"] == ["2610.00847"]
    assert a.meta["document_type"] == ["article"]
    assert a.meta["n_references"] == 32
    thesis = items[1]
    assert thesis.meta == {"arxiv": [], "citation_count": 0, "document_type": ["thesis"],
                           "n_references": 0}
    # toutes les dates d'entrée tombent dans la fenêtre demandée
    assert all("2026-09-30" <= it.published[:10] <= "2026-10-03" for it in items)


def test_arxiv_oai_reel():
    # blob 8bbbe336…, run 20261004T0246Z, set physics:hep-th, datestamps 2026-09-30 → 2026-10-03
    items, token, n = arxiv.parse_oai((FIX / "arxiv_oai_hepth_20260930_1003.xml").read_bytes())
    assert (n, token) == (3, None)
    assert [(it.item_id, it.version) for it in items] == [
        ("2102.06878", "v1"), ("2102.06878", "v2"), ("2102.06878", "v3"), ("2102.06878", "v4"),
        ("2102.06878", "v5"), ("2610.00146", "v1"), ("2610.02209", "v1")]
    # remplacement d'un article de 2021, annoncé le 2 octobre : invisible pour l'ancienne API
    v5 = items[4]
    assert v5.published == "2021-02-13T07:22:28Z"
    assert v5.updated == "2026-10-01T09:23:39Z"
    assert v5.meta["datestamp"] == "2026-10-02"
    # soumis le 10 septembre, annoncé le 2 octobre : hors de toute fenêtre de soumission de 7 jours
    late = items[5]
    assert late.updated == "2026-09-10T12:13:32Z" and late.meta["datestamp"] == "2026-10-02"
    assert late.meta["primary"] == "hep-ph"
    assert late.meta["categories"] == ["hep-ph", "hep-th", "quant-ph"]
    assert items[6].title == "Leading gravitational dressing of operators and states in de Sitter space"
    assert items[6].meta["authors"] == "Steven B. Giddings and Zi-Yue Wang"


def test_arxiv_oai_jour_sans_annonce():
    """Réponse réelle (sonde du 2026-10-04, hep-ex le samedi 3) : noRecordsMatch = 0 élément."""
    raw = (b"<?xml version=\"1.0\" encoding=\"UTF-8\"?>\n<OAI-PMH xmlns=\"http://www.openarchives.org/OAI/2.0/\">"
           b"<responseDate>2026-10-04T02:34:37Z</responseDate>"
           b"<error code='noRecordsMatch'>The combination of the values of the from, until, set and "
           b"metadataPrefix arguments results in an empty list.</error></OAI-PMH>")
    assert arxiv.parse_oai(raw) == ([], None, 0)
    bad = raw.replace(b"noRecordsMatch", b"badResumptionToken")
    try:
        arxiv.parse_oai(bad)
    except arxiv.ArxivError as e:
        assert "badResumptionToken" in str(e)
    else:
        raise AssertionError("une erreur OAI autre que noRecordsMatch doit lever")


def test_arxiv_rss_reel_vide_le_week_end():
    # blob 8c99fb1e…, https://rss.arxiv.org/rss/hep-th lu le dimanche 4 octobre (non tronqué)
    raw = (FIX / "arxiv_rss_hepth_dimanche_20261004.xml").read_bytes()
    assert arxiv.parse_rss(raw) == []
    assert b"<day>Saturday</day>" in raw and b"<day>Sunday</day>" in raw
    # reconstruit à 04:00 UTC (minuit à New York) : le run de 00:40 UTC lit le flux de la veille
    assert b"<lastBuildDate>Sat, 03 Oct 2026 04:00:01 +0000</lastBuildDate>" in raw


def test_arxiv_api_ancienne_collecte_rejouable():
    """Blobs arxiv_api archivés jusqu'au 2026-10-04 : le parseur doit rester capable de les rejouer.

    blob 2093af71…, run 20261004T0215Z. Le titre prouve la réécriture silencieuse du filtre.
    """
    raw = (FIX / "arxiv_api_hepph_legacy_20261004.xml").read_bytes()
    assert b"AND lastUpdatedDate" not in raw and b'AND submittedDate:"202609270156 TO 202610040215"' in raw
    items, total = arxiv.parse_api(raw)
    assert total == 192
    assert [(it.item_id, it.version) for it in items] == [
        ("2609.33151", "v1"), ("2609.34820", "v1"), ("2609.34937", "v2")]
    assert items[1].meta["primary"] == "astro-ph.HE"
    assert items[1].meta["doi"] == "10.1103/lsrj-27p1"
    assert items[2].published == "2026-09-28T11:32:33Z" and items[2].updated == "2026-09-29T10:17:22Z"
