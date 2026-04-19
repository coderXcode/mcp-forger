"""
Real-time log streaming (SSE) + log query routes.
Notifications routes included here too.
"""
from __future__ import annotations

import asyncio
import json
from datetime import datetime

from fastapi import APIRouter, Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select
from sse_starlette.sse import EventSourceResponse

from db.database import get_session
from db.models import LogEntry, LogLevel, Notification, NotificationType

router = APIRouter(tags=["logs"])


# ── Logs ──────────────────────────────────────────────────────────────────────

@router.get("/api/projects/{project_id}/logs")
async def get_logs(
    project_id: int,
    level: str | None = None,
    limit: int = 100,
    session: AsyncSession = Depends(get_session),
):
    query = select(LogEntry).where(LogEntry.project_id == project_id)
    if level:
        query = query.where(LogEntry.level == LogLevel(level))
    query = query.order_by(LogEntry.created_at.desc()).limit(limit)
    result = await session.execute(query)
    logs = result.scalars().all()
    return [
        {
            "id": l.id,
            "level": l.level.value,
            "message": l.message,
            "source": l.source,
            "created_at": l.created_at.isoformat(),
        }
        for l in reversed(logs)
    ]


@router.get("/api/projects/{project_id}/logs/stream")
async def stream_logs(project_id: int, request: Request):
    """Server-Sent Events stream for real-time log tailing."""
    async def event_generator():
        # ── Backfill: send last 50 historical logs on connect ─────────
        from db.database import AsyncSessionLocal
        async with AsyncSessionLocal() as session:
            result = await session.execute(
                select(LogEntry)
                .where(LogEntry.project_id == project_id)
                .order_by(LogEntry.created_at.desc())
                .limit(50)
            )
            history = list(reversed(result.scalars().all()))
            last_id = history[-1].id if history else 0
            for log in history:
                yield {
                    "event": "log",
                    "data": json.dumps({
                        "id": log.id,
                        "level": log.level.value,
                        "message": log.message,
                        "source": log.source,
                        "created_at": log.created_at.isoformat(),
                    }),
                }

        # ── Live tail: poll for new logs ──────────────────────────────
        while True:
            if await request.is_disconnected():
                break
            async with AsyncSessionLocal() as session:
                result = await session.execute(
                    select(LogEntry)
                    .where(LogEntry.project_id == project_id)
                    .where(LogEntry.id > last_id)
                    .order_by(LogEntry.created_at.asc())
                    .limit(20)
                )
                new_logs = result.scalars().all()
                for log in new_logs:
                    last_id = log.id
                    yield {
                        "event": "log",
                        "data": json.dumps({
                            "id": log.id,
                            "level": log.level.value,
                            "message": log.message,
                            "source": log.source,
                            "created_at": log.created_at.isoformat(),
                        }),
                    }
            await asyncio.sleep(1.5)

    return EventSourceResponse(event_generator())


@router.get("/api/logs/stream")
async def stream_all_logs(request: Request):
    """SSE stream for ALL project logs (dashboard-level feed)."""
    async def event_generator():
        last_id = 0
        while True:
            if await request.is_disconnected():
                break
            from db.database import AsyncSessionLocal
            async with AsyncSessionLocal() as session:
                result = await session.execute(
                    select(LogEntry)
                    .where(LogEntry.id > last_id)
                    .order_by(LogEntry.created_at.asc())
                    .limit(30)
                )
                new_logs = result.scalars().all()
                for log in new_logs:
                    last_id = log.id
                    yield {
                        "event": "log",
                        "data": json.dumps({
                            "id": log.id,
                            "level": log.level.value,
                            "message": log.message,
                            "source": log.source,
                            "project_id": log.project_id,
                            "created_at": log.created_at.isoformat(),
                        }),
                    }
            await asyncio.sleep(1.5)

    return EventSourceResponse(event_generator())


# ── Notifications ─────────────────────────────────────────────────────────────

@router.get("/api/notifications")
async def get_notifications(
    unread_only: bool = False,
    session: AsyncSession = Depends(get_session),
):
    query = select(Notification).order_by(Notification.created_at.desc()).limit(50)
    if unread_only:
        query = query.where(Notification.is_read == False)
    result = await session.execute(query)
    notifs = result.scalars().all()
    return [
        {
            "id": n.id,
            "project_id": n.project_id,
            "type": n.type.value,
            "title": n.title,
            "message": n.message,
            "is_read": n.is_read,
            "requires_response": n.requires_response,
            "link": n.link,
            "created_at": n.created_at.isoformat(),
        }
        for n in notifs
    ]


@router.post("/api/notifications/{notification_id}/read")
async def mark_read(notification_id: int, session: AsyncSession = Depends(get_session)):
    result = await session.execute(
        select(Notification).where(Notification.id == notification_id)
    )
    n = result.scalars().first()
    if n:
        n.is_read = True
        session.add(n)
    return {"ok": True}


@router.post("/api/notifications/read-all")
async def mark_all_read(session: AsyncSession = Depends(get_session)):
    result = await session.execute(select(Notification).where(Notification.is_read == False))
    for n in result.scalars().all():
        n.is_read = True
        session.add(n)
    return {"ok": True}


@router.get("/api/notifications/stream")
async def stream_notifications(request: Request):
    """SSE stream for real-time notification badge updates."""
    async def event_generator():
        last_id = 0
        while True:
            if await request.is_disconnected():
                break
            from db.database import AsyncSessionLocal
            async with AsyncSessionLocal() as session:
                result = await session.execute(
                    select(Notification)
                    .where(Notification.id > last_id)
                    .where(Notification.is_read == False)
                    .order_by(Notification.created_at.asc())
                    .limit(10)
                )
                new_notifs = result.scalars().all()
                for n in new_notifs:
                    last_id = n.id
                    yield {
                        "event": "notification",
                        "data": json.dumps({
                            "id": n.id,
                            "type": n.type.value,
                            "title": n.title,
                            "message": n.message,
                            "project_id": n.project_id,
                        }),
                    }
            await asyncio.sleep(2)

    return EventSourceResponse(event_generator())
