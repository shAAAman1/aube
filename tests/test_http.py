import email.message
import urllib.error
from datetime import datetime, timezone

import pytest

from aube import http
from aube.http import FetchError, Fetcher, retry_after_s

URL = "https://export.arxiv.org/api/query?x=1"
NOW = datetime(2026, 10, 4, 2, 0, tzinfo=timezone.utc)


class _Ok:
    status, headers = 200, {"Content-Type": "application/atom+xml"}

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def read(self, n):
        return b"<feed/>"


def _http_error(code, retry_after=None):
    h = email.message.Message()
    if retry_after is not None:
        h["Retry-After"] = retry_after
    return urllib.error.HTTPError(URL, code, "err", h, None)


@pytest.fixture
def script(monkeypatch):
    """Réponses successives de urlopen : exception à lever ou réponse à rendre."""
    queue = []

    def urlopen(req, timeout):
        x = queue.pop(0)
        if isinstance(x, Exception):
            raise x
        return x

    monkeypatch.setattr(http.urllib.request, "urlopen", urlopen)
    return queue


def test_retry_after_formats():
    assert retry_after_s("120") == 120
    assert retry_after_s(" 7 ") == 7
    assert retry_after_s("Sun, 04 Oct 2026 02:01:30 GMT", now=NOW) == 90
    assert retry_after_s("Sun, 04 Oct 2026 01:00:00 GMT", now=NOW) == 0  # date passée
    assert retry_after_s(None) is None
    assert retry_after_s("") is None
    assert retry_after_s("bientôt") is None


def test_503_retry_after_est_respecte(script):
    slept = []
    script += [_http_error(503, "42"), _Ok()]
    r = Fetcher("ua", sleep=slept.append).get(URL)
    assert r.status == 200
    assert slept == [42]  # et non le backoff par défaut de 5 s


def test_retry_after_plus_court_que_le_backoff(script):
    slept = []
    script += [_http_error(429, "1"), _Ok()]
    Fetcher("ua", sleep=slept.append).get(URL)
    assert slept == [5]  # le backoff minimal reste appliqué


def test_sans_retry_after_backoff_exponentiel(script):
    slept = []
    script += [_http_error(503), _http_error(503), _Ok()]
    Fetcher("ua", sleep=slept.append).get(URL)
    assert slept == [5, 10]


def test_retry_after_excessif_abandonne_sans_attendre(script):
    slept = []
    script += [_http_error(503, "86400"), _Ok()]
    with pytest.raises(FetchError, match=r"HTTP 503 \(Retry-After 86400 s\)"):
        Fetcher("ua", sleep=slept.append, max_retry_after_s=600).get(URL)
    assert slept == []


def test_404_pas_de_nouvel_essai(script):
    slept = []
    script += [_http_error(404, "10"), _Ok()]
    with pytest.raises(FetchError, match="HTTP 404"):
        Fetcher("ua", sleep=slept.append).get(URL)
    assert slept == []
