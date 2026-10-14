import { useCallback, useEffect, useRef, useState } from 'react'
import { AlertCircle, ArrowLeft, BookOpen, Clock3, FileSearch, RefreshCw } from 'lucide-react'
import { ApiError, fetchInvestigations } from '../api/client'
import type { InvestigationRecord, RepoIdentitySummary } from '../types/api'

interface InvestigationWorkspaceProps {
  repository: RepoIdentitySummary | null
}

function describeError(error: Error) {
  return error instanceof ApiError ? error.detail : error.message
}

function formatTimestamp(timestamp: string | null) {
  if (!timestamp) return 'Timestamp not recorded'
  const date = new Date(timestamp)
  return Number.isNaN(date.getTime()) ? timestamp : date.toLocaleString()
}

function displayValidity(value: string | null) {
  if (!value) return 'Validity not recorded'
  return value.replaceAll('_', ' ').toLowerCase().replace(/\b\w/g, (letter) => letter.toUpperCase())
}

function InvestigationDetail({
  investigation,
  onBack,
}: {
  investigation: InvestigationRecord
  onBack: () => void
}) {
  const result = investigation.result ?? {}
  const files = Array.isArray(result.files_to_modify)
    ? result.files_to_modify.filter((file): file is string => typeof file === 'string')
    : []
  const gitHead = typeof result.git_head === 'string' ? result.git_head : null
  const otherResult = Object.fromEntries(
    Object.entries(result).filter(([key]) => key !== 'files_to_modify' && key !== 'git_head'),
  )

  return (
    <section className="investigation-detail card" aria-labelledby="investigation-detail-title">
      <button type="button" className="investigation-back-button" onClick={onBack}>
        <ArrowLeft size={15} /> Back to investigations
      </button>
      <div className="investigation-detail-heading">
        <div>
          <span className="section-kicker">Investigation #{investigation.id}</span>
          <h2 id="investigation-detail-title">{investigation.problem}</h2>
        </div>
        <span className={`investigation-validity validity-${(investigation.current_validity ?? 'unknown').toLowerCase()}`}>
          {displayValidity(investigation.current_validity)}
        </span>
      </div>
      <div className="investigation-timestamp"><Clock3 size={14} /> Created {formatTimestamp(investigation.created_at)}</div>

      <div className="investigation-findings-grid">
        <section className="investigation-recorded-section">
          <h3>Recorded root cause</h3>
          {investigation.root_cause
            ? <p className="investigation-long-text">{investigation.root_cause}</p>
            : <p className="investigation-missing">No root cause was recorded.</p>}
        </section>
        <section className="investigation-recorded-section">
          <h3>Recorded plan</h3>
          {investigation.plan
            ? <p className="investigation-long-text">{investigation.plan}</p>
            : <p className="investigation-missing">No plan was recorded.</p>}
        </section>
      </div>

      <section className="investigation-recorded-section investigation-result-section">
        <h3>Persisted result data</h3>
        {!investigation.result ? (
          <p className="investigation-missing">No structured result was saved for this investigation.</p>
        ) : (
          <>
            {files.length > 0 && (
              <div className="investigation-result-field">
                <span>Files identified for change</span>
                <ul>{files.map((file, index) => <li key={`${file}-${index}`}><code>{file}</code></li>)}</ul>
              </div>
            )}
            {gitHead && <div className="investigation-result-field"><span>Git HEAD at investigation</span><code>{gitHead}</code></div>}
            {Object.keys(otherResult).length > 0 && (
              <pre className="investigation-result-json">{JSON.stringify(otherResult, null, 2)}</pre>
            )}
            {files.length === 0 && !gitHead && Object.keys(otherResult).length === 0 && (
              <p className="investigation-missing">The result was saved, but contains no displayable fields.</p>
            )}
          </>
        )}
        <p className="investigation-evidence-note">
          Retrieved code excerpts and investigation steps are not stored in this record. File paths above are recorded proposed changes, not source evidence.
        </p>
      </section>

      {investigation.invalidation_reason && (
        <div className="investigation-invalidation-note">
          <strong>Validity note:</strong> {investigation.invalidation_reason}
          {investigation.invalidated_at && <span> · Updated {formatTimestamp(investigation.invalidated_at)}</span>}
        </div>
      )}
    </section>
  )
}

export function InvestigationWorkspace({ repository }: InvestigationWorkspaceProps) {
  const repoPath = repository?.repo_path ?? null
  const [investigations, setInvestigations] = useState<InvestigationRecord[] | null>(null)
  const [selectedId, setSelectedId] = useState<number | null>(null)
  const [error, setError] = useState<Error | null>(null)
  const [loading, setLoading] = useState(false)
  const requestId = useRef(0)
  const controller = useRef<AbortController | null>(null)

  const load = useCallback(async () => {
    if (!repoPath) return
    const id = ++requestId.current
    controller.current?.abort()
    const nextController = new AbortController()
    controller.current = nextController
    setLoading(true)
    setError(null)
    try {
      const response = await fetchInvestigations(repoPath, nextController.signal)
      if (id === requestId.current) setInvestigations(response.investigations)
    } catch (reason) {
      if (nextController.signal.aborted || id !== requestId.current) return
      setError(reason instanceof Error ? reason : new Error(String(reason)))
    } finally {
      if (id === requestId.current) setLoading(false)
    }
  }, [repoPath])

  useEffect(() => {
    let active = true
    if (repoPath) void Promise.resolve().then(() => { if (active) void load() })
    return () => {
      active = false
      requestId.current += 1
      controller.current?.abort()
    }
  }, [load, repoPath])

  const selected = investigations?.find((investigation) => investigation.id === selectedId) ?? null

  return (
    <section className="investigations-workspace" aria-label="Investigations workspace">
      <header className="investigations-page-header">
        <div>
          <span className="section-kicker">Maintained engineering state</span>
          <h1>Investigations</h1>
          <p>Review persisted records. Status labels show memory validity; no investigation workflow status is stored.</p>
        </div>
        {repository && <div className="investigation-repository" title={repository.repo_path}>{repository.repo_name}</div>}
      </header>

      {!repository ? (
        <div className="investigations-empty card">
          <FileSearch size={24} />
          <h2>Inspect a repository first</h2>
          <p>Investigation records are loaded for the repository selected in the workspace.</p>
        </div>
      ) : selected ? (
        <InvestigationDetail investigation={selected} onBack={() => setSelectedId(null)} />
      ) : (
        <section className="investigation-list-panel card" aria-label="Persisted investigations">
          <div className="investigation-list-heading">
            <div>
              <span className="section-kicker">Repository history</span>
              <h2>Saved investigations</h2>
            </div>
            <button type="button" className="btn btn-secondary btn-sm" onClick={() => void load()} disabled={loading} aria-label="Refresh investigations">
              <RefreshCw size={14} className={loading ? 'spinner' : ''} />
            </button>
          </div>
          {loading && investigations === null && <div className="investigations-loading" role="status"><RefreshCw size={15} className="spinner" /> Loading saved investigations…</div>}
          {error && (
            <div className="investigations-error" role="alert">
              <AlertCircle size={17} />
              <div><strong>Could not load investigations</strong><p>{describeError(error)}</p></div>
              <button type="button" className="btn-link" onClick={() => void load()}>Retry</button>
            </div>
          )}
          {!loading && !error && investigations?.length === 0 && (
            <div className="investigations-empty-list"><BookOpen size={21} /><h3>No saved investigations</h3><p>No persisted investigation records were found for this repository.</p></div>
          )}
          {investigations && investigations.length > 0 && (
            <>
              <div className="investigation-count">Showing {investigations.length} records. The API returns up to 100 of the most recent investigations.</div>
              <ul className="investigation-record-list">
                {investigations.map((investigation) => (
                  <li key={investigation.id}>
                    <button type="button" className="investigation-record-row" onClick={() => setSelectedId(investigation.id)}>
                      <span className="investigation-record-main">
                        <strong>{investigation.problem}</strong>
                        <span>{investigation.root_cause || 'Root cause not recorded'}</span>
                      </span>
                      <span className="investigation-record-meta">
                        <span className={`investigation-validity validity-${(investigation.current_validity ?? 'unknown').toLowerCase()}`}>{displayValidity(investigation.current_validity)}</span>
                        <time>{formatTimestamp(investigation.created_at)}</time>
                      </span>
                    </button>
                  </li>
                ))}
              </ul>
            </>
          )}
        </section>
      )}
    </section>
  )
}
