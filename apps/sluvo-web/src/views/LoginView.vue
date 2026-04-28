<template>
  <main class="login-shell">
    <section class="login-hero" aria-label="Sluvo login">
      <nav class="login-nav">
        <button class="login-brand" type="button" @click="goHome">
          <span class="login-brand__mark">
            <img :src="logoUrl" alt="" />
          </span>
          <span>
            <strong>Sluvo</strong>
          </span>
        </button>

        <button class="login-nav__ghost" type="button" @click="goHome">
          <ArrowLeft :size="16" />
          返回首页
        </button>
      </nav>

      <div class="login-hero__content">
        <p class="login-eyebrow">
          <Sparkles :size="16" />
          Creator Access
        </p>
        <h1>登录 Sluvo</h1>
        <p class="login-copy">进入 Sluvo 无限画布，继续管理剧本、角色、分镜和生成任务。</p>
      </div>

      <div class="login-signal" aria-hidden="true">
        <span class="signal-line signal-line--one" />
        <span class="signal-line signal-line--two" />
        <span class="signal-line signal-line--three" />
        <span class="signal-node signal-node--script">Script</span>
        <span class="signal-node signal-node--asset">Asset</span>
        <span class="signal-node signal-node--video">Video</span>
      </div>
    </section>

    <section class="login-panel" aria-label="登录表单">
      <div class="login-panel__heading">
        <span class="login-panel__mark">
          <LockKeyhole :size="20" />
        </span>
        <div>
          <h2>账号登录</h2>
          <p>邮箱与密码</p>
        </div>
      </div>

      <form class="login-form" @submit.prevent="submitLogin">
        <label class="field">
          <span>邮箱</span>
          <div class="field-control">
            <Mail :size="18" />
            <input
              v-model.trim="form.email"
              autocomplete="email"
              name="email"
              placeholder="name@shenlu.top"
              type="email"
              required
            />
          </div>
        </label>

        <label class="field">
          <span>密码</span>
          <div class="field-control">
            <LockKeyhole :size="18" />
            <input
              v-model="form.password"
              :type="showPassword ? 'text' : 'password'"
              autocomplete="current-password"
              name="password"
              placeholder="输入密码"
              required
            />
            <button
              class="password-toggle"
              type="button"
              :aria-label="showPassword ? '隐藏密码' : '显示密码'"
              @click="showPassword = !showPassword"
            >
              <component :is="showPassword ? EyeOff : Eye" :size="17" />
            </button>
          </div>
        </label>

        <div class="login-row">
          <label class="remember">
            <input v-model="rememberAccount" type="checkbox" />
            <span>记住邮箱</span>
          </label>
          <button class="link-button" type="button" @click="openReset">忘记密码</button>
        </div>

        <p v-if="feedback.message" class="feedback" :class="`is-${feedback.type}`">
          {{ feedback.message }}
        </p>

        <button class="submit-button" type="submit" :disabled="isSubmitting">
          <LoaderCircle v-if="isSubmitting" class="spin" :size="18" />
          <LogIn v-else :size="18" />
          {{ isSubmitting ? '登录中' : '登录并进入 Sluvo' }}
        </button>
      </form>

    </section>
  </main>
</template>

<script setup>
import { computed, reactive, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import {
  ArrowLeft,
  Eye,
  EyeOff,
  LoaderCircle,
  LockKeyhole,
  LogIn,
  Mail,
  Sparkles
} from 'lucide-vue-next'
import { loginWithPassword } from '../api/authApi'
import logoUrl from '../../LOGO.png'

const router = useRouter()
const route = useRoute()

const form = reactive({
  email: window.localStorage.getItem('shenlu_email') || '',
  password: ''
})
const rememberAccount = ref(Boolean(form.email))
const showPassword = ref(false)
const isSubmitting = ref(false)
const feedback = reactive({
  type: 'idle',
  message: ''
})

const redirectPath = computed(() => {
  const target = typeof route.query.redirect === 'string' ? route.query.redirect : '/'
  if (!target.startsWith('/') || target.startsWith('//')) {
    return '/'
  }
  return target
})

async function submitLogin() {
  feedback.message = ''

  if (!form.email || !form.password) {
    feedback.type = 'error'
    feedback.message = '请输入邮箱和密码'
    return
  }

  isSubmitting.value = true
  try {
    const payload = await loginWithPassword({
      email: form.email,
      password: form.password
    })

    window.localStorage.setItem('shenlu_token', payload.token)
    window.localStorage.setItem('shenlu_nickname', payload.nickname || '神鹿创作者')

    if (rememberAccount.value) {
      window.localStorage.setItem('shenlu_email', payload.email || form.email)
    } else {
      window.localStorage.removeItem('shenlu_email')
    }

    feedback.type = 'success'
    feedback.message = '登录成功，正在进入工作台'
    await router.replace(redirectPath.value)
  } catch (error) {
    feedback.type = 'error'
    feedback.message = error instanceof Error ? error.message : '登录失败，请稍后重试'
  } finally {
    isSubmitting.value = false
  }
}

function goHome() {
  router.push('/')
}

function openReset() {
  window.open('https://ai.shenlu.top', '_blank', 'noopener,noreferrer')
}
</script>

<style scoped>
.login-shell {
  display: grid;
  grid-template-columns: minmax(0, 1fr) minmax(360px, 480px);
  min-height: 100vh;
  background:
    linear-gradient(115deg, rgba(214, 181, 109, 0.14), transparent 32%),
    linear-gradient(180deg, #050505 0%, #0d0b07 52%, #030303 100%);
  color: #f9f1dc;
}

.login-hero {
  position: relative;
  display: grid;
  min-height: 100vh;
  overflow: hidden;
  padding: 30px clamp(28px, 6vw, 86px) 56px;
}

.login-hero::before {
  position: absolute;
  inset: 0;
  background:
    linear-gradient(rgba(255, 241, 199, 0.035) 1px, transparent 1px),
    linear-gradient(90deg, rgba(255, 241, 199, 0.03) 1px, transparent 1px);
  background-size: 56px 56px;
  content: "";
  mask-image: linear-gradient(90deg, #000 0%, rgba(0, 0, 0, 0.62) 54%, transparent 100%);
}

.login-nav,
.login-hero__content,
.login-signal {
  position: relative;
  z-index: 1;
}

.login-nav {
  display: flex;
  align-items: center;
  justify-content: space-between;
  align-self: start;
  gap: 18px;
}

.login-brand,
.login-nav__ghost,
.link-button,
.password-toggle {
  border: 0;
  background: transparent;
  color: inherit;
  font: inherit;
  cursor: pointer;
}

.login-brand {
  display: inline-flex;
  align-items: center;
  gap: 12px;
  text-align: left;
}

.login-brand__mark {
  display: grid;
  place-items: center;
  width: 42px;
  height: 42px;
  overflow: hidden;
  padding: 2px;
  border: 1px solid rgba(255, 231, 164, 0.44);
  border-radius: 8px;
  background: linear-gradient(180deg, rgba(255, 241, 199, 0.16), rgba(214, 181, 109, 0.06));
  color: #fff1c7;
  font-weight: 900;
}

.login-brand__mark img {
  display: block;
  width: 100%;
  height: 100%;
  border-radius: 6px;
  object-fit: cover;
}

.login-brand strong,
.login-brand small {
  display: block;
}

.login-brand strong {
  color: #fff8e6;
  font-size: 18px;
  line-height: 1.1;
}

.login-brand small {
  margin-top: 3px;
  color: rgba(249, 241, 220, 0.52);
  font-size: 12px;
}

.login-nav__ghost {
  display: inline-flex;
  align-items: center;
  gap: 7px;
  min-height: 38px;
  padding: 0 13px;
  border: 1px solid rgba(255, 241, 199, 0.14);
  border-radius: 8px;
  background: rgba(255, 255, 255, 0.04);
  color: rgba(255, 248, 230, 0.76);
}

.login-hero__content {
  align-self: center;
  max-width: 650px;
  animation: loginRise 520ms ease both;
}

.login-eyebrow {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  margin: 0 0 18px;
  color: #d6b56d;
  font-weight: 800;
  letter-spacing: 0;
}

.login-hero h1 {
  max-width: 620px;
  margin: 0;
  color: #fff8e6;
  font-size: clamp(46px, 7vw, 88px);
  line-height: 0.95;
  letter-spacing: 0;
}

.login-copy {
  max-width: 520px;
  margin: 22px 0 0;
  color: rgba(249, 241, 220, 0.68);
  font-size: 18px;
  line-height: 1.8;
}

.login-signal {
  align-self: end;
  width: min(680px, 100%);
  height: 178px;
  border-top: 1px solid rgba(255, 241, 199, 0.12);
}

.signal-line,
.signal-node {
  position: absolute;
}

.signal-line {
  height: 1px;
  background: linear-gradient(90deg, transparent, rgba(214, 181, 109, 0.52), transparent);
  animation: signalSweep 3.8s ease-in-out infinite;
}

.signal-line--one {
  left: 0;
  right: 18%;
  top: 48px;
}

.signal-line--two {
  left: 18%;
  right: 0;
  top: 92px;
  animation-delay: 480ms;
}

.signal-line--three {
  left: 8%;
  right: 28%;
  top: 136px;
  animation-delay: 920ms;
}

.signal-node {
  display: grid;
  place-items: center;
  min-width: 82px;
  min-height: 38px;
  border: 1px solid rgba(255, 241, 199, 0.18);
  border-radius: 8px;
  background: rgba(12, 11, 8, 0.8);
  color: rgba(255, 248, 230, 0.74);
  font-size: 12px;
  font-weight: 900;
}

.signal-node--script {
  left: 9%;
  top: 28px;
}

.signal-node--asset {
  left: 43%;
  top: 72px;
}

.signal-node--video {
  right: 12%;
  top: 116px;
}

.login-panel {
  display: grid;
  align-content: center;
  gap: 26px;
  min-height: 100vh;
  padding: clamp(26px, 5vw, 54px);
  border-left: 1px solid rgba(255, 241, 199, 0.12);
  background: rgba(8, 7, 5, 0.86);
  box-shadow: -28px 0 70px rgba(0, 0, 0, 0.32);
}

.login-panel__heading {
  display: flex;
  align-items: center;
  gap: 14px;
}

.login-panel__mark {
  display: grid;
  flex: 0 0 auto;
  place-items: center;
  width: 44px;
  height: 44px;
  border: 1px solid rgba(214, 181, 109, 0.38);
  border-radius: 8px;
  background: rgba(214, 181, 109, 0.09);
  color: #fff1c7;
}

.login-panel h2 {
  margin: 0;
  color: #fff8e6;
  font-size: 26px;
  line-height: 1.2;
}

.login-panel p {
  margin: 5px 0 0;
  color: rgba(249, 241, 220, 0.54);
}

.login-form {
  display: grid;
  gap: 18px;
}

.field {
  display: grid;
  gap: 8px;
}

.field > span,
.remember,
.link-button {
  color: rgba(249, 241, 220, 0.68);
  font-size: 13px;
  font-weight: 800;
}

.field-control {
  display: flex;
  align-items: center;
  gap: 10px;
  min-height: 48px;
  padding: 0 12px;
  border: 1px solid rgba(255, 241, 199, 0.14);
  border-radius: 8px;
  background: rgba(255, 255, 255, 0.045);
  color: rgba(255, 241, 199, 0.52);
  transition: border-color 160ms ease, background 160ms ease, box-shadow 160ms ease;
}

.field-control:focus-within {
  border-color: rgba(214, 181, 109, 0.66);
  background: rgba(214, 181, 109, 0.07);
  box-shadow: 0 0 0 3px rgba(214, 181, 109, 0.11);
}

.field-control input {
  min-width: 0;
  flex: 1;
  border: 0;
  outline: 0;
  background: transparent;
  color: #fff8e6;
  font: inherit;
}

.field-control input::placeholder {
  color: rgba(249, 241, 220, 0.32);
}

.password-toggle {
  display: grid;
  place-items: center;
  width: 32px;
  height: 32px;
  border-radius: 8px;
  color: rgba(249, 241, 220, 0.62);
}

.password-toggle:hover {
  background: rgba(255, 255, 255, 0.06);
  color: #fff8e6;
}

.login-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 14px;
}

.remember {
  display: inline-flex;
  align-items: center;
  gap: 8px;
}

.remember input {
  width: 15px;
  height: 15px;
  accent-color: #d6b56d;
}

.link-button {
  color: #d6b56d;
}

.feedback {
  margin: 0;
  padding: 11px 12px;
  border-radius: 8px;
  font-size: 13px;
  line-height: 1.5;
}

.feedback.is-error {
  border: 1px solid rgba(255, 114, 114, 0.24);
  background: rgba(255, 114, 114, 0.08);
  color: #ffc0c0;
}

.feedback.is-success {
  border: 1px solid rgba(94, 211, 166, 0.26);
  background: rgba(94, 211, 166, 0.08);
  color: #b9f3dc;
}

.submit-button {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 9px;
  min-height: 50px;
  border: 0;
  border-radius: 8px;
  background: linear-gradient(180deg, #fff1c7 0%, #d6b56d 48%, #a8742d 100%);
  color: #1c1307;
  font: inherit;
  font-weight: 950;
  cursor: pointer;
  box-shadow: 0 18px 38px rgba(214, 181, 109, 0.18);
  transition: transform 160ms ease, filter 160ms ease;
}

.submit-button:hover:not(:disabled) {
  transform: translateY(-1px);
  filter: brightness(1.04);
}

.submit-button:disabled {
  cursor: wait;
  opacity: 0.72;
}

.spin {
  animation: spin 900ms linear infinite;
}

@keyframes loginRise {
  from {
    opacity: 0;
    transform: translateY(18px);
  }

  to {
    opacity: 1;
    transform: translateY(0);
  }
}

@keyframes signalSweep {
  0%,
  100% {
    opacity: 0.32;
    transform: translateX(-8px);
  }

  50% {
    opacity: 0.88;
    transform: translateX(10px);
  }
}

@keyframes spin {
  to {
    transform: rotate(360deg);
  }
}

@media (max-width: 880px) {
  .login-shell {
    grid-template-columns: 1fr;
  }

  .login-hero {
    min-height: auto;
    padding: 24px 20px 28px;
  }

  .login-hero__content {
    padding: 72px 0 38px;
  }

  .login-hero h1 {
    font-size: clamp(40px, 16vw, 62px);
  }

  .login-copy {
    font-size: 16px;
  }

  .login-signal {
    height: 126px;
  }

  .login-panel {
    min-height: auto;
    border-left: 0;
    border-top: 1px solid rgba(255, 241, 199, 0.12);
    box-shadow: none;
  }
}

@media (max-width: 520px) {
  .login-nav {
    align-items: flex-start;
  }

  .login-nav__ghost {
    width: 38px;
    padding: 0;
    justify-content: center;
  }

  .login-nav__ghost svg + * {
    display: none;
  }

  .login-row {
    align-items: flex-start;
    flex-direction: column;
  }

  .signal-node {
    min-width: 68px;
  }
}
</style>
