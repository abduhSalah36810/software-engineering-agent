import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { AlertCircle, ArrowLeft, BookOpen, Clock3, GitCommitHorizontal, Search, ShieldCheck, RefreshCw } from 'lucide-react'
import { ApiError, fetchEngineeringMemory } from '../api/client'
import type {
  EngineeringChangeRecord,
  EngineeringDecisionRecord,
  EngineeringMemoryResponse,
  RepoIdentitySummary,
} from '../types/api'

interface EngineeringMemoryWorkspaceProps {
  repository: RepoIdentitySummary | null
}

type MemoryFilter = 'all' | 'decisions' | 'changes'
type MemoryItem =
  | { type: 'decision'; record: EngineeringDecisionRecord; key: string; createdAt: string }
  | { type: 'change'; record: EngineeringChangeRecord; key: string; createdAt: string }

function readable(value: string | null | undefined, empty = 'Not recorded') {
  return value?.trim() ? value : empty
}

function formatTime(value: string) {
  const date = new Date(value)
  return Number.isNaN(date.getTime()) ? value : date.toLocaleString()
}

function formatValidity(value: string | null) {
  if (!value) return 'Validity not recorded'
  return value.replaceAll('_', ' ').toLowerCase().replace(/\b\w/g, (letter) => letter.toUpperCase())
}

function sourceDescription(source: string) {
  switch (source.toLowerCase()) {
    case 'user_confirmed': return 'User confirmed'
    case 'agent_recommendation': return 'Agent recommendation · unconfirmed'
    case 'inferred': return 'Inferred'
    case 'observed': return 'Observed source'
    case 'external_doc': return 'External documentation'
    default: return `Recorded source · ${source}`
  }
}

function sourceClass(source: string) {
  return `memory-source-label source-${source.toLowerCase()}`
}

function decisionStatusClass(value: string | null) {
  return `memory-validity validity-${(value ?? 'unknown').toLowerCase()}`
}

function DecisionDetail({ record }: { record: EngineeringDecisionRecord }) {
  return (
    <article className="memory-detail card">
      <span className="section-kicker">Engineering decision · #{record.id}</span>
      <h2>{record.subject}</h2>
      <div className="memory-detail-meta">
        <span className={sourceClass(record.source)}>{sourceDescription(record.source)}</span>
        <span className={decisionStatusClass(record.current_validity)}>{formatValidity(record.current_validity)}</span>
        <time><Clock3 size={13} /> {formatTime(record.created_at)}</time>
      </div>
      <section className="memory-detail-section">
        <h3>Recorded decision</h3>
        <p className="memory-long-text">{record.decision}</p>
      </section>
      <section className="memory-detail-section">
        <h3>Rationale</h3>
        <p className="memory-long-text">{readable(record.rationale)}</p>
      </section>
      {record.reference && (
        <section className="memory-detail-section">
          <h3>Reference</h3>
          <p className="memory-long-text">{record.reference}</p>
        </section>
      )}
      {record.invalidation_reason && (
        <div className="memory-validity-note">
          <strong>Validity note:</strong> {record.invalidation_reason}
          {record.invalidated_at && <span> · Updated {formatTime(record.invalidated_at)}</span>}
        </div>
      )}
      <p className="memory-provenance-note">Source describes how this record was captured. Only “User confirmed” indicates explicit user confirmation; agent recommendations and inferences are not approved decisions.</p>
    </article>
  )
}

function ChangeDetail({ record }: { record: EngineeringChangeRecord }) {
  return (
    <article className="memory-detail card">
      <span className="section-kicker">Commit change record · #{record.id}</span>
      <h2 className="memory-commit-hash">{record.commit_hash}</h2>
      <div className="memory-detail-meta">
        <time><Clock3 size={13} /> {formatTime(record.created_at)}</time>
        <span className={`memory-drift ${record.drift_detected ? 'has-drift' : ''}`}>
          {record.drift_detected ? 'Drift marked' : 'No drift marked'}
        </span>
      </div>
      <section className="memory-detail-section">
        <h3>Recorded changed files <span>{record.changed_files.length}</span></h3>
        {record.changed_files.length > 0 ? (
          <ul className="memory-file-list">{record.changed_files.map((file, index) => <li key={`${file}-${index}`}><code>{file}</code></li>)}</ul>
        ) : <p className="memory-missing">No changed files were recorded for this commit.</p>}
      </section>
      {record.changed_symbols && record.changed_symbols.length > 0 && (
        <section className="memory-detail-section">
          <h3>Recorded changed symbols</h3>
          <ul className="memory-file-list">{record.changed_symbols.map((symbol, index) => <li key={`${symbol}-${index}`}><code>{symbol}</code></li>)}</ul>
        </section>
      )}
      <section className="memory-impact-section">
        <h3>Recorded engineering impact</h3>
        {record.architecture_impact
          ? <p className="memory-long-text">{record.architecture_impact}</p>
          : <p className="memory-missing">No architecture impact was recorded.</p>}
        {record.review && <div className="memory-review"><strong>Review</strong><p>{record.review}</p></div>}
        <p className="memory-provenance-note">File and symbol lists are stored commit metadata. Architecture impact, drift, and review are recorded assessments, not direct file-system measurements.</p>
      </section>
    </article>
  )
}

function describeError(error: Error) {
  return error instanceof ApiError ? error.detail : error.message
}

export function EngineeringMemoryWorkspace({ repository }: EngineeringMemoryWorkspaceProps) {
  const repoPath = repository?.repo_path ?? null
  const [data, setData] = useState<EngineeringMemoryResponse | null>(null)
  const [filter, setFilter] = useState<MemoryFilter>('all')
  const [query, setQuery] = useState('')
  const [selectedKey, setSelectedKey] = useState<string | null>(null)
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
      const response = await fetchEngineeringMemory(repoPath, nextController.signal)
      if (id === requestId.current) setData(response)
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

  const items = useMemo<MemoryItem[]>(() => {
    if (!data) return []
    const combined: MemoryItem[] = [
      ...data.decisions.map((record) => ({ type: 'decision' as const, record, key: `decision:${record.id}`, createdAt: record.created_at })),
      ...data.change_records.map((record) => ({ type: 'change' as const, record, key: `change:${record.id}`, createdAt: record.created_at })),
    ]
    return combined.sort((a, b) => new Date(b.createdAt).getTime() - new Date(a.createdAt).getTime())
  }, [data])

  const filteredItems = useMemo(() => {
    const needle = query.trim().toLowerCase()
    return items.filter((item) => {
      if (filter === 'decisions' && item.type !== 'decision') return false
      if (filter === 'changes' && item.type !== 'change') return false
      if (!needle) return true
      if (item.type === 'decision') {
        const record = item.record
        return [record.subject, record.decision, record.rationale, record.source, record.reference, record.current_validity, record.invalidation_reason]
          .some((value) => value?.toLowerCase().includes(needle))
      }
      const record = item.record
      return [record.commit_hash, record.changed_files.join(' '), record.changed_symbols?.join(' '), record.architecture_impact, record.review, String(record.drift_detected)]
        .some((value) => value?.toLowerCase().includes(needle))
    })
  }, [filter, items, query])

  const selected = filteredItems.find((item) => item.key === selectedKey) ?? null
  const counts = { decisions: data?.decisions.length ?? 0, changes: data?.change_records.length ?? 0 }

  return (
    <section className="engineering-memory-workspace" aria-label="Engineering memory workspace">
      <header className="engineering-memory-heading">
        <div>
          <span className="section-kicker">Maintained engineering state</span>
          <h1>Engineering memory</h1>
          <p>Inspect stored decisions and commit records for the selected repository.</p>
        </div>
        {repository && <span className="memory-repository-name" title={repository.repo_path}>{repository.repo_name}</span>}
      </header>

      {!repository ? (
        <div className="memory-empty card"><BookOpen size={24} /><h2>Inspect a repository first</h2><p>Engineering memory is loaded for the repository selected in the workspace.</p></div>
      ) : (
        <section className="memory-browser card" aria-label="Persisted engineering memory">
          <div className="memory-browser-toolbar">
            <div className="memory-filter-tabs" role="tablist" aria-label="Memory record type">
              {(['all', 'decisions', 'changes'] as const).map((value) => (
                <button type="button" role="tab" aria-selected={filter === value} className={filter === value ? 'is-active' : ''} onClick={() => { setFilter(value); setSelectedKey(null) }} key={value}>
                  {value === 'all' ? `All (${counts.decisions + counts.changes})` : value === 'decisions' ? `Decisions (${counts.decisions})` : `Change records (${counts.changes})`}
                </button>
              ))}
            </div>
            <button type="button" className="btn btn-secondary btn-sm" onClick={() => void load()} disabled={loading} aria-label="Refresh engineering memory">
              <RefreshCw size={14} className={loading ? 'spinner' : ''} />
            </button>
          </div>

          {!selected && (
            <label className="memory-search">
              <Search size={15} />
              <input type="search" value={query} onChange={(event) => setQuery(event.target.value)} placeholder="Search decisions, files, commits, and recorded summaries" aria-label="Search engineering memory" />
            </label>
          )}

          {loading && !data && <div className="memory-state-message" role="status"><RefreshCw size={15} className="spinner" /> Loading engineering memory…</div>}
          {error && <div className="memory-error" role="alert"><AlertCircle size={17} /><div><strong>Could not load engineering memory</strong><p>{describeError(error)}</p></div><button type="button" className="btn-link" onClick={() => void load()}>Retry</button></div>}
          {!loading && !error && data && items.length === 0 && <div className="memory-empty-list"><BookOpen size={22} /><h2>No persisted decisions or change records</h2><p>The repository has no records of these types in engineering memory.</p></div>}
          {!loading && !error && data && items.length > 0 && !selected && filteredItems.length === 0 && <div className="memory-empty-list"><Search size={20} /><h2>No matching records</h2><p>Try another search or record type.</p></div>}

          {!loading && !error && selected?.type === 'decision' && (
            <div className="memory-detail-view"><button type="button" className="memory-back-button" onClick={() => setSelectedKey(null)}><ArrowLeft size={14} /> Back to records</button><DecisionDetail record={selected.record} /></div>
          )}
          {!loading && !error && selected?.type === 'change' && (
            <div className="memory-detail-view"><button type="button" className="memory-back-button" onClick={() => setSelectedKey(null)}><ArrowLeft size={14} /> Back to records</button><ChangeDetail record={selected.record} /></div>
          )}

          {!loading && !error && data && !selected && filteredItems.length > 0 && (
            <>
              <div className="memory-list-count">{filteredItems.length} matching record{filteredItems.length === 1 ? '' : 's'}{data.change_records_truncated ? ' · additional older change records may be omitted' : ''}</div>
              <ul className="memory-record-list">
                {filteredItems.map((item) => (
                  <li key={item.key}>
                    <button type="button" className="memory-record-row" onClick={() => setSelectedKey(item.key)}>
                      {item.type === 'decision' ? <ShieldCheck size={17} className="memory-decision-icon" /> : <GitCommitHorizontal size={17} className="memory-change-icon" />}
                      <span className="memory-record-summary">
                        <strong>{item.type === 'decision' ? item.record.subject : item.record.commit_hash.slice(0, 12)}</strong>
                        <span>{item.type === 'decision' ? item.record.decision : item.record.review || item.record.architecture_impact || `${item.record.changed_files.length} recorded file changes`}</span>
                      </span>
                      <span className="memory-record-meta">
                        {item.type === 'decision' ? <><span className={sourceClass(item.record.source)}>{sourceDescription(item.record.source)}</span><span className={decisionStatusClass(item.record.current_validity)}>{formatValidity(item.record.current_validity)}</span></> : <span className="memory-record-kind">Change record</span>}
                        <time>{formatTime(item.createdAt)}</time>
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
