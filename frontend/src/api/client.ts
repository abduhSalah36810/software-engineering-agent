import type {
  ApiErrorResponse,
  EngineeringMemoryResponse,
  InvestigationListResponse,
  ProjectOverviewResponse,
  RepositoryDirectoryResponse,
  RepositoryFileResponse,
  ToolListResponse,
  ToolExecutionResponse,
} from '../types/api'

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL || ''

export class ApiError extends Error {
  errorCode: string
  statusCode: number
  detail: string

  constructor(errorCode: string, detail: string, statusCode: number) {
    super(detail)
    this.name = 'ApiError'
    this.errorCode = errorCode
    this.detail = detail
    this.statusCode = statusCode
  }
}

export async function fetchProjectOverview(
  repoPath: string,
  includeAssessment: boolean = false
): Promise<ProjectOverviewResponse> {
  const params = new URLSearchParams({
    repo_path: repoPath.trim(),
    include_assessment: String(includeAssessment),
  })

  const url = `${API_BASE_URL}/api/project/overview?${params.toString()}`

  let response: Response
  try {
    response = await fetch(url, {
      method: 'GET',
      headers: {
        Accept: 'application/json',
      },
    })
  } catch {
    throw new ApiError(
      'network_error',
      'Cannot connect to backend agent server. Ensure FastAPI is running on http://localhost:8000.',
      0
    )
  }

  if (!response.ok) {
    let errData: ApiErrorResponse | null = null
    try {
      errData = await response.json()
    } catch {
      // Fallback if response is not JSON
    }

    const errorCode = errData?.error || `http_${response.status}`
    const detail =
      errData?.detail ||
      `API error (HTTP ${response.status}): ${response.statusText || 'Unexpected server error'}`
    throw new ApiError(errorCode, detail, response.status)
  }

  return response.json()
}

async function fetchApiJson<T>(url: string, signal?: AbortSignal): Promise<T> {
  let response: Response
  try {
    response = await fetch(url, {
      method: 'GET',
      headers: { Accept: 'application/json' },
      signal,
    })
  } catch (error) {
    if (signal?.aborted) throw error
    throw new ApiError(
      'network_error',
      'Cannot connect to backend agent server. Ensure FastAPI is running on http://localhost:8000.',
      0,
    )
  }

  if (!response.ok) {
    let errData: ApiErrorResponse | null = null
    try {
      errData = await response.json()
    } catch {
      // Use the status text when the backend did not return a JSON error.
    }
    throw new ApiError(
      errData?.error || `http_${response.status}`,
      errData?.detail || `API error (HTTP ${response.status}): ${response.statusText || 'Unexpected server error'}`,
      response.status,
    )
  }

  return response.json() as Promise<T>
}

export function fetchRepositoryDirectory(
  repoPath: string,
  relativePath: string,
  offset: number,
  signal?: AbortSignal,
): Promise<RepositoryDirectoryResponse> {
  const params = new URLSearchParams({
    repo_path: repoPath,
    relative_path: relativePath,
    offset: String(offset),
  })
  return fetchApiJson<RepositoryDirectoryResponse>(
    `${API_BASE_URL}/api/project/tree?${params.toString()}`,
    signal,
  )
}

export function fetchRepositoryFile(
  repoPath: string,
  filePath: string,
  signal?: AbortSignal,
): Promise<RepositoryFileResponse> {
  const params = new URLSearchParams({ repo_path: repoPath, file_path: filePath })
  return fetchApiJson<RepositoryFileResponse>(
    `${API_BASE_URL}/api/project/file?${params.toString()}`,
    signal,
  )
}

export function fetchInvestigations(
  repoPath: string,
  signal?: AbortSignal,
): Promise<InvestigationListResponse> {
  const params = new URLSearchParams({ repo_path: repoPath, limit: '100' })
  return fetchApiJson<InvestigationListResponse>(
    `${API_BASE_URL}/api/project/investigations?${params.toString()}`,
    signal,
  )
}

export function fetchEngineeringMemory(
  repoPath: string,
  signal?: AbortSignal,
): Promise<EngineeringMemoryResponse> {
  const params = new URLSearchParams({ repo_path: repoPath, change_limit: '100' })
  return fetchApiJson<EngineeringMemoryResponse>(
    `${API_BASE_URL}/api/project/memory?${params.toString()}`,
    signal,
  )
}

export function fetchRegisteredTools(
  repoPath: string,
  signal?: AbortSignal,
): Promise<ToolListResponse> {
  const params = new URLSearchParams({ repo_path: repoPath })
  return fetchApiJson<ToolListResponse>(
    `${API_BASE_URL}/api/project/tools?${params.toString()}`,
    signal,
  )
}

export async function executeTool(
  repoPath: string,
  toolName: string,
  operation: string,
  args: Record<string, any> = {},
  signal?: AbortSignal,
): Promise<ToolExecutionResponse> {
  let response: Response
  try {
    response = await fetch(`${API_BASE_URL}/api/project/tools/execute`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        Accept: 'application/json',
      },
      body: JSON.stringify({
        repo_path: repoPath,
        tool_name: toolName,
        operation,
        arguments: args,
      }),
      signal,
    })
  } catch (error) {
    if (signal?.aborted) throw error
    throw new ApiError(
      'network_error',
      'Cannot connect to backend agent server.',
      0,
    )
  }

  if (!response.ok) {
    let errData: any = null
    try {
      errData = await response.json()
    } catch {}
    throw new ApiError(
      errData?.error || `http_${response.status}`,
      errData?.detail || `API error (HTTP ${response.status})`,
      response.status,
    )
  }

  return response.json() as Promise<ToolExecutionResponse>
}
