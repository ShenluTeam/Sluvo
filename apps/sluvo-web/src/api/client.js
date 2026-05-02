const API_BASE = (import.meta.env.VITE_API_BASE || '').replace(/\/$/, '')
const API_TIMEOUT_MS = 25000

export class ApiError extends Error {
  constructor(message, { status = 0, payload = null } = {}) {
    super(message)
    this.name = 'ApiError'
    this.status = status
    this.payload = payload
  }
}

export function buildApiUrl(path) {
  const normalizedPath = path.startsWith('/') ? path : `/${path}`
  return `${API_BASE}${normalizedPath}`
}

export async function apiFetch(path, options = {}) {
  const token = window.localStorage.getItem('shenlu_token') || ''
  const controller = new AbortController()
  const timeoutId = window.setTimeout(() => controller.abort(), options.timeout || API_TIMEOUT_MS)
  const headers = {
    ...(options.headers || {})
  }

  if (token) {
    headers.Authorization = `Bearer ${token}`
  }

  if (!(options.body instanceof FormData)) {
    headers['Content-Type'] = headers['Content-Type'] || 'application/json'
  }

  let response
  try {
    response = await fetch(buildApiUrl(path), {
      ...options,
      headers,
      signal: options.signal || controller.signal
    })
  } catch (error) {
    if (error?.name === 'AbortError') {
      throw new Error('API 连接超时，请检查网络或稍后重试')
    }
    throw error
  } finally {
    window.clearTimeout(timeoutId)
  }

  const contentType = response.headers.get('content-type') || ''
  const payload = contentType.includes('application/json')
    ? await response.json()
    : await response.text()

  if (!response.ok) {
    const detail = typeof payload === 'object' && payload !== null ? payload.detail || payload.message || payload.error : ''
    const fallbackMessage =
      response.status === 401
        ? '未登录或登录已过期，请先登录'
        : response.status === 403
          ? '当前账号没有权限执行此操作'
          : response.status === 500
            ? 'API 服务暂时异常，或本地代理目标未正确配置'
            : `API request failed: ${response.status}`
    const message = Array.isArray(detail)
      ? detail.map((item) => item?.msg || item?.message || String(item)).join('; ')
      : detail || fallbackMessage
    throw new ApiError(message, {
      status: response.status,
      payload
    })
  }

  return payload
}
