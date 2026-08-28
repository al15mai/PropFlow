"""Minimal sync test client for the FastAPI app.

starlette's bundled TestClient breaks against httpx>=0.28 (removed the `app=`
shortcut) and this repo's global env has that combo, while the corp network
blocks installing a compatible pin. This wrapper drives the ASGI app directly
via httpx.ASGITransport over a single reused event loop (per-request
`asyncio.run` is pathologically slow on Windows).
"""
from __future__ import annotations

import asyncio

import httpx


class ASGIClient:
    def __init__(self, app, headers=None):
        self._loop = asyncio.new_event_loop()
        transport = httpx.ASGITransport(app=app)
        self._client = httpx.AsyncClient(
            transport=transport, base_url="http://test", headers=headers or {}
        )

    def set_token(self, token):
        """Swap the default bearer token (or clear it with None)."""
        if token:
            self._client.headers["Authorization"] = f"Bearer {token}"
        else:
            self._client.headers.pop("Authorization", None)

    def request(self, method: str, url: str, **kw) -> httpx.Response:
        return self._loop.run_until_complete(self._client.request(method, url, **kw))

    def get(self, url, **kw):
        return self.request("GET", url, **kw)

    def post(self, url, **kw):
        return self.request("POST", url, **kw)

    def put(self, url, **kw):
        return self.request("PUT", url, **kw)

    def delete(self, url, **kw):
        return self.request("DELETE", url, **kw)

    def close(self) -> None:
        try:
            self._loop.run_until_complete(self._client.aclose())
        finally:
            self._loop.close()
