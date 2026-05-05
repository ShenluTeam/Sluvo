<template>
  <div class="add-node-menu" :class="`add-node-menu--${variant}`" :style="menuStyle">
    <p class="add-node-menu__title">{{ title }}</p>

    <button
      v-for="item in filteredNodeItems"
      :key="item.id"
      class="add-node-menu__item"
      :class="{ 'is-disabled': isDisabled(item) }"
      type="button"
      :disabled="isDisabled(item)"
      :title="item.description"
      @pointerdown.stop
      @pointerup.stop
      @click.stop.prevent="handleSelect(item)"
      @keydown.enter.stop.prevent="handleSelect(item)"
      @keydown.space.stop.prevent="handleSelect(item)"
    >
      <span class="add-node-menu__icon">
        <component :is="item.icon" :size="26" />
      </span>
      <span class="add-node-menu__copy">
        <span class="add-node-menu__label-row">
          <span class="add-node-menu__label">{{ item.label }}</span>
          <small v-if="item.badge">{{ item.badge }}</small>
        </span>
        <span class="add-node-menu__description">{{ item.description }}</span>
      </span>
    </button>

    <p v-if="showResources" class="add-node-menu__title add-node-menu__title--resource">添加资源</p>

    <button
      v-if="showResources"
      v-for="item in resourceItems"
      :key="item.id"
      class="add-node-menu__item"
      :class="{ 'is-disabled': isDisabled(item) }"
      type="button"
      :disabled="isDisabled(item)"
      :title="item.description"
      @pointerdown.stop
      @pointerup.stop
      @click.stop.prevent="handleSelect(item)"
      @keydown.enter.stop.prevent="handleSelect(item)"
      @keydown.space.stop.prevent="handleSelect(item)"
    >
      <span class="add-node-menu__icon">
        <component :is="item.icon" :size="26" />
      </span>
      <span class="add-node-menu__copy">
        <span class="add-node-menu__label-row">
          <span class="add-node-menu__label">{{ item.label }}</span>
        </span>
        <span class="add-node-menu__description">{{ item.description }}</span>
      </span>
    </button>
  </div>
</template>

<script setup>
import { computed } from 'vue'
import { AudioLines, Bot, Clapperboard, FileText, ImagePlus, Library, Scissors, Upload, Video } from 'lucide-vue-next'

const props = defineProps({
  position: {
    type: Object,
    required: true
  },
  title: {
    type: String,
    default: '添加节点'
  },
  variant: {
    type: String,
    default: 'default'
  },
  showResources: {
    type: Boolean,
    default: true
  },
  disabledItems: {
    type: Array,
    default: () => []
  },
  allowedItems: {
    type: Array,
    default: () => []
  },
  onSelect: {
    type: Function,
    default: null
  }
})

const emit = defineEmits(['select-node'])

const nodeItems = [
  {
    id: 'text',
    label: '文本',
    description: '剧本、广告词、品牌文案',
    type: 'prompt_note',
    icon: FileText,
    patch: { title: '文本节点', kindLabel: '文本', numberedTitle: true }
  },
  {
    id: 'image',
    label: '图片',
    description: '海报、分镜、角色设计',
    type: 'image_unit',
    icon: ImagePlus,
    patch: { title: '图片节点', kindLabel: '图片', numberedTitle: true }
  },
  {
    id: 'video',
    label: '视频',
    description: '创意广告、动画、电影',
    type: 'video_unit',
    icon: Video,
    patch: { title: '视频节点', kindLabel: '视频', numberedTitle: true }
  },
  {
    id: 'compose',
    label: '视频合成',
    description: '多个视频片段合为一个',
    type: 'media_board',
    icon: Scissors,
    badge: 'Beta',
    patch: { title: '视频合成节点', kindLabel: '合成', numberedTitle: true }
  },
  {
    id: 'audio',
    label: '音频',
    description: '音效、配音、音乐',
    type: 'audio_unit',
    icon: AudioLines,
    patch: { title: '音频节点', kindLabel: '音频', numberedTitle: true }
  },
  {
    id: 'script',
    label: '脚本',
    description: '创意脚本、生成故事板',
    type: 'script_episode',
    icon: Clapperboard,
    badge: 'Beta',
    patch: { title: '脚本节点', kindLabel: '脚本', numberedTitle: true }
  },
  {
    id: 'agent',
    label: 'Agent',
    description: '读取上下文并提出画布改动',
    type: 'agent_node',
    icon: Bot,
    badge: 'Beta',
    patch: { title: 'Agent 节点', kindLabel: 'Agent', numberedTitle: true }
  }
]

const resourceItems = [
  {
    id: 'upload',
    label: '上传',
    description: '可上传图片、视频、音频文件',
    type: 'asset_table',
    icon: Upload,
    patch: { title: '上传资源节点', kindLabel: '资源', numberedTitle: true }
  },
  {
    id: 'library',
    label: '从图库选择',
    description: '从历史生成中选择素材',
    type: 'asset_table',
    icon: Library,
    patch: { title: '历史素材节点', kindLabel: '素材', numberedTitle: true }
  }
]

const retiredNodeItemIds = new Set(['compose', 'script'])
const availableNodeItems = computed(() => nodeItems.filter((item) => !retiredNodeItemIds.has(item.id)))
const menuStyle = computed(() => ({
  left: `${props.position.x}px`,
  top: `${props.position.y}px`
}))

const filteredNodeItems = computed(() => {
  if (!props.allowedItems.length) return availableNodeItems.value
  return availableNodeItems.value.filter((item) => props.allowedItems.includes(item.id) || props.allowedItems.includes(item.type))
})

let lastSelect = { id: '', at: 0 }

function isDisabled(item) {
  return props.disabledItems.includes(item.id) || props.disabledItems.includes(item.type)
}

function handleSelect(item) {
  if (isDisabled(item)) return
  const now = window.performance.now()
  if (lastSelect.id === item.id && now - lastSelect.at < 260) return
  lastSelect = { id: item.id, at: now }
  if (props.onSelect) {
    props.onSelect(item)
    return
  }
  emit('select-node', item)
}
</script>
