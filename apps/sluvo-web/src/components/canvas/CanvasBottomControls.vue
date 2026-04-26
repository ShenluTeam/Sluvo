<template>
  <div class="canvas-bottom-controls" @click.stop>
    <button
      class="bottom-tool"
      :class="{ 'is-active': gridVisible }"
      type="button"
      title="显示/隐藏网格"
      @click="$emit('toggle-grid')"
    >
      <LayoutGrid :size="17" />
    </button>
    <button
      class="bottom-tool"
      :class="{ 'is-active': minimapVisible }"
      type="button"
      title="画布小地图"
      @click="$emit('toggle-minimap')"
    >
      <Map :size="17" />
    </button>
    <button class="bottom-tool" type="button" title="定位画布" @click="$emit('locate')">
      <MapPin :size="17" />
    </button>
    <button
      class="bottom-tool"
      :class="{ 'is-active': snapEnabled }"
      type="button"
      title="吸附网格"
      @click="$emit('toggle-snap')"
    >
      <Link2 :size="18" />
    </button>
    <button class="bottom-tool" type="button" title="缩小" @click="$emit('zoom-out')">
      <Minus :size="18" />
    </button>
    <span class="zoom-readout">{{ zoomLabel }}</span>
    <button class="bottom-tool" type="button" title="放大" @click="$emit('zoom-in')">
      <Plus :size="18" />
    </button>
  </div>
</template>

<script setup>
import { LayoutGrid, Link2, Map, MapPin, Minus, Plus } from 'lucide-vue-next'

defineProps({
  zoomLabel: {
    type: String,
    default: '100%'
  },
  gridVisible: {
    type: Boolean,
    default: true
  },
  snapEnabled: {
    type: Boolean,
    default: true
  },
  minimapVisible: {
    type: Boolean,
    default: true
  }
})

defineEmits(['toggle-grid', 'toggle-minimap', 'locate', 'toggle-snap', 'zoom-in', 'zoom-out'])
</script>
