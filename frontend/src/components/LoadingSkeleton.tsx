export function LoadingSkeleton() {
  return (
    <div className="skeleton-container" aria-busy="true" aria-label="Loading repository overview">
      <div className="skeleton-header pulse"></div>
      <div className="dashboard-grid">
        <div className="card skeleton-card pulse">
          <div className="skeleton-line skeleton-title"></div>
          <div className="skeleton-line skeleton-text"></div>
          <div className="skeleton-line skeleton-text"></div>
        </div>
        <div className="card skeleton-card pulse">
          <div className="skeleton-line skeleton-title"></div>
          <div className="skeleton-line skeleton-text"></div>
          <div className="skeleton-line skeleton-text"></div>
        </div>
      </div>
    </div>
  )
}
