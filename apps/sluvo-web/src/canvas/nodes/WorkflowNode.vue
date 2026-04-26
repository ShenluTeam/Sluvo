<template>
  <div
    class="workflow-node"
    :class="[
      `workflow-node--${data.nodeType}`,
      { 'workflow-node--group': data.kind === 'group', 'workflow-node--collapsed': data.collapsed }
    ]"
    :style="{ '--node-accent': data.accent }"
  >
    <template v-if="data.kind === 'group'">
      <div class="workflow-node__group-title">
        <span>{{ data.icon }}</span>
        <strong>{{ data.title }}</strong>
      </div>
      <p>{{ data.body }}</p>
    </template>

    <template v-else>
      <div class="workflow-node__caption">
        <component :is="nodeConfig.icon" :size="18" />
        <span>{{ data.title }}</span>
      </div>

      <section class="workflow-node__frame">
        <Handle id="in" class="workflow-node__handle workflow-node__handle--in" type="target" :position="Position.Left" />

        <div class="workflow-node__hero" :class="`workflow-node__hero--${nodeConfig.hero}`">
          <component :is="nodeConfig.icon" v-if="nodeConfig.hero !== 'text'" :size="58" />
          <span v-else class="workflow-node__text-lines" />
        </div>

        <div class="workflow-node__try">尝试:</div>

        <div class="workflow-node__suggestions">
          <button
            v-for="item in nodeConfig.suggestions"
            :key="item.label"
            class="workflow-node__suggestion nodrag"
            :class="{ 'is-active': data.action === item.label }"
            type="button"
            @click.stop="applySuggestion(item)"
          >
            <component :is="item.icon" :size="18" />
            <span>{{ item.label }}</span>
          </button>
        </div>

        <Handle id="out" class="workflow-node__handle workflow-node__handle--out" type="source" :position="Position.Right" />
      </section>

      <section v-if="!data.collapsed" class="workflow-node__composer nodrag">
        <div v-if="nodeConfig.chips.length" class="workflow-node__chips">
          <button v-for="chip in nodeConfig.chips" :key="chip" type="button">{{ chip }}</button>
        </div>

        <p>{{ nodeConfig.prompt }}</p>

        <div v-if="data.status === 'running'" class="workflow-node__active-action">
          已选择：{{ data.action }}
        </div>

        <div class="workflow-node__composer-footer">
          <span>{{ nodeConfig.model }}</span>
          <button type="button" @click.stop="applySuggestion(nodeConfig.suggestions[0])">
            <ArrowUp :size="18" />
          </button>
        </div>
      </section>
    </template>
  </div>
</template>

<script setup>
import { computed } from 'vue'
import {
  ArrowUp,
  AudioLines,
  Clapperboard,
  FileText,
  Image,
  ImageUp,
  Library,
  Music,
  Scissors,
  Sparkles,
  Upload,
  Video
} from 'lucide-vue-next'
import { Handle, Position } from '@vue-flow/core'

const props = defineProps({
  id: {
    type: String,
    required: true
  },
  data: {
    type: Object,
    required: true
  }
})

const configs = {
  prompt_note: {
    icon: FileText,
    hero: 'text',
    prompt: '写下你想讲的故事、场景或角色设定。例如：一个来自未来的机器人，在城市屋顶看星星。',
    model: 'GVLM 3.1',
    chips: [],
    suggestions: [
      { label: '自己编写内容', icon: FileText },
      { label: '文生视频', icon: Video },
      { label: '图片反推提示词', icon: Image },
      { label: '文字生音乐', icon: Music }
    ]
  },
  image_unit: {
    icon: Image,
    hero: 'image',
    prompt: '描述你想要生成的画面内容，按 / 呼出指令，@ 引用素材',
    model: 'Lib Nano Pro · 16:9 · 2K',
    chips: ['风格', '标记', '聚焦'],
    suggestions: [
      { label: '图生图', icon: ImageUp },
      { label: '图片高清', icon: Sparkles }
    ]
  },
  video_unit: {
    icon: Video,
    hero: 'video',
    prompt: '描述镜头运动、角色动作和画面节奏，也可以引用图片或文本节点。',
    model: 'Lib Video · 5s',
    chips: ['镜头', '节奏', '首帧'],
    suggestions: [
      { label: '文生视频', icon: FileText },
      { label: '图生视频', icon: Image },
      { label: '首尾帧生成', icon: Video }
    ]
  },
  audio_unit: {
    icon: AudioLines,
    hero: 'audio',
    prompt: '描述音效、配音语气或音乐氛围，生成可给视频复用的声音素材。',
    model: 'Lib Audio · 44.1k',
    chips: ['音色', '时长', '氛围'],
    suggestions: [
      { label: '音效', icon: AudioLines },
      { label: '配音', icon: FileText },
      { label: '音乐', icon: Music }
    ]
  },
  script_episode: {
    icon: Clapperboard,
    hero: 'script',
    prompt: '输入创意方向，生成故事脚本、分镜节拍和可继续连线的创作链路。',
    model: 'Story Pilot',
    chips: ['结构', '角色', '分镜'],
    suggestions: [
      { label: '创意脚本', icon: FileText },
      { label: '生成故事板', icon: Clapperboard },
      { label: '分镜拆解', icon: Video }
    ]
  },
  asset_table: {
    icon: Upload,
    hero: 'asset',
    prompt: '上传图片、视频、音频文件，或整理角色、场景、道具等参考素材。',
    model: 'Asset Library',
    chips: ['图片', '视频', '音频'],
    suggestions: [
      { label: '上传图片', icon: Upload },
      { label: '上传视频', icon: Video },
      { label: '上传音频', icon: AudioLines }
    ]
  },
  storyboard_table: {
    icon: Clapperboard,
    hero: 'script',
    prompt: '把脚本拆成镜头表，继续生成画面或视频片段。',
    model: 'Storyboard',
    chips: ['镜号', '景别', '运动'],
    suggestions: [
      { label: '生成分镜', icon: Clapperboard },
      { label: '生成首帧', icon: Image },
      { label: '生成视频', icon: Video }
    ]
  },
  media_board: {
    icon: Scissors,
    hero: 'compose',
    prompt: '选择历史素材或多个视频片段，合成为一个可预览的结果。',
    model: 'Media Board',
    chips: ['片段', '排序', '导出'],
    suggestions: [
      { label: '合并片段', icon: Scissors },
      { label: '从历史选择', icon: Library },
      { label: '导出预览', icon: Video }
    ]
  }
}

const nodeConfig = computed(() => configs[props.data.nodeType] || configs.prompt_note)

function applySuggestion(item) {
  props.data.status = 'running'
  props.data.action = item.label
  props.data.body = `已选择「${item.label}」，可以继续输入提示词或从右侧加号连出下游节点。`
}
</script>
