<template>
  <main class="community-directory">
    <header class="community-topbar">
      <button class="community-brand" type="button" @click="goHome">
        <span class="community-brand__mark">
          <img :src="logoUrl" alt="" />
        </span>
        <strong>Sluvo</strong>
      </button>

      <nav class="community-switcher" aria-label="社区类型">
        <button
          v-for="item in communityTabs"
          :key="item.name"
          type="button"
          :class="{ 'is-active': item.name === route.name }"
          @click="router.push({ name: item.name })"
        >
          {{ item.label }}
        </button>
      </nav>

      <div class="community-topbar__actions">
        <button type="button" @click="goCapabilities">能力</button>
        <button type="button" @click="goCanvas">自由画布</button>
        <button class="community-topbar__primary" type="button" @click="goHome">
          <LogIn :size="17" />
          返回主页
        </button>
      </div>
    </header>

    <section class="community-shell">
      <div class="community-heading">
        <div>
          <span>{{ currentConfig.kicker }}</span>
          <h1>{{ currentConfig.title }}</h1>
          <p>{{ currentConfig.description }}</p>
        </div>
        <label class="community-search">
          <Search :size="16" />
          <input v-model.trim="searchText" type="search" :placeholder="currentConfig.searchPlaceholder" />
        </label>
      </div>

      <div class="community-filters" aria-label="社区筛选">
        <button class="is-active" type="button">全部</button>
        <button type="button" disabled>我的收藏</button>
      </div>

      <p v-if="error" class="community-message community-message--error">{{ error }}</p>
      <p v-else-if="loading" class="community-message">
        <Loader2 class="spin" :size="18" />
        正在同步社区内容
      </p>

      <div class="community-grid">
        <article
          v-for="item in filteredItems"
          :key="item.id"
          class="community-card"
          tabindex="0"
          @click="openItem(item)"
          @keydown.enter.prevent="openItem(item)"
          @keydown.space.prevent="openItem(item)"
        >
          <span class="community-card__preview" :class="{ 'community-card__preview--media': item.coverUrl }">
            <img v-if="item.coverUrl" :src="item.coverUrl" :alt="item.title" loading="lazy" />
            <component v-else :is="currentConfig.icon" :size="34" />
          </span>
          <span class="community-card__meta">{{ item.meta }}</span>
          <strong>{{ item.title }}</strong>
          <p>{{ item.description }}</p>
          <div class="community-card__tags">
            <span v-for="tag in item.tags" :key="tag">{{ tag }}</span>
          </div>
          <button type="button" @click.stop="openItem(item)">{{ currentConfig.actionLabel }}</button>
        </article>

        <article v-if="!loading && filteredItems.length === 0" class="community-card community-card--empty">
          <span class="community-card__preview">
            <component :is="currentConfig.icon" :size="34" />
          </span>
          <span class="community-card__meta">等待发布</span>
          <strong>{{ currentConfig.emptyTitle }}</strong>
          <p>{{ searchText ? '换个关键词试试。' : currentConfig.emptyDescription }}</p>
          <button type="button" @click="goCanvas">去创作</button>
        </article>
      </div>
    </section>
  </main>
</template>

<script setup>
import { computed, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { Bot, Boxes, GitFork, Image, Loader2, LogIn, Search } from 'lucide-vue-next'
import logoUrl from '../../LOGO.png'
import { fetchSluvoCommunityAgents, fetchSluvoCommunityCanvases, forkSluvoCommunityAgent } from '../api/sluvoApi'

const router = useRouter()
const route = useRoute()
const searchText = ref('')
const loading = ref(false)
const error = ref('')
const remoteItems = ref([])

const communityTabs = [
  { name: 'community-canvases', label: '画布社区' },
  { name: 'community-agents', label: 'Agent 社区' },
  { name: 'community-skills', label: 'Skill 社区' }
]

const skillItems = [
  {
    id: 'storyboard-skill',
    title: '漫剧分镜生成链',
    description: '从剧情段落生成角色、镜头、景别与视频提示词的画布 Skill。',
    meta: 'Sluvo Skill',
    tags: ['分镜', '漫剧', '提示词']
  },
  {
    id: 'character-board',
    title: '角色资产板',
    description: '沉淀角色设定、参考图、一致性约束和生成记录，适合系列项目复用。',
    meta: 'Sluvo Skill',
    tags: ['角色', '资产', '复用']
  },
  {
    id: 'video-polish',
    title: '视频精修流水线',
    description: '把视频生成、重试、筛选和成片导出组织成稳定的生产流程。',
    meta: 'Sluvo Skill',
    tags: ['视频', '流水线', '交付']
  }
]

const pageConfigs = {
  'community-canvases': {
    type: 'canvas',
    icon: Image,
    kicker: 'Canvas Community',
    title: '画布社区',
    description: '浏览创作者公开的 Sluvo 画布，学习完整创作路径，并 Fork 到自己的工作台继续生长。',
    searchPlaceholder: '搜索画布名称',
    actionLabel: '查看画布',
    emptyTitle: '还没有社区画布',
    emptyDescription: '发布你的第一张开放画布，让其他创作者可以学习和 Fork。'
  },
  'community-agents': {
    type: 'agent',
    icon: Bot,
    kicker: 'Agent Community',
    title: 'Agent 社区',
    description: '发现可复用的导演、编剧、分镜和生成 Agent 团队，把优秀协作方式装进项目。',
    searchPlaceholder: '搜索 Agent 名称',
    actionLabel: '安装 Agent',
    emptyTitle: '还没有社区 Agent',
    emptyDescription: '把你常用的创作 Agent 发布出来，沉淀成团队资产。'
  },
  'community-skills': {
    type: 'skill',
    icon: Boxes,
    kicker: 'Skill Community',
    title: 'Skill 社区',
    description: '把高频创作方法保存为可安装的 Skill，复用稳定的节点模板、Agent 流程和生产链。',
    searchPlaceholder: '搜索 Skill 名称',
    actionLabel: '查看 Skill',
    emptyTitle: '还没有匹配 Skill',
    emptyDescription: '沉淀一条高频流程，发布成可复用的画布 Skill。'
  }
}

const currentConfig = computed(() => pageConfigs[route.name] || pageConfigs['community-canvases'])

const directoryItems = computed(() => {
  if (currentConfig.value.type === 'skill') return skillItems
  return remoteItems.value.map((item, index) => normalizeRemoteItem(item, index))
})

const filteredItems = computed(() => {
  const keyword = searchText.value.toLowerCase()
  if (!keyword) return directoryItems.value
  return directoryItems.value.filter((item) => {
    return [item.title, item.description, item.meta, ...(item.tags || [])].some((value) => String(value || '').toLowerCase().includes(keyword))
  })
})

onMounted(() => {
  loadItems()
})

watch(
  () => route.name,
  () => {
    searchText.value = ''
    loadItems()
  }
)

async function loadItems() {
  loading.value = true
  error.value = ''
  remoteItems.value = []
  try {
    if (currentConfig.value.type === 'canvas') {
      remoteItems.value = await fetchSluvoCommunityCanvases({ limit: 24, sort: 'latest' })
    } else if (currentConfig.value.type === 'agent') {
      remoteItems.value = await fetchSluvoCommunityAgents({ limit: 24, sort: 'latest' })
    }
  } catch (err) {
    error.value = err instanceof Error ? err.message : '社区内容加载失败'
    if (err?.status === 401) router.push({ name: 'login', query: { redirect: route.fullPath } })
  } finally {
    loading.value = false
  }
}

function normalizeRemoteItem(item, index) {
  const title = item.title || item.name || item.agentName || `社区作品 ${index + 1}`
  return {
    id: item.id || item.publicationId || `remote-${index}`,
    source: item,
    title,
    description: item.description || item.summary || item.prompt || (currentConfig.value.type === 'agent' ? '一组可复用的 Sluvo Agent 协作配置。' : '一张可学习、可复用的社区画布。'),
    coverUrl: resolveImageUrl(item.coverUrl || item.cover_url || item.thumbnailUrl || item.previewUrl || item.cover),
    meta: `${item.author?.nickname || item.authorName || 'Sluvo 创作者'} · ${item.forkCount || 0} Fork`,
    tags: Array.isArray(item.tags) ? item.tags.slice(0, 3) : []
  }
}

function resolveImageUrl(value) {
  if (!value) return ''
  if (typeof value === 'string') return value.trim()
  if (Array.isArray(value)) return value.map(resolveImageUrl).find(Boolean) || ''
  if (typeof value === 'object') {
    return resolveImageUrl(value.url) || resolveImageUrl(value.src) || resolveImageUrl(value.imageUrl) || resolveImageUrl(value.previewUrl)
  }
  return ''
}

async function openItem(item) {
  if (currentConfig.value.type === 'canvas' && item.id) {
    router.push({ name: 'community-canvas-detail', params: { publicationId: item.id } })
    return
  }
  if (currentConfig.value.type === 'agent' && item.id) {
    try {
      await forkSluvoCommunityAgent(item.id)
      router.push({ name: 'workspace' })
    } catch (err) {
      error.value = err instanceof Error ? err.message : '安装 Agent 失败'
      if (err?.status === 401) router.push({ name: 'login', query: { redirect: route.fullPath } })
    }
    return
  }
  goCanvas()
}

function goHome() {
  router.push({ name: 'home' })
}

function goCapabilities() {
  router.push({ name: 'home', hash: '#capabilities' })
}

function goCanvas() {
  router.push({ name: 'workspace' })
}
</script>

<style scoped>
.community-directory {
  min-height: 100vh;
  padding-top: 72px;
  background:
    radial-gradient(circle at 72% 0%, rgba(214, 181, 109, 0.08), transparent 32%),
    #050505;
  color: #f9f1dc;
}

.community-topbar {
  position: fixed;
  top: 0;
  left: 0;
  z-index: 30;
  display: grid;
  grid-template-columns: 1fr auto 1fr;
  align-items: center;
  gap: 20px;
  width: 100%;
  min-height: 72px;
  padding: 12px clamp(22px, 4.8vw, 76px);
  border-bottom: 1px solid rgba(236, 204, 136, 0.08);
  background: linear-gradient(180deg, rgba(5, 5, 5, 0.84), rgba(5, 5, 5, 0.58));
  backdrop-filter: blur(28px) saturate(1.18);
  box-shadow: 0 18px 44px rgba(0, 0, 0, 0.28);
}

.community-brand,
.community-switcher,
.community-topbar__actions,
.community-topbar__actions button {
  display: inline-flex;
  align-items: center;
}

.community-brand {
  justify-self: start;
  gap: 14px;
  padding: 0;
  background: transparent;
  color: #fff5d7;
  font-size: 23px;
  font-weight: 900;
}

.community-brand__mark {
  display: grid;
  place-items: center;
  width: 46px;
  height: 46px;
  padding: 2px;
  border: 1px solid rgba(245, 213, 145, 0.34);
  border-radius: 14px;
  background:
    linear-gradient(145deg, rgba(255, 241, 199, 0.13), rgba(214, 181, 109, 0.07)),
    #0e0b06;
  box-shadow: inset 0 1px 0 rgba(255, 255, 255, 0.12);
}

.community-brand__mark img {
  width: 100%;
  height: 100%;
  border-radius: 11px;
  object-fit: cover;
}

.community-switcher {
  justify-self: center;
  gap: 8px;
  padding: 4px;
  border: 1px solid rgba(214, 181, 109, 0.12);
  border-radius: 14px;
  background: rgba(255, 255, 255, 0.035);
  box-shadow: inset 0 1px 0 rgba(255, 255, 255, 0.06);
}

.community-switcher button,
.community-topbar__actions button {
  min-height: 42px;
  padding: 0 18px;
  border: 1px solid rgba(214, 181, 109, 0.18);
  border-radius: 12px;
  background: rgba(255, 255, 255, 0.045);
  color: #f8ecd1;
  font-size: 14px;
  font-weight: 800;
}

.community-switcher button.is-active {
  color: #fff5d7;
  background: rgba(214, 181, 109, 0.16);
  box-shadow: inset 0 1px 0 rgba(255, 255, 255, 0.08);
}

.community-topbar__actions {
  justify-self: end;
  gap: 12px;
}

.community-topbar__primary {
  gap: 8px;
  min-width: 0;
  min-height: 48px !important;
  padding: 0 24px !important;
  justify-content: center;
  border-color: rgba(255, 228, 162, 0.58) !important;
  color: #1a1206 !important;
  background:
    linear-gradient(180deg, rgba(255, 245, 203, 0.95), rgba(225, 183, 91, 0.95) 46%, rgba(176, 124, 42, 0.98)),
    #d6b56d !important;
  box-shadow:
    0 18px 46px rgba(184, 135, 53, 0.24),
    inset 0 1px 0 rgba(255, 255, 255, 0.48);
}

.community-shell {
  width: min(1640px, calc(100vw - 140px));
  margin: 0 auto;
  padding: 82px 0 110px;
}

.community-heading {
  display: flex;
  align-items: flex-end;
  justify-content: space-between;
  gap: 28px;
  margin-bottom: 28px;
}

.community-heading span {
  color: rgba(214, 181, 109, 0.72);
  font-size: 12px;
  font-weight: 950;
  text-transform: uppercase;
}

.community-heading h1 {
  margin: 12px 0 0;
  color: #fff8e6;
  font-size: 42px;
  line-height: 1.05;
}

.community-heading p {
  max-width: 660px;
  margin: 12px 0 0;
  color: rgba(249, 241, 220, 0.54);
  font-size: 15px;
  line-height: 1.75;
  font-weight: 750;
}

.community-search {
  display: inline-flex;
  align-items: center;
  gap: 10px;
  width: min(350px, 100%);
  min-height: 48px;
  padding: 0 16px;
  border-radius: 8px;
  background: rgba(255, 255, 255, 0.075);
  color: rgba(249, 241, 220, 0.45);
}

.community-search input {
  width: 100%;
  border: 0;
  outline: 0;
  background: transparent;
  color: #fff8e6;
  font-size: 15px;
}

.community-filters {
  display: flex;
  gap: 12px;
  margin-bottom: 34px;
}

.community-filters button {
  min-height: 42px;
  padding: 0 28px;
  border-radius: 10px;
  background: rgba(255, 255, 255, 0.075);
  color: rgba(249, 241, 220, 0.58);
  font-size: 14px;
  font-weight: 950;
}

.community-filters button.is-active {
  color: #fff8e6;
  background: rgba(255, 255, 255, 0.14);
}

.community-message {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  margin: 0 0 18px;
  color: rgba(249, 241, 220, 0.62);
  font-weight: 850;
}

.community-message--error {
  color: #f3d894;
}

.community-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(260px, 1fr));
  gap: 22px;
}

.community-card {
  display: grid;
  gap: 11px;
  min-height: 280px;
  padding: 14px 14px 18px;
  border: 1px solid rgba(255, 255, 255, 0.07);
  border-radius: 16px;
  background:
    linear-gradient(180deg, rgba(255, 255, 255, 0.045), transparent),
    #171717;
  color: #fff8e6;
  cursor: pointer;
  transition: transform 0.18s ease, border-color 0.18s ease, background 0.18s ease;
}

.community-card:hover,
.community-card:focus-visible {
  border-color: rgba(214, 181, 109, 0.36);
  background: #1d1d1d;
  outline: none;
  transform: translateY(-3px);
}

.community-card__preview {
  display: grid;
  place-items: center;
  overflow: hidden;
  aspect-ratio: 16 / 9;
  border: 1px solid rgba(255, 241, 199, 0.1);
  border-radius: 9px;
  background:
    radial-gradient(circle at 50% 50%, rgba(214, 181, 109, 0.13), transparent 42%),
    #252721;
  color: #fff1c7;
}

.community-card__preview--media img {
  width: 100%;
  height: 100%;
  object-fit: cover;
}

.community-card__meta {
  color: rgba(214, 181, 109, 0.68);
  font-size: 12px;
  font-weight: 850;
}

.community-card strong {
  color: #fff8e6;
  font-size: 20px;
  line-height: 1.25;
}

.community-card p {
  min-height: 46px;
  margin: 0;
  color: rgba(249, 241, 220, 0.52);
  font-size: 13px;
  line-height: 1.65;
}

.community-card__tags {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}

.community-card__tags span {
  padding: 5px 9px;
  border-radius: 999px;
  background: rgba(214, 181, 109, 0.11);
  color: rgba(249, 241, 220, 0.68);
  font-size: 11px;
  font-weight: 850;
}

.community-card button {
  justify-self: start;
  min-height: 34px;
  padding: 0 14px;
  border: 1px solid rgba(214, 181, 109, 0.2);
  border-radius: 8px;
  background: rgba(214, 181, 109, 0.12);
  color: #fff5d7;
  font-size: 12px;
  font-weight: 950;
}

.community-card--empty {
  border-style: dashed;
}

.spin {
  animation: spin 0.9s linear infinite;
}

@keyframes spin {
  to {
    transform: rotate(360deg);
  }
}

@media (max-width: 1100px) {
  .community-topbar {
    grid-template-columns: 1fr;
    justify-items: stretch;
  }

  .community-brand,
  .community-switcher,
  .community-topbar__actions {
    justify-self: stretch;
  }

  .community-switcher,
  .community-topbar__actions {
    overflow-x: auto;
  }

  .community-directory {
    padding-top: 210px;
  }

  .community-shell {
    width: calc(100vw - 40px);
    padding-top: 54px;
  }

  .community-heading {
    align-items: flex-start;
    flex-direction: column;
  }
}

@media (max-width: 620px) {
  .community-topbar {
    padding: 12px 16px;
  }

  .community-brand {
    font-size: 24px;
  }

  .community-switcher button,
  .community-topbar__actions button {
    min-height: 42px;
    padding: 0 16px;
    font-size: 13px;
  }

  .community-topbar__primary {
    min-width: 132px;
  }

  .community-shell {
    width: calc(100vw - 28px);
  }

  .community-heading h1 {
    font-size: 34px;
  }

  .community-grid {
    grid-template-columns: 1fr;
  }
}
</style>
