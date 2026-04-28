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
