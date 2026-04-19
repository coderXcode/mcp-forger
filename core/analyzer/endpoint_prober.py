"""
Live endpoint prober.
Points at a running application URL and discovers its routes by:
  1. Checking common framework introspection paths (/openapi.json, /swagger.json, etc.)
  2. Spidering links in HTML responses
  3. Probing common REST patterns
"""
from __future__ import annotations

import asyncio
from typing import Any
from urllib.parse import urljoin, urlparse

import httpx

from config import settings

# Common spec/docs paths to probe first (fast-path)
OPENAPI_PATHS = [
    "/openapi.json",
    "/swagger.json",
    "/api-docs",
    "/api/openapi.json",
    "/api/swagger.json",
    "/v1/openapi.json",
    "/v2/openapi.json",
    "/docs/openapi.json",
    "/swagger/v1/swagger.json",
    "/api/schema/",
    "/.well-known/openapi.json",
]

# Common REST endpoint patterns to probe if no spec found
COMMON_PROBE_PATHS = [
    "/health",
    "/healthz",
    "/ping",
    "/status",
    "/api",
    "/api/v1",
    "/api/v2",
    "/api/users",
    "/api/items",
    "/api/products",
]


class EndpointProber:
    """Probe a live URL to discover its API structure."""

    def __init__(self, base_url: str, headers: dict | None = None):
        self._base = base_url.rstrip("/")
        self._headers = headers or {}
        self._discovered_spec_url: str | None = None

    async def probe(self) -> dict:
        """
        Returns a dict with:
          - spec_url: URL of found OpenAPI spec (or None)
          - spec_content: raw spec text (or None)
          - probed_endpoints: list of {path, status_code, content_type} for discovered routes
          - base_url
        """
        result: dict[str, Any] = {
            "base_url": self._base,
            "spec_url": None,
            "spec_content": None,
            "probed_endpoints": [],
        }

        if not settings.enable_live_probing:
            return result

        async with httpx.AsyncClient(
            headers=self._headers,
            follow_redirects=True,
            timeout=15,
            verify=False,  # allow self-signed in dev environments
        ) as client:
            # 1. Try to find an OpenAPI spec
            spec = await self._find_spec(client)
            if spec:
                result["spec_url"] = spec["url"]
                result["spec_content"] = spec["content"]
                return result  # Full spec found — no need to probe further

            # 2. Probe common paths
            tasks = [self._probe_path(client, path) for path in COMMON_PROBE_PATHS]
            probe_results = await asyncio.gather(*tasks, return_exceptions=True)
            result["probed_endpoints"] = [
                r for r in probe_results if isinstance(r, dict)
            ]

        return result

    async def _find_spec(self, client: httpx.AsyncClient) -> dict | None:
        for path in OPENAPI_PATHS:
            url = self._base + path
            try:
                resp = await client.get(url)
                if resp.status_code == 200 and self._looks_like_spec(resp):
                    return {"url": url, "content": resp.text}
            except (httpx.ConnectError, httpx.TimeoutException):
                continue
        return None

    async def _probe_path(self, client: httpx.AsyncClient, path: str) -> dict | None:
        url = self._base + path
        try:
            resp = await client.get(url)
            return {
                "path": path,
                "status_code": resp.status_code,
                "content_type": resp.headers.get("content-type", ""),
                "accessible": resp.status_code < 400,
            }
        except Exception:
            return None

    @staticmethod
    def _looks_like_spec(resp: httpx.Response) -> bool:
        ct = resp.headers.get("content-type", "")
        if "json" in ct or "yaml" in ct:
            text = resp.text[:500]
            return '"openapi"' in text or '"swagger"' in text or "openapi:" in text
        return False
