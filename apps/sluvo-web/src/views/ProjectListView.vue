<template>
  <main class="project-space">
    <aside class="space-rail" aria-label="Sluvo navigation">
      <button class="rail-logo" type="button" aria-label="返回首页" @click="goHome">
        <img :src="logoUrl" alt="" />
      </button>
      <button class="rail-tool" type="button" aria-label="首页" @click="goHome">
        <Compass :size="20" />
      </button>
      <button class="rail-tool is-active" type="button" aria-label="全部项目">
        <FolderOpen :size="20" />
      </button>
      <button class="rail-tool" type="button" aria-label="开放社区" @click="goCommunity">
        <Image :size="20" />
      </button>
      <span class="rail-separator" />
      <button class="rail-tool rail-tool--muted" type="button" aria-label="回收站" @click="goTrash">
        <Trash2 :size="19" />
      </button>
    </aside>

    <section class="space-main">
      <header class="space-topbar">
        <button class="space-brand" type="button" @click="goHome">
          <span class="space-brand__mark">
            <img :src="logoUrl" alt="" />
          </span>
          <strong>Sluvo</strong>
        </button>
        <div class="space-topbar__actions">
          <button type="button">简体中文</button>
          <button type="button">我的资产</button>
          <span>{{ userInitial }}</span>
        </div>
      </header>

      <div class="space-content">
        <div class="space-heading">
          <div>
            <h1>全部项目</h1>
            <p>管理你的 Sluvo 画布，继续最近的漫剧创作。</p>
          </div>
          <label class="space-search">
            <Search :size="15" />
            <input v-model.trim="searchText" type="search" placeholder="搜索项目名称" />
          </label>
        </div>

        <div class="space-tabs" aria-label="项目筛选">
          <button class="is-active" type="button">全部</button>
          <button type="button" disabled>我的收藏</button>
        </div>

        <p v-if="projectStore.error" class="space-error">{{ projectStore.error }}</p>

        <div class="project-grid">
          <button class="project-card project-card--create" type="button" :disabled="isCreatingProject" @click="createProject">
            <span class="project-card__preview project-card__preview--create">
              <Plus :size="28" />
            </span>
            <strong>新建项目</strong>
            <small>从一个创意、剧本、角色或分镜目标开始</small>
          </button>

          <article
            v-for="project in filteredProjects"
            :key="project.id"
            class="project-card"
            tabindex="0"
            @click="openProject(project.id)"
            @keydown.enter.prevent="openProject(project.id)"
            @keydown.space.prevent="openProject(project.id)"
          >
            <span
              class="project-card__preview"
              :class="getProjectCover(project) ? 'project-card__preview--media' : 'project-card__preview--no-cover'"
            >
              <img v-if="getProjectCover(project)" :src="getProjectCover(project)" :alt="project.title || '未命名画布'" loading="lazy" />
              <span v-else>无封面</span>
            </span>
            <button class="project-card__delete" type="button" :disabled="deletingProjectIds.has(project.id)" aria-label="删除项目" @click.stop="deleteProject(project)">
              <Trash2 :size="16" />
            </button>
            <strong>{{ project.title || '未命名画布' }}</strong>
            <small>{{ formatProjectMeta(project) }}</small>
          </article>

          <article v-if="!projectStore.loadingProjects && filteredProjects.length === 0" class="project-card project-card--empty">
            <span class="project-card__preview project-card__preview--no-cover">没有匹配项目</span>
            <strong>换个关键词试试</strong>
            <small>也可以直接新建一张画布。</small>
          </article>
        </div>
      </div>
    </section>
  </main>
</template>

<script setup>
import { computed, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { Compass, FolderOpen, Image, Plus, Search, Trash2 } from 'lucide-vue-next'
import logoUrl from '../../LOGO.png'
import { useAuthStore } from '../stores/authStore'
import { useProjectStore } from '../stores/projectStore'

const router = useRouter()
const authStore = useAuthStore()
const projectStore = useProjectStore()
const searchText = ref('')
const deletingProjectIds = ref(new Set())

const userInitial = computed(() => authStore.userInitial)
const isCreatingProject = computed(() => projectStore.creatingProject)
const filteredProjects = computed(() => {
  const keyword = searchText.value.toLowerCase()
  if (!keyword) return projectStore.projects
  return projectStore.projects.filter((project) => {
    const title = String(project.title || '').toLowerCase()
    const description = String(project.description || '').toLowerCase()
    return title.includes(keyword) || description.includes(keyword)
  })
})

onMounted(() => {
  authStore.syncFromStorage()
  projectStore.loadProjects().catch((error) => {
    if (error?.status === 401) authStore.logout()
  })
})

function goHome() {
  router.push({ name: 'workspace' })
}

function goTrash() {
  router.push({ name: 'trash' })
}

function goCommunity() {
  router.push({ name: 'community-canvases' })
}

async function createProject() {
  try {
    const payload = await projectStore.createProjectFromPrompt('')
    const projectId = payload?.project?.id
    if (projectId) router.push(`/projects/${projectId}/canvas`)
  } catch (error) {
    if (error?.status === 401) authStore.logout()
  }
}

function openProject(projectId) {
  if (projectId) router.push(`/projects/${projectId}/canvas`)
}

async function deleteProject(project) {
  if (!project?.id || deletingProjectIds.value.has(project.id)) return
  const title = project.title || '未命名画布'
  if (!window.confirm(`确定删除「${title}」吗？删除后会进入回收站。`)) return
  deletingProjectIds.value = new Set([...deletingProjectIds.value, project.id])
  try {
    await projectStore.deleteProject(project.id)
  } finally {
    const next = new Set(deletingProjectIds.value)
    next.delete(project.id)
    deletingProjectIds.value = next
  }
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

function formatProjectMeta(project) {
  const updated = project.updatedAt || project.createdAt
  if (!updated) return 'Sluvo 画布项目'
  const date = new Date(updated)
  if (Number.isNaN(date.getTime())) return 'Sluvo 画布项目'
  return date.toLocaleString('zh-CN', {
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit'
  })
}
</script>

<style scoped>
.project-space {
  display: block;
  min-height: 100vh;
  padding-left: 76px;
  background: #060606;
  color: #f9f1dc;
}

.space-rail {
  position: fixed;
  top: 0;
  left: 0;
  z-index: 12;
  display: flex;
  align-items: center;
  flex-direction: column;
  gap: 12px;
  width: 76px;
  height: 100vh;
  padding: 18px 12px;
  border-right: 1px solid rgba(214, 181, 109, 0.12);
  background: rgba(13, 11, 7, 0.96);
}

.rail-logo,
.space-brand__mark {
  display: grid;
  place-items: center;
  width: 46px;
  height: 46px;
  padding: 2px;
  border: 1px solid rgba(214, 181, 109, 0.32);
  border-radius: 8px;
  background:
    linear-gradient(145deg, rgba(255, 241, 199, 0.16), rgba(214, 181, 109, 0.08)),
    #0e0b06;
  color: #ffe7a4;
  overflow: hidden;
  box-shadow: inset 0 1px 0 rgba(255, 255, 255, 0.12);
}

.rail-logo {
  margin-bottom: 18px;
}

.rail-logo img,
.space-brand__mark img {
  width: 100%;
  height: 100%;
  border-radius: 6px;
  object-fit: cover;
}

.rail-tool {
  display: grid;
  place-items: center;
  width: 42px;
  height: 42px;
  border-radius: 8px;
  background: transparent;
  color: rgba(249, 241, 220, 0.7);
}

.rail-tool:hover,
.rail-tool.is-active {
  background: rgba(214, 181, 109, 0.16);
  color: #fff5d7;
}

.rail-tool--muted {
  margin-top: auto;
}

.rail-separator {
  width: 32px;
  height: 1px;
  margin: 4px 0;
  background: rgba(214, 181, 109, 0.12);
}

.space-main {
  min-width: 0;
}

.space-topbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  min-height: 68px;
  padding: 16px clamp(22px, 5vw, 92px);
  border-bottom: 1px solid rgba(255, 255, 255, 0.035);
  background: rgba(8, 8, 8, 0.92);
}

.space-brand,
.space-topbar__actions,
.space-topbar__actions button,
.space-topbar__actions span {
  display: inline-flex;
  align-items: center;
  gap: 10px;
}

.space-brand {
  gap: 14px;
  padding: 0;
  background: transparent;
  color: #fff8e6;
  font-size: 24px;
  font-weight: 900;
}

.space-topbar__actions button,
.space-topbar__actions span {
  min-height: 34px;
  padding: 0 12px;
  border-radius: 999px;
  background: rgba(255, 255, 255, 0.075);
  color: rgba(249, 241, 220, 0.82);
  font-size: 12px;
  font-weight: 900;
}

.space-content {
  width: min(1640px, calc(100vw - 170px));
  margin: 0 auto;
  padding: 64px 0 96px;
}

.space-heading {
  display: flex;
  align-items: flex-end;
  justify-content: space-between;
  gap: 22px;
  margin-bottom: 26px;
}

.space-heading h1 {
  margin: 0;
  color: #fff8e6;
  font-size: 30px;
}

.space-heading p {
  margin: 10px 0 0;
  color: rgba(249, 241, 220, 0.5);
  font-size: 13px;
  font-weight: 700;
}

.space-search {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  width: min(280px, 100%);
  min-height: 38px;
  padding: 0 12px;
  border-radius: 8px;
  background: rgba(255, 255, 255, 0.07);
  color: rgba(249, 241, 220, 0.48);
}

.space-search input {
  width: 100%;
  border: 0;
  outline: none;
  background: transparent;
  color: #fff8e6;
}

.space-tabs {
  display: flex;
  gap: 10px;
  margin-bottom: 28px;
}

.space-tabs button {
  min-height: 34px;
  padding: 0 24px;
  border-radius: 10px;
  background: rgba(255, 255, 255, 0.075);
  color: rgba(249, 241, 220, 0.58);
  font-size: 13px;
  font-weight: 900;
}

.space-tabs button.is-active {
  color: #fff8e6;
  background: rgba(255, 255, 255, 0.14);
}

.space-error {
  color: #f3d894;
  font-size: 13px;
  font-weight: 800;
}

.project-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(230px, 1fr));
  gap: 18px;
}

.project-card {
  position: relative;
  display: grid;
  gap: 9px;
  min-height: 178px;
  min-width: 0;
  padding: 10px 10px 14px;
  border: 1px solid rgba(255, 255, 255, 0.065);
  border-radius: 14px;
  background: #171717;
  color: #fff8e6;
  cursor: pointer;
  text-align: left;
  transition: transform 0.18s ease, border-color 0.18s ease, background 0.18s ease;
}

.project-card:hover,
.project-card:focus-visible {
  border-color: rgba(214, 181, 109, 0.36);
  background: #1d1d1d;
  outline: none;
  transform: translateY(-3px);
}

.project-card--create {
  border-style: dashed;
  background:
    radial-gradient(circle at 50% 32%, rgba(214, 181, 109, 0.12), transparent 34%),
    #171717;
}

.project-card__preview {
  position: relative;
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

.project-card__preview--media img {
  width: 100%;
  height: 100%;
  object-fit: cover;
}

.project-card__preview--create {
  border: 1px solid rgba(255, 241, 199, 0.12);
  background:
    radial-gradient(circle at 50% 50%, rgba(255, 241, 199, 0.14), transparent 42%),
    #22231f;
  color: #fff1c7;
}

.project-card__delete {
  position: absolute;
  top: 18px;
  right: 18px;
  display: grid;
  place-items: center;
  width: 32px;
  height: 32px;
  border-radius: 8px;
  background: rgba(8, 8, 8, 0.76);
  color: rgba(255, 222, 216, 0.82);
  opacity: 0;
  transition: opacity 0.16s ease;
}

.project-card:hover .project-card__delete,
.project-card:focus-within .project-card__delete {
  opacity: 1;
}

.project-card strong {
  overflow: hidden;
  padding: 0 4px;
  font-size: 16px;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.project-card small {
  padding: 0 4px;
  color: rgba(249, 241, 220, 0.48);
  font-size: 12px;
}

.project-card--empty {
  cursor: default;
  opacity: 0.72;
}

@media (max-width: 820px) {
  .project-space {
    padding-top: 64px;
    padding-left: 0;
  }

  .space-rail {
    z-index: 12;
    flex-direction: row;
    width: 100%;
    height: 64px;
    padding: 10px 14px;
    overflow-x: auto;
    border-right: 0;
    border-bottom: 1px solid rgba(214, 181, 109, 0.12);
  }

  .rail-logo {
    margin: 0 8px 0 0;
  }

  .rail-separator {
    width: 1px;
    height: 28px;
    margin: 0 2px;
  }

  .rail-tool--muted {
    margin-top: 0;
    margin-left: auto;
  }

  .space-topbar,
  .space-heading {
    align-items: flex-start;
    flex-direction: column;
  }

  .space-content {
    width: calc(100vw - 32px);
    padding-top: 36px;
  }

  .project-grid {
    grid-template-columns: 1fr;
  }
}
</style>
