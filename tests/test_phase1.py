import gzip
import shutil
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from aube import audit, collect, config
from aube.sources import arxiv
from aube.store import Store

from .fake import FakeWeb

ROOT = Path(__file__).resolve().parents[1]
T0 = datetime(2026, 10, 1, 0, 40, tzinfo=timezone.utc)


@pytest.fixture
def env(tmp_path):
    shutil.copy(ROOT / "config.toml", tmp_path / "config.toml")
    cfg = config.load(tmp_path / "config.toml")
    web = FakeWeb()
    return cfg, web


def paper(n, when, cats=("hep-th",), v="v1"):
    return {"id": f"2610.{n:05d}", "v": v, "updated": when.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "cats": list(cats), "title": f"Article {n}"}


def go(cfg, web, now):
    return collect.run(cfg, now=now, fetcher=web, sleep=lambda s: None, clock=lambda: now)


def test_split_id():
    assert arxiv.split_id("http://arxiv.org/abs/2610.01234v2") == ("2610.01234", "v2")
    assert arxiv.split_id("oai:arXiv.org:hep-th/9901001v1") == ("hep-th/9901001", "v1")
    assert arxiv.split_id("arXiv:2610.01234") == ("2610.01234", "")


def test_pagination_complete_et_sans_doublon(env):
    cfg, web = env
    web.papers = [paper(i, T0 - timedelta(hours=i)) for i in range(450)]  # 3 pages de 200
    m = go(cfg, web, T0)
    assert m["status"] == "ok", m["errors"]
    s = Store(cfg.data_dir)
    assert s.db.execute("SELECT count(*) FROM items WHERE source='arxiv'").fetchone()[0] == 7 * 24 + 1
    # second run : recouvrement de 7 jours, rien de nouveau, aucun doublon
    go(cfg, web, T0 + timedelta(days=1))
    assert s.db.execute("SELECT count(*) FROM items WHERE source='arxiv'").fetchone()[0] == 7 * 24 + 1


def test_nouvelle_version_est_un_nouvel_element(env):
    cfg, web = env
    web.papers = [paper(1, T0 - timedelta(hours=1))]
    go(cfg, web, T0)
    web.papers.append(paper(1, T0 + timedelta(hours=2), v="v2"))
    go(cfg, web, T0 + timedelta(days=1))
    rows = Store(cfg.data_dir).db.execute("SELECT version FROM items ORDER BY 1").fetchall()
    assert [r[0] for r in rows] == ["v1", "v2"]


def test_page_vide_intempestive_est_rejouee(env):
    cfg, web = env
    web.papers = [paper(i, T0 - timedelta(hours=i)) for i in range(10)]
    url = arxiv.api_url("hep-th", T0 - timedelta(days=7), T0, 0, 200)
    web.flaky_once.add(url)
    m = go(cfg, web, T0)
    assert m["status"] == "ok"
    assert Store(cfg.data_dir).db.execute("SELECT count(*) FROM items").fetchone()[0] == 10


def test_panne_puis_rattrapage_sans_trou(env):
    cfg, web = env
    web.papers = [paper(i, T0 - timedelta(hours=i)) for i in range(5)]
    go(cfg, web, T0)
    web.down.add("https://export.arxiv.org")
    # panne pendant 10 jours : plus long que le recouvrement de 7 jours
    for d in range(1, 11):
        web.papers.append(paper(100 + d, T0 + timedelta(days=d, hours=-5)))
        m = go(cfg, web, T0 + timedelta(days=d))
        assert m["status"] == "partial"
    web.down.clear()
    go(cfg, web, T0 + timedelta(days=11))
    rep = audit.audit(cfg.data_dir, now=T0 + timedelta(days=11, hours=1))
    assert "trou_de_fenetre" not in rep["problemes"]      # la fenêtre part du dernier succès
    s = Store(cfg.data_dir)
    assert all(s.known("arxiv", f"2610.{100 + d:05d}") for d in range(1, 11))


def test_audit_propre_puis_falsifications(env):
    cfg, web = env
    web.cern = [("a", "Nouvelles du LHC")]
    web.inspire = [{"control_number": 1, "updated": "2026-09-30T10:00:00", "title": "x"}]
    for d in range(3):
        now = T0 + timedelta(days=d)
        web.papers.append(paper(d, now - timedelta(hours=3)))
        web.witness = {"hep-th": [(f"2610.{d:05d}", "v1", "new")]}
        go(cfg, web, now)
    end = T0 + timedelta(days=2, hours=1)
    rep = audit.audit(cfg.data_dir, now=end, days=3)
    assert rep["problemes"] == {}, rep["problemes"]
    assert rep["temoins_verifies"] >= 1
    assert rep["critere_phase1"] == "ATTEINT"

    # falsification 1 : le témoin annonce un article que l'API n'a jamais rendu
    web.witness = {"hep-th": [("2610.99999", "v1", "new")]}
    go(cfg, web, T0 + timedelta(days=3))
    go(cfg, web, T0 + timedelta(days=4, hours=2))
    rep = audit.audit(cfg.data_dir, now=T0 + timedelta(days=4, hours=3))
    assert "temoin_absent" in rep["problemes"]

    # falsification 2 : un octet altéré dans l'archive
    s = Store(cfg.data_dir)
    blob = next(s.blobs.rglob("*.gz"))
    raw = bytearray(gzip.decompress(blob.read_bytes()))
    raw[-2] ^= 1
    blob.write_bytes(gzip.compress(bytes(raw), mtime=0))
    rep = audit.audit(cfg.data_dir, now=T0 + timedelta(days=4, hours=3))
    assert "hash_invalide" in rep["problemes"]


def test_index_rejouable(env):
    cfg, web = env
    web.papers = [paper(i, T0 - timedelta(hours=i)) for i in range(20)]
    go(cfg, web, T0)
    s = Store(cfg.data_dir)
    s.db.execute("DELETE FROM items WHERE item_id='2610.00003'")
    s.db.commit()
    rep = audit.audit(cfg.data_dir, now=T0)
    assert "index_non_rejouable" in rep["problemes"]


def test_cern_trou_detecte(env):
    cfg, web = env
    web.cern = [("a", "A"), ("b", "B")]
    go(cfg, web, T0)
    web.cern = [("c", "C"), ("d", "D")]   # plus aucun élément commun : on a pu rater des actus
    go(cfg, web, T0 + timedelta(days=1))
    rep = audit.audit(cfg.data_dir, now=T0 + timedelta(days=1))
    assert "cern_trou_possible" in rep["problemes"]


def test_cern_deux_pages_pas_de_faux_trou(env):
    """15 actus entre deux runs : la page 1 seule ne recoupe rien, l'union des 2 pages si."""
    cfg, web = env
    old = [(f"o{i}", f"O{i}") for i in range(20)]
    web.cern = old
    go(cfg, web, T0)
    web.cern = [(f"n{i}", f"N{i}") for i in range(15)] + old
    go(cfg, web, T0 + timedelta(days=1))
    rep = audit.audit(cfg.data_dir, now=T0 + timedelta(days=1))
    assert "cern_trou_possible" not in rep["problemes"]


def test_cern_billet_re_date_ne_masque_pas_un_trou(env):
    """Un vieux billet re-daté (ex. « Upcoming events ») recoupe toujours : la date le démasque."""
    cfg, web = env
    d = lambda day: f"{day:02d} Sep 2026 10:00:00 +0000"
    web.cern = [("ev", "Upcoming events", "Mon, " + d(1))] + [(f"a{i}", "A", "Mon, " + d(1)) for i in range(5)]
    go(cfg, web, T0)
    # 25 actus parues depuis (plus que 2 pages), et « ev » re-daté en tête de flux
    web.cern = [("ev", "Upcoming events", "Tue, " + d(29))] + \
               [(f"b{i}", "B", "Mon, " + d(28 - i % 20)) for i in range(25)]
    go(cfg, web, T0 + timedelta(days=1))
    rep = audit.audit(cfg.data_dir, now=T0 + timedelta(days=1))
    assert any("postérieur" in x for x in rep["problemes"].get("cern_trou_possible", []))


def test_archive_deterministe(env, tmp_path):
    """Mêmes réponses, même moment → blobs octet pour octet identiques."""
    cfg, web = env
    web.papers = [paper(i, T0 - timedelta(hours=i)) for i in range(30)]
    go(cfg, web, T0)
    a = {p.name: p.read_bytes() for p in Store(cfg.data_dir).blobs.rglob("*.gz")}
    other = tmp_path / "b"
    other.mkdir()
    shutil.copy(cfg.root / "config.toml", other / "config.toml")
    cfg2 = config.load(other / "config.toml")
    go(cfg2, web, T0)
    b = {p.name: p.read_bytes() for p in Store(cfg2.data_dir).blobs.rglob("*.gz")}
    assert a == b
