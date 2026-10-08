"""Principe de référence : toute donnée remonte à sa source, de façon vérifiable.

Chaîne d'une référence :
  élément (source:id+version)
    → source publique canonique (ex. https://arxiv.org/abs/2610.01234v2)
    → blob local (SHA256 des octets reçus) — contient l'élément, vérifié par re-parsing
    → manifeste du run (URL interrogée, date, commit git, hash du code et de la config)

Une référence qui ne se résout pas jusqu'au bout est un défaut, pas un détail.
"""

import json

from .audit import parse_fetch
from .store import Store, sha256


def canonical_url(source: str, item_id: str, version: str, meta: dict) -> str:
    if source == "arxiv":
        return f"https://arxiv.org/abs/{item_id}{version}"
    if source == "inspire":
        return f"https://inspirehep.net/literature/{item_id}"
    return meta.get("link", "")


def resolve(store: Store, source: str, item_id: str, version: str | None = None) -> list[dict]:
    q = "SELECT source,item_id,version,title,meta,first_run,fetch_sha256 FROM items WHERE source=? AND item_id=?"
    args = [source, item_id]
    if version:
        q += " AND version=?"
        args.append(version)
    out = []
    for src, iid, ver, title, meta, run_id, fsha in store.db.execute(q + " ORDER BY version", args):
        meta = json.loads(meta or "{}")
        ref = {"element": f"{src}:{iid}{ver if src == 'arxiv' else ''}", "titre": title,
               "source_publique": canonical_url(src, iid, ver, meta),
               "blob_sha256": fsha, "run": run_id, "verifie": False, "probleme": None}
        mpath = store.manifests / f"{run_id}.json"
        try:
            raw = store.get_blob(fsha)
            if sha256(raw) != fsha:
                raise ValueError("hash du blob invalide")
            m = json.loads(mpath.read_bytes())
            fetch = next((f for f in m["fetches"] if f.get("sha256") == fsha), None)
            if fetch is None:
                raise ValueError("blob absent du manifeste de son run")
            keys = {(it.source, it.item_id, it.version)
                    for it in parse_fetch(fetch["kind"], raw, fetch["key"])}
            if (src, iid, ver) not in keys:
                raise ValueError("le blob ne contient pas l'élément")
            ref.update(url_interrogee=fetch["url"], recu_le=fetch["fetched_at"],
                       commit=m.get("git", {}).get("commit"), code_sha256=m["code_sha256"],
                       verifie=True)
        except (OSError, ValueError, KeyError) as e:
            ref["probleme"] = str(e)
        out.append(ref)
    return out
