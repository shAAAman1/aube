"""Récupération HTTP minimale (stdlib). Seul point d'accès réseau du projet."""

import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
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


class _HttpsOnlyRedirect(urllib.request.HTTPRedirectHandler):
    """urllib suit par défaut une redirection vers http:// : on la refuse."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        if urlparse(newurl).scheme != "https":
            raise FetchError(f"redirection refusée hors https : {req.full_url} → {newurl}")
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def retry_after_s(value: str | None, now: datetime | None = None) -> float | None:
    """En-tête Retry-After (RFC 9110) : délai en secondes ou date HTTP. None si absent ou illisible."""
    value = (value or "").strip()
    if not value:
        return None
    if value.isdigit():
        return float(value)
    try:
        when = parsedate_to_datetime(value)
    except (TypeError, ValueError):
        return None
    if when.tzinfo is None:
        when = when.replace(tzinfo=timezone.utc)
    return max(0.0, (when - (now or datetime.now(timezone.utc))).total_seconds())


class Fetcher:
    def __init__(self, user_agent: str, timeout_s: float = 60, max_bytes: int = 50_000_000,
                 retries: int = 4, sleep=time.sleep, max_retry_after_s: float = 600):
        self.user_agent = user_agent
        self.timeout_s = timeout_s
        self.max_bytes = max_bytes
        self.retries = retries
        self.sleep = sleep
        # Au-delà, on abandonne plutôt que de bloquer le run : l'échec est consigné et rattrapé.
        self.max_retry_after_s = max_retry_after_s
        self.opener = urllib.request.build_opener(_HttpsOnlyRedirect)

    def get(self, url: str) -> Response:
        if urlparse(url).scheme != "https":
            raise FetchError(f"schéma refusé (https seulement) : {url}")
        last, wait = None, None
        for attempt in range(self.retries + 1):
            if attempt:
                # Le serveur peut exiger plus que notre backoff : on respecte le plus long des deux.
                self.sleep(max(min(60, 5 * 2 ** (attempt - 1)), wait or 0))
            wait = None
            try:
                req = urllib.request.Request(url, headers={"User-Agent": self.user_agent})
                with self.opener.open(req, timeout=self.timeout_s) as r:
                    body = r.read(self.max_bytes + 1)
                    if len(body) > self.max_bytes:
                        raise FetchError(f"réponse > {self.max_bytes} octets : {url}")
                    return Response(url=r.geturl(), status=r.status, body=body,
                                    content_type=r.headers.get("Content-Type", ""))
            except urllib.error.HTTPError as e:
                last = f"HTTP {e.code}"
                if e.code not in RETRY_STATUS:
                    break
                wait = retry_after_s(e.headers.get("Retry-After") if e.headers else None)
                if wait is not None:
                    last += f" (Retry-After {wait:.0f} s)"
                    if wait > self.max_retry_after_s:
                        break
            except (urllib.error.URLError, TimeoutError, ConnectionError) as e:
                last = f"{type(e).__name__}: {e}"
        raise FetchError(f"{last} — {url}")
