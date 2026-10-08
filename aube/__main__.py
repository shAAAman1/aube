"""Usage : python -m aube [-c config.toml] {collect,audit,verify}"""

import argparse
import json
import sys
from pathlib import Path

from . import audit as audit_mod
from . import collect, config
from .store import Store, sha256


def main(argv=None):
    ap = argparse.ArgumentParser(prog="aube")
    ap.add_argument("-c", "--config", default=str(Path.cwd() / "config.toml"))
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("collect", help="un run de collecte")
    a = sub.add_parser("audit", help="vérifie le critère de phase 1")
    a.add_argument("--json", action="store_true")
    a.add_argument("--days", type=int, default=14)
    sub.add_parser("verify", help="recalcule le SHA256 de tous les blobs")
    r = sub.add_parser("ref", help="résout la chaîne de référence d'un élément")
    r.add_argument("element", help="ex. arxiv:2610.01234v2, arxiv:2610.01234, inspire:123456")
    args = ap.parse_args(argv)
    cfg = config.load(args.config)

    if args.cmd == "collect":
        m = collect.run(cfg)
        n = sum(1 for f in m["fetches"] if f.get("status") == "ok")
        print(f"run {m['run_id']} : {m['status']} · {n} requêtes OK · {len(m['errors'])} erreur(s)")
        for e in m["errors"]:
            print(f"  ✗ {e['source']}/{e['key']} : {e['error']}", file=sys.stderr)
        return 0 if m["status"] == "ok" else 1

    if args.cmd == "audit":
        rep = audit_mod.audit(cfg.data_dir, days=args.days)
        print(json.dumps(rep, ensure_ascii=False, indent=1) if args.json else audit_mod.render(rep))
        return 0 if rep["critere_phase1"] == "ATTEINT" else 2

    if args.cmd == "ref":
        from .ref import resolve
        from .sources.arxiv import split_id
        src, _, ident = args.element.partition(":")
        ver = None
        if src == "arxiv":
            ident, ver = split_id("arXiv:" + ident)
        refs = resolve(Store(cfg.data_dir), src, ident, ver or None)
        if not refs:
            print(f"✗ {args.element} : inconnu de l'archive")
            return 1
        print(json.dumps(refs, ensure_ascii=False, indent=1))
        return 0 if all(x["verifie"] for x in refs) else 1

    if args.cmd == "verify":
        store, bad, n = Store(cfg.data_dir), 0, 0
        for p in sorted(store.blobs.rglob("*.gz")):
            n += 1
            if sha256(store.get_blob(p.name[:-3])) != p.name[:-3]:
                bad += 1
                print(f"✗ {p}")
        print(f"{n} blobs vérifiés, {bad} corrompu(s)")
        return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
