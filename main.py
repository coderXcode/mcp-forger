"""
MCP Forge — FastAPI Application Entry Point
"""
from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request, Depends
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select

from config import settings, get_settings
from db.database import get_session, init_db
from db.models import Project, ProjectSnapshot, ChatMessage, TestRun

# ── API Routers ───────────────────────────────────────────────────────────────
from api.routes.projects    import router as projects_router
from api.routes.chat        import router as chat_router
from api.routes.generate    import router as generate_router
from api.routes.snapshots   import router as snapshots_router
from api.routes.tests       import router as tests_router
from api.routes.logs        import router as logs_router
from api.routes.config_routes import router as config_router


# ── Lifespan ──────────────────────────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    settings.ensure_dirs()
    await init_db()
    # Reset any projects stuck in GENERATING/ANALYZING due to a reload/crash
    from db.database import AsyncSessionLocal
    from db.models import Project, ProjectStatus
    from sqlmodel import select
    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(Project).where(Project.status.in_([ProjectStatus.GENERATING, ProjectStatus.ANALYZING]))
        )
        stuck = result.scalars().all()
        for p in stuck:
            p.status = ProjectStatus.READY
            session.add(p)
        if stuck:
            await session.commit()
            import logging
            logging.getLogger(__name__).warning(
                "Reset %d stuck project(s) from GENERATING/ANALYZING → READY on startup", len(stuck)
            )
    yield


# ── App ───────────────────────────────────────────────────────────────────────

app = FastAPI(
    title="MCP Forge",
    description="Convert any application into an MCP server — with AI assistance",
    version="1.0.0",
    lifespan=lifespan,
    docs_url="/docs",
    redoc_url="/redoc",
)

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Static files & templates
app.mount("/static", StaticFiles(directory="dashboard/static"), name="static")
templates = Jinja2Templates(directory="dashboard/templates")

# Inject settings into all templates
def _template_globals(request: Request):
    return {"settings": settings, "request": request}


# ── API Routes ────────────────────────────────────────────────────────────────

app.include_router(projects_router)
app.include_router(chat_router)
app.include_router(generate_router)
app.include_router(snapshots_router)
app.include_router(tests_router)
app.include_router(logs_router)
app.include_router(config_router)


# ── Health ────────────────────────────────────────────────────────────────────

@app.get("/health")
async def health():
    return {"status": "ok", "version": "1.0.0", "llm": settings.llm_provider}


# ── Dashboard Pages ───────────────────────────────────────────────────────────

@app.get("/", response_class=HTMLResponse)
async def dashboard(request: Request):
    return templates.TemplateResponse(request, "index.html", {"settings": get_settings()})


@app.get("/projects/new", response_class=HTMLResponse)
async def new_project_page(request: Request):
    return templates.TemplateResponse(request, "new_project.html", {"settings": get_settings()})


@app.get("/projects/{project_id}", response_class=HTMLResponse)
async def project_detail(
    request: Request,
    project_id: int,
    session: AsyncSession = Depends(get_session),
):
    result = await session.execute(select(Project).where(Project.id == project_id))
    project = result.scalars().first()
    if not project:
        return HTMLResponse("<h1>Project not found</h1>", status_code=404)
    return templates.TemplateResponse(
        request, "project.html",
        {"project": project, "settings": get_settings()},
    )


@app.get("/config", response_class=HTMLResponse)
async def config_page(request: Request):
    return templates.TemplateResponse(request, "config.html", {"settings": get_settings()})


# ── HTMX Partials ─────────────────────────────────────────────────────────────

@app.get("/partials/project-list", response_class=HTMLResponse)
async def partial_project_list(request: Request, session: AsyncSession = Depends(get_session)):
    result = await session.execute(select(Project).order_by(Project.updated_at.desc()))
    projects = result.scalars().all()
    return templates.TemplateResponse(
        request, "partials/project_list.html",
        {"projects": projects},
    )


@app.get("/partials/sidebar-projects", response_class=HTMLResponse)
async def partial_sidebar_projects(request: Request, session: AsyncSession = Depends(get_session)):
    result = await session.execute(
        select(Project).order_by(Project.updated_at.desc()).limit(10)
    )
    projects = result.scalars().all()
    return templates.TemplateResponse(
        request, "partials/sidebar_projects.html",
        {"projects": projects},
    )


@app.get("/partials/project-status/{project_id}", response_class=HTMLResponse)
async def partial_project_status(
    request: Request, project_id: int, session: AsyncSession = Depends(get_session)
):
    result = await session.execute(select(Project).where(Project.id == project_id))
    project = result.scalars().first()
    if not project:
        return HTMLResponse("")

    status = project.status.value
    spin = status in ["analyzing", "generating", "testing"]
    color_map = {
        "ready": "bg-green-900 text-green-300",
        "analyzing": "bg-yellow-900 text-yellow-300",
        "generating": "bg-yellow-900 text-yellow-300",
        "testing": "bg-blue-900 text-blue-300",
        "error": "bg-red-900 text-red-300",
    }
    color = color_map.get(status, "bg-gray-700 text-gray-400")
    icon = '<i class="fa-solid fa-spinner fa-spin mr-1.5 text-xs"></i>' if spin else ""
    return HTMLResponse(
        f'<span class="status-badge {color}">{icon}{status.title()}</span>'
    )


@app.get("/partials/chat-messages/{project_id}", response_class=HTMLResponse)
async def partial_chat_messages(
    request: Request, project_id: int, session: AsyncSession = Depends(get_session)
):
    result = await session.execute(
        select(ChatMessage)
        .where(ChatMessage.project_id == project_id)
        .order_by(ChatMessage.created_at.asc())
    )
    messages = result.scalars().all()
    return templates.TemplateResponse(
        request, "partials/chat_messages.html",
        {"messages": messages},
    )


@app.get("/partials/snapshot-files/{project_id}/{version}", response_class=HTMLResponse)
async def partial_snapshot_files(
    request: Request, project_id: int, version: int, session: AsyncSession = Depends(get_session)
):
    result = await session.execute(
        select(ProjectSnapshot)
        .where(ProjectSnapshot.project_id == project_id)
        .where(ProjectSnapshot.version == version)
    )
    snap = result.scalars().first()
    if not snap:
        return HTMLResponse('<p class="text-red-400">Snapshot not found.</p>')
    return templates.TemplateResponse(
        request, "partials/snapshot_files.html",
        {"files": snap.files or {}},
    )


@app.get("/partials/snapshot-list/{project_id}", response_class=HTMLResponse)
async def partial_snapshot_list(
    request: Request, project_id: int, session: AsyncSession = Depends(get_session)
):
    result = await session.execute(
        select(ProjectSnapshot)
        .where(ProjectSnapshot.project_id == project_id)
        .order_by(ProjectSnapshot.version.desc())
    )
    snapshots = result.scalars().all()
    return templates.TemplateResponse(
        request, "partials/snapshot_list.html",
        {"snapshots": snapshots, "project_id": project_id},
    )


@app.get("/partials/test-runs/{project_id}", response_class=HTMLResponse)
async def partial_test_runs(
    request: Request, project_id: int, session: AsyncSession = Depends(get_session)
):
    result = await session.execute(
        select(TestRun)
        .where(TestRun.project_id == project_id)
        .order_by(TestRun.created_at.desc())
        .limit(10)
    )
    runs = result.scalars().all()
    return templates.TemplateResponse(
        request, "partials/test_runs.html",
        {"runs": runs},
    )


@app.get("/partials/analysis-summary/{project_id}", response_class=HTMLResponse)
async def partial_analysis_summary(
    request: Request, project_id: int, session: AsyncSession = Depends(get_session)
):
    from db.models import AnalysisResult
    result = await session.execute(
        select(AnalysisResult)
        .where(AnalysisResult.project_id == project_id)
        .order_by(AnalysisResult.created_at.desc())
    )
    analysis = result.scalars().first()
    if not analysis:
        return HTMLResponse(
            '<h3 class="font-semibold text-white mb-4">Analysis Summary</h3>'
            '<p class="text-sm text-gray-500">No analysis yet. Click Re-analyze to start.</p>'
        )
    endpoints = analysis.endpoints or []
    tools_count = sum(1 for e in endpoints if e.get("mcp_type") == "tool")
    resources_count = sum(1 for e in endpoints if e.get("mcp_type") == "resource")
    auth_info = analysis.auth_info or {}
    auth_str = ', '.join(auth_info.keys()) if auth_info else 'none'
    return HTMLResponse(f"""
        <h3 class="font-semibold text-white mb-4">Analysis Summary</h3>
        <dl class="space-y-3 text-sm">
          <div class="flex justify-between"><dt class="text-gray-400">Language</dt><dd class="text-white font-mono">{analysis.language or '—'}</dd></div>
          <div class="flex justify-between"><dt class="text-gray-400">Framework</dt><dd class="text-white font-mono">{analysis.framework or '—'}</dd></div>
          <div class="flex justify-between"><dt class="text-gray-400">Total Endpoints</dt><dd class="text-white">{len(endpoints)}</dd></div>
          <div class="flex justify-between"><dt class="text-gray-400">Tools</dt><dd class="text-green-400">{tools_count}</dd></div>
          <div class="flex justify-between"><dt class="text-gray-400">Resources</dt><dd class="text-blue-400">{resources_count}</dd></div>
          <div class="flex justify-between"><dt class="text-gray-400">Auth</dt><dd class="text-white text-xs">{auth_str}</dd></div>
        </dl>
    """)


@app.get("/partials/clarifications/{project_id}", response_class=HTMLResponse)
async def partial_clarifications(
    request: Request, project_id: int, session: AsyncSession = Depends(get_session)
):
    from db.models import Clarification
    result = await session.execute(
        select(Clarification)
        .where(Clarification.project_id == project_id)
        .where(Clarification.is_resolved == False)
        .order_by(Clarification.created_at.asc())
    )
    clarifications = result.scalars().all()
    if not clarifications:
        return HTMLResponse("")

    html = '<div id="clarifications-panel" class="space-y-3">'
    for c in clarifications:
        safe_q = c.question.replace('"', '&quot;').replace("'", "&#39;")
        html += f"""
        <div class="bg-yellow-900/30 border border-yellow-700/50 rounded-lg p-4 space-y-2">
          <div class="flex items-start gap-2">
            <i class="fa-solid fa-circle-question text-yellow-400 text-sm mt-0.5 flex-shrink-0"></i>
            <p class="text-sm text-yellow-200">{c.question}</p>
          </div>
          <div class="flex gap-2 items-center">
            <input id="clarify-input-{c.id}"
                   type="text"
                   placeholder="Type your answer…"
                   class="flex-1 bg-gray-800 border border-gray-600 text-white text-sm rounded-lg px-3 py-1.5 focus:outline-none focus:border-yellow-500"
                   onkeydown="if(event.key==='Enter'){{document.getElementById('clarify-btn-{c.id}').click()}}" />
            <button id="clarify-btn-{c.id}"
                    onclick="answerClarification({c.id}, {project_id}, '{safe_q}')"
                    class="text-xs bg-yellow-700 hover:bg-yellow-600 text-white px-3 py-1.5 rounded-lg flex-shrink-0 transition-colors">
              Submit
            </button>
          </div>
        </div>"""
    html += """</div>
<script>
async function answerClarification(id, projectId, question) {
  const input = document.getElementById('clarify-input-' + id);
  const answer = input.value.trim();
  if (!answer) { input.focus(); return; }
  const btn = document.getElementById('clarify-btn-' + id);
  btn.disabled = true;
  btn.textContent = 'Sending…';
  try {
    const r = await fetch(`/api/projects/${projectId}/chat/clarifications/${id}/answer`, {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({content: answer})
    });
    if (r.ok) {
      // Reload clarifications panel
      const panel = document.getElementById('clarifications-panel');
      const refresh = await fetch(`/partials/clarifications/${projectId}`);
      panel.outerHTML = await refresh.text() || '';
      // Reload chat messages so the agent response appears
      htmx.trigger(document.getElementById('chat-messages'), 'refresh');
    } else {
      btn.disabled = false; btn.textContent = 'Submit';
    }
  } catch(e) { btn.disabled = false; btn.textContent = 'Submit'; }
}
</script>"""
    return HTMLResponse(html)


# ── Log SSE partial (raw HTML line for live appending) ───────────────────────

@app.get("/sse/log-line")
async def sse_log_line(level: str = "info", message: str = "", source: str = ""):
    """Used by SSE beforeend swap to append a log line."""
    color = {"debug": "text-gray-500", "info": "text-blue-400",
             "warning": "text-yellow-400", "error": "text-red-400"}.get(level, "text-gray-300")
    return HTMLResponse(
        f'<div class="{color} flex gap-2">'
        f'<span class="text-gray-600">[{source}]</span>'
        f'<span>{message}</span>'
        f'</div>\n'
    )


# ── Run ───────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=settings.port,
        reload=settings.debug,
        log_level=settings.log_level.lower(),
    )
