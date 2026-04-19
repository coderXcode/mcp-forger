"""
Snapshot / versioning routes.
"""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select

from db.database import get_session
from db.models import Project, ProjectSnapshot
from core.versioner.snapshot import SnapshotManager

router = APIRouter(prefix="/api/projects/{project_id}/snapshots", tags=["snapshots"])


@router.get("/")
async def list_snapshots(project_id: int, session: AsyncSession = Depends(get_session)):
    result = await session.execute(
        select(ProjectSnapshot)
        .where(ProjectSnapshot.project_id == project_id)
        .where(ProjectSnapshot.version > 0)   # exclude v0 source snapshot
        .order_by(ProjectSnapshot.version.desc())
    )
    snapshots = result.scalars().all()
    return [
        {
            "id": s.id,
            "version": s.version,
            "label": s.label,
            "description": s.description,
            "is_active": s.is_active,
            "files": list(s.files.keys()) if s.files else [],
            "diff": s.diff,
            "created_at": s.created_at.isoformat(),
        }
        for s in snapshots
    ]


@router.get("/{version}/files")
async def get_snapshot_files(
    project_id: int, version: int, session: AsyncSession = Depends(get_session)
):
    result = await session.execute(
        select(ProjectSnapshot)
        .where(ProjectSnapshot.project_id == project_id)
        .where(ProjectSnapshot.version == version)
    )
    snap = result.scalars().first()
    if not snap:
        raise HTTPException(404, "Snapshot not found")
    return {"version": snap.version, "label": snap.label, "files": snap.files}


@router.get("/{version}/diff")
async def get_snapshot_diff(
    project_id: int,
    version: int,
    base: int | None = None,
    session: AsyncSession = Depends(get_session),
):
    """Return line-level unified diff between this snapshot and a base version.
    base=0 means compare against empty (shows all lines as added).
    base=None uses the immediately preceding snapshot.
    """
    import difflib

    result = await session.execute(
        select(ProjectSnapshot)
        .where(ProjectSnapshot.project_id == project_id)
        .where(ProjectSnapshot.version == version)
    )
    snap = result.scalars().first()
    if not snap:
        raise HTTPException(404, "Snapshot not found")

    prev = None
    if base is None:
        # Default: immediately preceding snapshot
        result2 = await session.execute(
            select(ProjectSnapshot)
            .where(ProjectSnapshot.project_id == project_id)
            .where(ProjectSnapshot.version < version)
            .order_by(ProjectSnapshot.version.desc())
        )
        prev = result2.scalars().first()
    elif base > 0:
        result2 = await session.execute(
            select(ProjectSnapshot)
            .where(ProjectSnapshot.project_id == project_id)
            .where(ProjectSnapshot.version == base)
        )
        prev = result2.scalars().first()
        if not prev:
            raise HTTPException(404, f"Base snapshot v{base} not found")
    elif base == 0:
        # base=0: compare against source snapshot (v0) if it exists, else empty
        result2 = await session.execute(
            select(ProjectSnapshot)
            .where(ProjectSnapshot.project_id == project_id)
            .where(ProjectSnapshot.version == 0)
        )
        prev = result2.scalars().first()
    # base < 0 not used

    old_files: dict = prev.files if prev else {}
    new_files: dict = snap.files or {}

    added = [f for f in new_files if f not in old_files]
    removed = [f for f in old_files if f not in new_files]
    modified = [f for f in new_files if f in old_files and old_files[f] != new_files[f]]

    hunks: dict = {}

    for fname in added:
        lines = new_files[fname].splitlines()
        hunks[fname] = [{"type": "header", "text": "@@ new file — all lines added @@"}] + [
            {"type": "added", "text": f"+{line}"} for line in lines
        ]

    for fname in removed:
        lines = old_files[fname].splitlines()
        hunks[fname] = [{"type": "header", "text": "@@ deleted file — all lines removed @@"}] + [
            {"type": "removed", "text": f"-{line}"} for line in lines
        ]

    for fname in modified:
        old_lines = old_files[fname].splitlines()
        new_lines = new_files[fname].splitlines()
        raw = list(difflib.unified_diff(
            old_lines, new_lines,
            fromfile=f"a/{fname}", tofile=f"b/{fname}",
            lineterm="",
        ))
        file_hunks = []
        for line in raw:
            if line.startswith("---") or line.startswith("+++"):
                continue
            elif line.startswith("@@"):
                file_hunks.append({"type": "header", "text": line})
            elif line.startswith("+"):
                file_hunks.append({"type": "added", "text": line})
            elif line.startswith("-"):
                file_hunks.append({"type": "removed", "text": line})
            else:
                file_hunks.append({"type": "context", "text": line})
        hunks[fname] = file_hunks

    return {
        "version": version,
        "base_version": prev.version if prev else None,
        "base_label": prev.label if prev else "(empty)",
        "files": {"added": added, "removed": removed, "modified": modified},
        "hunks": hunks,
    }


@router.post("/{version}/rollback")
async def rollback_to_snapshot(
    project_id: int, version: int, session: AsyncSession = Depends(get_session)
):
    if version == 0:
        raise HTTPException(400, "Cannot rollback to source snapshot (v0)")
    result = await session.execute(select(Project).where(Project.id == project_id))
    project = result.scalars().first()
    if not project:
        raise HTTPException(404, "Project not found")

    sm = SnapshotManager(session)
    snap = await sm.rollback(project, version)
    await session.commit()
    from core.logger import project_log
    await project_log(project_id, f"Rolled back to snapshot v{snap.version} ({snap.label})", source="snapshots")
    return {"ok": True, "active_version": snap.version, "label": snap.label}


@router.delete("/{version}")
async def delete_snapshot(
    project_id: int, version: int, session: AsyncSession = Depends(get_session)
):
    result = await session.execute(
        select(ProjectSnapshot)
        .where(ProjectSnapshot.project_id == project_id)
        .where(ProjectSnapshot.version == version)
    )
    snap = result.scalars().first()
    if not snap:
        raise HTTPException(404, "Snapshot not found")
    if snap.is_active:
        raise HTTPException(400, "Cannot delete the active snapshot")
    await session.delete(snap)
    return {"ok": True}
