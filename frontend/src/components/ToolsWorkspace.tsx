import { useCallback, useEffect, useState } from 'react'
import {
  AlertCircle,
  CheckCircle2,
  Clock,
  FileCode2,
  GitBranch,
  Play,
  RotateCcw,
  ShieldCheck,
  Terminal,
} from 'lucide-react'
import { ApiError, executeTool, fetchRegisteredTools } from '../api/client'
import type {
  RepoIdentitySummary,
  ToolDescriptor,
  ToolExecutionResponse,
} from '../types/api'

interface ToolsWorkspaceProps {
  repository: RepoIdentitySummary | null
}

export function ToolsWorkspace({ repository }: ToolsWorkspaceProps) {
  const repoPath = repository?.repo_path ?? ''

  const [tools, setTools] = useState<ToolDescriptor[]>([])
  const [loadingTools, setLoadingTools] = useState<boolean>(false)
  const [toolsError, setToolsError] = useState<string | null>(null)

  const [selectedTool, setSelectedTool] = useState<string>('git')
  const [selectedOperation, setSelectedOperation] = useState<string>('status')

  // Form arguments
  const [argPath, setArgPath] = useState<string>('.')
  const [argPattern, setArgPattern] = useState<string>('')
  const [argLimit, setArgLimit] = useState<number>(10)
  const [argRef, setArgRef] = useState<string>('HEAD')
  const [argCommand, setArgCommand] = useState<string>('git --version')
  const [argStaged, setArgStaged] = useState<boolean>(false)

  // Execution state
  const [executing, setExecuting] = useState<boolean>(false)
  const [executionResult, setExecutionResult] = useState<ToolExecutionResponse | null>(null)
  const [executionError, setExecutionError] = useState<string | null>(null)

  const loadTools = useCallback(async () => {
    if (!repoPath) return
    setLoadingTools(true)
    setToolsError(null)
    try {
      const res = await fetchRegisteredTools(repoPath)
      setTools(res.tools)
      if (res.tools.length > 0 && !res.tools.some((t) => t.name === selectedTool)) {
        setSelectedTool(res.tools[0].name)
        if (res.tools[0].supported_operations.length > 0) {
          setSelectedOperation(res.tools[0].supported_operations[0])
        }
      }
    } catch (err) {
      setToolsError(err instanceof ApiError ? err.detail : String(err))
    } finally {
      setLoadingTools(false)
    }
  }, [repoPath, selectedTool])

  useEffect(() => {
    loadTools()
  }, [loadTools])

  const handleToolSelect = (toolName: string) => {
    setSelectedTool(toolName)
    const t = tools.find((item) => item.name === toolName)
    if (t && t.supported_operations.length > 0) {
      setSelectedOperation(t.supported_operations[0])
    }
    setExecutionResult(null)
    setExecutionError(null)
  }

  const handleRunTool = async () => {
    if (!repoPath) return
    setExecuting(true)
    setExecutionError(null)

    // Build arguments map based on tool & operation
    const args: Record<string, any> = {}
    if (selectedTool === 'git') {
      if (selectedOperation === 'log') {
        args.limit = argLimit
        if (argRef) args.revision = argRef
        if (argPath && argPath !== '.') args.path = argPath
      } else if (selectedOperation === 'diff') {
        if (argStaged) args.staged = true
        if (argPath && argPath !== '.') args.path = argPath
        if (argRef && argRef !== 'HEAD') args.commit = argRef
      } else if (selectedOperation === 'changed_files') {
        if (argStaged) args.staged = true
        args.limit = argLimit
      }
    } else if (selectedTool === 'filesystem') {
      if (selectedOperation === 'list_dir') {
        args.path = argPath || '.'
      } else if (selectedOperation === 'read_file') {
        args.path = argPath || 'README.md'
      } else if (selectedOperation === 'search_text') {
        args.pattern = argPattern
        if (argPath && argPath !== '.') args.path = argPath
      }
    } else if (selectedTool === 'terminal') {
      args.command = argCommand
    }

    try {
      const res = await executeTool(repoPath, selectedTool, selectedOperation, args)
      setExecutionResult(res)
    } catch (err) {
      setExecutionError(err instanceof ApiError ? err.detail : String(err))
    } finally {
      setExecuting(false)
    }
  }

  const currentToolDescriptor = tools.find((t) => t.name === selectedTool)
  const operations = currentToolDescriptor?.supported_operations || []

  return (
    <div className="workspace-view" aria-label="Tools Workspace">
      {/* Workspace Subheader */}
      <div className="workspace-subheader">
        <div>
          <h2 className="workspace-view-title">Tooling & Capability Sandbox</h2>
          <p className="workspace-view-subtitle">
            Execute verified, sandboxed repository operations through the Tool Foundation.
          </p>
        </div>
        <div className="workspace-subheader-actions">
          <span className="badge badge-emerald">
            <ShieldCheck size={13} style={{ marginRight: 4 }} /> Read-Only Safety Enforced
          </span>
          <button
            type="button"
            className="btn btn-secondary"
            onClick={loadTools}
            disabled={loadingTools}
            title="Reload available tools"
          >
            <RotateCcw size={14} className={loadingTools ? 'animate-spin' : ''} />
            <span>Reload</span>
          </button>
        </div>
      </div>

      {toolsError && (
        <div className="banner banner-error" role="alert">
          <AlertCircle size={16} />
          <span>{toolsError}</span>
        </div>
      )}

      {/* Tools Selector Tabs */}
      <div className="card" style={{ marginBottom: 16 }}>
        <div className="card-header">
          <h3 className="card-title">Available Capability Adapters</h3>
          <span className="badge badge-neutral">{tools.length} Registered</span>
        </div>
        <div className="tool-selector-grid" style={{ display: 'flex', gap: 12, padding: '8px 16px 16px' }}>
          {tools.map((t) => (
            <button
              key={t.name}
              type="button"
              className={`tool-card-btn ${selectedTool === t.name ? 'is-active' : ''}`}
              onClick={() => handleToolSelect(t.name)}
              style={{
                flex: 1,
                padding: '12px 16px',
                textAlign: 'left',
                borderRadius: 8,
                border: selectedTool === t.name ? '2px solid var(--accent, #3b82f6)' : '1px solid var(--border, #334155)',
                background: selectedTool === t.name ? 'var(--bg-active, rgba(59, 130, 246, 0.1))' : 'var(--bg-card, #1e293b)',
                cursor: 'pointer',
                color: 'inherit',
              }}
            >
              <div style={{ display: 'flex', alignItems: 'center', gap: 8, fontWeight: 600, marginBottom: 4 }}>
                {t.name === 'git' && <GitBranch size={16} className="text-emerald" />}
                {t.name === 'filesystem' && <FileCode2 size={16} className="text-blue" />}
                {t.name === 'terminal' && <Terminal size={16} className="text-amber" />}
                <span style={{ textTransform: 'capitalize' }}>{t.name} Tool</span>
              </div>
              <small style={{ display: 'block', color: 'var(--text-muted, #94a3b8)', fontSize: '0.8rem' }}>
                {t.description}
              </small>
            </button>
          ))}
        </div>
      </div>

      {/* Operation & Execution Form */}
      <div className="card" style={{ marginBottom: 16 }}>
        <div className="card-header">
          <h3 className="card-title">
            Configure Operation: <code style={{ color: 'var(--accent, #60a5fa)' }}>{selectedTool}.{selectedOperation}</code>
          </h3>
        </div>
        <div style={{ padding: 16 }}>
          {/* Operations Pills */}
          <div style={{ marginBottom: 16 }}>
            <span style={{ display: 'block', fontSize: '0.85rem', color: 'var(--text-muted, #94a3b8)', marginBottom: 6 }}>
              Select Operation:
            </span>
            <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
              {operations.map((op) => (
                <button
                  key={op}
                  type="button"
                  className={`btn ${selectedOperation === op ? 'btn-primary' : 'btn-secondary'}`}
                  onClick={() => setSelectedOperation(op)}
                  style={{ fontSize: '0.85rem', padding: '4px 12px' }}
                >
                  {op}
                </button>
              ))}
            </div>
          </div>

          {/* Dynamic Inputs based on selected tool & operation */}
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(240px, 1fr))', gap: 12, marginBottom: 16 }}>
            {(selectedOperation === 'read_file' || selectedOperation === 'list_dir' || (selectedTool === 'filesystem' && selectedOperation === 'search_text') || (selectedTool === 'git' && (selectedOperation === 'diff' || selectedOperation === 'log'))) && (
              <div>
                <label style={{ display: 'block', fontSize: '0.85rem', marginBottom: 4 }}>
                  Target Path (repository-relative):
                </label>
                <input
                  type="text"
                  className="input"
                  value={argPath}
                  onChange={(e) => setArgPath(e.target.value)}
                  placeholder={selectedOperation === 'read_file' ? 'README.md' : '.'}
                  style={{ width: '100%' }}
                />
              </div>
            )}

            {selectedOperation === 'search_text' && (
              <div>
                <label style={{ display: 'block', fontSize: '0.85rem', marginBottom: 4 }}>
                  Search Pattern / Regex:
                </label>
                <input
                  type="text"
                  className="input"
                  value={argPattern}
                  onChange={(e) => setArgPattern(e.target.value)}
                  placeholder="e.g. def run() or FastAPI"
                  style={{ width: '100%' }}
                />
              </div>
            )}

            {selectedTool === 'git' && selectedOperation === 'log' && (
              <div>
                <label style={{ display: 'block', fontSize: '0.85rem', marginBottom: 4 }}>
                  Revision / Ref:
                </label>
                <input
                  type="text"
                  className="input"
                  value={argRef}
                  onChange={(e) => setArgRef(e.target.value)}
                  placeholder="HEAD or commit hash"
                  style={{ width: '100%' }}
                />
              </div>
            )}

            {(selectedOperation === 'log' || selectedOperation === 'changed_files') && (
              <div>
                <label style={{ display: 'block', fontSize: '0.85rem', marginBottom: 4 }}>
                  Limit (max records):
                </label>
                <input
                  type="number"
                  className="input"
                  value={argLimit}
                  onChange={(e) => setArgLimit(Number(e.target.value))}
                  min={1}
                  max={100}
                  style={{ width: '100%' }}
                />
              </div>
            )}

            {selectedTool === 'git' && (selectedOperation === 'diff' || selectedOperation === 'changed_files') && (
              <div style={{ display: 'flex', alignItems: 'center', marginTop: 24 }}>
                <label style={{ display: 'flex', alignItems: 'center', gap: 6, cursor: 'pointer' }}>
                  <input
                    type="checkbox"
                    checked={argStaged}
                    onChange={(e) => setArgStaged(e.target.checked)}
                  />
                  <span>Staged changes only</span>
                </label>
              </div>
            )}

            {selectedTool === 'terminal' && (
              <div style={{ gridColumn: '1 / -1' }}>
                <label style={{ display: 'block', fontSize: '0.85rem', marginBottom: 4 }}>
                  Command (read-only safe commands):
                </label>
                <input
                  type="text"
                  className="input"
                  value={argCommand}
                  onChange={(e) => setArgCommand(e.target.value)}
                  placeholder="e.g. git --version or pwd or ls"
                  style={{ width: '100%' }}
                />
              </div>
            )}
          </div>

          <div style={{ display: 'flex', justifyContent: 'flex-end' }}>
            <button
              type="button"
              className="btn btn-primary"
              onClick={handleRunTool}
              disabled={executing || !repoPath}
              style={{ display: 'flex', alignItems: 'center', gap: 6 }}
            >
              <Play size={15} />
              <span>{executing ? 'Executing...' : 'Execute Tool'}</span>
            </button>
          </div>
        </div>
      </div>

      {/* Execution Results View */}
      {executionError && (
        <div className="banner banner-error" role="alert" style={{ marginBottom: 16 }}>
          <AlertCircle size={16} />
          <span>Execution failed: {executionError}</span>
        </div>
      )}

      {executionResult && (
        <div className="card" style={{ marginBottom: 16 }}>
          <div className="card-header">
            <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
              {executionResult.success ? (
                <CheckCircle2 size={18} className="text-emerald" />
              ) : (
                <AlertCircle size={18} className="text-amber" />
              )}
              <h3 className="card-title">
                Result: {executionResult.tool_name}.{executionResult.operation}
              </h3>
            </div>
            <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
              <span className={`badge ${executionResult.success ? 'badge-emerald' : 'badge-amber'}`}>
                {executionResult.success ? 'Success' : 'Error'}
              </span>
              {executionResult.metadata?.executed_at && (
                <span className="file-pill" style={{ fontSize: '0.75rem' }}>
                  <Clock size={11} style={{ marginRight: 4 }} />
                  {executionResult.metadata.executed_at.slice(11, 19)}
                </span>
              )}
            </div>
          </div>

          <div style={{ padding: 16 }}>
            {executionResult.error && (
              <div className="banner banner-amber" style={{ marginBottom: 12 }}>
                <strong>Error:</strong> {executionResult.error}
              </div>
            )}

            {/* Evidence Provenance Pill */}
            {executionResult.evidence && (
              <div
                style={{
                  background: 'var(--bg-subtle, rgba(255, 255, 255, 0.03))',
                  border: '1px solid var(--border, #334155)',
                  borderRadius: 6,
                  padding: '8px 12px',
                  marginBottom: 12,
                  fontSize: '0.8rem',
                  display: 'flex',
                  gap: 16,
                  flexWrap: 'wrap',
                  alignItems: 'center',
                }}
              >
                <span><strong>Evidence Source:</strong> {executionResult.evidence.source_tool}</span>
                <span><strong>Category:</strong> {executionResult.evidence.category}</span>
                <span><strong>Interpreted:</strong> {executionResult.evidence.is_interpreted ? 'True' : 'False (Raw Fact)'}</span>
                {executionResult.evidence.target && (
                  <span><strong>Target:</strong> <code>{executionResult.evidence.target}</code></span>
                )}
              </div>
            )}

            {/* Output formatting */}
            <div
              style={{
                background: 'var(--bg-code, #0f172a)',
                color: 'var(--text-code, #f8fafc)',
                padding: 16,
                borderRadius: 8,
                maxHeight: 480,
                overflow: 'auto',
                fontSize: '0.85rem',
                fontFamily: 'monospace',
                whiteSpace: 'pre-wrap',
                border: '1px solid var(--border, #334155)',
              }}
            >
              {typeof executionResult.output === 'string'
                ? executionResult.output
                : JSON.stringify(executionResult.output, null, 2)}
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
