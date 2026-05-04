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

        <div class="login-nav__actions">
          <button class="login-nav__ghost" type="button" @click="toggleAuthMode">
            <component :is="isRegisterMode ? LogIn : UserPlus" :size="16" />
            {{ isRegisterMode ? '账号登录' : '注册账号' }}
          </button>
          <button class="login-nav__ghost" type="button" @click="goHome">
            <ArrowLeft :size="16" />
            返回首页
          </button>
        </div>
      </nav>

      <div class="login-hero__content">
        <p class="login-eyebrow">
          <Sparkles :size="16" />
          Creator Access
        </p>
        <h1>{{ isRegisterMode ? '注册 Sluvo' : '登录 Sluvo' }}</h1>
        <p class="login-copy">
          {{ isRegisterMode ? '创建神鹿账号，领取创作空间并开始搭建你的第一条生成链路。' : '进入无限画布，继续管理剧本、角色、分镜和生成任务。' }}
        </p>
      </div>

      <div class="login-particles" aria-hidden="true">
        <span v-for="dot in particleDots" :key="dot" />
      </div>

      <div class="login-signal" aria-hidden="true">
        <div class="signal-orbit">
          <span />
          <i />
        </div>
        <span class="signal-line signal-line--one" />
        <span class="signal-line signal-line--two" />
        <span class="signal-line signal-line--three" />
        <span class="signal-node signal-node--script">Script</span>
        <span class="signal-node signal-node--asset">Asset</span>
        <span class="signal-node signal-node--video">Video</span>
        <span class="signal-node signal-node--image">Image</span>
      </div>
    </section>

    <section class="login-panel" :aria-label="isRegisterMode ? '注册表单' : '登录表单'">
      <div class="login-card">
        <div class="login-panel__heading">
          <span class="login-panel__mark">
            <component :is="isRegisterMode ? UserPlus : LockKeyhole" :size="22" />
          </span>
          <div>
            <h2>{{ isRegisterMode ? '账号注册' : '账号登录' }}</h2>
            <p>{{ isRegisterMode ? '使用邮箱创建你的 Sluvo 账号' : '使用神鹿账号进入 Sluvo' }}</p>
          </div>
        </div>

        <form v-if="!isRegisterMode" class="login-form" @submit.prevent="submitLogin">
          <label class="field">
            <span>邮箱</span>
            <div class="field-control">
              <Mail :size="19" />
              <input
                v-model.trim="form.email"
                autocomplete="off"
                autocapitalize="none"
                autocorrect="off"
                spellcheck="false"
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
              <LockKeyhole :size="19" />
              <input
                v-model="form.password"
                :type="showPassword ? 'text' : 'password'"
                autocomplete="current-password"
                autocapitalize="none"
                autocorrect="off"
                spellcheck="false"
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
                <component :is="showPassword ? EyeOff : Eye" :size="18" />
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
            <LoaderCircle v-if="isSubmitting" class="spin" :size="19" />
            <LogIn v-else :size="19" />
            {{ isSubmitting ? '登录中' : '登录并进入 Sluvo' }}
          </button>

          <button class="secondary-button" type="button" @click="goRegister">
            <UserPlus :size="18" />
            没有账号，立即注册
          </button>
        </form>

        <form v-else class="login-form register-form" @submit.prevent="submitRegister">
          <label class="field">
            <span>邮箱</span>
            <div class="field-control">
              <Mail :size="19" />
              <input
                v-model.trim="registerForm.email"
                autocomplete="email"
                autocapitalize="none"
                autocorrect="off"
                spellcheck="false"
                name="register-email"
                placeholder="name@shenlu.top"
                type="email"
                required
              />
            </div>
          </label>

          <label class="field">
            <span>昵称</span>
            <div class="field-control">
              <UserRound :size="19" />
              <input
                v-model.trim="registerForm.nickname"
                autocomplete="nickname"
                name="nickname"
                placeholder="可选"
                type="text"
              />
            </div>
          </label>

          <label class="field">
            <span>密码</span>
            <div class="field-control">
              <LockKeyhole :size="19" />
              <input
                v-model="registerForm.password"
                :type="showRegisterPassword ? 'text' : 'password'"
                autocomplete="new-password"
                autocapitalize="none"
                autocorrect="off"
                spellcheck="false"
                name="register-password"
                placeholder="设置登录密码"
                required
              />
              <button
                class="password-toggle"
                type="button"
                :aria-label="showRegisterPassword ? '隐藏密码' : '显示密码'"
                @click="showRegisterPassword = !showRegisterPassword"
              >
                <component :is="showRegisterPassword ? EyeOff : Eye" :size="18" />
              </button>
            </div>
          </label>

          <label class="field">
            <span>确认密码</span>
            <div class="field-control">
              <LockKeyhole :size="19" />
              <input
                v-model="registerForm.confirmPassword"
                :type="showRegisterPassword ? 'text' : 'password'"
                autocomplete="new-password"
                autocapitalize="none"
                autocorrect="off"
                spellcheck="false"
                name="register-confirm-password"
                placeholder="再次输入密码"
                required
              />
            </div>
          </label>

          <label class="field">
            <span>图形验证码</span>
            <div class="captcha-control">
              <div class="field-control">
                <ShieldCheck :size="19" />
                <input
                  v-model.trim="registerForm.captchaCode"
                  autocomplete="off"
                  autocapitalize="characters"
                  autocorrect="off"
                  spellcheck="false"
                  name="captcha-code"
                  placeholder="输入图形码"
                  type="text"
                  required
                />
              </div>
              <button
                class="captcha-image"
                type="button"
                title="刷新图形验证码"
                :disabled="isLoadingCaptcha"
                @click="loadCaptcha"
              >
                <LoaderCircle v-if="isLoadingCaptcha" class="spin" :size="18" />
                <img v-else-if="registerForm.captchaImage" :src="registerForm.captchaImage" alt="" />
                <RefreshCw v-else :size="18" />
              </button>
            </div>
          </label>

          <label class="field">
            <span>邮箱验证码</span>
            <div class="code-control">
              <div class="field-control">
                <BadgeCheck :size="19" />
                <input
                  v-model.trim="registerForm.emailCode"
                  autocomplete="one-time-code"
                  inputmode="numeric"
                  name="email-code"
                  placeholder="6 位验证码"
                  type="text"
                  required
                />
              </div>
              <button class="code-button" type="button" :disabled="!canSendCode" @click="requestEmailCode">
                <LoaderCircle v-if="isSendingCode" class="spin" :size="17" />
                <Mail v-else :size="17" />
                {{ codeCooldown > 0 ? `${codeCooldown}s` : '发送验证码' }}
              </button>
            </div>
          </label>

          <p v-if="feedback.message" class="feedback" :class="`is-${feedback.type}`">
            {{ feedback.message }}
          </p>

          <button class="submit-button" type="submit" :disabled="isSubmitting">
            <LoaderCircle v-if="isSubmitting" class="spin" :size="19" />
            <UserPlus v-else :size="19" />
            {{ isSubmitting ? '注册中' : '注册并进入 Sluvo' }}
          </button>

          <button class="secondary-button" type="button" @click="goLogin">
            <LogIn :size="18" />
            已有账号，返回登录
          </button>
        </form>

        <div class="login-card__meta">
          <span>Canvas workspace</span>
          <span>Model routing</span>
          <span>Task history</span>
        </div>
      </div>
    </section>
  </main>
</template>

<script setup>
import { computed, onBeforeUnmount, reactive, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import {
  ArrowLeft,
  BadgeCheck,
  Eye,
  EyeOff,
  LoaderCircle,
  LockKeyhole,
  LogIn,
  Mail,
  RefreshCw,
  ShieldCheck,
  Sparkles,
  UserPlus,
  UserRound
} from 'lucide-vue-next'
import { fetchCaptcha, registerWithEmail, sendEmailCode } from '../api/authApi'
import { useAuthStore } from '../stores/authStore'
import logoUrl from '../../LOGO.png'

const router = useRouter()
const route = useRoute()
const authStore = useAuthStore()

const form = reactive({
  email: window.localStorage.getItem('shenlu_email') || '',
  password: ''
})
const registerForm = reactive({
  email: window.localStorage.getItem('shenlu_email') || '',
  nickname: '',
  password: '',
  confirmPassword: '',
  captchaId: '',
  captchaCode: '',
  captchaImage: '',
  emailCode: ''
})
const rememberAccount = ref(Boolean(form.email))
const showPassword = ref(false)
const showRegisterPassword = ref(false)
const isSubmitting = ref(false)
const isLoadingCaptcha = ref(false)
const isSendingCode = ref(false)
const codeCooldown = ref(0)
let cooldownTimer = 0
const feedback = reactive({
  type: 'idle',
  message: ''
})
const particleDots = Array.from({ length: 24 }, (_, index) => index)
const isRegisterMode = computed(() => route.name === 'register')
const canSendCode = computed(() => (
  Boolean(registerForm.email && registerForm.captchaCode && registerForm.captchaId)
  && !isSendingCode.value
  && codeCooldown.value === 0
))

const redirectPath = computed(() => {
  const target = typeof route.query.redirect === 'string' ? route.query.redirect : '/'
  if (!target.startsWith('/') || target.startsWith('//')) {
    return '/'
  }
  return target
})

watch(isRegisterMode, (active) => {
  feedback.message = ''
  if (active) {
    registerForm.email = registerForm.email || form.email
    if (!registerForm.captchaImage) loadCaptcha()
  } else {
    form.email = form.email || registerForm.email
  }
}, { immediate: true })

onBeforeUnmount(() => {
  if (cooldownTimer) window.clearInterval(cooldownTimer)
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
    await authStore.login(
      {
        email: form.email,
        password: form.password
      },
      { rememberEmail: rememberAccount.value }
    )
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

async function requestEmailCode() {
  feedback.message = ''

  if (!registerForm.email || !registerForm.captchaCode || !registerForm.captchaId) {
    feedback.type = 'error'
    feedback.message = '请输入邮箱和图形验证码'
    return
  }

  isSendingCode.value = true
  try {
    await sendEmailCode({
      email: registerForm.email,
      captchaId: registerForm.captchaId,
      captchaCode: registerForm.captchaCode
    })
    feedback.type = 'success'
    feedback.message = '邮箱验证码已发送，请查收'
    startCodeCooldown()
  } catch (error) {
    feedback.type = 'error'
    feedback.message = error instanceof Error ? error.message : '验证码发送失败，请刷新后重试'
    await loadCaptcha()
  } finally {
    isSendingCode.value = false
  }
}

async function submitRegister() {
  feedback.message = ''

  if (!registerForm.email || !registerForm.password || !registerForm.confirmPassword || !registerForm.emailCode) {
    feedback.type = 'error'
    feedback.message = '请完整填写注册信息'
    return
  }

  if (registerForm.password.length < 6) {
    feedback.type = 'error'
    feedback.message = '密码至少需要 6 位'
    return
  }

  if (registerForm.password !== registerForm.confirmPassword) {
    feedback.type = 'error'
    feedback.message = '两次输入的密码不一致'
    return
  }

  isSubmitting.value = true
  try {
    await registerWithEmail({
      email: registerForm.email,
      password: registerForm.password,
      emailCode: registerForm.emailCode,
      nickname: registerForm.nickname
    })
    await authStore.login(
      {
        email: registerForm.email,
        password: registerForm.password
      },
      { rememberEmail: true }
    )
    feedback.type = 'success'
    feedback.message = '注册成功，正在进入工作台'
    await router.replace(redirectPath.value)
  } catch (error) {
    feedback.type = 'error'
    feedback.message = error instanceof Error ? error.message : '注册失败，请稍后重试'
  } finally {
    isSubmitting.value = false
  }
}

async function loadCaptcha() {
  isLoadingCaptcha.value = true
  try {
    const payload = await fetchCaptcha()
    registerForm.captchaId = payload.captcha_id || payload.captchaId || ''
    registerForm.captchaImage = payload.image || ''
    registerForm.captchaCode = ''
  } catch (error) {
    feedback.type = 'error'
    feedback.message = error instanceof Error ? error.message : '图形验证码加载失败'
  } finally {
    isLoadingCaptcha.value = false
  }
}

function startCodeCooldown() {
  codeCooldown.value = 60
  if (cooldownTimer) window.clearInterval(cooldownTimer)
  cooldownTimer = window.setInterval(() => {
    codeCooldown.value = Math.max(0, codeCooldown.value - 1)
    if (codeCooldown.value === 0 && cooldownTimer) {
      window.clearInterval(cooldownTimer)
      cooldownTimer = 0
    }
  }, 1000)
}

function goHome() {
  router.push('/')
}

function goRegister() {
  registerForm.email = registerForm.email || form.email
  router.push({ name: 'register', query: route.query })
}

function goLogin() {
  form.email = form.email || registerForm.email
  router.push({ name: 'login', query: route.query })
}

function toggleAuthMode() {
  if (isRegisterMode.value) {
    goLogin()
  } else {
    goRegister()
  }
}

function openReset() {
  window.open('https://ai.shenlu.top', '_blank', 'noopener,noreferrer')
}
</script>

<style scoped>
.login-shell {
  display: grid;
  grid-template-columns: minmax(0, 1fr) minmax(420px, 0.88fr);
  min-height: 100vh;
  background:
    radial-gradient(circle at 24% 22%, rgba(214, 181, 109, 0.16), transparent 28%),
    radial-gradient(circle at 76% 52%, rgba(255, 241, 199, 0.07), transparent 32%),
    linear-gradient(180deg, #050505 0%, #0d0b07 52%, #030303 100%);
  color: #f9f1dc;
}

.login-hero {
  position: relative;
  display: grid;
  grid-template-rows: auto 1fr minmax(260px, 34vh);
  min-height: 100vh;
  overflow: hidden;
  padding: 30px clamp(36px, 6vw, 92px) 64px;
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

.login-hero::after {
  position: absolute;
  inset: 0;
  background:
    linear-gradient(90deg, rgba(214, 181, 109, 0.1), transparent 34%),
    radial-gradient(ellipse at 34% 66%, rgba(214, 181, 109, 0.12), transparent 38%);
  content: "";
  pointer-events: none;
}

.login-nav,
.login-hero__content,
.login-particles,
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

.login-nav__actions {
  display: flex;
  align-items: center;
  justify-content: flex-end;
  gap: 10px;
}

.login-brand,
.login-nav__ghost,
.link-button,
.password-toggle,
.captcha-image,
.code-button,
.secondary-button {
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
  max-width: 720px;
  padding-top: clamp(54px, 10vh, 120px);
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
  max-width: 720px;
  margin: 0;
  color: #fff8e6;
  font-size: clamp(64px, 7.2vw, 112px);
  line-height: 0.95;
  letter-spacing: 0;
  text-shadow: 0 24px 60px rgba(0, 0, 0, 0.5);
}

.login-copy {
  max-width: 620px;
  margin: 22px 0 0;
  color: rgba(249, 241, 220, 0.68);
  font-size: 20px;
  line-height: 1.8;
}

.login-particles {
  position: absolute;
  inset: 0;
  overflow: hidden;
  pointer-events: none;
}

.login-particles span {
  position: absolute;
  width: 5px;
  height: 5px;
  border-radius: 999px;
  background: rgba(255, 232, 166, 0.72);
  box-shadow:
    0 0 16px rgba(214, 181, 109, 0.72),
    0 0 42px rgba(214, 181, 109, 0.28);
  animation: particleDrift 9s cubic-bezier(0.22, 0.8, 0.24, 1) infinite;
}

.login-particles span:nth-child(3n) {
  width: 7px;
  height: 7px;
  background: rgba(255, 246, 218, 0.86);
}

.login-particles span:nth-child(4n) {
  width: 3px;
  height: 3px;
  animation-duration: 11s;
}

.login-particles span:nth-child(1) { left: 12%; top: 18%; animation-delay: -0.2s; }
.login-particles span:nth-child(2) { left: 22%; top: 42%; animation-delay: -1.1s; }
.login-particles span:nth-child(3) { left: 32%; top: 28%; animation-delay: -2.4s; }
.login-particles span:nth-child(4) { left: 48%; top: 16%; animation-delay: -3.2s; }
.login-particles span:nth-child(5) { left: 58%; top: 48%; animation-delay: -4.1s; }
.login-particles span:nth-child(6) { left: 71%; top: 32%; animation-delay: -5.4s; }
.login-particles span:nth-child(7) { left: 18%; top: 72%; animation-delay: -6.1s; }
.login-particles span:nth-child(8) { left: 42%; top: 78%; animation-delay: -1.8s; }
.login-particles span:nth-child(9) { left: 64%; top: 70%; animation-delay: -2.9s; }
.login-particles span:nth-child(10) { left: 80%; top: 58%; animation-delay: -3.7s; }
.login-particles span:nth-child(11) { left: 8%; top: 52%; animation-delay: -4.7s; }
.login-particles span:nth-child(12) { left: 36%; top: 58%; animation-delay: -5.9s; }
.login-particles span:nth-child(13) { left: 54%; top: 24%; animation-delay: -0.9s; }
.login-particles span:nth-child(14) { left: 74%; top: 16%; animation-delay: -2.1s; }
.login-particles span:nth-child(15) { left: 86%; top: 36%; animation-delay: -3.4s; }
.login-particles span:nth-child(16) { left: 28%; top: 88%; animation-delay: -4.5s; }
.login-particles span:nth-child(17) { left: 52%; top: 88%; animation-delay: -5.7s; }
.login-particles span:nth-child(18) { left: 78%; top: 82%; animation-delay: -6.6s; }
.login-particles span:nth-child(19) { left: 16%; top: 30%; animation-delay: -0.5s; }
.login-particles span:nth-child(20) { left: 44%; top: 38%; animation-delay: -1.6s; }
.login-particles span:nth-child(21) { left: 68%; top: 44%; animation-delay: -2.6s; }
.login-particles span:nth-child(22) { left: 90%; top: 70%; animation-delay: -3.9s; }
.login-particles span:nth-child(23) { left: 6%; top: 84%; animation-delay: -5s; }
.login-particles span:nth-child(24) { left: 60%; top: 10%; animation-delay: -6.4s; }

.login-signal {
  align-self: end;
  width: min(860px, 100%);
  height: 350px;
  border-top: 1px solid rgba(255, 241, 199, 0.12);
}

.signal-orbit {
  position: absolute;
  right: 5%;
  top: -64px;
  width: 180px;
  height: 180px;
  border: 1px solid rgba(255, 241, 199, 0.1);
  border-radius: 50%;
  animation: orbitPulse 4.5s ease-in-out infinite;
}

.signal-orbit span,
.signal-orbit i {
  position: absolute;
  border-radius: 50%;
}

.signal-orbit span {
  inset: 42px;
  border: 1px solid rgba(214, 181, 109, 0.22);
}

.signal-orbit i {
  right: 28px;
  top: 54px;
  width: 18px;
  height: 18px;
  background: #d6b56d;
  box-shadow: 0 0 28px rgba(214, 181, 109, 0.58);
}

.signal-line,
.signal-node {
  position: absolute;
}

.signal-line {
  height: 2px;
  background: linear-gradient(90deg, transparent, rgba(214, 181, 109, 0.76), rgba(255, 241, 199, 0.38), transparent);
  box-shadow: 0 0 18px rgba(214, 181, 109, 0.2);
  animation: signalSweep 3.4s ease-in-out infinite;
}

.signal-line--one {
  left: 0;
  right: 10%;
  top: 100px;
}

.signal-line--two {
  left: 14%;
  right: 0;
  top: 182px;
  animation-delay: 480ms;
}

.signal-line--three {
  left: 7%;
  right: 18%;
  top: 268px;
  animation-delay: 920ms;
}

.signal-node {
  display: grid;
  place-items: center;
  min-width: 138px;
  min-height: 66px;
  padding: 0 24px;
  border: 1px solid rgba(255, 241, 199, 0.3);
  border-radius: 12px;
  background:
    linear-gradient(180deg, rgba(255, 241, 199, 0.1), rgba(214, 181, 109, 0.05)),
    rgba(15, 13, 10, 0.92);
  color: rgba(255, 248, 230, 0.94);
  font-size: 18px;
  font-weight: 900;
  box-shadow:
    inset 0 1px 0 rgba(255, 241, 199, 0.12),
    0 20px 52px rgba(0, 0, 0, 0.38),
    0 0 34px rgba(214, 181, 109, 0.13);
  animation: nodeFloat 4.8s ease-in-out infinite;
}

.signal-node--script {
  left: 8%;
  top: 72px;
}

.signal-node--asset {
  left: 38%;
  top: 154px;
  animation-delay: -1.2s;
}

.signal-node--video {
  right: 9%;
  top: 248px;
  animation-delay: -2.1s;
}

.signal-node--image {
  left: 16%;
  top: 252px;
  animation-delay: -3.1s;
}

.login-panel {
  display: grid;
  align-content: center;
  justify-items: center;
  min-width: 0;
  min-height: 100vh;
  padding: clamp(46px, 5.4vw, 92px);
  border-left: 1px solid rgba(255, 241, 199, 0.12);
  background:
    radial-gradient(circle at 50% 38%, rgba(214, 181, 109, 0.1), transparent 34%),
    rgba(8, 7, 5, 0.88);
  box-shadow: -28px 0 70px rgba(0, 0, 0, 0.32);
}

.login-card {
  width: min(100%, 760px);
  min-height: 85vh;
  display: grid;
  align-content: center;
  padding: clamp(56px, 5.2vw, 86px);
  border: 1px solid rgba(255, 241, 199, 0.18);
  border-radius: 20px;
  background:
    linear-gradient(180deg, rgba(255, 241, 199, 0.055), transparent 36%),
    rgba(18, 16, 12, 0.9);
  box-shadow:
    inset 0 1px 0 rgba(255, 241, 199, 0.1),
    0 34px 96px rgba(0, 0, 0, 0.5),
    0 0 90px rgba(214, 181, 109, 0.08),
    0 0 0 1px rgba(214, 181, 109, 0.05);
}

.login-panel__heading,
.login-form,
.login-card__meta {
  width: min(100%, 560px);
  justify-self: center;
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
  width: 58px;
  height: 58px;
  border: 1px solid rgba(214, 181, 109, 0.38);
  border-radius: 8px;
  background: rgba(214, 181, 109, 0.09);
  color: #fff1c7;
}

.login-panel h2 {
  margin: 0;
  color: #fff8e6;
  font-size: 42px;
  line-height: 1.2;
}

.login-panel p {
  margin: 7px 0 0;
  color: rgba(249, 241, 220, 0.54);
  font-size: 18px;
}

.login-form {
  display: grid;
  gap: 24px;
  margin-top: 42px;
}

.register-form {
  gap: 18px;
  margin-top: 34px;
}

.field {
  display: grid;
  gap: 10px;
}

.field > span,
.remember,
.link-button,
.code-button,
.secondary-button {
  color: rgba(249, 241, 220, 0.68);
  font-size: 16px;
  font-weight: 800;
}

.field-control {
  display: flex;
  align-items: center;
  gap: 16px;
  min-height: 76px;
  padding: 0 24px;
  border: 1px solid rgba(255, 241, 199, 0.14);
  border-radius: 8px;
  background: rgba(255, 255, 255, 0.045);
  color: rgba(255, 241, 199, 0.52);
  transition: border-color 160ms ease, background 160ms ease, box-shadow 160ms ease;
}

.field-control > svg {
  width: 22px;
  height: 22px;
  flex: 0 0 auto;
}

.field-control:focus-within {
  border-color: rgba(214, 181, 109, 0.66);
  background: rgba(214, 181, 109, 0.07);
  box-shadow: 0 0 0 3px rgba(214, 181, 109, 0.11);
}

.field-control input {
  min-width: 0;
  flex: 1;
  height: 100%;
  border: 0;
  outline: 0;
  background: transparent;
  color: #fff8e6;
  font: inherit;
  font-size: 22px;
  font-weight: 800;
  line-height: 1.2;
  letter-spacing: 0;
  caret-color: #fff1c7;
  appearance: none;
}

.field-control input:focus {
  font-size: 22px;
  font-weight: 800;
}

.field-control input::selection {
  background: rgba(214, 181, 109, 0.42);
  color: #fff8e6;
}

.field-control input:-webkit-autofill,
.field-control input:-webkit-autofill:hover,
.field-control input:-webkit-autofill:focus {
  border: 0;
  -webkit-text-fill-color: #fff8e6;
  caret-color: #fff1c7;
  box-shadow: 0 0 0 1000px rgba(28, 25, 18, 0.96) inset;
  font-size: 22px;
  font-weight: 800;
  transition: background-color 9999s ease-in-out 0s;
}

.field-control input::placeholder {
  color: rgba(249, 241, 220, 0.32);
  font-size: 20px;
  font-weight: 700;
}

.password-toggle {
  display: grid;
  place-items: center;
  width: 38px;
  height: 38px;
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

.captcha-control,
.code-control {
  display: grid;
  grid-template-columns: minmax(0, 1fr) auto;
  gap: 12px;
  align-items: stretch;
}

.captcha-image,
.code-button {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  min-height: 76px;
  border: 1px solid rgba(255, 241, 199, 0.14);
  border-radius: 8px;
  background: rgba(255, 255, 255, 0.045);
  color: rgba(255, 241, 199, 0.72);
  transition: border-color 160ms ease, background 160ms ease, color 160ms ease;
}

.captcha-image {
  width: 142px;
  overflow: hidden;
  padding: 0;
}

.captcha-image img {
  display: block;
  width: 100%;
  height: 100%;
  object-fit: cover;
}

.code-button {
  gap: 8px;
  min-width: 132px;
  padding: 0 16px;
  color: #d6b56d;
}

.captcha-image:hover:not(:disabled),
.code-button:hover:not(:disabled) {
  border-color: rgba(214, 181, 109, 0.5);
  background: rgba(214, 181, 109, 0.08);
  color: #fff1c7;
}

.captcha-image:disabled,
.code-button:disabled {
  cursor: wait;
  opacity: 0.58;
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
  min-height: 72px;
  border: 0;
  border-radius: 8px;
  background: linear-gradient(180deg, #fff1c7 0%, #d6b56d 48%, #a8742d 100%);
  color: #1c1307;
  font: inherit;
  font-size: 17px;
  font-weight: 950;
  cursor: pointer;
  box-shadow: 0 18px 38px rgba(214, 181, 109, 0.18);
  transition: transform 160ms ease, filter 160ms ease;
}

.secondary-button {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 9px;
  min-height: 54px;
  border: 1px solid rgba(255, 241, 199, 0.16);
  border-radius: 8px;
  background: rgba(255, 255, 255, 0.035);
  color: rgba(255, 248, 230, 0.78);
  transition: border-color 160ms ease, background 160ms ease, color 160ms ease;
}

.login-card__meta {
  display: flex;
  flex-wrap: wrap;
  gap: 12px;
  margin-top: 34px;
}

.login-card__meta span {
  min-height: 36px;
  padding: 0 15px;
  border: 1px solid rgba(255, 241, 199, 0.14);
  border-radius: 999px;
  color: rgba(249, 241, 220, 0.68);
  font-size: 15px;
  font-weight: 800;
  line-height: 36px;
}

.submit-button:hover:not(:disabled) {
  transform: translateY(-1px);
  filter: brightness(1.04);
}

.secondary-button:hover {
  border-color: rgba(214, 181, 109, 0.42);
  background: rgba(214, 181, 109, 0.08);
  color: #fff1c7;
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

@keyframes particleDrift {
  0% {
    opacity: 0;
    transform: translate3d(-12px, 68px, 0) scale(0.58);
  }

  20%,
  76% {
    opacity: 0.9;
  }

  100% {
    opacity: 0;
    transform: translate3d(42px, -150px, 0) scale(1.22);
  }
}

@keyframes nodeFloat {
  0%,
  100% {
    transform: translateY(0) scale(1);
  }

  50% {
    transform: translateY(-18px) scale(1.035);
  }
}

@keyframes orbitPulse {
  0%,
  100% {
    opacity: 0.52;
    transform: scale(0.96);
  }

  50% {
    opacity: 0.92;
    transform: scale(1.04);
  }
}

@keyframes spin {
  to {
    transform: rotate(360deg);
  }
}

@media (max-width: 1080px) {
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
    padding: clamp(22px, 6vw, 56px);
    border-left: 0;
    border-top: 1px solid rgba(255, 241, 199, 0.12);
    box-shadow: none;
  }

  .login-card {
    width: min(680px, 100%);
    padding: clamp(28px, 7vw, 56px);
    min-height: auto;
  }

  .login-panel h2 {
    font-size: clamp(28px, 7vw, 42px);
  }
}

@media (max-width: 520px) {
  .login-shell {
    min-height: 100dvh;
  }

  .login-nav {
    align-items: flex-start;
  }

  .login-nav__actions {
    flex-wrap: wrap;
    justify-content: flex-end;
  }

  .login-hero {
    grid-template-rows: auto auto minmax(92px, 20vh);
  }

  .login-hero__content {
    padding: 54px 0 28px;
  }

  .login-card {
    padding: 22px;
  }

  .login-panel__heading {
    align-items: flex-start;
  }

  .field-control {
    min-height: 60px;
    gap: 10px;
    padding: 0 14px;
  }

  .captcha-control,
  .code-control {
    grid-template-columns: 1fr;
  }

  .captcha-image,
  .code-button {
    width: 100%;
    min-height: 54px;
  }

  .field-control input,
  .field-control input:focus,
  .field-control input:-webkit-autofill,
  .field-control input:-webkit-autofill:hover,
  .field-control input:-webkit-autofill:focus {
    font-size: 17px;
  }

  .field-control input::placeholder {
    font-size: 16px;
  }

  .submit-button {
    min-height: 58px;
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
