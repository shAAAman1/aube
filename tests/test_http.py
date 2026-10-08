import email.message
import io
import urllib.error
import urllib.request
import urllib.response
from datetime import datetime, timezone

import pytest

from aube.http import FetchError, Fetcher, _HttpsOnlyRedirect, retry_after_s

URL = "https://export.arxiv.org/api/query?x=1"
NOW = datetime(2026, 10, 4, 2, 0, tzinfo=timezone.utc)


class _Ok:
    status, headers = 200, {"Content-Type": "application/atom+xml"}

    def geturl(self):
        return URL

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def read(self, n):
        return b"<feed/>"


class _Opener:
    """Réponses successives : exception à lever ou réponse à rendre."""

    def __init__(self, queue):
        self.queue = queue

    def open(self, req, timeout):
        x = self.queue.pop(0)
        if isinstance(x, Exception):
            raise x
        return x


def _http_error(code, retry_after=None):
    h = email.message.Message()
    if retry_after is not None:
        h["Retry-After"] = retry_after
    return urllib.error.HTTPError(URL, code, "err", h, None)


def _fetcher(responses, slept, **kw):
    f = Fetcher("ua", sleep=slept.append, **kw)
    f.opener = _Opener(list(responses))
    return f


def test_retry_after_formats():
    assert retry_after_s("120") == 120
    assert retry_after_s(" 7 ") == 7
    assert retry_after_s("Sun, 04 Oct 2026 02:01:30 GMT", now=NOW) == 90
    assert retry_after_s("Sun, 04 Oct 2026 01:00:00 GMT", now=NOW) == 0  # date passée
    assert retry_after_s(None) is None
    assert retry_after_s("") is None
    assert retry_after_s("bientôt") is None


def test_503_retry_after_est_respecte():
    slept = []
    r = _fetcher([_http_error(503, "42"), _Ok()], slept).get(URL)
    assert r.status == 200
    assert slept == [42]  # et non le backoff par défaut de 5 s


def test_retry_after_plus_court_que_le_backoff():
    slept = []
    _fetcher([_http_error(429, "1"), _Ok()], slept).get(URL)
    assert slept == [5]  # le backoff minimal reste appliqué


def test_sans_retry_after_backoff_exponentiel():
    slept = []
    _fetcher([_http_error(503), _http_error(503), _Ok()], slept).get(URL)
    assert slept == [5, 10]


def test_retry_after_excessif_abandonne_sans_attendre():
    slept = []
    f = _fetcher([_http_error(503, "86400"), _Ok()], slept, max_retry_after_s=600)
    with pytest.raises(FetchError, match=r"HTTP 503 \(Retry-After 86400 s\)"):
        f.get(URL)
    assert slept == []


def test_404_pas_de_nouvel_essai():
    slept = []
    with pytest.raises(FetchError, match="HTTP 404"):
        _fetcher([_http_error(404, "10"), _Ok()], slept).get(URL)
    assert slept == []


def test_redirection_vers_http_refusee():
    # Observé le 2026-10-04 : https://home.cern/news/feed/ → 301 http://home.cern/feed/
    req = urllib.request.Request("https://home.cern/news/feed/")
    h = _HttpsOnlyRedirect()
    with pytest.raises(FetchError, match="hors https"):
        h.redirect_request(req, None, 301, "Moved", {}, "http://home.cern/feed/")
    ok = h.redirect_request(req, None, 301, "Moved", {}, "https://home.cern/feed/")
    assert ok.full_url == "https://home.cern/feed/"


def test_opener_refuse_redirection_http_de_bout_en_bout():
    """Chaîne urllib réelle (sans réseau) : un 301 vers http lève FetchError, sans requête http."""

    class Redirige(urllib.request.BaseHandler):
        handler_order = 100

        def https_open(self, req):
            hdrs = email.message.Message()
            hdrs["Location"] = "http://home.cern/feed/"
            r = urllib.response.addinfourl(io.BytesIO(b""), hdrs, req.full_url, 301)
            r.msg = "Moved"
            return r

        def http_open(self, req):
            raise AssertionError("requête http émise")

    f = Fetcher("ua", retries=0)
    f.opener.add_handler(Redirige())   # l'opener construit par Fetcher, pas un opener de test
    with pytest.raises(FetchError, match="hors https"):
        f.get("https://home.cern/news/feed/")


def test_schema_http_refuse():
    with pytest.raises(FetchError, match="https seulement"):
        Fetcher("ua", retries=0).get("http://home.cern/feed/")
