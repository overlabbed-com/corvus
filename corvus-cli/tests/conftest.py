"""Fixtures for the CLI suite: a hermetic environment and an in-memory HTTP transport.

No test ever opens a socket - every httpx.Client the CLI builds gets a MockTransport.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

import httpx
import pytest

from corvus_cli import main


@pytest.fixture(autouse=True)
def isolated_env(monkeypatch, tmp_path):
    """Hermetic env: no real ~/.corvus.json and no inherited CORVUS_* variables."""
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.delenv("CORVUS_URL", raising=False)
    monkeypatch.delenv("CORVUS_TOKEN", raising=False)
    return tmp_path


@dataclass
class Call:
    """One request the CLI actually sent."""

    method: str
    url: str
    path: str
    headers: dict
    params: dict
    body: Any = None


@dataclass
class FakeAPI:
    """A route table plus a record of what was requested."""

    routes: dict = field(default_factory=dict)
    calls: list = field(default_factory=list)

    def on(self, method: str, path: str, payload: Any, status: int = 200) -> FakeAPI:
        self.routes[(method.upper(), path)] = (status, payload)
        return self

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.calls.append(
            Call(
                method=request.method,
                url=str(request.url),
                path=request.url.path,
                headers=dict(request.headers),
                params=dict(request.url.params),
                body=json.loads(request.content) if request.content else None,
            )
        )
        status, payload = self.routes.get((request.method, request.url.path), (404, {"detail": "no route"}))
        return httpx.Response(status, json=payload)

    def call(self, method: str, path: str) -> Call:
        """The one recorded call to (method, path)."""
        matches = [c for c in self.calls if c.method == method.upper() and c.path == path]
        assert len(matches) == 1, f"expected exactly one {method} {path}, recorded {self.calls}"
        return matches[0]


@pytest.fixture
def api(monkeypatch) -> FakeAPI:
    """Route every httpx.Client through an in-memory transport (never a live server)."""
    fake = FakeAPI()
    real_client = httpx.Client

    def factory(*args, **kwargs):
        kwargs["transport"] = httpx.MockTransport(fake.handler)
        return real_client(*args, **kwargs)

    monkeypatch.setattr(main.httpx, "Client", factory)
    return fake
