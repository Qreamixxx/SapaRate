"""Tiny HTTP helper on the standard library (so no requests/httpx dependency)."""
import json
import socket
import urllib.error
import urllib.request

USER_AGENT = "cqa-prototype/1.0"


class HttpError(Exception):
    def __init__(self, status: int, body: str, headers: dict | None = None):
        super().__init__(f"HTTP {status}: {body[:300]}")
        self.status = status
        self.body = body
        self.headers = headers or {}


def request(url: str, method: str = "GET", data=None, headers: dict | None = None,
            timeout: float = 120, max_bytes: int | None = None):
    """Returns (status, headers_lowercase, body_bytes). Raises HttpError on 4xx/5xx."""
    h = {"User-Agent": USER_AGENT, **(headers or {})}
    body = None
    if data is not None:
        body = json.dumps(data, ensure_ascii=False).encode("utf-8")
        h.setdefault("Content-Type", "application/json")
    req = urllib.request.Request(url, data=body, headers=h, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            raw = r.read(max_bytes) if max_bytes else r.read()
            return r.status, {k.lower(): v for k, v in r.headers.items()}, raw
    except urllib.error.HTTPError as e:
        text = e.read().decode("utf-8", "replace")
        raise HttpError(e.code, text, {k.lower(): v for k, v in (e.headers or {}).items()}) from None
    except urllib.error.URLError as e:
        raise HttpError(0, f"Нет соединения: {e.reason}") from None
    except (TimeoutError, socket.timeout):
        raise HttpError(0, "Таймаут: сервер не ответил вовремя") from None


def get_json(url: str, timeout: float = 60):
    _, _, raw = request(url, timeout=timeout)
    return json.loads(raw.decode("utf-8"))


def post_json(url: str, data, headers: dict | None = None, timeout: float = 180):
    _, _, raw = request(url, method="POST", data=data, headers=headers, timeout=timeout)
    return json.loads(raw.decode("utf-8"))
