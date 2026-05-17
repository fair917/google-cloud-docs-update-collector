from __future__ import annotations

import time

import httpx


class FetchError(Exception):
    pass


def make_client(user_agent: str, timeout_seconds: int) -> httpx.Client:
    return httpx.Client(
        http2=True,
        timeout=timeout_seconds,
        follow_redirects=True,
        headers={
            "User-Agent": user_agent,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en;q=0.8, ja;q=0.7",
        },
    )


def fetch_html(client: httpx.Client, url: str, retries: int = 3) -> str:
    last_err: Exception | None = None
    for attempt in range(retries):
        try:
            resp = client.get(url)
            if resp.status_code == 200:
                return resp.text
            if resp.status_code in (429, 500, 502, 503, 504):
                last_err = FetchError(f"HTTP {resp.status_code}")
            else:
                raise FetchError(f"HTTP {resp.status_code}")
        except (httpx.TransportError, httpx.TimeoutException) as e:
            last_err = e
        time.sleep(min(2 ** attempt, 8))
    raise FetchError(f"failed after {retries} attempts: {last_err}")
