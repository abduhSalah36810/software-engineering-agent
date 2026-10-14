import { useState } from 'react'
import { GitCompare, ArrowRight, ChevronDown, ChevronUp } from 'lucide-react'
import type { IncrementalStatusSummary } from '../types/api'

interface IncrementalIntelligenceCardProps {
  incremental: IncrementalStatusSummary
}

export function IncrementalIntelligenceCard({
  incremental,
}: IncrementalIntelligenceCardProps) {
  const [showDetails, setShowDetails] = useState(false)

  const getStatusBadge = (status: string) => {
    switch (status) {
      case 'unchanged':
        return <span className="badge badge-emerald">Evolution Unchanged</span>
      case 'dirty':
        return <span className="badge badge-amber">Working-Tree Dirty</span>
      case 'changed':
        return <span className="badge badge-blue">Committed Evolution Detected</span>
      case 'stale_baseline':
        return <span className="badge badge-danger">Stale Baseline Anchor</span>
      case 'initial_baseline':
        return <span className="badge badge-purple">Initial Baseline</span>
      default:
        return <span className="badge badge-neutral">{status}</span>
    }
  }

  return (
    <section className="card" aria-label="Incremental Change Intelligence">
      <div className="card-header">
        <div className="card-title-group">
          <GitCompare size={18} className="text-purple" />
          <h3 className="card-title">Incremental Intelligence & Dimensions</h3>
        </div>
        {getStatusBadge(incremental.status)}
      </div>

      <div className="baseline-comparison-box">
        <div className="comparison-item">
          <span className="comparison-label">Baseline Anchor</span>
          <code className="monospace-chip">
            {incremental.previous_commit
              ? incremental.previous_commit.slice(0, 10)
              : (incremental.is_initial_baseline ? 'None (Initial Baseline)' : 'Unanchored')}
          </code>
        </div>
        <ArrowRight size={16} className="text-muted" />
        <div className="comparison-item">
          <span className="comparison-label">Current HEAD</span>
          <code className="monospace-chip font-bold">
            {incremental.current_commit ? incremental.current_commit.slice(0, 10) : 'None'}
          </code>
        </div>
      </div>

      <div className="dimensions-container">
        <div className="dimension-block">
          <h4 className="dimension-heading">
            <span>Touched Committed Dimensions ({incremental.committed_dimensions.length})</span>
          </h4>
          {incremental.committed_dimensions.length > 0 ? (
            <div className="tag-list">
              {incremental.committed_dimensions.map((dim) => (
                <span key={`committed-${dim}`} className="badge badge-purple font-medium">
                  {dim}
                </span>
              ))}
            </div>
          ) : (
            <span className="text-muted text-sm">No committed dimensions touched</span>
          )}
        </div>

        <div className="dimension-block">
          <h4 className="dimension-heading">
            <span>Touched Working-Tree Dimensions ({incremental.uncommitted_dimensions.length})</span>
          </h4>
          {incremental.uncommitted_dimensions.length > 0 ? (
            <div className="tag-list">
              {incremental.uncommitted_dimensions.map((dim) => (
                <span key={`uncommitted-${dim}`} className="badge badge-amber font-medium">
                  {dim}
                </span>
              ))}
            </div>
          ) : (
            <span className="text-muted text-sm">No uncommitted dimensions touched</span>
          )}
        </div>
      </div>

      {incremental.dimensions_detail.length > 0 && (
        <div className="details-accordion">
          <button
            type="button"
            onClick={() => setShowDetails(!showDetails)}
            className="accordion-toggle-btn"
          >
            <span>Dimension Evidence Breakdown ({incremental.dimensions_detail.length})</span>
            {showDetails ? <ChevronUp size={15} /> : <ChevronDown size={15} />}
          </button>

          {showDetails && (
            <div className="accordion-content">
              {incremental.dimensions_detail.map((d, idx) => (
                <div key={`detail-${idx}`} className="dim-detail-card">
                  <div className="dim-detail-header">
                    <span className="badge badge-mono">{d.dimension}</span>
                    <span className="text-xs text-muted">{d.evidence_files.length} file(s)</span>
                  </div>
                  <ul className="reason-list">
                    {d.reasons.map((r, rIdx) => (
                      <li key={`r-${rIdx}`} className="reason-item">{r}</li>
                    ))}
                  </ul>
                  <div className="evidence-files-pills">
                    {d.evidence_files.map((f, fIdx) => (
                      <code key={`f-${fIdx}`} className="mini-file-chip">{f}</code>
                    ))}
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>
      )}
    </section>
  )
}
