"""
Phase 4.4 — Incremental Understand Again.

Deterministic mechanism that allows the agent to "understand again" only
what became affected after repository evolution.

Answers:
    "Given what changed since the last engineering state, what existing
     engineering knowledge can we deterministically recompute, what can
     remain preserved, and what still requires verification?"

Design principles:
  - Deterministic. Zero LLM. Zero external services. Zero code modification.
  - Reuses existing deterministic engines:
      * RepoDiscovery (repo_discovery.py)
      * RepositoryAssessmentEngine (repository_assessment.py)
      * ProjectStageInferencer (project_stage.py)
      * Git context helpers (git_context.py)
      * EngineeringMemoryStore (sqlite_store.py)
  - CRITICAL SEMANTIC RULE:
      dimension recomputed != memory record revalidated
    A deterministic reassessment of a dimension does NOT automatically prove
    that historical decisions or investigations in that dimension are still valid.
  - recomputed_dimensions: Current deterministic engineering facts/assessment
    for that dimension were successfully recomputed.
  - revalidated_records: Contains ONLY records for which newly available
    deterministic evidence directly proves the stored knowledge remains consistent.
  - If direct evidence is insufficient: record REMAINS REQUIRES_VERIFICATION.
  - Stale baseline preserves STALE; does not fabricate diffs or partial revalidations.
  - Uncommitted changes produce session-scoped results; zero permanent SQLite validity updates.
  - Historical records are NEVER deleted.
  - Uses canonical repository identity: repo_id = str(Path(repo_path).resolve()).
"""

from __future__ import annotations

from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal
import json
import os

from src.helpers.repo import get_canonical_repo_id
from src.helpers.repo_discovery import RepoDiscovery
from src.helpers.repository_assessment import RepositoryAssessmentEngine
from src.helpers.project_stage import ProjectStageInferencer
from src.helpers.git_context import get_git_context
from src.memory.sqlite_store import EngineeringMemoryStore
from src.helpers.incremental_change import IncrementalChangeResult
from src.helpers.affected_dimensions import AffectedDimensionsResult, SUPPORTED_DIMENSIONS
from src.helpers.memory_invalidation import MemoryInvalidationResult


# ── Data structures ──────────────────────────────────────────────────────────


@dataclass
class ReunderstoodDimension:
    """Represents the re-understanding status and evidence for a single dimension."""
    dimension: str
    status: str                         # "recomputed" | "preserved"
    evidence: dict = field(default_factory=dict)
    reasons: list = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "ReunderstoodDimension":
        return cls(
            dimension=str(data["dimension"]),
            status=str(data["status"]),
            evidence=dict(data.get("evidence", {})),
            reasons=list(data.get("reasons", [])),
        )


@dataclass
class IncrementalUnderstandResult:
    """
    Structured outcome of Phase 4.4 Incremental Understand Again.

    Answers:
      - What changed? (repo_id, status)
      - What was recomputed? (recomputed_dimensions)
      - What was preserved? (preserved_dimensions)
      - What was revalidated? (revalidated_records)
      - What remains unresolved? (unresolved_records)
      - What is the updated engineering state? (updated_profile, updated_assessment)
      - Is deterministic processing complete? (deterministic_processing_complete)
    """
    repo_id: str
    status: str                         # "no_changes" | "reunderstood" | "stale_baseline" | "initial_baseline"
    affected_dimensions: list           # sorted list of affected dimension names
    recomputed_dimensions: list         # sorted list of recomputed dimension names
    preserved_dimensions: list          # sorted list of preserved dimension names
    revalidated_records: list           # list of dicts: [{record_type, id, previous_validity, new_validity, reason}]
    unresolved_records: list            # list of dicts: [{record_type, id, validity, reason}]
    updated_profile: dict | None
    updated_assessment: dict | None
    deterministic_processing_complete: bool

    def to_dict(self) -> dict:
        return asdict(self)

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), indent=2)

    @classmethod
    def from_dict(cls, data: dict) -> "IncrementalUnderstandResult":
        return cls(
            repo_id=str(data["repo_id"]),
            status=str(data["status"]),
            affected_dimensions=list(data.get("affected_dimensions", [])),
            recomputed_dimensions=list(data.get("recomputed_dimensions", [])),
            preserved_dimensions=list(data.get("preserved_dimensions", [])),
            revalidated_records=list(data.get("revalidated_records", [])),
            unresolved_records=list(data.get("unresolved_records", [])),
            updated_profile=data.get("updated_profile"),
            updated_assessment=data.get("updated_assessment"),
            deterministic_processing_complete=bool(data.get("deterministic_processing_complete", False)),
        )


# ── Invalidation Decision Evaluator ──────────────────────────────────────────


def _evaluate_decision(
    decision: dict,
    recomputed_evidence: dict,
    profile_dict: dict | None,
) -> tuple[bool, str]:
    """
    Determines whether newly recomputed deterministic evidence directly confirms
    that a stored decision remains consistent.

    Returns:
        (True, reason)  -> directly confirmed by deterministic evidence
        (False, reason) -> evidence is insufficient or inconclusive
    """
    subject = (decision.get("subject") or "").lower().strip()
    dec_val = (decision.get("decision") or "").lower().strip()

    # Rule 1: Testing decisions
    if subject in ("tests", "testing", "test_framework") and "tests" in recomputed_evidence:
        t_info = recomputed_evidence["tests"]
        frameworks = [f.lower() for f in t_info.get("frameworks", [])]
        for fw in frameworks:
            if fw in dec_val or dec_val in fw:
                return True, f"Testing framework '{decision.get('decision')}' confirmed present in test assessment"
        if dec_val in ("has_tests", "true") and t_info.get("has_tests"):
            return True, "Presence of tests confirmed by deterministic test assessment"

    # Rule 2: Dependency / package manager decisions
    if subject in ("dependencies", "package_manager", "manifest") and "dependencies" in recomputed_evidence:
        d_info = recomputed_evidence["dependencies"]
        pms = [p.lower() for p in d_info.get("package_managers", [])]
        manifests = [m.lower() for m in d_info.get("manifests", [])]
        for pm in pms:
            if pm in dec_val or dec_val in pm:
                return True, f"Package manager '{decision.get('decision')}' confirmed by manifest inspection"
        for man in manifests:
            if man in dec_val or dec_val in man:
                return True, f"Dependency manifest '{decision.get('decision')}' confirmed present"

    # Rule 3: Language / source code decisions
    if subject in ("language", "primary_language", "source_code") and "source_code" in recomputed_evidence:
        c_info = recomputed_evidence["source_code"]
        if profile_dict:
            langs = [l.lower() for l in profile_dict.get("detected_languages", [])]
            primary = (profile_dict.get("primary_language") or "").lower()
            if (dec_val in langs or dec_val == primary or primary in dec_val) and c_info.get("is_clean", True):
                return True, f"Language '{decision.get('decision')}' confirmed present and source syntax is clean"

    # Rule 4: Database / technology infrastructure decisions
    if subject in ("database", "caching", "message_queues", "deployment") and profile_dict:
        tech_entries = profile_dict.get(subject, [])
        for entry in tech_entries:
            entry_name = (entry.get("name") if isinstance(entry, dict) else getattr(entry, "name", "")).lower()
            if entry_name in dec_val or dec_val in entry_name:
                return True, f"Technology '{decision.get('decision')}' directly confirmed in repository profile"
        if subject == "deployment" and profile_dict.get("has_docker") and "docker" in dec_val:
            return True, "Docker deployment configuration directly confirmed in repository profile"

    # Fallback: insufficient deterministic evidence
    return False, "Deterministic evidence insufficient to verify decision; remains requiring verification"


# ── Incremental Understand Engine ─────────────────────────────────────────────


class IncrementalUnderstandEngine:
    """
    Deterministic Incremental Understand Again engine (Phase 4.4).
    """

    def __init__(self, memory: EngineeringMemoryStore | None = None) -> None:
        self.memory = memory

    def understand(
        self,
        change_result: IncrementalChangeResult,
        dims_result: AffectedDimensionsResult,
        invalidation_result: MemoryInvalidationResult,
        repo_path: str | Path | None = None,
        memory: EngineeringMemoryStore | None = None,
    ) -> IncrementalUnderstandResult:
        """
        Executes minimal deterministic re-understanding of affected dimensions.
        """
        store = memory or self.memory

        # 1. Resolve canonical repository identity
        if repo_path:
            canonical_id = get_canonical_repo_id(repo_path)
            str_path = str(repo_path)
        else:
            canonical_id = getattr(change_result, "repo_id", "unknown")
            str_path = canonical_id if os.path.exists(canonical_id) else None

        is_initial_baseline = bool(getattr(change_result, "is_initial_baseline", False))
        is_baseline_stale = bool(getattr(change_result, "is_baseline_stale", False))
        requires_reverification = bool(getattr(change_result, "requires_reverification", False))

        # ── Case A: Initial baseline ────────────────────────────────────────
        if is_initial_baseline:
            return IncrementalUnderstandResult(
                repo_id=canonical_id,
                status="initial_baseline",
                affected_dimensions=[],
                recomputed_dimensions=[],
                preserved_dimensions=sorted(SUPPORTED_DIMENSIONS),
                revalidated_records=[],
                unresolved_records=[],
                updated_profile=None,
                updated_assessment=None,
                deterministic_processing_complete=True,
            )

        # ── Case B: Stale baseline ──────────────────────────────────────────
        if is_baseline_stale or requires_reverification:
            unresolved = []
            if store:
                decisions = store.load_decisions(canonical_id)
                investigations = store.load_investigations(canonical_id)
                for dec in decisions:
                    if dec.get("current_validity") in ("STALE", "REQUIRES_VERIFICATION"):
                        unresolved.append({
                            "record_type": "decision",
                            "id": dec["id"],
                            "validity": dec.get("current_validity", "STALE"),
                            "reason": "Repository baseline is stale or untrusted; cannot incrementally revalidate",
                        })
                for inv in investigations:
                    if inv.get("current_validity") in ("STALE", "REQUIRES_VERIFICATION"):
                        unresolved.append({
                            "record_type": "investigation",
                            "id": inv["id"],
                            "validity": inv.get("current_validity", "STALE"),
                            "reason": "Repository baseline is stale or untrusted; cannot incrementally revalidate",
                        })

            return IncrementalUnderstandResult(
                repo_id=canonical_id,
                status="stale_baseline",
                affected_dimensions=[],
                recomputed_dimensions=[],
                preserved_dimensions=sorted(SUPPORTED_DIMENSIONS),
                revalidated_records=[],
                unresolved_records=unresolved,
                updated_profile=None,
                updated_assessment=None,
                deterministic_processing_complete=False,
            )

        # ── Case C: No changes ──────────────────────────────────────────────
        if hasattr(dims_result, "all_affected_dimensions"):
            raw_dims = dims_result.all_affected_dimensions
        elif hasattr(dims_result, "all_dimensions"):
            raw_dims = dims_result.all_dimensions
        else:
            raw_dims = getattr(invalidation_result, "affected_dimensions", [])

        affected_dims = sorted(set(raw_dims))
        has_changes = getattr(change_result, "has_changes", False)
        if not has_changes and not affected_dims:
            return IncrementalUnderstandResult(
                repo_id=canonical_id,
                status="no_changes",
                affected_dimensions=[],
                recomputed_dimensions=[],
                preserved_dimensions=sorted(SUPPORTED_DIMENSIONS),
                revalidated_records=[],
                unresolved_records=[],
                updated_profile=None,
                updated_assessment=None,
                deterministic_processing_complete=True,
            )

        # ── Case D: Normal incremental re-understanding ─────────────────────
        # Distinguish committed vs uncommitted-only changes
        has_committed = getattr(change_result, "has_committed_changes", False)
        has_uncommitted = getattr(change_result, "has_uncommitted_changes", False)
        is_uncommitted_only = has_uncommitted and not has_committed

        recomputed_dimensions: list = []
        recomputed_evidence: dict = {}

        # Initialize modular assessment engine
        assessment_engine = RepositoryAssessmentEngine(str_path)

        for dim in affected_dims:
            if dim not in SUPPORTED_DIMENSIONS:
                continue

            if dim == "source_code":
                health, _ = assessment_engine.assess_code_health()
                recomputed_evidence["source_code"] = {
                    "is_clean": health.is_clean,
                    "scanned_files": health.scanned_file_count,
                    "syntax_errors": len(health.syntax_errors),
                    "import_errors": len(health.import_errors),
                }
                recomputed_dimensions.append(dim)

            elif dim == "dependencies":
                dep_status, _ = assessment_engine.assess_dependencies()
                recomputed_evidence["dependencies"] = {
                    "manifests": list(dep_status.get("manifests_found", [])),
                    "package_managers": list(dep_status.get("package_managers", [])),
                    "has_lockfile": dep_status.get("has_lockfile", False),
                    "dependency_count": dep_status.get("dependency_count", 0),
                }
                recomputed_dimensions.append(dim)

            elif dim in ("architecture", "repository_structure"):
                observed, documented, drift, _ = assessment_engine.assess_architecture()
                recomputed_evidence[dim] = {
                    "observed": observed,
                    "documented": documented,
                    "drift": drift,
                }
                recomputed_dimensions.append(dim)

            elif dim == "tests":
                test_status, _ = assessment_engine.assess_testing()
                recomputed_evidence["tests"] = {
                    "has_tests": test_status.get("has_tests", False),
                    "frameworks": list(test_status.get("test_frameworks", [])),
                    "test_files": test_status.get("test_file_count", 0),
                    "has_config": test_status.get("has_test_config", False),
                }
                recomputed_dimensions.append(dim)

            elif dim == "documentation":
                doc_status, _ = assessment_engine.assess_documentation()
                recomputed_evidence["documentation"] = {
                    "has_readme": doc_status.get("has_readme", False),
                    "size": doc_status.get("readme_size_bytes", 0),
                    "has_setup": doc_status.get("has_setup_instructions", False),
                }
                recomputed_dimensions.append(dim)

            elif dim == "ci_cd":
                has_ci = False
                ci_configs = []
                if str_path and os.path.exists(str_path):
                    p = Path(str_path)
                    wf_dir = p / ".github" / "workflows"
                    if wf_dir.is_dir():
                        ci_configs = [f.name for f in wf_dir.glob("*.yml")] + [f.name for f in wf_dir.glob("*.yaml")]
                        has_ci = len(ci_configs) > 0
                    for cfg in (".gitlab-ci.yml", ".travis.yml", "azure-pipelines.yml"):
                        if (p / cfg).exists():
                            ci_configs.append(cfg)
                            has_ci = True
                recomputed_evidence["ci_cd"] = {
                    "has_ci": has_ci,
                    "configs": ci_configs,
                }
                recomputed_dimensions.append(dim)

            elif dim == "deployment":
                has_docker = False
                deploy_files = []
                if str_path and os.path.exists(str_path):
                    p = Path(str_path)
                    for f in ("Dockerfile", "docker-compose.yml", "docker-compose.yaml", "Procfile"):
                        if (p / f).exists():
                            deploy_files.append(f)
                            has_docker = True
                recomputed_evidence["deployment"] = {
                    "has_docker": has_docker,
                    "deploy_files": deploy_files,
                }
                recomputed_dimensions.append(dim)

            elif dim == "configuration":
                config_files = []
                if str_path and os.path.exists(str_path):
                    p = Path(str_path)
                    for f in ("pyproject.toml", "setup.cfg", "pytest.ini", ".editorconfig", "tsconfig.json"):
                        if (p / f).exists():
                            config_files.append(f)
                recomputed_evidence["configuration"] = {
                    "config_files": config_files,
                }
                recomputed_dimensions.append(dim)

        recomputed_dimensions = sorted(set(recomputed_dimensions))
        preserved_dimensions = sorted([d for d in SUPPORTED_DIMENSIONS if d not in recomputed_dimensions])

        # ── Update profile and assessment if safe ───────────────────────────
        updated_profile = None
        updated_assessment = None

        if str_path and os.path.exists(str_path):
            try:
                discovery = RepoDiscovery(str_path)
                profile_obj = discovery.discover()
                updated_profile = profile_obj.to_dict()
                if store and not is_uncommitted_only:
                    store.save_repo_profile(profile_obj, repo_id=canonical_id)
            except Exception:
                pass

            try:
                assessment_obj = assessment_engine.build_assessment()
                updated_assessment = assessment_obj.to_dict()
            except Exception:
                pass

        # ── Evaluate memory records requiring verification ──────────────────
        revalidated_records = []
        unresolved_records = []

        if store:
            candidate_decisions = store.load_decisions_by_validity(canonical_id, "REQUIRES_VERIFICATION")
            candidate_investigations = store.load_investigations_by_validity(canonical_id, "REQUIRES_VERIFICATION")

            # Evaluate candidate decisions
            for dec in candidate_decisions:
                dec_id = int(dec["id"])
                confirmed, reason = _evaluate_decision(dec, recomputed_evidence, updated_profile)
                if confirmed:
                    revalidated_records.append({
                        "record_type": "decision",
                        "id": dec_id,
                        "previous_validity": "REQUIRES_VERIFICATION",
                        "new_validity": "VALID",
                        "reason": reason,
                    })
                    # Update SQLite ONLY for committed changes
                    if not is_uncommitted_only:
                        store.update_record_validity(
                            table="decisions",
                            record_id=dec_id,
                            current_validity="VALID",
                            invalidated_at=None,
                            invalidation_reason=None,
                        )
                else:
                    unresolved_records.append({
                        "record_type": "decision",
                        "id": dec_id,
                        "validity": "REQUIRES_VERIFICATION",
                        "reason": reason,
                    })

            # Evaluate candidate investigations
            # Deterministic syntax/AST checks cannot verify bug fix logic -> remain REQUIRES_VERIFICATION
            for inv in candidate_investigations:
                inv_id = int(inv["id"])
                unresolved_records.append({
                    "record_type": "investigation",
                    "id": inv_id,
                    "validity": "REQUIRES_VERIFICATION",
                    "reason": "Deterministic syntax/AST checks cannot verify investigation resolution without test execution; remains requiring verification",
                })

        return IncrementalUnderstandResult(
            repo_id=canonical_id,
            status="reunderstood",
            affected_dimensions=affected_dims,
            recomputed_dimensions=recomputed_dimensions,
            preserved_dimensions=preserved_dimensions,
            revalidated_records=revalidated_records,
            unresolved_records=unresolved_records,
            updated_profile=updated_profile,
            updated_assessment=updated_assessment,
            deterministic_processing_complete=True,
        )


# ── Convenience Function ───────────────────────────────────────────────────────


def understand_again(
    change_result: IncrementalChangeResult,
    dims_result: AffectedDimensionsResult,
    invalidation_result: MemoryInvalidationResult,
    repo_path: str | Path | None = None,
    memory: EngineeringMemoryStore | None = None,
) -> IncrementalUnderstandResult:
    """
    Convenience function to run Phase 4.4 Incremental Understand Again.
    """
    engine = IncrementalUnderstandEngine(memory=memory)
    return engine.understand(
        change_result=change_result,
        dims_result=dims_result,
        invalidation_result=invalidation_result,
        repo_path=repo_path,
        memory=memory,
    )
