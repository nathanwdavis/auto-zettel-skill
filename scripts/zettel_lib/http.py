"""Fetch wrapper with an injectable transport.

Tests substitute a cassette transport so the metadata-lookup branches of
``verify_refs.py`` are exercised without network access (and so offline or
egress-restricted environments degrade predictably per NFR-5).
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass
from typing import Callable, Protocol

DEFAULT_TIMEOUT = 20
MAX_RETRIES = 4


@dataclass
class Response:
    status: int
    body: str
    headers: dict[str, str]

    def json(self):
        return json.loads(self.body)


class Transport(Protocol):
    def __call__(self, url: str, headers: dict[str, str]) -> Response: ...


class NetworkUnavailable(RuntimeError):
    """Raised when no live transport can reach the network."""


def requests_transport(url: str, headers: dict[str, str]) -> Response:
    import requests  # imported lazily so --offline works without the dependency

    try:
        resp = requests.get(url, headers=headers, timeout=DEFAULT_TIMEOUT)
    except Exception as exc:  # noqa: BLE001 - any transport error degrades alike
        raise NetworkUnavailable(str(exc)) from exc
    return Response(resp.status_code, resp.text, dict(resp.headers))


class CassetteTransport:
    """Replays recorded responses keyed by URL substring (test double)."""

    def __init__(self, cassettes: dict[str, Response]):
        self.cassettes = cassettes
        self.calls: list[str] = []

    def __call__(self, url: str, headers: dict[str, str]) -> Response:
        self.calls.append(url)
        for fragment, response in self.cassettes.items():
            if fragment in url:
                return response
        raise NetworkUnavailable(f"no cassette for {url}")


def get_json(
    url: str,
    *,
    transport: Transport = requests_transport,
    user_agent: str = "zettel-bootstrap/0.1",
    sleep: Callable[[float], None] = time.sleep,
):
    """GET a URL, backing off on 429/5xx. Returns parsed JSON or ``None``.

    Crossref revised its rate limits effective 2025-12-01, so 429s are expected
    on the public pool and are retried with exponential backoff, honouring
    ``Retry-After`` when the server sends it (FR-10).
    """
    headers = {"User-Agent": user_agent, "Accept": "application/json"}
    delay = 2.0
    for attempt in range(MAX_RETRIES):
        resp = transport(url, headers)
        if resp.status == 200:
            try:
                return resp.json()
            except json.JSONDecodeError:
                return None
        if resp.status in (429, 500, 502, 503, 504) and attempt < MAX_RETRIES - 1:
            wait = float(resp.headers.get("Retry-After", delay) or delay)
            sleep(wait)
            delay *= 2
            continue
        return None
    return None
