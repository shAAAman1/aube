"""Run de collecte : interroge les sources, archive les octets bruts, indexe, écrit le manifeste."""

import fcntl
import platform
import time
from datetime import date, datetime, timedelta, timezone

from . import __version__, code_hash, git_state
from .http import FetchError, Fetcher
from .sources import arxiv, cern, inspire
from .store import Store


def _iso(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def _parse_iso(s: str) -> datetime:
    return datetime.strptime(s, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)


class Run:
    def __init__(self, cfg, store: Store, fetcher: Fetcher, now: datetime, sleep=time.sleep,
                 clock=None):
        self.cfg, self.store, self.fetcher, self.sleep = cfg, store, fetcher, sleep
        self.clock = clock or (lambda: datetime.now(timezone.utc))
        self.now = now.replace(second=0, microsecond=0)
        self.run_id = self.now.strftime("%Y%m%dT%H%MZ")
        self.manifest = {
            "run_id": self.run_id, "started_at": _iso(self.clock()),
            "aube_version": __version__, "code_sha256": code_hash(), "git": git_state(),
            "config_sha256": cfg.sha256, "python": platform.python_version(),
            "fetches": [], "windows": [], "errors": [],
        }

    # --- primitives ----------------------------------------------------------
    def fetch(self, kind: str, key: str, url: str) -> tuple[bytes, str]:
        entry = {"seq": len(self.manifest["fetches"]), "kind": kind, "key": key, "url": url,
                 "fetched_at": _iso(self.clock())}
        self.manifest["fetches"].append(entry)
        try:
            r = self.fetcher.get(url)
        except FetchError as e:
            entry.update(status="error", error=str(e))
            raise
        digest = self.store.put_blob(r.body)
        entry.update(status="ok", http=r.status, sha256=digest, bytes=len(r.body),
                     content_type=r.content_type)
        return r.body, digest

    def error(self, source: str, key: str, exc: Exception):
        self.manifest["errors"].append({"source": source, "key": key,
                                        "error": f"{type(exc).__name__}: {exc}"})

    def window(self, source, key, since, until, expected, received):
        complete = expected is None or received == expected
        w = {"source": source, "key": key, "since": since, "until": until,
             "expected": expected, "received": received, "complete": complete}
        self.manifest["windows"].append(w)
        self.store.db.execute("INSERT INTO windows VALUES (?,?,?,?,?,?,?,?)",
                              (self.run_id, source, key, since, until, expected, received,
                               int(complete)))
        return complete

    # --- sources -------------------------------------------------------------
    def arxiv_category(self, cat: str):
        """OAI-PMH arXivRaw par jours de datestamp clos (jusqu'à hier UTC inclus).

        OAI-PMH ne donne aucun total (pas de completeListSize) : la complétude d'une fenêtre
        repose sur le suivi des jetons jusqu'à leur absence, et sur le témoin RSS.
        """
        c = self.cfg.section("arxiv")
        until = (self.now - timedelta(days=1)).date()
        last = self.store.last_complete_until("arxiv_oai", cat)
        base = date.fromisoformat(last) if last else until
        since = base - timedelta(days=c["overlap_days"])
        keys, day = set(), since
        while day <= until:
            keys |= self._oai_day(cat, c["sets"][cat], day, c["delay_s"])
            day += timedelta(days=1)
        self.window("arxiv_oai", cat, since.isoformat(), until.isoformat(), None, len(keys))

    def _oai_day(self, cat: str, set_spec: str, day: date, delay: float) -> set:
        """Un seul jour de datestamp par requête, jamais une fenêtre de plusieurs jours.

        Les jetons sont sans état (from + skip) : si un enregistrement déjà servi change de
        datestamp pendant la pagination, la page suivante saute un enregistrement. Sur un jour
        clos, un tel enregistrement part vers aujourd'hui (relu au prochain run) ; celui qui
        a été sauté reste dans le jour : une seconde passe complète le récupère. Elle n'a lieu
        que si le jour a demandé plus d'une page (~1300 enregistrements, jamais vu à ce jour).
        """
        keys, passes = set(), 0
        while True:
            passes += 1
            token, pages, tokens_seen = None, 0, set()
            while True:
                body, digest = self.fetch("arxiv_oai", cat, arxiv.oai_url(set_spec, day, day, token))
                items, token, n = arxiv.parse_oai(body)
                self.sleep(delay)
                pages += 1
                self.manifest["fetches"][-1].update(n_items=len(items), n_records=n)
                self.store.add_items(items, self.run_id, digest)
                keys |= {(it.item_id, it.version) for it in items}
                if not token:
                    break
                if n == 0:
                    raise arxiv.ArxivError("page OAI-PMH vide suivie d'un resumptionToken")
                if token in tokens_seen:
                    raise arxiv.ArxivError(f"resumptionToken répété : {token}")
                tokens_seen.add(token)
            if pages == 1 or passes == 2:
                return keys

    def arxiv_witness(self, cat: str):
        body, digest = self.fetch("arxiv_rss", cat, arxiv.RSS.format(cat=cat))
        rows = arxiv.parse_rss(body)
        self.manifest["fetches"][-1]["n_items"] = len(rows)
        for item_id, version, atype in rows:
            self.store.db.execute("INSERT OR IGNORE INTO witness VALUES (?,?,?,?,?,?)",
                                  (self.run_id, cat, item_id, version, atype, digest))

    def cern_feed(self, url: str):
        body, digest = self.fetch("cern_rss", url, url)
        items = cern.parse_feed(body, url)
        already = sum(self.store.known("cern", it.item_id) for it in items)
        f = self.manifest["fetches"][-1]
        f.update(n_items=len(items), n_already_known=already)
        self.store.add_items(items, self.run_id, digest)
        self.window("cern", url, _iso(self.now), _iso(self.now), None, len(items))

    def inspire(self):
        c = self.cfg.section("inspire")
        until = (self.now - timedelta(days=1)).date()  # fenêtre close : jusqu'à hier inclus
        last = self.store.last_complete_until("inspire", "literature")
        base = datetime.fromisoformat(last).date() if last else until
        since = base - timedelta(days=c["overlap_days"])
        # Après une longue panne, rattrapage par morceaux : une fenêtre trop large dépasserait
        # MAX_DEPTH et échouerait à chaque run sans jamais avancer.
        until = min(until, since + timedelta(days=c.get("max_window_days", 14) - 1))
        page, expected, n, seen = 1, None, 0, set()
        while True:
            url = inspire.api_url(c["query"], since, until, c["page_size"], c["fields"], page)
            body, digest = self.fetch("inspire", "literature", url)
            items, total, _ = inspire.parse_page(body)
            self.sleep(c["delay_s"])
            if expected is None:
                expected = total
                if total > inspire.MAX_DEPTH:
                    raise inspire.InspireError(f"{total} résultats > {inspire.MAX_DEPTH} : réduire la fenêtre")
            elif total != expected:
                raise inspire.InspireError(f"total instable pendant la pagination ({expected}→{total})")
            self.manifest["fetches"][-1]["n_items"] = len(items)
            self.store.add_items(items, self.run_id, digest)
            n += len(items)
            seen |= {it.item_id for it in items}
            if not items or n >= expected:
                break
            page += 1
        # Pagination page/size sans instantané : un enregistrement modifié pendant le run peut
        # glisser d'une page à l'autre (doublon + saut). On compte donc les identifiants distincts.
        if len(seen) != n:
            raise inspire.InspireError(f"pagination décalée : {n} reçus, {len(seen)} distincts")
        if not self.window("inspire", "literature", since.isoformat(), until.isoformat(),
                           expected, len(seen)):
            raise inspire.InspireError(f"fenêtre incomplète : {len(seen)}/{expected}")

    # --- orchestration ---------------------------------------------------------
    def execute(self) -> dict:
        db = self.store.db
        db.execute("INSERT INTO runs (run_id, started_at) VALUES (?,?)",
                   (self.run_id, self.manifest["started_at"]))
        db.commit()  # sinon le rollback d'une première source en échec efface aussi cette ligne
        jobs = [("arxiv", cat, lambda c=cat: self.arxiv_category(c))
                for cat in self.cfg.section("arxiv").get("categories", [])]
        if self.cfg.section("arxiv_witness").get("enabled", True):
            jobs += [("arxiv_witness", cat, lambda c=cat: self.arxiv_witness(c))
                     for cat in self.cfg.section("arxiv").get("categories", [])]
        jobs += [("cern", u, lambda u=u: self.cern_feed(u))
                 for u in self.cfg.section("cern").get("feeds", [])]
        if self.cfg.section("inspire").get("enabled", False):
            jobs.append(("inspire", "literature", self.inspire))

        for source, key, job in jobs:
            try:
                job()
                db.commit()  # chaque source validée indépendamment
            except Exception as e:  # une source en panne n'arrête pas les autres
                db.rollback()
                self.error(source, key, e)
                # le rollback a effacé la fenêtre éventuelle : la consigner au manifeste suffit

        m = self.manifest
        m["finished_at"] = _iso(self.clock())
        m["status"] = "ok" if not m["errors"] else "partial"
        digest = self.store.write_manifest(self.run_id, m)
        db.execute("UPDATE runs SET finished_at=?, status=?, manifest_sha256=? WHERE run_id=?",
                   (m["finished_at"], m["status"], digest, self.run_id))
        db.commit()
        return m


def run(cfg, now: datetime | None = None, fetcher: Fetcher | None = None, sleep=time.sleep,
        clock=None) -> dict:
    g = cfg.section("general")
    store = Store(cfg.data_dir)
    lock = open(cfg.data_dir / ".lock", "w")
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        raise SystemExit("un autre run est en cours (verrou data/.lock)")
    fetcher = fetcher or Fetcher(g["user_agent"], g.get("timeout_s", 60),
                                 g.get("max_bytes", 50_000_000), g.get("retries", 4))
    return Run(cfg, store, fetcher, now or datetime.now(timezone.utc), sleep, clock).execute()
