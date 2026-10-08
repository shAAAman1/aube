"""Parseurs contre des réponses RÉELLES, tronquées (extraites des blobs de data/).

Seuls des éléments entiers ont été retirés : les fixtures XML gardent les octets d'origine des
éléments conservés, les fixtures JSON sont ré-sérialisées (contenu identique). Les totaux
annoncés restent ceux de la réponse complète : ne pas réutiliser ces fixtures pour tester la
boucle de pagination de collect.py.
"""

from pathlib import Path

from aube.sources import cern, inspire

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
