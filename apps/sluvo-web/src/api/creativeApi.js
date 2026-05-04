import { apiFetch } from './client'

export function fetchCreativeImageCatalog() {
  return apiFetch('/api/creative/images/catalog')
}

export function fetchCreativeVideoCatalog() {
  return apiFetch('/api/creative/videos/catalog')
}

export function fetchCreativeAudioCatalog() {
  return apiFetch('/api/creative/audio/catalog')
}

export function fetchCreativeVoiceAssets() {
  return apiFetch('/api/creative/voice-assets')
}

export function submitCreativeImage(payload) {
  return apiFetch('/api/creative/images', {
    method: 'POST',
    body: JSON.stringify(payload)
  })
}

export function estimateCreativeVideo(payload) {
  return apiFetch('/api/creative/videos/estimate', {
    method: 'POST',
    body: JSON.stringify(payload)
  })
}

export function submitCreativeVideo(payload) {
  return apiFetch('/api/creative/videos', {
    method: 'POST',
    body: JSON.stringify(payload)
  })
}

export function estimateCreativeAudio(payload) {
  return apiFetch('/api/creative/audio/estimate', {
    method: 'POST',
    body: JSON.stringify(payload)
  })
}

export function submitCreativeAudio(payload) {
  return apiFetch('/api/creative/audio/generate', {
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
