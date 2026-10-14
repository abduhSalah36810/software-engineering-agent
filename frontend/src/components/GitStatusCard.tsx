import { useState } from 'react'
import { GitBranch, GitCommit, AlertOctagon, ChevronDown, ChevronUp } from 'lucide-react'
import type { GitStatusSummary } from '../types/api'

interface GitStatusCardProps {
  git: GitStatusSummary
}

export function GitStatusCard({ git }: GitStatusCardProps) {
  const [showAllUncommitted, setShowAllUncommitted] = useState(false)

  if (!git.is_git_repo) {
    return (
      <section className="card" aria-label="Git Version Control">
        <div className="card-header">
          <div className="card-title-group">
            <GitBranch size={18} className="text-muted" />
            <h3 className="card-title">Git Revision & Working Tree</h3>
          </div>
          <span className="badge badge-neutral">Non-Git Directory</span>
        </div>
        <div className="empty-subcard">
          <p className="text-muted">This directory is not managed by Git version control.</p>
        </div>
      </section>
    )
  }

  const visibleUncommitted = showAllUncommitted
    ? git.uncommitted_files
    : git.uncommitted_files.slice(0, 6)

  return (
    <section className="card" aria-label="Git Version Control">
      <div className="card-header">
        <div className="card-title-group">
          <GitBranch size={18} className="text-emerald" />
          <h3 className="card-title">Git Revision & Working Tree</h3>
        </div>
        <span className={`badge ${git.is_dirty ? 'badge-amber' : 'badge-emerald'}`}>
          {git.is_dirty ? `Dirty (${git.uncommitted_files.length} uncommitted)` : 'Clean Tree'}
        </span>
      </div>

      <div className="git-meta-grid">
        <div className="meta-box">
          <span className="meta-box-label">Active Branch</span>
          <span className="meta-box-value">
            <GitBranch size={14} className="text-emerald" />
            <code>{git.branch || 'HEAD (detached)'}</code>
          </span>
        </div>
        <div className="meta-box">
          <span className="meta-box-label">Current HEAD Commit</span>
          <span className="meta-box-value">
            <GitCommit size={14} className="text-blue" />
            <code className="monospace-chip font-bold">
              {git.head_commit ? git.head_commit.slice(0, 10) : 'None (unborn head)'}
            </code>
          </span>
        </div>
      </div>

      {git.has_uncommitted_changes && (
        <div className="uncommitted-section">
          <div className="uncommitted-header">
            <div className="uncommitted-title">
              <AlertOctagon size={14} className="text-amber" />
              <span>Uncommitted Working-Tree Changes ({git.uncommitted_files.length})</span>
            </div>
            {git.uncommitted_files.length > 6 && (
              <button
                type="button"
                onClick={() => setShowAllUncommitted(!showAllUncommitted)}
                className="btn-link"
              >
                {showAllUncommitted ? (
                  <>Show Less <ChevronUp size={14} /></>
                ) : (
                  <>Show All ({git.uncommitted_files.length}) <ChevronDown size={14} /></>
                )}
              </button>
            )}
          </div>
          <div className="uncommitted-files-list">
            {visibleUncommitted.map((file, idx) => (
              <span key={`uncommitted-${idx}`} className="file-pill file-pill-dirty">
                <code>{file}</code>
              </span>
            ))}
          </div>
        </div>
      )}

      {git.recent_commits.length > 0 && (
        <div className="commits-section">
          <h4 className="section-subtitle"><GitCommit size={14} /> Recent Evolution Log</h4>
          <div className="commit-list">
            {git.recent_commits.slice(0, 5).map((c, idx) => (
              <div key={`c-${idx}`} className="commit-item">
                <code className="commit-hash">{c.hash}</code>
                <span className="commit-msg" title={c.message}>{c.message}</span>
              </div>
            ))}
          </div>
        </div>
      )}
    </section>
  )
}
