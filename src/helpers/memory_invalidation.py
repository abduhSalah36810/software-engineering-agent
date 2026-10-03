"""
Phase 4.3.5 — Memory Invalidation.

Deterministic component that identifies previously stored engineering
knowledge that may no longer be valid after repository changes, and
marks it as REQUIRES_VERIFICATION or STALE while preserving all
historical records.

Answers:
    "What previous knowledge should no longer be blindly trusted?"

It does NOT answer:
    "What is wrong with the architecture?"

That belongs to later assessment/reasoning (Phase 4.4+).

Design principles:
  - Deterministic. Zero LLM. Zero embeddings. Zero external services.
  - Historical records are NEVER deleted.
  - An old decision does NOT become false merely because the repo changed.
  - Only its current_validity changes (VALID -> REQUIRES_VERIFICATION / STALE).
  - Uncommitted changes trigger session-scoped verification; they are NOT
    written as permanent validity-state updates to SQLite.
  - Unknown/unmapped dimensions never produce fabricated invalidation.

Validity states:
  VALID                 - knowledge is current, not affected by recent changes
  REQUIRES_VERIFICATION - directly affected dimension; should be re-checked
  STALE                 - baseline is unreachable; broad re-understanding needed
"""

from __future__ import annotations

from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from typing import Literal
import json

from src.helpers.affected_dimensions import AffectedDimension, AffectedDimensionsResult
from src.memory.sqlite_store import EngineeringMemoryStore

# ── Validity vocabulary ────────────────────────────────────────────────────

ValidityState = Literal["VALID", "REQUIRES_VERIFICATION", "STALE"]

# ── Dimension -> knowledge-category mapping ────────────────────────────────
#
# Only map what we can assert deterministically.
# Each key is a canonical dimension from Phase 4.3.
# Each value is a human-readable description of what category of stored
# knowledge may be affected.
#
# IMPORTANT: This table does NOT cascade (e.g., dependencies -> architecture).
# Cascading invalidation requires direct deterministic evidence.

DIMENSION_TO_KNOWLEDGE_CATEGORY: dict[str, str] = {
    "source_code":            "source/code-related understanding",
    "tests":                  "testing-related understanding",
    "dependencies":           "dependency/technology-related understanding",
    "deployment":             "deployment/runtime-related understanding",
    "ci_cd":                  "CI/CD-related understanding",
    "documentation":          "documentation-derived observations",
    "configuration":          "configuration/runtime-related understanding",
    "repository_structure":   "repository/architecture-related understanding",
    "architecture":           "architecture-related understanding",
}

# ── Per-dimension: which SQLite record types should be flagged ─────────────
#
# Each dimension targets a subset of stored record types.
# "decisions" and "investigations" are the knowledge-bearing tables.
# Mapping is conservative and direct.

_DIM_TARGETS: dict[str, set] = {
    "source_code":          {"decisions", "investigations"},
    "tests":                {"decisions", "investigations"},
    "dependencies":         {"decisions", "investigations"},
    "deployment":           {"decisions", "investigations"},
    "ci_cd":                {"decisions", "investigations"},
    "documentation":        {"decisions"},
    "configuration":        {"decisions", "investigations"},
    "repository_structure": {"decisions", "investigations"},
    "architecture":         {"decisions", "investigations"},
}

# ── Dataclasses ──────────────────────────────────────────────────────────────


@dataclass
class InvalidatedItem:
    """
    A single item of stored engineering knowledge whose current validity
    has been updated.  The historical record is preserved unchanged.
    """
    record_type: str                # "decision" | "investigation"
    record_id: int
    repo_id: str
    dimension: str                  # which dimension caused this invalidation
    evidence_files: list            # evidence that triggered invalidation
    reasons: list                   # why this dimension was flagged
    previous_validity: str
    new_validity: str
    knowledge_category: str         # human-readable category description
    is_from_uncommitted: bool = False  # True -> working-tree only, not permanent history

    def to_dict(self) -> dict:
        return asdict(self)

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), indent=2)

    @classmethod
    def from_dict(cls, data: dict) -> "InvalidatedItem":
        return cls(
            record_type=str(data["record_type"]),
            record_id=int(data["record_id"]),
            repo_id=str(data["repo_id"]),
            dimension=str(data["dimension"]),
            evidence_files=list(data.get("evidence_files", [])),
            reasons=list(data.get("reasons", [])),
            previous_validity=str(data["previous_validity"]),
            new_validity=str(data["new_validity"]),
            knowledge_category=str(data["knowledge_category"]),
            is_from_uncommitted=bool(data.get("is_from_uncommitted", False)),
        )


@dataclass
class MemoryInvalidationResult:
    """
    Structured outcome of Phase 4.3.5 memory invalidation.

    Contains enough information to explain:
      - Which repo was affected
      - Which dimensions were involved
      - Which stored records were flagged
      - Whether broad re-verification is needed
      - What evidence triggered each invalidation
    """
    repo_id: str
    status: str                         # "initial_baseline" | "invalidated" | "no_changes" | "stale_baseline"
    affected_dimensions: list           # sorted list of dimension names that triggered invalidation
    invalidated_items: list             # list[InvalidatedItem]
    verification_required: bool          # at least one item requires verification
    broad_reverification_required: bool  # stale baseline -> broader re-understanding needed
    evidence: dict                       # dimension -> evidence_files
    reasons: dict                        # dimension -> reasons
    invalidated_count: int
    is_initial_baseline: bool

    def to_dict(self) -> dict:
        d = asdict(self)
        return d

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), indent=2)

    @classmethod
    def from_dict(cls, data: dict) -> "MemoryInvalidationResult":
        items = [
            i if isinstance(i, InvalidatedItem) else InvalidatedItem.from_dict(i)
            for i in data.get("invalidated_items", [])
        ]
        return cls(
            repo_id=str(data["repo_id"]),
            status=str(data["status"]),
            affected_dimensions=list(data.get("affected_dimensions", [])),
            invalidated_items=items,
            verification_required=bool(data.get("verification_required", False)),
            broad_reverification_required=bool(data.get("broad_reverification_required", False)),
            evidence=dict(data.get("evidence", {})),
            reasons=dict(data.get("reasons", {})),
            invalidated_count=int(data.get("invalidated_count", 0)),
            is_initial_baseline=bool(data.get("is_initial_baseline", False)),
        )


# ── Invalidation Engine ───────────────────────────────────────────────────────


class MemoryInvalidationEngine:
    """
    Deterministic memory invalidation engine for Phase 4.3.5.

    Takes:
      - change_result: IncrementalChangeResult (Phase 4.1/4.2 output)
      - dimensions_result: AffectedDimensionsResult (Phase 4.3 output)
      - memory: EngineeringMemoryStore (SQLite store)

    Produces:
      - MemoryInvalidationResult

    Rules:
      1. initial_baseline -> no previous knowledge to invalidate -> return immediately.
      2. is_baseline_stale or requires_reverification -> broad_reverification_required = True,
         mark ALL known decisions/investigations as STALE.
      3. Otherwise -> only mark records matching touched dimensions as REQUIRES_VERIFICATION.
      4. Unknown dimensions -> NO fabricated invalidation.
      5. Uncommitted changes -> can trigger session-scoped REQUIRES_VERIFICATION but are
         NOT written to the permanent SQLite validity state.
      6. Historical records are never deleted.
    """

    def __init__(self, memory: EngineeringMemoryStore) -> None:
        self.memory = memory

    # ── Public API ─────────────────────────────────────────────────────────

    def invalidate(
        self,
        change_result,
        dimensions_result: AffectedDimensionsResult,
    ) -> MemoryInvalidationResult:
        """
        Main entry point.  Runs the full invalidation pipeline.

        Args:
            change_result: IncrementalChangeResult from Phase 4.1/4.2.
            dimensions_result: AffectedDimensionsResult from Phase 4.3.

        Returns:
            MemoryInvalidationResult describing what was invalidated and why.
        """
        repo_id: str = str(getattr(change_result, "repo_id", "unknown"))
        is_initial_baseline: bool = bool(getattr(change_result, "is_initial_baseline", False))
        is_baseline_stale: bool = bool(getattr(change_result, "is_baseline_stale", False))
        requires_reverification: bool = bool(getattr(change_result, "requires_reverification", False))

        # ── Case A: Initial baseline — no previous knowledge exists ──────
        if is_initial_baseline:
            return MemoryInvalidationResult(
                repo_id=repo_id,
                status="initial_baseline",
                affected_dimensions=[],
                invalidated_items=[],
                verification_required=False,
                broad_reverification_required=False,
                evidence={},
                reasons={},
                invalidated_count=0,
                is_initial_baseline=True,
            )

        # ── Case B: Stale baseline — broad re-understanding required ─────
        if is_baseline_stale or requires_reverification:
            return self._handle_stale_baseline(repo_id)

        # ── Case C: Normal incremental invalidation ───────────────────────
        return self._handle_incremental(repo_id, dimensions_result)

    # ── Private helpers ────────────────────────────────────────────────────

    def _now(self) -> str:
        return datetime.now(timezone.utc).isoformat()

    def _handle_stale_baseline(self, repo_id: str) -> MemoryInvalidationResult:
        """
        When the git anchor is stale, mark ALL existing decisions and
        investigations as STALE and signal broad re-verification.
        Historical records are preserved; only current_validity changes.
        """
        now = self._now()
        invalidated_items: list = []

        # Mark all decisions
        decisions = self.memory.load_decisions(repo_id)
        for dec in decisions:
            prev_validity = dec.get("current_validity", "VALID") or "VALID"
            new_validity = "STALE"
            self.memory.update_record_validity(
                table="decisions",
                record_id=int(dec["id"]),
                current_validity=new_validity,
                invalidated_at=now,
                invalidation_reason="Stale git baseline: broader re-understanding required",
            )
            invalidated_items.append(InvalidatedItem(
                record_type="decision",
                record_id=int(dec["id"]),
                repo_id=repo_id,
                dimension="__stale_baseline__",
                evidence_files=[],
                reasons=["Stale git baseline: git anchor no longer reachable or missing"],
                previous_validity=prev_validity,
                new_validity=new_validity,
                knowledge_category="all engineering knowledge",
                is_from_uncommitted=False,
            ))

        # Mark all investigations
        investigations = self.memory.load_investigations(repo_id)
        for inv in investigations:
            prev_validity = inv.get("current_validity", "VALID") or "VALID"
            new_validity = "STALE"
            self.memory.update_record_validity(
                table="investigations",
                record_id=int(inv["id"]),
                current_validity=new_validity,
                invalidated_at=now,
                invalidation_reason="Stale git baseline: broader re-understanding required",
            )
            invalidated_items.append(InvalidatedItem(
                record_type="investigation",
                record_id=int(inv["id"]),
                repo_id=repo_id,
                dimension="__stale_baseline__",
                evidence_files=[],
                reasons=["Stale git baseline: git anchor no longer reachable or missing"],
                previous_validity=prev_validity,
                new_validity=new_validity,
                knowledge_category="all engineering knowledge",
                is_from_uncommitted=False,
            ))

        return MemoryInvalidationResult(
            repo_id=repo_id,
            status="stale_baseline",
            affected_dimensions=[],
            invalidated_items=invalidated_items,
            verification_required=True,
            broad_reverification_required=True,
            evidence={},
            reasons={"__stale_baseline__": [
                "Stale git baseline: git anchor no longer reachable or missing",
            ]},
            invalidated_count=len(invalidated_items),
            is_initial_baseline=False,
        )

    def _handle_incremental(
        self,
        repo_id: str,
        dimensions_result: AffectedDimensionsResult,
    ) -> MemoryInvalidationResult:
        """
        Normal incremental invalidation.

        For each committed dimension that has a direct mapping in
        DIMENSION_TO_KNOWLEDGE_CATEGORY, flag decisions and investigations
        as REQUIRES_VERIFICATION.

        Uncommitted-only dimensions produce session-scoped items (not written
        to the permanent SQLite validity state).
        """
        now = self._now()

        # Build dimension-evidence/reason maps from committed changes
        committed_dim_map: dict = {
            d.dimension: d for d in dimensions_result.committed
        }
        uncommitted_dim_map: dict = {
            d.dimension: d for d in dimensions_result.uncommitted
        }

        # Only include dimensions that appear in our mapping (unknown -> no fabrication)
        valid_committed_dims = {
            dim: committed_dim_map[dim]
            for dim in committed_dim_map
            if dim in DIMENSION_TO_KNOWLEDGE_CATEGORY
        }
        valid_uncommitted_dims = {
            dim: uncommitted_dim_map[dim]
            for dim in uncommitted_dim_map
            if dim in DIMENSION_TO_KNOWLEDGE_CATEGORY
            and dim not in valid_committed_dims  # avoid double-counting
        }

        all_valid_dims = dict(valid_committed_dims)
        all_valid_dims.update(valid_uncommitted_dims)

        affected_dimensions = sorted(all_valid_dims.keys())

        # Early exit: no known affected dimensions
        if not affected_dimensions:
            return MemoryInvalidationResult(
                repo_id=repo_id,
                status="no_changes",
                affected_dimensions=[],
                invalidated_items=[],
                verification_required=False,
                broad_reverification_required=False,
                evidence={},
                reasons={},
                invalidated_count=0,
                is_initial_baseline=False,
            )

        # Build evidence/reasons maps for result
        evidence: dict = {}
        reasons: dict = {}
        for dim, ad in all_valid_dims.items():
            evidence[dim] = sorted(ad.evidence_files)
            reasons[dim] = sorted(ad.reasons)

        # Collect existing records
        decisions = self.memory.load_decisions(repo_id)
        investigations = self.memory.load_investigations(repo_id)

        invalidated_items: list = []

        # Track which record IDs have already been written to SQLite (avoid duplicate writes)
        marked_decision_ids: set = set()
        marked_investigation_ids: set = set()

        for dim in affected_dimensions:
            ad = all_valid_dims[dim]
            is_uncommitted = (dim in valid_uncommitted_dims and dim not in valid_committed_dims)
            category = DIMENSION_TO_KNOWLEDGE_CATEGORY[dim]
            targets = _DIM_TARGETS.get(dim, set())
            new_validity = "REQUIRES_VERIFICATION"
            dim_reasons = sorted(ad.reasons)
            dim_evidence = sorted(ad.evidence_files)
            invalidation_reason = (
                f"Dimension '{dim}' affected — {category} may require verification. "
                f"Evidence: {', '.join(dim_evidence[:3]) or 'none'}"
            )

            if "decisions" in targets:
                for dec in decisions:
                    dec_id = int(dec["id"])
                    prev_validity = dec.get("current_validity", "VALID") or "VALID"
                    # Only write to SQLite for committed changes (permanent)
                    if not is_uncommitted and dec_id not in marked_decision_ids:
                        self.memory.update_record_validity(
                            table="decisions",
                            record_id=dec_id,
                            current_validity=new_validity,
                            invalidated_at=now,
                            invalidation_reason=invalidation_reason,
                        )
                        marked_decision_ids.add(dec_id)
                    invalidated_items.append(InvalidatedItem(
                        record_type="decision",
                        record_id=dec_id,
                        repo_id=repo_id,
                        dimension=dim,
                        evidence_files=dim_evidence,
                        reasons=dim_reasons,
                        previous_validity=prev_validity,
                        new_validity=new_validity,
                        knowledge_category=category,
                        is_from_uncommitted=is_uncommitted,
                    ))

            if "investigations" in targets:
                for inv in investigations:
                    inv_id = int(inv["id"])
                    prev_validity = inv.get("current_validity", "VALID") or "VALID"
                    if not is_uncommitted and inv_id not in marked_investigation_ids:
                        self.memory.update_record_validity(
                            table="investigations",
                            record_id=inv_id,
                            current_validity=new_validity,
                            invalidated_at=now,
                            invalidation_reason=invalidation_reason,
                        )
                        marked_investigation_ids.add(inv_id)
                    invalidated_items.append(InvalidatedItem(
                        record_type="investigation",
                        record_id=inv_id,
                        repo_id=repo_id,
                        dimension=dim,
                        evidence_files=dim_evidence,
                        reasons=dim_reasons,
                        previous_validity=prev_validity,
                        new_validity=new_validity,
                        knowledge_category=category,
                        is_from_uncommitted=is_uncommitted,
                    ))

        # Unique record count: each (type, id) pair counted once
        unique_record_ids = set(
            (item.record_type, item.record_id) for item in invalidated_items
        )

        return MemoryInvalidationResult(
            repo_id=repo_id,
            status="invalidated" if invalidated_items else "no_changes",
            affected_dimensions=affected_dimensions,
            invalidated_items=invalidated_items,
            verification_required=len(invalidated_items) > 0,
            broad_reverification_required=False,
            evidence=evidence,
            reasons=reasons,
            invalidated_count=len(unique_record_ids),
            is_initial_baseline=False,
        )


# ── Convenience function ───────────────────────────────────────────────────────


def invalidate_memory(
    change_result,
    dimensions_result: AffectedDimensionsResult,
    memory: EngineeringMemoryStore,
) -> MemoryInvalidationResult:
    """
    Convenience function.  Runs Phase 4.3.5 memory invalidation.

    Args:
        change_result: IncrementalChangeResult (Phase 4.1/4.2 output).
        dimensions_result: AffectedDimensionsResult (Phase 4.3 output).
        memory: EngineeringMemoryStore (SQLite store).

    Returns:
        MemoryInvalidationResult.
    """
    engine = MemoryInvalidationEngine(memory=memory)
    return engine.invalidate(change_result, dimensions_result)
