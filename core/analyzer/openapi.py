"""
OpenAPI / Swagger spec analyzer.
Parses both JSON and YAML specs from a URL or raw string.
Extracts endpoints, schemas, auth, and suggests Tool vs Resource classification.
"""
from __future__ import annotations

import json
import re
from typing import Any
from urllib.parse import urlparse

import httpx
import yaml


class OpenAPIAnalyzer:
    """Parse an OpenAPI 2/3 spec into the normalized endpoint format used by MCP Forge."""

    def __init__(self, spec_url_or_content: str):
        self._raw = spec_url_or_content
        self._spec: dict = {}

    # ── Public API ────────────────────────────────────────────────────────────

    async def analyze(self) -> dict:
        """Return a normalized analysis dict ready to store in AnalysisResult."""
        self._spec = await self._load_spec()
        return {
            "language": "any",
            "framework": self._detect_framework(),
            "base_url": self._get_base_url(),
            "auth_info": self._extract_auth(),
            "schemas": self._extract_schemas(),
            "endpoints": self._extract_endpoints(),
            "info": self._spec.get("info", {}),
            "openapi_version": self._spec.get("openapi") or self._spec.get("swagger", ""),
        }

    # ── Loaders ───────────────────────────────────────────────────────────────

    async def _load_spec(self) -> dict:
        raw = self._raw.strip()
        # URL?
        if raw.startswith("http://") or raw.startswith("https://"):
            async with httpx.AsyncClient(follow_redirects=True, timeout=30) as client:
                resp = await client.get(raw)
                resp.raise_for_status()
                raw = resp.text

        # Try JSON, then YAML
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            return yaml.safe_load(raw)

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _detect_framework(self) -> str:
        info = self._spec.get("info", {})
        title = (info.get("title") or "").lower()
        desc  = (info.get("description") or "").lower()
        combined = title + " " + desc
        for fw in ["fastapi", "express", "django", "flask", "rails", "spring", "gin", "echo"]:
            if fw in combined:
                return fw
        return "unknown"

    def _get_base_url(self) -> str:
        # OAS 3
        servers = self._spec.get("servers", [])
        if servers:
            return servers[0].get("url", "")
        # Swagger 2
        host = self._spec.get("host", "")
        base = self._spec.get("basePath", "/")
        scheme = (self._spec.get("schemes") or ["https"])[0]
        return f"{scheme}://{host}{base}" if host else ""

    def _extract_auth(self) -> dict:
        # OAS 3
        components = self._spec.get("components", {})
        security_schemes = components.get("securitySchemes", {})
        # Swagger 2
        if not security_schemes:
            security_schemes = self._spec.get("securityDefinitions", {})

        result = {}
        for name, scheme in security_schemes.items():
            result[name] = {
                "type": scheme.get("type"),
                "scheme": scheme.get("scheme"),
                "in": scheme.get("in"),
                "name": scheme.get("name"),
                "flows": scheme.get("flows"),
            }
        return result

    def _extract_schemas(self) -> dict:
        # OAS 3
        components = self._spec.get("components", {})
        schemas = components.get("schemas", {})
        # Swagger 2
        if not schemas:
            schemas = self._spec.get("definitions", {})
        return schemas

    def _extract_endpoints(self) -> list[dict]:
        paths = self._spec.get("paths", {})
        endpoints = []
        for path, path_item in paths.items():
            for method in ["get", "post", "put", "patch", "delete", "head", "options"]:
                op = path_item.get(method)
                if not op:
                    continue
                endpoints.append(self._parse_operation(path, method.upper(), op))
        return endpoints

    def _parse_operation(self, path: str, method: str, op: dict) -> dict:
        params = op.get("parameters", [])
        query_params = [p for p in params if p.get("in") == "query"]
        path_params  = [p for p in params if p.get("in") == "path"]
        header_params = [p for p in params if p.get("in") == "header"]

        body_schema = None
        req_body = op.get("requestBody", {})
        if req_body:
            content = req_body.get("content", {})
            for ct in ["application/json", "application/x-www-form-urlencoded"]:
                if ct in content:
                    body_schema = content[ct].get("schema")
                    break

        responses = op.get("responses", {})
        success_response = responses.get("200") or responses.get("201") or {}

        # Tool vs Resource heuristic
        mcp_type = self._classify_mcp_type(method, path, op)

        return {
            "path": path,
            "method": method,
            "operation_id": op.get("operationId") or self._generate_op_id(method, path),
            "summary": op.get("summary", ""),
            "description": op.get("description", ""),
            "tags": op.get("tags", []),
            "query_params": query_params,
            "path_params": path_params,
            "header_params": header_params,
            "body_schema": body_schema,
            "response_schema": success_response,
            "security": op.get("security", []),
            "mcp_type": mcp_type,           # "tool" | "resource" | "prompt"
            "deprecated": op.get("deprecated", False),
        }

    def _classify_mcp_type(self, method: str, path: str, op: dict) -> str:
        """Heuristic: GET endpoints with {id} or listing are Resources; mutations are Tools."""
        if method == "GET":
            # Collection endpoints (no path param in last segment) → resource
            # Individual item endpoints → resource
            return "resource"
        # POST/PUT/PATCH/DELETE → tool
        return "tool"

    def _generate_op_id(self, method: str, path: str) -> str:
        cleaned = re.sub(r"[{}/ ]", "_", path).strip("_")
        return f"{method.lower()}_{cleaned}"
