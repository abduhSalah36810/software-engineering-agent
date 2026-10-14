import { AlertCircle, ServerCrash, Ban, FileQuestion } from 'lucide-react'
import { ApiError } from '../api/client'

interface ErrorBannerProps {
  error: ApiError | Error
  onRetry?: () => void
}

export function ErrorBanner({ error, onRetry }: ErrorBannerProps) {
  const isApiError = error instanceof ApiError
  const errorCode = isApiError ? error.errorCode : 'unknown_error'
  const statusCode = isApiError ? error.statusCode : 500

  const getErrorIcon = () => {
    switch (errorCode) {
      case 'repo_not_found':
        return <FileQuestion size={20} className="text-danger" />
      case 'network_error':
        return <ServerCrash size={20} className="text-amber" />
      case 'access_denied':
        return <Ban size={20} className="text-danger" />
      default:
        return <AlertCircle size={20} className="text-danger" />
    }
  }

  const getErrorHeadline = () => {
    switch (errorCode) {
      case 'repo_not_found':
        return 'Repository Directory Not Found'
      case 'network_error':
        return 'Backend Agent Server Unavailable'
      case 'access_denied':
        return 'Filesystem Access Denied'
      case 'assessment_error':
        return 'Code Health Assessment Failed'
      default:
        return `Inspection Failed (${statusCode > 0 ? `HTTP ${statusCode}` : 'Network Error'})`
    }
  }

  return (
    <div className="alert-banner error-banner" role="alert">
      <div className="alert-banner-icon">{getErrorIcon()}</div>
      <div className="alert-banner-content">
        <h4 className="alert-banner-title">{getErrorHeadline()}</h4>
        <p className="alert-banner-desc">{error.message}</p>
        <div className="error-actions-row">
          <code className="text-xs monospace-chip">Code: {errorCode}</code>
          {onRetry && (
            <button type="button" onClick={onRetry} className="btn-retry">
              Retry Inspection
            </button>
          )}
        </div>
      </div>
    </div>
  )
}
