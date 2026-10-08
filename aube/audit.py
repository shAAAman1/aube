"""Audit du critère de phase 1 : « deux semaines de flux archivés sans perte ni doublon ».

Chaque contrôle est réfutable : il peut échouer, et il dit pourquoi.
L'audit relit les données PRIMAIRES (manifestes + blobs) et rejoue l'indexation
pour la comparer à l'index SQLite. Rien n'est cru sur parole.
"""

import gzip
import json
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
from email.utils import parsedate_to_datetime

from .sources import arxiv, cern, inspire
from .store import Store, sha256

KIND_SOURCE = {"arxiv_api": "arxiv", "arxiv_oai": "arxiv", "arxiv_rss": "arxiv_witness",
               "cern_rss": "cern", "inspire": "inspire"}
WINDOW_SOURCE = {"arxiv_oai": "arxiv"}  # nom de la source dans les erreurs du manifeste
WITNESS_MIN_SPAN = 7                    # jours : une semaine contient toujours des annonces
WITNESS_GRACE = timedelta(hours=24)
STALE_AFTER = timedelta(hours=36)


def _dt(s):
    return datetime.strptime(s, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)


def _day_end(d: str) -> datetime:
    """Fin d'un jour clos 'AAAA-MM-JJ' (UTC) : minuit du lendemain."""
    return datetime.combine(date.fromisoformat(d) + timedelta(days=1), datetime.min.time(),
                            tzinfo=timezone.utc)


def _rfc822(s):
    try:
        d = parsedate_to_datetime(s)
    except (TypeError, ValueError):
        return None
    return d if d.tzinfo else d.replace(tzinfo=timezone.utc)


def parse_fetch(kind, raw, key):
    if kind == "arxiv_oai":
        return arxiv.parse_oai(raw)[0]
    if kind == "arxiv_api":  # collecte abandonnée le 2026-10-04, rejouée pour l'historique
        return arxiv.parse_api(raw)[0]
    if kind == "cern_rss":
        return cern.parse_feed(raw, key)
    if kind == "inspire":
        return inspire.parse_page(raw)[0]
    raise ValueError(kind)


def audit(data_dir, now=None, days=14) -> dict:
    now = now or datetime.now(timezone.utc)
    store = Store(data_dir)
    manifests = sorted(store.manifests.glob("*.json"))
    checks = defaultdict(list)          # nom -> liste de problèmes
    replay = set()                      # (source, item_id, version)
    cern_seen, cern_newest = set(), None
    witness = []                        # (fetched_at, cat, id, version, atype)
    witness_live = defaultdict(list)    # cat -> dates des lectures RSS non vides
    windows = defaultdict(list)
    runs = []

    for mpath in manifests:
        m = json.loads(mpath.read_bytes())
        runs.append(m)
        cern_run = []                   # éléments CERN de ce run, toutes pages confondues
        failed = {(e["source"], e["key"]) for e in m.get("errors", [])}
        for w in m.get("windows", []):
            if w["complete"] and (WINDOW_SOURCE.get(w["source"], w["source"]), w["key"]) not in failed:
                windows[(w["source"], w["key"])].append(w)
        for f in m["fetches"]:
            if f.get("status") != "ok":
                continue
            # 1. intégrité : le blob existe et son contenu a bien le hash consigné
            p = store.blob_path(f["sha256"])
            if not p.exists():
                checks["blob_manquant"].append(f"{m['run_id']} #{f['seq']} {f['sha256']}")
                continue
            raw = gzip.decompress(p.read_bytes())
            if sha256(raw) != f["sha256"]:
                checks["hash_invalide"].append(f"{m['run_id']} #{f['seq']} {p}")
                continue
            source = KIND_SOURCE[f["kind"]]
            if (source, f["key"]) in failed:
                continue  # le run a annulé cette source (réponse rejetée, erreur déjà comptée)
            # Une réponse archivée que le parseur actuel rejette ne doit pas faire planter
            # l'audit : les manifestes sont permanents, il ne tournerait plus jamais.
            try:
                if f["kind"] == "arxiv_rss":
                    rows = arxiv.parse_rss(raw)
                else:
                    items = parse_fetch(f["kind"], raw, f["key"])
            except Exception as e:
                checks["blob_illisible"].append(
                    f"{m['run_id']} #{f['seq']} {f['kind']} : {type(e).__name__}: {e}")
                continue
            if f["kind"] == "arxiv_rss":
                witness += [(f["fetched_at"], f["key"], *r) for r in rows]
                if rows:
                    witness_live[f["key"]].append(_dt(f["fetched_at"]).date())
                continue
            if f["kind"] == "cern_rss":
                cern_run += items
            replay |= {(it.source, it.item_id, it.version) for it in items}

        # 2a. continuité d'un flux à fenêtre glissante, jugée sur l'union des pages du run :
        # il faut un élément déjà vu ET que le plus ancien élément lu ne soit pas plus récent
        # que tout ce qu'on avait déjà (un vieux billet re-daté fournirait sinon un faux
        # point commun et masquerait le trou).
        if cern_run:
            ids = {it.item_id for it in cern_run}
            dates = [d for d in (_rfc822(it.published) for it in cern_run) if d]
            if cern_seen and not (ids & cern_seen):
                checks["cern_trou_possible"].append(
                    f"{m['run_id']} : aucun élément commun avec les runs précédents")
            elif cern_newest and dates and min(dates) > cern_newest:
                checks["cern_trou_possible"].append(
                    f"{m['run_id']} : élément le plus ancien {min(dates):%Y-%m-%d %H:%M} postérieur "
                    f"à tout ce qui avait été vu ({cern_newest:%Y-%m-%d %H:%M})")
            cern_seen |= ids
            if dates:
                cern_newest = max([cern_newest, *dates] if cern_newest else dates)

    # 2b. continuité des fenêtres arXiv / INSPIRE : aucune zone de temps non couverte.
    # « arxiv » = ancienne API (instants), « arxiv_oai » et « inspire » = jours clos inclus.
    for (source, key), ws in windows.items():
        if source not in ("arxiv", "arxiv_oai", "inspire"):
            continue
        ws.sort(key=lambda w: w["since"])
        reach = ws[0]["until"]
        for w in ws[1:]:
            gap = (w["since"] > reach) if source == "arxiv" else (
                date.fromisoformat(w["since"]) > date.fromisoformat(reach) + timedelta(days=1))
            if gap:
                checks["trou_de_fenetre"].append(f"{source}/{key} : rien entre {reach} et {w['since']}")
            reach = max(reach, w["until"])
        # OAI-PMH rend une fenêtre (éventuellement vide) même le week-end : pas de faux retard.
        if source == "arxiv_oai" and now - _day_end(reach) > STALE_AFTER:
            checks["source_en_retard"].append(f"arxiv_oai/{key} : dernière fenêtre complète {reach}")

    # 3. témoin indépendant : tout ce que le RSS annonce doit être dans l'archive.
    # Un flux lu le jour J ne contient que des annonces de datestamp <= J. Mais la datestamp
    # suit la DERNIÈRE modification : un article remplacé (ou corrigé) le jour J+1 n'est
    # moissonné qu'au run J+2. On juge donc le témoin lu le jour J quand l'OAI couvre J+1.
    # Pour l'ancienne API, on gardait une marge de 24 h.
    limit_by_cat = {}
    for (s, k), ws in windows.items():
        u = max(w["until"] for w in ws)
        if s == "arxiv_oai":
            lim = _day_end(u) - timedelta(days=1, microseconds=1)
        elif s == "arxiv":
            lim = _dt(u) - WITNESS_GRACE
        else:
            continue
        limit_by_cat[k] = max(lim, limit_by_cat.get(k, lim))
    witness_checked = 0
    for fetched_at, cat, item_id, version, atype in witness:
        lim = limit_by_cat.get(cat)
        if lim is None or _dt(fetched_at) > lim:
            continue  # trop récent pour juger
        witness_checked += 1
        if ("arxiv", item_id, version) not in replay:
            has_id = any(k[0] == "arxiv" and k[1] == item_id for k in replay) if version else False
            tag = "temoin_version_absente" if has_id else "temoin_absent"
            checks[tag].append(f"{cat} {item_id}{version} ({atype}) annoncé {fetched_at}")

    # 3b. témoin inactif : pour arXiv (OAI ne donne aucun total), le témoin est le SEUL
    # contrôle de complétude. S'il ne produit plus rien (format changé, flux déplacé), il faut
    # le dire plutôt que conclure « aucun témoin absent ». Jugé sur la partie de l'horizon
    # couverte par l'archive, dès qu'elle atteint une semaine.
    horizon_day = now.date() - timedelta(days=days - 1)
    first_day = min((datetime.strptime(m["run_id"][:8], "%Y%m%d").date() for m in runs), default=None)
    if first_day:
        start = max(horizon_day, first_day)
        if (now.date() - start).days + 1 >= WITNESS_MIN_SPAN:
            for cat in sorted({k for (s, k) in windows if s == "arxiv_oai"}):
                if not any(d >= start for d in witness_live.get(cat, [])):
                    checks["temoin_inactif"].append(
                        f"{cat} : aucune annonce lue dans le RSS depuis le {start}")

    # 4. l'index SQLite est-il exactement ce que le rejeu des données primaires produit ?
    indexed = set(store.db.execute("SELECT source, item_id, version FROM items"))
    if indexed != replay:
        checks["index_non_rejouable"].append(
            f"{len(indexed - replay)} dans l'index seulement, {len(replay - indexed)} dans le rejeu seulement")

    # 5. doublons sémantiques (même objet sous deux clés)
    for row in store.db.execute(
            "SELECT lower(trim(item_id)), version, count(*) FROM items WHERE source='arxiv' "
            "GROUP BY 1,2 HAVING count(*) > 1"):
        checks["doublon_arxiv"].append(str(row))
    for row in store.db.execute(
            "SELECT json_extract(meta,'$.link'), count(DISTINCT item_id) FROM items "
            "WHERE source='cern' GROUP BY 1 HAVING count(DISTINCT item_id) > 1"):
        checks["doublon_cern"].append(str(row))

    # 6. erreurs de run : seules celles de la fenêtre du critère (`days` derniers jours) bloquent.
    # Les manifestes ne sont jamais supprimés : sans cette borne, une seule erreur ancienne
    # rendrait le critère inatteignable pour toujours. Les plus anciennes restent affichées.
    horizon = (now.date() - timedelta(days=days - 1)).strftime("%Y%m%d")
    old_errors = []
    for m in runs:
        for e in m.get("errors", []):
            line = f"{m['run_id']} {e['source']}/{e['key']} : {e['error']}"
            (checks["erreur_de_run"] if m["run_id"][:8] >= horizon else old_errors).append(line)

    # Critère : `days` jours consécutifs (jusqu'à aujourd'hui) avec un run sans erreur.
    ok_days = {m["run_id"][:8] for m in runs if m.get("status") == "ok"}
    streak, d = 0, now.date()
    while d.strftime("%Y%m%d") in ok_days:
        streak += 1
        d -= timedelta(days=1)

    blocking = bool(checks)  # tout problème bloque le critère
    counts = dict(store.db.execute("SELECT source, count(*) FROM items GROUP BY 1").fetchall())
    return {
        "date": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "runs": len(runs),
        "jours_consecutifs_ok": streak,
        "objectif_jours": days,
        "items_par_source": counts,
        "temoins_verifies": witness_checked,
        "problemes": {k: v for k, v in checks.items()},
        "erreurs_hors_fenetre": old_errors,
        "critere_phase1": "ATTEINT" if streak >= days and not blocking else "NON ATTEINT",
    }


def render(rep: dict) -> str:
    lines = [f"Audit Aube — {rep['date']}",
             f"Runs : {rep['runs']} · jours consécutifs sans erreur : "
             f"{rep['jours_consecutifs_ok']}/{rep['objectif_jours']}",
             f"Éléments indexés : {rep['items_par_source']}",
             f"Annonces du témoin RSS vérifiées : {rep['temoins_verifies']}"]
    if not rep["problemes"]:
        lines.append("Aucun problème détecté.")
    for k, v in rep["problemes"].items():
        lines.append(f"✗ {k} ({len(v)})")
        lines += [f"    {x}" for x in v[:10]]
        if len(v) > 10:
            lines.append(f"    … {len(v) - 10} de plus")
    if rep["erreurs_hors_fenetre"]:
        lines.append(f"(info) {len(rep['erreurs_hors_fenetre'])} erreur(s) de run antérieure(s) "
                     f"à la fenêtre de {rep['objectif_jours']} jours, non bloquante(s)")
    lines.append(f"Critère phase 1 : {rep['critere_phase1']}")
    return "\n".join(lines)
