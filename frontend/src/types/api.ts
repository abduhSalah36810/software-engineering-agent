export type StageType = 'IDEA' | 'EARLY' | 'MID' | 'LATE' | 'MATURE'
export type ConfidenceType = 'LOW' | 'MEDIUM' | 'HIGH'

export interface RepoIdentitySummary {
  repo_id: string
  repo_name: string
  repo_path: string
}

export interface TechnologyItem {
  name: string
  purpose: string
  version?: string | null
  evidence?: string | null
}

export interface ProfileFinding {
  category: string
  observation: string
  evidence: string
  source: string
  severity?: string | null
}

export interface ProjectProfileSummary {
  name: string
  primary_language?: string | null
  detected_languages: string[]
  package_managers: string[]
  frameworks: TechnologyItem[]
  databases: TechnologyItem[]
  caching: TechnologyItem[]
  message_queues: TechnologyItem[]
  external_services: string[]
  entry_points: string[]
  has_docker: boolean
  has_tests: boolean
  architecture_style_observed?: string | null
  architecture_style_documented?: string | null
  findings_count: number
  findings: ProfileFinding[]
}

export interface GitCommitSummary {
  hash: string
  message: string
}

export interface GitStatusSummary {
  is_git_repo: boolean
  head_commit?: string | null
  branch?: string | null
  is_dirty: boolean
  has_uncommitted_changes: boolean
  uncommitted_files: string[]
  recent_commits: GitCommitSummary[]
}

export interface AffectedDimensionDetail {
  dimension: string
  evidence_files: string[]
  reasons: string[]
}

export interface IncrementalStatusSummary {
  status: string
  previous_commit?: string | null
  current_commit?: string | null
  is_initial_baseline: boolean
  is_baseline_stale: boolean
  requires_reverification: boolean
  has_committed_changes: boolean
  has_uncommitted_changes: boolean
  changed_files: string[]
  uncommitted_files: string[]
  committed_dimensions: string[]
  uncommitted_dimensions: string[]
  unknown_files: string[]
  dimensions_detail: AffectedDimensionDetail[]
}

export interface MemoryValiditySummary {
  has_engineering_history: boolean
  decisions_count: number
  decisions_by_validity: Record<string, number>
  investigations_count: number
  investigations_by_validity: Record<string, number>
  requires_verification_count: number
  stale_baseline_warning: boolean
}

export interface CodeHealthSummary {
  is_clean: boolean
  scanned_file_count: number
  syntax_error_count: number
  import_error_count: number
  unparseable_files_count: number
  syntax_errors: ProfileFinding[]
  import_errors: ProfileFinding[]
  unparseable_files: string[]
  freshly_computed: boolean
}

export interface ProjectStageSummary {
  stage: StageType
  confidence: ConfidenceType
  primary_signals: string[]
  conflicting_signals: string[]
  constraints: string[]
  freshly_computed: boolean
}

export interface ProjectOverviewResponse {
  identity: RepoIdentitySummary
  profile: ProjectProfileSummary | null
  git: GitStatusSummary
  incremental: IncrementalStatusSummary
  memory: MemoryValiditySummary
  health: CodeHealthSummary | null
  stage: ProjectStageSummary | null
  assessment_status: string
  assessment_message: string | null
}

export interface ApiErrorResponse {
  error: string
  detail: string
}

export type RepositoryEntryKind = 'directory' | 'file' | 'restricted' | 'other'

export interface RepositoryEntry {
  name: string
  relative_path: string
  kind: RepositoryEntryKind
  size_bytes: number | null
  modified_at: string | null
  is_symlink: boolean
}

export interface RepositoryDirectoryResponse {
  repo_path: string
  relative_path: string
  parent_path: string | null
  entries: RepositoryEntry[]
  total_entries: number
  next_offset: number | null
}

export interface RepositoryFileResponse {
  repo_path: string
  relative_path: string
  name: string
  size_bytes: number
  modified_at: string
  content: string
}

export interface InvestigationRecord {
  id: number
  problem: string
  root_cause: string | null
  plan: string | null
  result: Record<string, unknown> | null
  created_at: string | null
  current_validity: string | null
  invalidated_at: string | null
  invalidation_reason: string | null
}

export interface InvestigationListResponse {
  repo_path: string
  investigations: InvestigationRecord[]
  total_returned: number
  limit: number
}

export interface EngineeringDecisionRecord {
  id: number
  subject: string
  decision: string
  rationale: string
  source: string
  reference: string | null
  created_at: string
  current_validity: string | null
  invalidated_at: string | null
  invalidation_reason: string | null
}

export interface EngineeringChangeRecord {
  id: number
  commit_hash: string
  changed_files: string[]
  changed_symbols: string[] | null
  architecture_impact: string | null
  drift_detected: boolean
  review: string | null
  created_at: string
}

export interface EngineeringMemoryResponse {
  repo_path: string
  decisions: EngineeringDecisionRecord[]
  change_records: EngineeringChangeRecord[]
  change_records_limit: number
  change_records_truncated: boolean
}

export interface ToolDescriptor {
  name: string
  description: string
  supported_operations: string[]
  is_read_only: boolean
}

export interface ToolListResponse {
  repo_path: string
  tools: ToolDescriptor[]
}

export interface ToolEvidencePayload {
  source_tool: string
  operation: string
  category: string
  success: boolean
  is_interpreted: boolean
  target?: string | null
  timestamp: string
}

export interface ToolExecutionResponse {
  tool_name: string
  operation: string
  success: boolean
  output?: any
  error?: string | null
  metadata: Record<string, any>
  evidence?: ToolEvidencePayload | null
}
