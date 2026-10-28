"""A small Chatwoot API client (application API, one account): the calls the tools and the seeder need."""

import os
import time
from typing import Any

import httpx


class ChatwootError(Exception):
    pass


class Chatwoot:
    def __init__(self, url: str | None = None, token: str | None = None, account: int | str | None = None,
                 transport: httpx.BaseTransport | None = None):
        url = url or os.environ.get("CHATWOOT_URL", "http://127.0.0.1:3010")
        token = token or os.environ.get("CHATWOOT_TOKEN", "")
        account = account or os.environ.get("CHATWOOT_ACCOUNT", "1")
        if not token:
            raise ChatwootError("CHATWOOT_TOKEN is not set (scripts/up.sh writes it to .env)")
        self.url = url.rstrip("/")
        self.account = int(account)
        self.http = httpx.Client(
            base_url=f"{self.url}/api/v1/accounts/{self.account}/",
            headers={"api_access_token": token, "Accept": "application/json"},
            timeout=30,
            transport=transport,
        )

    def call(self, method: str, path: str, **kw: Any) -> Any:
        for wait in (1, 2, 4, 0):
            r = self.http.request(method, path, **kw)
            if r.status_code != 429 or not wait:
                break
            time.sleep(wait)
        if r.status_code == 404:
            raise ChatwootError("not found")
        if r.status_code >= 400:
            try:
                body = r.json()
                msg = body.get("message") or body.get("error") or ", ".join(body.get("errors", [])) or None
            except (ValueError, AttributeError):
                msg = None
            raise ChatwootError(msg or f"Chatwoot answered {r.status_code}")
        return r.json() if r.content else None

    def get(self, path: str, **params: Any) -> Any:
        return self.call("GET", path, params=params)

    def post(self, path: str, data: dict) -> Any:
        return self.call("POST", path, json=data)

    def patch(self, path: str, data: dict) -> Any:
        return self.call("PATCH", path, json=data)
