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


def paper(n, when, cats=("hep-th",), v="v1", stamp=None):
    """stamp : datestamp OAI (jour d'annonce), par défaut le jour de `when`."""
    p = {"id": f"2610.{n:05d}", "v": v, "updated": when.strftime("%Y-%m-%dT%H:%M:%SZ"),
         "cats": list(cats), "title": f"Article {n}"}
    if stamp:
        p["stamp"] = stamp
    return p


def go(cfg, web, now):
    return collect.run(cfg, now=now, fetcher=web, sleep=lambda s: None, clock=lambda: now)


def test_split_id():
    assert arxiv.split_id("http://arxiv.org/abs/2610.01234v2") == ("2610.01234", "v2")
    assert arxiv.split_id("oai:arXiv.org:hep-th/9901001v1") == ("hep-th/9901001", "v1")
    assert arxiv.split_id("arXiv:2610.01234") == ("2610.01234", "")


def _in_window(papers, a, b):
    return sum(1 for p in papers if a <= p["updated"][:10] <= b)


def test_pagination_complete_et_sans_doublon(env):
    cfg, web = env
    web.oai_page = 10
    web.papers = [paper(i, T0 - timedelta(hours=i)) for i in range(450)]
    m = go(cfg, web, T0)
    assert m["status"] == "ok", m["errors"]
    oai_fetches = [f for f in m["fetches"] if f["kind"] == "arxiv_oai" and f["key"] == "hep-th"]
    # un jour à la fois (27 → 30 sept.), 24 enregistrements par jour = 3 pages, et seconde
    # passe dès qu'un jour dépasse une page : 4 × 2 × 3 requêtes
    assert len(oai_fetches) == 24
    assert all("from=2026-09-" in f["url"] or "resumptionToken" in f["url"] for f in oai_fetches)
    s = Store(cfg.data_dir)
    n = lambda: s.db.execute("SELECT count(*) FROM items WHERE source='arxiv'").fetchone()[0]
    assert n() == _in_window(web.papers, "2026-09-27", "2026-09-30") == 96
    # second run : recouvrement, seul le 1er octobre s'ajoute, aucun doublon
    go(cfg, web, T0 + timedelta(days=1))
    assert n() == _in_window(web.papers, "2026-09-27", "2026-10-01") == 97


def test_glissement_de_pagination_rattrape_par_la_seconde_passe(env):
    """Un enregistrement de la page 1 reçoit une v2 annoncée aujourd'hui pendant la pagination :
    le jeton sans état (skip) saute alors le premier enregistrement de la page 2."""
    cfg, web = env
    cfg.raw["arxiv"]["categories"] = ["hep-th"]
    web.oai_page = 10
    day = T0 - timedelta(days=1)                       # 30 septembre
    web.papers = [paper(i, day.replace(hour=1) + timedelta(minutes=i)) for i in range(25)]
    page2_first = web.papers[10]["id"]
    web.oai_on_page2 = lambda w: w.papers.append(
        paper(0, T0, v="v2", stamp=T0.date().isoformat()))
    m = go(cfg, web, T0)
    assert m["status"] == "ok", m["errors"]
    s = Store(cfg.data_dir)
    assert s.known("arxiv", page2_first)               # sauté en passe 1, repris en passe 2
    assert s.db.execute("SELECT count(DISTINCT item_id) FROM items").fetchone()[0] == 25


def test_annonce_tardive_collectee(env):
    """Soumis le 10 septembre, annoncé (datestamp) le 2 octobre, comme 2610.00146."""
    cfg, web = env
    web.papers = [paper(146, datetime(2026, 9, 10, 12, 13, tzinfo=timezone.utc), stamp="2026-10-02")]
    go(cfg, web, T0 + timedelta(days=1))               # until = 1er octobre : pas encore annoncé
    s = Store(cfg.data_dir)
    assert not s.known("arxiv", "2610.00146")
    go(cfg, web, T0 + timedelta(days=2))               # until = 2 octobre
    assert s.known("arxiv", "2610.00146", "v1")


def test_gardes_de_pagination_oai(env):
    from .fake import oai
    cfg, web = env
    cfg.raw["arxiv"]["categories"] = ["hep-th"]
    rec = [("2610.00001", "2026-09-27", [("v1", T0 - timedelta(days=4))], ["hep-th"], "t")]
    web.oai_forced = [oai([], token="x")]              # page vide mais jeton présent
    m = go(cfg, web, T0)
    assert any("vide suivie" in e["error"] for e in m["errors"]), m["errors"]
    web.oai_forced = [oai(rec, token="t1"), oai(rec, token="t1")]   # jeton qui boucle
    m = go(cfg, web, T0 + timedelta(minutes=1))
    assert any("répété" in e["error"] for e in m["errors"]), m["errors"]


def test_enregistrement_supprime_ignore(env):
    cfg, web = env
    web.papers = [paper(1, T0 - timedelta(hours=5))]
    web.oai_deleted = ["2610.99999"]
    m = go(cfg, web, T0)
    assert m["status"] == "ok", m["errors"]
    assert Store(cfg.data_dir).db.execute("SELECT item_id FROM items").fetchall() == [("2610.00001",)]


def test_ligne_runs_conservee_si_la_premiere_source_echoue(env):
    cfg, web = env
    web.down.add("https://oaipmh.arxiv.org")
    m = go(cfg, web, T0)
    assert m["status"] == "partial"
    rows = Store(cfg.data_dir).db.execute("SELECT run_id, status FROM runs").fetchall()
    assert rows == [(m["run_id"], "partial")]


def test_nouvelle_version_est_un_nouvel_element(env):
    cfg, web = env
    web.papers = [paper(1, T0 - timedelta(hours=1))]
    go(cfg, web, T0)
    web.papers.append(paper(1, T0 + timedelta(hours=2), v="v2"))
    go(cfg, web, T0 + timedelta(days=1))
    rows = Store(cfg.data_dir).db.execute("SELECT version FROM items ORDER BY 1").fetchall()
    assert [r[0] for r in rows] == ["v1", "v2"]


def test_remplacement_ancien_et_version_intermediaire(env):
    """Ce que l'API ratait : la v3 d'un article de 2021, et une v2 déjà dépassée par la v3."""
    cfg, web = env
    old = datetime(2021, 2, 13, 7, 22, tzinfo=timezone.utc)
    web.papers = [paper(7, old), paper(7, old + timedelta(days=30), v="v2"),
                  paper(7, T0 - timedelta(days=2), v="v3", stamp="2026-09-30")]
    m = go(cfg, web, T0)
    assert m["status"] == "ok", m["errors"]
    rows = Store(cfg.data_dir).db.execute(
        "SELECT version, published, updated FROM items ORDER BY 1").fetchall()
    assert [r[0] for r in rows] == ["v1", "v2", "v3"]
    assert all(r[1] == "2021-02-13T07:22:00Z" for r in rows)   # date de la v1


def test_jour_sans_annonce_et_erreur_oai(env):
    cfg, web = env
    web.oai_errors = {"physics:hep-ph": "badArgument"}
    m = go(cfg, web, T0)                                  # aucun article : noRecordsMatch partout
    errs = {(e["source"], e["key"]): e["error"] for e in m["errors"]}
    assert list(errs) == [("arxiv", "hep-ph")]
    assert "badArgument" in errs[("arxiv", "hep-ph")]
    ws = {w["key"]: w for w in m["windows"] if w["source"] == "arxiv_oai"}
    assert "hep-ph" not in ws                            # fenêtre annulée avec la source
    assert ws["hep-th"]["received"] == 0 and ws["hep-th"]["complete"]


def test_panne_puis_rattrapage_sans_trou(env):
    cfg, web = env
    web.papers = [paper(i, T0 - timedelta(hours=i)) for i in range(5)]
    go(cfg, web, T0)
    web.down.add("https://oaipmh.arxiv.org")
    # panne pendant 10 jours : plus long que le recouvrement de 3 jours
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

    # falsification 1 : le témoin annonce un article que l'archive n'a jamais reçu.
    # Lu le 4 octobre, il n'est jugé que quand l'OAI couvre le 5 (marge d'un jour de datestamp).
    web.witness = {"hep-th": [("2610.99999", "v1", "new")]}
    go(cfg, web, T0 + timedelta(days=3))
    web.witness = {}
    go(cfg, web, T0 + timedelta(days=4, hours=2))       # OAI jusqu'au 4 : trop tôt pour juger
    rep = audit.audit(cfg.data_dir, now=T0 + timedelta(days=4, hours=3))
    assert "temoin_absent" not in rep["problemes"]
    go(cfg, web, T0 + timedelta(days=5))                # OAI jusqu'au 5
    rep = audit.audit(cfg.data_dir, now=T0 + timedelta(days=5, hours=1))
    assert "temoin_absent" in rep["problemes"]

    # falsification 2 : un octet altéré dans l'archive
    s = Store(cfg.data_dir)
    blob = next(s.blobs.rglob("*.gz"))
    raw = bytearray(gzip.decompress(blob.read_bytes()))
    raw[-2] ^= 1
    blob.write_bytes(gzip.compress(bytes(raw), mtime=0))
    rep = audit.audit(cfg.data_dir, now=T0 + timedelta(days=5, hours=1))
    assert "hash_invalide" in rep["problemes"]


def test_temoin_lu_apres_reconstruction_du_rss(env):
    """Run rattrapé à 05:00 UTC : le RSS du jour annonce des articles de datestamp J que l'OAI
    (jusqu'à J-1) n'a pas encore. Pas de faux temoin_absent ; jugé et trouvé deux runs plus tard."""
    cfg, web = env
    j = T0.replace(hour=5)                                          # 1er octobre, 05:00
    web.papers = [paper(5, j - timedelta(hours=20), stamp=j.date().isoformat())]
    web.witness = {"hep-th": [("2610.00005", "v1", "new")]}
    go(cfg, web, j)
    web.witness = {}
    for d in (1, 2):
        go(cfg, web, T0 + timedelta(days=d))
        rep = audit.audit(cfg.data_dir, now=T0 + timedelta(days=d, hours=1))
        assert not {"temoin_absent", "temoin_version_absente"} & set(rep["problemes"]), rep["problemes"]
    assert rep["temoins_verifies"] == 1


def test_temoin_inactif_signale(env):
    """Si le RSS ne produit plus rien (format changé), le critère ne doit pas passer en silence."""
    cfg, web = env
    for d in range(8):
        go(cfg, web, T0 + timedelta(days=d))
    rep = audit.audit(cfg.data_dir, now=T0 + timedelta(days=7, hours=1))
    assert any(x.startswith("hep-th") for x in rep["problemes"].get("temoin_inactif", []))
    assert rep["critere_phase1"] == "NON ATTEINT"
    # moins d'une semaine d'archive : pas encore jugeable
    rep = audit.audit(cfg.data_dir, now=T0 + timedelta(days=5, hours=1), days=6)
    assert "temoin_inactif" not in rep["problemes"]


def test_audit_survit_a_un_blob_rejete(env, monkeypatch):
    cfg, web = env
    web.oai_errors = {"physics:hep-ph": "badResumptionToken"}       # rejetée à la collecte
    go(cfg, web, T0)
    rep = audit.audit(cfg.data_dir, now=T0 + timedelta(hours=1))    # ne doit pas lever
    assert "blob_illisible" not in rep["problemes"]                 # déjà compté : erreur_de_run
    assert rep["problemes"]["erreur_de_run"]
    # un parseur devenu plus strict rejette un blob qu'un run avait accepté : signalé
    web.oai_errors = {}
    web.papers = [paper(1, T0 - timedelta(hours=5))]
    go(cfg, web, T0 + timedelta(days=1))
    monkeypatch.setattr(audit.arxiv, "parse_oai", lambda raw: (_ for _ in ()).throw(ValueError("x")))
    rep = audit.audit(cfg.data_dir, now=T0 + timedelta(days=1, hours=1))
    assert rep["problemes"]["blob_illisible"]


def _manifest(store, run_id, windows=(), fetches=(), errors=()):
    import json
    store.manifests.mkdir(parents=True, exist_ok=True)
    (store.manifests / f"{run_id}.json").write_text(json.dumps(
        {"run_id": run_id, "status": "ok", "fetches": list(fetches), "windows": list(windows),
         "errors": list(errors)}))


def test_trou_et_retard_en_jours_clos(env):
    cfg, _ = env
    s = Store(cfg.data_dir)
    w = lambda a, b: {"source": "arxiv_oai", "key": "hep-th", "since": a, "until": b,
                      "expected": None, "received": 0, "complete": True}
    _manifest(s, "20260904T0040Z", [w("2026-09-01", "2026-09-03")])
    _manifest(s, "20260905T0040Z", [w("2026-09-04", "2026-09-04")])  # contigu : pas de trou
    _manifest(s, "20260913T0040Z", [w("2026-09-10", "2026-09-12")])  # rien du 5 au 9
    rep = audit.audit(cfg.data_dir, now=datetime(2026, 9, 14, 11, 0, tzinfo=timezone.utc))
    assert rep["problemes"]["trou_de_fenetre"] == ["arxiv_oai/hep-th : rien entre 2026-09-04 et 2026-09-10"]
    assert "source_en_retard" not in rep["problemes"]                # 35 h après la fin du 12
    rep = audit.audit(cfg.data_dir, now=datetime(2026, 9, 14, 13, 0, tzinfo=timezone.utc))
    assert rep["problemes"]["source_en_retard"]                      # 37 h


def test_rejeu_mixte_ancienne_api_et_oai(env):
    """Archive réelle du 4 octobre : blobs arxiv_api (abandonnés) puis arxiv_oai, mêmes articles."""
    from aube.sources import arxiv as ax
    cfg, web = env
    s = Store(cfg.data_dir)
    raw = (ROOT / "tests/fixtures/arxiv_api_hepph_legacy_20261004.xml").read_bytes()
    sha = s.put_blob(raw)
    items, total = ax.parse_api(raw)
    s.add_items(items, "20260930T0040Z", sha)
    s.db.commit()
    _manifest(s, "20260930T0040Z",
              windows=[{"source": "arxiv", "key": "hep-ph", "since": "2026-09-27T01:56:00Z",
                        "until": "2026-09-30T00:40:00Z", "expected": 3, "received": 3, "complete": True}],
              fetches=[{"seq": 0, "kind": "arxiv_api", "key": "hep-ph", "status": "ok", "sha256": sha,
                        "fetched_at": "2026-09-30T00:40:00Z"}])
    # l'OAI renvoie ensuite les mêmes articles, avec en plus la v1 de 2609.34937
    web.papers = []
    for it in items:
        for v in range(1, int(it.version[1:]) + 1):
            web.papers.append({"id": it.item_id, "v": f"v{v}", "updated": it.updated,
                               "cats": ["hep-ph"], "title": it.title, "stamp": "2026-09-29"})
    go(cfg, web, T0)
    rep = audit.audit(cfg.data_dir, now=T0 + timedelta(hours=1), days=1)
    assert "index_non_rejouable" not in rep["problemes"], rep["problemes"]
    assert "blob_illisible" not in rep["problemes"], rep["problemes"]
    keys = set(s.db.execute("SELECT item_id, version FROM items WHERE source='arxiv'"))
    assert ("2609.34937", "v1") in keys and ("2609.34937", "v2") in keys


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


def test_inspire_pagination_decalee_detectee(env):
    """Un enregistrement qui glisse d'une page à l'autre : doublon + saut, même nombre reçu."""
    cfg, web = env
    web.inspire = [{"control_number": i, "updated": "2026-09-30T10:00:00", "title": "x"}
                   for i in range(1, 301)]  # 2 pages de 250
    web.inspire_shift_after_page1 = True
    m = go(cfg, web, T0)
    errs = [e["error"] for e in m["errors"] if e["source"] == "inspire"]
    assert errs and "pagination décalée" in errs[0], m["errors"]
    s = Store(cfg.data_dir)
    assert s.db.execute("SELECT count(*) FROM items WHERE source='inspire'").fetchone()[0] == 0


def test_erreur_de_run_bornee_a_la_fenetre(env):
    cfg, web = env
    web.cern = [("a", "A")]
    web.down.add("https://home.cern")
    go(cfg, web, T0)                               # run en erreur le jour 0
    web.down.clear()
    for d in range(1, 15):
        go(cfg, web, T0 + timedelta(days=d))
    # fenêtre de 14 jours = jours 1 à 14 : l'erreur du jour 0 n'en fait plus partie
    rep = audit.audit(cfg.data_dir, now=T0 + timedelta(days=14, hours=1), days=14)
    assert "erreur_de_run" not in rep["problemes"]
    assert len(rep["erreurs_hors_fenetre"]) == 2   # 2 pages CERN
    # fenêtre de 15 jours : elle en fait partie et bloque
    rep = audit.audit(cfg.data_dir, now=T0 + timedelta(days=14, hours=1), days=15)
    assert len(rep["problemes"]["erreur_de_run"]) == 2


def test_inspire_total_instable_detecte(env):
    cfg, web = env
    web.inspire = [{"control_number": i, "updated": "2026-09-30T10:00:00", "title": "x"}
                   for i in range(1, 301)]
    web.inspire_drop_before_page2 = True                # fusion ou suppression en cours de run
    m = go(cfg, web, T0)
    errs = [e["error"] for e in m["errors"] if e["source"] == "inspire"]
    assert errs and "total instable" in errs[0], m["errors"]
    assert not [w for w in m["windows"] if w["source"] == "inspire"]


def test_inspire_rattrapage_par_tranches(env):
    cfg, web = env
    web.inspire = [{"control_number": 1, "updated": "2026-09-01T10:00:00", "title": "x"}]
    go(cfg, web, T0)                                    # fenêtre 27 → 30 septembre
    m = go(cfg, web, T0 + timedelta(days=40))           # 40 jours de panne
    w = [w for w in m["windows"] if w["source"] == "inspire"][0]
    assert (w["since"], w["until"]) == ("2026-09-27", "2026-10-10")   # 14 jours au plus
    m = go(cfg, web, T0 + timedelta(days=41))
    w = [w for w in m["windows"] if w["source"] == "inspire"][0]
    assert w["since"] == "2026-10-07"                   # avance : reprise 3 jours avant


def _sigterm_on(fragment):
    """Envoie un VRAI SIGTERM au processus à la première requête contenant `fragment`."""
    import os
    import signal
    fired = []

    def hook(url):
        if fragment in url and not fired:
            fired.append(url)
            os.kill(os.getpid(), signal.SIGTERM)
    return hook


def test_sigterm_ecrit_le_manifeste_et_garde_l_index_rejouable(env):
    import json
    import signal
    cfg, web = env
    web.papers = [paper(i, T0 - timedelta(hours=3 + i)) for i in range(5)]
    web.cern = [("a", "A")]
    web.inspire = [{"control_number": i, "updated": "2026-09-30T10:00:00", "title": "x"}
                   for i in range(1, 301)]                     # 2 pages
    web.on_get = _sigterm_on("page=2")                         # au milieu d'INSPIRE
    before = signal.getsignal(signal.SIGTERM)
    m = go(cfg, web, T0)
    assert signal.getsignal(signal.SIGTERM) is before          # handler restauré
    assert m["status"] == "interrupted"
    assert [(e["source"], e["key"]) for e in m["errors"]] == [("inspire", "literature")]
    assert "SIGTERM" in m["errors"][0]["error"]
    assert m["not_run"] == []
    s = Store(cfg.data_dir)
    disk = json.loads((s.manifests / f"{m['run_id']}.json").read_text())
    assert disk["status"] == "interrupted"                     # manifeste bien écrit
    counts = dict(s.db.execute("SELECT source, count(*) FROM items GROUP BY 1"))
    assert counts == {"arxiv": 5, "cern": 1}                   # INSPIRE annulé, le reste gardé
    assert s.db.execute("SELECT status FROM runs").fetchall() == [("interrupted",)]
    rep = audit.audit(cfg.data_dir, now=T0 + timedelta(hours=1))
    assert "index_non_rejouable" not in rep["problemes"], rep["problemes"]
    assert rep["problemes"]["erreur_de_run"]
    assert rep["jours_consecutifs_ok"] == 0                    # un run interrompu ne compte pas


def test_sigterm_liste_les_sources_non_lancees(env):
    cfg, web = env
    web.cern = [("a", "A")]
    web.on_get = _sigterm_on("home.cern/feed/?paged=2")
    m = go(cfg, web, T0)
    assert m["status"] == "interrupted"
    assert m["errors"][-1]["key"] == "https://home.cern/feed/?paged=2"
    assert m["not_run"] == [{"source": "inspire", "key": "literature"}]
    assert "inspire" not in " ".join(f["url"] for f in m["fetches"])
    interrupted = [f for f in m["fetches"] if f.get("status") == "error"]
    assert len(interrupted) == 1 and interrupted[0]["error"].startswith("interrompu")


def test_ctrl_c_suit_le_meme_chemin(env):
    cfg, web = env

    def hook(url):
        if "home.cern" in url:
            raise KeyboardInterrupt
    web.on_get = hook
    m = go(cfg, web, T0)
    assert m["status"] == "interrupted"
    assert (Store(cfg.data_dir).manifests / f"{m['run_id']}.json").exists()


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
