"""Aube — veille physique locale. Phase 1 : collecte et archive."""

import hashlib
from pathlib import Path

__version__ = "0.1.0"

PKG_DIR = Path(__file__).resolve().parent


def code_hash() -> str:
    """SHA256 du code source du paquet (fichiers .py triés par chemin).

    Consigné dans chaque manifeste : on sait exactement quel code a produit un run.
    """
    h = hashlib.sha256()
    for p in sorted(PKG_DIR.rglob("*.py")):
        h.update(p.relative_to(PKG_DIR).as_posix().encode())
        h.update(b"\0")
        h.update(p.read_bytes())
        h.update(b"\0")
    return h.hexdigest()


def git_state() -> dict:
    """Commit et état « sale » du dépôt, si le code tourne depuis un clone git."""
    import subprocess
    root = PKG_DIR.parent
    try:
        rev = subprocess.run(["git", "-C", str(root), "rev-parse", "HEAD"],
                             capture_output=True, text=True, timeout=5)
        if rev.returncode != 0:
            return {}
        dirty = subprocess.run(["git", "-C", str(root), "status", "--porcelain", "--", "aube"],
                               capture_output=True, text=True, timeout=5).stdout.strip()
        return {"commit": rev.stdout.strip(), "dirty": bool(dirty)}
    except (OSError, subprocess.TimeoutExpired):
        return {}
