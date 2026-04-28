<template>
  <main class="sluvo-home" :class="{ 'is-authed': isAuthenticated }">
    <section v-if="!isAuthenticated" class="home-guest-shell">
      <nav class="home-nav" aria-label="Sluvo">
        <button class="home-brand" type="button" @click="scrollToTop">
          <span class="home-brand__mark">S</span>
          <span>
            <strong>Sluvo</strong>
            <small>by 神鹿影视 AI</small>
          </span>
        </button>

        <div class="home-nav__actions">
          <button class="home-nav__link" type="button" @click="scrollToCapabilities">能力</button>
          <button class="home-nav__link" type="button" @click="openCanvas()">自由画布</button>
          <button class="home-nav__primary" type="button" @click="openLogin">
            <LogIn :size="17" />
            登录神鹿账号
          </button>
        </div>
      </nav>

      <div class="guest-hero">
        <div class="guest-hero__copy">
          <span class="guest-hero__eyebrow">
            <Sparkles :size="16" />
            神鹿影视 AI 平台旗下的无限画布创作工作台
          </span>
          <h1>Sluvo</h1>
          <p class="guest-hero__lead">把剧本、角色、分镜、图片、视频和生成任务放进同一张可执行画布。</p>
          <div class="guest-hero__actions">
            <button class="gold-button" type="button" @click="openLogin">
              登录神鹿账号
              <ArrowUpRight :size="18" />
            </button>
            <button class="quiet-button" type="button" @click="scrollToCapabilities">查看能力</button>
          </div>
        </div>

        <div class="guest-stage" aria-label="Sluvo workflow preview">
          <div class="guest-stage__beam" />
          <article v-for="node in previewNodes" :key="node.title" class="preview-node" :class="node.className">
            <span>{{ node.kind }}</span>
            <strong>{{ node.title }}</strong>
            <small>{{ node.caption }}</small>
          </article>
        </div>
      </div>

      <section id="capabilities" class="capability-band">
        <article v-for="item in capabilityCards" :key="item.title" class="capability-card">
          <component :is="item.icon" :size="24" />
          <strong>{{ item.title }}</strong>
          <span>{{ item.description }}</span>
        </article>
      </section>
    </section>

    <section v-else class="home-workbench">
      <aside class="workbench-rail" aria-label="Sluvo navigation">
        <button class="rail-logo" type="button" aria-label="Sluvo 首页" @click="scrollToTop">S</button>
        <button class="rail-tool is-active" type="button" aria-label="首页">
          <Compass :size="20" />
        </button>
        <button class="rail-tool" type="button" aria-label="项目" @click="focusProjects">
          <FolderOpen :size="20" />
        </button>
        <button class="rail-tool" type="button" aria-label="资产">
          <Image :size="20" />
        </button>
        <span class="rail-separator" />
        <button class="rail-tool rail-tool--muted" type="button" aria-label="回收站">
          <Trash2 :size="19" />
        </button>
      </aside>

      <div class="workbench-main">
        <div class="campaign-bar">
          <span>
            <Sparkles :size="16" />
            Seedance 2.0、角色一致性、分镜短片工作流已接入神鹿能力池
          </span>
          <button type="button" @click="openCanvas()">去创作</button>
        </div>

        <header class="workbench-topbar">
          <button class="home-brand home-brand--compact" type="button" @click="scrollToTop">
            <span class="home-brand__mark">S</span>
            <strong>Sluvo</strong>
          </button>

          <div class="workbench-topbar__actions">
            <button class="top-chip" type="button">
              <Globe2 :size="16" />
              简体中文
            </button>
            <button class="top-icon" type="button" aria-label="教程">
              <BookOpen :size="18" />
            </button>
            <button class="top-icon" type="button" aria-label="通知">
              <Bell :size="18" />
            </button>
            <button class="top-chip top-chip--gold" type="button">
              <Crown :size="16" />
              加入创作者计划
            </button>
            <button class="top-chip" type="button">
              <Coins :size="16" />
              116
            </button>
            <button class="avatar-pill" type="button" :title="userName">{{ userInitial }}</button>
          </div>
        </header>

        <section class="creator-console" aria-labelledby="creator-title">
          <div class="creator-console__mascot">
            <Sparkles :size="20" />
          </div>
          <h1 id="creator-title">今天想制作什么影视项目？</h1>
          <p>输入创意、粘贴剧本，或把参考图拖进来，Sluvo 会把它整理成可执行画布。</p>

          <form class="prompt-composer" @submit.prevent="openCanvas()">
            <textarea
              v-model="promptText"
              aria-label="创作描述"
              placeholder="拖拽/粘贴图片到这里，或描述：角色、剧情、分镜、风格参考"
            />
            <div class="prompt-composer__footer">
              <div class="composer-tools">
                <button v-for="tool in composerTools" :key="tool.label" type="button">
                  <component :is="tool.icon" :size="16" />
                  {{ tool.label }}
                </button>
              </div>
              <button class="send-button" type="submit" aria-label="开始生成画布">
                <Send :size="18" />
              </button>
            </div>
          </form>

          <div class="skill-strip" aria-label="快捷技能">
            <button v-for="skill in skillChips" :key="skill.label" type="button" @click="openCanvas()">
              <component :is="skill.icon" :size="16" />
              {{ skill.label }}
              <small v-if="skill.badge">{{ skill.badge }}</small>
            </button>
          </div>
        </section>

        <section ref="projectsSection" class="home-section recent-projects" aria-labelledby="recent-title">
          <div class="section-heading">
            <h2 id="recent-title">
              <Sparkles :size="22" />
              最近项目
            </h2>
            <div class="section-heading__actions">
              <button type="button" @click="openCanvas()">
                <Plus :size="16" />
                新建项目
              </button>
              <button type="button" @click="focusProjects">
                查看全部
                <ChevronRight :size="15" />
              </button>
            </div>
          </div>

          <div class="project-grid">
            <button
              v-for="(project, index) in recentProjects"
              :key="project.id"
              class="project-card"
              type="button"
              @click="openCanvas(project.id)"
            >
              <span class="project-card__preview" :class="`project-card__preview--${index + 1}`">
                <span v-for="dot in 3" :key="dot" />
              </span>
              <strong>{{ projectTitle(project, index) }}</strong>
              <small>{{ project.updatedAt }}</small>
            </button>
          </div>
        </section>

        <section class="home-section showcase-section" aria-labelledby="showcase-title">
          <div class="section-heading">
            <h2 id="showcase-title">
              <Sparkles :size="22" />
              亮点
            </h2>
            <button type="button">
              发现更多
              <ArrowUpRight :size="16" />
            </button>
          </div>

          <div class="showcase-grid">
            <article v-for="item in showcaseCards" :key="item.title" class="showcase-card" :class="item.className">
              <div class="showcase-card__media">
                <component :is="item.icon" :size="40" />
              </div>
              <div class="showcase-card__copy">
                <span>{{ item.kicker }}</span>
                <strong>{{ item.title }}</strong>
                <p>{{ item.description }}</p>
                <button type="button" @click="openCanvas()">
                  查看创作过程
                  <Play :size="15" />
                </button>
              </div>
            </article>
          </div>
        </section>
      </div>
    </section>
  </main>
</template>

<script setup>
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import {
  ArrowUpRight,
  Bell,
  BookOpen,
  ChevronRight,
  Clapperboard,
  Coins,
  Compass,
  Crown,
  Expand,
  FileText,
  Film,
  FolderOpen,
  Globe2,
  Image,
  Layers,
  LogIn,
  Palette,
  Play,
  Plus,
  Send,
  Sparkles,
  Trash2,
  Upload,
  UserRound,
  Video
} from 'lucide-vue-next'
import { createProjectSummaryList } from '../mock/projects'

const router = useRouter()
const projectsSection = ref(null)
const promptText = ref('')
const token = ref('')
const userName = ref('')
const projects = ref(createProjectSummaryList())

const isAuthenticated = computed(() => Boolean(token.value))
const recentProjects = computed(() => projects.value.slice(0, 3))
const userInitial = computed(() => (userName.value || 'S').trim().slice(0, 1).toUpperCase())

const previewNodes = [
  { kind: 'Script', title: '故事脚本', caption: '节拍与角色动机', className: 'preview-node--script' },
  { kind: 'Assets', title: '角色资产', caption: '一致性参考', className: 'preview-node--asset' },
  { kind: 'Shot', title: '分镜生成', caption: '镜头与首帧', className: 'preview-node--shot' },
  { kind: 'Video', title: '短片输出', caption: '版本审阅', className: 'preview-node--video' }
]

const capabilityCards = [
  {
    icon: FileText,
    title: '剧本到分镜',
    description: '把创意文本拆成可执行镜头和资产清单。'
  },
  {
    icon: UserRound,
    title: '角色一致性',
    description: '让角色、场景、道具在多个生成节点中复用。'
  },
  {
    icon: Video,
    title: '图片到视频',
    description: '用神鹿影视 AI 能力链生成短剧镜头和动态片段。'
  }
]

const composerTools = [
  { label: '上传', icon: Upload },
  { label: '剧本', icon: FileText },
  { label: '角色', icon: UserRound },
  { label: '分镜', icon: Clapperboard }
]

const skillChips = [
  { label: 'Seedance 2.0 故事动画', icon: Film },
  { label: '自由画布', icon: Expand, badge: '多模型' },
  { label: '剧情故事短片', icon: Clapperboard },
  { label: '角色设计', icon: UserRound }
]

const showcaseCards = [
  {
    kicker: 'Workflow',
    title: '剧情故事短片',
    description: '从故事梗概到角色资产、分镜表、首帧和视频镜头，串成一张创作画布。',
    icon: Film,
    className: 'showcase-card--story'
  },
  {
    kicker: 'Canvas',
    title: '自由画布',
    description: '像搭积木一样连接脚本、图片、音频和视频生成节点，沉淀团队工作流。',
    icon: Layers,
    className: 'showcase-card--canvas'
  },
  {
    kicker: 'Design',
    title: '角色设计',
    description: '把角色设定、三视图、表情参考和镜头引用收拢到同一个资产链路。',
    icon: Palette,
    className: 'showcase-card--character'
  }
]

function readAuthState() {
  token.value = localStorage.getItem('shenlu_token') || ''
  userName.value = localStorage.getItem('shenlu_nickname') || localStorage.getItem('shenlu_email') || 'Sluvo Creator'
}

function handleStorage(event) {
  if (['shenlu_token', 'shenlu_nickname', 'shenlu_email'].includes(event.key)) {
    readAuthState()
  }
}

function openLogin() {
  router.push('/login')
}

function openCanvas(projectId = 'proj-aurora') {
  router.push(`/projects/${projectId}/canvas`)
}

function projectTitle(project, index) {
  return ['自由画布', '剧情故事短片', '未命名项目'][index] || project.name
}

function scrollToTop() {
  window.scrollTo({ top: 0, behavior: 'smooth' })
}

function scrollToCapabilities() {
  document.getElementById('capabilities')?.scrollIntoView({ behavior: 'smooth', block: 'start' })
}

function focusProjects() {
  projectsSection.value?.scrollIntoView({ behavior: 'smooth', block: 'start' })
}

onMounted(() => {
  readAuthState()
  window.addEventListener('storage', handleStorage)
})

onBeforeUnmount(() => {
  window.removeEventListener('storage', handleStorage)
})
</script>

<style scoped>
.sluvo-home {
  min-height: 100vh;
  background:
    radial-gradient(circle at 50% -10%, rgba(214, 181, 109, 0.18), transparent 34%),
    linear-gradient(180deg, #050505 0%, #090806 58%, #030303 100%);
  color: #f9f1dc;
  overflow-x: hidden;
}

.home-guest-shell,
.home-workbench {
  min-height: 100vh;
}

.home-nav,
.workbench-topbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 20px;
}

.home-nav {
  position: sticky;
  top: 0;
  z-index: 20;
  min-height: 78px;
  padding: 16px clamp(18px, 4vw, 64px);
  border-bottom: 1px solid rgba(214, 181, 109, 0.12);
  background: rgba(5, 5, 5, 0.76);
  backdrop-filter: blur(18px);
}

.home-brand {
  display: inline-flex;
  align-items: center;
  gap: 12px;
  min-width: 0;
  padding: 0;
  background: transparent;
  color: #fff5d7;
  text-align: left;
}

.home-brand__mark,
.rail-logo,
.avatar-pill {
  display: grid;
  place-items: center;
  width: 38px;
  height: 38px;
  border: 1px solid rgba(245, 213, 145, 0.42);
  border-radius: 8px;
  background:
    linear-gradient(145deg, rgba(255, 241, 199, 0.16), rgba(214, 181, 109, 0.08)),
    #0e0b06;
  color: #ffe7a4;
  font-weight: 900;
  box-shadow: inset 0 1px 0 rgba(255, 255, 255, 0.12);
}

.home-brand strong {
  display: block;
  font-size: 20px;
  letter-spacing: 0;
}

.home-brand small {
  display: block;
  color: rgba(249, 241, 220, 0.58);
  font-size: 12px;
  font-weight: 700;
}

.home-nav__actions,
.workbench-topbar__actions,
.section-heading,
.section-heading__actions,
.composer-tools,
.skill-strip {
  display: flex;
  align-items: center;
  gap: 10px;
}

.home-nav__link,
.home-nav__primary,
.gold-button,
.quiet-button,
.top-chip,
.top-icon,
.section-heading button,
.composer-tools button,
.skill-strip button,
.showcase-card button {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 8px;
  min-height: 38px;
  border: 1px solid rgba(214, 181, 109, 0.18);
  border-radius: 8px;
  background: rgba(255, 255, 255, 0.045);
  color: #f8ecd1;
  font-size: 14px;
  font-weight: 800;
}

.home-nav__link {
  padding: 0 12px;
  color: rgba(248, 236, 209, 0.76);
}

.home-nav__primary,
.gold-button {
  padding: 0 16px;
  border-color: rgba(255, 221, 151, 0.5);
  background: linear-gradient(180deg, #f8d98e, #b88735);
  color: #1a1206;
  box-shadow: 0 16px 42px rgba(184, 135, 53, 0.22);
}

.quiet-button {
  padding: 0 16px;
}

.guest-hero {
  display: grid;
  grid-template-columns: minmax(320px, 0.82fr) minmax(380px, 1fr);
  align-items: center;
  gap: clamp(34px, 6vw, 86px);
  min-height: calc(100vh - 78px);
  padding: clamp(42px, 8vw, 110px) clamp(18px, 6vw, 92px);
}

.guest-hero__copy {
  max-width: 680px;
  animation: home-rise 0.58s ease both;
}

.guest-hero__eyebrow {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  min-height: 34px;
  padding: 0 12px;
  border: 1px solid rgba(214, 181, 109, 0.24);
  border-radius: 8px;
  background: rgba(214, 181, 109, 0.08);
  color: #f3d894;
  font-size: 13px;
  font-weight: 900;
}

.guest-hero h1 {
  margin: 22px 0 12px;
  color: #fff8e6;
  font-size: clamp(76px, 13vw, 178px);
  font-weight: 950;
  line-height: 0.82;
  letter-spacing: 0;
}

.guest-hero__lead {
  max-width: 560px;
  margin: 0;
  color: rgba(255, 248, 230, 0.78);
  font-size: clamp(19px, 2vw, 30px);
  font-weight: 800;
  line-height: 1.38;
}

.guest-hero__actions {
  display: flex;
  flex-wrap: wrap;
  gap: 12px;
  margin-top: 34px;
}

.guest-stage {
  position: relative;
  min-height: 520px;
  overflow: hidden;
  border: 1px solid rgba(214, 181, 109, 0.18);
  border-radius: 8px;
  background:
    linear-gradient(rgba(214, 181, 109, 0.08) 1px, transparent 1px),
    linear-gradient(90deg, rgba(214, 181, 109, 0.08) 1px, transparent 1px),
    radial-gradient(circle at 52% 44%, rgba(214, 181, 109, 0.18), transparent 42%),
    #070706;
  background-size: 44px 44px, 44px 44px, auto, auto;
  box-shadow: inset 0 1px 0 rgba(255, 255, 255, 0.06), 0 34px 90px rgba(0, 0, 0, 0.42);
  animation: home-rise 0.68s 0.08s ease both;
}

.guest-stage__beam {
  position: absolute;
  top: 50%;
  right: 14%;
  left: 18%;
  height: 2px;
  background: linear-gradient(90deg, transparent, #d6b56d, transparent);
  box-shadow: 0 0 22px rgba(214, 181, 109, 0.7);
}

.preview-node {
  position: absolute;
  display: grid;
  gap: 7px;
  width: 190px;
  padding: 16px;
  border: 1px solid rgba(214, 181, 109, 0.28);
  border-radius: 8px;
  background: rgba(19, 16, 11, 0.92);
  box-shadow: 0 18px 42px rgba(0, 0, 0, 0.42);
}

.preview-node span {
  color: #d6b56d;
  font-size: 12px;
  font-weight: 900;
  text-transform: uppercase;
}

.preview-node strong {
  color: #fff5d7;
  font-size: 18px;
}

.preview-node small {
  color: rgba(249, 241, 220, 0.58);
  font-size: 13px;
  font-weight: 700;
}

.preview-node--script {
  top: 16%;
  left: 8%;
}

.preview-node--asset {
  top: 20%;
  right: 10%;
}

.preview-node--shot {
  bottom: 18%;
  left: 18%;
}

.preview-node--video {
  right: 16%;
  bottom: 16%;
}

.capability-band {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 16px;
  padding: 0 clamp(18px, 6vw, 92px) 80px;
}

.capability-card {
  display: grid;
  gap: 10px;
  min-height: 168px;
  padding: 22px;
  border: 1px solid rgba(214, 181, 109, 0.16);
  border-radius: 8px;
  background: rgba(255, 255, 255, 0.04);
}

.capability-card svg {
  color: #d6b56d;
}

.capability-card strong {
  color: #fff5d7;
  font-size: 20px;
}

.capability-card span {
  color: rgba(249, 241, 220, 0.62);
  font-size: 14px;
  line-height: 1.6;
}

.home-workbench {
  display: grid;
  grid-template-columns: 76px 1fr;
  background: #050505;
}

.workbench-rail {
  position: sticky;
  top: 0;
  z-index: 15;
  display: flex;
  align-items: center;
  flex-direction: column;
  gap: 12px;
  height: 100vh;
  padding: 18px 12px;
  border-right: 1px solid rgba(214, 181, 109, 0.12);
  background: rgba(13, 11, 7, 0.96);
}

.rail-logo {
  margin-bottom: 18px;
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

.workbench-main {
  min-width: 0;
  padding-bottom: 64px;
}

.campaign-bar {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 14px;
  min-height: 46px;
  padding: 8px 18px;
  border-bottom: 1px solid rgba(214, 181, 109, 0.1);
  background:
    linear-gradient(90deg, rgba(214, 181, 109, 0.04), rgba(214, 181, 109, 0.14), rgba(214, 181, 109, 0.04)),
    #090706;
  color: #fff1c7;
  font-size: 14px;
  font-weight: 900;
}

.campaign-bar span {
  display: inline-flex;
  align-items: center;
  gap: 8px;
}

.campaign-bar button {
  min-height: 26px;
  padding: 0 12px;
  border-radius: 999px;
  background: #d6b56d;
  color: #171006;
  font-size: 12px;
  font-weight: 900;
}

.workbench-topbar {
  min-height: 78px;
  padding: 16px clamp(18px, 5vw, 72px);
}

.home-brand--compact small {
  display: none;
}

.top-chip,
.top-icon,
.avatar-pill {
  min-height: 34px;
  padding: 0 12px;
  border-color: rgba(214, 181, 109, 0.14);
  background: rgba(255, 255, 255, 0.06);
}

.top-icon,
.avatar-pill {
  width: 38px;
  padding: 0;
}

.top-chip--gold {
  border-color: rgba(255, 221, 151, 0.42);
  background: rgba(214, 181, 109, 0.16);
  color: #fff1c7;
}

.creator-console,
.home-section {
  width: min(960px, calc(100vw - 140px));
  margin: 0 auto;
}

.creator-console {
  position: relative;
  display: grid;
  justify-items: center;
  padding: 40px 0 30px;
  text-align: center;
}

.creator-console__mascot {
  display: grid;
  place-items: center;
  width: 50px;
  height: 50px;
  margin-bottom: 14px;
  border-radius: 8px;
  background: rgba(214, 181, 109, 0.12);
  color: #d6b56d;
  box-shadow: 0 0 36px rgba(214, 181, 109, 0.18);
}

.creator-console h1 {
  margin: 0 0 10px;
  color: #fff8e6;
  font-size: clamp(30px, 4vw, 52px);
  letter-spacing: 0;
}

.creator-console p {
  max-width: 620px;
  margin: 0 0 24px;
  color: rgba(249, 241, 220, 0.62);
  font-size: 15px;
  font-weight: 700;
}

.prompt-composer {
  position: relative;
  width: min(640px, 100%);
  overflow: hidden;
  border: 1px solid rgba(255, 231, 164, 0.48);
  border-radius: 8px;
  background:
    linear-gradient(180deg, rgba(255, 255, 255, 0.035), transparent 42%),
    #0d0b07;
  box-shadow:
    inset 0 1px 0 rgba(255, 255, 255, 0.08),
    0 24px 80px rgba(0, 0, 0, 0.34),
    0 0 42px rgba(214, 181, 109, 0.12);
}

.prompt-composer::before {
  position: absolute;
  inset: 0;
  background: linear-gradient(110deg, transparent 0%, rgba(255, 241, 199, 0.12) 42%, transparent 58%);
  content: "";
  transform: translateX(-100%);
  animation: composer-sheen 4s ease-in-out infinite;
}

.prompt-composer textarea {
  position: relative;
  z-index: 1;
  width: 100%;
  min-height: 126px;
  padding: 18px 18px 10px;
  border: 0;
  outline: none;
  background: transparent;
  color: #fff8e6;
  resize: vertical;
}

.prompt-composer textarea::placeholder {
  color: rgba(249, 241, 220, 0.45);
}

.prompt-composer__footer {
  position: relative;
  z-index: 1;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  padding: 0 10px 10px;
}

.composer-tools {
  flex-wrap: wrap;
}

.composer-tools button,
.skill-strip button {
  min-height: 32px;
  padding: 0 10px;
  border-radius: 8px;
  background: rgba(255, 255, 255, 0.06);
  color: rgba(249, 241, 220, 0.78);
  font-size: 12px;
}

.send-button {
  display: grid;
  place-items: center;
  width: 38px;
  height: 38px;
  border-radius: 8px;
  background: linear-gradient(180deg, #d6b56d, #9f722c);
  color: #160f06;
}

.skill-strip {
  justify-content: center;
  flex-wrap: wrap;
  margin-top: 16px;
}

.skill-strip button:first-child {
  color: #fff1c7;
  box-shadow: 0 0 30px rgba(214, 181, 109, 0.16);
}

.skill-strip small {
  padding: 1px 5px;
  border-radius: 4px;
  background: rgba(214, 181, 109, 0.22);
  color: #fff1c7;
}

.home-section {
  padding-top: 36px;
}

.section-heading {
  justify-content: space-between;
  margin-bottom: 16px;
}

.section-heading h2 {
  display: flex;
  align-items: center;
  gap: 9px;
  margin: 0;
  color: #fff8e6;
  font-size: 26px;
}

.section-heading h2 svg {
  color: #d6b56d;
}

.section-heading button {
  min-height: 32px;
  padding: 0 10px;
  background: rgba(255, 255, 255, 0.055);
  color: rgba(249, 241, 220, 0.78);
  font-size: 12px;
}

.project-grid {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 16px;
}

.project-card {
  display: grid;
  gap: 8px;
  min-width: 0;
  padding: 8px 8px 14px;
  border: 1px solid rgba(214, 181, 109, 0.12);
  border-radius: 8px;
  background: rgba(255, 255, 255, 0.055);
  color: #fff8e6;
  text-align: left;
  transition:
    transform 0.18s ease,
    border-color 0.18s ease,
    background 0.18s ease;
}

.project-card:hover,
.showcase-card:hover {
  border-color: rgba(214, 181, 109, 0.34);
  background: rgba(214, 181, 109, 0.075);
  transform: translateY(-3px);
}

.project-card__preview {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 4px;
  height: 88px;
  padding: 8px;
  border-radius: 6px;
  background: #24211b;
}

.project-card__preview span {
  border-radius: 5px;
  background:
    linear-gradient(180deg, rgba(255, 255, 255, 0.16), transparent),
    var(--preview-fill, #7f6740);
}

.project-card__preview--1 {
  --preview-fill: linear-gradient(145deg, #caa466, #5f4220);
}

.project-card__preview--2 {
  --preview-fill: linear-gradient(145deg, #8f7a51, #24201a);
}

.project-card__preview--3 {
  --preview-fill: linear-gradient(145deg, #4f4636, #1b1a18);
}

.project-card strong {
  padding: 0 4px;
  overflow: hidden;
  font-size: 16px;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.project-card small {
  padding: 0 4px;
  color: rgba(249, 241, 220, 0.5);
  font-size: 12px;
}

.showcase-grid {
  display: grid;
  grid-template-columns: 1.2fr 0.95fr;
  gap: 16px;
}

.showcase-card {
  position: relative;
  display: grid;
  min-height: 250px;
  overflow: hidden;
  border: 1px solid rgba(214, 181, 109, 0.12);
  border-radius: 8px;
  background: rgba(255, 255, 255, 0.055);
  transition:
    transform 0.18s ease,
    border-color 0.18s ease,
    background 0.18s ease;
}

.showcase-card:first-child {
  grid-row: span 2;
  min-height: 516px;
}

.showcase-card__media {
  position: absolute;
  inset: 0;
  display: grid;
  place-items: center;
  background:
    radial-gradient(circle at 50% 34%, rgba(255, 241, 199, 0.22), transparent 28%),
    linear-gradient(135deg, rgba(214, 181, 109, 0.12), rgba(30, 24, 14, 0.92));
  color: rgba(255, 241, 199, 0.42);
  transition: transform 0.2s ease;
}

.showcase-card:hover .showcase-card__media {
  transform: scale(1.03);
}

.showcase-card--canvas .showcase-card__media {
  background:
    linear-gradient(rgba(214, 181, 109, 0.1) 1px, transparent 1px),
    linear-gradient(90deg, rgba(214, 181, 109, 0.1) 1px, transparent 1px),
    radial-gradient(circle at 50% 40%, rgba(214, 181, 109, 0.2), transparent 34%),
    #16130c;
  background-size: 34px 34px, 34px 34px, auto, auto;
}

.showcase-card--character .showcase-card__media {
  background:
    radial-gradient(circle at 72% 24%, rgba(255, 241, 199, 0.18), transparent 24%),
    linear-gradient(145deg, #2a2114, #080806);
}

.showcase-card__copy {
  position: relative;
  z-index: 1;
  display: grid;
  align-content: end;
  gap: 9px;
  min-height: 100%;
  padding: 24px;
  background: linear-gradient(180deg, transparent 24%, rgba(0, 0, 0, 0.78) 100%);
}

.showcase-card__copy span {
  color: #d6b56d;
  font-size: 12px;
  font-weight: 900;
  text-transform: uppercase;
}

.showcase-card__copy strong {
  color: #fff8e6;
  font-size: clamp(24px, 3vw, 42px);
  line-height: 1.1;
}

.showcase-card__copy p {
  max-width: 540px;
  margin: 0;
  color: rgba(249, 241, 220, 0.66);
  font-size: 14px;
  line-height: 1.6;
}

.showcase-card button {
  justify-self: start;
  min-height: 34px;
  padding: 0 12px;
  background: rgba(255, 255, 255, 0.08);
}

@keyframes home-rise {
  from {
    opacity: 0;
    transform: translateY(18px);
  }

  to {
    opacity: 1;
    transform: translateY(0);
  }
}

@keyframes composer-sheen {
  0%,
  55% {
    transform: translateX(-100%);
  }

  100% {
    transform: translateX(100%);
  }
}

@media (max-width: 1180px) {
  .guest-hero {
    grid-template-columns: 1fr;
  }

  .guest-stage {
    min-height: 440px;
  }

  .creator-console,
  .home-section {
    width: min(820px, calc(100vw - 116px));
  }

  .workbench-topbar {
    align-items: flex-start;
    flex-direction: column;
  }

  .workbench-topbar__actions {
    flex-wrap: wrap;
  }
}

@media (max-width: 820px) {
  .home-nav,
  .workbench-topbar,
  .campaign-bar {
    align-items: flex-start;
    flex-direction: column;
  }

  .home-nav__actions {
    flex-wrap: wrap;
  }

  .capability-band,
  .project-grid,
  .showcase-grid {
    grid-template-columns: 1fr;
  }

  .home-workbench {
    grid-template-columns: 1fr;
  }

  .workbench-rail {
    position: sticky;
    top: 0;
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

  .rail-tool--muted {
    margin-top: 0;
    margin-left: auto;
  }

  .creator-console,
  .home-section {
    width: calc(100vw - 32px);
  }

  .showcase-card:first-child {
    min-height: 330px;
  }
}

@media (max-width: 560px) {
  .guest-hero {
    padding-top: 34px;
  }

  .guest-stage {
    min-height: 420px;
  }

  .preview-node {
    width: 150px;
    padding: 12px;
  }

  .preview-node--asset {
    right: 4%;
  }

  .preview-node--shot {
    left: 6%;
  }

  .preview-node--video {
    right: 5%;
  }

  .prompt-composer__footer {
    align-items: flex-start;
    flex-direction: column;
  }

  .send-button {
    align-self: flex-end;
  }

  .section-heading {
    align-items: flex-start;
    flex-direction: column;
  }
}
</style>
