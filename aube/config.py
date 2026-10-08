import hashlib
import tomllib
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Config:
    root: Path
    raw: dict
    sha256: str

    @property
    def data_dir(self) -> Path:
        return (self.root / self.raw["general"]["data_dir"]).resolve()

    def section(self, name: str) -> dict:
        return self.raw.get(name, {})


def _merge(a: dict, b: dict) -> dict:
    out = dict(a)
    for k, v in b.items():
        out[k] = _merge(out[k], v) if isinstance(v, dict) and isinstance(out.get(k), dict) else v
    return out


def load(path: Path) -> Config:
    """config.toml (versionné) + config.local.toml facultatif (non versionné : contact, chemins).

    Le hash couvre les deux fichiers : un run reste rattaché à sa configuration exacte.
    """
    path = Path(path).resolve()
    data = path.read_bytes()
    raw = tomllib.loads(data.decode("utf-8"))
    h = hashlib.sha256(data)
    local = path.with_name("config.local.toml")
    if local.exists():
        ldata = local.read_bytes()
        raw = _merge(raw, tomllib.loads(ldata.decode("utf-8")))
        h.update(b"\0local\0" + ldata)
    return Config(root=path.parent, raw=raw, sha256=h.hexdigest())
