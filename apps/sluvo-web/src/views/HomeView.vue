<template>
  <main class="sluvo-home" :class="{ 'is-authed': isAuthenticated }">
    <section v-if="!isAuthenticated" class="home-guest-shell">
      <nav class="home-nav" aria-label="Sluvo">
        <button class="home-brand" type="button" @click="scrollToTop">
          <span class="home-brand__mark">
            <img :src="logoUrl" alt="" />
          </span>
          <span>
            <strong>Sluvo</strong>
          </span>
        </button>

        <div class="home-nav__actions">
          <button class="home-nav__link" type="button" @click="scrollToCapabilities">能力</button>
          <button class="home-nav__link" type="button" @click="openCanvas()">自由画布</button>
          <button class="home-nav__primary" type="button" @click="openLogin">
            <LogIn :size="17" />
            登录 Sluvo
          </button>
        </div>
      </nav>

      <div class="guest-hero">
        <div class="guest-hero__copy">
          <span class="guest-hero__eyebrow">
            <Sparkles :size="16" />
            开放式AI Agent 无限画布创作平台
          </span>
          <h1>Sluvo</h1>
          <p class="guest-hero__lead">把灵感、角色、分镜、模型与 Agent 团队放进同一张无限画布。Sluvo 让创作过程可以被记录、复用、分享，并在社区中生长为新的画布、Agent 与 Skill。</p>
          <div class="guest-hero__actions">
            <button class="gold-button" type="button" @click="openLogin">
              进入 Sluvo
              <ArrowUpRight :size="18" />
            </button>
            <button class="quiet-button" type="button" @click="scrollToCapabilities">查看开放生态</button>
          </div>
        </div>

        <div class="guest-stage" aria-label="Sluvo workflow preview">
          <div class="guest-stage__beam" />
          <div class="guest-stage__beam guest-stage__beam--vertical" />
          <article
            v-for="node in previewNodes"
            :key="node.title"
            class="preview-node"
            :class="node.className"
            tabindex="0"
          >
            <span>{{ node.kind }}</span>
            <strong>{{ node.title }}</strong>
            <small>{{ node.caption }}</small>
            <em>{{ node.signal }}</em>
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
        <button class="rail-logo" type="button" aria-label="Sluvo 首页" @click="scrollToTop">
          <img :src="logoUrl" alt="" />
        </button>
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
            Sluvo 正在构建开放画布社区：创作过程、Agent 团队与画布 Skill 都将可以分享、fork 和复用。
          </span>
          <button type="button" :disabled="isCreatingProject" @click="startProjectFromPrompt()">开启我的画布</button>
        </div>

        <header class="workbench-topbar">
          <button class="home-brand home-brand--compact" type="button" @click="scrollToTop">
            <span class="home-brand__mark">
              <img :src="logoUrl" alt="" />
            </span>
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
            <button class="top-chip" type="button" title="灵感值余额">
              <Coins :size="16" />
              {{ pointsLabel }}
            </button>
            <button class="avatar-pill" type="button" :title="userName">{{ userInitial }}</button>
            <button class="top-chip top-chip--logout" type="button" @click="logout">
              <LogOut :size="16" />
              退出登录
            </button>
          </div>
        </header>

        <section class="creator-console" aria-labelledby="creator-title">
          <div class="creator-stage">
            <div class="creator-media-layer" aria-hidden="true">
              <article
                v-for="card in heroMediaCards"
                :key="card.title"
                class="hero-media-card"
                :class="card.className"
                :style="{ '--card-accent': card.accent }"
                @mouseenter="playPreviewVideo"
                @mouseleave="pausePreviewVideo"
              >
                <span class="hero-media-card__visual">
                  <video
                    v-if="card.videoUrl"
                    muted
                    loop
                    playsinline
                    preload="metadata"
                    :poster="card.posterUrl || card.imageUrl"
                  >
                    <source :src="card.videoUrl" type="video/mp4" />
                  </video>
                  <img v-else :src="card.imageUrl" alt="" loading="lazy" />
                </span>
                <span class="hero-media-card__kind">{{ card.kind }}</span>
                <strong>{{ card.title }}</strong>
                <small>{{ card.description }}</small>
              </article>
            </div>

            <div class="creator-console__content">
              <div class="creator-console__mascot">
                <Sparkles :size="20" />
              </div>
              <h1 id="creator-title">导演～今天想创作什么影视项目？</h1>
              <p>输入创意、粘贴剧本，或上传参考素材。Sluvo 会把它整理成可执行画布，并逐步沉淀为可复用、可分享的创作流程。</p>

              <form class="prompt-composer" @submit.prevent="startProjectFromPrompt()">
                <textarea
                  v-model="promptText"
                  aria-label="创作描述"
                  placeholder="描述一个漫剧创意、角色设定、分镜目标，或你想构建的 Agent / Skill 工作流"
                />
                <div class="prompt-composer__footer">
                  <div class="composer-tools">
                    <button v-for="tool in composerTools" :key="tool.label" type="button">
                      <component :is="tool.icon" :size="16" />
                      {{ tool.label }}
                    </button>
                  </div>
                  <button class="send-button" type="submit" :disabled="isCreatingProject" aria-label="开始生成画布">
                    <Send :size="18" />
                  </button>
                </div>
              </form>
              <p v-if="projectFeedback" class="creator-console__feedback">{{ projectFeedback }}</p>

              <div class="skill-strip" aria-label="快捷技能">
                <button v-for="skill in skillChips" :key="skill.label" type="button" :disabled="isCreatingProject" @click="startProjectFromPrompt(skill.label)">
                  <component :is="skill.icon" :size="16" />
                  {{ skill.label }}
                  <small v-if="skill.badge">{{ skill.badge }}</small>
                </button>
              </div>
            </div>
          </div>
        </section>

        <section class="home-section showcase-section" aria-labelledby="showcase-title">
          <div class="section-heading section-heading--stacked">
            <h2 id="showcase-title">
              <Film :size="22" />
              灵感样片
            </h2>
            <p>从官方样片开始，把风格、角色和分镜拆成你的下一张画布。</p>
          </div>

          <div class="showcase-carousel" aria-label="灵感样片" @mouseenter="stopShowcaseRotation" @mouseleave="startShowcaseRotation">
            <article
              v-for="(item, index) in visibleShowcaseItems"
              :key="item.title"
              class="showcase-card"
              :class="{ 'showcase-card--primary': index === 0 }"
              tabindex="0"
              :style="{ '--card-accent': item.accent }"
              @click="startProjectFromPrompt(item.promptSeed)"
              @keydown.enter.prevent="startProjectFromPrompt(item.promptSeed)"
              @keydown.space.prevent="startProjectFromPrompt(item.promptSeed)"
              @mouseenter="playPreviewVideo"
              @mouseleave="pausePreviewVideo"
              @focusin="playPreviewVideo"
              @focusout="pausePreviewVideo"
            >
              <span class="showcase-card__media">
                <video
                  v-if="item.videoUrl"
                  muted
                  loop
                  playsinline
                  preload="metadata"
                  :poster="item.posterUrl || item.imageUrl"
                >
                  <source :src="item.videoUrl" type="video/mp4" />
                </video>
                <img :src="item.imageUrl" :alt="item.title" loading="lazy" />
              </span>
              <span class="showcase-card__meta">{{ item.kind }}</span>
              <strong>{{ item.title }}</strong>
              <p>{{ item.description }}</p>
              <button type="button" :disabled="isCreatingProject" @click.stop="startProjectFromPrompt(item.promptSeed)">用这个风格开始</button>
            </article>
          </div>

          <div class="showcase-dots" aria-label="切换灵感样片">
            <button
              v-for="(item, index) in showcaseItems"
              :key="item.title"
              type="button"
              :class="{ 'is-active': index === activeShowcaseIndex }"
              :aria-label="`显示${item.title}`"
              @click="selectShowcase(index)"
            />
          </div>
        </section>

        <section ref="projectsSection" class="home-section recent-projects" aria-labelledby="recent-title">
          <div class="section-heading section-heading--stacked">
            <h2 id="recent-title">
              <Sparkles :size="22" />
              最近创作
            </h2>
            <p>继续你的画布，或把一次创作过程沉淀为可分享资产。</p>
          </div>

          <p v-if="projectStore.error" class="home-section__error">{{ projectStore.error }}</p>

          <div v-if="projectStore.loadingProjects" class="project-grid">
            <article v-for="item in 3" :key="item" class="project-card project-card--loading">
              <span class="project-card__preview project-card__preview--empty" />
              <strong>加载中</strong>
              <small>正在同步 Sluvo 项目</small>
            </article>
          </div>

          <div v-else class="project-grid">
            <button
              class="project-card project-card--empty"
              type="button"
              :disabled="isCreatingProject"
              @click="startProjectFromPrompt()"
            >
              <span class="project-card__preview project-card__preview--empty">
                <span class="project-card__create-icon">
                  <Plus :size="24" />
                </span>
              </span>
              <strong>新建项目</strong>
              <small>创建一个 Sluvo 画布</small>
            </button>
            <article
              v-for="project in projectStore.projects"
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
                <img
                  v-if="getProjectCover(project)"
                  :src="getProjectCover(project)"
                  :alt="project.title || '未命名画布'"
                  loading="lazy"
                />
                <span v-else class="project-card__no-cover">无封面</span>
              </span>
              <button
                class="project-card__delete"
                type="button"
                :disabled="deletingProjectIds.has(project.id)"
                :title="`删除 ${project.title || '未命名画布'}`"
                aria-label="删除项目"
                @click.stop="deleteProject(project)"
              >
                <Trash2 :size="16" />
              </button>
              <strong>{{ project.title || '未命名画布' }}</strong>
              <small>{{ formatProjectMeta(project) }}</small>
            </article>
          </div>
        </section>

        <section class="home-section open-ecosystem" aria-labelledby="ecosystem-title">
          <div class="section-heading section-heading--stacked">
            <h2 id="ecosystem-title">
              <Sparkles :size="22" />
              开放生态目标
            </h2>
            <p>Sluvo 会把个人创作升级为可复用的社区资产。</p>
          </div>

          <div class="open-ecosystem-grid">
            <article v-for="item in ecosystemVisualCards" :key="item.title" class="open-ecosystem-card">
              <span class="open-ecosystem-card__visual">
                <video
                  v-if="item.videoUrl"
                  muted
                  loop
                  playsinline
                  preload="metadata"
                  :poster="item.posterUrl || item.imageUrl"
                  @mouseenter="playPreviewVideo"
                  @mouseleave="pausePreviewVideo"
                  @focusin="playPreviewVideo"
                  @focusout="pausePreviewVideo"
                >
                  <source :src="item.videoUrl" type="video/mp4" />
                </video>
                <img v-else :src="item.imageUrl" :alt="item.title" loading="lazy" />
              </span>
              <span class="open-ecosystem-card__icon">
                <component :is="item.icon" :size="20" />
              </span>
              <strong>{{ item.title }}</strong>
              <p>{{ item.description }}</p>
            </article>
          </div>

          <div class="open-ecosystem-cta">
            <span>从今天的每一次创作开始，积累未来可分享的创作资产。</span>
            <button type="button" :disabled="isCreatingProject" @click="startProjectFromPrompt()">创建开放画布</button>
          </div>
        </section>

        <section class="home-section agent-section" aria-labelledby="agent-title">
          <div class="section-heading">
            <h2 id="agent-title">
              <Sparkles :size="22" />
              Agent 能力栈
            </h2>
          </div>

          <div class="agent-panel">
            <article class="agent-primary">
              <span class="agent-primary__eyebrow">Sluvo Agent Team</span>
              <h3>让每个创作者都能组建自己的漫剧 Agent 团队</h3>
              <p>Sluvo 会让 Agent 读取画布上下文、理解节点关系、提出下一步动作，并把一套有效的协作方式保存为可分享的团队模板。</p>
              <div class="agent-flow" aria-label="Agent workflow steps">
                <span>理解</span>
                <span>分工</span>
                <span>执行</span>
                <span>沉淀</span>
              </div>
            </article>

            <div class="agent-capability-list">
              <article v-for="item in agentCapabilities" :key="item.title" class="agent-capability">
                <span class="agent-capability__icon">
                  <component :is="item.icon" :size="20" />
                </span>
                <div>
                  <strong>{{ item.title }}</strong>
                  <p>{{ item.description }}</p>
                </div>
              </article>
            </div>
          </div>
        </section>
      </div>
    </section>
  </main>
</template>

<script setup>
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import {
  ArrowUpRight,
  Bell,
  BookOpen,
  Boxes,
  Clapperboard,
  Coins,
  Compass,
  Crown,
  Expand,
  FileText,
  Film,
  FolderOpen,
  Globe2,
  GitFork,
  Image,
  Layers,
  LogIn,
  LogOut,
  Network,
  PackageOpen,
  Plus,
  Share2,
  Send,
  Sparkles,
  Trash2,
  Upload,
  UserRound,
  UsersRound
} from 'lucide-vue-next'
import logoUrl from '../../LOGO.png'
import { useAuthStore } from '../stores/authStore'
import { useProjectStore } from '../stores/projectStore'
import { fetchUserDashboard } from '../api/authApi'
import { saveSluvoCanvasBatch } from '../api/sluvoApi'

const router = useRouter()
const authStore = useAuthStore()
const projectStore = useProjectStore()
const projectsSection = ref(null)
const promptText = ref('')
const projectFeedback = ref('')
const deletingProjectIds = ref(new Set())
const activeShowcaseIndex = ref(0)
let showcaseRotationTimer = null
const accountPoints = ref(0)

const isAuthenticated = computed(() => authStore.isAuthenticated)
const isCreatingProject = computed(() => projectStore.creatingProject)
const userName = computed(() => authStore.displayName)
const userInitial = computed(() => authStore.userInitial)
const visibleShowcaseItems = computed(() => {
  return [0, 1, 2]
    .map((offset) => showcaseItems[(activeShowcaseIndex.value + offset) % showcaseItems.length])
    .filter(Boolean)
})

const remoteMedia = {
  character: 'https://shenlu1.oss-cn-beijing.aliyuncs.com/static-repo/sluvo/home/showcase/v1/hero-character-board.webp',
  storyboard: 'https://shenlu1.oss-cn-beijing.aliyuncs.com/static-repo/sluvo/home/showcase/v1/hero-storyboard-board.webp',
  firstFrame: 'https://shenlu1.oss-cn-beijing.aliyuncs.com/static-repo/sluvo/home/showcase/v1/hero-first-frame.webp',
  filmPreview: 'https://images.unsplash.com/photo-1485846234645-a62644f84728?auto=format&fit=crop&w=900&q=82',
  agentQueue: 'https://shenlu1.oss-cn-beijing.aliyuncs.com/static-repo/sluvo/home/showcase/v1/agent-team-planning-cover.webp',
  skillPack: 'https://images.unsplash.com/photo-1526498460520-4c246339dccb?auto=format&fit=crop&w=900&q=82',
  palace: 'https://images.unsplash.com/photo-1528181304800-259b08848526?auto=format&fit=crop&w=900&q=82',
  cyber: 'https://images.unsplash.com/photo-1519608487953-e999c86e7455?auto=format&fit=crop&w=900&q=82',
  portrait: 'https://images.unsplash.com/photo-1494790108377-be9c29b29330?auto=format&fit=crop&w=900&q=82',
  music: 'https://images.unsplash.com/photo-1511379938547-c1f69419868d?auto=format&fit=crop&w=900&q=82',
  commerce: 'https://images.unsplash.com/photo-1492684223066-81342ee5ff30?auto=format&fit=crop&w=900&q=82',
  canvasMap: 'https://images.unsplash.com/photo-1516321318423-f06f85e504b3?auto=format&fit=crop&w=900&q=82',
  videoPreview: 'https://shenlu1.oss-cn-beijing.aliyuncs.com/static-repo/sluvo/home/showcase/v1/video-first-frame.mp4',
  motionPreview: 'https://commondatastorage.googleapis.com/gtv-videos-bucket/sample/ForBiggerBlazes.mp4'
}

const heroMediaCards = [
  {
    kind: 'Character Board',
    title: '角色三视图',
    description: '设定、服装、表情统一在同一张创作画布。',
    imageUrl: remoteMedia.character,
    accent: '#f2c879',
    className: 'hero-media-card--character'
  },
  {
    kind: 'Storyboard',
    title: '分镜板',
    description: '镜头顺序、动作节奏和画面参考一眼可见。',
    imageUrl: remoteMedia.storyboard,
    accent: '#caa466',
    className: 'hero-media-card--storyboard'
  },
  {
    kind: 'First Frame',
    title: '首帧图生视频',
    description: '从关键画面推进到动态短剧镜头。',
    imageUrl: remoteMedia.firstFrame,
    posterUrl: remoteMedia.firstFrame,
    videoUrl: remoteMedia.videoPreview,
    accent: '#9fd8ff',
    className: 'hero-media-card--firstframe'
  },
  {
    kind: 'Preview',
    title: '漫剧成片预览',
    description: '让样片和生成结果回到画布继续迭代。',
    imageUrl: remoteMedia.filmPreview,
    posterUrl: remoteMedia.filmPreview,
    videoUrl: remoteMedia.motionPreview,
    accent: '#ffcf8a',
    className: 'hero-media-card--preview'
  },
  {
    kind: 'Agent Queue',
    title: 'Agent 正在规划',
    description: '导演、编剧、分镜、美术各自推进下一步。',
    imageUrl: remoteMedia.agentQueue,
    accent: '#d6b56d',
    className: 'hero-media-card--agent'
  },
  {
    kind: 'Skill Pack',
    title: '画布 Skill 包',
    description: '把高频流程保存为可安装的创作方法。',
    imageUrl: remoteMedia.skillPack,
    accent: '#e6d6a7',
    className: 'hero-media-card--skill'
  }
]

const showcaseItems = [
  {
    kind: '古风短剧',
    title: '宫墙夜雨',
    description: '从角色关系到宫廷分镜，快速生成一条古风剧情链路。',
    imageUrl: remoteMedia.palace,
    promptSeed: '古风短剧：宫墙夜雨，女主在雨夜宫墙边发现密信，生成角色设定、三幕剧情、分镜和首帧视频链路。',
    accent: '#d6b56d'
  },
  {
    kind: '赛博漫剧',
    title: '霓虹追逃',
    description: '霓虹城市、机械义体和高节奏镜头组合成短剧样片。',
    imageUrl: remoteMedia.cyber,
    posterUrl: remoteMedia.cyber,
    videoUrl: remoteMedia.motionPreview,
    promptSeed: '赛博漫剧：霓虹追逃，义体侦探在雨夜城市追踪失控 AI，生成视觉风格、角色、分镜和视频镜头。',
    accent: '#9fd8ff'
  },
  {
    kind: '角色设定集',
    title: '双主角设定',
    description: '生成主角、反派、服装、表情和角色一致性参考。',
    imageUrl: remoteMedia.portrait,
    promptSeed: '角色设定集：双主角漫剧，生成男女主外貌、服装、三视图、表情包和一致性参考。',
    accent: '#f0b982'
  },
  {
    kind: '分镜到成片',
    title: '镜头推进',
    description: '从分镜表开始，把镜头说明拆成图片和视频生成节点。',
    imageUrl: remoteMedia.filmPreview,
    posterUrl: remoteMedia.filmPreview,
    videoUrl: remoteMedia.videoPreview,
    promptSeed: '分镜到成片：根据一场追逐戏生成 8 格分镜、首帧图、镜头运动和图生视频链路。',
    accent: '#fff1c7'
  },
  {
    kind: '音乐剧情短片',
    title: '雨夜独白',
    description: '把音乐情绪、旁白和镜头节奏整理成可执行画布。',
    imageUrl: remoteMedia.music,
    promptSeed: '音乐剧情短片：雨夜独白，围绕一段低沉钢琴曲生成旁白、镜头节奏、画面风格和视频片段。',
    accent: '#c7a7ff'
  },
  {
    kind: '广告剧情片',
    title: '新品一分钟',
    description: '把产品卖点写成剧情，用分镜和视频节点输出短片。',
    imageUrl: remoteMedia.commerce,
    promptSeed: '广告剧情片：新品一分钟，将产品卖点转成三幕剧情、人物场景、分镜脚本和视频生成节点。',
    accent: '#ffcf8a'
  }
]
const pointsLabel = computed(() => formatPointValue(accountPoints.value))

const previewNodes = [
  {
    kind: 'Open Canvas',
    title: '创作过程可分享',
    caption: '把画布中的灵感、节点、依赖与生成路径发布到社区',
    signal: 'Share / Fork',
    className: 'preview-node--script'
  },
  {
    kind: 'Agent Team',
    title: '漫剧团队可编排',
    caption: '自定义导演、编剧、分镜、角色、生成等 Agent 分工',
    signal: 'Plan / Execute',
    className: 'preview-node--asset'
  },
  {
    kind: 'Canvas Skill',
    title: '画布技能可沉淀',
    caption: '把一组节点和流程保存为可安装、可复用的 Skill',
    signal: 'Build / Reuse',
    className: 'preview-node--shot'
  },
  {
    kind: 'Community',
    title: '创作者网络可共生',
    caption: '从他人的作品、Agent 和 Skill 中 fork 出新的创作路径',
    signal: 'Publish / Remix',
    className: 'preview-node--video'
  }
]

const capabilityCards = [
  {
    icon: Share2,
    title: '开放画布',
    description: '记录从灵感到成片的完整创作过程。节点、素材、分镜、生成历史和依赖关系都可以成为可分享的作品资产。'
  },
  {
    icon: UsersRound,
    title: '开放 Agent',
    description: '让用户组建自己的漫剧 Agent 团队：导演、编剧、角色设定、分镜、美术、视频生成，都可以被配置、协作和分享。'
  },
  {
    icon: PackageOpen,
    title: '开放 Skill',
    description: '把高频创作方法沉淀成画布 Skill。一个 Skill 可以是一套节点模板、一段 Agent 流程，也可以是一条可复用的生产链。'
  },
  {
    icon: GitFork,
    title: '社区共创',
    description: '用户可以发布、fork、收藏和安装他人的画布、Agent 团队与 Skill，让创作经验在社区里持续复用。'
  }
]

const composerTools = [
  { label: '上传', icon: Upload },
  { label: '剧本', icon: FileText },
  { label: '角色', icon: UserRound },
  { label: '分镜', icon: Clapperboard }
]

const skillChips = [
  { label: '漫剧世界观生成', icon: Film },
  { label: '角色 Agent 团队', icon: UsersRound },
  { label: '分镜到视频链路', icon: Clapperboard },
  { label: '保存为画布 Skill', icon: PackageOpen },
  { label: '社区画布灵感', icon: Expand, badge: '多模型' }
]

const ecosystemVisualCards = [
  {
    title: '画布可以发布',
    description: '把一次完整创作过程发布为社区画布。其他创作者可以浏览、学习、复制或 fork。',
    icon: Share2,
    imageUrl: remoteMedia.canvasMap
  },
  {
    title: 'Agent 可以组队',
    description: '把你的导演、编剧、分镜、美术和生成 Agent 保存为团队模板，在项目之间复用。',
    icon: UsersRound,
    imageUrl: remoteMedia.agentQueue
  },
  {
    title: 'Skill 可以流通',
    description: '把高频创作流程封装成 Skill，让别人一键安装到自己的无限画布中。',
    icon: Boxes,
    imageUrl: remoteMedia.skillPack
  }
]

const agentCapabilities = [
  {
    title: '上下文理解',
    description: 'Agent 读取剧本、角色、分镜、素材和生成历史，而不是只处理孤立提示词。',
    icon: Network
  },
  {
    title: '团队编排',
    description: '用户可以定义导演、编剧、角色、美术、分镜、视频等 Agent 的职责与协作顺序。',
    icon: Layers
  },
  {
    title: '社区复用',
    description: '成熟的 Agent 团队可以发布到社区，被安装、fork，并服务新的画布项目。',
    icon: GitFork
  }
]

function readAuthState() {
  authStore.syncFromStorage()
  if (authStore.isAuthenticated) {
    projectStore.loadProjects().catch((error) => {
      if (error?.status === 401) authStore.logout()
    })
    authStore.refreshUser().then((user) => mergePointFields(user)).catch(() => {})
    refreshAccountPoints()
  } else {
    accountPoints.value = 0
    projectStore.clearWorkspace()
  }
}

function handleStorage(event) {
  if (['shenlu_token', 'shenlu_nickname', 'shenlu_email'].includes(event.key)) {
    readAuthState()
  }
}

function openLogin() {
  router.push({ name: 'login' })
}

function logout() {
  authStore.logout()
  accountPoints.value = 0
  readAuthState()
  router.push('/')
  scrollToTop()
}

async function refreshAccountPoints() {
  if (!authStore.isAuthenticated) return
  try {
    const dashboard = await fetchUserDashboard()
    mergeDashboardPayload(dashboard)
  } catch (error) {
    if (error?.status === 401) authStore.logout()
  }
}

function mergeDashboardPayload(payload) {
  const data = payload?.dashboard || payload?.data || payload || {}
  mergePointFields(data.points_summary || data.pointsSummary || data)
}

function mergePointFields(source = {}) {
  const directTotal = pickNumber(source, ['total_points', 'totalPoints', 'points', 'point_balance', 'pointBalance', 'balance', 'credits'], null)
  if (directTotal !== null) {
    accountPoints.value = directTotal
    return
  }
  const permanent = pickNumber(source, ['permanent_points', 'permanentPoints', 'general_points', 'generalPoints'], 0)
  const temporary = pickNumber(source, ['temporary_points', 'temporaryPoints', 'libtv_points', 'libtvPoints'], 0)
  accountPoints.value = permanent + temporary
}

function pickNumber(source, keys, fallback = 0) {
  for (const key of keys) {
    const value = source?.[key]
    const numeric = Number(value)
    if (value !== undefined && value !== null && Number.isFinite(numeric)) return numeric
  }
  return fallback
}

function formatPointValue(value) {
  const numeric = Number(value || 0)
  return new Intl.NumberFormat('zh-CN').format(Number.isFinite(numeric) ? numeric : 0)
}

function openCanvas(projectId = '') {
  if (!authStore.isAuthenticated) {
    router.push({
      name: 'login',
      query: { redirect: '/projects' }
    })
    return
  }

  if (projectId) {
    router.push(`/projects/${projectId}/canvas`)
    return
  }

  startProjectFromPrompt()
}

async function startProjectFromPrompt(seedText = '') {
  if (!authStore.isAuthenticated) {
    openCanvas()
    return
  }

  const prompt = (seedText || promptText.value).trim()
  projectFeedback.value = '正在创建 Sluvo 画布'
  try {
    const payload = await projectStore.createProjectFromPrompt(prompt)
    const projectId = payload?.project?.id
    const canvas = payload?.canvas
    if (prompt && canvas?.id) {
      projectFeedback.value = '正在写入初始提示词节点'
      await createInitialPromptNode(canvas, prompt, payload?.project?.title)
    }
    if (projectId) {
      promptText.value = ''
      await projectStore.loadProjects()
      await router.push(`/projects/${projectId}/canvas`)
    }
  } catch (error) {
    if (error?.status === 401) authStore.logout()
    projectFeedback.value = error instanceof Error ? error.message : '项目创建失败'
  }
}

async function createInitialPromptNode(canvas, prompt, title = '') {
  await saveSluvoCanvasBatch(canvas.id, {
    expectedRevision: canvas.revision,
    title: title || canvas.title,
    viewport: { x: 0, y: 0, zoom: 1 },
    snapshot: {
      version: 1,
      source: 'sluvo_home_prompt',
      nodes: [
        {
          type: 'prompt_note',
          title: '创意提示词',
          prompt
        }
      ],
      edges: []
    },
    nodes: [
      {
        nodeType: 'note',
        title: '创意提示词',
        position: { x: 120, y: 120 },
        size: { width: 500, height: 690 },
        status: 'draft',
        data: {
          clientId: `initial-prompt-${Date.now()}`,
          directType: 'prompt_note',
          prompt,
          body: prompt,
          promptPlaceholder: '继续补充这个创意的角色、场景和分镜方向。'
        },
        style: {}
      }
    ],
    edges: []
  })
}

function openProject(projectId) {
  if (!projectId) return
  router.push(`/projects/${projectId}/canvas`)
}

async function deleteProject(project) {
  if (!project?.id || deletingProjectIds.value.has(project.id)) return
  const title = project.title || '未命名画布'
  if (!window.confirm(`确定删除「${title}」吗？`)) return
  deletingProjectIds.value = new Set([...deletingProjectIds.value, project.id])
  try {
    await projectStore.deleteProject(project.id)
  } catch (error) {
    projectFeedback.value = error instanceof Error ? error.message : '项目删除失败'
  } finally {
    const next = new Set(deletingProjectIds.value)
    next.delete(project.id)
    deletingProjectIds.value = next
  }
}

function playPreviewVideo(event) {
  const video = event?.currentTarget?.querySelector?.('video')
  if (!video) return
  video.play?.().catch(() => {})
}

function pausePreviewVideo(event) {
  const video = event?.currentTarget?.querySelector?.('video')
  if (!video) return
  video.pause?.()
}

function startShowcaseRotation() {
  stopShowcaseRotation()
  showcaseRotationTimer = window.setInterval(() => {
    activeShowcaseIndex.value = (activeShowcaseIndex.value + 1) % showcaseItems.length
  }, 4200)
}

function stopShowcaseRotation() {
  if (!showcaseRotationTimer) return
  window.clearInterval(showcaseRotationTimer)
  showcaseRotationTimer = null
}

function selectShowcase(index) {
  activeShowcaseIndex.value = index
  startShowcaseRotation()
}

function resolveProjectImageUrl(value) {
  if (!value) return ''
  if (typeof value === 'string') return value.trim()
  if (Array.isArray(value)) {
    for (const item of value) {
      const resolved = resolveProjectImageUrl(item)
      if (resolved) return resolved
    }
    return ''
  }
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
  if (!updated) return project.description || 'Sluvo 画布项目'
  const date = new Date(updated)
  if (Number.isNaN(date.getTime())) return project.description || 'Sluvo 画布项目'
  return `更新于 ${date.toLocaleDateString('zh-CN', { month: '2-digit', day: '2-digit' })}`
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
  startShowcaseRotation()
  window.addEventListener('storage', handleStorage)
})

watch(
  () => authStore.isAuthenticated,
  (authenticated) => {
    if (authenticated) {
      projectStore.loadProjects().catch(() => {})
      refreshAccountPoints()
    } else {
      accountPoints.value = 0
    }
  }
)

onBeforeUnmount(() => {
  stopShowcaseRotation()
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
  min-height: 96px;
  padding: 20px clamp(22px, 4.8vw, 82px);
  border-bottom: 1px solid rgba(214, 181, 109, 0.12);
  background: rgba(5, 5, 5, 0.76);
  backdrop-filter: blur(18px);
}

.home-brand {
  display: inline-flex;
  align-items: center;
  gap: 14px;
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
  width: 46px;
  height: 46px;
  border: 1px solid rgba(245, 213, 145, 0.42);
  border-radius: 8px;
  background:
    linear-gradient(145deg, rgba(255, 241, 199, 0.16), rgba(214, 181, 109, 0.08)),
    #0e0b06;
  color: #ffe7a4;
  font-weight: 900;
  box-shadow: inset 0 1px 0 rgba(255, 255, 255, 0.12);
}

.home-brand__mark,
.rail-logo {
  overflow: hidden;
  padding: 2px;
}

.home-brand__mark img,
.rail-logo img {
  display: block;
  width: 100%;
  height: 100%;
  border-radius: 6px;
  object-fit: cover;
}

.home-brand strong {
  display: block;
  font-size: 24px;
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
  min-width: 0;
}

.home-nav__link,
.home-nav__primary,
.gold-button,
.quiet-button,
.top-chip,
.top-icon,
.section-heading button,
.composer-tools button,
.skill-strip button {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 8px;
  min-height: 44px;
  border: 1px solid rgba(214, 181, 109, 0.18);
  border-radius: 8px;
  background: rgba(255, 255, 255, 0.045);
  color: #f8ecd1;
  font-size: 15px;
  font-weight: 800;
}

.home-nav__link {
  padding: 0 16px;
  color: rgba(248, 236, 209, 0.76);
}

.home-nav__primary,
.gold-button {
  padding: 0 20px;
  border-color: rgba(255, 221, 151, 0.5);
  background: linear-gradient(180deg, #f8d98e, #b88735);
  color: #1a1206;
  box-shadow: 0 16px 42px rgba(184, 135, 53, 0.22);
}

.quiet-button {
  padding: 0 20px;
}

.guest-hero {
  display: grid;
  grid-template-columns: minmax(0, 0.72fr) minmax(460px, 1.28fr);
  align-items: center;
  gap: clamp(42px, 6.5vw, 112px);
  min-height: calc(100vh - 96px);
  padding: clamp(48px, 7vw, 96px) clamp(24px, 6vw, 110px);
}

.guest-hero__copy {
  max-width: 720px;
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
  margin: 24px 0 0;
  color: #fff8e6;
  font-size: clamp(86px, 12vw, 168px);
  font-weight: 950;
  line-height: 0.86;
  letter-spacing: 0;
}

.guest-hero__lead {
  max-width: 640px;
  margin: 26px 0 0;
  color: rgba(255, 248, 230, 0.78);
  font-size: clamp(18px, 1.45vw, 24px);
  font-weight: 800;
  line-height: 1.62;
}

.guest-hero__actions {
  display: flex;
  flex-wrap: wrap;
  gap: 12px;
  margin-top: 42px;
}

.guest-stage {
  position: relative;
  min-width: 0;
  min-height: clamp(560px, 62vh, 720px);
  overflow: hidden;
  border: 1px solid rgba(214, 181, 109, 0.18);
  border-radius: 8px;
  background:
    linear-gradient(rgba(214, 181, 109, 0.08) 1px, transparent 1px),
    linear-gradient(90deg, rgba(214, 181, 109, 0.08) 1px, transparent 1px),
    radial-gradient(circle at 52% 44%, rgba(214, 181, 109, 0.18), transparent 42%),
    #070706;
  background-size: 48px 48px, 48px 48px, auto, auto;
  box-shadow: inset 0 1px 0 rgba(255, 255, 255, 0.06), 0 34px 90px rgba(0, 0, 0, 0.42);
  animation: home-rise 0.68s 0.08s ease both;
}

.guest-stage::before,
.guest-stage::after {
  position: absolute;
  inset: 50%;
  width: 280px;
  height: 280px;
  border: 1px solid rgba(255, 241, 199, 0.1);
  border-radius: 50%;
  content: "";
  transform: translate(-50%, -50%);
}

.guest-stage::before {
  box-shadow: 0 0 80px rgba(214, 181, 109, 0.16);
  animation: orbitPulse 4s ease-in-out infinite;
}

.guest-stage::after {
  width: 420px;
  height: 420px;
  border-color: rgba(214, 181, 109, 0.08);
  animation: orbitPulse 5.6s ease-in-out infinite reverse;
}

.guest-stage__beam {
  position: absolute;
  top: 22%;
  right: -14%;
  left: -14%;
  height: 120px;
  background: linear-gradient(100deg, transparent 18%, rgba(214, 181, 109, 0.12), transparent 72%);
  filter: blur(4px);
  opacity: 0.7;
  pointer-events: none;
  transform: rotate(-14deg);
  transform-origin: center;
  animation: beamScan 2.8s ease-in-out infinite;
}

.guest-stage__beam--vertical {
  top: auto;
  right: -18%;
  bottom: 6%;
  left: -18%;
  width: auto;
  height: 140px;
  background: linear-gradient(100deg, transparent 22%, rgba(255, 241, 199, 0.1), transparent 68%);
  transform: rotate(13deg);
  animation-delay: 0.6s;
}

.preview-node {
  position: absolute;
  z-index: var(--node-z);
  display: grid;
  align-content: start;
  gap: 11px;
  width: clamp(320px, 43%, 430px);
  min-height: 214px;
  padding: 26px;
  border: 1px solid rgba(214, 181, 109, 0.28);
  border-radius: 8px;
  background:
    linear-gradient(145deg, rgba(255, 241, 199, 0.08), transparent 48%),
    linear-gradient(180deg, rgba(255, 255, 255, 0.035), transparent 38%),
    rgba(19, 16, 11, 0.94);
  box-shadow:
    0 22px 54px rgba(0, 0, 0, 0.48),
    inset 0 1px 0 rgba(255, 255, 255, 0.08);
  outline: none;
  transform: translate3d(var(--node-x, 0), var(--node-y, 0), 0) rotate(var(--node-rotate, 0deg));
  transform-origin: center;
  transition:
    transform 0.56s cubic-bezier(0.2, 0.8, 0.18, 1),
    z-index 0s linear 0.02s,
    border-color 0.28s ease,
    background 0.28s ease,
    box-shadow 0.28s ease,
    opacity 0.28s ease;
}

.preview-node::before {
  position: relative;
  z-index: 1;
  width: 8px;
  height: 8px;
  border-radius: 999px;
  background: #d6b56d;
  box-shadow: 0 0 16px rgba(214, 181, 109, 0.8);
  content: "";
}

.preview-node::after {
  position: absolute;
  inset: 0;
  border-radius: inherit;
  background:
    linear-gradient(115deg, transparent 0 46%, rgba(255, 241, 199, 0.1) 49%, transparent 54%),
    linear-gradient(180deg, rgba(0, 0, 0, 0), rgba(0, 0, 0, 0.16));
  content: "";
  opacity: 0.62;
  pointer-events: none;
  z-index: 0;
}

.preview-node span {
  position: relative;
  z-index: 1;
  color: #d6b56d;
  font-size: 13px;
  font-weight: 900;
  text-transform: uppercase;
}

.preview-node strong {
  position: relative;
  z-index: 1;
  color: #fff5d7;
  font-size: clamp(24px, 2.4vw, 34px);
  line-height: 1.1;
}

.preview-node small {
  position: relative;
  z-index: 1;
  color: rgba(249, 241, 220, 0.58);
  font-size: 15px;
  font-weight: 700;
  line-height: 1.45;
}

.preview-node em {
  position: relative;
  z-index: 1;
  display: inline-flex;
  width: fit-content;
  margin-top: 2px;
  padding: 5px 9px;
  border-radius: 999px;
  background: rgba(214, 181, 109, 0.12);
  color: rgba(255, 241, 199, 0.72);
  font-size: 12px;
  font-style: normal;
  font-weight: 900;
}

.preview-node:hover,
.preview-node:focus-visible {
  z-index: 20;
  border-color: rgba(255, 221, 151, 0.58);
  background:
    linear-gradient(145deg, rgba(255, 241, 199, 0.12), transparent 48%),
    linear-gradient(180deg, rgba(255, 255, 255, 0.045), transparent 38%),
    rgba(24, 20, 13, 0.98);
  box-shadow:
    0 32px 76px rgba(0, 0, 0, 0.58),
    0 0 42px rgba(214, 181, 109, 0.16),
    inset 0 1px 0 rgba(255, 255, 255, 0.1);
  opacity: 1;
  transform: translate3d(var(--node-hover-x, 0), var(--node-hover-y, 0), 0) scale(1.08);
}

.preview-node:hover::after,
.preview-node:focus-visible::after {
  opacity: 0.18;
}

.preview-node--script {
  top: 8%;
  left: 7%;
  --node-rotate: -2deg;
  --node-z: 4;
  --node-hover-x: 18px;
  --node-hover-y: 18px;
}

.preview-node--asset {
  top: 13%;
  right: 7%;
  --node-rotate: 1.8deg;
  --node-z: 3;
  --node-hover-x: -18px;
  --node-hover-y: 12px;
}

.preview-node--shot {
  right: 14%;
  bottom: 8%;
  --node-rotate: -1.4deg;
  --node-z: 2;
  --node-hover-x: -10px;
  --node-hover-y: -18px;
}

.preview-node--video {
  bottom: 13%;
  left: 10%;
  --node-rotate: 2deg;
  --node-z: 1;
  --node-hover-x: 16px;
  --node-hover-y: -12px;
}

.capability-band {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(min(100%, 240px), 1fr));
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

.top-chip--logout {
  border-color: rgba(255, 241, 199, 0.16);
  color: rgba(249, 241, 220, 0.66);
}

.top-chip--logout:hover {
  border-color: rgba(255, 241, 199, 0.28);
  background: rgba(255, 255, 255, 0.09);
  color: #fff8e6;
}

.creator-console {
  width: min(1320px, calc(100vw - 140px));
  margin: 0 auto;
}

.home-section {
  width: min(960px, calc(100vw - 140px));
  margin: 0 auto;
}

.creator-console {
  position: relative;
  padding: 26px 0 30px;
  text-align: center;
}

.creator-stage {
  position: relative;
  display: grid;
  place-items: center;
  min-height: 560px;
  overflow: hidden;
  border-radius: 8px;
}

.creator-stage::before {
  position: absolute;
  inset: 8% 15%;
  border: 1px solid rgba(214, 181, 109, 0.08);
  border-radius: 999px;
  background:
    radial-gradient(circle at 50% 42%, rgba(214, 181, 109, 0.2), transparent 42%),
    radial-gradient(circle at 50% 50%, rgba(255, 241, 199, 0.08), transparent 54%);
  content: "";
  opacity: 0.84;
}

.creator-stage::after {
  position: absolute;
  inset: 0;
  z-index: 2;
  background:
    linear-gradient(90deg, #050505 0%, rgba(5, 5, 5, 0) 18%, rgba(5, 5, 5, 0) 82%, #050505 100%),
    linear-gradient(180deg, rgba(5, 5, 5, 0) 0%, #050505 96%);
  content: "";
  pointer-events: none;
}

.creator-media-layer {
  position: absolute;
  inset: 0;
  z-index: 1;
  pointer-events: none;
}

.creator-console__content {
  position: relative;
  z-index: 3;
  display: grid;
  justify-items: center;
  width: min(720px, 100%);
  padding: 24px 20px;
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

.creator-console__feedback,
.home-section__error {
  color: #f3d894 !important;
  font-size: 13px !important;
  font-weight: 800;
}

.hero-media-card {
  position: absolute;
  z-index: 1;
  display: grid;
  gap: 6px;
  width: 196px;
  padding: 8px 8px 10px;
  border: 1px solid rgba(214, 181, 109, 0.2);
  border-color: color-mix(in srgb, var(--card-accent, #d6b56d) 44%, transparent);
  border-radius: 8px;
  background:
    linear-gradient(145deg, color-mix(in srgb, var(--card-accent, #d6b56d) 18%, transparent), transparent 54%),
    rgba(16, 14, 10, 0.78);
  box-shadow:
    0 22px 54px rgba(0, 0, 0, 0.38),
    inset 0 1px 0 rgba(255, 255, 255, 0.08);
  opacity: 0.58;
  text-align: left;
  transform: translate3d(0, 0, 0) rotate(var(--card-rotate, 0deg));
  animation: mediaFloat 8s ease-in-out infinite;
  pointer-events: auto;
}

.hero-media-card__visual {
  position: relative;
  display: block;
  overflow: hidden;
  aspect-ratio: 16 / 10;
  border-radius: 6px;
  background:
    radial-gradient(circle at 50% 40%, color-mix(in srgb, var(--card-accent, #d6b56d) 28%, transparent), transparent 46%),
    #1c1810;
}

.hero-media-card__visual::after,
.showcase-card__media::after,
.open-ecosystem-card__visual::after,
.project-card__preview--media::after {
  position: absolute;
  inset: 0;
  background:
    linear-gradient(180deg, rgba(0, 0, 0, 0), rgba(0, 0, 0, 0.38)),
    linear-gradient(110deg, transparent 0 45%, rgba(255, 241, 199, 0.12) 48%, transparent 54%);
  content: "";
  pointer-events: none;
}

.hero-media-card img,
.hero-media-card video,
.showcase-card img,
.showcase-card video,
.open-ecosystem-card img,
.open-ecosystem-card video,
.project-card__preview--media img {
  display: block;
  width: 100%;
  height: 100%;
  object-fit: cover;
}

.hero-media-card__kind {
  color: color-mix(in srgb, var(--card-accent, #d6b56d) 82%, #fff8e6);
  font-size: 10px;
  font-weight: 900;
  text-transform: uppercase;
}

.hero-media-card strong {
  color: #fff8e6;
  font-size: 14px;
}

.hero-media-card small {
  color: rgba(249, 241, 220, 0.56);
  font-size: 11px;
  line-height: 1.35;
}

.hero-media-card:hover {
  z-index: 4;
  opacity: 0.92;
}

.hero-media-card--character {
  top: 8%;
  left: 7%;
  --card-rotate: -5deg;
}

.hero-media-card--storyboard {
  top: 17%;
  right: 8%;
  --card-rotate: 4deg;
  animation-delay: -1.4s;
}

.hero-media-card--firstframe {
  top: 47%;
  left: 2%;
  width: 224px;
  --card-rotate: 3deg;
  animation-delay: -2.2s;
}

.hero-media-card--preview {
  right: 3%;
  bottom: 13%;
  width: 236px;
  --card-rotate: -3deg;
  animation-delay: -3.1s;
}

.hero-media-card--agent {
  bottom: 5%;
  left: 20%;
  width: 178px;
  --card-rotate: 2deg;
  animation-delay: -4s;
}

.hero-media-card--skill {
  top: 4%;
  right: 28%;
  width: 170px;
  --card-rotate: -2deg;
  animation-delay: -5s;
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

.send-button:disabled,
.skill-strip button:disabled,
.campaign-bar button:disabled,
.project-card:disabled {
  cursor: wait;
  opacity: 0.64;
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

.section-heading--stacked {
  align-items: flex-start;
  flex-direction: column;
  gap: 8px;
}

.section-heading--stacked p {
  max-width: 620px;
  margin: 0;
  color: rgba(249, 241, 220, 0.58);
  font-size: 14px;
  font-weight: 700;
  line-height: 1.55;
}

.section-heading button {
  min-height: 32px;
  padding: 0 10px;
  background: rgba(255, 255, 255, 0.055);
  color: rgba(249, 241, 220, 0.78);
  font-size: 12px;
}

.showcase-section {
  width: min(1180px, calc(100vw - 140px));
  padding-top: 8px;
}

.showcase-carousel {
  display: grid;
  grid-template-columns: minmax(0, 1.2fr) repeat(2, minmax(0, 0.86fr));
  gap: 16px;
  min-height: 390px;
  padding: 2px 0 0;
}

.showcase-card {
  position: relative;
  display: grid;
  gap: 9px;
  min-height: 360px;
  padding: 10px 10px 14px;
  overflow: hidden;
  border: 1px solid rgba(214, 181, 109, 0.13);
  border-radius: 8px;
  background:
    linear-gradient(145deg, color-mix(in srgb, var(--card-accent, #d6b56d) 13%, transparent), transparent 60%),
    rgba(255, 255, 255, 0.045);
  color: #fff8e6;
  cursor: pointer;
  text-align: left;
  animation: showcaseSwap 0.36s ease both;
  transition:
    transform 0.18s ease,
    border-color 0.18s ease,
    background 0.18s ease;
}

.showcase-card--primary {
  min-height: 390px;
}

.showcase-card--primary .showcase-card__media {
  aspect-ratio: 16 / 11;
}

.showcase-card:hover,
.showcase-card:focus-visible {
  border-color: color-mix(in srgb, var(--card-accent, #d6b56d) 54%, transparent);
  background:
    linear-gradient(145deg, color-mix(in srgb, var(--card-accent, #d6b56d) 18%, transparent), transparent 60%),
    rgba(214, 181, 109, 0.065);
  outline: none;
  transform: translateY(-3px);
}

.showcase-card__media {
  position: relative;
  display: block;
  overflow: hidden;
  aspect-ratio: 4 / 5;
  border-radius: 6px;
  background:
    radial-gradient(circle at 50% 35%, color-mix(in srgb, var(--card-accent, #d6b56d) 22%, transparent), transparent 46%),
    #17130d;
}

.showcase-card__media video {
  position: absolute;
  inset: 0;
  z-index: 2;
  opacity: 0;
  transition: opacity 0.2s ease;
}

.showcase-card:hover .showcase-card__media video,
.showcase-card:focus-visible .showcase-card__media video {
  opacity: 1;
}

.showcase-card__meta {
  color: color-mix(in srgb, var(--card-accent, #d6b56d) 76%, #fff8e6);
  font-size: 12px;
  font-weight: 900;
}

.showcase-card strong {
  font-size: 18px;
}

.showcase-card p {
  min-height: 42px;
  margin: 0;
  color: rgba(249, 241, 220, 0.58);
  font-size: 13px;
  line-height: 1.55;
}

.showcase-card button {
  width: fit-content;
  min-height: 34px;
  margin-top: auto;
  padding: 0 12px;
  border: 1px solid rgba(255, 221, 151, 0.32);
  border-radius: 8px;
  background: rgba(214, 181, 109, 0.14);
  color: #fff1c7;
  font-size: 12px;
  font-weight: 900;
}

.showcase-dots {
  display: flex;
  justify-content: center;
  gap: 8px;
  margin-top: 12px;
}

.showcase-dots button {
  width: 8px;
  height: 8px;
  padding: 0;
  border: 1px solid rgba(214, 181, 109, 0.32);
  border-radius: 999px;
  background: rgba(214, 181, 109, 0.14);
}

.showcase-dots button.is-active {
  width: 24px;
  background: #d6b56d;
}

.project-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(min(100%, 260px), 1fr));
  gap: 16px;
}

.project-card {
  position: relative;
  display: grid;
  gap: 8px;
  min-width: 0;
  padding: 8px 8px 14px;
  border: 1px solid rgba(214, 181, 109, 0.12);
  border-radius: 8px;
  background: rgba(255, 255, 255, 0.055);
  color: #fff8e6;
  cursor: pointer;
  text-align: left;
  transition:
    transform 0.18s ease,
    border-color 0.18s ease,
    background 0.18s ease;
}

.project-card--empty {
  border-style: dashed;
  background:
    linear-gradient(180deg, rgba(214, 181, 109, 0.08), rgba(255, 255, 255, 0.04)),
    rgba(255, 255, 255, 0.035);
}

.project-card--loading {
  pointer-events: none;
  opacity: 0.72;
}

.project-card:hover,
.project-card:focus-visible,
.open-ecosystem-card:hover,
.agent-capability:hover {
  border-color: rgba(214, 181, 109, 0.34);
  background: rgba(214, 181, 109, 0.075);
  transform: translateY(-3px);
}

.project-card:focus-visible {
  outline: 2px solid rgba(229, 200, 137, 0.62);
  outline-offset: 2px;
}

.project-card__delete {
  position: absolute;
  top: 14px;
  right: 14px;
  z-index: 2;
  display: grid;
  place-items: center;
  width: 34px;
  height: 34px;
  border: 1px solid rgba(255, 187, 176, 0.22);
  border-radius: 8px;
  background: rgba(12, 10, 8, 0.72);
  color: rgba(255, 222, 216, 0.88);
  opacity: 0;
  transform: translateY(-3px);
  transition:
    opacity 0.16s ease,
    transform 0.16s ease,
    background 0.16s ease,
    border-color 0.16s ease;
}

.project-card:hover .project-card__delete,
.project-card:focus-within .project-card__delete {
  opacity: 1;
  transform: translateY(0);
}

.project-card__delete:hover {
  border-color: rgba(255, 156, 142, 0.5);
  background: rgba(93, 30, 22, 0.82);
  color: #fff2ef;
}

.project-card__delete:disabled {
  cursor: wait;
  opacity: 0.5;
}

.project-card__preview {
  position: relative;
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 4px;
  height: 88px;
  padding: 8px;
  border-radius: 6px;
  background: #24211b;
}

.project-card__preview--media {
  display: block;
  overflow: hidden;
  aspect-ratio: 16 / 9;
  height: auto;
  min-height: 112px;
  padding: 0;
}

.project-card__preview--no-cover,
.project-card--empty .project-card__preview--empty {
  display: grid;
  grid-template-columns: 1fr;
  place-items: center;
  overflow: hidden;
  aspect-ratio: 16 / 9;
  height: auto;
  min-height: 112px;
  padding: 0;
}

.project-card__preview--no-cover {
  border: 1px dashed rgba(255, 241, 199, 0.14);
  background:
    radial-gradient(circle at 50% 34%, rgba(214, 181, 109, 0.11), transparent 38%),
    linear-gradient(145deg, rgba(255, 255, 255, 0.04), rgba(5, 5, 5, 0.72));
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

.project-card__preview--empty {
  place-items: center;
  background:
    radial-gradient(circle at 50% 35%, rgba(255, 241, 199, 0.18), transparent 34%),
    linear-gradient(145deg, rgba(214, 181, 109, 0.14), rgba(19, 16, 10, 0.9));
}

.project-card__preview--empty span {
  background: none;
}

.project-card__no-cover {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  padding: 6px 10px;
  border: 1px solid rgba(255, 241, 199, 0.16);
  border-radius: 999px;
  background: rgba(5, 5, 5, 0.28) !important;
  color: rgba(255, 248, 230, 0.48);
  font-size: 12px;
  font-weight: 900;
}

.project-card__create-icon {
  display: grid;
  place-items: center;
  width: 48px;
  height: 48px;
  border: 1px solid rgba(255, 241, 199, 0.3);
  border-radius: 8px;
  background: rgba(5, 5, 5, 0.42) !important;
  color: #fff1c7;
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

.open-ecosystem-grid {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 16px;
}

.open-ecosystem-card {
  display: grid;
  align-content: start;
  gap: 12px;
  min-height: 320px;
  padding: 10px 10px 18px;
  border: 1px solid rgba(214, 181, 109, 0.12);
  border-radius: 8px;
  background:
    linear-gradient(145deg, rgba(214, 181, 109, 0.09), transparent 58%),
    rgba(255, 255, 255, 0.045);
  transition:
    transform 0.18s ease,
    border-color 0.18s ease,
    background 0.18s ease;
}

.open-ecosystem-card__visual {
  position: relative;
  display: block;
  overflow: hidden;
  aspect-ratio: 16 / 9;
  border-radius: 6px;
  background:
    radial-gradient(circle at 50% 38%, rgba(214, 181, 109, 0.18), transparent 42%),
    #17130d;
}

.open-ecosystem-card__icon {
  display: grid;
  place-items: center;
  width: 42px;
  height: 42px;
  border: 1px solid rgba(255, 241, 199, 0.18);
  border-radius: 8px;
  background: rgba(214, 181, 109, 0.1);
  color: #fff1c7;
  margin: 2px 10px 0;
}

.open-ecosystem-card strong {
  color: #fff8e6;
  font-size: 18px;
  padding: 0 10px;
}

.open-ecosystem-card p {
  margin: 0;
  color: rgba(249, 241, 220, 0.58);
  font-size: 13px;
  line-height: 1.65;
  padding: 0 10px;
}

.open-ecosystem-cta {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 18px;
  margin-top: 16px;
  padding: 16px 18px;
  border: 1px solid rgba(255, 221, 151, 0.18);
  border-radius: 8px;
  background:
    linear-gradient(90deg, rgba(214, 181, 109, 0.08), rgba(255, 255, 255, 0.035)),
    rgba(255, 255, 255, 0.04);
}

.open-ecosystem-cta span {
  color: rgba(255, 248, 230, 0.76);
  font-size: 14px;
  font-weight: 800;
  line-height: 1.5;
}

.open-ecosystem-cta button {
  flex: 0 0 auto;
  min-height: 38px;
  padding: 0 16px;
  border: 1px solid rgba(255, 221, 151, 0.42);
  border-radius: 8px;
  background: linear-gradient(180deg, #d6b56d, #9f722c);
  color: #160f06;
  font-size: 13px;
  font-weight: 900;
}

.agent-panel {
  display: grid;
  grid-template-columns: minmax(0, 1.1fr) minmax(min(100%, 300px), 0.8fr);
  gap: 16px;
}

.agent-primary {
  position: relative;
  display: grid;
  align-content: end;
  gap: 16px;
  min-height: 340px;
  overflow: hidden;
  padding: 28px;
  border: 1px solid rgba(214, 181, 109, 0.12);
  border-radius: 8px;
  background:
    linear-gradient(rgba(214, 181, 109, 0.08) 1px, transparent 1px),
    linear-gradient(90deg, rgba(214, 181, 109, 0.08) 1px, transparent 1px),
    radial-gradient(circle at 76% 16%, rgba(255, 241, 199, 0.18), transparent 22%),
    linear-gradient(145deg, rgba(214, 181, 109, 0.12), rgba(8, 7, 5, 0.96));
  background-size: 40px 40px, 40px 40px, auto, auto;
}

.agent-primary::before {
  position: absolute;
  top: 28px;
  right: 28px;
  width: 96px;
  height: 96px;
  border: 1px solid rgba(255, 241, 199, 0.18);
  border-radius: 50%;
  background:
    radial-gradient(circle, rgba(255, 241, 199, 0.2), transparent 56%),
    rgba(255, 255, 255, 0.035);
  content: "";
}

.agent-primary__eyebrow {
  color: #d6b56d;
  font-size: 12px;
  font-weight: 900;
  text-transform: uppercase;
}

.agent-primary h3 {
  max-width: 520px;
  margin: 0;
  color: #fff8e6;
  font-size: clamp(24px, 3vw, 42px);
  line-height: 1.1;
}

.agent-primary p {
  max-width: 540px;
  margin: 0;
  color: rgba(249, 241, 220, 0.66);
  font-size: 14px;
  line-height: 1.6;
}

.agent-flow {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 8px;
  max-width: 520px;
}

.agent-flow span {
  display: grid;
  place-items: center;
  min-height: 36px;
  border: 1px solid rgba(214, 181, 109, 0.16);
  border-radius: 8px;
  background: rgba(255, 255, 255, 0.055);
  color: rgba(255, 248, 230, 0.78);
  font-size: 13px;
  font-weight: 900;
}

.agent-capability-list {
  display: grid;
  gap: 12px;
}

.agent-capability {
  display: grid;
  grid-template-columns: auto 1fr;
  gap: 14px;
  min-height: 104px;
  padding: 16px;
  border: 1px solid rgba(214, 181, 109, 0.12);
  border-radius: 8px;
  background: rgba(255, 255, 255, 0.045);
  transition:
    transform 0.18s ease,
    border-color 0.18s ease,
    background 0.18s ease;
}

.agent-capability__icon {
  display: grid;
  place-items: center;
  width: 40px;
  height: 40px;
  border: 1px solid rgba(255, 241, 199, 0.18);
  border-radius: 8px;
  background: rgba(214, 181, 109, 0.1);
  color: #fff1c7;
}

.agent-capability strong {
  display: block;
  color: #fff8e6;
  font-size: 16px;
}

.agent-capability p {
  margin: 6px 0 0;
  color: rgba(249, 241, 220, 0.58);
  font-size: 13px;
  line-height: 1.55;
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

@keyframes orbitPulse {
  0%,
  100% {
    opacity: 0.5;
    transform: translate(-50%, -50%) scale(0.96);
  }

  50% {
    opacity: 1;
    transform: translate(-50%, -50%) scale(1.04);
  }
}

@keyframes beamScan {
  0%,
  100% {
    opacity: 0.36;
    filter: blur(0);
  }

  50% {
    opacity: 1;
    filter: blur(0.6px);
  }
}

@keyframes nodeFloat {
  0%,
  100% {
    transform: translateY(0);
  }

  50% {
    transform: translateY(-8px);
  }
}

@keyframes mediaFloat {
  0%,
  100% {
    transform: translate3d(0, 0, 0) rotate(var(--card-rotate, 0deg));
  }

  50% {
    transform: translate3d(0, -10px, 0) rotate(var(--card-rotate, 0deg));
  }
}

@keyframes showcaseSwap {
  from {
    opacity: 0;
    transform: translateY(10px);
  }

  to {
    opacity: 1;
    transform: translateY(0);
  }
}

@media (max-width: 1180px) {
  .guest-hero {
    grid-template-columns: 1fr;
  }

  .guest-stage {
    min-height: 540px;
  }

  .home-nav__actions {
    flex-wrap: wrap;
    justify-content: flex-end;
  }

  .preview-node {
    width: clamp(270px, 42%, 380px);
    min-height: 190px;
    padding: 22px;
  }

  .creator-console,
  .home-section,
  .showcase-section {
    width: min(820px, calc(100vw - 116px));
  }

  .creator-stage {
    min-height: 540px;
  }

  .hero-media-card--agent,
  .hero-media-card--skill {
    display: none;
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

  .home-nav {
    min-height: 0;
    padding: 16px 18px;
  }

  .home-nav__actions {
    width: 100%;
    flex-wrap: wrap;
  }

  .home-nav__actions > button {
    flex: 1 1 140px;
  }

  .home-brand--compact strong {
    display: none;
  }

  .capability-band,
  .open-ecosystem-grid,
  .project-grid,
  .agent-panel {
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

  .campaign-bar span {
    align-items: flex-start;
  }

  .creator-console,
  .home-section,
  .showcase-section {
    width: calc(100vw - 32px);
  }

  .creator-stage {
    min-height: 520px;
  }

  .creator-stage::before {
    inset: 12% 4%;
  }

  .hero-media-card {
    width: 160px;
    opacity: 0.42;
  }

  .hero-media-card--character,
  .hero-media-card--storyboard {
    display: none;
  }

  .hero-media-card--firstframe {
    top: 10%;
    left: -8px;
    width: 168px;
  }

  .hero-media-card--preview {
    right: -10px;
    bottom: 7%;
    width: 176px;
  }

  .showcase-carousel {
    grid-template-columns: 1fr;
    min-height: 0;
  }

  .showcase-card:not(.showcase-card--primary) {
    display: none;
  }

  .agent-primary {
    min-height: 330px;
  }

  .open-ecosystem-cta {
    align-items: flex-start;
    flex-direction: column;
  }
}

@media (max-width: 560px) {
  .home-nav__link {
    display: none;
  }

  .home-nav__actions > .home-nav__primary,
  .guest-hero__actions > button {
    flex: 1 1 100%;
  }

  .guest-hero {
    padding: 34px 16px 46px;
  }

  .guest-hero__eyebrow {
    align-items: flex-start;
    min-height: 0;
    padding: 8px 10px;
    line-height: 1.45;
  }

  .guest-hero h1 {
    font-size: clamp(56px, 22vw, 86px);
  }

  .guest-stage {
    min-height: 420px;
  }

  .preview-node {
    width: min(78%, 300px);
    min-height: 150px;
    padding: 16px;
  }

  .preview-node strong {
    font-size: 20px;
  }

  .preview-node small {
    font-size: 12px;
  }

  .preview-node--script {
    top: 7%;
    left: 6%;
  }

  .preview-node--asset {
    top: 18%;
    right: 5%;
  }

  .preview-node--shot {
    right: 7%;
    bottom: 7%;
  }

  .preview-node--video {
    bottom: 18%;
    left: 5%;
  }

  .prompt-composer__footer {
    align-items: flex-start;
    flex-direction: column;
  }

  .send-button {
    align-self: flex-end;
  }

  .creator-stage {
    min-height: auto;
    overflow: visible;
  }

  .creator-stage::before,
  .creator-stage::after,
  .creator-media-layer {
    display: none;
  }

  .creator-console__content {
    padding: 26px 0 8px;
  }

  .showcase-card {
    min-height: 330px;
  }

  .showcase-card--primary {
    min-height: 340px;
  }

  .section-heading {
    align-items: flex-start;
    flex-direction: column;
  }

  .agent-flow {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }

  .agent-capability {
    grid-template-columns: 1fr;
  }
}
</style>
