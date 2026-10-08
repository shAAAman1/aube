"""Parseurs contre des réponses RÉELLES, tronquées (extraites des blobs de data/).

Chaque fixture garde les octets d'origine des éléments conservés : seuls des éléments entiers
ont été retirés. Les totaux annoncés restent donc ceux de la réponse complète.
"""

from pathlib import Path

from aube.sources import cern

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
