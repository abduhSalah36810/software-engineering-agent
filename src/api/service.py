# src/api/service.py
"""
Service layer for read-only project overview data aggregation.

Orchestrates deterministic helpers:
  - Canonical repo identity resolution
  - Git context & working-tree status
  - Engineering memory reads (RepoProfile, decisions, investigations)
  - Incremental change intelligence & affected dimensions
  - Conditional code health assessment & project stage inference

Guarantees:
  - Zero SQLite mutations
  - Zero git modifications
  - Zero full-agent-graph or tool executions
  - Fast baseline execution (<15ms) when assessment is not explicitly requested
"""

from pathlib import Path

from src.helpers.repo import get_canonical_repo_id
from src.helpers.git_context import get_git_context, get_git_working_tree_status
from src.helpers.incremental_change import IncrementalChangeDetector
from src.helpers.repository_assessment import RepositoryAssessmentEngine
from src.helpers.project_stage import ProjectStageInferencer
from src.memory.sqlite_store import EngineeringMemoryStore
from src.models.repo_profile import RepoProfile

from src.api.schemas import (
    AffectedDimensionDetail,
    CodeHealthSummary,
    GitCommitSummary,
    GitStatusSummary,
    IncrementalStatusSummary,
    MemoryValiditySummary,
    ProfileFinding,
    ProjectOverviewResponse,
    ProjectProfileSummary,
    ProjectStageSummary,
    RepoIdentitySummary,
    TechnologyItem,
)


def build_project_overview(
    resolved_path: Path,
    include_assessment: bool = False,
    memory_store: EngineeringMemoryStore | None = None,
) -> ProjectOverviewResponse:
    """
    Builds a complete, deterministic, read-only ProjectOverviewResponse.
    """
    repo_path_str = str(resolved_path)
    repo_id = get_canonical_repo_id(resolved_path)
    repo_name = resolved_path.name

    store = memory_store or EngineeringMemoryStore()

    # 1. Project Profile from SQLite engineering memory
    profile_dict = store.load_repo_profile(repo_id)
    if profile_dict is None and repo_name != repo_id:
        profile_dict = store.load_repo_profile(repo_name)

    profile_obj: RepoProfile | None = None
    profile_summary: ProjectProfileSummary | None = None
    display_name = repo_name

    if profile_dict is not None:
        try:
            profile_obj = RepoProfile.from_dict(profile_dict)
            if profile_obj.name:
                display_name = profile_obj.name

            profile_summary = ProjectProfileSummary(
                name=profile_obj.name or repo_name,
                primary_language=profile_obj.primary_language,
                detected_languages=list(profile_obj.detected_languages or []),
                package_managers=list(profile_obj.package_managers or []),
                frameworks=[
                    TechnologyItem(
                        name=t.name,
                        purpose=t.purpose,
                        version=t.version,
                        evidence=t.evidence,
                    )
                    for t in (profile_obj.frameworks or [])
                ],
                databases=[
                    TechnologyItem(
                        name=d.name,
                        purpose=d.purpose,
                        version=d.version,
                        evidence=d.evidence,
                    )
                    for d in (profile_obj.databases or [])
                ],
                caching=[
                    TechnologyItem(
                        name=c.name,
                        purpose=c.purpose,
                        version=c.version,
                        evidence=c.evidence,
                    )
                    for c in (profile_obj.caching or [])
                ],
                message_queues=[
                    TechnologyItem(
                        name=m.name,
                        purpose=m.purpose,
                        version=m.version,
                        evidence=m.evidence,
                    )
                    for m in (profile_obj.message_queues or [])
                ],
                external_services=list(profile_obj.external_services or []),
                entry_points=list(profile_obj.entry_points or []),
                has_docker=bool(profile_obj.has_docker),
                has_tests=bool(profile_obj.has_tests),
                architecture_style_observed=profile_obj.architecture_style_observed,
                architecture_style_documented=profile_obj.architecture_style_documented,
                findings_count=len(profile_obj.findings or []),
                findings=[
                    ProfileFinding(
                        category=f.category,
                        observation=f.observation,
                        evidence=f.evidence,
                        source=f.source,
                        severity=f.severity,
                    )
                    for f in (profile_obj.findings or [])
                ],
            )
        except Exception:
            profile_summary = None

    # 2. Decisions & Investigations Validity Counts from Memory (via SQL COUNT)
    dec_counts = store.count_decisions_by_validity(repo_id)
    if not dec_counts and repo_name != repo_id:
        dec_counts = store.count_decisions_by_validity(repo_name)
    total_decisions = sum(dec_counts.values())

    inv_counts = store.count_investigations_by_validity(repo_id)
    if not inv_counts and repo_name != repo_id:
        inv_counts = store.count_investigations_by_validity(repo_name)
    total_investigations = sum(inv_counts.values())

    has_history = store.has_engineering_history(repo_id)
    req_ver_count = (
        dec_counts.get("REQUIRES_VERIFICATION", 0)
        + inv_counts.get("REQUIRES_VERIFICATION", 0)
    )

    # 3. Git Status
    git_ctx = get_git_context(repo_path_str)
    is_dirty, uncommitted_files = get_git_working_tree_status(repo_path_str)
    git_summary = GitStatusSummary(
        is_git_repo=git_ctx.is_git_repo,
        head_commit=git_ctx.head_commit,
        branch=git_ctx.branch,
        is_dirty=is_dirty,
        has_uncommitted_changes=len(uncommitted_files) > 0,
        uncommitted_files=uncommitted_files,
        recent_commits=[
            GitCommitSummary(hash=c["hash"], message=c["message"])
            for c in git_ctx.recent_commits
        ],
    )

    # 4. Incremental Change Detection & Affected Dimensions
    detector = IncrementalChangeDetector(
        repo_path=repo_path_str,
        repo_name=display_name,
        repo_id=repo_id,
        memory=store,
    )
    change_result = detector.detect_changes()
    dims_result = detector.detect_affected_dimensions()

    all_dims_detail = [
        AffectedDimensionDetail(
            dimension=d.dimension,
            evidence_files=list(d.evidence_files),
            reasons=list(d.reasons),
        )
        for d in (dims_result.committed + dims_result.uncommitted)
    ]

    stale_baseline_warning = (
        change_result.is_baseline_stale
        or change_result.requires_reverification
        or req_ver_count > 0
    )

    incremental_summary = IncrementalStatusSummary(
        status=change_result.status,
        previous_commit=change_result.previous_commit,
        current_commit=change_result.current_commit,
        is_initial_baseline=change_result.is_initial_baseline,
        is_baseline_stale=change_result.is_baseline_stale,
        requires_reverification=change_result.requires_reverification,
        has_committed_changes=change_result.has_committed_changes,
        has_uncommitted_changes=change_result.has_uncommitted_changes,
        changed_files=change_result.changed_files,
        uncommitted_files=change_result.uncommitted_files,
        committed_dimensions=dims_result.committed_affected_dimensions,
        uncommitted_dimensions=dims_result.uncommitted_affected_dimensions,
        unknown_files=dims_result.unknown_files,
        dimensions_detail=all_dims_detail,
    )

    memory_summary = MemoryValiditySummary(
        has_engineering_history=has_history,
        decisions_count=total_decisions,
        decisions_by_validity=dec_counts,
        investigations_count=total_investigations,
        investigations_by_validity=inv_counts,
        requires_verification_count=req_ver_count,
        stale_baseline_warning=stale_baseline_warning,
    )

    # 5. Assessment and Project Stage Synthesis
    health_summary: CodeHealthSummary | None = None
    stage_summary: ProjectStageSummary | None = None

    if include_assessment:
        assessment_engine = RepositoryAssessmentEngine(
            repo_path=repo_path_str,
            profile=profile_obj,
        )
        assessment = assessment_engine.build_assessment()
        stage_inferencer = ProjectStageInferencer()
        stage_res = stage_inferencer.infer(assessment, profile=profile_obj)

        health_summary = CodeHealthSummary(
            is_clean=assessment.health.is_clean,
            scanned_file_count=assessment.health.scanned_file_count,
            syntax_error_count=len(assessment.health.syntax_errors),
            import_error_count=len(assessment.health.import_errors),
            unparseable_files_count=len(assessment.health.unparseable_files),
            syntax_errors=[
                ProfileFinding(
                    category=f.category,
                    observation=f.observation,
                    evidence=f.evidence,
                    source=f.source,
                    severity=f.severity,
                )
                for f in assessment.health.syntax_errors
            ],
            import_errors=[
                ProfileFinding(
                    category=f.category,
                    observation=f.observation,
                    evidence=f.evidence,
                    source=f.source,
                    severity=f.severity,
                )
                for f in assessment.health.import_errors
            ],
            unparseable_files=list(assessment.health.unparseable_files),
            freshly_computed=True,
        )

        stage_summary = ProjectStageSummary(
            stage=stage_res.stage,
            confidence=stage_res.confidence,
            primary_signals=stage_res.primary_signals,
            conflicting_signals=stage_res.conflicting_signals,
            constraints=stage_res.constraints,
            freshly_computed=True,
        )
        assessment_status = "computed"
        assessment_message = None
    else:
        assessment_status = "not_requested"
        assessment_message = (
            "Code health and project stage were not computed. Pass include_assessment=true "
            "to execute deterministic AST and engineering assessment."
        )

    identity_summary = RepoIdentitySummary(
        repo_id=repo_id,
        repo_name=display_name,
        repo_path=repo_path_str,
    )

    return ProjectOverviewResponse(
        identity=identity_summary,
        profile=profile_summary,
        git=git_summary,
        incremental=incremental_summary,
        memory=memory_summary,
        health=health_summary,
        stage=stage_summary,
        assessment_status=assessment_status,
        assessment_message=assessment_message,
    )
