"""
Per-project conversation memory manager.
Builds rich context from the DB to inject into agent conversations.
"""
from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select

from db.models import (
    AnalysisResult, ChatMessage, Clarification, Project,
    ProjectSnapshot, TestRun
)


class ProjectMemory:
    """Assembles structured context for the agent from DB state."""

    def __init__(self, session: AsyncSession, project: Project):
        self._session = session
        self._project = project

    async def get_context(self) -> dict:
        """Return a context dict for injecting into the agent system prompt."""
        analysis = await self._get_analysis()
        active_snap = await self._get_active_snapshot()
        last_test = await self._get_last_test()
        open_clarifications = await self._get_open_clarifications()

        return {
            "project_id": self._project.id,
            "project_name": self._project.name,
            "status": self._project.status.value,
            "source_type": self._project.source_type.value,
            "target_language": self._project.target_language.value,
            "endpoints_count": len(analysis.get("endpoints", [])) if analysis else 0,
            "language": analysis.get("language") if analysis else None,
            "framework": analysis.get("framework") if analysis else None,
            "active_snapshot": active_snap.version if active_snap else None,
            "snapshot_label": active_snap.label if active_snap else None,
            "last_test": {
                "total": last_test.total,
                "passed": last_test.passed,
                "failed": last_test.failed,
                "status": last_test.status.value,
            } if last_test else None,
            "open_clarifications": [
                {"id": c.id, "question": c.question}
                for c in open_clarifications
            ],
        }

    async def get_full_context_string(self) -> str:
        """Return a formatted string for inclusion in agent context."""
        ctx = await self.get_context()
        lines = [
            f"Project: {ctx['project_name']} (status: {ctx['status']})",
            f"Source: {ctx['source_type']} → Target: {ctx['target_language']}",
        ]
        if ctx["language"]:
            lines.append(f"Detected: {ctx['language']} / {ctx['framework']}")
        if ctx["endpoints_count"]:
            lines.append(f"Endpoints analyzed: {ctx['endpoints_count']}")
        if ctx["active_snapshot"]:
            lines.append(f"Active: {ctx['snapshot_label']} (v{ctx['active_snapshot']})")
        if ctx["last_test"]:
            t = ctx["last_test"]
            lines.append(f"Tests: {t['passed']}/{t['total']} passed ({t['status']})")
        if ctx["open_clarifications"]:
            lines.append(f"Pending clarifications: {len(ctx['open_clarifications'])}")
        return "\n".join(lines)

    # ── Private ───────────────────────────────────────────────────────────────

    async def _get_analysis(self) -> dict | None:
        result = await self._session.execute(
            select(AnalysisResult)
            .where(AnalysisResult.project_id == self._project.id)
            .order_by(AnalysisResult.created_at.desc())
        )
        obj = result.scalars().first()
        if not obj:
            return None
        return {
            "language": obj.language,
            "framework": obj.framework,
            "endpoints": obj.endpoints or [],
            "auth_info": obj.auth_info or {},
        }

    async def _get_active_snapshot(self) -> ProjectSnapshot | None:
        if not self._project.active_snapshot_id:
            return None
        result = await self._session.execute(
            select(ProjectSnapshot).where(ProjectSnapshot.id == self._project.active_snapshot_id)
        )
        return result.scalars().first()

    async def _get_last_test(self) -> TestRun | None:
        result = await self._session.execute(
            select(TestRun)
            .where(TestRun.project_id == self._project.id)
            .order_by(TestRun.created_at.desc())
        )
        return result.scalars().first()

    async def _get_open_clarifications(self) -> list[Clarification]:
        result = await self._session.execute(
            select(Clarification)
            .where(Clarification.project_id == self._project.id)
            .where(Clarification.is_resolved == False)
            .order_by(Clarification.created_at.asc())
        )
        return result.scalars().all()
