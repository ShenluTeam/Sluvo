import { apiFetch } from './client'

export function fetchCreativeImageCatalog() {
  return apiFetch('/api/creative/images/catalog')
}

export function submitCreativeImage(payload) {
  return apiFetch('/api/creative/images', {
    method: 'POST',
    body: JSON.stringify(payload)
  })
}

export function fetchCreativeRecord(recordId) {
  return apiFetch(`/api/creative/records/${recordId}`)
}

export function fetchCreativeRecords(params = {}) {
  const searchParams = new URLSearchParams()
  Object.entries(params).forEach(([key, value]) => {
    if (value !== undefined && value !== null && value !== '') searchParams.set(key, String(value))
  })
  const query = searchParams.toString()
  return apiFetch(`/api/creative/records${query ? `?${query}` : ''}`)
}

export function fetchTask(taskId) {
  return apiFetch(`/api/tasks/${taskId}`)
}
