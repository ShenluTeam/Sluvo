<template>
  <main class="trash-space">
    <aside class="trash-rail" aria-label="Sluvo navigation">
      <button class="rail-logo" type="button" aria-label="返回首页" @click="goHome">
        <img :src="logoUrl" alt="" />
      </button>
      <button class="rail-tool" type="button" aria-label="首页" @click="goHome">
        <Home :size="20" />
      </button>
      <button class="rail-tool" type="button" aria-label="全部项目" @click="goProjects">
        <FolderOpen :size="20" />
      </button>
      <button class="rail-tool" type="button" aria-label="开放社区" @click="goCommunity">
        <Compass :size="20" />
      </button>
      <button class="rail-tool rail-tool--muted is-active" type="button" aria-label="回收站">
        <Trash2 :size="19" />
      </button>
    </aside>

    <section class="trash-main">
      <header class="trash-topbar">
        <button class="trash-brand" type="button" @click="goHome">
          <img :src="logoUrl" alt="" />
          <strong>Sluvo</strong>
        </button>
        <label class="trash-search">
          <Search :size="15" />
          <input v-model.trim="searchText" type="search" placeholder="搜索项目" />
        </label>
      </header>

      <div class="trash-content">
        <div class="trash-heading">
          <h1>回收站</h1>
          <p>已删除的项目会暂存在这里，后续可接入恢复和彻底删除能力。</p>
        </div>

        <div class="trash-tabs" aria-label="回收站分类">
          <button class="is-active" type="button">项目</button>
          <button type="button" disabled>角色</button>
          <button type="button" disabled>场景</button>
        </div>

        <p class="trash-retention">删除的内容仅保留 30 天</p>
        <p v-if="errorText" class="trash-error">{{ errorText }}</p>

        <div class="trash-grid">
          <article v-for="project in filteredDeletedProjects" :key="project.id" class="trash-card">
            <span
              class="trash-card__preview"
              :class="getProjectCover(project) ? 'trash-card__preview--media' : 'trash-card__preview--empty'"
            >
              <img v-if="getProjectCover(project)" :src="getProjectCover(project)" :alt="project.title || '未命名画布'" loading="lazy" />
              <span v-else>无封面</span>
            </span>
            <strong>{{ project.title || '未命名画布' }}</strong>
            <small>{{ formatTrashMeta(project) }}</small>
          </article>

          <article v-if="!loading && filteredDeletedProjects.length === 0" class="trash-card trash-card--empty">
            <span class="trash-card__preview trash-card__preview--empty">回收站为空</span>
            <strong>没有已删除项目</strong>
            <small>删除项目后会出现在这里。</small>
          </article>
        </div>
      </div>
    </section>
  </main>
</template>

<script setup>
import { computed, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { Compass, FolderOpen, Home, Search, Trash2 } from 'lucide-vue-next'
import logoUrl from '../../LOGO.png'
import { useAuthStore } from '../stores/authStore'
import { fetchSluvoProjects } from '../api/sluvoApi'

const router = useRouter()
const authStore = useAuthStore()
const deletedProjects = ref([])
const loading = ref(false)
const errorText = ref('')
const searchText = ref('')

const filteredDeletedProjects = computed(() => {
  const keyword = searchText.value.toLowerCase()
  if (!keyword) return deletedProjects.value
  return deletedProjects.value.filter((project) => {
    const title = String(project.title || '').toLowerCase()
    const description = String(project.description || '').toLowerCase()
    return title.includes(keyword) || description.includes(keyword)
  })
})

onMounted(() => {
  authStore.syncFromStorage()
  loadDeletedProjects()
})

async function loadDeletedProjects() {
  loading.value = true
  errorText.value = ''
  try {
    deletedProjects.value = await fetchSluvoProjects({ includeDeleted: true })
  } catch (error) {
    if (error?.status === 401) authStore.logout()
    errorText.value = error instanceof Error ? error.message : '回收站加载失败'
  } finally {
    loading.value = false
  }
}

function goHome() {
  router.push({ name: 'home' })
}

function goProjects() {
  router.push({ name: 'projects' })
}

function goCommunity() {
  router.push({ name: 'home', hash: '#community' })
}

function resolveProjectImageUrl(value) {
  if (!value) return ''
  if (typeof value === 'string') return value.trim()
  if (Array.isArray(value)) return value.map(resolveProjectImageUrl).find(Boolean) || ''
  if (typeof value === 'object') {
    return (
      resolveProjectImageUrl(value.firstImageUrl) ||
      resolveProjectImageUrl(value.first_image_url) ||
      resolveProjectImageUrl(value.thumbnailUrl) ||
      resolveProjectImageUrl(value.thumbnail_url) ||
      resolveProjectImageUrl(value.previewUrl) ||
      resolveProjectImageUrl(value.preview_url) ||
      resolveProjectImageUrl(value.coverUrl) ||
      resolveProjectImageUrl(value.cover_url) ||
      resolveProjectImageUrl(value.imageUrl) ||
      resolveProjectImageUrl(value.image_url) ||
      resolveProjectImageUrl(value.url) ||
      resolveProjectImageUrl(value.src)
    )
  }
  return ''
}

function getProjectCover(project) {
  return (
    resolveProjectImageUrl(project?.firstImageUrl) ||
    resolveProjectImageUrl(project?.first_image_url) ||
    resolveProjectImageUrl(project?.coverUrl) ||
    resolveProjectImageUrl(project?.cover_url) ||
    resolveProjectImageUrl(project?.assets) ||
    resolveProjectImageUrl(project?.images) ||
    resolveProjectImageUrl(project?.media) ||
    resolveProjectImageUrl(project?.settings?.firstImageUrl) ||
    resolveProjectImageUrl(project?.settings?.first_image_url) ||
    resolveProjectImageUrl(project?.settings?.coverUrl)
  )
}

function formatTrashMeta(project) {
  if (!project.deletedAt) return '保留 30 天'
  const deletedAt = new Date(project.deletedAt)
  if (Number.isNaN(deletedAt.getTime())) return '保留 30 天'
  const elapsed = Math.floor((Date.now() - deletedAt.getTime()) / 86400000)
  const daysLeft = Math.max(0, 30 - elapsed)
  return `${daysLeft} 天后清理`
}
</script>

<style scoped>
.trash-space {
  display: grid;
  grid-template-columns: 76px 1fr;
  min-height: 100vh;
  background: #060606;
  color: #f9f1dc;
}

.trash-rail {
  position: sticky;
  top: 0;
  display: flex;
  align-items: center;
  flex-direction: column;
  gap: 12px;
  height: 100vh;
  padding: 18px 12px;
  background: rgba(13, 13, 13, 0.96);
}

.rail-logo,
.rail-tool {
  display: grid;
  place-items: center;
  width: 42px;
  height: 42px;
  border-radius: 12px;
  color: rgba(249, 241, 220, 0.72);
}

.rail-logo {
  overflow: hidden;
  border: 1px solid rgba(214, 181, 109, 0.32);
  border-radius: 8px;
}

.rail-logo img {
  width: 100%;
  height: 100%;
  object-fit: cover;
}

.rail-tool {
  background: rgba(255, 255, 255, 0.04);
}

.rail-tool:hover,
.rail-tool.is-active {
  background: rgba(255, 255, 255, 0.12);
  color: #fff8e6;
}

.rail-tool--muted {
  margin-top: auto;
}

.trash-main {
  min-width: 0;
}

.trash-topbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  min-height: 68px;
  padding: 16px clamp(22px, 5vw, 92px);
  border-bottom: 1px solid rgba(255, 255, 255, 0.035);
  background: rgba(8, 8, 8, 0.92);
}

.trash-brand {
  display: inline-flex;
  align-items: center;
  gap: 10px;
  color: #fff8e6;
  font-size: 20px;
  font-weight: 900;
}

.trash-brand img {
  width: 34px;
  height: 34px;
  border-radius: 7px;
}

.trash-search {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  width: min(260px, 100%);
  min-height: 38px;
  padding: 0 12px;
  border-radius: 8px;
  background: rgba(255, 255, 255, 0.07);
  color: rgba(249, 241, 220, 0.48);
}

.trash-search input {
  width: 100%;
  border: 0;
  outline: none;
  background: transparent;
  color: #fff8e6;
}

.trash-content {
  width: min(1640px, calc(100vw - 170px));
  margin: 0 auto;
  padding: 64px 0 96px;
}

.trash-heading h1 {
  margin: 0;
  color: #fff8e6;
  font-size: 30px;
}

.trash-heading p {
  margin: 10px 0 0;
  color: rgba(249, 241, 220, 0.5);
  font-size: 13px;
  font-weight: 700;
}

.trash-tabs {
  display: flex;
  gap: 10px;
  margin: 28px 0 18px;
}

.trash-tabs button {
  min-height: 34px;
  padding: 0 24px;
  border-radius: 10px;
  background: rgba(255, 255, 255, 0.075);
  color: rgba(249, 241, 220, 0.58);
  font-size: 13px;
  font-weight: 900;
}

.trash-tabs button.is-active {
  color: #fff8e6;
  background: rgba(255, 255, 255, 0.14);
}

.trash-retention {
  margin: 0 0 18px;
  color: #ff6f62;
  font-size: 13px;
  font-weight: 900;
}

.trash-error {
  color: #f3d894;
  font-size: 13px;
  font-weight: 800;
}

.trash-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(230px, 1fr));
  gap: 18px;
}

.trash-card {
  display: grid;
  gap: 9px;
  min-height: 178px;
  padding: 10px 10px 14px;
  border: 1px solid rgba(255, 255, 255, 0.065);
  border-radius: 14px;
  background: #171717;
  color: #fff8e6;
}

.trash-card__preview {
  display: grid;
  place-items: center;
  overflow: hidden;
  aspect-ratio: 16 / 9;
  border-radius: 8px;
  background: #272a28;
  color: rgba(249, 241, 220, 0.46);
  font-size: 12px;
  font-weight: 900;
}

.trash-card__preview--media img {
  width: 100%;
  height: 100%;
  object-fit: cover;
}

.trash-card strong {
  overflow: hidden;
  padding: 0 4px;
  font-size: 16px;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.trash-card small {
  padding: 0 4px;
  color: rgba(249, 241, 220, 0.48);
  font-size: 12px;
}

.trash-card--empty {
  opacity: 0.72;
}

@media (max-width: 820px) {
  .trash-space {
    grid-template-columns: 1fr;
  }

  .trash-rail {
    z-index: 10;
    flex-direction: row;
    width: 100%;
    height: 64px;
    overflow-x: auto;
  }

  .rail-tool--muted {
    margin-top: 0;
    margin-left: auto;
  }

  .trash-topbar {
    align-items: flex-start;
    flex-direction: column;
  }

  .trash-content {
    width: calc(100vw - 32px);
    padding-top: 36px;
  }

  .trash-grid {
    grid-template-columns: 1fr;
  }
}
</style>
