"""
LLM-powered code analyzer — language agnostic.
Sends code files to the configured LLM and asks it to:
  - Identify language & framework
  - Extract all API endpoints / functions
  - Suggest Tool vs Resource classification for each
  - Identify auth patterns
This approach works for ANY language without tree-sitter grammar files.
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from config import get_settings


ANALYZE_PROMPT = """You are an expert API analyzer for MCP (Model Context Protocol) conversion.

Analyze the following code files and extract:
1. Programming language and framework
2. All API endpoints / RPC functions / public methods
3. For each endpoint: method, path/name, parameters, return type, description
4. Authentication mechanisms used
5. For each endpoint, classify as one of:
   - "tool": performs an action, has side effects, takes meaningful parameters (POST/PUT/DELETE)
   - "resource": reads/fetches data, can be URI-addressed (GET)
   - "prompt": generates or formats text for the user

Return a JSON object with this exact structure:
{
  "language": "python|javascript|go|java|...",
  "framework": "fastapi|express|django|gin|...",
  "auth_info": {"type": "bearer|api_key|basic|none", "details": "..."},
  "endpoints": [
    {
      "name": "function_or_operation_name",
      "path": "/api/path or function_name",
      "method": "GET|POST|PUT|DELETE|FUNCTION",
      "description": "what this does",
      "parameters": [{"name": "x", "type": "string", "required": true, "description": "..."}],
      "returns": "return type description",
      "mcp_type": "tool|resource|prompt",
      "tags": []
    }
  ],
  "schemas": {},
  "notes": "anything important the MCP generator should know"
}

Only return the JSON, no explanation.

CODE FILES:
{code}
"""


class ASTAnalyzer:
    """
    Language-agnostic analyzer that uses the LLM to understand any codebase.
    Accepts file paths (local), raw code strings, or a zip archive.
    """

    def __init__(self, files: dict[str, str] | None = None):
        """
        files: dict of {filename: content}
        """
        self._files = files or {}

    def add_file(self, filename: str, content: str) -> None:
        self._files[filename] = content

    async def analyze(self) -> dict:
        """Return normalized analysis result using LLM understanding."""
        if not self._files:
            return self._empty_result()

        code_block = self._format_code_block()
        try:
            response_text = await self._call_llm(code_block)
            data = self._parse_response(response_text)
        except Exception:
            data = self._empty_result()

        # Deterministic fallback: if LLM returned no endpoints, extract FastAPI routes via AST
        if not data.get("endpoints"):
            static_eps = self._static_fastapi_extract()
            if static_eps:
                data["endpoints"] = static_eps
                if data.get("language", "unknown") in ("unknown", ""):
                    data["language"] = "python"
                if data.get("framework", "unknown") in ("unknown", ""):
                    data["framework"] = "fastapi"

        return data

    # ── LLM call ─────────────────────────────────────────────────────────────

    async def _call_llm(self, code: str) -> str:
        # Use % substitution to avoid KeyError from { } in the prompt template
        prompt = ANALYZE_PROMPT.replace("{code}", code[:60_000])

        settings = get_settings()
        provider = settings.llm_provider
        if provider == "gemini":
            if not settings.gemini_api_key:
                raise ValueError("GEMINI_API_KEY is not set. Add it to your .env file and restart.")
            return await self._call_gemini(prompt)
        elif provider == "anthropic":
            if not settings.anthropic_api_key:
                raise ValueError("ANTHROPIC_API_KEY is not set. Add it to your .env file and restart.")
            return await self._call_anthropic(prompt)
        elif provider == "local":
            return await self._call_local(prompt)
        else:
            if not settings.openai_api_key:
                raise ValueError("OPENAI_API_KEY is not set. Add it to your .env file and restart.")
            return await self._call_openai(prompt)

    async def _call_gemini(self, prompt: str) -> str:
        settings = get_settings()
        import asyncio
        from google import genai
        client = genai.Client(api_key=settings.gemini_api_key)
        response = await asyncio.to_thread(
            client.models.generate_content,
            model=settings.gemini_model,
            contents=prompt,
        )
        return response.text

    async def _call_anthropic(self, prompt: str) -> str:
        settings = get_settings()
        import anthropic
        client = anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key)
        message = await client.messages.create(
            model=settings.anthropic_model,
            max_tokens=4096,
            messages=[{"role": "user", "content": prompt}],
        )
        return message.content[0].text

    async def _call_openai(self, prompt: str) -> str:
        settings = get_settings()
        from openai import AsyncOpenAI
        client = AsyncOpenAI(api_key=settings.openai_api_key)
        resp = await client.chat.completions.create(
            model=settings.openai_model,
            messages=[{"role": "user", "content": prompt}],
            response_format={"type": "json_object"},
        )
        return resp.choices[0].message.content

    async def _call_local(self, prompt: str) -> str:
        from core.llm.local_provider import generate
        return await generate(prompt)

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _format_code_block(self) -> str:
        blocks = []
        for fname, content in self._files.items():
            ext = Path(fname).suffix
            lang_hint = {
                ".py": "python", ".js": "javascript", ".ts": "typescript",
                ".go": "go", ".java": "java", ".rb": "ruby", ".rs": "rust",
                ".cs": "csharp", ".php": "php",
            }.get(ext, "")
            blocks.append(f"### FILE: {fname}\n```{lang_hint}\n{content[:10_000]}\n```")
        return "\n\n".join(blocks)

    def _parse_response(self, text: str) -> dict:
        # Strip thinking blocks (Gemini 2.5 wraps reasoning in <think>...</think>)
        text = re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL)
        # Strip markdown code fences if present
        text = re.sub(r"```(?:json)?\n?", "", text).strip().rstrip("`").strip()
        # If there's still non-JSON preamble, find the first {
        brace_idx = text.find("{")
        if brace_idx > 0:
            text = text[brace_idx:]
        try:
            data = json.loads(text)
            data.setdefault("language", "unknown")
            data.setdefault("framework", "unknown")
            data.setdefault("auth_info", {})
            data.setdefault("endpoints", [])
            data.setdefault("schemas", {})
            data.setdefault("base_url", "")
            return data
        except json.JSONDecodeError:
            return {**self._empty_result(), "raw_response": text}

    def _static_fastapi_extract(self) -> list[dict]:
        """
        Deterministic FastAPI/Flask route extractor using Python's ast module.
        Used as a fallback when the LLM returns no endpoints.
        Returns endpoint dicts in the template-ready format (operation_id, path_params, etc.).
        """
        import ast as _ast
        import re

        HTTP_METHODS = {"get", "post", "put", "patch", "delete", "head", "options"}
        METHOD_TO_MCP = {
            "get": "resource", "head": "resource", "options": "resource",
            "post": "tool", "put": "tool", "patch": "tool", "delete": "tool",
        }
        SKIP_NAMES = {"self", "request", "response", "background", "session",
                      "current_user", "db", "user"}
        SKIP_ANNOTATIONS = {"Depends", "BackgroundTasks", "AsyncSession", "Session",
                            "Request", "Response", "HTTPAuthorizationCredentials"}

        endpoints: list[dict] = []

        for fname, content in self._files.items():
            if not fname.endswith(".py"):
                continue
            try:
                tree = _ast.parse(content, filename=fname)
            except SyntaxError:
                continue

            for node in _ast.walk(tree):
                if not isinstance(node, (_ast.FunctionDef, _ast.AsyncFunctionDef)):
                    continue
                for decorator in node.decorator_list:
                    path, method = self._extract_fastapi_route(decorator)
                    if path is None:
                        continue

                    # Path params from {param} in URL
                    path_param_names = set(re.findall(r"\{(\w+)\}", path))
                    path_params = [
                        {"name": p, "type": "string", "required": True, "in": "path"}
                        for p in re.findall(r"\{(\w+)\}", path)
                    ]

                    # Docstring
                    docstring = ""
                    if (
                        node.body
                        and isinstance(node.body[0], _ast.Expr)
                        and isinstance(node.body[0].value, _ast.Constant)
                        and isinstance(node.body[0].value.value, str)
                    ):
                        docstring = node.body[0].value.value.strip().split("\n")[0]

                    # Query params and body detection from function args
                    query_params: list[dict] = []
                    has_body = False
                    for arg in node.args.args:
                        name = arg.arg
                        if name in SKIP_NAMES or name in path_param_names:
                            continue
                        ann_str = ""
                        if arg.annotation and hasattr(_ast, "unparse"):
                            try:
                                ann_str = _ast.unparse(arg.annotation)
                            except Exception:
                                pass
                        if any(s in ann_str for s in SKIP_ANNOTATIONS):
                            continue
                        # Pascal-case annotation = Pydantic model = request body
                        if ann_str and ann_str[0].isupper() and method in ("post", "put", "patch"):
                            has_body = True
                            continue
                        # Primitives in GET/DELETE → query params
                        if method in ("get", "delete", "head"):
                            query_params.append({
                                "name": name,
                                "type": ann_str or "string",
                                "required": False,
                                "in": "query",
                            })

                    # If POST/PUT/PATCH has function args beyond path params, assume body
                    if method in ("post", "put", "patch") and not has_body:
                        non_path = [
                            a.arg for a in node.args.args
                            if a.arg not in SKIP_NAMES and a.arg not in path_param_names
                        ]
                        if non_path:
                            has_body = True

                    endpoints.append({
                        "operation_id": node.name,
                        "name": node.name,
                        "path": path,
                        "method": method.upper(),
                        "summary": docstring or f"{method.upper()} {path}",
                        "description": docstring or f"{method.upper()} {path}",
                        "path_params": path_params,
                        "query_params": query_params,
                        "body_schema": {"type": "object"} if has_body else None,
                        "mcp_type": METHOD_TO_MCP.get(method, "tool"),
                        "parameters": path_params + query_params,
                        "tags": [],
                        "returns": "JSON response",
                    })

        return endpoints

    @staticmethod
    def _extract_fastapi_route(decorator) -> tuple:
        """Extract (path, method) from a FastAPI route decorator, or (None, None)."""
        import ast as _ast

        if not isinstance(decorator, _ast.Call):
            return None, None
        func = decorator.func
        if not isinstance(func, _ast.Attribute):
            return None, None
        method = func.attr.lower()
        if method not in {"get", "post", "put", "patch", "delete", "head", "options"}:
            return None, None
        # First positional arg = path string
        if decorator.args and isinstance(decorator.args[0], _ast.Constant) and isinstance(decorator.args[0].value, str):
            return decorator.args[0].value, method
        # 'path' keyword arg
        for kw in decorator.keywords:
            if kw.arg == "path" and isinstance(kw.value, _ast.Constant):
                return kw.value.value, method
        return None, None

    @staticmethod
    def _empty_result() -> dict:
        return {
            "language": "unknown",
            "framework": "unknown",
            "auth_info": {},
            "endpoints": [],
            "schemas": {},
            "base_url": "",
            "notes": "",
        }
