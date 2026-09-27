"""
Project Stage & State Inference Component (Phase 3).

Deterministically synthesizes multiple independent engineering signals:
  1. Implementation presence & codebase
  2. Architecture (observed structure, drift)
  3. Testing infrastructure (test files, configurations, CI execution)
  4. Dependency management (manifests, lockfile pinning)
  5. Deployment & CI/CD (containerization, workflow pipelines)
  6. Git evolution (vitality, commit history, active branch)
  7. Documentation (README depth, setup, architecture, deployment guides)

Produces a ProjectStageInference with:
  - stage: IDEA, EARLY, MID, LATE, MATURE
  - confidence: LOW, MEDIUM, HIGH
  - primary_signals: evidence directly supporting the inferred stage
  - conflicting_signals: contradictory or mismatched evidence
  - constraints: missing dimensions and unverified engineering assumptions

Zero LLM calls. Zero heuristics based on a single metric or hardcoded threshold.
"""

from typing import Literal
from src.models.assessment import (
    ConfidenceType,
    EngineeringAssessment,
    ProjectStageInference,
    StageType,
)
from src.models.repo_profile import RepoProfile


class ProjectStageInferencer:
    """
    Deterministic inference engine that derives the repository's project stage
    and inference confidence from multi-dimensional engineering evidence.
    """

    def infer(
        self,
        assessment: EngineeringAssessment,
        profile: RepoProfile | None = None,
    ) -> ProjectStageInference:
        """
        Synthesizes an EngineeringAssessment (and optional RepoProfile)
        into a structured ProjectStageInference.
        """
        primary_signals: list[str] = []
        conflicting_signals: list[str] = []
        constraints: list[str] = []

        # ── 1. Extract Dimensional Facts ──────────────────────────────────────
        # A. Implementation volume
        scanned_files = assessment.health.scanned_file_count
        is_clean = assessment.health.is_clean
        syntax_errors = len(assessment.health.syntax_errors)
        import_errors = len(assessment.health.import_errors)

        # B. Architecture
        arch_obs = assessment.architecture_style_observed
        arch_doc = assessment.architecture_style_documented
        arch_drift = assessment.architecture_drift_detected

        # C. Dependencies
        dep_status = assessment.dependency_status or {}
        manifest_count = dep_status.get("manifest_count", 0)
        has_lockfile = dep_status.get("has_lockfile", False)
        manifests_found = dep_status.get("manifests_found", [])

        # D. Testing
        test_status = assessment.test_framework_status or {}
        has_tests = test_status.get("has_tests", False)
        test_file_count = test_status.get("test_file_count", 0)
        has_test_config = test_status.get("has_test_config", False)
        ci_test_detected = test_status.get("ci_test_detected", False)
        test_frameworks = test_status.get("test_frameworks", [])

        # E. Git Vitality
        git_status = assessment.git_vitality or {}
        is_git = git_status.get("is_git_repo", False)
        recent_commits = git_status.get("recent_commit_count", 0)
        has_history = git_status.get("has_history", False)

        # F. Deployment & CI/CD
        has_docker = (
            (profile.has_docker if profile else False)
            or any("docker" in f.observation.lower() for f in assessment.findings)
        )
        ci_cd_detected = (
            (len(profile.ci_cd) > 0 if profile else False)
            or ci_test_detected
            or any("ci" in f.category.lower() or "workflow" in f.observation.lower() for f in assessment.findings)
        )
        has_deployment_docs = any(
            (f.category in ("documentation", "deployment") and ("deploy" in f.observation.lower() or "docker" in f.observation.lower()))
            or f.category == "deployment"
            for f in assessment.findings
        )

        # G. Documentation
        has_readme = any(
            f.category == "documentation" and "README documentation detected" in f.observation
            for f in assessment.findings
        )
        minimal_readme = any(
            f.category == "documentation" and "minimal or placeholder" in f.observation
            for f in assessment.findings
        )
        no_readme = any(
            f.category == "documentation" and "No README file found" in f.observation
            for f in assessment.findings
        )

        # ── 2. Identify Constraints & Missing Dimensions ──────────────────────
        constraints.append(
            "Project release intent, operational roadmap, and target milestone are not explicitly declared by the user."
        )
        if not is_git:
            constraints.append("Repository is not tracked by Git; version control evolution cannot be verified.")
        if not has_tests:
            constraints.append("Repository contains no detectable automated test suite.")
        if not arch_obs:
            constraints.append("Architecture style could not be confidently inferred from repository structure.")
        if not (has_docker or ci_cd_detected or has_deployment_docs):
            constraints.append("No deployment configuration or CI/CD workflow detected.")

        # ── 3. Rule-Based Multi-Dimensional Stage Synthesis ───────────────────

        # CASE 1: IDEA
        # No source code implementation exists (documentation-only, specification, or empty).
        if scanned_files == 0:
            stage: StageType = "IDEA"
            primary_signals.append("No source code implementation files detected in repository.")
            if has_readme and not minimal_readme:
                primary_signals.append("Repository contains project documentation or specification without an implemented codebase.")
            elif minimal_readme or no_readme:
                primary_signals.append("Repository directory is unpopulated or contains minimal non-implementation files.")

            if manifest_count > 0:
                conflicting_signals.append(
                    f"Dependency manifest(s) present ({', '.join(manifests_found)}) despite 0 source code implementation files."
                )
            if is_git and recent_commits > 0:
                conflicting_signals.append(
                    f"Git history exists ({recent_commits} commit(s)) prior to source code implementation."
                )

        else:
            # CASE 2: Implementation files exist (scanned_files > 0)
            # Synthesis across 6 independent engineering dimensions:
            #   1. Architecture established
            #   2. Testing infrastructure established
            #   3. Dependency management pinned with lockfile
            #   4. Deployment / CI/CD configuration established
            #   5. Git evolution active / sustained
            #   6. Documentation established with setup/usage

            is_arch_established = arch_obs is not None
            is_testing_established = has_tests and (has_test_config or ci_test_detected or test_file_count >= 2)
            is_dep_pinned = has_lockfile and manifest_count > 0
            is_deploy_established = ci_cd_detected or has_docker or has_deployment_docs
            has_git_evolution = is_git and has_history and recent_commits >= 2
            is_doc_established = has_readme and not minimal_readme

            # Count of established engineering dimensions (0 to 6)
            mature_dimensions = sum([
                1 if is_arch_established else 0,
                1 if is_testing_established else 0,
                1 if is_dep_pinned else 0,
                1 if is_deploy_established else 0,
                1 if has_git_evolution else 0,
                1 if is_doc_established else 0,
            ])

            # Technical core practices count (architecture, testing, deploy, dependencies)
            tech_core_count = sum([
                1 if is_arch_established else 0,
                1 if is_testing_established else 0,
                1 if is_deploy_established else 0,
                1 if is_dep_pinned else 0,
            ])

            # MATURE Evaluation:
            # Evidence of an established engineering system across multiple independent dimensions.
            # Requires at least 4 established dimensions and at least 2 technical core practices.
            if mature_dimensions >= 4 and tech_core_count >= 2:
                stage = "MATURE"
                primary_signals.append(
                    "Multi-dimensional engineering maturity established across architecture, testing, dependency management, and evolution."
                )
                if is_arch_established:
                    primary_signals.append(f"Established architectural layout observed: {arch_obs}.")
                if is_testing_established:
                    primary_signals.append(
                        f"Established automated test suite present ({test_file_count} test file(s), configured)."
                    )
                if is_dep_pinned:
                    primary_signals.append("Deterministic dependency management with lockfile pinning verified.")
                if has_git_evolution:
                    primary_signals.append(f"Sustained Git commit evolution ({recent_commits}+ commits).")
                if is_deploy_established:
                    primary_signals.append("Deployment configuration and/or CI/CD automation detected.")

            # LATE Evaluation:
            # System approaches release readiness: at least 3 established dimensions,
            # with architecture or testing established alongside operational readiness (deployment or lockfile).
            elif mature_dimensions >= 3 and (is_arch_established or is_testing_established) and (
                is_deploy_established or is_dep_pinned
            ):
                stage = "LATE"
                primary_signals.append(
                    "System approaches release readiness with multiple coordinated engineering dimensions."
                )
                if is_arch_established:
                    primary_signals.append(f"Established architectural pattern observed: {arch_obs}.")
                if is_testing_established:
                    primary_signals.append(f"Automated test infrastructure present ({test_file_count} test files).")
                if is_dep_pinned:
                    primary_signals.append("Dependency pinning with lockfile present.")
                if is_deploy_established:
                    primary_signals.append("Deployment or containerization configuration present.")
                if has_git_evolution:
                    primary_signals.append(f"Active Git history detected ({recent_commits} commits).")

            # MID Evaluation:
            # Active development with multiple coordinated components and emerging practices.
            elif scanned_files >= 2 and (
                mature_dimensions >= 2
                or (is_arch_established or is_testing_established)
            ):
                stage = "MID"
                primary_signals.append(
                    "Substantial multi-component implementation actively in development."
                )
                if is_arch_established:
                    primary_signals.append(f"Architectural structure observed: {arch_obs}.")
                if has_tests:
                    primary_signals.append(f"Test suite present ({test_file_count} test file(s)).")
                if manifest_count > 0:
                    primary_signals.append(f"Declared dependencies present ({', '.join(manifests_found)}).")
                if has_git_evolution:
                    primary_signals.append(f"Ongoing Git commit evolution ({recent_commits} commits).")

            # EARLY Evaluation:
            # Initial development or weak engineering infrastructure across dimensions.
            else:
                stage = "EARLY"
                primary_signals.append(
                    f"Initial code implementation detected ({scanned_files} source code file(s))."
                )
                if manifest_count > 0:
                    primary_signals.append(f"Initial dependency manifest present ({', '.join(manifests_found)}).")
                if not has_tests:
                    primary_signals.append("Automated test suite not yet established.")
                if not arch_obs:
                    primary_signals.append("Architectural organization is nascent or unformed.")
                if is_git and recent_commits <= 3:
                    primary_signals.append(f"Early Git commit history ({recent_commits} commit(s)).")

        # ── 4. Cross-Dimensional Conflict Detection ───────────────────────────

        # Conflict: Large file count with weak engineering evidence (no tests or no architecture)
        if scanned_files > 15 and not has_tests:
            conflicting_signals.append(
                f"Extensive codebase ({scanned_files} files) present without any automated test infrastructure."
            )
        if scanned_files > 15 and not arch_obs:
            conflicting_signals.append(
                f"Substantial file count ({scanned_files} files) present without recognized architectural organization."
            )

        # Conflict: Deployment infrastructure but minimal/no Git history
        if (has_docker or ci_cd_detected) and (not is_git or recent_commits <= 2):
            conflicting_signals.append(
                "Deployment or CI/CD infrastructure configured despite minimal or absent Git version control history."
            )

        # Conflict: Many dependencies but minimal code
        if manifest_count >= 2 and scanned_files <= 2 and scanned_files > 0:
            conflicting_signals.append(
                f"Multiple dependency manifests ({manifest_count}) declared for minimal implementation code ({scanned_files} file(s))."
            )

        # Conflict: Substantial codebase outside Git
        if scanned_files > 10 and not is_git:
            conflicting_signals.append(
                f"Substantial codebase ({scanned_files} files) exists outside of Git version control."
            )

        # Conflict: High commit volume with tiny codebase (e.g. 50 commits, 1 file)
        if is_git and recent_commits > 15 and scanned_files <= 2 and scanned_files > 0:
            conflicting_signals.append(
                f"Sustained commit history ({recent_commits} commits) despite very limited codebase implementation ({scanned_files} file(s))."
            )

        # Conflict: Architecture drift
        if arch_drift and arch_obs and arch_doc:
            conflicting_signals.append(
                f"Documented architecture '{arch_doc}' differs from observed structure '{arch_obs}'."
            )

        # Conflict: Active code health violations in mature/late/mid codebase
        if not is_clean and stage in ("MID", "LATE", "MATURE"):
            detail_items = []
            if syntax_errors:
                detail_items.append(f"{syntax_errors} syntax error(s)")
            if import_errors:
                detail_items.append(f"{import_errors} import error(s)")
            detail_text = ", ".join(detail_items) if detail_items else "active violations"
            conflicting_signals.append(
                f"Active code health violations ({detail_text}) detected within an established {stage} codebase."
            )

        # Conflict: MID stage with poor Git history
        if stage in ("MID", "LATE") and is_git and recent_commits <= 1:
            conflicting_signals.append(
                f"Git history is limited ({recent_commits} commit(s)) despite substantial implementation structure."
            )

        # ── 5. Confidence Calculation ─────────────────────────────────────────
        # Confidence measures certainty in the inference, NOT project maturity.
        # LOW: >= 2 conflicts OR >= 3 missing dimension constraints.
        # MEDIUM: 1 conflict OR 1-2 missing dimension constraints.
        # HIGH: 0 conflicts, <= 1 missing dimension constraint, strong alignment.

        conflict_count = len(conflicting_signals)
        specific_constraints = [
            c for c in constraints
            if not c.startswith("Project release intent")
        ]
        missing_dim_count = len(specific_constraints)

        if conflict_count >= 2 or missing_dim_count >= 3:
            confidence: ConfidenceType = "LOW"
        elif conflict_count == 1 or missing_dim_count == 2:
            confidence = "MEDIUM"
        else:
            confidence = "HIGH"

        return ProjectStageInference(
            stage=stage,
            confidence=confidence,
            primary_signals=primary_signals,
            conflicting_signals=conflicting_signals,
            constraints=constraints,
        )
