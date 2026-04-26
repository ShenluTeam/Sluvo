<template>
  <aside class="canvas-tool-rail" aria-label="画布工具" @click.stop>
    <button
      class="rail-button rail-button--primary magnetic-target"
      type="button"
      title="添加节点"
      data-tooltip="添加节点"
      @click="$emit('open-add-menu', $event)"
    >
      <Plus :size="28" />
    </button>

    <button
      class="rail-button"
      :class="{ 'is-active': activePanel === 'toolbox' }"
      type="button"
      title="我的工具箱"
      data-tooltip="我的工具箱"
      @click="$emit('open-toolbox')"
    >
      <Waypoints :size="23" />
    </button>
    <button
      class="rail-button"
      :class="{ 'is-active': activePanel === 'assets' }"
      type="button"
      title="我的素材"
      data-tooltip="我的素材"
      @click="$emit('open-assets')"
    >
      <Shapes :size="23" />
    </button>
    <button
      class="rail-button"
      :class="{ 'is-active': activePanel === 'history' }"
      type="button"
      title="历史记录"
      data-tooltip="历史记录"
      @click="$emit('open-history')"
    >
      <Clock3 :size="23" />
    </button>

    <span class="rail-separator" />

    <button
      class="rail-button"
      :class="{ 'is-active': helpVisible }"
      type="button"
      title="帮助"
      data-tooltip="帮助"
      @click="$emit('toggle-help')"
    >
      <CircleHelp :size="23" />
    </button>
    <button class="rail-button" type="button" title="支持" data-tooltip="支持" @click="$emit('support')">
      <Headphones :size="23" />
    </button>
  </aside>
</template>

<script setup>
import { CircleHelp, Clock3, Headphones, Plus, Shapes, Waypoints } from 'lucide-vue-next'

defineProps({
  canUndo: {
    type: Boolean,
    default: false
  },
  helpVisible: {
    type: Boolean,
    default: false
  },
  activePanel: {
    type: String,
    default: ''
  }
})

defineEmits(['open-add-menu', 'open-toolbox', 'open-assets', 'open-history', 'toggle-help', 'support'])
</script>
