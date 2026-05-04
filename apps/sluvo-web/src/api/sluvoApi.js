import { apiFetch, ApiError, buildApiUrl } from './client'

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

export async function fetchSluvoProjects({ includeArchived = false, includeDeleted = false } = {}) {
  const params = new URLSearchParams()
  if (includeArchived) params.set('includeArchived', 'true')
  if (includeDeleted) params.set('includeDeleted', 'true')
  const query = params.toString() ? `?${params.toString()}` : ''
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

export async function fetchSluvoCommunityCanvases({ limit = 12, sort = 'latest' } = {}) {
  const params = new URLSearchParams()
  params.set('limit', String(limit))
  if (sort) params.set('sort', sort)
  const payload = await apiFetch(`/api/sluvo/community/canvases?${params.toString()}`)
  return Array.isArray(payload?.items) ? payload.items : []
}

export function fetchSluvoCommunityCanvas(publicationId) {
  return apiFetch(`/api/sluvo/community/canvases/${publicationId}`)
}

export function publishSluvoProjectToCommunity(projectId, payload) {
  return apiFetch(`/api/sluvo/projects/${projectId}/community/publish`, {
    method: 'POST',
    body: JSON.stringify(payload)
  })
}

export function forkSluvoCommunityCanvas(publicationId) {
  return apiFetch(`/api/sluvo/community/canvases/${publicationId}/fork`, {
    method: 'POST'
  })
}

export function unpublishSluvoCommunityCanvas(publicationId) {
  return apiFetch(`/api/sluvo/community/canvases/${publicationId}/unpublish`, {
    method: 'POST'
  })
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

export function uploadSluvoCanvasAsset(canvasId, file, options = {}) {
  const threshold = options.base64Threshold || 5 * 1024 * 1024
  if (options.useBase64Upload || file.size <= threshold) {
    return uploadSluvoCanvasAssetBase64(canvasId, file, options)
  }
  return uploadSluvoCanvasAssetMultipart(canvasId, file, options)
}

async function uploadSluvoCanvasAssetBase64(canvasId, file, options = {}) {
  options.onProgress?.(18, '正在读取文件')
  const dataBase64 = await readFileAsDataUrl(file)
  options.onProgress?.(42, '正在提交到服务')
  let progress = 42
  const progressTimer = setInterval(() => {
    progress = Math.min(88, progress + (progress < 68 ? 8 : 3))
    options.onProgress?.(progress, '服务正在处理')
  }, 1400)
  try {
    const payload = await apiFetch(`/api/sluvo/canvases/${canvasId}/assets/upload/base64`, {
      method: 'POST',
      body: JSON.stringify({
        filename: file.name || 'upload.bin',
        contentType: file.type || 'application/octet-stream',
        dataBase64,
        mediaType: options.mediaType,
        nodeId: options.nodeId || null,
        width: options.width || null,
        height: options.height || null,
        durationSeconds: options.durationSeconds || null,
        metadata: options.metadata || {}
      }),
      timeout: options.timeout || 120000
    })
    options.onProgress?.(100, '上传成功')
    return payload
  } finally {
    clearInterval(progressTimer)
  }
}

function uploadSluvoCanvasAssetMultipart(canvasId, file, options = {}) {
  return new Promise((resolve, reject) => {
    const form = new FormData()
    form.append('file', file)
    if (options.mediaType) form.append('mediaType', options.mediaType)
    if (options.nodeId) form.append('nodeId', options.nodeId)
    if (options.width) form.append('width', String(options.width))
    if (options.height) form.append('height', String(options.height))
    if (options.durationSeconds) form.append('durationSeconds', String(options.durationSeconds))

    const xhr = new XMLHttpRequest()
    xhr.open('POST', buildApiUrl(`/api/sluvo/canvases/${canvasId}/assets/upload`))
    xhr.timeout = options.timeout || 120000
    const token = window.localStorage.getItem('shenlu_token') || ''
    if (token) xhr.setRequestHeader('Authorization', `Bearer ${token}`)
    xhr.upload.onprogress = (event) => {
      if (!event.lengthComputable) return
      const progress = Math.max(8, Math.min(96, Math.round((event.loaded / event.total) * 96)))
      options.onProgress?.(progress)
    }
    xhr.onload = () => {
      const payload = parseUploadResponse(xhr.responseText)
      if (xhr.status >= 200 && xhr.status < 300) {
        options.onProgress?.(100)
        resolve(payload)
        return
      }
      reject(new ApiError(extractUploadError(payload, xhr.status), { status: xhr.status, payload }))
    }
    xhr.onerror = () => reject(new ApiError('上传失败，请检查网络后重试', { status: 0 }))
    xhr.ontimeout = () => reject(new ApiError('上传处理超时，请稍后重试', { status: 0 }))
    xhr.onabort = () => reject(new ApiError('上传已取消', { status: 0 }))
    xhr.send(form)
  })
}

function readFileAsDataUrl(file) {
  return new Promise((resolve, reject) => {
    const reader = new FileReader()
    reader.onload = () => resolve(String(reader.result || ''))
    reader.onerror = () => reject(new ApiError('文件读取失败，请重试', { status: 0 }))
    reader.readAsDataURL(file)
  })
}

function parseUploadResponse(text) {
  if (!text) return {}
  try {
    return JSON.parse(text)
  } catch {
    return { message: text }
  }
}

function extractUploadError(payload, status) {
  const detail = payload?.detail || payload?.message || payload?.error
  if (Array.isArray(detail)) return detail.map((item) => item?.msg || item?.message || String(item)).join('; ')
  return detail || `上传失败：${status}`
}
