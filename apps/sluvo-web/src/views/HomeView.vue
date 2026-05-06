<template>
  <main class="sluvo-home" :class="{ 'is-authed': showWorkbench }">
    <section v-if="!showWorkbench" class="home-guest-shell">
      <nav class="home-nav" aria-label="Sluvo">
        <button class="home-brand" type="button" @click="scrollToTop">
          <span class="home-brand__mark">
            <img :src="logoUrl" alt="" />
          </span>
          <span>
            <strong>Sluvo</strong>
          </span>
        </button>

        <div class="home-nav__center" aria-label="社区入口">
          <button type="button" @click="openCanvasCommunity">画布社区</button>
          <button type="button" @click="openAgentCommunity">Agent 社区</button>
          <button type="button" @click="openSkillCommunity">Skill 社区</button>
        </div>

        <div class="home-nav__actions">
          <button class="home-nav__link" type="button" @click="scrollToCapabilities">能力</button>
          <button class="home-nav__link" type="button" @click="openCanvas()">自由画布</button>
          <button class="home-nav__primary" type="button" @click="openSluvo">
            <LogIn :size="17" />
            {{ isAuthenticated ? '进入 Sluvo' : '登录 Sluvo' }}
          </button>
        </div>
      </nav>

      <div class="guest-hero">
        <div class="guest-hero__copy">
          <span class="guest-hero__eyebrow">
            <Sparkles :size="16" />
            AI Canvas Operating System
          </span>
          <h1 class="guest-hero__headline" aria-label="让影视创作在无限画布中生长">
            <span class="guest-hero__headline-brand">Sluvo</span>
            <span class="guest-hero__headline-main">
              <span class="guest-hero__headline-prefix">让</span>
              <span class="guest-hero__headline-drama">影视</span>
              <span class="guest-hero__headline-suffix">创作</span>
            </span>
            <span class="guest-hero__headline-accent">在无限画布中</span>
            <span class="guest-hero__headline-pair">
              <em>被编排</em>
              <i>生成</i>
            </span>
            <span class="guest-hero__headline-final">
              <em>复用</em>
              <strong>分享</strong>
            </span>
          </h1>
          <p class="guest-hero__sublead">Sluvo 把灵感、角色、分镜、模型与 Agent 团队放进同一张画布。创作过程会被记录，流程可以复用，并沉淀为新的 Canvas、Agent 与 Skill。</p>
          <div class="guest-hero__actions">
            <button class="gold-button" type="button" @click="openSluvo">
              进入 Sluvo
              <ArrowUpRight :size="18" />
            </button>
            <button class="quiet-button" type="button" @click="scrollToCapabilities">查看能力</button>
          </div>
          <div class="guest-hero__proof" aria-label="Sluvo highlights">
            <span><strong>Canvas</strong> 无限画布</span>
            <span><strong>Agent</strong> 团队协作</span>
            <span><strong>Skill</strong> 流程复用</span>
          </div>
        </div>

        <div class="guest-stage" aria-label="Sluvo workflow preview">
          <div class="guest-stage__halo" />
          <div class="guest-stage__watermark" aria-hidden="true">Sluvo</div>
          <div class="guest-stage__beam" />
          <div class="guest-stage__beam guest-stage__beam--vertical" />
          <div class="guest-stage__device" aria-hidden="true">
            <div class="guest-stage__device-bar">
              <span />
              <span />
              <span />
              <strong>Open Canvas</strong>
            </div>
            <div class="guest-stage__canvas-map">
              <i class="canvas-line canvas-line--one" />
              <i class="canvas-line canvas-line--two" />
              <i class="canvas-line canvas-line--three" />
            </div>
          </div>
          <article
            v-for="node in previewNodes"
            :key="node.title"
            class="preview-node"
            :class="node.className"
            role="button"
            tabindex="0"
            :aria-label="`查看${node.title}详情`"
            @click="scrollToPreviewDetail(node.id)"
            @keydown.enter.prevent="scrollToPreviewDetail(node.id)"
            @keydown.space.prevent="scrollToPreviewDetail(node.id)"
            @mouseenter="playPreviewVideo"
            @mouseleave="pausePreviewVideo"
            @focusin="playPreviewVideo"
            @focusout="pausePreviewVideo"
          >
            <span>{{ node.kind }}</span>
            <strong>{{ node.title }}</strong>
            <small>{{ node.caption }}</small>
            <button
              class="preview-node__signal"
              type="button"
              :aria-label="`查看${node.title}详情`"
              @click.stop="scrollToPreviewDetail(node.id)"
            >
              {{ node.signal }}
            </button>
            <div class="preview-node__media" aria-hidden="true">
              <div class="preview-node__screen" :class="{ 'preview-node__screen--video': node.videoUrl }">
                <video
                  v-if="node.videoUrl"
                  muted
                  loop
                  playsinline
                  disablepictureinpicture
                  disableremoteplayback
                  controlslist="nodownload nofullscreen noremoteplayback"
                  translate="no"
                  preload="metadata"
                  :poster="node.posterUrl"
                >
                  <source :src="node.videoUrl" type="video/mp4" />
                </video>
                <template v-else>
                  <span class="preview-node__scan" />
                  <span class="preview-node__graph">
                    <i />
                    <i />
                    <i />
                    <i />
                    <i />
                    <i />
                    <i />
                  </span>
                  <span class="preview-node__play">▶</span>
                </template>
              </div>
              <div class="preview-node__timeline">
                <span />
              </div>
            </div>
          </article>
        </div>
      </div>

      <section class="problem-section" aria-labelledby="problem-title">
        <div class="problem-section__intro">
          <h2 id="problem-title">影视 AI 创作最大的市场痛点，是协作、画布与复用没有闭环</h2>
          <p>单点工具已经很多，但智能体协作、无限画布组织、创作过程复现、专属 Agent 团队共享和 Skill 复用往往彼此割裂。Sluvo 把 OIIOII 式智能体协作与 LIBTV 式无限画布创作接到同一个系统里，让一次创作不再只是一次性产出，而能沉淀为可分享、可复现、可安装的生产资产。</p>
        </div>
        <div class="problem-grid">
          <article v-for="item in problemCards" :key="item.title" class="problem-card">
            <span class="problem-card__index">{{ item.index }}</span>
            <component :is="item.icon" :size="22" />
            <strong>{{ item.title }}</strong>
            <p>{{ item.description }}</p>
          </article>
        </div>
      </section>

      <section class="workflow-detail-section" aria-labelledby="workflow-detail-title">
        <div class="workflow-detail-section__intro">
          <h2 id="workflow-detail-title">用无限画布把创作系统重新接起来</h2>
          <p>每一个节点都不是一个孤立功能，而是 Sluvo 画布里的一个生产层：从创作过程、Agent 团队、Skill 沉淀到社区共创，最终组成可以被记录、分享、安装和再次生长的创作网络。</p>
        </div>
        <div class="workflow-detail-grid">
          <article
            v-for="(node, index) in previewNodes"
            :id="`workflow-detail-${node.id}`"
            :key="`${node.id}-detail`"
            class="workflow-detail-card"
            :class="[`workflow-detail-card--${node.id}`, { 'is-target': activeWorkflowDetailId === node.id }]"
          >
            <div class="workflow-detail-card__index">{{ String(index + 1).padStart(2, '0') }}</div>
            <div class="workflow-detail-card__content">
              <span>{{ node.kind }}</span>
              <h3>{{ node.detailTitle }}</h3>
              <p>{{ node.detailDescription }}</p>
              <ul>
                <li v-for="item in node.detailPoints" :key="item">{{ item }}</li>
              </ul>
            </div>
            <div class="workflow-detail-card__chips" aria-label="能力关键词">
              <span v-for="item in node.detailTags" :key="item">{{ item }}</span>
            </div>
          </article>
        </div>
      </section>

      <section ref="projectAgentSection" class="project-agent-showcase" aria-labelledby="project-agent-title">
        <div class="project-agent-showcase__intro">
          <span>Project Agent Team</span>
          <h2 id="project-agent-title">项目里最强的 Agent，不是工具，是一支会协作的创作团队</h2>
          <p>导演、编剧、分镜、美术与视频生成 Agent 会围绕同一张画布读取上下文、分配任务、交付节点，并把优秀团队沉淀成可以复用的项目资产。</p>
        </div>
        <div class="project-agent-stage">
          <div class="project-agent-stage__aurora" aria-hidden="true" />
          <article class="project-agent-hero">
            <span class="project-agent-hero__eyebrow">
              <Crown :size="16" />
              Featured Team
            </span>
            <h3>影视旗舰 Agent 阵列</h3>
            <p>为一条高质量漫剧生产线预设的协作团队：先理解故事目标，再拆分角色、镜头、美术和视频任务，最后回写到画布节点。</p>
            <div class="project-agent-hero__metrics" aria-label="Agent performance metrics">
              <span v-for="item in agentShowcaseMetrics" :key="item.label">
                <strong>{{ item.value }}</strong>
                {{ item.label }}
              </span>
            </div>
          </article>
          <div class="project-agent-orbit" aria-hidden="true">
            <span />
            <span />
            <span />
          </div>
          <div class="project-agent-grid">
            <article v-for="agent in agentShowcaseAgents" :key="agent.title" class="project-agent-card">
              <span class="project-agent-card__icon">
                <component :is="agent.icon" :size="22" />
              </span>
              <span class="project-agent-card__role">{{ agent.role }}</span>
              <strong>{{ agent.title }}</strong>
              <p>{{ agent.description }}</p>
              <div class="project-agent-card__signal">
                <i />
                {{ agent.signal }}
              </div>
            </article>
          </div>
          <div class="project-agent-pipeline" aria-label="Agent workflow">
            <span v-for="step in agentShowcasePipeline" :key="step">{{ step }}</span>
          </div>
        </div>
      </section>

      <section id="capabilities" class="capability-band">
        <div class="capability-track">
          <article v-for="item in capabilityCards" :key="item.title" class="capability-card">
            <component :is="item.icon" :size="24" />
            <strong>{{ item.title }}</strong>
            <span>{{ item.description }}</span>
          </article>
          <article v-for="item in capabilityCards" :key="`${item.title}-loop`" class="capability-card" aria-hidden="true">
            <component :is="item.icon" :size="24" />
            <strong>{{ item.title }}</strong>
            <span>{{ item.description }}</span>
          </article>
        </div>
      </section>

      <section id="models" class="model-showcase" aria-labelledby="model-showcase-title">
        <div class="model-showcase__heading">
          <span>
            <Sparkles :size="16" />
            Connected Models
          </span>
          <h2 id="model-showcase-title">我们已接入的模型矩阵</h2>
          <p>图像、视频、音频和 Agent 推理模型统一进入 Sluvo 的画布生成网络。</p>
        </div>
        <div class="model-showcase__stage" aria-label="Sluvo connected model brands">
          <div
            v-for="(row, index) in connectedModelBrandRows"
            :key="`brand-row-${index}`"
            class="model-stream"
            :class="[`model-stream--${index + 1}`, `model-stream--${row.direction}`]"
            :style="{ '--stream-duration': `${20 + row.items.length * 1.4}s` }"
          >
            <div class="model-stream__track">
              <span v-for="brand in row.items" :key="brand.name" class="model-chip">
                <span class="model-chip__icon">
                  <img :src="brand.iconUrl" :alt="`${brand.name} icon`" loading="lazy" />
                </span>
                <span>{{ brand.name }}</span>
              </span>
              <span v-for="brand in row.items" :key="`${brand.name}-loop`" class="model-chip" aria-hidden="true">
                <span class="model-chip__icon">
                  <img :src="brand.iconUrl" alt="" loading="lazy" />
                </span>
                <span>{{ brand.name }}</span>
              </span>
            </div>
          </div>
        </div>
      </section>

      <section id="community" ref="communitySection" class="guest-community-band" aria-labelledby="guest-community-title">
        <div class="section-heading section-heading--stacked">
          <h2 id="guest-community-title">
            <GitFork :size="22" />
            开放画布社区
          </h2>
          <p>游客可以先浏览社区画布，登录后查看完整画布并 Fork 到自己的工作台。</p>
        </div>
        <div class="community-grid">
          <article v-for="item in visibleCommunityCanvases" :key="item.id" class="community-card" tabindex="0" @click="openCommunityDetail(item)">
            <span class="community-card__cover">
              <img v-if="item.coverUrl" :src="item.coverUrl" :alt="item.title" loading="lazy" />
              <span v-else>开放画布</span>
            </span>
            <span class="community-card__meta">{{ item.author?.nickname || 'Sluvo 创作者' }} · {{ item.forkCount || 0 }} Fork</span>
            <strong>{{ item.title }}</strong>
            <p>{{ item.description || '一张可学习、可复用的社区画布。' }}</p>
            <button type="button" @click.stop="openCommunityDetail(item)">登录查看详情</button>
          </article>
          <article v-if="!communityLoading && visibleCommunityCanvases.length === 0" class="community-card community-card--empty">
            <span class="community-card__cover">等待发布</span>
            <strong>社区画布即将出现</strong>
            <p>发布你的第一张开放画布，让其他创作者可以学习和 Fork。</p>
          </article>
        </div>
      </section>
    </section>

    <section v-else class="home-workbench">
      <aside class="workbench-rail" aria-label="Sluvo navigation">
        <button class="rail-logo" type="button" aria-label="Sluvo 首页" @click="scrollToTop">
          <img :src="logoUrl" alt="" />
        </button>
        <button
          class="rail-tool"
          :class="{ 'is-active': activeWorkbenchSection === 'top' }"
          type="button"
          aria-label="首页"
          @click="scrollToTop"
        >
          <Compass :size="20" />
        </button>
        <button
          class="rail-tool"
          type="button"
          aria-label="我的项目"
          @click="openProjectsSpace"
        >
          <FolderOpen :size="20" />
        </button>
        <button
          class="rail-tool"
          :class="{ 'is-active': activeWorkbenchSection === 'community' }"
          type="button"
          aria-label="社区"
          @click="scrollToCommunity"
        >
          <Image :size="20" />
        </button>
        <span class="rail-separator" />
        <button class="rail-tool rail-tool--muted" type="button" aria-label="回收站" @click="openTrash">
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
            <button class="top-chip top-chip--home" type="button" @click="openLandingHome">
              <House :size="16" />
              首页
            </button>
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
              <h1 id="creator-title" class="creator-headline">
                <span :key="activeCreatorHeadline">{{ activeCreatorHeadline }}</span>
              </h1>
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

        <section class="home-section creation-start" aria-labelledby="creation-title">
          <div class="section-heading creation-heading">
            <div>
              <h2 id="creation-title">
                <Sparkles :size="22" />
                最近项目
              </h2>
              <p>继续你的画布，或新建一个影视创作项目。</p>
            </div>
            <div class="creation-heading__actions">
              <button type="button" :disabled="isCreatingProject" @click="startProjectFromPrompt()">
                <Plus :size="15" />
                新建项目
              </button>
              <button type="button" @click="openProjectsSpace">
                查看全部
                <ArrowUpRight :size="15" />
              </button>
            </div>
          </div>

          <p v-if="projectStore.error" class="home-section__error">{{ projectStore.error }}</p>

          <div v-if="projectStore.loadingProjects" class="project-strip">
            <article v-for="item in 4" :key="item" class="project-card project-card--loading project-card--strip">
              <span class="project-card__preview project-card__preview--empty" />
              <strong>加载中</strong>
              <small>正在同步 Sluvo 项目</small>
            </article>
          </div>

          <div v-else class="project-strip" aria-label="最近项目">
            <button
              v-if="projectStore.projects.length === 0"
              class="project-card project-card--empty project-card--strip project-card--new-inline"
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
              <small>从创意、剧本、角色或分镜目标开始</small>
            </button>
            <article
              v-for="project in visibleRecentProjects"
              :key="project.id"
              class="project-card project-card--strip"
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

        <section class="home-section showcase-section" aria-labelledby="showcase-title">
          <div class="section-heading section-heading--stacked">
            <h2 id="showcase-title">
              <Film :size="22" />
              亮点
            </h2>
            <p>从样片、角色、场景和工作流开始，把平台能力拆成你的下一张画布。</p>
          </div>

          <div class="showcase-carousel" aria-label="平台亮点" @mouseenter="stopShowcaseRotation" @mouseleave="startShowcaseRotation">
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

        <section class="home-section ecosystem-agent-section" aria-labelledby="ecosystem-title">
          <div class="section-heading section-heading--stacked">
            <h2 id="ecosystem-title">
              <Sparkles :size="22" />
              开放生态与 Agent 能力
            </h2>
            <p>Sluvo 会把个人创作升级为可复用的社区资产，并让 Agent 参与画布上下文协作。</p>
          </div>

          <div class="ecosystem-agent-layout">
            <div class="open-ecosystem-grid open-ecosystem-grid--compact">
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

            <div class="agent-panel agent-panel--compact">
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
          </div>

          <div class="open-ecosystem-cta">
            <span>从今天的每一次创作开始，积累未来可分享的创作资产。</span>
            <button type="button" :disabled="isCreatingProject" @click="startProjectFromPrompt()">创建开放画布</button>
          </div>
        </section>

        <section id="community" ref="communitySection" class="home-section community-section community-space" aria-labelledby="community-title">
          <div class="section-heading section-heading--stacked community-space__heading">
            <h2 id="community-title">
              <GitFork :size="22" />
              开放画布社区
            </h2>
            <p>向下探索其他创作者发布的画布，Fork 成你的下一张作品。</p>
          </div>
          <p v-if="communityError" class="home-section__error">{{ communityError }}</p>
          <div class="community-grid community-grid--space">
            <article
              v-for="(item, index) in visibleCommunityCanvases"
              :key="item.id"
              class="community-card community-card--space"
              :style="{ '--space-index': index }"
              tabindex="0"
              @click="openCommunityDetail(item)"
            >
              <span class="community-card__cover">
                <img v-if="item.coverUrl" :src="item.coverUrl" :alt="item.title" loading="lazy" />
                <span v-else>开放画布</span>
              </span>
              <span class="community-card__meta">{{ item.author?.nickname || 'Sluvo 创作者' }} · {{ item.forkCount || 0 }} Fork</span>
              <strong>{{ item.title }}</strong>
              <p>{{ item.description || '一张可学习、可复用的社区画布。' }}</p>
              <div class="community-card__actions">
                <button type="button" @click.stop="openCommunityDetail(item)">查看详情</button>
                <button type="button" :disabled="forkingCommunityIds.has(item.id)" @click.stop="forkCommunityCanvas(item)">
                  <Loader2 v-if="forkingCommunityIds.has(item.id)" class="spin" :size="15" />
                  Fork 到我的画布
                </button>
              </div>
            </article>
            <article v-if="communityLoading" class="community-card community-card--empty community-card--space">
              <span class="community-card__cover">同步中</span>
              <strong>正在加载社区画布</strong>
              <p>稍等片刻，Sluvo 正在拉取最新开放画布。</p>
            </article>
            <article v-if="!communityLoading && visibleCommunityCanvases.length === 0" class="community-card community-card--empty community-card--space">
              <span class="community-card__cover">等待发布</span>
              <strong>还没有社区画布</strong>
              <p>你可以先创建项目，在画布工作台里发布到社区。</p>
            </article>
          </div>
        </section>
      </div>
    </section>
  </main>
</template>

<script setup>
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
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
  House,
  Loader2,
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
import { fetchSluvoCommunityCanvases, forkSluvoCommunityCanvas, saveSluvoCanvasBatch } from '../api/sluvoApi'

const router = useRouter()
const route = useRoute()
const authStore = useAuthStore()
const projectStore = useProjectStore()
const communitySection = ref(null)
const projectAgentSection = ref(null)
const activeWorkbenchSection = ref('top')
const promptText = ref('')
const projectFeedback = ref('')
const deletingProjectIds = ref(new Set())
const activeShowcaseIndex = ref(0)
const activeHeadlineIndex = ref(0)
const activeWorkflowDetailId = ref('')
let showcaseRotationTimer = null
let headlineRotationTimer = null
const accountPoints = ref(0)
const communityCanvases = ref([])
const communityLoading = ref(false)
const communityError = ref('')
const forkingCommunityIds = ref(new Set())

const isAuthenticated = computed(() => authStore.isAuthenticated)
const showWorkbench = computed(() => isAuthenticated.value && route.name === 'workspace')
const isCreatingProject = computed(() => projectStore.creatingProject)
const userName = computed(() => authStore.displayName)
const userInitial = computed(() => authStore.userInitial)
const visibleShowcaseItems = computed(() => {
  return [0, 1, 2]
    .map((offset) => showcaseItems[(activeShowcaseIndex.value + offset) % showcaseItems.length])
    .filter(Boolean)
})
const visibleCommunityCanvases = computed(() => communityCanvases.value.slice(0, 6))
const activeCreatorHeadline = computed(() => creatorHeadlines[activeHeadlineIndex.value] || creatorHeadlines[0])
const visibleRecentProjects = computed(() => projectStore.projects.slice(0, 5))

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

const homeMedia = {
  shareForkCanvas: '/media/home/share-fork-canvas.mp4',
  agentTeamFlow: '/media/home/agent-team-flow.mp4',
  canvasSkillPack: '/media/home/canvas-skill-pack.mp4',
  communityRemixNetwork: '/media/home/community-remix-network.mp4'
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
    id: 'canvas',
    kind: 'Open Canvas',
    title: '创作过程可分享',
    caption: '把画布中的灵感、节点、依赖与生成路径发布到社区',
    signal: 'Share / Fork',
    videoUrl: homeMedia.shareForkCanvas,
    detailTitle: '让创作过程本身成为作品资产',
    detailDescription: 'Sluvo 会把从灵感到成片的关键路径留在同一张无限画布里。节点之间的依赖、素材来源、生成记录和分镜结构都可以被保留下来，发布后别人看到的不只是结果，也能看到作品是如何被搭建出来的。',
    detailPoints: [
      '画布节点、素材、生成路径和版本记录可以一起发布。',
      '别人可以直接 Fork 一张画布，在原有结构上继续创作。',
      '适合把一次完整项目沉淀成可复盘、可展示、可二创的创作资产。'
    ],
    detailTags: ['Canvas', 'Share', 'Fork'],
    className: 'preview-node--script preview-node--has-video'
  },
  {
    id: 'agent',
    kind: 'Agent Team',
    title: '漫剧团队可编排',
    caption: '自定义导演、编剧、分镜、角色、生成等 Agent 分工',
    signal: 'Plan / Execute',
    videoUrl: homeMedia.agentTeamFlow,
    detailTitle: '把漫剧生产拆给一支可编排的 Agent 团队',
    detailDescription: '从世界观、角色设定、剧情推进到分镜、美术和视频生成，每个 Agent 都可以承担明确职责。你可以像搭建团队一样配置它们的输入、输出和协作顺序，让复杂创作流程稳定运行。',
    detailPoints: [
      '导演、编剧、角色、美术、分镜、视频等 Agent 可以独立配置。',
      'Agent 之间通过画布节点传递上下文，减少重复提示和断层。',
      '适合长篇漫剧、系列短片和多人协作型项目。'
    ],
    detailTags: ['Agent', 'Plan', 'Execute'],
    className: 'preview-node--asset preview-node--has-video'
  },
  {
    id: 'skill',
    kind: 'Canvas Skill',
    title: '画布技能可沉淀',
    caption: '把一组节点和流程保存为可安装、可复用的 Skill',
    signal: 'Build / Reuse',
    videoUrl: homeMedia.canvasSkillPack,
    detailTitle: '把高频创作方法沉淀成可安装的 Skill',
    detailDescription: '当一套节点组合、Agent 流程或生成方法被验证有效后，可以保存为 Skill。它既可以是一套模板，也可以是一条自动化生产链，让创作者不用每次从零搭建。',
    detailPoints: [
      '把稳定流程保存成 Skill，下一次创作可以直接安装复用。',
      'Skill 可以包含节点模板、Agent 编排、参数和执行顺序。',
      '适合沉淀短剧开场、角色资产板、分镜生成链等高频能力。'
    ],
    detailTags: ['Skill', 'Build', 'Reuse'],
    className: 'preview-node--shot preview-node--has-video'
  },
  {
    id: 'community',
    kind: 'Community',
    title: '创作者网络可共生',
    caption: '从他人的作品、Agent 和 Skill 中 fork 出新的创作路径',
    signal: 'Publish / Remix',
    videoUrl: homeMedia.communityRemixNetwork,
    detailTitle: '让画布、Agent 与 Skill 在社区里继续生长',
    detailDescription: '社区不是只展示成片的橱窗，而是可以继续 Fork、改造和安装的创作网络。创作者可以从他人的画布、Agent 团队和 Skill 中获得起点，再发布自己的新版本。',
    detailPoints: [
      '作品、Agent 团队和 Skill 都可以成为社区里的可复用资产。',
      'Fork 和 Remix 会保留来源关系，让创作路径自然生长。',
      '适合团队共创、模板市场、案例复用和灵感扩展。'
    ],
    detailTags: ['Community', 'Publish', 'Remix'],
    className: 'preview-node--video preview-node--has-video'
  }
]

const problemCards = [
  {
    index: '01',
    icon: Layers,
    title: '智能体协作难以落到项目',
    description: '很多 Agent 只能完成单点任务，缺少像 OIIOII 一样围绕项目目标持续分工、读取上下文、协同推进的团队机制。'
  },
  {
    index: '02',
    icon: Network,
    title: '无限画布和创作过程割裂',
    description: '创作者需要像 LIBTV 一样在无限画布中组织灵感、角色、分镜和生成结果，但现有流程很难把画布变成可执行生产系统。'
  },
  {
    index: '03',
    icon: Share2,
    title: '优秀画布无法共享复现',
    description: '一次成功的创作路径通常只能被观看结果，不能被完整复现、Fork 和二次创作，创作经验无法规模化流通。'
  },
  {
    index: '04',
    icon: PackageOpen,
    title: 'Agent 团队与 Skill 难以资产化',
    description: '专属智能体团队、角色分工、节点流程和高频 Skill 很难被打包分享，导致团队每次都要重新搭建生产方法。'
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

const connectedModelBrands = [
  { name: 'Seedance', iconUrl: '/media/model-icons/seedance.ico' },
  { name: 'Kling', iconUrl: '/media/model-icons/kling.png' },
  { name: 'Veo', iconUrl: '/media/model-icons/gemini.svg' },
  { name: 'Vidu', iconUrl: '/media/model-icons/vidu.svg' },
  { name: 'Nano Banana', iconUrl: '/media/model-icons/gemini.svg' },
  { name: 'GPT Image', iconUrl: '/media/model-icons/openai.svg' },
  { name: 'MiniMax', iconUrl: '/media/model-icons/minimax.ico' },
  { name: 'DeepSeek', iconUrl: '/media/model-icons/deepseek.ico' },
  { name: 'HappyHorse', iconUrl: '/media/model-icons/happyhouse.png' }
]

const connectedModelBrandRows = [
  { direction: 'forward', items: connectedModelBrands },
  { direction: 'reverse', items: [...connectedModelBrands].reverse() }
]

const agentShowcaseMetrics = [
  { value: '6', label: '核心 Agent' },
  { value: '24/7', label: '画布上下文待命' },
  { value: '92%', label: '流程复用率' }
]

const agentShowcasePipeline = ['故事目标', '角色设定', '分镜拆解', '美术统一', '视频生成', '画布回写']

const agentShowcaseAgents = [
  {
    icon: Compass,
    role: 'Director Agent',
    title: '导演调度',
    description: '统筹故事目标、风格约束和执行顺序，把复杂项目拆成可以连续推进的画布任务。',
    signal: 'Plan / Route'
  },
  {
    icon: FileText,
    role: 'Writer Agent',
    title: '编剧推进',
    description: '读取角色关系和剧情上下文，生成台词、冲突、转折与下一场戏的叙事目标。',
    signal: 'Script / Beat'
  },
  {
    icon: Clapperboard,
    role: 'Shot Agent',
    title: '分镜设计',
    description: '把剧本转换成镜头序列、景别、动作和节奏，并保持前后镜头的连续感。',
    signal: 'Shot / Motion'
  },
  {
    icon: UserRound,
    role: 'Character Agent',
    title: '角色守护',
    description: '维护人物设定、口吻、服饰、关系和情绪曲线，减少系列创作中的角色漂移。',
    signal: 'Persona / Memory'
  },
  {
    icon: Sparkles,
    role: 'Art Agent',
    title: '美术统一',
    description: '对齐色彩、构图、材质和视觉关键词，让不同生成节点保持统一的审美方向。',
    signal: 'Style / Look'
  },
  {
    icon: Film,
    role: 'Video Agent',
    title: '成片生成',
    description: '接收分镜、美术和动作要求，组织视频生成、预览和结果回写，形成可追踪版本。',
    signal: 'Render / Review'
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

const creatorHeadlines = [
  '导演～今天想创作什么影视项目？',
  '编剧～今天想展开哪段高能剧情？',
  '分镜师～今天想推进哪场关键戏？',
  '美术导演～今天想定下什么视觉风格？',
  '制片人～今天想搭建哪条漫剧生产线？',
  'Agent 团队～今天想拆解哪条创作链路？'
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

function openSluvo() {
  if (authStore.isAuthenticated) {
    router.push({ name: 'workspace' })
    return
  }
  router.push({ name: 'login', query: { redirect: '/workspace' } })
}

function openLandingHome() {
  router.push({ name: 'home' })
  scrollToTop()
}

async function loadCommunityCanvases() {
  communityLoading.value = true
  communityError.value = ''
  try {
    communityCanvases.value = await fetchSluvoCommunityCanvases({ limit: 6, sort: 'latest' })
  } catch (error) {
    communityError.value = error instanceof Error ? error.message : '社区画布加载失败'
  } finally {
    communityLoading.value = false
  }
}

function openCommunityDetail(item) {
  if (!authStore.isAuthenticated) {
    router.push({ name: 'login', query: { redirect: `/community/canvases/${item.id}` } })
    return
  }
  router.push({ name: 'community-canvas-detail', params: { publicationId: item.id }, query: { from: 'community' } })
}

async function forkCommunityCanvas(item) {
  if (!authStore.isAuthenticated) {
    router.push({ name: 'login', query: { redirect: `/community/canvases/${item.id}` } })
    return
  }
  if (!item?.id || forkingCommunityIds.value.has(item.id)) return
  forkingCommunityIds.value = new Set([...forkingCommunityIds.value, item.id])
  try {
    const payload = await forkSluvoCommunityCanvas(item.id)
    const projectId = payload?.project?.id
    if (projectId) {
      await projectStore.loadProjects().catch(() => {})
      router.push(`/projects/${projectId}/canvas`)
    }
  } catch (error) {
    communityError.value = error instanceof Error ? error.message : 'Fork 社区画布失败'
    if (error?.status === 401) authStore.logout()
  } finally {
    const next = new Set(forkingCommunityIds.value)
    next.delete(item.id)
    forkingCommunityIds.value = next
  }
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
      query: { redirect: '/workspace' }
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
  video.currentTime = 0
  video.play?.().catch(() => {})
}

function pausePreviewVideo(event) {
  const video = event?.currentTarget?.querySelector?.('video')
  if (!video) return
  video.pause?.()
  video.currentTime = 0
}

function startShowcaseRotation() {
  stopShowcaseRotation()
  showcaseRotationTimer = window.setInterval(() => {
    activeShowcaseIndex.value = (activeShowcaseIndex.value + 1) % showcaseItems.length
  }, 4200)
}

function startHeadlineRotation() {
  stopHeadlineRotation()
  headlineRotationTimer = window.setInterval(() => {
    activeHeadlineIndex.value = (activeHeadlineIndex.value + 1) % creatorHeadlines.length
  }, 3600)
}

function stopHeadlineRotation() {
  if (!headlineRotationTimer) return
  window.clearInterval(headlineRotationTimer)
  headlineRotationTimer = null
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
  activeWorkbenchSection.value = 'top'
  window.scrollTo({ top: 0, behavior: 'smooth' })
}

function scrollToCapabilities() {
  document.getElementById('capabilities')?.scrollIntoView({ behavior: 'smooth', block: 'start' })
}

function scrollToProjectAgents() {
  projectAgentSection.value?.scrollIntoView({ behavior: 'smooth', block: 'start' })
}

function openCanvasCommunity() {
  router.push({ name: 'community-canvases' })
}

function openAgentCommunity() {
  router.push({ name: 'community-agents' })
}

function openSkillCommunity() {
  router.push({ name: 'community-skills' })
}

function scrollToPreviewDetail(id) {
  if (!id) return
  const targetId = `workflow-detail-${id}`
  activeWorkflowDetailId.value = id
  document.getElementById(targetId)?.scrollIntoView({ behavior: 'smooth', block: 'center' })
}

function openProjectsSpace() {
  router.push({ name: 'projects' })
}

function openTrash() {
  router.push({ name: 'trash' })
}

function scrollToCommunity() {
  activeWorkbenchSection.value = 'community'
  communitySection.value?.scrollIntoView({ behavior: 'smooth', block: 'start' })
}

function scrollToRouteHash() {
  if (route.hash !== '#community' || !showWorkbench.value) return
  nextTick(() => {
    activeWorkbenchSection.value = 'community'
    communitySection.value?.scrollIntoView({ behavior: 'smooth', block: 'start' })
    clearConsumedWorkspaceHash()
  })
}

function clearConsumedWorkspaceHash() {
  if (route.hash !== '#community' || typeof window === 'undefined') return
  const nextUrl = `${window.location.pathname}${window.location.search}`
  window.history.replaceState(window.history.state, '', nextUrl)
}

function resetGuestScrollOnLoad() {
  if (typeof window === 'undefined' || showWorkbench.value) return
  if ('scrollRestoration' in window.history) {
    window.history.scrollRestoration = 'manual'
  }
  if (route.hash) {
    const nextUrl = `${window.location.pathname}${window.location.search}`
    window.history.replaceState(window.history.state, '', nextUrl)
  }
  window.requestAnimationFrame(() => {
    window.scrollTo({ top: 0, left: 0, behavior: 'auto' })
  })
  window.setTimeout(() => {
    window.scrollTo({ top: 0, left: 0, behavior: 'auto' })
  }, 0)
}

function updateActiveWorkbenchSection() {
  if (!showWorkbench.value) return
  const activationLine = Math.min(220, Math.max(120, window.innerHeight * 0.28))
  const communityTop = communitySection.value?.getBoundingClientRect().top ?? Number.POSITIVE_INFINITY

  if (communityTop <= activationLine) {
    activeWorkbenchSection.value = 'community'
  } else {
    activeWorkbenchSection.value = 'top'
  }
}

onMounted(() => {
  resetGuestScrollOnLoad()
  readAuthState()
  loadCommunityCanvases()
  startShowcaseRotation()
  startHeadlineRotation()
  scrollToRouteHash()
  window.addEventListener('storage', handleStorage)
  window.addEventListener('scroll', updateActiveWorkbenchSection, { passive: true })
  window.addEventListener('resize', updateActiveWorkbenchSection)
  nextTick(updateActiveWorkbenchSection)
})

watch(
  () => [route.name, route.hash, showWorkbench.value],
  () => {
    scrollToRouteHash()
    nextTick(updateActiveWorkbenchSection)
  }
)

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
  stopHeadlineRotation()
  window.removeEventListener('storage', handleStorage)
  window.removeEventListener('scroll', updateActiveWorkbenchSection)
  window.removeEventListener('resize', updateActiveWorkbenchSection)
})
</script>

<style scoped>
.sluvo-home {
  min-height: 100vh;
  background:
    radial-gradient(circle at 70% 8%, rgba(236, 204, 136, 0.18), transparent 30%),
    radial-gradient(circle at 28% 18%, rgba(163, 119, 43, 0.12), transparent 28%),
    linear-gradient(180deg, #050505 0%, #090806 48%, #030303 100%);
  color: #f9f1dc;
  overflow-x: hidden;
}

.home-guest-shell,
.home-workbench {
  min-height: 100vh;
}

.home-guest-shell {
  display: flex;
  flex-direction: column;
  padding-top: 72px;
}

.home-nav,
.workbench-topbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 20px;
}

.home-nav {
  position: fixed;
  display: grid;
  grid-template-columns: minmax(160px, 1fr) auto minmax(340px, 1fr);
  top: 0;
  right: 0;
  left: 0;
  z-index: 20;
  order: 0;
  min-height: 72px;
  padding: 12px clamp(22px, 4.8vw, 76px);
  border-bottom: 1px solid rgba(236, 204, 136, 0.08);
  background: linear-gradient(180deg, rgba(5, 5, 5, 0.84), rgba(5, 5, 5, 0.58));
  backdrop-filter: blur(28px) saturate(1.18);
  box-shadow: 0 18px 44px rgba(0, 0, 0, 0.28);
}

.home-nav__actions {
  justify-self: end;
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
  border: 1px solid rgba(245, 213, 145, 0.34);
  border-radius: 14px;
  background:
    linear-gradient(145deg, rgba(255, 241, 199, 0.13), rgba(214, 181, 109, 0.07)),
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
  border-radius: 11px;
  object-fit: cover;
}

.home-brand strong {
  display: block;
  font-size: 23px;
  letter-spacing: 0;
}

.home-brand small {
  display: block;
  color: rgba(249, 241, 220, 0.58);
  font-size: 12px;
  font-weight: 700;
}

.home-nav__center {
  display: inline-flex;
  align-items: center;
  justify-self: center;
  gap: 8px;
  min-width: 0;
  padding: 4px;
  border: 1px solid rgba(214, 181, 109, 0.12);
  border-radius: 14px;
  background: rgba(255, 255, 255, 0.035);
  box-shadow: inset 0 1px 0 rgba(255, 255, 255, 0.06);
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
.home-nav__center button,
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
  min-height: 42px;
  border: 1px solid rgba(214, 181, 109, 0.18);
  border-radius: 12px;
  background: rgba(255, 255, 255, 0.045);
  color: #f8ecd1;
  font-size: 14px;
  font-weight: 800;
  transition:
    transform 0.2s ease,
    border-color 0.2s ease,
    background 0.2s ease,
    box-shadow 0.2s ease;
}

.home-nav__link:hover,
.home-nav__center button:hover,
.quiet-button:hover,
.home-nav__primary:hover,
.gold-button:hover {
  border-color: rgba(255, 221, 151, 0.34);
}

.home-nav__center button {
  position: relative;
  min-height: 38px;
  padding: 0 16px;
  overflow: hidden;
  border-radius: 10px;
  color: rgba(255, 245, 215, 0.82);
  white-space: nowrap;
}

.home-nav__center button::before {
  position: absolute;
  inset: 0;
  background: linear-gradient(105deg, transparent 0 30%, rgba(255, 241, 199, 0.18) 48%, transparent 64%);
  content: "";
  opacity: 0;
  transform: translateX(-90%);
  transition: opacity 0.2s ease;
}

.home-nav__center button:hover::before {
  opacity: 1;
  animation: navOptionFlow 1.2s ease;
}

.home-nav__link {
  padding: 0 18px;
  color: rgba(248, 236, 209, 0.76);
}

.home-nav__primary,
.gold-button {
  min-height: 48px;
  padding: 0 24px;
  border-color: rgba(255, 228, 162, 0.58);
  background:
    linear-gradient(180deg, rgba(255, 245, 203, 0.95), rgba(225, 183, 91, 0.95) 46%, rgba(176, 124, 42, 0.98)),
    #d6b56d;
  color: #1a1206;
  box-shadow:
    0 18px 46px rgba(184, 135, 53, 0.24),
    inset 0 1px 0 rgba(255, 255, 255, 0.48);
}

.quiet-button {
  min-height: 48px;
  padding: 0 24px;
  background: rgba(255, 255, 255, 0.035);
  color: rgba(255, 248, 230, 0.88);
}

.guest-hero {
  position: relative;
  order: 1;
  display: grid;
  grid-template-columns: minmax(360px, 0.86fr) minmax(520px, 1.14fr);
  align-items: center;
  gap: clamp(56px, 7vw, 120px);
  min-height: calc(100vh - 72px);
  padding: clamp(56px, 8vw, 112px) clamp(24px, 6vw, 112px) clamp(72px, 8vw, 118px);
}

.guest-hero::before {
  position: absolute;
  inset: 10% 6% auto;
  height: 52%;
  background:
    radial-gradient(ellipse at 50% 50%, rgba(255, 229, 166, 0.14), transparent 64%),
    linear-gradient(90deg, transparent, rgba(214, 181, 109, 0.08), transparent);
  content: "";
  filter: blur(22px);
  opacity: 0.8;
  pointer-events: none;
}

.guest-hero__copy {
  position: relative;
  z-index: 2;
  max-width: 720px;
  animation: home-rise 0.58s ease both;
}

.guest-hero__eyebrow {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  min-height: 36px;
  padding: 0 14px;
  border: 1px solid rgba(214, 181, 109, 0.2);
  border-radius: 999px;
  background: rgba(214, 181, 109, 0.07);
  color: #eed28f;
  font-size: 12px;
  font-weight: 850;
  letter-spacing: 0.04em;
}

.guest-hero__headline {
  position: relative;
  display: grid;
  gap: 0;
  max-width: 760px;
  margin: 30px 0 0;
  color: #fff8e6;
  font-size: 78px;
  font-weight: 900;
  line-height: 0.9;
  letter-spacing: 0;
}

.guest-hero__headline span {
  display: block;
  width: fit-content;
  max-width: 100%;
  text-wrap: balance;
}

.guest-hero__headline-brand {
  position: relative;
  margin-bottom: 22px;
  color: transparent;
  background:
    linear-gradient(180deg, #fffdf2 0%, #f6dfac 38%, #c49545 70%, #6f4c1e 100%);
  background-clip: text;
  -webkit-background-clip: text;
  font-size: 134px;
  font-weight: 900;
  line-height: 0.82;
  isolation: isolate;
  text-shadow:
    0 1px 0 rgba(255, 255, 255, 0.24),
    22px 34px 72px rgba(0, 0, 0, 0.34),
    14px 18px 62px rgba(214, 181, 109, 0.18),
    -8px -10px 28px rgba(255, 241, 199, 0.1);
  transform: skewX(-5deg);
  transform-origin: left bottom;
}

.guest-hero__headline-brand::before,
.guest-hero__headline-brand::after {
  position: absolute;
  inset: -0.1em -0.04em;
  color: transparent;
  content: "Sluvo";
  pointer-events: none;
}

.guest-hero__headline-brand::before {
  z-index: -1;
  background:
    linear-gradient(105deg, rgba(139, 98, 36, 0.18), rgba(255, 221, 151, 0.88) 34%, rgba(123, 204, 255, 0.36) 52%, rgba(198, 164, 255, 0.24) 62%, rgba(245, 205, 116, 0.6) 82%);
  background-size: 220% 100%;
  background-clip: text;
  -webkit-background-clip: text;
  filter: blur(1.4px);
  opacity: 0.62;
  transform: translate(0.085em, 0.07em) skewX(-3deg);
  animation: sluvoPrism 7.2s ease-in-out infinite;
}

.guest-hero__headline-brand::after {
  z-index: 1;
  background:
    linear-gradient(112deg, transparent 0 36%, rgba(255, 255, 255, 0.95) 44%, rgba(255, 232, 164, 0.6) 48%, transparent 58%);
  background-size: 260% 100%;
  background-clip: text;
  -webkit-background-clip: text;
  opacity: 0.5;
  transform: translate(-0.018em, -0.012em);
  animation: sluvoSheen 5.4s cubic-bezier(0.42, 0, 0.22, 1) infinite;
}

.guest-hero__headline-main {
  display: flex !important;
  align-items: flex-end;
  gap: 0.1em;
  color: rgba(255, 248, 230, 0.96);
  text-shadow: 0 18px 46px rgba(0, 0, 0, 0.28);
}

.guest-hero__headline-prefix,
.guest-hero__headline-drama,
.guest-hero__headline-suffix {
  display: inline-block !important;
  width: auto !important;
}

.guest-hero__headline-drama {
  color: transparent;
  background:
    linear-gradient(180deg, #fff8dd 0%, #f0c66d 42%, #b98230 76%, #6e4a1d 100%);
  background-clip: text;
  -webkit-background-clip: text;
  font-size: 1.34em;
  line-height: 0.78;
  text-shadow:
    0 20px 58px rgba(214, 181, 109, 0.3),
    0 1px 0 rgba(255, 255, 255, 0.22);
}

.guest-hero__headline-accent {
  margin-top: -6px;
  color: transparent;
  background:
    linear-gradient(180deg, #fff4c8 0%, #d9b15d 52%, #8e6428 100%);
  background-clip: text;
  -webkit-background-clip: text;
  text-shadow: 0 18px 52px rgba(214, 181, 109, 0.26);
}

.guest-hero__headline-pair {
  position: relative;
  display: flex !important;
  align-items: flex-start;
  justify-content: space-between;
  gap: 28px;
  width: min(680px, 100%);
  margin-top: 4px;
  padding-bottom: 12px;
  color: rgba(255, 248, 230, 0.96);
}

.guest-hero__headline-pair::after {
  position: absolute;
  right: 14%;
  bottom: 4px;
  left: 0;
  height: 4px;
  border-radius: 999px;
  background: linear-gradient(90deg, rgba(214, 181, 109, 0.95), rgba(255, 241, 199, 0.48), transparent);
  content: "";
  opacity: 0.76;
}

.guest-hero__headline-pair em,
.guest-hero__headline-pair i {
  display: block;
  font-style: normal;
  line-height: 0.9;
  white-space: nowrap;
}

.guest-hero__headline-pair i {
  color: #fff8e6;
}

.guest-hero__headline-final {
  display: flex !important;
  align-items: center;
  flex-wrap: wrap;
  gap: 18px;
  margin-top: 6px;
}

.guest-hero__headline-final em,
.guest-hero__headline-final strong {
  display: inline-flex;
  align-items: center;
  min-height: 0.98em;
  font-style: normal;
  line-height: 0.98;
}

.guest-hero__headline-final em {
  color: rgba(255, 248, 230, 0.52);
}

.guest-hero__headline-final strong {
  padding: 0 20px 8px;
  border: 1px solid rgba(255, 224, 150, 0.3);
  border-radius: 18px;
  background:
    linear-gradient(180deg, rgba(255, 238, 184, 0.92), rgba(214, 181, 109, 0.92)),
    #d6b56d;
  color: #160f06;
  box-shadow:
    0 26px 60px rgba(184, 135, 53, 0.22),
    inset 0 1px 0 rgba(255, 255, 255, 0.42);
}

.guest-hero__sublead {
  max-width: 620px;
  margin: 28px 0 0;
  color: rgba(255, 248, 230, 0.68);
  font-size: 18px;
  font-weight: 720;
  line-height: 1.76;
}

.guest-hero__actions {
  display: flex;
  flex-wrap: wrap;
  gap: 14px;
  margin-top: 38px;
}

.guest-hero__proof {
  display: flex;
  flex-wrap: wrap;
  gap: 18px;
  margin-top: 34px;
  color: rgba(255, 248, 230, 0.54);
  font-size: 13px;
  font-weight: 700;
}

.guest-hero__proof span {
  display: inline-flex;
  align-items: center;
  gap: 7px;
}

.guest-hero__proof span::before {
  width: 5px;
  height: 5px;
  border-radius: 999px;
  background: #d6b56d;
  box-shadow: 0 0 16px rgba(214, 181, 109, 0.78);
  content: "";
}

.guest-hero__proof strong {
  color: #f3d894;
  font-weight: 900;
}

.guest-stage {
  position: relative;
  min-width: 0;
  min-height: clamp(600px, 68vh, 760px);
  overflow: hidden;
  border: 1px solid rgba(236, 204, 136, 0.2);
  border-radius: 28px;
  background:
    radial-gradient(circle at 50% 48%, rgba(214, 181, 109, 0.22), transparent 39%),
    radial-gradient(ellipse at 76% 24%, rgba(255, 241, 199, 0.08), transparent 34%),
    linear-gradient(180deg, rgba(255, 255, 255, 0.035), transparent 38%),
    #060606;
  background-size: auto, auto, auto, auto;
  box-shadow:
    inset 0 1px 0 rgba(255, 255, 255, 0.09),
    inset 0 0 120px rgba(214, 181, 109, 0.05),
    0 42px 120px rgba(0, 0, 0, 0.58);
  animation: home-rise 0.68s 0.08s ease both;
  perspective: 1200px;
}

.guest-stage:has(.preview-node:hover),
.guest-stage:has(.preview-node:focus-visible) {
  overflow: visible;
}

.guest-stage__halo {
  position: absolute;
  inset: 14% 13% 9%;
  border-radius: 50%;
  background:
    radial-gradient(ellipse at 50% 50%, rgba(255, 237, 183, 0.2), rgba(214, 181, 109, 0.08) 34%, transparent 68%);
  filter: blur(12px);
  opacity: 0.8;
  pointer-events: none;
}

.guest-stage__watermark {
  position: absolute;
  top: 44%;
  left: 50%;
  z-index: 0;
  color: transparent;
  background:
    linear-gradient(180deg, rgba(255, 248, 230, 0.12), rgba(214, 181, 109, 0.035)),
    linear-gradient(90deg, transparent, rgba(255, 241, 199, 0.18), transparent);
  background-clip: text;
  -webkit-background-clip: text;
  filter: blur(0.4px);
  font-size: 168px;
  font-weight: 900;
  line-height: 0.82;
  opacity: 0.42;
  pointer-events: none;
  text-shadow: 0 0 72px rgba(214, 181, 109, 0.18);
  transform: translate(-50%, -50%) rotate(-8deg) scaleX(1.08);
  user-select: none;
  white-space: nowrap;
}

.guest-stage__watermark::after {
  position: absolute;
  inset: -18% -10%;
  background: linear-gradient(100deg, transparent 18%, rgba(255, 241, 199, 0.2) 46%, transparent 66%);
  content: "";
  filter: blur(16px);
  opacity: 0.18;
  transform: translateX(-10%);
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

.guest-stage__device {
  position: absolute;
  inset: 12% 9% 11%;
  z-index: 1;
  overflow: hidden;
  border: 1px solid rgba(255, 235, 178, 0.22);
  border-radius: 24px;
  background:
    linear-gradient(135deg, rgba(255, 255, 255, 0.12), transparent 28%),
    linear-gradient(180deg, rgba(18, 15, 10, 0.72), rgba(5, 5, 5, 0.9)),
    #0b0906;
  box-shadow:
    0 54px 120px rgba(0, 0, 0, 0.5),
    0 0 70px rgba(214, 181, 109, 0.1),
    inset 0 1px 0 rgba(255, 255, 255, 0.14);
  transform: rotateX(58deg) rotateZ(-8deg) translateY(40px);
  transform-origin: center;
}

.guest-stage__device::before {
  position: absolute;
  inset: 0;
  background:
    linear-gradient(118deg, transparent 0 38%, rgba(255, 241, 199, 0.15) 45%, transparent 52%),
    radial-gradient(circle at 76% 30%, rgba(214, 181, 109, 0.16), transparent 28%);
  content: "";
  opacity: 0.58;
  pointer-events: none;
}

.guest-stage__device-bar {
  position: relative;
  z-index: 1;
  display: flex;
  align-items: center;
  gap: 9px;
  height: 54px;
  padding: 0 22px;
  border-bottom: 1px solid rgba(214, 181, 109, 0.12);
}

.guest-stage__device-bar span {
  width: 8px;
  height: 8px;
  border-radius: 999px;
  background: rgba(214, 181, 109, 0.72);
}

.guest-stage__device-bar strong {
  margin-left: 10px;
  color: rgba(255, 248, 230, 0.68);
  font-size: 13px;
  font-weight: 850;
}

.guest-stage__canvas-map {
  position: absolute;
  inset: 54px 0 0;
  background:
    radial-gradient(ellipse at 50% 46%, rgba(214, 181, 109, 0.16), transparent 42%),
    linear-gradient(165deg, transparent 12%, rgba(214, 181, 109, 0.08) 46%, transparent 72%);
  overflow: hidden;
}

.guest-stage__canvas-map::before,
.guest-stage__canvas-map::after {
  position: absolute;
  right: -18%;
  left: -18%;
  height: 38%;
  border: 1px solid rgba(214, 181, 109, 0.1);
  border-right: 0;
  border-left: 0;
  border-radius: 50%;
  content: "";
  opacity: 0.56;
  transform: rotate(-9deg);
}

.guest-stage__canvas-map::before {
  top: 18%;
}

.guest-stage__canvas-map::after {
  bottom: 12%;
  opacity: 0.36;
  transform: rotate(8deg);
}

.canvas-line {
  position: absolute;
  display: block;
}

.canvas-line {
  height: 2px;
  border-radius: 999px;
  background: linear-gradient(90deg, transparent, rgba(214, 181, 109, 0.62), transparent);
  transform-origin: left center;
}

.canvas-line--one {
  top: 24%;
  left: 18%;
  width: 44%;
  transform: rotate(16deg);
}

.canvas-line--two {
  top: 48%;
  left: 31%;
  width: 46%;
  transform: rotate(-12deg);
}

.canvas-line--three {
  top: 63%;
  left: 18%;
  width: 58%;
  transform: rotate(10deg);
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
  --node-hover-scale: 1.14;
  --node-jolt-scale: 1.17;
  --node-dip-scale: 1.115;
  --node-snap-scale: 1.155;
  --node-depth: 0px;
  display: grid;
  align-content: start;
  gap: 11px;
  width: clamp(260px, 34%, 360px);
  min-height: 168px;
  padding: 22px;
  overflow: hidden;
  border: 1px solid rgba(236, 204, 136, 0.24);
  border-radius: 18px;
  background:
    linear-gradient(145deg, rgba(255, 241, 199, 0.1), transparent 46%),
    linear-gradient(180deg, rgba(255, 255, 255, 0.05), transparent 42%),
    rgba(16, 13, 8, 0.78);
  backdrop-filter: blur(18px) saturate(1.1);
  box-shadow:
    0 28px 70px rgba(0, 0, 0, 0.48),
    inset 0 1px 0 rgba(255, 255, 255, 0.12);
  cursor: pointer;
  outline: none;
  transform: translate3d(var(--node-x, 0), var(--node-y, 0), var(--node-depth)) rotateX(var(--node-tilt-x, 0deg)) rotateY(var(--node-tilt-y, 0deg)) rotate(var(--node-rotate, 0deg));
  transform-origin: center;
  transition:
    width 0.46s cubic-bezier(0.2, 0.8, 0.18, 1),
    transform 0.56s cubic-bezier(0.2, 0.8, 0.18, 1),
    z-index 0s linear 0.02s,
    border-color 0.28s ease,
    background 0.28s ease,
    min-height 0.42s cubic-bezier(0.2, 0.8, 0.18, 1),
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
  transition: opacity 0.24s ease;
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

.preview-node > span {
  position: relative;
  z-index: 1;
  color: #d6b56d;
  font-size: 11px;
  font-weight: 900;
  text-transform: uppercase;
}

.preview-node > span,
.preview-node strong,
.preview-node small,
.preview-node__signal {
  transition:
    opacity 0.28s ease,
    transform 0.36s cubic-bezier(0.2, 0.8, 0.18, 1),
    filter 0.28s ease;
}

.preview-node strong {
  position: relative;
  z-index: 1;
  color: #fff5d7;
  font-size: 28px;
  line-height: 1.1;
}

.preview-node small {
  position: relative;
  z-index: 1;
  color: rgba(249, 241, 220, 0.58);
  font-size: 13px;
  font-weight: 700;
  line-height: 1.45;
}

.preview-node__signal {
  position: relative;
  z-index: 1;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: fit-content;
  margin-top: 2px;
  padding: 5px 9px;
  border: 1px solid rgba(236, 204, 136, 0.08);
  border-radius: 999px;
  background: rgba(214, 181, 109, 0.12);
  color: rgba(255, 241, 199, 0.72);
  cursor: pointer;
  font-size: 11px;
  font-weight: 900;
  line-height: 1.2;
  box-shadow: inset 0 1px 0 rgba(255, 255, 255, 0.06);
}

.preview-node__signal:hover,
.preview-node__signal:focus-visible {
  border-color: rgba(255, 221, 151, 0.28);
  background: rgba(214, 181, 109, 0.2);
  color: #fff5d7;
  outline: none;
  box-shadow:
    0 0 18px rgba(214, 181, 109, 0.18),
    inset 0 1px 0 rgba(255, 255, 255, 0.1);
}

.preview-node__media {
  position: relative;
  z-index: 1;
  display: grid;
  gap: 8px;
  max-height: 0;
  opacity: 0;
  overflow: hidden;
  clip-path: inset(100% 0 0 0 round 14px);
  transition:
    max-height 0.44s cubic-bezier(0.2, 0.8, 0.18, 1),
    opacity 0.24s ease,
    clip-path 0.44s cubic-bezier(0.2, 0.8, 0.18, 1);
}

.preview-node__screen {
  position: relative;
  min-height: 82px;
  overflow: hidden;
  border: 1px solid rgba(236, 204, 136, 0.18);
  border-radius: 14px;
  background:
    radial-gradient(circle at 72% 22%, color-mix(in srgb, var(--preview-accent, #d6b56d) 28%, transparent), transparent 34%),
    linear-gradient(135deg, rgba(255, 241, 199, 0.1), transparent 42%),
    linear-gradient(180deg, rgba(6, 6, 5, 0.16), rgba(0, 0, 0, 0.68));
  box-shadow:
    inset 0 1px 0 rgba(255, 255, 255, 0.1),
    0 18px 36px rgba(0, 0, 0, 0.3);
  transition:
    min-height 0.46s cubic-bezier(0.2, 0.8, 0.18, 1),
    border-color 0.28s ease,
    box-shadow 0.28s ease;
}

.preview-node__screen video {
  position: absolute;
  inset: 0;
  z-index: 1;
  width: 100%;
  height: 100%;
  background: #030303;
  object-fit: contain;
  pointer-events: none;
  user-select: none;
}

.preview-node__screen video::-webkit-media-controls,
.preview-node__screen video::-webkit-media-controls-enclosure,
.preview-node__screen video::-webkit-media-controls-panel,
.preview-node__screen video::-webkit-media-controls-overlay-play-button,
.preview-node__screen video::-webkit-media-controls-start-playback-button {
  display: none !important;
  opacity: 0 !important;
  pointer-events: none !important;
}

.preview-node__screen::before,
.preview-node__screen::after {
  position: absolute;
  z-index: 2;
  content: "";
  pointer-events: none;
}

.preview-node__screen::before {
  inset: 12px 16px;
  border-radius: 12px;
  background:
    linear-gradient(90deg, rgba(255, 241, 199, 0.12) 1px, transparent 1px),
    linear-gradient(0deg, rgba(255, 241, 199, 0.08) 1px, transparent 1px);
  background-size: 22px 22px;
  opacity: 0.22;
}

.preview-node__screen::after {
  inset: auto 14px 14px;
  height: 2px;
  border-radius: 999px;
  background: linear-gradient(90deg, transparent, color-mix(in srgb, var(--preview-accent, #d6b56d) 82%, #fff 18%), transparent);
  opacity: 0.76;
  filter: drop-shadow(0 0 9px color-mix(in srgb, var(--preview-accent, #d6b56d) 52%, transparent));
  transform-origin: left;
  animation: previewSignal 1.8s ease-in-out infinite;
}

.preview-node__screen--video::before {
  inset: 0;
  border-radius: 0;
  background:
    linear-gradient(180deg, rgba(5, 5, 5, 0.02), rgba(5, 5, 5, 0.3)),
    linear-gradient(90deg, rgba(255, 241, 199, 0.08) 1px, transparent 1px),
    linear-gradient(0deg, rgba(255, 241, 199, 0.06) 1px, transparent 1px);
  background-size: auto, 22px 22px, 22px 22px;
  opacity: 0.38;
}

.preview-node__scan {
  position: absolute;
  inset: -30% auto -30% -24%;
  z-index: 2;
  width: 34%;
  background: linear-gradient(90deg, transparent, rgba(255, 245, 215, 0.2), transparent);
  filter: blur(2px);
  opacity: 0;
}

.preview-node__graph {
  position: absolute;
  right: 48px;
  bottom: 25px;
  left: 18px;
  z-index: 1;
  display: grid;
  grid-template-columns: repeat(7, 1fr);
  align-items: end;
  gap: 5px;
  height: 38px;
}

.preview-node__graph i {
  display: block;
  height: 38%;
  border-radius: 999px 999px 3px 3px;
  background: linear-gradient(180deg, #fff5d7, color-mix(in srgb, var(--preview-accent, #d6b56d) 82%, #997a35 18%));
  box-shadow: 0 0 14px color-mix(in srgb, var(--preview-accent, #d6b56d) 38%, transparent);
  opacity: 0.82;
  transform-origin: bottom;
}

.preview-node__graph i:nth-child(2) {
  animation-delay: -0.62s;
}

.preview-node__graph i:nth-child(3) {
  animation-delay: -1.12s;
}

.preview-node__graph i:nth-child(4) {
  animation-delay: -0.22s;
}

.preview-node__graph i:nth-child(5) {
  animation-delay: -0.86s;
}

.preview-node__graph i:nth-child(6) {
  animation-delay: -1.34s;
}

.preview-node__graph i:nth-child(7) {
  animation-delay: -0.44s;
}

.preview-node__play {
  position: absolute;
  right: 15px;
  bottom: 16px;
  z-index: 3;
  display: grid;
  width: 27px;
  height: 27px;
  place-items: center;
  border: 1px solid rgba(255, 241, 199, 0.26);
  border-radius: 999px;
  background: rgba(0, 0, 0, 0.38);
  color: #fff5d7;
  font-size: 9px;
  line-height: 1;
  box-shadow:
    0 0 18px color-mix(in srgb, var(--preview-accent, #d6b56d) 32%, transparent),
    inset 0 1px 0 rgba(255, 255, 255, 0.12);
}

.preview-node__timeline {
  height: 4px;
  overflow: hidden;
  border-radius: 999px;
  background: rgba(255, 241, 199, 0.12);
}

.preview-node__timeline span {
  display: block;
  width: 100%;
  height: 100%;
  border-radius: inherit;
  background: linear-gradient(90deg, #fff5d7, var(--preview-accent, #d6b56d));
  transform: scaleX(0);
  transform-origin: left;
}

.preview-node:hover .preview-node__media,
.preview-node:focus-visible .preview-node__media {
  max-height: 228px;
  opacity: 1;
  clip-path: inset(0 0 0 0 round 14px);
}

.preview-node:hover .preview-node__screen,
.preview-node:focus-visible .preview-node__screen {
  min-height: 184px;
  border-color: rgba(255, 221, 151, 0.34);
  box-shadow:
    0 28px 60px rgba(0, 0, 0, 0.42),
    0 0 32px color-mix(in srgb, var(--preview-accent, #d6b56d) 24%, transparent),
    inset 0 1px 0 rgba(255, 255, 255, 0.12);
}

.preview-node--has-video:hover,
.preview-node--has-video:focus-visible {
  width: clamp(340px, 43%, 470px);
  min-height: 386px;
  padding: 18px;
}

.preview-node--has-video:hover .preview-node__media,
.preview-node--has-video:focus-visible .preview-node__media {
  position: absolute;
  inset: 18px;
  display: grid;
  grid-template-rows: minmax(0, 1fr) 5px;
  max-height: none;
  animation: previewVideoRise 0.58s cubic-bezier(0.2, 0.8, 0.18, 1) both;
}

.preview-node--has-video:hover .preview-node__screen,
.preview-node--has-video:focus-visible .preview-node__screen {
  min-height: 0;
  border-radius: 18px;
}

.preview-node--has-video:hover .preview-node__timeline span,
.preview-node--has-video:focus-visible .preview-node__timeline span {
  animation: previewProgress 6s linear infinite;
}

.preview-node--has-video:hover > span,
.preview-node--has-video:hover > strong,
.preview-node--has-video:hover > small,
.preview-node--has-video:focus-visible > span,
.preview-node--has-video:focus-visible > strong,
.preview-node--has-video:focus-visible > small {
  opacity: 0;
  filter: blur(4px);
  transform: translateY(-10px);
}

.preview-node--has-video:hover > .preview-node__signal,
.preview-node--has-video:focus-visible > .preview-node__signal {
  position: absolute;
  top: 26px;
  right: 26px;
  z-index: 5;
  border-color: rgba(255, 221, 151, 0.26);
  background: rgba(6, 6, 5, 0.58);
  color: #fff5d7;
  filter: none;
  transform: none;
  backdrop-filter: blur(14px);
}

.preview-node:hover .preview-node__scan,
.preview-node:focus-visible .preview-node__scan {
  animation: previewScan 1.6s ease-in-out infinite;
}

.preview-node:hover .preview-node__graph i,
.preview-node:focus-visible .preview-node__graph i {
  animation: previewBar 1.28s ease-in-out infinite;
}

.preview-node:hover .preview-node__timeline span,
.preview-node:focus-visible .preview-node__timeline span {
  animation: previewProgress 3.8s linear infinite;
}

.preview-node--has-video:hover .preview-node__timeline span,
.preview-node--has-video:focus-visible .preview-node__timeline span {
  animation: previewProgress 6s linear infinite;
}

.preview-node:hover,
.preview-node:focus-visible {
  z-index: 20;
  min-height: 352px;
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
  animation: previewCardFlipJolt 0.74s cubic-bezier(0.2, 0.8, 0.18, 1) both;
  transform: translate3d(var(--node-hover-x, 0), var(--node-hover-y, 0), calc(var(--node-depth) + 42px)) rotateX(var(--node-hover-tilt-x, 0deg)) rotateY(var(--node-hover-tilt-y, 0deg)) rotate(var(--node-hover-rotate, 0deg)) scale(var(--node-hover-scale));
}

.preview-node:hover::after,
.preview-node:focus-visible::after {
  opacity: 0.18;
}

.preview-node--has-video:hover::before,
.preview-node--has-video:focus-visible::before {
  opacity: 0;
}

.preview-node--script {
  top: 7%;
  left: 3%;
  --preview-accent: #f0c66d;
  --node-depth: 38px;
  --node-tilt-x: 1.5deg;
  --node-tilt-y: -7deg;
  --node-rotate: -3.2deg;
  --node-hover-tilt-x: 0deg;
  --node-hover-tilt-y: -3deg;
  --node-hover-rotate: -0.8deg;
  --node-hover-scale: 1.16;
  --node-jolt-scale: 1.2;
  --node-dip-scale: 1.13;
  --node-snap-scale: 1.175;
  --node-z: 8;
  --node-hover-x: 20px;
  --node-hover-y: 22px;
  width: clamp(300px, 39%, 410px);
  min-height: 184px;
}

.preview-node--asset {
  top: 13%;
  right: 3%;
  --preview-accent: #e3ad57;
  --node-depth: 14px;
  --node-tilt-x: -1deg;
  --node-tilt-y: 6deg;
  --node-rotate: 2.2deg;
  --node-hover-tilt-x: 0deg;
  --node-hover-tilt-y: 3deg;
  --node-hover-rotate: 0.7deg;
  --node-z: 6;
  --node-hover-x: -20px;
  --node-hover-y: 16px;
  width: clamp(280px, 36%, 382px);
}

.preview-node--shot {
  right: 9%;
  bottom: 6%;
  --preview-accent: #d8c08a;
  --node-depth: -10px;
  --node-tilt-x: 4deg;
  --node-tilt-y: 4deg;
  --node-rotate: -1.6deg;
  --node-hover-tilt-x: 1deg;
  --node-hover-tilt-y: 2deg;
  --node-hover-rotate: -0.4deg;
  --node-z: 4;
  --node-hover-x: -14px;
  --node-hover-y: -20px;
  width: clamp(260px, 33%, 354px);
}

.preview-node--video {
  bottom: 10%;
  left: 5%;
  --preview-accent: #f7dd93;
  --node-depth: 3px;
  --node-tilt-x: 3deg;
  --node-tilt-y: -5deg;
  --node-rotate: 2.6deg;
  --node-hover-tilt-x: 1deg;
  --node-hover-tilt-y: -2deg;
  --node-hover-rotate: 0.6deg;
  --node-z: 5;
  --node-hover-x: 18px;
  --node-hover-y: -16px;
  width: clamp(270px, 34%, 370px);
}

.problem-section {
  position: relative;
  order: 2;
  padding: 0 clamp(18px, 6vw, 92px) 92px;
  overflow: hidden;
}

.problem-section::before {
  position: absolute;
  inset: -40px 10% auto;
  height: 260px;
  background:
    radial-gradient(ellipse at 50% 50%, rgba(236, 204, 136, 0.16), transparent 66%),
    linear-gradient(90deg, transparent, rgba(214, 181, 109, 0.08), transparent);
  content: "";
  filter: blur(28px);
  opacity: 0.82;
  pointer-events: none;
}

.problem-section__intro {
  position: relative;
  z-index: 1;
  display: grid;
  gap: 14px;
  max-width: 980px;
  margin: 0 auto 34px;
  text-align: center;
}

.problem-section__intro span,
.section-kicker {
  justify-self: center;
  width: fit-content;
  padding: 7px 12px;
  border: 1px solid rgba(236, 204, 136, 0.18);
  border-radius: 999px;
  background: rgba(214, 181, 109, 0.08);
  color: #d6b56d;
  font-size: 12px;
  font-weight: 900;
  letter-spacing: 0.08em;
  text-transform: uppercase;
}

.problem-section__intro h2 {
  margin: 0;
  color: #fff5d7;
  font-size: clamp(34px, 4.8vw, 68px);
  line-height: 1.04;
}

.problem-section__intro p {
  max-width: 860px;
  margin: 0 auto;
  color: rgba(249, 241, 220, 0.62);
  font-size: 16px;
  font-weight: 700;
  line-height: 1.75;
}

.problem-grid {
  position: relative;
  z-index: 1;
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 14px;
  max-width: 1240px;
  margin: 0 auto;
}

.problem-card {
  position: relative;
  display: grid;
  align-content: start;
  gap: 14px;
  min-height: 250px;
  padding: 24px;
  overflow: hidden;
  border: 1px solid rgba(236, 204, 136, 0.14);
  border-radius: 20px;
  background:
    linear-gradient(180deg, rgba(255, 255, 255, 0.05), transparent 54%),
    rgba(10, 9, 6, 0.78);
  box-shadow:
    0 28px 72px rgba(0, 0, 0, 0.34),
    inset 0 1px 0 rgba(255, 255, 255, 0.07);
}

.problem-card::before {
  position: absolute;
  inset: 0;
  background:
    radial-gradient(circle at 18% 14%, rgba(214, 181, 109, 0.16), transparent 28%),
    linear-gradient(110deg, transparent 0 38%, rgba(255, 241, 199, 0.1) 48%, transparent 60%);
  content: "";
  opacity: 0.34;
  transform: translateX(-28%);
  animation: detailCardSheen 6s ease-in-out infinite;
  pointer-events: none;
}

.problem-card:nth-child(2n)::before {
  animation-delay: -1.4s;
}

.problem-card:nth-child(3n)::before {
  animation-delay: -2.8s;
}

.problem-card > * {
  position: relative;
  z-index: 1;
}

.problem-card__index {
  color: rgba(214, 181, 109, 0.7);
  font-size: 12px;
  font-weight: 950;
  letter-spacing: 0.1em;
}

.problem-card svg {
  color: #d6b56d;
  filter: drop-shadow(0 0 16px rgba(214, 181, 109, 0.24));
}

.problem-card strong {
  color: #fff5d7;
  font-size: 22px;
  line-height: 1.18;
}

.problem-card p {
  margin: 0;
  color: rgba(249, 241, 220, 0.6);
  font-size: 14px;
  font-weight: 700;
  line-height: 1.65;
}

.workflow-detail-section {
  position: relative;
  order: 4;
  padding: 8px clamp(18px, 6vw, 92px) 92px;
  overflow: hidden;
}

.workflow-detail-section::before {
  position: absolute;
  inset: -80px 8% auto;
  height: 240px;
  background:
    radial-gradient(ellipse at 50% 50%, rgba(236, 204, 136, 0.18), transparent 68%),
    linear-gradient(90deg, transparent, rgba(214, 181, 109, 0.1), transparent);
  content: "";
  filter: blur(28px);
  opacity: 0.74;
  pointer-events: none;
}

.workflow-detail-section__intro {
  position: relative;
  z-index: 1;
  display: grid;
  gap: 14px;
  max-width: 900px;
  margin: 0 auto 34px;
  text-align: center;
}

.workflow-detail-section__intro span {
  justify-self: center;
  padding: 7px 12px;
  border: 1px solid rgba(236, 204, 136, 0.18);
  border-radius: 999px;
  background: rgba(214, 181, 109, 0.08);
  color: #d6b56d;
  font-size: 12px;
  font-weight: 900;
  letter-spacing: 0.08em;
  text-transform: uppercase;
}

.workflow-detail-section__intro h2 {
  margin: 0;
  color: #fff5d7;
  font-size: clamp(32px, 4vw, 58px);
  line-height: 1.06;
}

.workflow-detail-section__intro p {
  margin: 0;
  color: rgba(249, 241, 220, 0.62);
  font-size: 16px;
  font-weight: 700;
  line-height: 1.75;
}

.workflow-detail-grid {
  position: relative;
  z-index: 1;
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 18px;
  max-width: 1180px;
  margin: 0 auto;
}

.workflow-detail-grid::before {
  position: absolute;
  top: 42px;
  bottom: 42px;
  left: 50%;
  width: 1px;
  background: linear-gradient(180deg, transparent, rgba(214, 181, 109, 0.34), transparent);
  content: "";
  opacity: 0.58;
  pointer-events: none;
}

.workflow-detail-card {
  position: relative;
  display: grid;
  grid-template-columns: auto minmax(0, 1fr);
  gap: 22px;
  min-height: 300px;
  padding: 28px;
  overflow: hidden;
  scroll-margin-top: 110px;
  border: 1px solid rgba(236, 204, 136, 0.16);
  border-radius: 24px;
  background:
    linear-gradient(135deg, rgba(255, 241, 199, 0.08), transparent 44%),
    linear-gradient(180deg, rgba(255, 255, 255, 0.045), transparent 54%),
    rgba(11, 10, 7, 0.84);
  box-shadow:
    0 30px 80px rgba(0, 0, 0, 0.34),
    inset 0 1px 0 rgba(255, 255, 255, 0.08);
  isolation: isolate;
}

.workflow-detail-card::before,
.workflow-detail-card::after {
  position: absolute;
  content: "";
  pointer-events: none;
}

.workflow-detail-card::before {
  inset: 0;
  z-index: -1;
  background:
    radial-gradient(circle at 16% 18%, rgba(214, 181, 109, 0.16), transparent 30%),
    linear-gradient(105deg, transparent 0 38%, rgba(255, 241, 199, 0.11) 48%, transparent 58%);
  opacity: 0.62;
  transform: translateX(-22%);
  animation: detailCardSheen 6.4s ease-in-out infinite;
}

.workflow-detail-card::after {
  right: 24px;
  bottom: 24px;
  width: 160px;
  height: 160px;
  border: 1px solid rgba(214, 181, 109, 0.1);
  border-radius: 999px;
  background: radial-gradient(circle, rgba(214, 181, 109, 0.1), transparent 62%);
  opacity: 0.8;
}

.workflow-detail-card:nth-child(2n)::before {
  animation-delay: -1.8s;
}

.workflow-detail-card:nth-child(3n)::before {
  animation-delay: -3.2s;
}

.workflow-detail-card__index {
  display: grid;
  width: 62px;
  height: 62px;
  place-items: center;
  border: 1px solid rgba(255, 221, 151, 0.24);
  border-radius: 18px;
  background:
    linear-gradient(180deg, rgba(255, 241, 199, 0.12), rgba(214, 181, 109, 0.06)),
    rgba(0, 0, 0, 0.28);
  color: #f3d894;
  font-size: 18px;
  font-weight: 950;
  box-shadow:
    0 0 28px rgba(214, 181, 109, 0.12),
    inset 0 1px 0 rgba(255, 255, 255, 0.12);
}

.workflow-detail-card__content {
  position: relative;
  z-index: 1;
  display: grid;
  gap: 14px;
}

.workflow-detail-card__content span {
  color: #d6b56d;
  font-size: 12px;
  font-weight: 900;
  letter-spacing: 0.08em;
  text-transform: uppercase;
}

.workflow-detail-card__content h3 {
  margin: 0;
  color: #fff5d7;
  font-size: clamp(24px, 2.4vw, 34px);
  line-height: 1.14;
}

.workflow-detail-card__content p {
  margin: 0;
  color: rgba(249, 241, 220, 0.66);
  font-size: 14px;
  font-weight: 700;
  line-height: 1.75;
}

.workflow-detail-card__content ul {
  display: grid;
  gap: 10px;
  margin: 2px 0 0;
  padding: 0;
  list-style: none;
}

.workflow-detail-card__content li {
  position: relative;
  padding-left: 18px;
  color: rgba(255, 248, 230, 0.78);
  font-size: 14px;
  font-weight: 750;
  line-height: 1.58;
}

.workflow-detail-card__content li::before {
  position: absolute;
  top: 0.68em;
  left: 0;
  width: 7px;
  height: 7px;
  border-radius: 999px;
  background: #d6b56d;
  box-shadow: 0 0 14px rgba(214, 181, 109, 0.54);
  content: "";
}

.workflow-detail-card__chips {
  position: relative;
  z-index: 1;
  display: flex;
  grid-column: 1 / -1;
  flex-wrap: wrap;
  gap: 8px;
  align-self: end;
}

.workflow-detail-card__chips span {
  padding: 7px 10px;
  border: 1px solid rgba(236, 204, 136, 0.14);
  border-radius: 999px;
  background: rgba(214, 181, 109, 0.09);
  color: rgba(255, 241, 199, 0.76);
  font-size: 12px;
  font-weight: 900;
}

.workflow-detail-card:target,
.workflow-detail-card.is-target {
  border-color: rgba(255, 221, 151, 0.46);
  box-shadow:
    0 34px 92px rgba(0, 0, 0, 0.42),
    0 0 46px rgba(214, 181, 109, 0.18),
    inset 0 1px 0 rgba(255, 255, 255, 0.1);
  animation: detailTargetPulse 1.6s ease both;
}

.project-agent-showcase {
  position: relative;
  order: 5;
  padding: 0 clamp(18px, 6vw, 92px) 104px;
  overflow: hidden;
}

.project-agent-showcase::before {
  position: absolute;
  inset: 6% -8% auto;
  height: 360px;
  background:
    radial-gradient(ellipse at 50% 45%, rgba(236, 204, 136, 0.18), transparent 64%),
    radial-gradient(circle at 72% 20%, rgba(255, 248, 230, 0.1), transparent 30%);
  content: "";
  filter: blur(30px);
  opacity: 0.8;
  pointer-events: none;
}

.project-agent-showcase__intro {
  position: relative;
  z-index: 1;
  display: grid;
  gap: 14px;
  max-width: 980px;
  margin: 0 auto 34px;
  text-align: center;
}

.project-agent-showcase__intro span {
  justify-self: center;
  padding: 7px 12px;
  border: 1px solid rgba(236, 204, 136, 0.2);
  border-radius: 999px;
  background: rgba(214, 181, 109, 0.09);
  color: #d6b56d;
  font-size: 12px;
  font-weight: 900;
  letter-spacing: 0.08em;
  text-transform: uppercase;
}

.project-agent-showcase__intro h2 {
  margin: 0;
  color: #fff5d7;
  font-size: clamp(34px, 4.6vw, 64px);
  line-height: 1.05;
}

.project-agent-showcase__intro p {
  margin: 0 auto;
  max-width: 820px;
  color: rgba(249, 241, 220, 0.62);
  font-size: 16px;
  font-weight: 700;
  line-height: 1.75;
}

.project-agent-stage {
  position: relative;
  z-index: 1;
  display: grid;
  grid-template-columns: minmax(300px, 0.78fr) minmax(0, 1.22fr);
  gap: 24px;
  max-width: 1240px;
  margin: 0 auto;
  padding: 28px;
  overflow: hidden;
  border: 1px solid rgba(236, 204, 136, 0.18);
  border-radius: 30px;
  background:
    linear-gradient(145deg, rgba(255, 241, 199, 0.07), transparent 44%),
    radial-gradient(ellipse at 70% 40%, rgba(214, 181, 109, 0.13), transparent 48%),
    rgba(7, 7, 6, 0.9);
  box-shadow:
    0 42px 130px rgba(0, 0, 0, 0.5),
    inset 0 1px 0 rgba(255, 255, 255, 0.08);
}

.project-agent-stage::before {
  position: absolute;
  inset: 24px;
  border: 1px solid rgba(214, 181, 109, 0.08);
  border-radius: 24px;
  background:
    linear-gradient(90deg, rgba(255, 241, 199, 0.045) 1px, transparent 1px),
    linear-gradient(0deg, rgba(255, 241, 199, 0.035) 1px, transparent 1px);
  background-size: 52px 52px;
  content: "";
  mask-image: radial-gradient(ellipse at 50% 50%, #000 0 58%, transparent 78%);
  pointer-events: none;
}

.project-agent-stage__aurora {
  position: absolute;
  inset: 8% 12%;
  border-radius: 999px;
  background:
    linear-gradient(100deg, transparent 8%, rgba(214, 181, 109, 0.18), transparent 68%),
    radial-gradient(ellipse at 50% 50%, rgba(255, 241, 199, 0.12), transparent 62%);
  filter: blur(16px);
  opacity: 0.74;
  transform: rotate(-8deg);
  animation: agentAurora 5.4s ease-in-out infinite;
  pointer-events: none;
}

.project-agent-hero {
  position: relative;
  z-index: 1;
  display: grid;
  align-content: space-between;
  justify-items: center;
  gap: 24px;
  min-height: 520px;
  padding: 30px;
  overflow: hidden;
  border: 1px solid rgba(255, 221, 151, 0.22);
  border-radius: 24px;
  background:
    linear-gradient(180deg, rgba(255, 255, 255, 0.06), transparent 46%),
    radial-gradient(circle at 30% 22%, rgba(214, 181, 109, 0.18), transparent 34%),
    rgba(12, 10, 7, 0.86);
  box-shadow:
    0 34px 84px rgba(0, 0, 0, 0.38),
    inset 0 1px 0 rgba(255, 255, 255, 0.1);
}

.project-agent-hero::before,
.project-agent-hero::after {
  position: absolute;
  content: "";
  pointer-events: none;
}

.project-agent-hero::before {
  inset: 44% auto auto 50%;
  width: 260px;
  height: 260px;
  border: 1px solid rgba(214, 181, 109, 0.16);
  border-radius: 999px;
  box-shadow:
    0 0 0 38px rgba(214, 181, 109, 0.025),
    0 0 0 82px rgba(214, 181, 109, 0.018),
    0 0 70px rgba(214, 181, 109, 0.2);
  transform: translate(-50%, -50%);
  animation: agentCorePulse 3.8s ease-in-out infinite;
}

.project-agent-hero::after {
  inset: -30% auto -20% -22%;
  width: 42%;
  background: linear-gradient(90deg, transparent, rgba(255, 241, 199, 0.14), transparent);
  filter: blur(4px);
  transform: rotate(14deg);
  animation: agentCardSweep 4.8s ease-in-out infinite;
}

.project-agent-hero__eyebrow {
  position: relative;
  z-index: 1;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 8px;
  width: fit-content;
  justify-self: center;
  color: #f3d894;
  font-size: 12px;
  font-weight: 950;
  letter-spacing: 0.08em;
  text-transform: uppercase;
}

.project-agent-hero h3 {
  position: relative;
  z-index: 1;
  max-width: 460px;
  margin: 0;
  color: #fff5d7;
  font-size: clamp(32px, 3.4vw, 52px);
  line-height: 1.03;
  text-align: center;
}

.project-agent-hero p {
  position: relative;
  z-index: 1;
  max-width: 470px;
  margin: 0 auto;
  color: rgba(249, 241, 220, 0.66);
  font-size: 15px;
  font-weight: 750;
  line-height: 1.72;
  text-align: center;
}

.project-agent-hero__metrics {
  position: relative;
  z-index: 1;
  display: grid;
  width: 100%;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 10px;
}

.project-agent-hero__metrics span {
  display: grid;
  gap: 5px;
  min-height: 82px;
  padding: 15px;
  border: 1px solid rgba(236, 204, 136, 0.14);
  border-radius: 16px;
  background: rgba(0, 0, 0, 0.24);
  color: rgba(249, 241, 220, 0.58);
  font-size: 12px;
  font-weight: 850;
  justify-items: center;
  text-align: center;
}

.project-agent-hero__metrics strong {
  color: #ffe4a2;
  font-size: 24px;
  line-height: 1;
}

.project-agent-orbit {
  position: absolute;
  top: 50%;
  left: 42%;
  z-index: 0;
  width: 330px;
  height: 330px;
  border: 1px solid rgba(214, 181, 109, 0.12);
  border-radius: 999px;
  opacity: 0.72;
  transform: translate(-50%, -50%);
  animation: agentOrbitTurn 18s linear infinite;
  pointer-events: none;
}

.project-agent-orbit span {
  position: absolute;
  width: 11px;
  height: 11px;
  border-radius: 999px;
  background: #d6b56d;
  box-shadow: 0 0 20px rgba(214, 181, 109, 0.78);
}

.project-agent-orbit span:nth-child(1) {
  top: -5px;
  left: 50%;
}

.project-agent-orbit span:nth-child(2) {
  right: 10%;
  bottom: 14%;
}

.project-agent-orbit span:nth-child(3) {
  bottom: 24%;
  left: 2%;
}

.project-agent-grid {
  position: relative;
  z-index: 1;
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 14px;
}

.project-agent-card {
  position: relative;
  display: grid;
  gap: 10px;
  min-height: 164px;
  padding: 20px;
  overflow: hidden;
  border: 1px solid rgba(236, 204, 136, 0.14);
  border-radius: 18px;
  background:
    linear-gradient(180deg, rgba(255, 255, 255, 0.045), transparent 58%),
    rgba(255, 255, 255, 0.028);
  box-shadow: inset 0 1px 0 rgba(255, 255, 255, 0.06);
  transition:
    transform 0.28s ease,
    border-color 0.28s ease,
    box-shadow 0.28s ease,
    background 0.28s ease;
}

.project-agent-card::before {
  position: absolute;
  inset: 0;
  background:
    radial-gradient(circle at 20% 16%, rgba(214, 181, 109, 0.18), transparent 28%),
    linear-gradient(105deg, transparent 0 38%, rgba(255, 241, 199, 0.12) 48%, transparent 58%);
  content: "";
  opacity: 0;
  transform: translateX(-34%);
  animation: agentCardSweep 5.8s ease-in-out infinite;
  pointer-events: none;
}

.project-agent-card:nth-child(2n)::before {
  animation-delay: -1.1s;
}

.project-agent-card:nth-child(3n)::before {
  animation-delay: -2.4s;
}

.project-agent-card:hover {
  border-color: rgba(255, 221, 151, 0.32);
  background:
    linear-gradient(180deg, rgba(255, 255, 255, 0.06), transparent 58%),
    rgba(214, 181, 109, 0.055);
  box-shadow:
    0 18px 44px rgba(0, 0, 0, 0.28),
    0 0 28px rgba(214, 181, 109, 0.12),
    inset 0 1px 0 rgba(255, 255, 255, 0.08);
  transform: translateY(-3px);
}

.project-agent-card > * {
  position: relative;
  z-index: 1;
}

.project-agent-card__icon {
  display: grid;
  width: 44px;
  height: 44px;
  place-items: center;
  border: 1px solid rgba(255, 221, 151, 0.22);
  border-radius: 14px;
  background: rgba(214, 181, 109, 0.1);
  color: #f3d894;
  box-shadow: 0 0 20px rgba(214, 181, 109, 0.12);
}

.project-agent-card__role {
  color: #d6b56d;
  font-size: 11px;
  font-weight: 950;
  letter-spacing: 0.06em;
  text-transform: uppercase;
}

.project-agent-card strong {
  color: #fff5d7;
  font-size: 21px;
  line-height: 1.15;
}

.project-agent-card p {
  margin: 0;
  color: rgba(249, 241, 220, 0.58);
  font-size: 13px;
  font-weight: 700;
  line-height: 1.58;
}

.project-agent-card__signal {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  width: fit-content;
  margin-top: 2px;
  color: rgba(255, 241, 199, 0.72);
  font-size: 11px;
  font-weight: 900;
}

.project-agent-card__signal i {
  display: block;
  width: 8px;
  height: 8px;
  border-radius: 999px;
  background: #d6b56d;
  box-shadow: 0 0 14px rgba(214, 181, 109, 0.64);
  animation: agentNodePulse 1.8s ease-in-out infinite;
}

.project-agent-pipeline {
  position: relative;
  z-index: 1;
  display: grid;
  grid-column: 1 / -1;
  grid-template-columns: repeat(6, minmax(0, 1fr));
  gap: 8px;
  padding-top: 8px;
}

.project-agent-pipeline span {
  position: relative;
  min-height: 44px;
  padding: 12px 10px;
  overflow: hidden;
  border: 1px solid rgba(236, 204, 136, 0.14);
  border-radius: 999px;
  background: rgba(214, 181, 109, 0.07);
  color: rgba(255, 241, 199, 0.78);
  font-size: 12px;
  font-weight: 900;
  text-align: center;
}

.project-agent-pipeline span::before {
  position: absolute;
  inset: 0;
  background: linear-gradient(90deg, transparent, rgba(255, 241, 199, 0.18), transparent);
  content: "";
  transform: translateX(-100%);
  animation: agentPipelineFlow 3.8s linear infinite;
}

.project-agent-pipeline span:nth-child(2)::before {
  animation-delay: 0.22s;
}

.project-agent-pipeline span:nth-child(3)::before {
  animation-delay: 0.44s;
}

.project-agent-pipeline span:nth-child(4)::before {
  animation-delay: 0.66s;
}

.project-agent-pipeline span:nth-child(5)::before {
  animation-delay: 0.88s;
}

.project-agent-pipeline span:nth-child(6)::before {
  animation-delay: 1.1s;
}

.capability-band {
  position: relative;
  order: 3;
  overflow: hidden;
  padding: 0 clamp(18px, 6vw, 92px) 88px;
  mask-image: linear-gradient(90deg, transparent 0, #000 7%, #000 93%, transparent 100%);
}

.guest-community-band {
  order: 6;
}

.capability-band::before {
  position: absolute;
  inset: -10% 5% auto;
  height: 120px;
  background: radial-gradient(ellipse at 50% 50%, rgba(214, 181, 109, 0.16), transparent 68%);
  content: "";
  filter: blur(28px);
  opacity: 0.72;
  pointer-events: none;
}

.capability-track {
  display: flex;
  gap: 16px;
  width: max-content;
  animation: capabilityMarquee 28s linear infinite;
  will-change: transform;
}

.capability-card {
  position: relative;
  display: grid;
  gap: 10px;
  flex: 0 0 400px;
  min-height: 156px;
  padding: 24px;
  overflow: hidden;
  border: 1px solid rgba(214, 181, 109, 0.13);
  border-radius: 18px;
  background:
    linear-gradient(180deg, rgba(255, 255, 255, 0.045), transparent 58%),
    rgba(255, 255, 255, 0.028);
  box-shadow: inset 0 1px 0 rgba(255, 255, 255, 0.06);
}

.capability-card::before {
  position: absolute;
  inset: 0;
  background:
    linear-gradient(105deg, transparent 0 34%, rgba(255, 241, 199, 0.12) 45%, transparent 58%),
    radial-gradient(circle at 14% 12%, rgba(214, 181, 109, 0.13), transparent 28%);
  content: "";
  opacity: 0;
  transform: translateX(-35%);
  animation: capabilitySheen 5.6s ease-in-out infinite;
  pointer-events: none;
}

.capability-card:nth-child(2n)::before {
  animation-delay: -1.4s;
}

.capability-card:nth-child(3n)::before {
  animation-delay: -2.8s;
}

.capability-card > * {
  position: relative;
  z-index: 1;
}

.capability-card svg {
  color: #d6b56d;
  filter: drop-shadow(0 0 14px rgba(214, 181, 109, 0.24));
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

.model-showcase {
  position: relative;
  order: 4;
  width: min(1220px, calc(100vw - 48px));
  margin: -22px auto 92px;
}

.model-showcase__heading {
  display: grid;
  justify-items: center;
  gap: 12px;
  margin-bottom: 28px;
  text-align: center;
}

.model-showcase__heading span {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  padding: 7px 12px;
  border: 1px solid rgba(82, 210, 214, 0.22);
  border-radius: 999px;
  background: rgba(82, 210, 214, 0.06);
  color: #b9fbff;
  font-size: 12px;
  font-weight: 900;
  text-transform: uppercase;
}

.model-showcase__heading h2 {
  margin: 0;
  color: #fff5d7;
  font-size: clamp(34px, 4.4vw, 60px);
  line-height: 1.05;
}

.model-showcase__heading p {
  margin: 0;
  max-width: 720px;
  color: rgba(249, 241, 220, 0.62);
  font-size: 16px;
  line-height: 1.7;
}

.model-showcase__stage {
  position: relative;
  display: grid;
  align-content: center;
  gap: 18px;
  min-height: 300px;
  padding: 44px 0;
  overflow: hidden;
  border: 1px solid rgba(214, 181, 109, 0.16);
  border-radius: 28px;
  background:
    linear-gradient(180deg, rgba(255, 255, 255, 0.052), rgba(255, 255, 255, 0.018)),
    linear-gradient(135deg, rgba(82, 210, 214, 0.065), transparent 38%, rgba(214, 181, 109, 0.075));
  box-shadow:
    0 30px 90px rgba(0, 0, 0, 0.34),
    inset 0 1px 0 rgba(255, 255, 255, 0.08);
}

.model-showcase__stage::before,
.model-showcase__stage::after {
  position: absolute;
  inset: 0;
  content: "";
  pointer-events: none;
}

.model-showcase__stage::before {
  background:
    linear-gradient(90deg, #050505 0, transparent 14%, transparent 86%, #050505 100%),
    repeating-linear-gradient(90deg, rgba(255, 241, 199, 0.04) 0 1px, transparent 1px 84px);
  opacity: 0.86;
}

.model-showcase__stage::after {
  border-radius: inherit;
  background: linear-gradient(110deg, transparent 0 36%, rgba(255, 241, 199, 0.16) 48%, rgba(82, 210, 214, 0.1) 54%, transparent 68%);
  mix-blend-mode: screen;
  transform: translateX(-82%);
  animation: modelStageSweep 7.2s ease-in-out infinite;
}

.model-stream {
  position: relative;
  z-index: 2;
  display: block;
  min-width: 0;
}

.model-stream__track {
  display: flex;
  gap: 14px;
  width: max-content;
  min-width: 100%;
  animation: modelRailFlow var(--stream-duration) linear infinite;
  will-change: transform;
}

.model-stream--reverse .model-stream__track {
  animation-direction: reverse;
}

.model-chip {
  position: relative;
  flex: 0 0 auto;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 11px;
  min-width: 176px;
  min-height: 66px;
  padding: 12px 18px 12px 12px;
  overflow: hidden;
  border: 1px solid rgba(255, 241, 199, 0.16);
  border-radius: 18px;
  background:
    linear-gradient(180deg, rgba(255, 255, 255, 0.07), rgba(255, 255, 255, 0.02)),
    rgba(4, 10, 11, 0.74);
  color: rgba(255, 248, 230, 0.9);
  font-size: 13px;
  font-weight: 900;
  text-align: center;
  white-space: nowrap;
  box-shadow:
    inset 0 1px 0 rgba(255, 255, 255, 0.08),
    0 0 24px rgba(82, 210, 214, 0.08);
}

.model-chip__icon {
  position: relative;
  z-index: 1;
  display: grid;
  place-items: center;
  width: 38px;
  height: 38px;
  padding: 7px;
  border: 1px solid rgba(255, 241, 199, 0.14);
  border-radius: 12px;
  background: rgba(255, 250, 236, 0.92);
  box-shadow: inset 0 1px 0 rgba(255, 255, 255, 0.6);
}

.model-chip__icon img {
  display: block;
  width: 100%;
  height: 100%;
  object-fit: contain;
}

.model-chip > span:last-child {
  position: relative;
  z-index: 1;
}

.model-chip::before {
  position: absolute;
  inset: 0;
  background: linear-gradient(105deg, transparent 0 36%, rgba(255, 241, 199, 0.24) 48%, rgba(82, 210, 214, 0.18) 56%, transparent 68%);
  content: "";
  opacity: 0;
  transform: translateX(-72%);
  animation: modelChipSheen 4.8s ease-in-out infinite;
}

.model-stream--reverse .model-chip::before {
  animation-delay: -1.2s;
}

.home-workbench {
  display: block;
  padding-left: 76px;
  background: #050505;
}

.workbench-rail {
  position: fixed;
  top: 0;
  left: 0;
  z-index: 15;
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

.rail-separator {
  width: 32px;
  height: 1px;
  margin: 4px 0;
  background: rgba(214, 181, 109, 0.12);
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

.top-chip--home {
  border-color: rgba(255, 221, 151, 0.36);
  background: rgba(214, 181, 109, 0.12);
  color: #fff1c7;
}

.top-chip--home:hover {
  border-color: rgba(255, 221, 151, 0.5);
  background: rgba(214, 181, 109, 0.18);
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
  width: min(980px, 100%);
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
  font-size: 52px;
  letter-spacing: 0;
}

.creator-headline {
  display: block;
  width: 100%;
  min-height: 1.18em;
  overflow: hidden;
  white-space: nowrap;
}

.creator-headline span {
  display: inline-block;
  max-width: 100%;
  animation: creator-headline-rise 0.58s cubic-bezier(0.22, 1, 0.36, 1);
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

.creation-start {
  width: min(1180px, calc(100vw - 140px));
  padding-top: 14px;
}

.creation-heading {
  align-items: flex-end;
  margin-bottom: 16px;
}

.creation-heading > div:first-child {
  display: grid;
  gap: 8px;
}

.creation-heading p {
  max-width: 620px;
  margin: 0;
  color: rgba(249, 241, 220, 0.58);
  font-size: 14px;
  font-weight: 700;
  line-height: 1.55;
}

.creation-heading__actions {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}

.creation-heading__actions button {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  min-height: 34px;
  padding: 0 12px;
  border: 1px solid rgba(255, 241, 199, 0.14);
  border-radius: 999px;
  background: rgba(255, 255, 255, 0.06);
  color: rgba(249, 241, 220, 0.8);
  font-size: 12px;
  font-weight: 900;
}

.creation-heading__actions button:first-child {
  border-color: rgba(255, 221, 151, 0.34);
  background: rgba(214, 181, 109, 0.14);
  color: #fff1c7;
}

.project-strip {
  display: grid;
  grid-auto-flow: column;
  grid-auto-columns: 260px;
  gap: 16px;
  overflow-x: auto;
  overflow-y: hidden;
  padding: 2px 2px 10px;
  scroll-snap-type: x proximity;
  scrollbar-width: thin;
}

.project-card--strip {
  min-height: 184px;
  scroll-snap-align: start;
}

.project-card--new-inline {
  border-color: rgba(255, 221, 151, 0.28);
}

.showcase-section,
.ecosystem-agent-section {
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

.project-grid--focused {
  grid-template-columns: repeat(2, minmax(0, 1fr));
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

.project-card--create-primary {
  grid-row: span 2;
  min-height: 100%;
  border-color: rgba(255, 221, 151, 0.34);
  background:
    radial-gradient(circle at 50% 30%, rgba(214, 181, 109, 0.18), transparent 44%),
    linear-gradient(145deg, rgba(214, 181, 109, 0.14), rgba(255, 255, 255, 0.045));
}

.project-card--create-primary .project-card__preview--empty {
  min-height: 190px;
}

.project-card--create-primary strong {
  font-size: 20px;
}

.project-card--create-primary small {
  color: rgba(255, 248, 230, 0.66);
  font-size: 13px;
  line-height: 1.5;
  white-space: normal;
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

.project-card__hint-icon {
  display: grid;
  place-items: center;
  width: 42px;
  height: 42px;
  margin: 8px 4px 4px;
  border: 1px solid rgba(255, 241, 199, 0.18);
  border-radius: 8px;
  background: rgba(214, 181, 109, 0.1);
  color: #fff1c7;
}

.project-card--hint {
  min-height: 156px;
  align-content: center;
  cursor: default;
  background:
    linear-gradient(145deg, rgba(214, 181, 109, 0.06), transparent 62%),
    rgba(255, 255, 255, 0.035);
}

.project-card--hint small {
  line-height: 1.5;
  white-space: normal;
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

.guest-community-band {
  width: min(1120px, calc(100vw - 48px));
  margin: 64px auto 0;
}

.community-section {
  margin-top: 46px;
}

.community-space {
  width: min(1280px, calc(100vw - 120px));
  min-height: 680px;
  padding: 82px clamp(16px, 4vw, 52px) 120px;
  overflow: hidden;
  border-radius: 10px;
  background:
    linear-gradient(rgba(214, 181, 109, 0.045) 1px, transparent 1px),
    linear-gradient(90deg, rgba(214, 181, 109, 0.045) 1px, transparent 1px),
    radial-gradient(circle at 24% 18%, rgba(214, 181, 109, 0.18), transparent 26%),
    radial-gradient(circle at 82% 48%, rgba(120, 96, 52, 0.14), transparent 28%),
    rgba(255, 255, 255, 0.018);
  background-size: 42px 42px, 42px 42px, auto, auto, auto;
}

.community-space__heading {
  max-width: 620px;
  margin-bottom: 34px;
}

.community-grid {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 16px;
}

.community-grid--space {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(320px, 420px));
  align-items: start;
  justify-content: start;
  gap: 24px;
  min-height: 0;
}

.community-card--space {
  width: 100%;
  min-height: 480px;
  animation: community-rise linear both;
  animation-timeline: view();
  animation-range: entry 0% cover 34%;
}

.community-card {
  display: grid;
  gap: 9px;
  min-width: 0;
  padding: 10px 10px 16px;
  border: 1px solid rgba(214, 181, 109, 0.14);
  border-radius: 8px;
  background:
    linear-gradient(145deg, rgba(214, 181, 109, 0.08), transparent 58%),
    rgba(255, 255, 255, 0.045);
  color: #fff8e6;
  cursor: pointer;
  transition:
    transform 0.18s ease,
    border-color 0.18s ease,
    background 0.18s ease;
}

.community-card:hover,
.community-card:focus-visible {
  border-color: rgba(214, 181, 109, 0.36);
  background: rgba(214, 181, 109, 0.075);
  transform: translateY(-3px);
}

.community-card:focus-visible {
  outline: 2px solid rgba(229, 200, 137, 0.62);
  outline-offset: 2px;
}

.community-card__cover {
  position: relative;
  display: grid;
  place-items: center;
  overflow: hidden;
  aspect-ratio: 16 / 9;
  border-radius: 6px;
  background:
    radial-gradient(circle at 50% 38%, rgba(214, 181, 109, 0.18), transparent 42%),
    #17130d;
  color: rgba(255, 248, 230, 0.56);
  font-size: 13px;
  font-weight: 900;
}

.community-card__cover img {
  width: 100%;
  height: 100%;
  object-fit: cover;
}

.community-card__meta {
  padding: 0 4px;
  color: rgba(214, 181, 109, 0.78);
  font-size: 12px;
  font-weight: 900;
}

.community-card strong {
  padding: 0 4px;
  overflow: hidden;
  font-size: 17px;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.community-card p {
  display: -webkit-box;
  min-height: 42px;
  margin: 0;
  padding: 0 4px;
  overflow: hidden;
  color: rgba(249, 241, 220, 0.58);
  font-size: 13px;
  line-height: 1.6;
  -webkit-box-orient: vertical;
  -webkit-line-clamp: 2;
}

.community-card__actions {
  display: flex;
  gap: 8px;
  padding: 2px 4px 0;
}

.community-card button {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 6px;
  min-height: 36px;
  padding: 0 12px;
  border: 1px solid rgba(255, 241, 199, 0.18);
  border-radius: 8px;
  background: rgba(255, 255, 255, 0.055);
  color: #fff1c7;
  font-size: 12px;
  font-weight: 900;
}

.community-card__actions button:last-child,
.guest-community-band .community-card button {
  border-color: rgba(255, 221, 151, 0.42);
  background: linear-gradient(180deg, #d6b56d, #9f722c);
  color: #160f06;
}

.community-card button:disabled {
  cursor: wait;
  opacity: 0.58;
}

.community-card--empty {
  cursor: default;
}

.spin {
  animation: spin 0.8s linear infinite;
}

.open-ecosystem-grid {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 16px;
}

.ecosystem-agent-layout {
  display: grid;
  grid-template-columns: minmax(0, 0.82fr) minmax(0, 1.18fr);
  gap: 16px;
  align-items: stretch;
}

.open-ecosystem-grid--compact {
  grid-template-columns: 1fr;
}

.open-ecosystem-grid--compact .open-ecosystem-card {
  grid-template-columns: 132px minmax(0, 1fr);
  min-height: 0;
  align-items: center;
  gap: 12px;
  padding: 10px;
}

.open-ecosystem-grid--compact .open-ecosystem-card__visual {
  grid-row: span 3;
  aspect-ratio: 4 / 3;
}

.open-ecosystem-grid--compact .open-ecosystem-card__icon {
  display: none;
}

.open-ecosystem-grid--compact .open-ecosystem-card strong,
.open-ecosystem-grid--compact .open-ecosystem-card p {
  padding: 0;
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

.agent-panel--compact {
  grid-template-columns: minmax(0, 1.05fr) minmax(260px, 0.82fr);
}

.agent-panel--compact .agent-primary {
  min-height: 312px;
}

.agent-panel--compact .agent-primary h3 {
  font-size: clamp(24px, 2.4vw, 36px);
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
    filter: blur(10px);
  }

  to {
    opacity: 1;
    filter: blur(0);
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

@keyframes creator-headline-rise {
  from {
    opacity: 0;
    transform: translateY(18px);
    filter: blur(8px);
  }

  to {
    opacity: 1;
    transform: translateY(0);
    filter: blur(0);
  }
}

@keyframes sluvoPrism {
  0%,
  100% {
    background-position: 8% 50%;
    opacity: 0.48;
  }

  42% {
    background-position: 92% 50%;
    opacity: 0.72;
  }

  68% {
    background-position: 64% 50%;
    opacity: 0.56;
  }
}

@keyframes sluvoSheen {
  0%,
  44% {
    background-position: 168% 50%;
    opacity: 0;
  }

  55% {
    opacity: 0.62;
  }

  84%,
  100% {
    background-position: -70% 50%;
    opacity: 0;
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

@keyframes previewCardJolt {
  0% {
    transform: translate3d(var(--node-hover-x, 0), var(--node-hover-y, 0), 0) rotate(var(--node-hover-rotate, 0deg)) scale(1.06);
  }

  22% {
    transform: translate3d(var(--node-hover-x, 0), var(--node-hover-y, 0), 0) rotate(calc(var(--node-hover-rotate, 0deg) + 0.55deg)) scale(var(--node-jolt-scale));
  }

  44% {
    transform: translate3d(var(--node-hover-x, 0), var(--node-hover-y, 0), 0) rotate(calc(var(--node-hover-rotate, 0deg) - 0.4deg)) scale(var(--node-dip-scale));
  }

  72% {
    transform: translate3d(var(--node-hover-x, 0), var(--node-hover-y, 0), 0) rotate(calc(var(--node-hover-rotate, 0deg) + 0.18deg)) scale(var(--node-snap-scale));
  }

  100% {
    transform: translate3d(var(--node-hover-x, 0), var(--node-hover-y, 0), 0) rotate(var(--node-hover-rotate, 0deg)) scale(var(--node-hover-scale));
  }
}

@keyframes previewCardFlipJolt {
  0% {
    filter: brightness(1);
    transform: translate3d(var(--node-hover-x, 0), var(--node-hover-y, 0), var(--node-depth)) rotateX(var(--node-tilt-x, 0deg)) rotateY(var(--node-tilt-y, 0deg)) rotate(var(--node-rotate, 0deg)) scale(1.02);
  }

  18% {
    filter: brightness(1.08);
    transform: translate3d(var(--node-hover-x, 0), var(--node-hover-y, 0), calc(var(--node-depth) + 52px)) rotateX(calc(var(--node-hover-tilt-x, 0deg) + 5deg)) rotateY(calc(var(--node-hover-tilt-y, 0deg) - 8deg)) rotate(calc(var(--node-hover-rotate, 0deg) + 0.8deg)) scale(var(--node-jolt-scale));
  }

  36% {
    transform: translate3d(var(--node-hover-x, 0), var(--node-hover-y, 0), calc(var(--node-depth) + 26px)) rotateX(calc(var(--node-hover-tilt-x, 0deg) - 3deg)) rotateY(calc(var(--node-hover-tilt-y, 0deg) + 5deg)) rotate(calc(var(--node-hover-rotate, 0deg) - 0.6deg)) scale(var(--node-dip-scale));
  }

  62% {
    filter: brightness(1.04);
    transform: translate3d(var(--node-hover-x, 0), var(--node-hover-y, 0), calc(var(--node-depth) + 48px)) rotateX(calc(var(--node-hover-tilt-x, 0deg) + 1.2deg)) rotateY(calc(var(--node-hover-tilt-y, 0deg) - 1.8deg)) rotate(calc(var(--node-hover-rotate, 0deg) + 0.25deg)) scale(var(--node-snap-scale));
  }

  100% {
    filter: brightness(1);
    transform: translate3d(var(--node-hover-x, 0), var(--node-hover-y, 0), calc(var(--node-depth) + 42px)) rotateX(var(--node-hover-tilt-x, 0deg)) rotateY(var(--node-hover-tilt-y, 0deg)) rotate(var(--node-hover-rotate, 0deg)) scale(var(--node-hover-scale));
  }
}

@keyframes previewVideoRise {
  0% {
    opacity: 0;
    clip-path: inset(72% 0 0 0 round 18px);
    transform: translateY(22px) scale(0.98);
  }

  54% {
    opacity: 1;
    clip-path: inset(0 0 0 0 round 18px);
    transform: translateY(-4px) scale(1);
  }

  100% {
    opacity: 1;
    clip-path: inset(0 0 0 0 round 18px);
    transform: translateY(0) scale(1);
  }
}

@keyframes previewScan {
  0% {
    opacity: 0;
    transform: translateX(0) skewX(-12deg);
  }

  18% {
    opacity: 0.7;
  }

  76% {
    opacity: 0.54;
  }

  100% {
    opacity: 0;
    transform: translateX(380%) skewX(-12deg);
  }
}

@keyframes previewSignal {
  0%,
  100% {
    opacity: 0.38;
    transform: scaleX(0.34);
  }

  50% {
    opacity: 0.88;
    transform: scaleX(0.92);
  }
}

@keyframes previewBar {
  0%,
  100% {
    height: 28%;
    opacity: 0.58;
  }

  35% {
    height: 96%;
    opacity: 0.96;
  }

  68% {
    height: 48%;
    opacity: 0.78;
  }
}

@keyframes previewProgress {
  from {
    transform: scaleX(0);
  }

  to {
    transform: scaleX(1);
  }
}

@keyframes detailCardSheen {
  0%,
  42% {
    opacity: 0.34;
    transform: translateX(-28%);
  }

  58% {
    opacity: 0.82;
  }

  100% {
    opacity: 0.34;
    transform: translateX(28%);
  }
}

@keyframes detailTargetPulse {
  0% {
    filter: brightness(1);
    transform: scale(1);
  }

  38% {
    filter: brightness(1.12);
    transform: scale(1.012);
  }

  100% {
    filter: brightness(1);
    transform: scale(1);
  }
}

@keyframes agentAurora {
  0%,
  100% {
    opacity: 0.46;
    transform: rotate(-10deg) scaleX(0.92);
  }

  50% {
    opacity: 0.9;
    transform: rotate(-4deg) scaleX(1.08);
  }
}

@keyframes agentCorePulse {
  0%,
  100% {
    opacity: 0.56;
    transform: translate(-50%, -50%) scale(0.96);
  }

  50% {
    opacity: 1;
    transform: translate(-50%, -50%) scale(1.04);
  }
}

@keyframes agentOrbitTurn {
  from {
    transform: translate(-50%, -50%) rotate(0deg);
  }

  to {
    transform: translate(-50%, -50%) rotate(360deg);
  }
}

@keyframes agentCardSweep {
  0%,
  44% {
    opacity: 0;
    transform: translateX(-42%);
  }

  58% {
    opacity: 0.82;
  }

  100% {
    opacity: 0;
    transform: translateX(42%);
  }
}

@keyframes agentNodePulse {
  0%,
  100% {
    opacity: 0.5;
    transform: scale(0.82);
  }

  50% {
    opacity: 1;
    transform: scale(1.18);
  }
}

@keyframes agentPipelineFlow {
  from {
    transform: translateX(-110%);
  }

  to {
    transform: translateX(110%);
  }
}

@keyframes navOptionFlow {
  from {
    transform: translateX(-90%);
  }

  to {
    transform: translateX(90%);
  }
}

@keyframes capabilityMarquee {
  from {
    transform: translate3d(0, 0, 0);
  }

  to {
    transform: translate3d(calc(-50% - 8px), 0, 0);
  }
}

@keyframes modelStageSweep {
  0%,
  42% {
    opacity: 0;
    transform: translateX(-82%);
  }

  55% {
    opacity: 0.75;
  }

  82%,
  100% {
    opacity: 0;
    transform: translateX(82%);
  }
}

@keyframes modelRailFlow {
  from {
    transform: translate3d(0, 0, 0);
  }

  to {
    transform: translate3d(calc(-50% - 5px), 0, 0);
  }
}

@keyframes modelChipSheen {
  0%,
  48% {
    opacity: 0;
    transform: translateX(-72%);
  }

  62% {
    opacity: 1;
  }

  92%,
  100% {
    opacity: 0;
    transform: translateX(72%);
  }
}

@keyframes capabilitySheen {
  0%,
  48% {
    opacity: 0;
    transform: translateX(-48%);
  }

  62% {
    opacity: 1;
  }

  88%,
  100% {
    opacity: 0;
    transform: translateX(48%);
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

@keyframes community-rise {
  from {
    opacity: 0;
    transform: translateY(72px) scale(0.96);
  }

  to {
    opacity: 1;
    transform: translateY(0) scale(1);
  }
}

@keyframes spin {
  to {
    transform: rotate(360deg);
  }
}

@media (max-width: 1180px) {
  .guest-hero {
    grid-template-columns: 1fr;
  }

  .guest-hero__headline {
    font-size: 74px;
  }

  .guest-hero__headline-brand {
    font-size: 118px;
  }

  .guest-hero__headline-final {
    gap: 12px;
  }

  .guest-stage {
    min-height: 540px;
  }

  .guest-stage__watermark {
    font-size: 132px;
  }

  .home-nav__actions {
    flex-wrap: wrap;
    justify-content: flex-end;
  }

  .home-nav {
    grid-template-columns: minmax(150px, 0.8fr) auto minmax(290px, 1fr);
    gap: 14px;
  }

  .home-nav__center button {
    padding-inline: 12px;
  }

  .preview-node {
    --node-hover-scale: 1.09;
    --node-jolt-scale: 1.12;
    --node-dip-scale: 1.07;
    --node-snap-scale: 1.1;
    width: 340px;
    min-height: 190px;
    padding: 22px;
  }

  .preview-node:hover,
  .preview-node:focus-visible {
    min-height: 340px;
    transform: translate3d(var(--node-hover-x, 0), var(--node-hover-y, 0), calc(var(--node-depth) + 28px)) rotateX(var(--node-hover-tilt-x, 0deg)) rotateY(var(--node-hover-tilt-y, 0deg)) rotate(var(--node-hover-rotate, 0deg)) scale(var(--node-hover-scale));
  }

  .preview-node--has-video:hover,
  .preview-node--has-video:focus-visible {
    width: min(430px, 82vw);
    min-height: 390px;
  }

  .preview-node--has-video:hover .preview-node__media,
  .preview-node--has-video:focus-visible .preview-node__media {
    inset: 16px;
    max-height: none;
  }

  .preview-node--has-video:hover .preview-node__screen,
  .preview-node--has-video:focus-visible .preview-node__screen {
    min-height: 0;
  }

  .workflow-detail-grid {
    grid-template-columns: 1fr;
  }

  .problem-grid {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }

  .workflow-detail-grid::before {
    left: 32px;
  }

  .workflow-detail-card {
    min-height: 0;
  }

  .project-agent-stage {
    grid-template-columns: 1fr;
  }

  .project-agent-hero {
    min-height: 420px;
  }

  .project-agent-orbit {
    top: 30%;
    left: 50%;
  }

  .project-agent-pipeline {
    grid-template-columns: repeat(3, minmax(0, 1fr));
  }

  .model-showcase {
    width: min(980px, calc(100vw - 48px));
  }

  .model-showcase__stage {
    min-height: 280px;
  }

  .creator-console,
  .home-section,
  .showcase-section,
  .creation-start,
  .ecosystem-agent-section {
    width: min(820px, calc(100vw - 116px));
  }

  .creation-start,
  .ecosystem-agent-layout {
    grid-template-columns: 1fr;
  }

  .platform-highlights {
    position: static;
    grid-template-columns: repeat(3, minmax(0, 1fr));
  }

  .platform-highlights__heading {
    grid-column: 1 / -1;
  }

  .agent-panel--compact {
    grid-template-columns: 1fr;
  }

  .creator-stage {
    min-height: 540px;
  }

  .creator-console h1 {
    font-size: 44px;
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
    display: flex;
    align-items: stretch;
    flex-direction: column;
  }

  .home-guest-shell {
    padding-top: 178px;
  }

  .home-brand {
    align-self: flex-start;
  }

  .home-nav__center,
  .home-nav__actions {
    width: 100%;
  }

  .home-nav__center {
    justify-content: stretch;
  }

  .home-nav__center button {
    flex: 1 1 0;
    padding-inline: 10px;
  }

  .guest-hero {
    gap: 38px;
  }

  .guest-hero__headline {
    font-size: 58px;
  }

  .guest-hero__headline-brand {
    font-size: 92px;
  }

  .guest-hero__sublead {
    font-size: 15px;
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

  .community-grid,
  .open-ecosystem-grid,
  .project-grid,
  .agent-panel {
    grid-template-columns: 1fr;
  }

  .capability-band {
    padding-inline: 16px;
    mask-image: linear-gradient(90deg, transparent 0, #000 4%, #000 96%, transparent 100%);
  }

  .workflow-detail-section {
    padding-inline: 16px;
  }

  .problem-section {
    padding-inline: 16px;
  }

  .problem-section__intro {
    text-align: left;
  }

  .problem-section__intro span,
  .section-kicker {
    justify-self: start;
  }

  .workflow-detail-section__intro {
    text-align: left;
  }

  .workflow-detail-section__intro span {
    justify-self: start;
  }

  .workflow-detail-card {
    grid-template-columns: 1fr;
    gap: 18px;
    padding: 22px;
    border-radius: 20px;
  }

  .workflow-detail-card__index {
    width: 52px;
    height: 52px;
    border-radius: 15px;
  }

  .problem-grid {
    grid-template-columns: 1fr;
  }

  .project-agent-showcase {
    padding-inline: 16px;
  }

  .project-agent-showcase__intro {
    text-align: left;
  }

  .project-agent-showcase__intro span {
    justify-self: start;
  }

  .project-agent-stage {
    padding: 18px;
    border-radius: 24px;
  }

  .project-agent-grid {
    grid-template-columns: 1fr;
  }

  .project-agent-hero__metrics {
    grid-template-columns: 1fr;
  }

  .capability-card {
    flex-basis: min(360px, 82vw);
  }

  .model-showcase {
    width: calc(100vw - 32px);
    margin-top: -34px;
    margin-bottom: 66px;
  }

  .model-showcase__heading {
    justify-items: start;
    text-align: left;
  }

  .model-showcase__heading h2 {
    font-size: 34px;
  }

  .model-showcase__stage {
    min-height: 0;
    padding: 22px 0;
    border-radius: 22px;
  }

  .model-stream__track {
    gap: 10px;
  }

  .home-workbench {
    padding-top: 64px;
    padding-left: 0;
  }

  .workbench-rail {
    position: fixed;
    top: 0;
    left: 0;
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

  .campaign-bar span {
    align-items: flex-start;
  }

  .creator-console,
  .home-section,
  .showcase-section,
  .creation-start,
  .ecosystem-agent-section {
    width: calc(100vw - 32px);
  }

  .project-grid--focused,
  .platform-highlights,
  .open-ecosystem-grid--compact .open-ecosystem-card {
    grid-template-columns: 1fr;
  }

  .project-card--create-primary {
    grid-row: auto;
  }

  .project-card--create-primary .project-card__preview--empty {
    min-height: 150px;
  }

  .project-strip {
    grid-auto-columns: minmax(220px, 78vw);
  }

  .open-ecosystem-grid--compact .open-ecosystem-card__visual {
    grid-row: auto;
    aspect-ratio: 16 / 9;
  }

  .creator-stage {
    min-height: 520px;
  }

  .creator-console h1 {
    font-size: 32px;
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

  .community-space {
    width: calc(100vw - 32px);
    min-height: 760px;
    padding: 56px 16px 80px;
  }

  .community-grid--space {
    grid-template-columns: 1fr;
    grid-auto-rows: auto;
    min-height: 0;
  }

  .community-card--space {
    grid-column: auto !important;
    grid-row: auto;
    margin-top: 0 !important;
  }
}

@media (max-width: 560px) {
  .home-nav__link {
    display: none;
  }

  .home-nav__center {
    display: grid;
    grid-template-columns: 1fr;
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

  .guest-hero__headline {
    font-size: 42px;
    line-height: 1.02;
  }

  .guest-hero__headline-brand {
    margin-bottom: 12px;
    font-size: 62px;
  }

  .guest-hero__headline-pair {
    gap: 14px;
    padding-bottom: 9px;
  }

  .guest-hero__headline-pair::after {
    right: 6%;
    height: 3px;
  }

  .guest-hero__headline-final strong {
    padding: 0 10px 5px;
    border-radius: 12px;
  }

  .guest-stage {
    min-height: 420px;
    border-radius: 20px;
  }

  .guest-stage__watermark {
    font-size: 76px;
    opacity: 0.34;
  }

  .guest-stage__device {
    inset: 12% -14% 18%;
    transform: rotateX(58deg) rotateZ(-8deg) translateY(42px) scale(0.86);
  }

  .preview-node {
    --node-hover-scale: 1.04;
    --node-jolt-scale: 1.065;
    --node-dip-scale: 1.025;
    --node-snap-scale: 1.05;
    width: min(78%, 300px);
    min-height: 150px;
    padding: 16px;
    border-radius: 14px;
  }

  .preview-node:hover,
  .preview-node:focus-visible {
    min-height: 276px;
    transform: translate3d(var(--node-hover-x, 0), var(--node-hover-y, 0), calc(var(--node-depth) + 18px)) rotateX(var(--node-hover-tilt-x, 0deg)) rotateY(var(--node-hover-tilt-y, 0deg)) rotate(var(--node-hover-rotate, 0deg)) scale(var(--node-hover-scale));
  }

  .preview-node--has-video:hover,
  .preview-node--has-video:focus-visible {
    width: min(88vw, 340px);
    min-height: 320px;
  }

  .preview-node strong {
    font-size: 20px;
  }

  .preview-node small {
    font-size: 12px;
  }

  .preview-node__screen {
    min-height: 70px;
    border-radius: 12px;
  }

  .preview-node:hover .preview-node__media,
  .preview-node:focus-visible .preview-node__media {
    max-height: 170px;
  }

  .preview-node:hover .preview-node__screen,
  .preview-node:focus-visible .preview-node__screen {
    min-height: 140px;
  }

  .preview-node--has-video:hover .preview-node__media,
  .preview-node--has-video:focus-visible .preview-node__media {
    inset: 14px;
    max-height: none;
  }

  .preview-node--has-video:hover .preview-node__screen,
  .preview-node--has-video:focus-visible .preview-node__screen {
    min-height: 0;
  }

  .workflow-detail-section {
    padding-bottom: 62px;
  }

  .problem-section {
    padding-bottom: 62px;
  }

  .problem-section__intro h2 {
    font-size: 30px;
  }

  .problem-section__intro p,
  .problem-card p {
    font-size: 13px;
  }

  .problem-card {
    min-height: 0;
    padding: 20px;
  }

  .workflow-detail-section__intro h2 {
    font-size: 30px;
  }

  .workflow-detail-section__intro p,
  .workflow-detail-card__content p,
  .workflow-detail-card__content li {
    font-size: 13px;
  }

  .workflow-detail-grid::before {
    display: none;
  }

  .project-agent-showcase {
    padding-bottom: 64px;
  }

  .project-agent-showcase__intro h2 {
    font-size: 30px;
  }

  .project-agent-showcase__intro p,
  .project-agent-hero p,
  .project-agent-card p {
    font-size: 13px;
  }

  .project-agent-hero {
    min-height: 0;
    padding: 22px;
  }

  .project-agent-hero__metrics {
    gap: 8px;
  }

  .project-agent-orbit {
    width: 220px;
    height: 220px;
    opacity: 0.42;
  }

  .project-agent-pipeline {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }

  .model-showcase__heading h2 {
    font-size: 30px;
  }

  .model-showcase__heading p {
    font-size: 13px;
  }

  .model-chip {
    min-width: 148px;
    min-height: 56px;
    padding: 10px 14px 10px 10px;
    font-size: 12px;
  }

  .model-chip__icon {
    width: 32px;
    height: 32px;
    border-radius: 10px;
  }

  .preview-node--script {
    top: 7%;
    left: 6%;
    width: min(82%, 320px);
  }

  .preview-node--asset {
    top: 18%;
    right: 5%;
    width: min(78%, 300px);
  }

  .preview-node--shot {
    right: 7%;
    bottom: 7%;
    width: min(74%, 288px);
  }

  .preview-node--video {
    bottom: 18%;
    left: 5%;
    width: min(76%, 292px);
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

  .creator-console h1 {
    font-size: 22px;
  }

  .project-strip {
    grid-auto-columns: minmax(210px, 84vw);
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
