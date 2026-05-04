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

export function fetchCaptcha() {
  return apiFetch('/api/captcha')
}

export function sendEmailCode({ email, captchaId, captchaCode }) {
  return apiFetch('/api/auth/send-email-code', {
    method: 'POST',
    body: JSON.stringify({
      email,
      captcha_id: captchaId,
      captcha_code: captchaCode
    })
  })
}

export function registerWithEmail({ email, password, emailCode, nickname }) {
  return apiFetch('/api/auth/register', {
    method: 'POST',
    body: JSON.stringify({
      email,
      password,
      email_code: emailCode,
      nickname: nickname || null
    })
  })
}

export function fetchCurrentUser() {
  return apiFetch('/api/user/me')
}

export function fetchUserDashboard() {
  return apiFetch('/api/user/dashboard')
}
