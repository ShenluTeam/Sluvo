import { apiFetch, ApiError } from './client'

export class SluvoRevisionConflictError extends ApiError {
  constructor(message, payload = null) {
    super(message || '画布已在其他地方更新', {
      status: 409,
      payload
    })
    this.name = 'SluvoRevisionConflictError'
  }
}

function wrapSluvoError(error) {
  if (error?.status === 409) {
    throw new SluvoRevisionConflictError(error.message, error.payload)
  }
  throw error
}

export async function fetchSluvoProjects({ includeArchived = false } = {}) {
  const query = includeArchived ? '?includeArchived=true' : ''
  const payload = await apiFetch(`/api/sluvo/projects${query}`)
  return Array.isArray(payload?.items) ? payload.items : []
}

export function createSluvoProject(payload) {
  return apiFetch('/api/sluvo/projects', {
    method: 'POST',
    body: JSON.stringify(payload)
  })
}

export function fetchSluvoProject(projectId) {
  return apiFetch(`/api/sluvo/projects/${projectId}`)
}

export function updateSluvoProject(projectId, payload) {
  return apiFetch(`/api/sluvo/projects/${projectId}`, {
    method: 'PATCH',
    body: JSON.stringify(payload)
  })
}

export function deleteSluvoProject(projectId) {
  return apiFetch(`/api/sluvo/projects/${projectId}`, {
    method: 'DELETE'
  })
}

export function fetchSluvoProjectCanvas(projectId) {
  return apiFetch(`/api/sluvo/projects/${projectId}/canvas`)
}

export async function saveSluvoCanvasBatch(canvasId, payload) {
  try {
    return await apiFetch(`/api/sluvo/canvases/${canvasId}/batch`, {
      method: 'POST',
      body: JSON.stringify(payload),
      timeout: 35000
    })
  } catch (error) {
    wrapSluvoError(error)
  }
}
