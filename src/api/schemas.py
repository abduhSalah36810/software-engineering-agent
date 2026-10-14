"""
Pydantic API DTOs and Schemas for Read-Only Project Overview.

Strictly separated from internal LangGraph AgentState and dataclasses.
Provides clean, structured, serializable responses for the frontend.
"""

from typing import Any, Literal
from pydantic import BaseModel, Field

StageType = Literal["IDEA", "EARLY", "MID", "LATE", "MATURE"]
ConfidenceType = Literal["LOW", "MEDIUM", "HIGH"]


class RepoIdentitySummary(BaseModel):
    """Canonical repository identity and display metadata."""
    repo_id: str = Field(description="Canonical resolved absolute path identifier")
    repo_name: str = Field(description="Display name of the repository")
    repo_path: str = Field(description="Resolved filesystem path string")


class TechnologyItem(BaseModel):
    """Detected library, framework, database, or tool."""
    name: str
    purpose: str
    version: str | None = None
    evidence: str | None = None


class ProfileFinding(BaseModel):
    """Evidence-backed discovery or diagnostic finding."""
    category: str
    observation: str
    evidence: str
    source: str
    severity: str | None = None


class ProjectProfileSummary(BaseModel):
    """Persisted engineering profile from SQLite memory store."""
    name: str
    primary_language: str | None = None
    detected_languages: list[str] = Field(default_factory=list)
    package_managers: list[str] = Field(default_factory=list)
    frameworks: list[TechnologyItem] = Field(default_factory=list)
    databases: list[TechnologyItem] = Field(default_factory=list)
    caching: list[TechnologyItem] = Field(default_factory=list)
    message_queues: list[TechnologyItem] = Field(default_factory=list)
    external_services: list[str] = Field(default_factory=list)
    entry_points: list[str] = Field(default_factory=list)
    has_docker: bool = False
    has_tests: bool = False
    architecture_style_observed: str | None = None
    architecture_style_documented: str | None = None
    findings_count: int = 0
    findings: list[ProfileFinding] = Field(default_factory=list)


class GitCommitSummary(BaseModel):
    """Compact summary of a git commit."""
    hash: str
    message: str


class GitStatusSummary(BaseModel):
    """Current Git working-tree and revision status."""
    is_git_repo: bool
    head_commit: str | None = None
    branch: str | None = None
    is_dirty: bool = False
    has_uncommitted_changes: bool = False
    uncommitted_files: list[str] = Field(default_factory=list)
    recent_commits: list[GitCommitSummary] = Field(default_factory=list)


class AffectedDimensionDetail(BaseModel):
    """Detailed evidence for an affected engineering dimension."""
    dimension: str
    evidence_files: list[str] = Field(default_factory=list)
    reasons: list[str] = Field(default_factory=list)


class IncrementalStatusSummary(BaseModel):
    """Change intelligence delta between engineering baseline and working tree."""
    status: str
    previous_commit: str | None = None
    current_commit: str | None = None
    is_initial_baseline: bool = False
    is_baseline_stale: bool = False
    requires_reverification: bool = False
    has_committed_changes: bool = False
    has_uncommitted_changes: bool = False
    changed_files: list[str] = Field(default_factory=list)
    uncommitted_files: list[str] = Field(default_factory=list)
    committed_dimensions: list[str] = Field(default_factory=list)
    uncommitted_dimensions: list[str] = Field(default_factory=list)
    unknown_files: list[str] = Field(default_factory=list)
    dimensions_detail: list[AffectedDimensionDetail] = Field(default_factory=list)


class MemoryValiditySummary(BaseModel):
    """Counts and validity status of persisted engineering decisions and investigations."""
    has_engineering_history: bool = False
    decisions_count: int = 0
    decisions_by_validity: dict[str, int] = Field(default_factory=dict)
    investigations_count: int = 0
    investigations_by_validity: dict[str, int] = Field(default_factory=dict)
    requires_verification_count: int = 0
    stale_baseline_warning: bool = False


class CodeHealthSummary(BaseModel):
    """AST syntax compilation, import integrity, and parseability diagnostic findings."""
    is_clean: bool
    scanned_file_count: int = 0
    syntax_error_count: int = 0
    import_error_count: int = 0
    unparseable_files_count: int = 0
    syntax_errors: list[ProfileFinding] = Field(default_factory=list)
    import_errors: list[ProfileFinding] = Field(default_factory=list)
    unparseable_files: list[str] = Field(default_factory=list)
    freshly_computed: bool = True


class ProjectStageSummary(BaseModel):
    """Multi-dimensional project stage synthesis."""
    stage: StageType
    confidence: ConfidenceType
    primary_signals: list[str] = Field(default_factory=list)
    conflicting_signals: list[str] = Field(default_factory=list)
    constraints: list[str] = Field(default_factory=list)
    freshly_computed: bool = True


class ProjectOverviewResponse(BaseModel):
    """Read-only dashboard overview response payload."""
    identity: RepoIdentitySummary
    profile: ProjectProfileSummary | None = None
    git: GitStatusSummary
    incremental: IncrementalStatusSummary
    memory: MemoryValiditySummary
    health: CodeHealthSummary | None = None
    stage: ProjectStageSummary | None = None
    assessment_status: str = Field(
        description="Indicates assessment state: computed, not_requested, or unavailable"
    )
    assessment_message: str | None = None


class InvestigationRecord(BaseModel):
    """Persisted investigation data; fields remain nullable when not recorded."""
    id: int
    problem: str
    root_cause: str | None = None
    plan: str | None = None
    result: dict[str, Any] | None = None
    created_at: str | None = None
    current_validity: str | None = None
    invalidated_at: str | None = None
    invalidation_reason: str | None = None


class InvestigationListResponse(BaseModel):
    """Read-only persisted investigations for one authorized repository."""
    repo_path: str
    investigations: list[InvestigationRecord] = Field(default_factory=list)
    total_returned: int
    limit: int


class EngineeringDecisionRecord(BaseModel):
    """A persisted engineering decision and its recorded source metadata."""
    id: int
    subject: str
    decision: str
    rationale: str
    source: str
    reference: str | None = None
    created_at: str
    current_validity: str | None = None
    invalidated_at: str | None = None
    invalidation_reason: str | None = None


class EngineeringChangeRecord(BaseModel):
    """A persisted commit observation and its separately recorded impact fields."""
    id: int
    commit_hash: str
    changed_files: list[str] = Field(default_factory=list)
    changed_symbols: list[str] | None = None
    architecture_impact: str | None = None
    drift_detected: bool
    review: str | None = None
    created_at: str


class EngineeringMemoryResponse(BaseModel):
    """Persisted decisions and change records for an authorized repository."""
    repo_path: str
    decisions: list[EngineeringDecisionRecord] = Field(default_factory=list)
    change_records: list[EngineeringChangeRecord] = Field(default_factory=list)
    change_records_limit: int
    change_records_truncated: bool


class ErrorResponse(BaseModel):
    """Standardized API error response format."""
    error: str
    detail: str


class RepositoryEntry(BaseModel):
    """One immediate child in a repository-relative directory listing."""
    name: str
    relative_path: str
    kind: Literal["directory", "file", "restricted", "other"]
    size_bytes: int | None = None
    modified_at: str | None = None
    is_symlink: bool = False


class RepositoryDirectoryResponse(BaseModel):
    """A page of immediate directory children within an authorized repository."""
    repo_path: str
    relative_path: str
    parent_path: str | None
    entries: list[RepositoryEntry] = Field(default_factory=list)
    total_entries: int
    next_offset: int | None = None


class RepositoryFileResponse(BaseModel):
    """Bounded UTF-8 text preview of one repository-relative file."""
    repo_path: str
    relative_path: str
    name: str
    size_bytes: int
    modified_at: str
    content: str


class ToolDescriptor(BaseModel):
    """Metadata describing a registered tool adapter and its capabilities."""
    name: str
    description: str
    supported_operations: list[str] = Field(default_factory=list)
    is_read_only: bool = True


class ToolListResponse(BaseModel):
    """List of registered and available tools for an authorized repository."""
    repo_path: str
    tools: list[ToolDescriptor] = Field(default_factory=list)


class ToolExecutionRequest(BaseModel):
    """Request to execute an authorized tool operation on an authorized repository."""
    repo_path: str = Field(description="Authorized repository root path")
    tool_name: str = Field(description="Name of the tool (e.g. git, filesystem, terminal)")
    operation: str = Field(description="Operation to execute (e.g. status, diff, read_file)")
    arguments: dict[str, Any] = Field(default_factory=dict, description="Parameters for the tool operation")


class ToolEvidencePayload(BaseModel):
    """Raw observed evidence record produced by tool execution."""
    source_tool: str
    operation: str
    category: str
    success: bool
    is_interpreted: bool = False
    target: str | None = None
    timestamp: str = ""


class ToolExecutionResponse(BaseModel):
    """Structured result of an authorized tool execution."""
    tool_name: str
    operation: str
    success: bool
    output: Any = None
    error: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    evidence: ToolEvidencePayload | None = None
