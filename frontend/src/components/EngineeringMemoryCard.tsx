import { Database, CheckCircle, AlertTriangle, XCircle, BookOpen, Bug } from 'lucide-react'
import type { MemoryValiditySummary } from '../types/api'

interface EngineeringMemoryCardProps {
  memory: MemoryValiditySummary
}

export function EngineeringMemoryCard({ memory }: EngineeringMemoryCardProps) {
  const validDecisions = memory.decisions_by_validity['VALID'] ?? 0
  const validInvestigations = memory.investigations_by_validity['VALID'] ?? 0
  const validTotal = validDecisions + validInvestigations

  const invalidDecisions = memory.decisions_by_validity['INVALID'] ?? 0
  const invalidInvestigations = memory.investigations_by_validity['INVALID'] ?? 0
  const invalidTotal = invalidDecisions + invalidInvestigations

  return (
    <section className="card" aria-label="Engineering Memory & Decisions">
      <div className="card-header">
        <div className="card-title-group">
          <Database size={18} className="text-cyan" />
          <h3 className="card-title">Maintained Engineering Memory</h3>
        </div>
        <span className="badge badge-cyan">
          {memory.has_engineering_history ? 'Persisted History' : 'Zero Memory'}
        </span>
      </div>

      <div className="memory-totals-grid">
        <div className="memory-stat-box">
          <div className="stat-icon-title">
            <BookOpen size={16} className="text-blue" />
            <span className="stat-label">Architectural Decisions</span>
          </div>
          <span className="stat-value">{memory.decisions_count}</span>
        </div>

        <div className="memory-stat-box">
          <div className="stat-icon-title">
            <Bug size={16} className="text-purple" />
            <span className="stat-label">Bug Investigations</span>
          </div>
          <span className="stat-value">{memory.investigations_count}</span>
        </div>
      </div>

      <div className="validity-breakdown-box">
        <h4 className="section-subtitle">Record Validity Breakdown</h4>
        <div className="validity-chips-row">
          <div className="validity-chip chip-valid" title="Grounded by unchanged repository state">
            <CheckCircle size={14} className="text-emerald" />
            <span className="validity-name">Valid</span>
            <span className="validity-count">{validTotal}</span>
          </div>
          <div className="validity-chip chip-reverify" title="Touches files or dimensions modified in this evolution">
            <AlertTriangle size={14} className="text-amber" />
            <span className="validity-name">Needs Verification</span>
            <span className="validity-count">{memory.requires_verification_count}</span>
          </div>
          <div className="validity-chip chip-invalid" title="Superseded, invalidated, or pruned">
            <XCircle size={14} className="text-danger" />
            <span className="validity-name">Invalid</span>
            <span className="validity-count">{invalidTotal}</span>
          </div>
        </div>
      </div>

      {memory.stale_baseline_warning && (
        <div className="memory-note-banner">
          <AlertTriangle size={14} className="text-amber" />
          <span className="text-xs">
            Baseline anchor commit is unreachable. Memory validity status reflects last recorded baseline.
          </span>
        </div>
      )}
    </section>
  )
}
