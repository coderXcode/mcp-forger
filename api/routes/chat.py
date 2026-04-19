"""
Chat routes — user ↔ agent conversation.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select

from db.database import get_session
from db.models import (
    ChatMessage, ChatMessageRead, Clarification, MessageRole,
    Notification, NotificationType, Project
)
from agent.chat import ForgeAgent
from agent.memory import ProjectMemory

router = APIRouter(prefix="/api/projects/{project_id}/chat", tags=["chat"])


class MessageIn(BaseModel):
    content: str


@router.get("/messages", response_model=list[ChatMessageRead])
async def get_messages(project_id: int, session: AsyncSession = Depends(get_session)):
    result = await session.execute(
        select(ChatMessage)
        .where(ChatMessage.project_id == project_id)
        .order_by(ChatMessage.created_at.asc())
    )
    return result.scalars().all()


@router.post("/send")
async def send_message(
    project_id: int,
    payload: MessageIn,
    session: AsyncSession = Depends(get_session),
):
    project = await _get_project(project_id, session)
    memory = ProjectMemory(session, project)
    context = await memory.get_context()

    agent = ForgeAgent(session, project)
    result = await agent.chat(payload.content, context)
    await session.commit()
    return result


@router.post("/clarifications/{clarification_id}/answer")
async def answer_clarification(
    project_id: int,
    clarification_id: int,
    payload: MessageIn,
    session: AsyncSession = Depends(get_session),
):
    """User provides an answer to a pending clarification question."""
    from datetime import datetime
    result = await session.execute(
        select(Clarification)
        .where(Clarification.id == clarification_id)
        .where(Clarification.project_id == project_id)
    )
    c = result.scalars().first()
    if not c:
        raise HTTPException(404, "Clarification not found")

    c.answer = payload.content
    c.is_resolved = True
    c.resolved_at = datetime.utcnow()
    session.add(c)

    # Also send the answer as a chat message so the agent sees it
    project = await _get_project(project_id, session)
    agent = ForgeAgent(session, project)
    message = f"[Answering your question: '{c.question}']\n\n{payload.content}"
    response = await agent.chat(message)
    await session.commit()
    return response


@router.get("/clarifications")
async def get_clarifications(project_id: int, session: AsyncSession = Depends(get_session)):
    result = await session.execute(
        select(Clarification)
        .where(Clarification.project_id == project_id)
        .order_by(Clarification.created_at.desc())
    )
    return result.scalars().all()


@router.delete("/messages")
async def clear_history(project_id: int, session: AsyncSession = Depends(get_session)):
    result = await session.execute(
        select(ChatMessage).where(ChatMessage.project_id == project_id)
    )
    for msg in result.scalars().all():
        await session.delete(msg)
    return {"ok": True}


async def _get_project(project_id: int, session: AsyncSession) -> Project:
    result = await session.execute(select(Project).where(Project.id == project_id))
    project = result.scalars().first()
    if not project:
        raise HTTPException(404, "Project not found")
    return project
