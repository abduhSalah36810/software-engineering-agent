import { useState } from 'react'
import { Activity, ShieldCheck, FileCheck2, Zap, ChevronDown, ChevronUp, AlertOctagon } from 'lucide-react'
import type { CodeHealthSummary, ProjectStageSummary, StageType, ConfidenceType } from '../types/api'

interface AssessmentCardProps {
  stage: ProjectStageSummary | null
  health: CodeHealthSummary | null
  status: string
  message: string | null
  onRunAssessment: () => void
  loadingAssessment: boolean
}

function getUnavailableMessage(status: string, message: string | null) {
  if (message) return message
  if (status === 'computed') return 'Assessment data is incomplete and cannot be displayed.'
  if (status === 'unavailable') return 'Assessment data is currently unavailable.'
  return 'Code health and project stage were not requested on this view.'
}

export function AssessmentCard({
  stage,
  health,
  status,
  message,
  onRunAssessment,
  loadingAssessment,
}: AssessmentCardProps) {
  const [showAllErrors, setShowAllErrors] = useState(false)
  const hasCompleteAssessment = status === 'computed' && stage !== null && health !== null

  const getStageBadgeClass = (s?: StageType) => {
    switch (s) {
      case 'MATURE':
        return 'badge-emerald'
      case 'LATE':
        return 'badge-blue'
      case 'MID':
        return 'badge-purple'
      case 'EARLY':
        return 'badge-amber'
      case 'IDEA':
        return 'badge-neutral'
      default:
        return 'badge-neutral'
    }
  }

  const getConfidenceBadgeClass = (c?: ConfidenceType) => {
    switch (c) {
      case 'HIGH':
        return 'badge-emerald'
      case 'MEDIUM':
        return 'badge-amber'
      case 'LOW':
        return 'badge-danger'
      default:
        return 'badge-neutral'
    }
  }

  return (
    <section className="card" aria-label="Engineering Assessment & Code Health">
      <div className="card-header">
        <div className="card-title-group">
          <Activity size={18} className="text-emerald" />
          <h3 className="card-title">Project Stage & Code Health Assessment</h3>
        </div>
        <div className="card-header-actions">
          {loadingAssessment ? (
            <span className="badge badge-neutral" role="status">Assessment Running</span>
          ) : hasCompleteAssessment ? (
            <span className="badge badge-emerald">Freshly Computed</span>
          ) : status === 'unavailable' ? (
            <span className="badge badge-amber">Unavailable</span>
          ) : status === 'computed' ? (
            <span className="badge badge-amber">Incomplete</span>
          ) : (
            <span className="badge badge-neutral">Not Assessed</span>
          )}
        </div>
      </div>

      {loadingAssessment ? (
        <div className="unassessed-box" role="status">
          <p className="unassessed-desc">The code health and project stage assessment is running.</p>
        </div>
      ) : hasCompleteAssessment && stage && health ? (
        <div className="assessment-content">
          {/* Stage & Confidence Summary */}
          <div className="stage-banner">
            <div className="stage-display">
              <span className="stage-caption">Inferred Project Stage</span>
              <span className={`stage-pill ${getStageBadgeClass(stage.stage)}`}>
                {stage.stage}
              </span>
            </div>
            <div className="confidence-display">
              <span className="stage-caption">Inference Certainty</span>
              <span className={`confidence-pill ${getConfidenceBadgeClass(stage.confidence)}`}>
                {stage.confidence} Confidence
              </span>
            </div>
          </div>

          {/* Primary Signals */}
          {stage.primary_signals.length > 0 && (
            <div className="signals-section">
              <h4 className="signals-heading text-emerald">
                <FileCheck2 size={14} /> Supporting Evidence Signals
              </h4>
              <ul className="signals-list">
                {stage.primary_signals.map((sig, idx) => (
                  <li key={`sig-${idx}`} className="signal-item">{sig}</li>
                ))}
              </ul>
            </div>
          )}

          {/* Conflicting Signals */}
          {stage.conflicting_signals.length > 0 && (
            <div className="signals-section">
              <h4 className="signals-heading text-amber">
                <AlertOctagon size={14} /> Contradictions & Conflicting Evidence
              </h4>
              <ul className="signals-list">
                {stage.conflicting_signals.map((conf, idx) => (
                  <li key={`conf-${idx}`} className="signal-item conflict-item">{conf}</li>
                ))}
              </ul>
            </div>
          )}

          {/* Code Health Diagnostics */}
          <div className="health-diagnostics-box">
            <div className="health-box-header">
              <div className="health-title-group">
                <ShieldCheck size={16} className={health.is_clean ? 'text-emerald' : 'text-amber'} />
                <span className="font-semibold">AST Syntax & Diagnostic Health</span>
              </div>
              <span className={`badge ${health.is_clean ? 'badge-emerald' : 'badge-amber'}`}>
                {health.is_clean ? 'No Findings' : 'Findings Detected'}
              </span>
            </div>

            <div className="health-counters-grid">
              <div className="counter-item">
                <span className="counter-num">{health.scanned_file_count}</span>
                <span className="counter-label">Source Files Scanned</span>
              </div>
              <div className="counter-item">
                <span className={`counter-num ${health.syntax_error_count > 0 ? 'text-danger' : ''}`}>
                  {health.syntax_error_count}
                </span>
                <span className="counter-label">Syntax Errors</span>
              </div>
              <div className="counter-item">
                <span className={`counter-num ${health.import_error_count > 0 ? 'text-amber' : ''}`}>
                  {health.import_error_count}
                </span>
                <span className="counter-label">Import Violations</span>
              </div>
              <div className="counter-item">
                <span className={`counter-num ${health.unparseable_files_count > 0 ? 'text-danger' : ''}`}>
                  {health.unparseable_files_count}
                </span>
                <span className="counter-label">Unparseable Files</span>
              </div>
            </div>

            {(health.syntax_errors.length > 0 || health.import_errors.length > 0) && (
              <div className="errors-list-container">
                <div className="errors-header">
                  <span className="text-xs font-semibold text-muted">
                    Detailed Health Findings
                  </span>
                  {(health.syntax_errors.length + health.import_errors.length > 4) && (
                    <button
                      type="button"
                      onClick={() => setShowAllErrors(!showAllErrors)}
                      className="btn-link"
                    >
                      {showAllErrors ? <>Less <ChevronUp size={12} /></> : <>All <ChevronDown size={12} /></>}
                    </button>
                  )}
                </div>

                <div className="errors-scroll-list">
                  {(showAllErrors
                    ? [...health.syntax_errors, ...health.import_errors]
                    : [...health.syntax_errors, ...health.import_errors].slice(0, 4)
                  ).map((err, idx) => (
                    <div key={`err-${idx}`} className="health-error-item">
                      <span className="error-cat-badge">{err.category}</span>
                      <span className="error-obs">{err.observation}</span>
                      <code className="error-evidence">{err.evidence}</code>
                    </div>
                  ))}
                </div>
              </div>
            )}
          </div>
        </div>
      ) : (
        <div className="unassessed-box">
          <p className="unassessed-desc">
            {getUnavailableMessage(status, message)}
          </p>
          <button
            type="button"
            onClick={onRunAssessment}
            disabled={loadingAssessment}
            className="btn btn-primary btn-run-assessment"
          >
            {loadingAssessment ? (
              <>Running Full AST Assessment...</>
            ) : (
              <>
                <Zap size={15} />
                <span>Run Full Code Assessment</span>
              </>
            )}
          </button>
        </div>
      )}
    </section>
  )
}
