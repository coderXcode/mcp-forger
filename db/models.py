"""
All SQLModel ORM models.
Each class maps to a DB table and is also a Pydantic schema.
"""
import uuid
from datetime import datetime
from enum import Enum
from typing import Any, List, Optional

from sqlmodel import Field, Relationship, SQLModel, Column
from sqlalchemy import JSON, Text


# ─── Enums ────────────────────────────────────────────────────────────────────

class ProjectStatus(str, Enum):
    PENDING    = "pending"
    ANALYZING  = "analyzing"
    CLARIFYING = "clarifying"   # agent is asking questions
    GENERATING = "generating"
    TESTING    = "testing"
    READY      = "ready"
    ERROR      = "error"

class SourceType(str, Enum):
    OPENAPI      = "openapi"      # Swagger/OpenAPI spec URL or file
    GITHUB       = "github"       # GitHub repo URL
    UPLOAD       = "upload"       # Uploaded code files / zip
    URL          = "url"          # Live running app URL (probed)
    LOCAL_FOLDER = "local_folder" # Path to a local directory on the server
    MANUAL       = "manual"       # User describes the API manually

class TargetLanguage(str, Enum):
    PYTHON_FASTMCP = "python_fastmcp"
    NODEJS         = "nodejs"
    GO             = "go"
    GENERIC        = "generic"    # LLM decides best fit

class MessageRole(str, Enum):
    USER      = "user"
    ASSISTANT = "assistant"
    SYSTEM    = "system"

class NotificationType(str, Enum):
    INFO     = "info"
    SUCCESS  = "success"
    WARNING  = "warning"
    ERROR    = "error"
    QUESTION = "question"   # agent is asking a clarification

class TestStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    PASSED  = "passed"
    FAILED  = "failed"
    ERROR   = "error"

class LogLevel(str, Enum):
    DEBUG   = "debug"
    INFO    = "info"
    WARNING = "warning"
    ERROR   = "error"

class AuthType(str, Enum):
    NONE        = "none"
    API_KEY     = "api_key"
    BEARER      = "bearer"
    BASIC       = "basic"
    OAUTH2      = "oauth2"
    CUSTOM      = "custom"


# ─── Project ──────────────────────────────────────────────────────────────────

class ProjectBase(SQLModel):
    name: str = Field(index=True)
    description: str = ""
    source_type: SourceType = SourceType.OPENAPI
    source_url: Optional[str] = None
    target_language: TargetLanguage = TargetLanguage.PYTHON_FASTMCP
    auth_profile_id: Optional[int] = Field(default=None, foreign_key="authprofile.id")

class Project(ProjectBase, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    slug: str = Field(index=True, unique=True)
    status: ProjectStatus = ProjectStatus.PENDING
    source_content: Optional[str] = Field(default=None, sa_column=Column(Text))
    analysis_result_id: Optional[int] = Field(default=None, foreign_key="analysisresult.id")
    active_snapshot_id: Optional[int] = None
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)

    # Relationships
    snapshots: List["ProjectSnapshot"] = Relationship(back_populates="project")
    messages: List["ChatMessage"] = Relationship(back_populates="project")
    notifications: List["Notification"] = Relationship(back_populates="project")
    test_runs: List["TestRun"] = Relationship(back_populates="project")
    logs: List["LogEntry"] = Relationship(back_populates="project")

class ProjectCreate(ProjectBase):
    pass

class ProjectRead(ProjectBase):
    id: int
    slug: str
    status: ProjectStatus
    active_snapshot_id: Optional[int]
    created_at: datetime
    updated_at: datetime


# ─── Analysis Result ──────────────────────────────────────────────────────────

class AnalysisResult(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    project_id: int = Field(foreign_key="project.id", index=True)
    language: str = ""
    framework: str = ""
    # JSON blobs stored as text
    endpoints: list[dict] = Field(default_factory=list, sa_column=Column(JSON))
    schemas: dict  = Field(default_factory=dict,  sa_column=Column(JSON))
    auth_info: dict = Field(default_factory=dict, sa_column=Column(JSON))
    raw_spec: Optional[str] = Field(default=None, sa_column=Column(Text))
    created_at: datetime = Field(default_factory=datetime.utcnow)


# ─── Project Snapshot (versioning) ────────────────────────────────────────────

class ProjectSnapshot(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    project_id: int = Field(foreign_key="project.id", index=True)
    version: int
    label: str = ""
    description: str = ""
    # Dict of filename → file content
    files: dict = Field(default_factory=dict, sa_column=Column(JSON))
    # Diff from previous snapshot (JSON patch)
    diff: Optional[dict] = Field(default=None, sa_column=Column(JSON))
    is_active: bool = False
    created_at: datetime = Field(default_factory=datetime.utcnow)

    project: Optional[Project] = Relationship(back_populates="snapshots")


# ─── Chat Messages ────────────────────────────────────────────────────────────

class ChatMessage(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    project_id: int = Field(foreign_key="project.id", index=True)
    role: MessageRole
    content: str = Field(sa_column=Column(Text))
    # Extra data: suggested_changes, clarification_id, tool_calls, etc.
    extra: dict = Field(default_factory=dict, sa_column=Column(JSON))
    created_at: datetime = Field(default_factory=datetime.utcnow)

    project: Optional[Project] = Relationship(back_populates="messages")

class ChatMessageCreate(SQLModel):
    content: str
    role: MessageRole = MessageRole.USER

class ChatMessageRead(SQLModel):
    id: int
    project_id: int
    role: MessageRole
    content: str
    extra: dict
    created_at: datetime


# ─── Notifications ────────────────────────────────────────────────────────────

class Notification(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    project_id: Optional[int] = Field(default=None, foreign_key="project.id", index=True)
    type: NotificationType = NotificationType.INFO
    title: str
    message: str = Field(sa_column=Column(Text))
    is_read: bool = False
    # For QUESTION type: the agent wants an answer
    requires_response: bool = False
    response: Optional[str] = None
    link: Optional[str] = None   # deep-link URL to navigate on click (e.g. /projects/1?tab=chat)
    created_at: datetime = Field(default_factory=datetime.utcnow)

    project: Optional[Project] = Relationship(back_populates="notifications")


# ─── Test Run ─────────────────────────────────────────────────────────────────

class TestRun(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    project_id: int = Field(foreign_key="project.id", index=True)
    snapshot_id: Optional[int] = Field(default=None, foreign_key="projectsnapshot.id")
    status: TestStatus = TestStatus.PENDING
    total: int = 0
    passed: int = 0
    failed: int = 0
    skipped: int = 0
    # List of individual test result dicts
    results: list[dict] = Field(default_factory=list, sa_column=Column(JSON))
    output: Optional[str] = Field(default=None, sa_column=Column(Text))
    # The generated test file content (so users can inspect what ran)
    test_code: Optional[str] = Field(default=None, sa_column=Column(Text))
    created_at: datetime = Field(default_factory=datetime.utcnow)
    completed_at: Optional[datetime] = None

    project: Optional[Project] = Relationship(back_populates="test_runs")


# ─── Log Entry ────────────────────────────────────────────────────────────────

class LogEntry(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    project_id: Optional[int] = Field(default=None, foreign_key="project.id", index=True)
    level: LogLevel = LogLevel.INFO
    message: str = Field(sa_column=Column(Text))
    source: str = ""      # e.g. "analyzer", "generator", "agent"
    extra: dict = Field(default_factory=dict, sa_column=Column(JSON))
    created_at: datetime = Field(default_factory=datetime.utcnow)

    project: Optional[Project] = Relationship(back_populates="logs")


# ─── Auth Profile ─────────────────────────────────────────────────────────────

class AuthProfile(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    name: str = Field(unique=True)
    auth_type: AuthType = AuthType.NONE
    # Encrypted JSON config (headers, tokens, scopes, etc.)
    config_encrypted: Optional[str] = None
    description: str = ""
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)


# ─── Clarification (agent Q&A tracking) ──────────────────────────────────────

class Clarification(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    project_id: int = Field(foreign_key="project.id", index=True)
    question: str = Field(sa_column=Column(Text))
    context: dict = Field(default_factory=dict, sa_column=Column(JSON))
    answer: Optional[str] = None
    is_resolved: bool = False
    created_at: datetime = Field(default_factory=datetime.utcnow)
    resolved_at: Optional[datetime] = None
