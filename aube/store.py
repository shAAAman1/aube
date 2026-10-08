"""Archive brute adressée par contenu + index SQLite dérivé.

Hiérarchie de confiance :
  1. blobs/      octets bruts tels que reçus, nommés par leur SHA256 (gzip, mtime=0)
  2. manifests/  un JSON par run : chaque requête, son hash, ses fenêtres
  3. aube.sqlite index dérivé, reconstructible à partir de 1 + 2 (voir audit)
"""

import gzip
import hashlib
import json
import os
import sqlite3
from dataclasses import dataclass, field
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS items (
    source TEXT NOT NULL,
    item_id TEXT NOT NULL,
    version TEXT NOT NULL,
    title TEXT,
    published TEXT,
    updated TEXT,
    meta TEXT,
    first_run TEXT NOT NULL,
    fetch_sha256 TEXT NOT NULL,
    PRIMARY KEY (source, item_id, version)
);
CREATE TABLE IF NOT EXISTS windows (
    run_id TEXT NOT NULL,
    source TEXT NOT NULL,
    key TEXT NOT NULL,
    since TEXT NOT NULL,
    until TEXT NOT NULL,
    expected INTEGER,
    received INTEGER NOT NULL,
    complete INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS witness (
    run_id TEXT NOT NULL,
    key TEXT NOT NULL,
    item_id TEXT NOT NULL,
    version TEXT NOT NULL,
    announce_type TEXT,
    fetch_sha256 TEXT NOT NULL,
    PRIMARY KEY (run_id, key, item_id, version)
);
CREATE TABLE IF NOT EXISTS runs (
    run_id TEXT PRIMARY KEY,
    started_at TEXT NOT NULL,
    finished_at TEXT,
    status TEXT,
    manifest_sha256 TEXT
);
"""


@dataclass
class Item:
    source: str
    item_id: str
    version: str
    title: str = ""
    published: str = ""
    updated: str = ""
    meta: dict = field(default_factory=dict)


def sha256(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def _atomic_write(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    with open(tmp, "wb") as f:
        f.write(data)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path)


class Store:
    def __init__(self, data_dir: Path):
        self.dir = Path(data_dir)
        self.blobs = self.dir / "blobs"
        self.manifests = self.dir / "manifests"
        self.dir.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(self.dir / "aube.sqlite")
        self.db.executescript(SCHEMA)

    # --- blobs -------------------------------------------------------------
    def blob_path(self, digest: str) -> Path:
        return self.blobs / digest[:2] / f"{digest}.gz"

    def put_blob(self, data: bytes) -> str:
        digest = sha256(data)
        p = self.blob_path(digest)
        if not p.exists():
            # mtime=0 : le .gz est lui-même déterministe pour un contenu donné.
            _atomic_write(p, gzip.compress(data, compresslevel=6, mtime=0))
        return digest

    def get_blob(self, digest: str) -> bytes:
        return gzip.decompress(self.blob_path(digest).read_bytes())

    # --- index -------------------------------------------------------------
    def add_items(self, items, run_id: str, fetch_sha: str) -> tuple[int, int]:
        """Insère ; retourne (nouveaux, déjà connus). La clé interdit tout doublon."""
        new = 0
        for it in items:
            cur = self.db.execute(
                "INSERT OR IGNORE INTO items VALUES (?,?,?,?,?,?,?,?,?)",
                (it.source, it.item_id, it.version, it.title, it.published, it.updated,
                 json.dumps(it.meta, ensure_ascii=False, sort_keys=True), run_id, fetch_sha))
            new += cur.rowcount
        return new, len(items) - new

    def known(self, source: str, item_id: str, version: str | None = None) -> bool:
        if version is None:
            q = self.db.execute("SELECT 1 FROM items WHERE source=? AND item_id=? LIMIT 1",
                                (source, item_id))
        else:
            q = self.db.execute("SELECT 1 FROM items WHERE source=? AND item_id=? AND version=?",
                                (source, item_id, version))
        return q.fetchone() is not None

    def last_complete_until(self, source: str, key: str) -> str | None:
        r = self.db.execute(
            "SELECT max(until) FROM windows WHERE source=? AND key=? AND complete=1",
            (source, key)).fetchone()
        return r[0]

    def write_manifest(self, run_id: str, manifest: dict) -> str:
        data = json.dumps(manifest, ensure_ascii=False, sort_keys=True, indent=1).encode()
        _atomic_write(self.manifests / f"{run_id}.json", data)
        return sha256(data)

    def commit(self):
        self.db.commit()
