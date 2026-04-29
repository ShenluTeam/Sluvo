<template>
  <section class="starter-strip">
    <div class="starter-strip__hint">
      <MousePointer2 :size="22" />
      <span>双击画布，自由生成节点</span>
    </div>

    <div class="starter-strip__cards">
      <button
        v-for="card in cards"
        :key="card.id"
        class="starter-card"
        :class="`starter-card--${card.id}`"
        type="button"
        @click="$emit('select-node', card.type)"
      >
        <component :is="card.icon" v-if="card.icon" :size="30" />
        <strong>{{ card.title }}</strong>
        <span class="starter-card__art" />
      </button>
    </div>
  </section>
</template>

<script setup>
import { Music2, MousePointer2 } from 'lucide-vue-next'

defineEmits(['select-node'])

const cards = [
  { id: 'story', title: '故事脚本生成', type: 'script_episode' },
  { id: 'character', title: '角色三视图', type: 'asset_table' },
  { id: 'firstframe', title: '首帧图生视频', type: 'video_unit' },
  { id: 'audio', title: '音频生视频', type: 'audio_unit', icon: Music2 }
]
</script>
