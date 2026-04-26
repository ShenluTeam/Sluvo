<template>
  <header class="libtv-topbar" @click.stop>
    <div class="libtv-topbar__left">
      <div class="libtv-logo-mark" />
      <strong class="libtv-logo-text">Sluvo</strong>
      <span class="libtv-divider" />
      <span class="libtv-project-title">{{ title }}</span>
    </div>

    <div class="libtv-topbar__right">
      <button class="top-pill top-pill--skills" type="button">Sluvo Skills</button>
      <button class="top-icon-button" type="button" aria-label="保存">
        <Save :size="20" />
      </button>
      <button class="top-icon-button" type="button" aria-label="分享">
        <Share2 :size="20" />
      </button>
      <button class="top-icon-button top-icon-button--notice" type="button" aria-label="通知">
        <Bell :size="20" />
      </button>
      <button class="top-pill top-pill--cyan" type="button">
        <Store :size="20" />
        会员超市
      </button>
      <button class="top-pill top-pill--member" type="button">
        <span class="top-pill__sale">限时 39 折</span>
        <Gem :size="19" />
        会员特惠39折
        <Zap :size="15" />
        100
      </button>
      <button class="top-avatar" type="button" aria-label="账户">S</button>
    </div>
  </header>
</template>

<script setup>
import { Bell, Gem, Save, Share2, Store, Zap } from 'lucide-vue-next'

defineProps({
  title: {
    type: String,
    default: '未命名'
  }
})
</script>
