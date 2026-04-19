"""
Test runner — Universal approach.

Architecture
------------
We ALWAYS test the generated MCP server itself, not the original source app.
This works identically for every source type (local folder, GitHub, OpenAPI URL,
manual, upload).

Flow:
1.  Resolve where the original API lives (start it if local/GitHub, use URL if remote).
2.  Write generated files to a temp dir and install their requirements.txt.
3.  Start the generated server.py with API_BASE_URL pointing at the original API.
4.  Run pytest against the generated server's HTTP endpoint.
5.  Tear everything down.
"""
from __future__ import annotations

import asyncio
import json
import os
import re
import shutil
import socket
import sys
import tempfile
import time
from datetime import datetime
from pathlib import Path


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("", 0))
        return s.getsockname()[1]


async def _kill(proc: asyncio.subprocess.Process) -> None:
    if proc and proc.returncode is None:
        proc.terminate()
        try:
            await asyncio.wait_for(proc.wait(), timeout=5)
        except asyncio.TimeoutError:
            proc.kill()


class TestRunner:
    """Execute pytest tests against the generated MCP server."""

    async def run(
        self,
        files: dict[str, str],
        test_code: str | None = None,
        source_url: str | None = None,
        source_type: str | None = None,
    ) -> dict:
        if not test_code:
            return self._empty_result("no_tests")
        stripped = test_code.strip()
        if not stripped or stripped.startswith("# Test generation failed"):
            return self._empty_result("error", output=stripped)

        with tempfile.TemporaryDirectory(prefix="mcp_forge_test_") as tmpdir:
            tmp = Path(tmpdir)

            # Write generated MCP files
            for fname, content in files.items():
                dest = tmp / fname
                dest.parent.mkdir(parents=True, exist_ok=True)
                dest.write_text(content, encoding="utf-8")

            # Write test + conftest + pytest.ini
            (tmp / "test_mcp_server.py").write_text(test_code, encoding="utf-8")
            (tmp / "conftest.py").write_text(
                "import pytest\n\npytest_plugins = ['pytest_asyncio']\n"
            )
            (tmp / "pytest.ini").write_text(
                "[pytest]\nasyncio_mode = auto\n"
            )

            # Install generated requirements.txt
            req = tmp / "requirements.txt"
            if req.exists():
                pip = await asyncio.create_subprocess_exec(
                    sys.executable, "-m", "pip", "install", "-r", str(req), "-q",
                    stdout=asyncio.subprocess.DEVNULL,
                    stderr=asyncio.subprocess.DEVNULL,
                )
                try:
                    await asyncio.wait_for(pip.communicate(), timeout=120)
                except asyncio.TimeoutError:
                    pass  # proceed anyway — packages may already be installed

            result = await self._run_with_generated_server(
                tmp, source_url=source_url, source_type=source_type
            )

        return result

    # ── Generated server orchestration ───────────────────────────────────────

    async def _run_with_generated_server(
        self,
        workdir: Path,
        source_url: str | None,
        source_type: str | None,
    ) -> dict:
        """
        1. Start the original API (local/GitHub) so the MCP server has a backend.
        2. Start the generated server.py with API_BASE_URL → original API.
        3. Run tests against the generated server.
        """
        original_proc = None
        mcp_proc = None
        clone_dir = None

        try:
            # ── Step 1: resolve original API URL ─────────────────────────────
            api_base_url, original_proc, clone_dir = await self._start_original_api(
                source_url, source_type
            )

            # ── Step 2: start the generated MCP server ────────────────────────
            mcp_port = _free_port()
            # Find the generated server entry — scan the workdir tree
            mcp_entry = self._detect_entry(workdir)
            if not mcp_entry:
                # Generated server may use FastMCP stdio transport — skip HTTP start
                # and run pytest directly against the original API
                return await self._run_pytest(workdir, base_url=api_base_url, api_url=api_base_url)

            mcp_env = {
                **os.environ,
                "BASE_URL":      api_base_url,
                "API_BASE_URL":  api_base_url,
                "PORT":          str(mcp_port),
                "HOST":          "0.0.0.0",
            }

            mcp_proc = await asyncio.create_subprocess_exec(
                sys.executable, "-m", "uvicorn",
                mcp_entry,
                "--host", "0.0.0.0",
                "--port", str(mcp_port),
                "--log-level", "warning",
                cwd=str(workdir),
                env=mcp_env,
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.DEVNULL,
            )

            mcp_base = f"http://localhost:{mcp_port}"
            # FastMCP servers may not expose /health — just wait for any response
            mcp_ready = await self._wait_for_port(mcp_port, timeout=15)

            if not mcp_ready:
                # Server may not be a uvicorn app (pure MCP transport) — run pytest
                # directly against the API base URL as fallback
                await _kill(mcp_proc)
                mcp_proc = None
                mcp_base = api_base_url

            # ── Step 3: run pytest ────────────────────────────────────────────
            return await self._run_pytest(
                workdir,
                base_url=mcp_base,
                api_url=api_base_url or mcp_base,
            )

        finally:
            await _kill(mcp_proc)
            await _kill(original_proc)
            if clone_dir and Path(clone_dir).exists():
                shutil.rmtree(clone_dir, ignore_errors=True)

    # ── Original API starter ─────────────────────────────────────────────────

    async def _start_original_api(
        self, source_url: str | None, source_type: str | None
    ) -> tuple[str | None, asyncio.subprocess.Process | None, str | None]:
        """
        Returns (api_base_url_or_None, process_or_None, clone_dir_or_None).
        Returns None as api_base_url when origin is unknown (MANUAL/UPLOAD).
        """
        stype = (source_type or "").lower()

        if stype == "local_folder" and source_url:
            src = Path(source_url)
            if src.exists():
                proc, port = await self._start_local_app(src)
                if proc and port:
                    return f"http://localhost:{port}", proc, None
            return None, None, None

        if stype == "github" and source_url:
            clone_dir = tempfile.mkdtemp(prefix="mcp_forge_clone_")
            try:
                git_proc = await asyncio.create_subprocess_exec(
                    "git", "clone", "--depth=1", source_url, clone_dir,
                    stdout=asyncio.subprocess.DEVNULL,
                    stderr=asyncio.subprocess.DEVNULL,
                )
                await asyncio.wait_for(git_proc.communicate(), timeout=60)
                proc, port = await self._start_local_app(Path(clone_dir))
                if proc and port:
                    return f"http://localhost:{port}", proc, clone_dir
            except Exception:
                pass
            return None, None, clone_dir

        if stype in ("url", "openapi") and source_url:
            base = re.sub(
                r"/(openapi\.json|swagger\.json|docs.*|api-docs.*)$",
                "", source_url
            )
            return base, None, None

        # MANUAL / UPLOAD / unknown — no original API
        return None, None, None

    async def _start_local_app(
        self, src: Path
    ) -> tuple[asyncio.subprocess.Process | None, int | None]:
        """Install deps, detect framework+entry, start app. Returns (proc, port)."""
        # Install deps
        req = src / "requirements.txt"
        if req.exists():
            pip = await asyncio.create_subprocess_exec(
                sys.executable, "-m", "pip", "install", "-r", str(req), "-q",
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.DEVNULL,
            )
            try:
                await asyncio.wait_for(pip.communicate(), timeout=90)
            except asyncio.TimeoutError:
                pass

        # Load .env from source dir into subprocess environment
        env = self._load_dotenv(src)
        port = _free_port()
        env["PORT"] = str(port)

        # Django: detect manage.py + django in requirements
        if (src / "manage.py").exists() and self._has_dep(src, "django"):
            proc = await asyncio.create_subprocess_exec(
                sys.executable, "manage.py", "runserver",
                f"0.0.0.0:{port}", "--noreload",
                cwd=str(src), env=env,
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.DEVNULL,
            )
            ready = await self._wait_for_ready(f"http://localhost:{port}", timeout=30)
            if not ready:
                await _kill(proc)
                return None, None
            return proc, port

        # ASGI/WSGI via uvicorn
        entry, cwd, pythonpath = self._detect_entry_full(src)
        if not entry:
            return None, None

        if pythonpath:
            env["PYTHONPATH"] = pythonpath + os.pathsep + env.get("PYTHONPATH", "")

        proc = await asyncio.create_subprocess_exec(
            sys.executable, "-m", "uvicorn",
            entry, "--host", "0.0.0.0", "--port", str(port),
            "--log-level", "warning",
            cwd=str(cwd), env=env,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
        )

        ready = await self._wait_for_ready(f"http://localhost:{port}", timeout=20)
        if not ready:
            await _kill(proc)
            return None, None

        return proc, port

    def _load_dotenv(self, src: Path) -> dict:
        """Return os.environ merged with any .env file in the source directory."""
        env = {**os.environ}
        dotenv = src / ".env"
        if not dotenv.exists():
            dotenv = src / ".env.example"  # use example as fallback if present
        if dotenv.exists():
            for line in dotenv.read_text(encoding="utf-8", errors="ignore").splitlines():
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    k, _, v = line.partition("=")
                    env.setdefault(k.strip(), v.strip().strip('"\"'))  # don't override real env
        return env

    def _has_dep(self, src: Path, name: str) -> bool:
        """Check if a package name appears in requirements.txt or pyproject.toml."""
        for f in [src / "requirements.txt", src / "pyproject.toml", src / "setup.cfg"]:
            if f.exists() and name.lower() in f.read_text(encoding="utf-8", errors="ignore").lower():
                return True
        return False

    def _detect_entry_full(self, src: Path) -> tuple[str | None, Path, str | None]:
        """
        Returns (uvicorn_entry, cwd, extra_pythonpath_or_None).
        Handles flat, src/, and package layouts.
        """
        # ── pyproject.toml declared entry ──────────────────────────────
        declared = self._entry_from_pyproject(src)
        if declared:
            return declared, src, None

        # ── Flat layout (root-level files) ────────────────────────────
        for fname in ["main.py", "app.py", "server.py", "api.py", "asgi.py"]:
            f = src / fname
            if f.exists():
                var = self._sniff_app_var(f)
                if var:
                    return f"{fname[:-3]}:{var}", src, None

        # ── src/ layout ────────────────────────────────────────────
        src_subdir = src / "src"
        if src_subdir.is_dir():
            for fname in ["main.py", "app.py", "server.py"]:
                f = src_subdir / fname
                if f.exists():
                    var = self._sniff_app_var(f)
                    if var:
                        # cwd = src_subdir so imports resolve; PYTHONPATH = project root
                        return f"{fname[:-3]}:{var}", src_subdir, str(src)

        # ── Package layout (app/__init__.py or app/main.py) ────────────
        skip = {"tests", "test", ".git", "__pycache__", ".venv", "venv", "env"}
        for pkg in sorted(src.iterdir()):
            if not pkg.is_dir() or pkg.name in skip:
                continue
            if not (pkg / "__init__.py").exists():
                continue
            # Check __init__.py
            var = self._sniff_app_var(pkg / "__init__.py")
            if var:
                return f"{pkg.name}:{var}", src, None
            # Check sub-files
            for fname in ["main.py", "app.py", "server.py", "asgi.py"]:
                f = pkg / fname
                if f.exists():
                    var = self._sniff_app_var(f)
                    if var:
                        return f"{pkg.name}.{fname[:-3]}:{var}", src, None

        return None, src, None

    def _detect_entry(self, src: Path) -> str | None:
        """Convenience wrapper used for the generated MCP server workdir."""
        entry, _, _ = self._detect_entry_full(src)
        return entry

    def _sniff_app_var(self, filepath: Path) -> str | None:
        """Scan file for ASGI app variable assignment. Returns var name or None."""
        try:
            text = filepath.read_text(encoding="utf-8", errors="ignore")
            for varname in ["app", "application", "create_app", "get_app"]:
                if re.search(rf"^{varname}\s*=", text, re.MULTILINE):
                    return varname
        except Exception:
            pass
        return None

    def _entry_from_pyproject(self, src: Path) -> str | None:
        """Try to extract uvicorn entry from pyproject.toml [tool.uvicorn] if present."""
        pp = src / "pyproject.toml"
        if not pp.exists():
            return None
        try:
            import re
            text = pp.read_text(encoding="utf-8")
            m = re.search(r'app\s*=\s*["\']([\w.:]+)["\']', text)
            if m:
                return m.group(1)
        except Exception:
            pass
        return None

    # ── Readiness helpers ─────────────────────────────────────────────────────

    async def _wait_for_ready(self, base_url: str, timeout: int = 20) -> bool:
        import httpx
        deadline = time.monotonic() + timeout
        async with httpx.AsyncClient(timeout=2) as client:
            while time.monotonic() < deadline:
                for path in ("/health", "/"):
                    try:
                        r = await client.get(f"{base_url}{path}")
                        if r.status_code < 500:
                            return True
                    except Exception:
                        pass
                await asyncio.sleep(0.5)
        return False

    async def _wait_for_port(self, port: int, timeout: int = 15) -> bool:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            try:
                reader, writer = await asyncio.wait_for(
                    asyncio.open_connection("127.0.0.1", port), timeout=1
                )
                writer.close()
                await writer.wait_closed()
                return True
            except Exception:
                await asyncio.sleep(0.5)
        return False

    # ── pytest runner ─────────────────────────────────────────────────────────

    async def _run_pytest(
        self, workdir: Path,
        base_url: str | None = None,
        api_url: str | None = None,
    ) -> dict:
        cmd = [
            "python", "-m", "pytest",
            str(workdir),
            "-v", "--tb=short", "--no-header",
            "--json-report",
            f"--json-report-file={workdir}/report.json",
            "--timeout=30",
        ]
        env = {**os.environ}
        if base_url:
            env["BASE_URL"] = base_url
        if api_url:
            env["API_BASE_URL"] = api_url

        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd, cwd=str(workdir), env=env,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
            )
            stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=120)
            output = stdout.decode("utf-8", errors="replace")
        except asyncio.TimeoutError:
            return self._empty_result("timeout", output="Test run timed out after 120s")
        except Exception as e:
            return self._empty_result("error", output=str(e))

        report_path = workdir / "report.json"
        if report_path.exists():
            try:
                return self._parse_report(json.loads(report_path.read_text()), output)
            except Exception:
                pass
        return self._parse_text_output(output, proc.returncode)

    # ── Result parsers ────────────────────────────────────────────────────────

    def _parse_report(self, report: dict, output: str) -> dict:
        summary = report.get("summary", {})
        tests   = report.get("tests", [])

        results = []
        for t in tests:
            results.append({
                "name":     t.get("nodeid", ""),
                "status":   t.get("outcome", "unknown"),
                "duration": round(t.get("duration", 0), 3),
                "message":  t.get("call", {}).get("longrepr", "")
                            if t.get("outcome") != "passed" else "",
            })

        total  = summary.get("total", len(tests))
        passed = summary.get("passed", 0)
        failed = summary.get("failed", 0)

        return {
            "status":  "passed" if failed == 0 and total > 0 else (
                       "failed" if failed > 0 else "error"),
            "total":   total,
            "passed":  passed,
            "failed":  failed,
            "skipped": summary.get("skipped", 0),
            "results": results,
            "output":  output,
            "report":  report,
            "completed_at": datetime.utcnow().isoformat(),
        }

    def _parse_text_output(self, output: str, returncode: int | None) -> dict:
        passed = output.count(" PASSED")
        failed = output.count(" FAILED")
        error  = output.count(" ERROR")
        total  = passed + failed + error

        return {
            "status":  "passed" if returncode == 0 else "failed",
            "total":   total,
            "passed":  passed,
            "failed":  failed + error,
            "skipped": 0,
            "results": [],
            "output":  output,
            "report":  {},
            "completed_at": datetime.utcnow().isoformat(),
        }

    @staticmethod
    def _empty_result(status: str, output: str = "") -> dict:
        return {
            "status":  status,
            "total":   0,
            "passed":  0,
            "failed":  0,
            "skipped": 0,
            "results": [],
            "output":  output,
            "report":  {},
            "completed_at": datetime.utcnow().isoformat(),
        }
