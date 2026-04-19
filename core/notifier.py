"""
Shared helper for creating project notifications.
Keeps notification logic out of route files.
"""
from __future__ import annotations

from db.models import Notification, NotificationType


async def notify(
    session,
    project_id: int,
    type: NotificationType,
    title: str,
    message: str,
    link: str | None = None,
    requires_response: bool = False,
) -> Notification:
    """Insert a notification row. Does NOT flush or commit — caller handles that."""
    n = Notification(
        project_id=project_id,
        type=type,
        title=title,
        message=message,
        link=link,
        requires_response=requires_response,
        is_read=False,
    )
    session.add(n)
    return n


def tab_link(project_id: int, tab: str) -> str:
    """Return the deep-link URL for a project tab."""
    return f"/projects/{project_id}?tab={tab}"
