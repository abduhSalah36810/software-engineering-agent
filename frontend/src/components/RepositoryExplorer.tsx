import { useCallback, useEffect, useRef, useState } from 'react'
import {
  AlertCircle,
  ArrowLeft,
  ChevronRight,
  FileCode2,
  FileText,
  Folder,
  FolderOpen,
  RefreshCw,
  ShieldAlert,
} from 'lucide-react'
import { ApiError, fetchRepositoryDirectory, fetchRepositoryFile } from '../api/client'
import type {
  RepositoryDirectoryResponse,
  RepositoryEntry,
  RepositoryFileResponse,
  RepoIdentitySummary,
} from '../types/api'

interface RepositoryExplorerProps {
  repository: RepoIdentitySummary | null
}

function formatFileSize(size: number | null) {
  if (size === null) return null
  if (size < 1024) return `${size} B`
  if (size < 1024 * 1024) return `${(size / 1024).toFixed(1)} KB`
  return `${(size / (1024 * 1024)).toFixed(1)} MB`
}

function errorMessage(error: Error) {
  return error instanceof ApiError ? error.detail : error.message
}

export function RepositoryExplorer({ repository }: RepositoryExplorerProps) {
  const repoPath = repository?.repo_path ?? null
  const [directoryPath, setDirectoryPath] = useState('.')
  const [directory, setDirectory] = useState<RepositoryDirectoryResponse | null>(null)
  const [directoryError, setDirectoryError] = useState<Error | null>(null)
  const [loadingDirectory, setLoadingDirectory] = useState(false)
  const [loadingMore, setLoadingMore] = useState(false)
  const [selectedEntry, setSelectedEntry] = useState<RepositoryEntry | null>(null)
  const [preview, setPreview] = useState<RepositoryFileResponse | null>(null)
  const [previewError, setPreviewError] = useState<Error | null>(null)
  const [loadingPreview, setLoadingPreview] = useState(false)

  const directoryRequestId = useRef(0)
  const previewRequestId = useRef(0)
  const directoryController = useRef<AbortController | null>(null)
  const previewController = useRef<AbortController | null>(null)

  const loadDirectory = useCallback(async (path: string, offset = 0, append = false) => {
    if (!repoPath) return
    const requestId = ++directoryRequestId.current
    directoryController.current?.abort()
    const controller = new AbortController()
    directoryController.current = controller

    setDirectoryPath(path)
    setDirectoryError(null)
    if (append) {
      setLoadingMore(true)
    } else {
      previewRequestId.current += 1
      previewController.current?.abort()
      setDirectory(null)
      setSelectedEntry(null)
      setPreview(null)
      setPreviewError(null)
      setLoadingPreview(false)
      setLoadingDirectory(true)
    }

    try {
      const result = await fetchRepositoryDirectory(repoPath, path, offset, controller.signal)
      if (requestId !== directoryRequestId.current) return
      setDirectory((current) => append && current?.relative_path === result.relative_path
        ? { ...result, entries: [...current.entries, ...result.entries] }
        : result)
      setDirectoryPath(result.relative_path)
    } catch (error) {
      if (controller.signal.aborted || requestId !== directoryRequestId.current) return
      setDirectoryError(error instanceof Error ? error : new Error(String(error)))
    } finally {
      if (requestId === directoryRequestId.current) {
        setLoadingDirectory(false)
        setLoadingMore(false)
      }
    }
  }, [repoPath])

  useEffect(() => {
    let active = true
    directoryRequestId.current += 1
    previewRequestId.current += 1
    directoryController.current?.abort()
    previewController.current?.abort()
    if (repoPath) {
      void Promise.resolve().then(() => {
        if (active) void loadDirectory('.')
      })
    }

    return () => {
      active = false
      directoryController.current?.abort()
      previewController.current?.abort()
    }
  }, [repoPath, loadDirectory])

  const selectFile = async (entry: RepositoryEntry) => {
    if (!repoPath || entry.kind !== 'file') return
    const requestId = ++previewRequestId.current
    previewController.current?.abort()
    const controller = new AbortController()
    previewController.current = controller
    setSelectedEntry(entry)
    setPreview(null)
    setPreviewError(null)
    setLoadingPreview(true)

    try {
      const result = await fetchRepositoryFile(repoPath, entry.relative_path, controller.signal)
      if (requestId !== previewRequestId.current) return
      setPreview(result)
    } catch (error) {
      if (controller.signal.aborted || requestId !== previewRequestId.current) return
      setPreviewError(error instanceof Error ? error : new Error(String(error)))
    } finally {
      if (requestId === previewRequestId.current) setLoadingPreview(false)
    }
  }

  const breadcrumbParts = directory?.relative_path && directory.relative_path !== '.'
    ? directory.relative_path.split('/')
    : []

  return (
    <section className="repository-explorer" aria-label="Repository explorer">
      <header className="explorer-page-header">
        <div>
          <span className="section-kicker">Repository structure</span>
          <h1>Repository explorer</h1>
          <p>Browse directories and inspect bounded text previews from the selected repository.</p>
        </div>
        {repository && (
          <div className="explorer-active-repository" title={repository.repo_path}>
            <FolderOpen size={15} />
            <span>{repository.repo_name}</span>
          </div>
        )}
      </header>

      {!repository ? (
        <div className="explorer-empty-state card">
          <Folder size={23} />
          <h2>Inspect a repository first</h2>
          <p>The explorer uses the canonical repository path returned by the overview API.</p>
        </div>
      ) : (
        <div className="explorer-workbench">
          <section className="explorer-browser-panel card" aria-label="Repository files">
            <div className="explorer-browser-heading">
              <div>
                <span className="section-kicker">Repository files</span>
                <h2>{directory?.relative_path ?? directoryPath}</h2>
              </div>
              <button
                type="button"
                className="btn btn-secondary btn-sm"
                onClick={() => void loadDirectory(directory?.relative_path ?? directoryPath)}
                disabled={loadingDirectory}
                aria-label="Refresh directory"
              >
                <RefreshCw size={14} className={loadingDirectory ? 'spinner' : ''} />
              </button>
            </div>

            <nav className="explorer-breadcrumbs" aria-label="Directory breadcrumbs">
              <button type="button" onClick={() => void loadDirectory('.')} aria-current={breadcrumbParts.length === 0 ? 'location' : undefined}>
                {repository.repo_name}
              </button>
              {breadcrumbParts.map((part, index) => {
                const path = breadcrumbParts.slice(0, index + 1).join('/')
                return (
                  <span className="explorer-breadcrumb-item" key={path}>
                    <ChevronRight size={13} aria-hidden="true" />
                    <button type="button" onClick={() => void loadDirectory(path)} aria-current={index === breadcrumbParts.length - 1 ? 'location' : undefined}>
                      {part}
                    </button>
                  </span>
                )
              })}
            </nav>

            {directory?.parent_path !== null && directory && (
              <button type="button" className="explorer-parent-button" onClick={() => void loadDirectory(directory.parent_path ?? '.')}>
                <ArrowLeft size={14} /> Parent directory
              </button>
            )}

            {directoryError && (
              <div className="explorer-inline-error" role="alert">
                <AlertCircle size={16} />
                <div>
                  <strong>Could not load this directory</strong>
                  <p>{errorMessage(directoryError)}</p>
                </div>
                <button type="button" className="btn-link" onClick={() => void loadDirectory(directoryPath)}>Retry</button>
              </div>
            )}

            {loadingDirectory && !directory && (
              <div className="explorer-loading" role="status"><RefreshCw size={15} className="spinner" /> Loading directory…</div>
            )}

            {directory && !directoryError && (
              <>
                <div className="explorer-list-summary">
                  {directory.total_entries} {directory.total_entries === 1 ? 'entry' : 'entries'}
                </div>
                {directory.entries.length === 0 ? (
                  <div className="explorer-directory-empty">
                    <Folder size={20} />
                    <span>This directory is empty.</span>
                  </div>
                ) : (
                  <ul className="explorer-entry-list">
                    {directory.entries.map((entry) => (
                      <li key={entry.relative_path}>
                        {entry.kind === 'directory' ? (
                          <button type="button" className="explorer-entry" onClick={() => void loadDirectory(entry.relative_path)}>
                            <Folder size={16} className="entry-folder-icon" />
                            <span className="explorer-entry-name">{entry.name}</span>
                            <ChevronRight size={14} className="entry-chevron" />
                            <span className="explorer-entry-meta">Folder</span>
                          </button>
                        ) : entry.kind === 'file' ? (
                          <button
                            type="button"
                            className={`explorer-entry ${selectedEntry?.relative_path === entry.relative_path ? 'is-selected' : ''}`}
                            onClick={() => void selectFile(entry)}
                            aria-pressed={selectedEntry?.relative_path === entry.relative_path}
                          >
                            <FileCode2 size={16} className="entry-file-icon" />
                            <span className="explorer-entry-name">{entry.name}</span>
                            <span className="explorer-entry-meta">{formatFileSize(entry.size_bytes)}</span>
                          </button>
                        ) : (
                          <div className="explorer-entry is-unavailable" title={entry.is_symlink ? 'Symbolic links are not followed' : 'This filesystem entry cannot be previewed'}>
                            {entry.kind === 'restricted' ? <ShieldAlert size={16} /> : <FileText size={16} />}
                            <span className="explorer-entry-name">{entry.name}</span>
                            <span className="explorer-entry-meta">{entry.kind === 'restricted' ? 'Restricted' : 'Unsupported'}</span>
                          </div>
                        )}
                      </li>
                    ))}
                  </ul>
                )}

                {directory.next_offset !== null && (
                  <button
                    type="button"
                    className="explorer-load-more"
                    onClick={() => void loadDirectory(directory.relative_path, directory.next_offset ?? 0, true)}
                    disabled={loadingMore}
                  >
                    {loadingMore ? 'Loading more…' : `Load more (${directory.entries.length} of ${directory.total_entries})`}
                  </button>
                )}
              </>
            )}
          </section>

          <section className="explorer-preview-panel card" aria-label="Selected file preview" aria-busy={loadingPreview}>
            {selectedEntry ? (
              <>
                <div className="explorer-preview-heading">
                  <div className="preview-file-icon"><FileCode2 size={17} /></div>
                  <div className="preview-file-title">
                    <h2>{selectedEntry.name}</h2>
                    <code>{selectedEntry.relative_path}</code>
                  </div>
                  {preview && <span className="badge badge-neutral">{formatFileSize(preview.size_bytes)}</span>}
                </div>
                {loadingPreview && <div className="explorer-preview-message" role="status"><RefreshCw size={15} className="spinner" /> Loading text preview…</div>}
                {previewError && (
                  <div className="explorer-preview-error" role="alert">
                    <AlertCircle size={17} />
                    <div>
                      <strong>Preview unavailable</strong>
                      <p>{errorMessage(previewError)}</p>
                    </div>
                    <button type="button" className="btn-link" onClick={() => void selectFile(selectedEntry)}>Retry</button>
                  </div>
                )}
                {preview && !loadingPreview && (
                  <>
                    <div className="preview-file-metadata">UTF-8 text · Modified {new Date(preview.modified_at).toLocaleString()}</div>
                    {preview.content.length === 0 ? (
                      <div className="explorer-preview-message">This file is empty.</div>
                    ) : (
                      <pre className="explorer-code-preview"><code>{preview.content}</code></pre>
                    )}
                  </>
                )}
              </>
            ) : (
              <div className="explorer-preview-empty">
                <FileText size={22} />
                <h2>Select a text file</h2>
                <p>Text previews are read-only and limited to 256 KiB. Binary, restricted, and oversized files cannot be opened.</p>
              </div>
            )}
          </section>
        </div>
      )}
    </section>
  )
}
