"""
Thin async helper to write LogEntry rows to the DB.
Import and use anywhere in the app:

    from core.logger import project_log
    await project_log(project_id, "Analysis started", source="analyzer")
"""
from __future__ import annotations
from db.models import LogEntry, LogLevel


async def project_log(
    project_id: int,
    message: str,
    level: str = "info",
    source: str = "system",
    session=None,
) -> None:
    """Write a log entry. Accepts an existing session or opens its own."""
    try:
        entry = LogEntry(
            project_id=project_id,
            level=LogLevel(level),
            message=message,
            source=source,
        )
        if session:
            session.add(entry)
            # Don't commit — caller owns the session
        else:
            from db.database import AsyncSessionLocal
            async with AsyncSessionLocal() as s:
                s.add(entry)
                await s.commit()
    except Exception:
        pass  # Never let logging crash the caller
