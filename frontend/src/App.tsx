import { useRef, useState } from 'react'
import {
  Activity,
  Brain,
  FolderGit2,
  GitBranch,
  LayoutDashboard,
  Terminal,
} from 'lucide-react'
import { fetchProjectOverview, ApiError } from './api/client'
import type { ProjectOverviewResponse } from './types/api'

import { ProjectSelector } from './components/ProjectSelector'
import { StaleWarningBanner } from './components/StaleWarningBanner'
import { RepositoryIdentityCard } from './components/RepositoryIdentityCard'
import { GitStatusCard } from './components/GitStatusCard'
import { IncrementalIntelligenceCard } from './components/IncrementalIntelligenceCard'
import { EngineeringMemoryCard } from './components/EngineeringMemoryCard'
import { AssessmentCard } from './components/AssessmentCard'
import { ErrorBanner } from './components/ErrorBanner'
import { LoadingSkeleton } from './components/LoadingSkeleton'
import { RepositoryExplorer } from './components/RepositoryExplorer'
import { InvestigationWorkspace } from './components/InvestigationWorkspace'
import { EngineeringMemoryWorkspace } from './components/EngineeringMemoryWorkspace'
import { ToolsWorkspace } from './components/ToolsWorkspace'

export function App() {
  const [activeView, setActiveView] = useState<'overview' | 'explorer' | 'investigations' | 'memory' | 'tools'>('overview')
  const [repoPath, setRepoPath] = useState<string>('.')
  const [loading, setLoading] = useState<boolean>(false)
  const [loadingAssessment, setLoadingAssessment] = useState<boolean>(false)
  const [data, setData] = useState<ProjectOverviewResponse | null>(null)
  const [error, setError] = useState<ApiError | Error | null>(null)
  const latestRequest = useRef(0)

  const handleInspect = async (path: string, includeAssessment: boolean = false) => {
    const requestId = ++latestRequest.current
    const isSameRepository =
      path.trim() === repoPath.trim() || path.trim() === data?.identity.repo_path
    setRepoPath(path)
    if (!isSameRepository) {
      setData(null)
    }
    if (includeAssessment) {
      setLoading(false)
      setLoadingAssessment(true)
    } else {
      setLoadingAssessment(false)
      setLoading(true)
    }
    setError(null)

    try {
      const response = await fetchProjectOverview(path, includeAssessment)
      if (requestId !== latestRequest.current) return
      setData(response)
    } catch (err: unknown) {
      if (requestId !== latestRequest.current) return
      if (err instanceof Error || err instanceof ApiError) {
        setError(err)
      } else {
        setError(new Error(String(err)))
      }
    } finally {
      if (requestId === latestRequest.current) {
        setLoading(false)
        setLoadingAssessment(false)
      }
    }
  }

  const handleRunAssessment = () => {
    if (data?.identity.repo_path) {
      handleInspect(data.identity.repo_path, true)
    } else if (repoPath) {
      handleInspect(repoPath, true)
    }
  }

  const repositoryName = data?.identity.repo_name || 'No repository selected'
  const repositoryPath = data?.identity.repo_path || repoPath

  return (
    <div className="workspace-shell">
      <aside className="workspace-sidebar" aria-label="Application sidebar">
        <a className="workspace-brand" href="#overview" onClick={() => setActiveView('overview')} aria-label="Software Engineering Agent overview">
          <span className="workspace-brand-mark"><Terminal size={19} /></span>
          <span className="workspace-brand-copy">
            <strong>Engineering Agent</strong>
            <small>Maintained engineering state</small>
          </span>
        </a>

        <div className="sidebar-repository" aria-live="polite">
          <span className="sidebar-eyebrow">Active repository</span>
          <span className="sidebar-repo-name">{repositoryName}</span>
          <code title={repositoryPath}>{repositoryPath}</code>
        </div>

        <nav className="workspace-navigation" aria-label="Workspace navigation">
          <span className="sidebar-eyebrow">Workspace</span>
          <a className={`navigation-link ${activeView === 'overview' ? 'is-current' : ''}`} href="#overview" onClick={() => setActiveView('overview')} aria-current={activeView === 'overview' ? 'page' : undefined}>
            <LayoutDashboard size={16} /> <span>Overview</span>
          </a>
          <a className="navigation-link" href="#repository-context" onClick={() => setActiveView('overview')}>
            <FolderGit2 size={16} /> <span>Repository</span>
          </a>
          <a className="navigation-link" href="#code-health" onClick={() => setActiveView('overview')}>
            <Activity size={16} /> <span>Code health</span>
          </a>
          <a className="navigation-link" href="#changes" onClick={() => setActiveView('overview')}>
            <GitBranch size={16} /> <span>Changes</span>
          </a>
          <button className={`navigation-link ${activeView === 'memory' ? 'is-current' : ''}`} type="button" onClick={() => setActiveView('memory')} aria-current={activeView === 'memory' ? 'page' : undefined}>
            <Brain size={16} /> <span>Engineering memory</span>
            <small>Records</small>
          </button>

          <span className="sidebar-eyebrow navigation-upcoming-label">Additional capabilities</span>
          <button className={`navigation-link explorer-navigation-link ${activeView === 'explorer' ? 'is-current' : ''}`} type="button" onClick={() => setActiveView('explorer')} aria-label="Repository explorer" aria-current={activeView === 'explorer' ? 'page' : undefined}>
            <FolderGit2 size={16} /> <span>Repository explorer</span>
            <small>Read only</small>
          </button>
          <button className={`navigation-link ${activeView === 'investigations' ? 'is-current' : ''}`} type="button" onClick={() => setActiveView('investigations')} aria-current={activeView === 'investigations' ? 'page' : undefined}>
            <Brain size={16} /> <span>Investigations</span>
            <small>History</small>
          </button>
          <button className={`navigation-link ${activeView === 'tools' ? 'is-current' : ''}`} type="button" onClick={() => setActiveView('tools')} aria-current={activeView === 'tools' ? 'page' : undefined}>
            <Terminal size={16} /> <span>Tools</span>
            <small>Connected</small>
          </button>
        </nav>

        <div className="sidebar-footer">
          <span className="read-only-indicator"><span /> Read-only overview</span>
          <span>Repository facts come from the connected API.</span>
        </div>
      </aside>

      <div className="workspace-main-column">
        <header className="workspace-topbar">
          <div className="topbar-label">
            <span className="topbar-kicker">Engineering workspace</span>
            <span className="topbar-title">{activeView === 'overview' ? 'Repository overview' : activeView === 'explorer' ? 'Repository explorer' : activeView === 'investigations' ? 'Investigations' : activeView === 'memory' ? 'Engineering memory' : 'Tooling & capabilities'}</span>
          </div>
          <div className="topbar-repository" title={repositoryPath}>
            <FolderGit2 size={15} />
            <span>{repositoryName}</span>
          </div>
        </header>

        <main className="workspace-main" id={activeView === 'overview' ? 'overview' : undefined}>
          <div className="workspace-content">
            {activeView === 'overview' && <div className="page-heading">
              <div>
                <span className="page-eyebrow">Maintained engineering state</span>
                <h1>Repository overview</h1>
                <p>Understand the repository, its current changes, and the evidence the agent has retained.</p>
              </div>
            </div>}

            <div className="repository-picker-region">
              <ProjectSelector currentPath={repoPath} loading={loading} onInspect={handleInspect} />
            </div>

            {error && (
              <ErrorBanner error={error} onRetry={() => handleInspect(repoPath, false)} />
            )}

            {activeView === 'overview' && loading && !data && <LoadingSkeleton />}

            {activeView === 'explorer' && <RepositoryExplorer key={data?.identity.repo_path ?? 'no-repository'} repository={data?.identity ?? null} />}

            {activeView === 'investigations' && <InvestigationWorkspace key={data?.identity.repo_path ?? 'no-repository'} repository={data?.identity ?? null} />}

            {activeView === 'memory' && <EngineeringMemoryWorkspace key={data?.identity.repo_path ?? 'no-repository'} repository={data?.identity ?? null} />}
            {activeView === 'tools' && <ToolsWorkspace key={data?.identity.repo_path ?? 'no-repository'} repository={data?.identity ?? (repoPath ? { repo_id: repoPath, repo_name: repositoryName, repo_path: repositoryPath } : null)} />}

            {activeView === 'overview' && data && (
              <div className="overview-content">
                <StaleWarningBanner incremental={data.incremental} memory={data.memory} />

                <section className="workspace-section" id="repository-context" aria-labelledby="repository-context-title">
                  <div className="workspace-section-heading">
                    <div>
                      <span className="section-kicker">Identity and project shape</span>
                      <h2 id="repository-context-title">Repository context</h2>
                    </div>
                    <p>What this repository contains, based on stored discovery evidence.</p>
                  </div>
                  <div className="workspace-grid">
                    <RepositoryIdentityCard identity={data.identity} profile={data.profile} />
                    <GitStatusCard git={data.git} />
                  </div>
                </section>

                <section className="workspace-section" id="code-health" aria-labelledby="code-health-title">
                  <div className="workspace-section-heading">
                    <div>
                      <span className="section-kicker">Assessment and evidence</span>
                      <h2 id="code-health-title">Engineering health</h2>
                    </div>
                    <p>Inferred project stage and deterministic diagnostics, when requested.</p>
                  </div>
                  <AssessmentCard
                    stage={data.stage}
                    health={data.health}
                    status={data.assessment_status}
                    message={data.assessment_message}
                    onRunAssessment={handleRunAssessment}
                    loadingAssessment={loadingAssessment}
                  />
                </section>

                <div className="workspace-grid workspace-section" id="changes-memory">
                  <section id="changes" aria-labelledby="changes-title">
                    <div className="workspace-section-heading compact-section-heading">
                      <div>
                        <span className="section-kicker">Repository evolution</span>
                        <h2 id="changes-title">Changes</h2>
                      </div>
                    </div>
                    <IncrementalIntelligenceCard incremental={data.incremental} />
                  </section>
                  <section id="engineering-memory" aria-labelledby="memory-title">
                    <div className="workspace-section-heading compact-section-heading">
                      <div>
                        <span className="section-kicker">Persisted context</span>
                        <h2 id="memory-title">Engineering memory</h2>
                      </div>
                    </div>
                    <EngineeringMemoryCard memory={data.memory} />
                  </section>
                </div>
              </div>
            )}

            {activeView === 'overview' && !data && !loading && !error && (
              <div className="card empty-state-card">
                <div className="empty-icon-circle"><FolderGit2 size={30} /></div>
                <h2 className="empty-title">Inspect a repository to begin</h2>
                <p className="empty-desc">
                  Enter a local repository path above to load its identity, Git state, incremental changes, and persisted engineering memory.
                </p>
                <button type="button" onClick={() => handleInspect('.', false)} className="btn btn-primary">
                  Inspect current workspace
                </button>
              </div>
            )}
          </div>
        </main>

        <footer className="workspace-footer">
          <span>Evidence-backed overview</span>
          <span>Filesystem and Git remain the source of repository facts</span>
        </footer>
      </div>
    </div>
  )
}

export default App
