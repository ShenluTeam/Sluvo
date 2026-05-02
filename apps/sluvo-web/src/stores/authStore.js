import { computed, ref } from 'vue'
import { defineStore } from 'pinia'
import { fetchCurrentUser, loginWithPassword } from '../api/authApi'

const TOKEN_KEY = 'shenlu_token'
const NICKNAME_KEY = 'shenlu_nickname'
const EMAIL_KEY = 'shenlu_email'

export const useAuthStore = defineStore('auth', () => {
  const token = ref(readStorage(TOKEN_KEY))
  const user = ref(null)
  const loadingUser = ref(false)
  const error = ref('')

  const isAuthenticated = computed(() => Boolean(token.value))
  const displayName = computed(() => {
    const current = user.value || {}
    return current.nickname || current.name || current.username || current.email || readStorage(NICKNAME_KEY) || readStorage(EMAIL_KEY) || 'Sluvo Creator'
  })
  const userInitial = computed(() => displayName.value.trim().slice(0, 1).toUpperCase() || 'S')

  function syncFromStorage() {
    token.value = readStorage(TOKEN_KEY)
  }

  async function login(credentials, { rememberEmail = true } = {}) {
    error.value = ''
    const payload = await loginWithPassword(credentials)
    token.value = payload.token || ''
    user.value = normalizeUserPayload(payload)
    window.localStorage.setItem(TOKEN_KEY, token.value)
    window.localStorage.setItem(NICKNAME_KEY, payload.nickname || payload.name || '神鹿创作者')
    if (rememberEmail) {
      window.localStorage.setItem(EMAIL_KEY, payload.email || credentials.email || '')
    } else {
      window.localStorage.removeItem(EMAIL_KEY)
    }
    return payload
  }

  async function refreshUser() {
    if (!token.value) return null
    loadingUser.value = true
    error.value = ''
    try {
      const payload = await fetchCurrentUser()
      user.value = normalizeUserPayload(payload)
      if (user.value?.nickname || user.value?.name || user.value?.username) {
        window.localStorage.setItem(NICKNAME_KEY, user.value.nickname || user.value.name || user.value.username)
      }
      if (user.value?.email) {
        window.localStorage.setItem(EMAIL_KEY, user.value.email)
      }
      return user.value
    } catch (err) {
      if (err?.status === 401) logout()
      error.value = err instanceof Error ? err.message : '用户信息加载失败'
      return null
    } finally {
      loadingUser.value = false
    }
  }

  function logout() {
    token.value = ''
    user.value = null
    window.localStorage.removeItem(TOKEN_KEY)
    window.localStorage.removeItem(NICKNAME_KEY)
  }

  return {
    token,
    user,
    loadingUser,
    error,
    isAuthenticated,
    displayName,
    userInitial,
    syncFromStorage,
    login,
    refreshUser,
    logout
  }
})

function normalizeUserPayload(payload) {
  return payload?.user || payload?.data || payload || null
}

function readStorage(key) {
  return window.localStorage.getItem(key) || ''
}
