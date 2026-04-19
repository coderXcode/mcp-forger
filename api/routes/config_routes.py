"""
Config editor routes — read and write the .env file from the dashboard.
Changes are applied immediately (settings object is reloaded).
"""
from __future__ import annotations

import re
from pathlib import Path

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

router = APIRouter(prefix="/api/config", tags=["config"])

ENV_FILE = Path(".env")
ENV_EXAMPLE = Path(".env.example")


class EnvVar(BaseModel):
    key: str
    value: str


class EnvUpdate(BaseModel):
    vars: list[EnvVar]


@router.get("/")
async def get_config():
    """Return all .env variables (masks sensitive values)."""
    env_vars = _read_env_file()
    masked = {}
    for key, value in env_vars.items():
        masked[key] = _mask_value(key, value)
    return {"vars": masked, "file_exists": ENV_FILE.exists()}


@router.get("/raw")
async def get_raw_config():
    """Return the raw .env file content (with masking for sensitive keys)."""
    if not ENV_FILE.exists():
        # Return example file as template
        if ENV_EXAMPLE.exists():
            return {"content": ENV_EXAMPLE.read_text(), "is_template": True}
        return {"content": "", "is_template": False}
    return {"content": ENV_FILE.read_text(), "is_template": False}


@router.put("/")
async def update_config(payload: EnvUpdate):
    """Update specific .env variables. Creates .env if it doesn't exist."""
    env_vars = _read_env_file()

    for item in payload.vars:
        key = item.key.strip().upper()
        if not re.match(r"^[A-Z][A-Z0-9_]*$", key):
            raise HTTPException(400, f"Invalid env var name: {key}")
        env_vars[key] = item.value

    _write_env_file(env_vars)

    # Reload settings
    from config import get_settings
    get_settings.cache_clear()

    return {"ok": True, "updated": [v.key for v in payload.vars]}


@router.post("/reset")
async def reset_from_example():
    """Copy .env.example → .env (useful for first-time setup)."""
    if not ENV_EXAMPLE.exists():
        raise HTTPException(404, ".env.example not found")
    content = ENV_EXAMPLE.read_text()
    ENV_FILE.write_text(content)
    return {"ok": True}


@router.get("/local-model/status")
async def local_model_status():
    """Return whether the local HuggingFace model is loaded in memory."""
    from core.llm.local_provider import get_status
    return get_status()


@router.post("/local-model/load")
async def local_model_load():
    """
    Trigger eager loading of the local model in the background.
    Returns immediately; poll /local-model/status to watch progress.
    """
    from config import settings
    if settings.llm_provider != "local":
        raise HTTPException(400, "LLM_PROVIDER is not 'local'. Change it first and save.")
    import asyncio
    from core.llm.local_provider import _ensure_loaded, get_status
    # Fire-and-forget background load
    asyncio.create_task(_ensure_loaded())
    return {"ok": True, "message": f"Loading {settings.local_model} in background…"}


# ── Helpers ───────────────────────────────────────────────────────────────────

def _read_env_file() -> dict[str, str]:
    if not ENV_FILE.exists():
        if ENV_EXAMPLE.exists():
            return _parse_env_text(ENV_EXAMPLE.read_text())
        return {}
    return _parse_env_text(ENV_FILE.read_text())


def _parse_env_text(text: str) -> dict[str, str]:
    result = {}
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" in line:
            key, _, value = line.partition("=")
            key = key.strip()
            value = value.strip().strip('"').strip("'")
            result[key] = value
    return result


def _write_env_file(vars: dict[str, str]) -> None:
    lines = []
    existing_keys = set()

    # Preserve comments and structure from existing file
    source = ENV_FILE if ENV_FILE.exists() else ENV_EXAMPLE
    if source.exists():
        for line in source.read_text().splitlines():
            stripped = line.strip()
            if stripped and not stripped.startswith("#") and "=" in stripped:
                key = stripped.split("=")[0].strip()
                if key in vars:
                    lines.append(f'{key}={vars[key]}')
                    existing_keys.add(key)
                else:
                    lines.append(line)
            else:
                lines.append(line)

    # Append any new keys not in original file
    for key, value in vars.items():
        if key not in existing_keys:
            lines.append(f"{key}={value}")

    ENV_FILE.write_text("\n".join(lines) + "\n")


SENSITIVE_KEYS = {"key", "secret", "token", "password", "api_key", "private"}


def _mask_value(key: str, value: str) -> str:
    key_lower = key.lower()
    if any(s in key_lower for s in SENSITIVE_KEYS) and len(value) > 4:
        return value[:4] + "****"
    return value
