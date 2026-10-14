import { useState } from 'react'
import type { FormEvent } from 'react'
import { Search, FolderGit2, Activity, AlertCircle, RefreshCw } from 'lucide-react'

interface ProjectSelectorProps {
  currentPath: string
  loading: boolean
  onInspect: (path: string, includeAssessment: boolean) => void
  disabled?: boolean
}

export function ProjectSelector({
  currentPath,
  loading,
  onInspect,
  disabled = false,
}: ProjectSelectorProps) {
  const [inputPath, setInputPath] = useState(currentPath || '.')
  const [validationError, setValidationError] = useState<string | null>(null)

  const handleSubmit = (e: FormEvent, includeAssessment: boolean = false) => {
    e.preventDefault()
    const trimmed = inputPath.trim()
    if (!trimmed) {
      setValidationError('Please enter a valid local repository directory path.')
      return
    }
    setValidationError(null)
    onInspect(trimmed, includeAssessment)
  }

  const handleQuickSelect = (preset: string) => {
    setInputPath(preset)
    setValidationError(null)
    onInspect(preset, false)
  }

  return (
    <section className="card selector-card" aria-label="Repository Selector">
      <form onSubmit={(e) => handleSubmit(e, false)} className="selector-form">
        <div className="selector-input-group">
          <label htmlFor="repo-path-input" className="selector-label">
            <FolderGit2 size={16} className="text-accent" />
            <span>Target Repository Path</span>
          </label>
          <div className="input-wrapper">
            <input
              id="repo-path-input"
              type="text"
              value={inputPath}
              onChange={(e) => {
                setInputPath(e.target.value)
                if (validationError) setValidationError(null)
              }}
              placeholder="e.g. . or /home/abdurrahman/software-engineering-agent or ./repos/youtube-dl"
              disabled={disabled || loading}
              className={`text-input ${validationError ? 'input-error' : ''}`}
            />
            {loading && <RefreshCw size={16} className="spinner input-spinner" />}
          </div>
          {validationError && (
            <div className="validation-error-msg">
              <AlertCircle size={14} />
              <span>{validationError}</span>
            </div>
          )}
        </div>

        <div className="selector-actions">
          <button
            type="submit"
            disabled={disabled || loading}
            className="btn btn-primary"
            title="Fetch read-only Git, Profile, and Memory overview without heavy AST scan"
          >
            {loading ? <RefreshCw size={15} className="spinner" /> : <Search size={15} />}
            <span>Inspect Repository</span>
          </button>

          <button
            type="button"
            onClick={(e) => handleSubmit(e, true)}
            disabled={disabled || loading}
            className="btn btn-secondary"
            title="Fetch overview with full deterministic AST Code Health and Project Stage synthesis"
          >
            <Activity size={15} />
            <span>Analyze with Assessment</span>
          </button>
        </div>
      </form>

      <div className="quick-presets">
        <span className="presets-label">Quick Presets:</span>
        <button
          type="button"
          onClick={() => handleQuickSelect('.')}
          disabled={disabled || loading}
          className="chip-btn"
        >
          <span>Current Agent Repo (<code>.</code>)</span>
        </button>
        <button
          type="button"
          onClick={() => handleQuickSelect('./repos/youtube-dl')}
          disabled={disabled || loading}
          className="chip-btn"
        >
          <span>Cloned Sample (<code>./repos/youtube-dl</code>)</span>
        </button>
      </div>
    </section>
  )
}
