import { useState } from 'react'
import { Folder, Code2, Layers, Cpu, Database, ChevronDown, ChevronUp, FileCode } from 'lucide-react'
import type { RepoIdentitySummary, ProjectProfileSummary } from '../types/api'

interface RepositoryIdentityCardProps {
  identity: RepoIdentitySummary
  profile: ProjectProfileSummary | null
}

export function RepositoryIdentityCard({
  identity,
  profile,
}: RepositoryIdentityCardProps) {
  const [showAllFindings, setShowAllFindings] = useState(false)

  const visibleFindings = showAllFindings
    ? profile?.findings || []
    : (profile?.findings || []).slice(0, 5)

  return (
    <section className="card" aria-label="Repository Identity & Profile">
      <div className="card-header">
        <div className="card-title-group">
          <Folder size={18} className="text-blue" />
          <h3 className="card-title">Repository Identity & Profile</h3>
        </div>
        <span className="badge badge-neutral">Canonical Identity</span>
      </div>

      <div className="identity-details">
        <div className="meta-row">
          <span className="meta-label">Display Name:</span>
          <span className="meta-value font-semibold">{profile?.name || identity.repo_name}</span>
        </div>
        <div className="meta-row">
          <span className="meta-label">Canonical ID:</span>
          <code className="meta-value monospace-chip">{identity.repo_id}</code>
        </div>
        <div className="meta-row">
          <span className="meta-label">Filesystem Path:</span>
          <code className="meta-value monospace-chip">{identity.repo_path}</code>
        </div>
      </div>

      {profile ? (
        <div className="profile-body">
          <div className="tag-section">
            <div className="tag-group">
              <span className="tag-label"><Code2 size={13} /> Languages:</span>
              <div className="tag-list">
                {profile.primary_language && (
                  <span className="badge badge-primary" title="Primary Language">
                    {profile.primary_language} (primary)
                  </span>
                )}
                {profile.detected_languages
                  .filter((l) => l !== profile.primary_language)
                  .map((lang) => (
                    <span key={lang} className="badge badge-neutral">
                      {lang}
                    </span>
                  ))}
              </div>
            </div>

            {profile.package_managers.length > 0 && (
              <div className="tag-group">
                <span className="tag-label"><Layers size={13} /> Package Managers:</span>
                <div className="tag-list">
                  {profile.package_managers.map((pm) => (
                    <span key={pm} className="badge badge-neutral">
                      {pm}
                    </span>
                  ))}
                </div>
              </div>
            )}

            {profile.entry_points.length > 0 && (
              <div className="tag-group">
                <span className="tag-label"><FileCode size={13} /> Entry Points:</span>
                <div className="tag-list">
                  {profile.entry_points.map((ep) => (
                    <span key={ep} className="badge badge-mono">
                      {ep}
                    </span>
                  ))}
                </div>
              </div>
            )}
          </div>

          <div className="feature-flags-grid">
            <div className="flag-card">
              <span className="flag-label">Docker Containerization</span>
              <span className={`flag-status ${profile.has_docker ? 'status-yes' : 'status-no'}`}>
                {profile.has_docker ? 'Detected' : 'None'}
              </span>
            </div>
            <div className="flag-card">
              <span className="flag-label">Automated Tests</span>
              <span className={`flag-status ${profile.has_tests ? 'status-yes' : 'status-no'}`}>
                {profile.has_tests ? 'Present' : 'Not Detected'}
              </span>
            </div>
          </div>

          {(profile.frameworks.length > 0 || profile.databases.length > 0) && (
            <div className="technologies-section">
              <h4 className="section-subtitle"><Cpu size={14} /> Technology Ecosystem</h4>
              <div className="tech-items-grid">
                {profile.frameworks.map((fw, idx) => (
                  <div key={`fw-${idx}`} className="tech-item">
                    <span className="tech-name">{fw.name} {fw.version ? `v${fw.version}` : ''}</span>
                    <span className="tech-purpose">{fw.purpose}</span>
                  </div>
                ))}
                {profile.databases.map((db, idx) => (
                  <div key={`db-${idx}`} className="tech-item">
                    <span className="tech-name"><Database size={12} /> {db.name}</span>
                    <span className="tech-purpose">{db.purpose}</span>
                  </div>
                ))}
              </div>
            </div>
          )}

          {profile.findings.length > 0 && (
            <div className="findings-section">
              <div className="findings-header">
                <h4 className="section-subtitle">
                  Evidence-Backed Findings ({profile.findings.length})
                </h4>
                {profile.findings.length > 5 && (
                  <button
                    type="button"
                    onClick={() => setShowAllFindings(!showAllFindings)}
                    className="btn-link"
                  >
                    {showAllFindings ? (
                      <>Show Less <ChevronUp size={14} /></>
                    ) : (
                      <>Show All ({profile.findings.length}) <ChevronDown size={14} /></>
                    )}
                  </button>
                )}
              </div>
              <ul className="findings-list">
                {visibleFindings.map((finding, idx) => (
                  <li key={`finding-${idx}`} className={`finding-item severity-${finding.severity || 'info'}`}>
                    <div className="finding-meta">
                      <span className={`badge badge-severity-${finding.severity || 'info'}`}>
                        {finding.severity?.toUpperCase() || 'INFO'}
                      </span>
                      <span className="finding-category">{finding.category}</span>
                      <span className="finding-source badge-mono">src: {finding.source}</span>
                    </div>
                    <div className="finding-obs">{finding.observation}</div>
                    {finding.evidence && (
                      <div className="finding-evidence">
                        <code>Evidence: {finding.evidence}</code>
                      </div>
                    )}
                  </li>
                ))}
              </ul>
            </div>
          )}
        </div>
      ) : (
        <div className="empty-subcard">
          <p className="text-muted">
            No persisted engineering profile in memory yet. The repository has not undergone repository discovery.
          </p>
        </div>
      )}
    </section>
  )
}
