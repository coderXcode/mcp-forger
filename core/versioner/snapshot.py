"""
Snapshot / versioning engine.
Each time the generator produces new code, a snapshot is saved.
Users can rollback to any previous snapshot.
Optionally commits to a local git repo.
"""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select

from config import settings
from db.models import Project, ProjectSnapshot


class SnapshotManager:
    """Create, list, and restore project snapshots."""

    def __init__(self, session: AsyncSession):
        self._session = session

    async def create_snapshot(
        self,
        project: Project,
        files: dict[str, str],
        label: str = "",
        description: str = "",
    ) -> ProjectSnapshot:
        """Save generated files as a new versioned snapshot."""
        # Get next version number
        result = await self._session.execute(
            select(ProjectSnapshot)
            .where(ProjectSnapshot.project_id == project.id)
            .order_by(ProjectSnapshot.version.desc())
        )
        last = result.scalars().first()
        next_version = (last.version + 1) if last else 1

        # Deactivate current active snapshot
        if last:
            result2 = await self._session.execute(
                select(ProjectSnapshot)
                .where(ProjectSnapshot.project_id == project.id)
                .where(ProjectSnapshot.is_active == True)
            )
            for snap in result2.scalars().all():
                snap.is_active = False
                self._session.add(snap)

        # Compute diff from previous snapshot
        diff = {}
        if last and last.files:
            diff = self._compute_diff(last.files, files)

        snapshot = ProjectSnapshot(
            project_id=project.id,
            version=next_version,
            label=label or f"v{next_version}",
            description=description,
            files=files,
            diff=diff,
            is_active=True,
        )
        self._session.add(snapshot)
        await self._session.flush()

        # Update project
        project.active_snapshot_id = snapshot.id
        project.updated_at = datetime.utcnow()
        self._session.add(project)

        # Write files to disk
        await self._write_to_disk(project.slug, snapshot)

        # Optionally commit to git
        if settings.enable_git_snapshots:
            await self._git_commit(project.slug, snapshot)

        return snapshot

    async def rollback(self, project: Project, version: int) -> ProjectSnapshot:
        """Rollback project to a specific snapshot version."""
        result = await self._session.execute(
            select(ProjectSnapshot)
            .where(ProjectSnapshot.project_id == project.id)
            .where(ProjectSnapshot.version == version)
        )
        target = result.scalars().first()
        if not target:
            raise ValueError(f"Snapshot v{version} not found for project {project.id}")

        # Deactivate all snapshots
        all_result = await self._session.execute(
            select(ProjectSnapshot).where(ProjectSnapshot.project_id == project.id)
        )
        for snap in all_result.scalars().all():
            snap.is_active = (snap.id == target.id)
            self._session.add(snap)

        project.active_snapshot_id = target.id
        project.updated_at = datetime.utcnow()
        self._session.add(project)

        # Rewrite to disk — clean first so stale files from newer snapshots are removed
        await self._write_to_disk(project.slug, target, clean=True)

        return target

    async def list_snapshots(self, project_id: int) -> list[ProjectSnapshot]:
        result = await self._session.execute(
            select(ProjectSnapshot)
            .where(ProjectSnapshot.project_id == project_id)
            .order_by(ProjectSnapshot.version.desc())
        )
        return result.scalars().all()

    async def get_active_files(self, project: Project) -> dict[str, str]:
        """Return the currently active snapshot's files."""
        if not project.active_snapshot_id:
            return {}
        result = await self._session.execute(
            select(ProjectSnapshot).where(ProjectSnapshot.id == project.active_snapshot_id)
        )
        snap = result.scalars().first()
        return snap.files if snap else {}

    # ── Helpers ───────────────────────────────────────────────────────────────

    async def _write_to_disk(self, project_slug: str, snapshot: ProjectSnapshot, clean: bool = False) -> None:
        out_dir = settings.output_dir / project_slug
        out_dir.mkdir(parents=True, exist_ok=True)

        if clean:
            # Remove all existing generated files so rollback is a clean slate
            import shutil
            for item in out_dir.iterdir():
                if item.name.startswith(".") or item.name == "tests":
                    continue  # preserve hidden files and test output
                if item.is_dir():
                    shutil.rmtree(item)
                else:
                    item.unlink()

        for fname, content in snapshot.files.items():
            file_path = out_dir / fname
            file_path.parent.mkdir(parents=True, exist_ok=True)
            file_path.write_text(content, encoding="utf-8")
            if fname.endswith(".sh"):
                file_path.chmod(0o755)

    async def _git_commit(self, project_slug: str, snapshot: ProjectSnapshot) -> None:
        try:
            import git
            repo_path = settings.output_dir / project_slug
            try:
                repo = git.Repo(str(repo_path))
            except git.InvalidGitRepositoryError:
                repo = git.Repo.init(str(repo_path))

            repo.git.add(A=True)
            repo.index.commit(
                f"snapshot v{snapshot.version}: {snapshot.label}\n\n{snapshot.description}"
            )
        except Exception:
            pass  # Git is optional — don't fail if it's not available

    @staticmethod
    def _compute_diff(old_files: dict, new_files: dict) -> dict:
        """Simple diff: track added, removed, modified files."""
        diff = {"added": [], "removed": [], "modified": []}

        for fname in new_files:
            if fname not in old_files:
                diff["added"].append(fname)
            elif old_files[fname] != new_files[fname]:
                diff["modified"].append(fname)

        for fname in old_files:
            if fname not in new_files:
                diff["removed"].append(fname)

        return diff
