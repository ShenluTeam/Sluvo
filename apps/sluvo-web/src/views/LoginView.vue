<template>
  <main class="login-shell">
    <section class="login-panel">
      <span class="login-mark">S</span>
      <h1>神鹿账号登录</h1>
      <p>Sluvo 复用 Shenlu 登录态。正式登录页接入前，可设置 `localStorage.shenlu_token` 后回到首页查看工作台。</p>
      <button type="button" @click="router.push('/')">返回首页</button>
    </section>
  </main>
</template>

<script setup>
import { useRouter } from 'vue-router'

const router = useRouter()
</script>

<style scoped>
.login-shell {
  display: grid;
  min-height: 100vh;
  padding: 24px;
  background:
    radial-gradient(circle at 50% 0%, rgba(214, 181, 109, 0.18), transparent 34%),
    #050505;
  color: #f9f1dc;
  place-items: center;
}

.login-panel {
  display: grid;
  justify-items: center;
  gap: 16px;
  width: min(460px, 100%);
  padding: 34px;
  border: 1px solid rgba(214, 181, 109, 0.18);
  border-radius: 8px;
  background: rgba(13, 11, 7, 0.92);
  text-align: center;
}

.login-mark {
  display: grid;
  place-items: center;
  width: 48px;
  height: 48px;
  border: 1px solid rgba(255, 231, 164, 0.48);
  border-radius: 8px;
  color: #fff1c7;
  font-weight: 900;
}

.login-panel h1 {
  margin: 0;
  color: #fff8e6;
}

.login-panel p {
  margin: 0;
  color: rgba(249, 241, 220, 0.62);
  line-height: 1.7;
}

.login-panel button {
  min-height: 40px;
  padding: 0 16px;
  border-radius: 8px;
  background: linear-gradient(180deg, #f8d98e, #b88735);
  color: #1a1206;
  font-weight: 900;
}
</style>
