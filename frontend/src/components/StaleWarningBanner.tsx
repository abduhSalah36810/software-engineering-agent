import { ShieldAlert } from 'lucide-react'
import type { IncrementalStatusSummary, MemoryValiditySummary } from '../types/api'

interface StaleWarningBannerProps {
  incremental: IncrementalStatusSummary
  memory: MemoryValiditySummary
}

export function StaleWarningBanner({
  incremental,
  memory,
}: StaleWarningBannerProps) {
  const isStale = incremental.is_baseline_stale
  const requiresReverification = incremental.requires_reverification
  const reqVerCount = memory.requires_verification_count

  if (!isStale && !requiresReverification && reqVerCount === 0 && !memory.stale_baseline_warning) {
    return null
  }

  return (
    <div className="alert-banner warning-banner" role="alert">
      <div className="alert-banner-icon">
        <ShieldAlert size={20} className="text-amber" />
      </div>
      <div className="alert-banner-content">
        <h4 className="alert-banner-title">Maintained Engineering State Requires Verification</h4>
        <p className="alert-banner-desc">
          {isStale && (
            <span>
              <strong>Stale Baseline Detected:</strong> Stored historical commit anchor cannot be verified or reached from current repository HEAD history.{' '}
            </span>
          )}
          {requiresReverification && !isStale && (
            <span>
              <strong>Re-verification Required:</strong> Significant repository structure or history changes require engineering re-understanding.{' '}
            </span>
          )}
          {reqVerCount > 0 && (
            <span>
              <strong>{reqVerCount} memory record(s)</strong> (decisions or bug investigations) are marked <code>REQUIRES_VERIFICATION</code> due to touched engineering dimensions.
            </span>
          )}
        </p>
      </div>
    </div>
  )
}
