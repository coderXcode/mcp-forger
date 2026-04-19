"""
GitHub repository fetcher.
Downloads and prepares code from a GitHub repo for analysis.
Supports public repos and private repos (via token).
Also fetches README, docs, and existing test files.
"""
from __future__ import annotations

import asyncio
import base64
import re
from pathlib import Path
from typing import Any

import httpx

from config import settings

# File extensions we care about for code analysis
SUPPORTED_EXTENSIONS = {
    ".py", ".js", ".ts", ".go", ".java", ".rb", ".rs", ".cs",
    ".php", ".swift", ".kt", ".scala", ".ex", ".exs",
    ".yaml", ".yml", ".json", ".toml",
    ".md", ".txt",  # docs
}

# Directories to skip
SKIP_DIRS = {
    "node_modules", ".git", "__pycache__", ".venv", "venv", "dist", "build",
    ".next", ".nuxt", "coverage", ".pytest_cache", ".mypy_cache",
    "vendor", "target", "out", "bin", "obj",
}

# Max file size to fetch (bytes)
MAX_FILE_SIZE = 150_000


class GitHubFetcher:
    """Fetch code files + docs from a GitHub repository URL."""

    GITHUB_API = "https://api.github.com"

    def __init__(self, repo_url: str):
        self._repo_url = repo_url.rstrip("/")
        self._owner, self._repo, self._ref = self._parse_url(repo_url)
        self._headers = {
            "Accept": "application/vnd.github.v3+json",
            **({"Authorization": f"token {settings.github_token}"} if settings.github_token else {}),
        }

    async def fetch(self, max_files: int = 80) -> dict:
        """
        Returns:
          files: {filename: content}  — code files for analysis
          docs:  {filename: content}  — README / docs
          tests: {filename: content}  — existing test files
          repo_info: dict             — name, description, language, stars
        """
        async with httpx.AsyncClient(headers=self._headers, timeout=30, follow_redirects=True) as client:
            repo_info = await self._get_repo_info(client)
            tree = await self._get_tree(client)

        files, docs, tests = {}, {}, {}
        interesting = [
            item for item in tree
            if item.get("type") == "blob"
            and self._should_include(item["path"])
            and item.get("size", 0) < MAX_FILE_SIZE
        ][:max_files]

        # Fetch all files concurrently (batched to avoid rate limits)
        async with httpx.AsyncClient(headers=self._headers, timeout=30) as client:
            tasks = [self._fetch_file(client, item["path"]) for item in interesting]
            results = await asyncio.gather(*tasks, return_exceptions=True)

        for item, result in zip(interesting, results):
            if isinstance(result, Exception):
                continue
            path = item["path"]
            if self._is_test_file(path):
                tests[path] = result
            elif self._is_doc_file(path):
                docs[path] = result
            else:
                files[path] = result

        return {
            "files": files,
            "docs": docs,
            "tests": tests,
            "repo_info": repo_info,
        }

    async def _get_repo_info(self, client: httpx.AsyncClient) -> dict:
        url = f"{self.GITHUB_API}/repos/{self._owner}/{self._repo}"
        resp = await client.get(url)
        if resp.status_code == 200:
            data = resp.json()
            return {
                "name": data.get("name"),
                "description": data.get("description"),
                "language": data.get("language"),
                "stars": data.get("stargazers_count"),
                "default_branch": data.get("default_branch", "main"),
                "topics": data.get("topics", []),
            }
        return {}

    async def _get_tree(self, client: httpx.AsyncClient) -> list[dict]:
        ref = self._ref or "HEAD"
        url = f"{self.GITHUB_API}/repos/{self._owner}/{self._repo}/git/trees/{ref}?recursive=1"
        resp = await client.get(url)
        if resp.status_code != 200:
            return []
        data = resp.json()
        return data.get("tree", [])

    async def _fetch_file(self, client: httpx.AsyncClient, path: str) -> str:
        url = f"{self.GITHUB_API}/repos/{self._owner}/{self._repo}/contents/{path}"
        if self._ref:
            url += f"?ref={self._ref}"
        resp = await client.get(url)
        resp.raise_for_status()
        data = resp.json()
        content_b64 = data.get("content", "")
        return base64.b64decode(content_b64.replace("\n", "")).decode("utf-8", errors="replace")

    # ── Filtering helpers ─────────────────────────────────────────────────────

    def _should_include(self, path: str) -> bool:
        parts = Path(path).parts
        if any(p in SKIP_DIRS for p in parts):
            return False
        return Path(path).suffix in SUPPORTED_EXTENSIONS

    def _is_test_file(self, path: str) -> bool:
        lower = path.lower()
        return any(x in lower for x in ["test_", "_test.", "spec.", ".test.", ".spec.", "/tests/", "/test/"])

    def _is_doc_file(self, path: str) -> bool:
        lower = path.lower()
        return any(lower.endswith(ext) for ext in [".md", ".txt", ".rst"]) or "doc" in lower

    @staticmethod
    def _parse_url(url: str) -> tuple[str, str, str]:
        """Parse github.com/owner/repo[/tree/ref] → (owner, repo, ref)."""
        url = re.sub(r"https?://(www\.)?github\.com/", "", url)
        parts = url.split("/")
        owner = parts[0] if len(parts) > 0 else ""
        repo  = parts[1].removesuffix(".git") if len(parts) > 1 else ""
        ref   = parts[3] if len(parts) > 3 and parts[2] in ("tree", "blob") else ""
        return owner, repo, ref
