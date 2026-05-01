import { apiFetch } from './client'

export function loginWithPassword({ email, password }) {
  return apiFetch('/api/auth/login', {
    method: 'POST',
    body: JSON.stringify({
      email,
      password
    })
  })
}

export function fetchCurrentUser() {
  return apiFetch('/api/user/me')
}

export function fetchUserDashboard() {
  return apiFetch('/api/user/dashboard')
}
