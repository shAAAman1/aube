"""Récupération HTTP minimale (stdlib). Seul point d'accès réseau du projet."""

import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from urllib.parse import urlparse

RETRY_STATUS = {429, 500, 502, 503, 504}


@dataclass
class Response:
    url: str
    status: int
    body: bytes
    content_type: str


class FetchError(Exception):
    pass


class Fetcher:
    def __init__(self, user_agent: str, timeout_s: float = 60, max_bytes: int = 50_000_000,
                 retries: int = 4, sleep=time.sleep):
        self.user_agent = user_agent
        self.timeout_s = timeout_s
        self.max_bytes = max_bytes
        self.retries = retries
        self.sleep = sleep

    def get(self, url: str) -> Response:
        if urlparse(url).scheme != "https":
            raise FetchError(f"schéma refusé (https seulement) : {url}")
        last = None
        for attempt in range(self.retries + 1):
            if attempt:
                self.sleep(min(60, 5 * 2 ** (attempt - 1)))
            try:
                req = urllib.request.Request(url, headers={"User-Agent": self.user_agent})
                with urllib.request.urlopen(req, timeout=self.timeout_s) as r:
                    body = r.read(self.max_bytes + 1)
                    if len(body) > self.max_bytes:
                        raise FetchError(f"réponse > {self.max_bytes} octets : {url}")
                    return Response(url=url, status=r.status, body=body,
                                    content_type=r.headers.get("Content-Type", ""))
            except urllib.error.HTTPError as e:
                last = f"HTTP {e.code}"
                if e.code not in RETRY_STATUS:
                    break
            except (urllib.error.URLError, TimeoutError, ConnectionError) as e:
                last = f"{type(e).__name__}: {e}"
        raise FetchError(f"{last} — {url}")
