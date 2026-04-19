"""
clear_db.py — wipe all data from the MCP Forge database.

Usage (run inside the Docker container or locally with the venv active):

  # Inside Docker:
  docker exec mcp_forge_app python clear_db.py

  # Locally:
  python clear_db.py

  # Drop & recreate tables entirely (nuclear option):
  python clear_db.py --drop

Options:
  --drop    Drop every table then recreate it (removes schema too, then re-creates)
  --yes     Skip the confirmation prompt
"""

import argparse
import asyncio
import sys

# Ensure project root is on path when run directly
import os
sys.path.insert(0, os.path.dirname(__file__))

from sqlalchemy import text
from sqlmodel import SQLModel

from db.database import engine, _patch_sqlite_url
from config import settings

# Import all models so SQLModel's metadata knows about them
import db.models  # noqa: F401


TABLES_IN_DELETE_ORDER = [
    # Children first to avoid FK violations
    "logentry",
    "notification",
    "testrun",
    "chatmessage",
    "projectsnapshot",
    "analysisresult",
    "project",
    "authprofile",
]


async def truncate_all() -> None:
    """Delete all rows from every table, preserving the schema."""
    async with engine.begin() as conn:
        # Disable FK checks for SQLite so we can delete in any order
        if "sqlite" in settings.db_url:
            await conn.execute(text("PRAGMA foreign_keys = OFF"))

        for table in TABLES_IN_DELETE_ORDER:
            try:
                result = await conn.execute(text(f"DELETE FROM {table}"))
                print(f"  ✓  {table:<25} {result.rowcount} rows deleted")
            except Exception as exc:
                print(f"  ✗  {table:<25} skipped ({exc})")

        if "sqlite" in settings.db_url:
            await conn.execute(text("PRAGMA foreign_keys = ON"))

    print("\nAll tables cleared.")


async def drop_and_recreate() -> None:
    """Drop every table then recreate the full schema from scratch."""
    async with engine.begin() as conn:
        print("Dropping all tables…")
        await conn.run_sync(SQLModel.metadata.drop_all)
        print("Recreating schema…")
        await conn.run_sync(SQLModel.metadata.create_all)
    print("Done — fresh empty database.")


def confirm(prompt: str) -> bool:
    try:
        answer = input(prompt + " [y/N] ").strip().lower()
    except (EOFError, KeyboardInterrupt):
        return False
    return answer in ("y", "yes")


async def main(drop: bool, yes: bool) -> None:
    if drop:
        msg = "⚠️  This will DROP and RECREATE all tables. All data will be lost."
    else:
        msg = "⚠️  This will DELETE all rows from every table. Schema is preserved."

    print(msg)
    if not yes and not confirm("Continue?"):
        print("Aborted.")
        return

    if drop:
        await drop_and_recreate()
    else:
        await truncate_all()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Clear the MCP Forge database")
    parser.add_argument("--drop", action="store_true", help="Drop and recreate all tables")
    parser.add_argument("--yes", "-y", action="store_true", help="Skip confirmation prompt")
    args = parser.parse_args()

    asyncio.run(main(drop=args.drop, yes=args.yes))
