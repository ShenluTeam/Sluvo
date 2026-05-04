<template>
  <main class="community-page">
    <nav class="community-nav">
      <button class="community-brand" type="button" @click="goHome">
        <img :src="logoUrl" alt="" />
        <strong>Sluvo</strong>
      </button>
      <button type="button" @click="goHome">返回首页</button>
    </nav>

    <section v-if="loading" class="community-state">
      <Loader2 class="spin" :size="24" />
      正在打开社区画布
    </section>

    <section v-else-if="error" class="community-state community-state--error">
      <strong>{{ error }}</strong>
      <button type="button" @click="loadPublication">重试</button>
    </section>

    <template v-else-if="publication">
      <header class="community-hero">
        <span class="community-hero__cover">
          <img v-if="publication.coverUrl" :src="publication.coverUrl" :alt="publication.title" />
          <span v-else>开放画布</span>
        </span>
        <div>
          <span class="community-hero__eyebrow">开放画布社区</span>
          <h1>{{ publication.title }}</h1>
          <p>{{ publication.description || '这是一张可学习、可复用的社区画布。' }}</p>
          <div class="community-hero__meta">
            <span>{{ publication.author?.nickname || 'Sluvo 创作者' }}</span>
            <span>{{ publication.forkCount || 0 }} Fork</span>
            <span>{{ formatDate(publication.publishedAt) }}</span>
          </div>
          <div class="community-tags">
            <span v-for="tag in publication.tags || []" :key="tag">{{ tag }}</span>
          </div>
          <button class="community-fork-button" type="button" :disabled="forking" @click="forkCanvas">
            <Loader2 v-if="forking" class="spin" :size="17" />
            <GitFork v-else :size="17" />
            Fork 到我的画布
          </button>
        </div>
      </header>

      <section ref="previewFrame" class="community-preview" aria-label="只读画布全景预览">
        <div class="community-preview__hud">
          <span>只读画布全景</span>
          <strong>{{ previewZoomLabel }}</strong>
        </div>
        <svg class="community-preview__edges" aria-hidden="true">
          <g :transform="previewSvgTransform">
            <path v-for="edge in previewEdges" :key="edge.id" :d="edge.path" />
          </g>
        </svg>
        <div class="community-preview__nodes" :style="previewLayerStyle">
          <article
            v-for="node in previewNodes"
            :key="node.id"
            class="community-node"
            :class="{ 'community-node--image': node.imageUrl }"
            :style="{ left: `${node.x}px`, top: `${node.y}px`, width: `${node.width}px`, height: `${node.height}px` }"
          >
            <strong>{{ node.title }}</strong>
            <span>{{ node.kind }}</span>
            <img v-if="node.imageUrl" :src="node.imageUrl" alt="" loading="lazy" />
            <p v-else>{{ node.body }}</p>
          </article>
        </div>
      </section>
    </template>
  </main>
</template>

<script setup>
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { GitFork, Loader2 } from 'lucide-vue-next'
import logoUrl from '../../LOGO.png'
import { fetchSluvoCommunityCanvas, forkSluvoCommunityCanvas } from '../api/sluvoApi'

const route = useRoute()
const router = useRouter()
const publication = ref(null)
const loading = ref(false)
const forking = ref(false)
const error = ref('')
const previewFrame = ref(null)
const previewSize = ref({ width: 1180, height: 620 })
let previewResizeObserver = null

const previewNodes = computed(() => {
  return (publication.value?.nodes || []).map((node, index) => {
    const data = node.data || {}
    const media = data.media || data.generatedImage || {}
    return {
      id: node.id,
      title: node.title || data.title || `节点 ${index + 1}`,
      kind: data.directType || node.nodeType || 'node',
      x: Number(node.position?.x || 0),
      y: Number(node.position?.y || 0),
      width: normalizeNodeSize(node.size?.width, 260),
      height: normalizeNodeSize(node.size?.height, resolveImageUrl(media) ? 190 : 150),
      imageUrl: resolveImageUrl(media) || resolveImageUrl(data.referenceImages) || resolveImageUrl(data),
      body: data.prompt || data.body || '社区画布节点'
    }
  })
})

const previewBounds = computed(() => {
  if (!previewNodes.value.length) return { x: 0, y: 0, width: 1200, height: 680 }
  const xs = previewNodes.value.map((node) => node.x)
  const ys = previewNodes.value.map((node) => node.y)
  const rights = previewNodes.value.map((node) => node.x + node.width)
  const bottoms = previewNodes.value.map((node) => node.y + node.height)
  const rawWidth = Math.max(...rights) - Math.min(...xs)
  const rawHeight = Math.max(...bottoms) - Math.min(...ys)
  const gutter = Math.max(160, Math.min(420, Math.max(rawWidth, rawHeight) * 0.08))
  const x = Math.min(...xs) - gutter
  const y = Math.min(...ys) - gutter
  return {
    x,
    y,
    width: Math.max(...rights) - x + gutter,
    height: Math.max(...bottoms) - y + gutter
  }
})

const previewFit = computed(() => {
  const bounds = previewBounds.value
  const frame = previewSize.value
  const padding = frame.width < 760 ? 28 : 58
  const availableWidth = Math.max(1, frame.width - padding * 2)
  const availableHeight = Math.max(1, frame.height - padding * 2)
  const scale = Math.min(1, availableWidth / bounds.width, availableHeight / bounds.height)
  const offsetX = (frame.width - bounds.width * scale) / 2 - bounds.x * scale
  const offsetY = (frame.height - bounds.height * scale) / 2 - bounds.y * scale
  return { scale, offsetX, offsetY }
})

const previewLayerStyle = computed(() => {
  const fit = previewFit.value
  return {
    transform: `translate(${fit.offsetX}px, ${fit.offsetY}px) scale(${fit.scale})`
  }
})

const previewSvgTransform = computed(() => {
  const fit = previewFit.value
  return `translate(${fit.offsetX} ${fit.offsetY}) scale(${fit.scale})`
})

const previewZoomLabel = computed(() => `${Math.round(previewFit.value.scale * 100)}%`)

const previewEdges = computed(() => {
  const nodeMap = new Map(previewNodes.value.map((node) => [node.id, node]))
  return (publication.value?.edges || [])
    .map((edge, index) => {
      const source = nodeMap.get(edge.sourceNodeId)
      const target = nodeMap.get(edge.targetNodeId)
      if (!source || !target) return null
      const sx = source.x + source.width
      const sy = source.y + source.height / 2
      const tx = target.x
      const ty = target.y + target.height / 2
      const mid = Math.max(80, Math.abs(tx - sx) * 0.42)
      return {
        id: edge.id || `edge-${index}`,
        path: `M ${sx} ${sy} C ${sx + mid} ${sy}, ${tx - mid} ${ty}, ${tx} ${ty}`
      }
    })
    .filter(Boolean)
})

onMounted(() => {
  loadPublication()
  nextTick(() => observePreviewFrame())
})

onBeforeUnmount(() => {
  previewResizeObserver?.disconnect?.()
  previewResizeObserver = null
})

watch(
  () => publication.value?.id,
  () => nextTick(() => {
    observePreviewFrame()
    measurePreviewFrame()
  })
)

async function loadPublication() {
  loading.value = true
  error.value = ''
  try {
    const payload = await fetchSluvoCommunityCanvas(route.params.publicationId)
    publication.value = payload?.publication || null
  } catch (err) {
    error.value = err instanceof Error ? err.message : '社区画布加载失败'
    if (err?.status === 401) router.push({ name: 'login', query: { redirect: route.fullPath } })
  } finally {
    loading.value = false
  }
}

async function forkCanvas() {
  if (!publication.value?.id || forking.value) return
  forking.value = true
  try {
    const payload = await forkSluvoCommunityCanvas(publication.value.id)
    const projectId = payload?.project?.id
    if (projectId) router.push(`/projects/${projectId}/canvas`)
  } catch (err) {
    error.value = err instanceof Error ? err.message : 'Fork 社区画布失败'
    if (err?.status === 401) router.push({ name: 'login', query: { redirect: route.fullPath } })
  } finally {
    forking.value = false
  }
}

function resolveImageUrl(value) {
  if (!value) return ''
  if (typeof value === 'string') return value.startsWith('http') ? value : ''
  if (Array.isArray(value)) {
    for (const item of value) {
      const resolved = resolveImageUrl(item)
      if (resolved) return resolved
    }
    return ''
  }
  if (typeof value === 'object') {
    return (
      resolveImageUrl(value.url) ||
      resolveImageUrl(value.previewUrl) ||
      resolveImageUrl(value.thumbnailUrl) ||
      resolveImageUrl(value.imageUrl) ||
      resolveImageUrl(value.src) ||
      resolveImageUrl(value.assetUrl) ||
      resolveImageUrl(value.mediaUrl) ||
      resolveImageUrl(value.coverUrl) ||
      resolveImageUrl(value.images) ||
      resolveImageUrl(value.assets)
    )
  }
  return ''
}

function normalizeNodeSize(value, fallback) {
  const size = Number(value)
  return Number.isFinite(size) && size > 0 ? size : fallback
}

function observePreviewFrame() {
  const element = previewFrame.value
  if (!element) return
  if (!previewResizeObserver && typeof ResizeObserver !== 'undefined') {
    previewResizeObserver = new ResizeObserver(measurePreviewFrame)
    previewResizeObserver.observe(element)
  }
  measurePreviewFrame()
}

function measurePreviewFrame() {
  const rect = previewFrame.value?.getBoundingClientRect?.()
  if (!rect?.width || !rect?.height) return
  previewSize.value = { width: rect.width, height: rect.height }
}

function formatDate(value) {
  if (!value) return '刚刚发布'
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return '刚刚发布'
  return date.toLocaleDateString('zh-CN', { month: '2-digit', day: '2-digit' })
}

function goHome() {
  router.push('/')
}
</script>

<style scoped>
.community-page {
  min-height: 100vh;
  padding: 24px clamp(18px, 5vw, 72px) 72px;
  background:
    radial-gradient(circle at 50% -10%, rgba(214, 181, 109, 0.18), transparent 34%),
    linear-gradient(180deg, #050505 0%, #090806 58%, #030303 100%);
  color: #fff8e6;
}

.community-nav,
.community-hero {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 18px;
}

.community-nav {
  margin-bottom: 34px;
}

.community-nav button,
.community-fork-button {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 8px;
  min-height: 40px;
  padding: 0 15px;
  border: 1px solid rgba(255, 241, 199, 0.2);
  border-radius: 8px;
  background: rgba(255, 255, 255, 0.055);
  color: #fff1c7;
  font-weight: 900;
}

.community-brand {
  padding-left: 6px !important;
}

.community-brand img {
  width: 34px;
  height: 34px;
  border-radius: 6px;
}

.community-hero {
  align-items: stretch;
  max-width: 1180px;
  margin: 0 auto 28px;
}

.community-hero__cover {
  display: grid;
  place-items: center;
  overflow: hidden;
  width: min(420px, 36vw);
  min-height: 260px;
  border: 1px solid rgba(214, 181, 109, 0.16);
  border-radius: 8px;
  background:
    radial-gradient(circle at 50% 38%, rgba(214, 181, 109, 0.18), transparent 42%),
    #17130d;
  color: rgba(255, 248, 230, 0.58);
  font-weight: 900;
}

.community-hero__cover img {
  width: 100%;
  height: 100%;
  object-fit: cover;
}

.community-hero > div {
  flex: 1;
  display: grid;
  align-content: center;
  gap: 14px;
  min-width: 0;
}

.community-hero__eyebrow,
.community-hero__meta,
.community-tags {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}

.community-hero__eyebrow,
.community-tags span {
  width: fit-content;
  padding: 5px 9px;
  border: 1px solid rgba(214, 181, 109, 0.22);
  border-radius: 999px;
  background: rgba(214, 181, 109, 0.1);
  color: #d6b56d;
  font-size: 12px;
  font-weight: 900;
}

.community-hero h1 {
  margin: 0;
  font-size: clamp(34px, 5vw, 72px);
  letter-spacing: 0;
}

.community-hero p {
  max-width: 680px;
  margin: 0;
  color: rgba(249, 241, 220, 0.64);
  line-height: 1.7;
}

.community-hero__meta span {
  color: rgba(249, 241, 220, 0.62);
  font-size: 13px;
  font-weight: 800;
}

.community-fork-button {
  width: fit-content;
  border-color: rgba(255, 221, 151, 0.42);
  background: linear-gradient(180deg, #d6b56d, #9f722c);
  color: #160f06;
}

.community-preview {
  position: relative;
  overflow: hidden;
  max-width: 1180px;
  height: min(760px, 72vh);
  min-height: 560px;
  margin: 0 auto;
  border: 1px solid rgba(214, 181, 109, 0.14);
  border-radius: 8px;
  background:
    linear-gradient(rgba(214, 181, 109, 0.055) 1px, transparent 1px),
    linear-gradient(90deg, rgba(214, 181, 109, 0.055) 1px, transparent 1px),
    radial-gradient(circle at 50% 40%, rgba(214, 181, 109, 0.12), transparent 46%),
    #090806;
  background-size: 34px 34px, 34px 34px, auto, auto;
}

.community-preview__hud {
  position: absolute;
  left: 16px;
  right: 16px;
  top: 14px;
  z-index: 4;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  pointer-events: none;
}

.community-preview__hud span,
.community-preview__hud strong {
  display: inline-flex;
  align-items: center;
  min-height: 30px;
  padding: 0 10px;
  border: 1px solid rgba(255, 241, 199, 0.13);
  border-radius: 8px;
  background: rgba(18, 15, 10, 0.72);
  color: rgba(255, 248, 230, 0.72);
  font-size: 12px;
  font-weight: 900;
  backdrop-filter: blur(8px);
}

.community-preview__edges {
  position: absolute;
  inset: 0;
  width: 100%;
  height: 100%;
}

.community-preview__edges path {
  fill: none;
  stroke: rgba(214, 181, 109, 0.58);
  stroke-width: 3;
  vector-effect: non-scaling-stroke;
}

.community-preview__nodes {
  position: absolute;
  inset: 0;
  transform-origin: 0 0;
}

.community-node {
  position: absolute;
  display: grid;
  align-content: start;
  gap: 8px;
  padding: 12px;
  overflow: hidden;
  border: 1px solid rgba(255, 241, 199, 0.16);
  border-radius: 8px;
  background: rgba(18, 15, 10, 0.92);
  box-shadow: 0 18px 40px rgba(0, 0, 0, 0.32);
}

.community-node--image {
  grid-template-rows: auto auto minmax(0, 1fr);
}

.community-node strong {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.community-node span {
  color: #d6b56d;
  font-size: 12px;
  font-weight: 900;
}

.community-node img {
  width: 100%;
  height: 100%;
  min-height: 0;
  object-fit: contain;
  border-radius: 6px;
  background: rgba(0, 0, 0, 0.38);
}

.community-node p {
  display: -webkit-box;
  margin: 0;
  overflow: hidden;
  color: rgba(249, 241, 220, 0.58);
  font-size: 12px;
  line-height: 1.5;
  -webkit-box-orient: vertical;
  -webkit-line-clamp: 4;
}

.community-state {
  display: grid;
  place-items: center;
  gap: 14px;
  min-height: 50vh;
  color: rgba(255, 248, 230, 0.68);
  font-weight: 900;
}

.community-state--error {
  color: #f3d894;
}

.spin {
  animation: spin 0.8s linear infinite;
}

@keyframes spin {
  to {
    transform: rotate(360deg);
  }
}

@media (max-width: 820px) {
  .community-nav,
  .community-hero {
    align-items: flex-start;
    flex-direction: column;
  }

  .community-hero__cover {
    width: 100%;
    min-height: 220px;
  }

  .community-preview {
    height: 62vh;
    min-height: 420px;
  }
}
</style>
