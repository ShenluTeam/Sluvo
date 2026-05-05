<template>
  <div class="libtv-canvas-shell" :class="{ 'is-space-panning': spacePanning, 'is-agent-expanded': agentPanel.visible }" @click="closeFloatingPanels" @contextmenu.capture="handleCanvasContextMenu">
    <section
      ref="canvasFrame"
      class="libtv-canvas-frame"
      tabindex="-1"
      @keydown.capture="handleCanvasKeyEvent"
      @keyup.capture="handleCanvasKeyEvent"
      @pointerdown.capture="handleFramePointerDown"
      @wheel.capture="handleCanvasWheel"
      @dragenter.prevent
      @dragover.prevent="handleCanvasDragOver"
      @drop.prevent="handleCanvasFileDrop"
      @dblclick="handleCanvasDoubleClick"
    >
      <VueFlow
        v-model:nodes="nodes"
        v-model:edges="edges"
        class="sluvo-flow"
        :node-types="nodeTypes"
        :edge-types="edgeTypes"
        :default-edge-options="defaultEdgeOptions"
        :snap-to-grid="snapEnabled"
        :snap-grid="[20, 20]"
        :delete-key-code="null"
        :selection-key-code="['Shift']"
        :multi-selection-key-code="['Shift']"
        :min-zoom="0.22"
        :max-zoom="2"
        :pan-on-drag="[1]"
        :zoom-on-scroll="false"
        :zoom-on-pinch="true"
        :zoom-on-double-click="false"
        :selection-on-drag="true"
        :elevate-nodes-on-select="true"
        :auto-pan-on-node-drag="true"
        :auto-pan-speed="18"
        @connect="handleConnect"
        @connect-start="handleConnectStart"
        @connect-end="handleConnectEnd"
        @node-drag-start="rememberHistory"
        @nodes-change="handleNodesChange"
        @edges-change="handleEdgesChange"
        @pane-click="handlePaneClick"
        @pane-context-menu="handlePaneContextMenu"
        @node-context-menu="handleNodeContextMenu"
        @node-double-click="handleNodeDoubleClick"
        @move-end="handleMoveEnd"
      >
        <Background
          v-if="gridVisible"
          pattern-color="rgba(201, 168, 91, 0.24)"
          :gap="22"
          :size="1.2"
        />
      </VueFlow>

      <div class="direct-node-layer" :style="directLayerStyle">
        <svg class="direct-edge-layer">
          <defs>
            <filter id="direct-edge-glow" x="-40%" y="-40%" width="180%" height="180%">
              <feGaussianBlur stdDeviation="3.5" result="blur" />
              <feMerge>
                <feMergeNode in="blur" />
                <feMergeNode in="SourceGraphic" />
              </feMerge>
            </filter>
          </defs>
          <g v-for="edge in directEdges" :key="edge.id" class="direct-edge">
            <path class="direct-edge__base" :d="getDirectEdgePath(edge)" pathLength="1" />
            <path class="direct-edge__glow" :d="getDirectEdgePath(edge)" pathLength="1" />
          </g>
          <path
            v-if="directConnection.active"
            class="direct-edge__draft"
            :d="getDraftEdgePath()"
            pathLength="1"
          />
          <path
            v-if="(referenceMenu.visible || addMenu.visible) && pendingDirectConnection.sourceId"
            class="direct-edge__draft"
            :d="getPendingDirectEdgePath()"
            pathLength="1"
          />
        </svg>

        <section
          v-for="group in directNodeGroups"
          :key="group.id"
          class="direct-group-frame"
          :class="{ 'is-selected': group.id === selectedDirectGroupId }"
          :style="getDirectGroupFrameStyle(group)"
          @click.stop
          @pointerdown.stop="handleDirectGroupPointerDown($event, group.id)"
        >
          <div class="direct-group-frame__label">{{ group.title }}</div>
          <button
            class="direct-group-frame__port direct-group-frame__port--left magnetic-target"
            type="button"
            title="向左添加节点"
            @click.stop
            @pointerdown.stop.prevent="startDirectGroupConnection($event, group, 'left')"
            @mousedown.stop.prevent="startDirectGroupConnection($event, group, 'left')"
          >
            <Plus :size="22" :stroke-width="2.4" />
          </button>
          <button
            class="direct-group-frame__port direct-group-frame__port--right magnetic-target"
            type="button"
            title="向右添加节点"
            @click.stop
            @pointerdown.stop.prevent="startDirectGroupConnection($event, group, 'right')"
            @mousedown.stop.prevent="startDirectGroupConnection($event, group, 'right')"
          >
            <Plus :size="22" :stroke-width="2.4" />
          </button>
        </section>

        <article
          v-for="(node, index) in directNodes"
          :key="node.id"
          :ref="(element) => registerDirectNodeElement(node.id, element)"
          class="direct-workflow-node"
          :class="[`direct-workflow-node--${node.type}`, { 'is-selected': selectedDirectNodeIds.includes(node.id), 'has-open-video-settings': activeVideoSettingsNodeId === node.id }]"
          :style="{ left: `${node.x}px`, top: `${node.y}px`, zIndex: getDirectNodeZIndex(node, index) }"
          :data-direct-node-id="node.id"
          draggable="false"
          tabindex="0"
          @click.stop
          @dragstart.prevent
          @selectstart="handleDirectNodeSelectStart"
          @keydown.delete.stop.prevent="deleteDirectNode(node.id)"
          @keydown.backspace.stop.prevent="deleteDirectNode(node.id)"
          @keyup.delete.stop.prevent="deleteDirectNode(node.id)"
          @keyup.backspace.stop.prevent="deleteDirectNode(node.id)"
          @pointerdown.stop="handleDirectNodePointerDown($event, node.id)"
        >
          <div class="direct-workflow-node__title" :class="{ 'direct-workflow-node__title--uploaded': node.type === 'uploaded_asset' }">
            <span>{{ node.icon }}</span>
            <span class="direct-workflow-node__title-text">{{ node.title }}</span>
            <span v-if="node.type === 'uploaded_asset'" class="direct-workflow-node__dimensions">
              {{ getUploadedAssetDimensions(node) }}
            </span>
          </div>

          <div class="direct-workflow-node__frame" :class="{ 'direct-workflow-node__frame--uploaded': node.type === 'uploaded_asset' }">
            <button
              class="direct-workflow-node__port direct-workflow-node__port--left magnetic-target"
              type="button"
              draggable="false"
              @pointerdown.stop.prevent="startDirectConnection($event, node.id, 'left')"
              @mousedown.stop.prevent="startDirectConnection($event, node.id, 'left')"
            >
              <Plus class="direct-workflow-node__port-icon" :size="18" :stroke-width="2.4" />
            </button>
            <button
              class="direct-workflow-node__port direct-workflow-node__port--right magnetic-target"
              type="button"
              draggable="false"
              @pointerdown.stop.prevent="startDirectConnection($event, node.id, 'right')"
              @mousedown.stop.prevent="startDirectConnection($event, node.id, 'right')"
            >
              <Plus class="direct-workflow-node__port-icon" :size="18" :stroke-width="2.4" />
            </button>

            <button
              v-if="node.type === 'uploaded_asset'"
              class="uploaded-asset__replace"
              type="button"
              title="重新上传"
              @pointerdown.stop
              @click.stop="replaceUploadedNode(node.id)"
            >
              <Upload :size="17" />
            </button>

            <div v-if="node.type === 'uploaded_asset'" class="uploaded-asset">
              <div v-if="node.media?.kind === 'image' && getUploadedImageSrc(node)" class="uploaded-asset__preview">
                <img :src="getUploadedImageSrc(node)" :alt="node.media.name" draggable="false" @error="handleUploadedImageError(node.id)" />
              </div>
              <div v-else-if="node.media?.kind === 'video' && node.media?.url" class="uploaded-asset__preview">
                <video :src="node.media.url" controls />
              </div>
              <div v-else-if="node.media?.kind === 'audio' && node.media?.url" class="uploaded-asset__audio">
                <Music2 :size="42" />
                <strong>{{ node.media.name }}</strong>
                <audio :src="node.media.url" controls />
              </div>
              <div v-else-if="node.upload?.status === 'error'" class="uploaded-asset__state uploaded-asset__state--error">
                <strong>{{ node.upload.message || '上传失败' }}</strong>
                <button type="button" @click.stop="retryUploadedNode(node.id)">重试</button>
              </div>
              <div v-else-if="node.upload?.status === 'uploading'" class="uploaded-asset__state">
                <span>上传中 {{ node.upload.progress }}%</span>
                <div class="uploaded-asset__progress">
                  <span :style="{ width: `${node.upload.progress}%` }" />
                </div>
              </div>
              <div v-else class="uploaded-asset__state">上传成功</div>
              <div v-if="node.upload?.status === 'uploading' && node.media?.url" class="uploaded-asset__overlay">
                <span>上传中 {{ node.upload.progress }}%</span>
                <div class="uploaded-asset__progress">
                  <span :style="{ width: `${node.upload.progress}%` }" />
                </div>
              </div>
              <div v-if="node.upload?.status === 'error' && node.media?.url" class="uploaded-asset__overlay uploaded-asset__overlay--error">
                <strong>{{ node.upload.message || '上传失败' }}</strong>
                <button type="button" @click.stop="retryUploadedNode(node.id)">重试</button>
              </div>
            </div>

            <div
              v-else-if="node.type === 'image_unit' && node.generationStatus === 'running'"
              class="generated-image__state"
            >
              <span class="generated-image__spinner" />
              <strong>生成中...</strong>
            </div>

            <div
              v-else-if="node.type === 'image_unit' && node.generatedImage?.url"
              class="generated-image__preview"
            >
              <img
                :src="getGeneratedImageSrc(node)"
                :alt="node.generatedImage.prompt || node.title"
                draggable="false"
                @error="handleGeneratedImageError(node.id)"
              />
              <div v-if="!node.generatedVideo?.isPlayable || node.generatedVideo?.loadError" class="generated-video__status">
                <span v-if="node.generatedVideo?.loadError">{{ node.generatedVideo?.loadErrorMessage || '视频地址暂时无法播放' }}</span>
                <span v-else>正在加载视频...</span>
                <button v-if="getGeneratedVideoSrc(node)" type="button" @click.stop="openGeneratedVideo(node)">打开原视频</button>
              </div>
              <div class="generated-image__actions" @click.stop @pointerdown.stop @contextmenu.prevent.stop>
                <button type="button" title="打开原视频" @click.stop="openGeneratedVideo(node)">
                  <Eye :size="16" />
                </button>
                <button type="button" title="预览图片" @click.stop="previewGeneratedImage(node)">
                  <Eye :size="16" />
                </button>
                <button type="button" title="下载图片" @click.stop="downloadGeneratedImage(node)">
                  <Download :size="16" />
                </button>
              </div>
            </div>

            <div
              v-else-if="node.type === 'video_unit' && node.generationStatus === 'running'"
              class="generated-image__state"
            >
              <span class="generated-image__spinner" />
              <strong>视频生成中...</strong>
              <small>{{ node.generationMessage || '正在同步任务结果' }}</small>
            </div>

            <div
              v-else-if="node.type === 'video_unit' && node.generatedVideo?.url"
              class="generated-video__preview"
            >
              <video
                :src="getGeneratedVideoSrc(node)"
                :poster="getGeneratedVideoPoster(node)"
                controls
                autoplay
                muted
                playsinline
                preload="metadata"
                @loadedmetadata="handleGeneratedVideoReady(node.id)"
                @canplay="handleGeneratedVideoReady(node.id)"
                @error="handleGeneratedVideoError(node.id, $event)"
              />
              <div class="generated-image__actions" @click.stop @pointerdown.stop @contextmenu.prevent.stop>
                <button type="button" title="下载视频" @click.stop="downloadGeneratedVideo(node)">
                  <Download :size="16" />
                </button>
              </div>
            </div>

            <div
              v-else-if="node.type === 'audio_unit' && node.generationStatus === 'running'"
              class="generated-image__state"
            >
              <span class="generated-image__spinner" />
              <strong>音频生成中...</strong>
              <small>{{ node.generationMessage || '正在同步配音结果' }}</small>
            </div>

            <div
              v-else-if="node.type === 'audio_unit' && node.generatedAudio?.url"
              class="generated-audio__preview"
            >
              <div class="generated-audio__wave" aria-hidden="true">
                <span v-for="index in 34" :key="index" :style="{ '--bar': ((index * 17) % 34) + 24 }" />
              </div>
              <div class="generated-audio__meta">
                <Music2 :size="36" />
                <div>
                  <strong>{{ node.generatedAudio.title || '音频结果' }}</strong>
                  <span>{{ getAudioModelLabel(node) }} · {{ getAudioCharacterLabel(node) }}</span>
                </div>
              </div>
              <audio :src="getGeneratedAudioSrc(node)" controls />
              <div class="generated-image__actions" @click.stop @pointerdown.stop @contextmenu.prevent.stop>
                <button type="button" title="下载音频" @click.stop="downloadGeneratedAudio(node)">
                  <Download :size="16" />
                </button>
              </div>
            </div>

            <template v-else>
              <div
                v-if="node.type === 'prompt_note' && node.prompt.trim()"
                class="direct-workflow-node__markdown"
                tabindex="0"
                v-html="renderDirectMarkdown(node.prompt)"
                @keydown="handleMarkdownKeydown"
              />
              <template v-else>
                <div class="direct-workflow-node__hero">
                  <span v-if="node.type === 'prompt_note'" class="direct-workflow-node__lines" />
                  <span v-else class="direct-workflow-node__icon">{{ node.icon }}</span>
                </div>

                <p>尝试:</p>
                <button v-for="action in node.actions" :key="action" type="button">{{ action }}</button>
              </template>
            </template>
          </div>

          <div
            v-if="node.type !== 'uploaded_asset' && isSingleSelectedDirectNode(node.id)"
            class="direct-workflow-node__fixed-panel"
            >
              <div
                v-if="shouldShowReferenceStrip(node)"
                class="direct-workflow-node__references"
                @click.stop
              @dblclick.stop
              @keydown.stop
              @keyup.stop
              @pointerdown.stop
              @mousedown.stop
              @dragover.prevent.stop
              >
                <div v-if="isStartEndVideoNode(node)" class="direct-workflow-node__start-end-frames">
                  <div
                    v-for="slot in startEndFrameSlots"
                    :key="slot.id"
                    class="direct-workflow-node__start-end-frame"
                    :class="{ 'has-media': Boolean(getStartEndFrameReference(node, slot.id)), 'is-uploading': getStartEndFrameReference(node, slot.id)?.status === 'uploading', 'is-error': getStartEndFrameReference(node, slot.id)?.status === 'error' }"
                    role="button"
                    tabindex="0"
                    :title="`上传${slot.label}`"
                    @click.stop="openReferenceUploadDialog(node.id, slot.id)"
                    @keydown.enter.stop.prevent="openReferenceUploadDialog(node.id, slot.id)"
                    @keydown.space.stop.prevent="openReferenceUploadDialog(node.id, slot.id)"
                  >
                    <img
                      v-if="getStartEndFrameReference(node, slot.id)"
                      :src="getStartEndFrameReference(node, slot.id).previewUrl || getStartEndFrameReference(node, slot.id).url"
                      :alt="slot.label"
                      draggable="false"
                    />
                    <div v-if="getStartEndFrameReference(node, slot.id)" class="direct-workflow-node__start-end-popout" aria-hidden="true">
                      <img
                        :src="getStartEndFrameReference(node, slot.id).previewUrl || getStartEndFrameReference(node, slot.id).url"
                        :alt="slot.label"
                        draggable="false"
                      />
                    </div>
                    <Plus v-else :size="18" />
                    <span>{{ slot.label }}</span>
                    <small v-if="getStartEndFrameReference(node, slot.id)?.status === 'uploading'">{{ getStartEndFrameReference(node, slot.id)?.progress || 0 }}%</small>
                    <button
                      v-if="getStartEndFrameReference(node, slot.id)?.source === 'manual'"
                      type="button"
                      title="移除参考图"
                      @click.stop="removeManualReferenceImage(node.id, getStartEndFrameReference(node, slot.id).id)"
                    >
                      <X :size="12" />
                    </button>
                  </div>
                </div>
                <template v-else>
                  <button
                    v-if="canUploadDirectReference(node)"
                    class="direct-workflow-node__reference-upload"
                    type="button"
                    :title="getReferenceUploadTitle(node)"
                    @click.stop="openReferenceUploadDialog(node.id)"
                  >
                    <Upload :size="17" />
                  </button>
                  <div
                    v-for="(reference, index) in getDirectVisualReferenceItems(node.id)"
                    :key="reference.id"
                    class="direct-workflow-node__reference-thumb"
                    :class="{ 'is-uploading': reference.status === 'uploading', 'is-error': reference.status === 'error' }"
                    :style="{ '--reference-aspect': getReferenceAspectRatio(reference) }"
                    draggable="true"
                    @click.stop="insertReferenceToken(node.id, index)"
                    @dragstart.stop="startReferenceDrag(node.id, reference.id)"
                    @dragover.prevent.stop
                    @drop.stop.prevent="dropReference(node.id, reference.id)"
                  >
                    <img
                      v-if="getReferenceKind(reference) === 'image'"
                      :src="reference.previewUrl || reference.url"
                      :alt="reference.name || `参考图 ${index + 1}`"
                      draggable="false"
                    />
                    <video
                      v-else-if="getReferenceKind(reference) === 'video'"
                      :src="reference.previewUrl || reference.url"
                      muted
                      playsinline
                      preload="metadata"
                      draggable="false"
                    />
                    <div v-else class="direct-workflow-node__reference-media">
                      <Music2 :size="18" />
                      <em>{{ getReferenceKindLabel(reference) }}</em>
                    </div>
                    <div class="direct-workflow-node__reference-popout" aria-hidden="true">
                      <img v-if="getReferenceKind(reference) === 'image'" :src="reference.previewUrl || reference.url" alt="" draggable="false" />
                      <video v-else-if="getReferenceKind(reference) === 'video'" :src="reference.previewUrl || reference.url" muted playsinline preload="metadata" />
                      <div v-else class="direct-workflow-node__reference-media direct-workflow-node__reference-media--popout">
                        <Music2 :size="26" />
                        <em>{{ getReferenceKindLabel(reference) }}</em>
                      </div>
                    </div>
                    <span>{{ index + 1 }}</span>
                    <button
                      v-if="reference.source === 'manual'"
                      type="button"
                      title="移除参考图"
                      @click.stop="removeManualReferenceImage(node.id, reference.id)"
                    >
                      <X :size="12" />
                    </button>
                    <small v-if="reference.status === 'uploading'">{{ reference.progress || 0 }}%</small>
                    <small v-else-if="reference.status === 'error'">失败</small>
                  </div>
                </template>
            </div>
            <div
              v-if="node.type !== 'prompt_note'"
              class="direct-workflow-node__prompt-field"
              @click.stop="focusDirectPromptEditor(node.id)"
              @pointerdown.stop="handlePromptFieldPointerDown(node.id, $event)"
              @mousedown.stop
              @selectstart.stop
            >
              <div
                :ref="(element) => registerDirectPromptEditor(node.id, element, node)"
                class="direct-workflow-node__prompt"
                :class="{ 'is-empty': isDirectPromptEditorEmpty(node) }"
                contenteditable="true"
                role="textbox"
                aria-multiline="true"
                aria-label="节点提示词"
                tabindex="0"
                spellcheck="false"
                @focus="startDirectTextEdit(node.id)"
                @input="handleDirectPromptInput(node.id, $event)"
                @paste.stop="handleDirectPromptPaste(node.id, $event)"
                @blur="finishDirectTextEdit"
                @pointerdown.stop
                @mousedown.stop
                @selectstart.stop
                @keydown="handleDirectPromptKeydown(node.id, $event)"
                @click.stop="saveDirectPromptSelection(node.id, $event)"
                @dblclick.stop
                @keyup.stop="saveDirectPromptSelection(node.id, $event)"
              ></div>
              <span
                v-if="isDirectPromptEditorEmpty(node)"
                class="direct-workflow-node__prompt-placeholder"
              >
                {{ getDirectNodeTextareaPlaceholder(node) }}
              </span>
            </div>
            <form
              v-else
              class="text-node-ai-composer"
              @submit.prevent="submitTextNodeAnalysis(node)"
              @click.stop
              @pointerdown.stop
              @mousedown.stop
              @keydown.stop
              @keyup.stop
            >
              <textarea
                v-model="textNodeComposer.input"
                rows="3"
                :placeholder="node.prompt.trim() ? '让模型分析、扩写、提取角色场景或继续拆分镜。' : getDirectNodeTextareaPlaceholder(node)"
              />
              <footer>
                <label>
                  <Bot :size="16" />
                  <select v-model="textNodeComposer.modelCode">
                    <option v-for="model in agentModelOptions" :key="model.id" :value="model.id">{{ model.label }}</option>
                  </select>
                </label>
                <button type="button" title="写入节点" :disabled="!textNodeComposer.input.trim()" @click.stop="writeTextComposerToNode(node)">
                  <ListChecks :size="16" />
                </button>
                <button type="submit" :disabled="textNodeComposer.busy || (!textNodeComposer.input.trim() && !node.prompt.trim())">
                  <ArrowUp :size="18" />
                </button>
              </footer>
              <p v-if="textNodeComposer.error" class="text-node-ai-composer__error">{{ textNodeComposer.error }}</p>
            </form>
            <div
              v-if="node.type === 'agent_node'"
              class="agent-node-runner"
              @click.stop
              @dblclick.stop
              @keydown.stop
              @keyup.stop
              @pointerdown.stop
              @mousedown.stop
            >
              <header>
                <div>
                  <strong>{{ node.agentName || getAgentProfileLabel(node.agentTemplateId || node.agentProfile) || '画布 Agent' }}</strong>
                  <span>{{ getAgentNodeContextSummary(node) }}</span>
                </div>
                <button type="button" @click.stop="syncAgentNodeFromPanel(node)">使用面板设置</button>
              </header>
              <label>
                Agent
                <select v-model="node.agentTemplateId" @change="applyAgentTemplateToNode(node)">
                  <option value="">自动派发</option>
                  <option v-for="agent in agentPanel.templates" :key="agent.id" :value="agent.id">{{ agent.name }}</option>
                </select>
              </label>
              <label>
                模型
                <select v-model="node.agentModelCode">
                  <option v-for="model in agentModelOptions" :key="model.id" :value="model.id">{{ model.label }}</option>
                </select>
              </label>
              <p v-if="node.agentRolePromptSummary">{{ node.agentRolePromptSummary }}</p>
              <small v-if="node.agentLastActionStatus">
                最近：{{ getAgentActionStatusLabel(node.agentLastActionStatus) }} · {{ node.agentLastProposal || node.agentLastMessage || '提案' }}
              </small>
              <button
                class="agent-node-runner__primary"
                type="button"
                :disabled="agentPanel.busy"
                @click.stop="runAgentNode(node)"
              >
                <Bot :size="16" />
                {{ agentPanel.busy && agentPanel.targetNodeId === node.id ? '运行中' : '运行 Agent' }}
              </button>
            </div>
            <div
              v-if="node.type === 'image_unit'"
              class="direct-workflow-node__generation-controls"
              @click.stop
              @dblclick.stop
              @keydown.stop
              @keyup.stop
              @pointerdown.stop
              @mousedown.stop
            >
              <label class="direct-workflow-node__select">
                <span>大模型</span>
                <select v-model="node.imageModelId" :disabled="node.generationStatus === 'running'" @change="syncImageNodeSettings(node)">
                  <option v-for="model in imageModelOptions" :key="model.id" :value="model.id">
                    {{ model.label }}
                  </option>
                </select>
              </label>
              <label v-if="hasImageField(node, 'resolution')" class="direct-workflow-node__select direct-workflow-node__select--resolution">
                <span>&#20998;&#36776;&#29575;</span>
                <select v-model="node.imageResolution" :disabled="node.generationStatus === 'running'">
                  <option v-for="resolution in getImageFieldOptions(node, 'resolution', imageResolutionOptions)" :key="resolution.id" :value="resolution.id">
                    {{ resolution.label }}
                  </option>
                </select>
              </label>
              <label v-if="hasImageField(node, 'quality')" class="direct-workflow-node__select direct-workflow-node__select--quality">
                <span>画质等级</span>
                <select v-model="node.imageQuality" :disabled="node.generationStatus === 'running'">
                  <option v-for="quality in getImageFieldOptions(node, 'quality', fallbackImageQualityOptions)" :key="quality.id" :value="quality.id">
                    {{ quality.label }}
                  </option>
                </select>
              </label>
              <label v-if="hasImageField(node, 'aspect_ratio')" class="direct-workflow-node__select direct-workflow-node__select--ratio">
                <span>画面比例</span>
                <select v-model="node.aspectRatio" :disabled="node.generationStatus === 'running'">
                  <option v-for="ratio in getImageFieldOptions(node, 'aspect_ratio', imageAspectRatioOptions)" :key="ratio.id || ratio" :value="ratio.id || ratio">
                    {{ ratio.label || ratio }}
                  </option>
                </select>
              </label>
              <button
                class="direct-workflow-node__generate"
                type="button"
                :disabled="node.generationStatus === 'running' || !node.prompt.trim() || hasPendingReferenceUploads(node.id)"
                @click.stop="runDirectImageNode(node)"
              >
                <span class="direct-workflow-node__generate-cost">
                  <Star :size="14" />
                  {{ getImageGenerationPointsButtonLabel(node) }}
                </span>
                <span>{{ node.generationStatus === 'running' ? '生成中' : '生成图片' }}</span>
              </button>
              <p v-if="node.generationStatus === 'error'" class="direct-workflow-node__generation-error">
                {{ node.generationMessage || '生成失败，请稍后重试' }}
              </p>
            </div>
            <div
              v-if="node.type === 'video_unit'"
              class="direct-workflow-node__generation-controls direct-workflow-node__generation-controls--video"
              @click.stop
              @dblclick.stop
              @keydown.stop
              @keyup.stop
              @pointerdown.stop
              @mousedown.stop
            >
              <div class="video-composer-bar">
                <label class="video-composer-select video-composer-select--model">
                  <span>模型</span>
                  <select v-model="node.videoModelId" :disabled="node.generationStatus === 'running'" @change="syncVideoNodeSettings(node)">
                    <option v-for="model in videoModelOptions" :key="model.id" :value="model.id">
                      {{ model.label }}
                    </option>
                  </select>
                </label>
                <label class="video-composer-select video-composer-select--type">
                  <span>类型</span>
                  <select v-model="node.videoGenerationType" :disabled="node.generationStatus === 'running'" @change="syncVideoNodeSettings(node)">
                    <option v-for="feature in getVideoFeatureOptions(node)" :key="feature.id" :value="feature.id">
                      {{ feature.label }}
                    </option>
                  </select>
                </label>
                <details class="video-settings-menu" @toggle.stop="handleVideoSettingsToggle(node.id, $event)">
                  <summary class="video-settings-trigger">
                    <SlidersHorizontal :size="16" />
                    <span>{{ getVideoSettingsSummary(node) }}</span>
                    <ChevronDown :size="15" />
                  </summary>
                  <div
                    class="video-settings-popover"
                    @click.stop
                    @dblclick.stop
                    @pointerdown.stop
                    @mousedown.stop
                  >
                    <section v-if="hasVideoField(node, 'aspect_ratio')" class="video-settings-section">
                      <strong>比例</strong>
                      <div class="video-ratio-grid">
                        <button
                          v-for="ratio in getVideoFieldOptions(node, 'aspect_ratio', fallbackVideoAspectRatioOptions)"
                          :key="ratio.id"
                          class="video-ratio-option"
                          :class="{ 'is-active': isVideoFieldOptionSelected(node, 'aspect_ratio', ratio.id) }"
                          type="button"
                          :disabled="node.generationStatus === 'running'"
                          @click.stop="setVideoNodeSetting(node, 'aspect_ratio', ratio.id)"
                        >
                          <span class="video-ratio-icon" :data-ratio="ratio.id" />
                          <span>{{ formatVideoAspectRatioLabel(ratio) }}</span>
                        </button>
                      </div>
                    </section>
                    <section v-if="hasVideoField(node, 'resolution')" class="video-settings-section">
                      <strong>清晰度</strong>
                      <div class="video-segmented-options">
                        <button
                          v-for="resolution in getVideoFieldOptions(node, 'resolution', fallbackVideoResolutionOptions)"
                          :key="resolution.id"
                          class="video-segmented-option"
                          :class="{ 'is-active': isVideoFieldOptionSelected(node, 'resolution', resolution.id) }"
                          type="button"
                          :disabled="node.generationStatus === 'running'"
                          @click.stop="setVideoNodeSetting(node, 'resolution', resolution.id)"
                        >
                          {{ resolution.label }}
                        </button>
                      </div>
                    </section>
                    <section v-if="hasVideoField(node, 'duration')" class="video-settings-section">
                      <strong>视频时长</strong>
                      <div class="video-duration-control">
                        <input
                          type="range"
                          min="0"
                          :max="Math.max(getVideoDurationOptions(node).length - 1, 0)"
                          :value="getVideoDurationOptionIndex(node)"
                          :disabled="node.generationStatus === 'running' || getVideoDurationOptions(node).length <= 1"
                          @input.stop="setVideoDurationByIndex(node, $event)"
                        />
                        <span>{{ formatVideoDurationValue(node.videoDuration) }}</span>
                      </div>
                    </section>
                    <section v-if="hasVideoField(node, 'quality_mode')" class="video-settings-section">
                      <strong>画质</strong>
                      <div class="video-segmented-options">
                        <button
                          v-for="quality in getVideoFieldOptions(node, 'quality_mode', fallbackVideoQualityModeOptions)"
                          :key="quality.id"
                          class="video-segmented-option"
                          :class="{ 'is-active': isVideoFieldOptionSelected(node, 'quality_mode', quality.id) }"
                          type="button"
                          :disabled="node.generationStatus === 'running'"
                          @click.stop="setVideoNodeSetting(node, 'quality_mode', quality.id)"
                        >
                          {{ quality.label }}
                        </button>
                      </div>
                    </section>
                    <section v-if="hasVideoField(node, 'motion_strength')" class="video-settings-section">
                      <strong>运动</strong>
                      <div class="video-segmented-options">
                        <button
                          v-for="motion in getVideoFieldOptions(node, 'motion_strength', fallbackVideoMotionStrengthOptions)"
                          :key="motion.id"
                          class="video-segmented-option"
                          :class="{ 'is-active': isVideoFieldOptionSelected(node, 'motion_strength', motion.id) }"
                          type="button"
                          :disabled="node.generationStatus === 'running'"
                          @click.stop="setVideoNodeSetting(node, 'motion_strength', motion.id)"
                        >
                          {{ motion.label }}
                        </button>
                      </div>
                    </section>
                    <div class="video-settings-toggles">
                      <button
                        v-if="hasVideoField(node, 'audio_enabled')"
                        class="video-toggle-option"
                        :class="{ 'is-active': node.videoAudioEnabled }"
                        type="button"
                        :disabled="node.generationStatus === 'running'"
                        @click.stop="toggleVideoBooleanSetting(node, 'audio_enabled')"
                      >
                        原生声音
                      </button>
                      <button
                        v-if="hasVideoField(node, 'web_search')"
                        class="video-toggle-option"
                        :class="{ 'is-active': node.videoWebSearch }"
                        type="button"
                        :disabled="node.generationStatus === 'running'"
                        @click.stop="toggleVideoBooleanSetting(node, 'web_search')"
                      >
                        联网增强
                      </button>
                    </div>
                  </div>
                </details>
                <button
                  class="direct-workflow-node__generate direct-workflow-node__generate--video"
                  type="button"
                  :title="getVideoGenerationBlocker(node)"
                  :disabled="node.generationStatus === 'running' || !node.prompt.trim() || hasPendingReferenceUploads(node.id) || isVideoEstimatePending(node) || Boolean(getVideoGenerationBlocker(node))"
                  @click.stop="runDirectVideoNode(node)"
                >
                  <span class="direct-workflow-node__generate-cost">
                    <Star :size="14" />
                    {{ getVideoGenerationPointsButtonLabel(node) }}
                  </span>
                  <span>{{ node.generationStatus === 'running' ? '生成中' : '生成视频' }}</span>
                </button>
              </div>
              <p v-if="node.generationStatus === 'error'" class="direct-workflow-node__generation-error">
                {{ node.generationMessage || '视频生成失败，请稍后重试' }}
              </p>
            </div>
            <div
              v-if="node.type === 'audio_unit'"
              class="direct-workflow-node__generation-controls direct-workflow-node__generation-controls--audio"
              @click.stop
              @dblclick.stop
              @keydown.stop
              @keyup.stop
              @pointerdown.stop
              @mousedown.stop
            >
              <div class="audio-composer-bar">
                <div class="audio-token-tools">
                  <details class="audio-token-menu">
                    <summary title="插入停顿">
                      <span>&lt;#&gt;</span>
                      停顿
                    </summary>
                    <div class="audio-token-popover">
                      <p>在文中插入停顿，精准掌控音频节奏，支持选择预设时长或直接输入秒数</p>
                      <button
                        v-for="pause in audioPauseOptions"
                        :key="pause.value"
                        type="button"
                        :class="{ 'is-active': pause.value === '0.25' }"
                        @click.stop="insertAudioPromptToken(node.id, pause.text, pause.text, 'pause', $event)"
                      >
                        {{ pause.label }}
                      </button>
                    </div>
                  </details>
                  <details class="audio-token-menu">
                    <summary title="插入语气词">
                      <span>()</span>
                      语气词
                    </summary>
                    <div class="audio-token-popover audio-token-popover--narrow">
                      <p>点击插入或输入生动的语气词，让语音更具感染力，系统仅支持预设库内的语气词标签</p>
                      <button
                        v-for="word in audioInterjectionOptions"
                        :key="word"
                        type="button"
                        @click.stop="insertAudioPromptToken(node.id, `(${word})`, `(${word})`, 'interjection', $event)"
                      >
                        {{ word }}
                      </button>
                    </div>
                  </details>
                </div>

                <label class="audio-model-select">
                  <AudioWaveform :size="18" />
                  <select
                    :value="getAudioTierSelectValue(node)"
                    :disabled="node.generationStatus === 'running'"
                    @change="setAudioTierFromSelect(node, $event)"
                  >
                    <option v-for="tier in getAudioTierOptions(node)" :key="tier.value" :value="tier.value">
                      {{ tier.label }}
                    </option>
                  </select>
                </label>

                <button v-if="isAudioLanguageBoostSupported(node)" class="audio-icon-button" type="button" title="语言增强" :class="{ 'is-active': node.audioLanguageBoost === 'auto' }" @click.stop="toggleAudioLanguageBoost(node)">
                  <Languages :size="18" />
                </button>

                <button class="audio-icon-button" type="button" title="音频设置" :class="{ 'is-active': node.audioSettingsOpen }" @click.stop="toggleAudioSettingsPanel(node)">
                  <SlidersHorizontal :size="18" />
                </button>

                <span class="audio-character-count">{{ getAudioCharacterLabel(node) }}</span>
                <span class="audio-point-label"><Star :size="14" /> {{ getAudioGenerationPointsButtonLabel(node) }}</span>
                <button
                  class="audio-send-button"
                  type="button"
                  :title="getAudioGenerationBlocker(node)"
                  :disabled="node.generationStatus === 'running' || !node.prompt.trim() || isAudioEstimatePending(node) || Boolean(getAudioGenerationBlocker(node))"
                  @click.stop="runDirectAudioNode(node)"
                >
                  <ArrowUp :size="20" />
                </button>
              </div>
              <p v-if="node.generationStatus === 'error'" class="direct-workflow-node__generation-error">
                {{ node.generationMessage || '音频生成失败，请稍后重试' }}
              </p>
              <section v-if="node.audioSettingsOpen" class="audio-inline-settings">
                <header>
                  <strong>音色设置</strong>
                  <button type="button" @click.stop="resetAudioNodeSettings(node)">一键重置</button>
                </header>
                <button class="audio-voice-card" type="button" @click.stop="openAudioVoicePicker(node)">
                  <span class="audio-voice-card__icon"><Music2 :size="22" /></span>
                  <span class="audio-voice-card__name">{{ getAudioVoiceLabel(node) }}</span>
                  <span class="audio-voice-card__copy">▣</span>
                  <span class="audio-voice-card__tag">{{ getAudioVoiceLanguageLabel(node) }}</span>
                  <ChevronDown :size="18" />
                </button>
                <div class="audio-basic-header">
                  <strong>基础调节</strong>
                  <ChevronDown :size="16" />
                </div>
                <label class="audio-slider-row">
                  <span>语速</span>
                  <input v-model.number="node.audioSpeed" type="range" min="0.5" max="2" step="0.01" />
                  <output>{{ formatAudioNumber(node.audioSpeed, 2) }}</output>
                </label>
                <label class="audio-slider-row">
                  <span>声调</span>
                  <input v-model.number="node.audioPitch" type="range" min="-12" max="12" step="1" />
                  <output>{{ formatAudioNumber(node.audioPitch, 0) }}</output>
                </label>
                <label class="audio-slider-row">
                  <span>音量</span>
                  <input v-model.number="node.audioVolume" type="range" min="0.1" max="10" step="0.1" />
                  <output>{{ formatAudioNumber(node.audioVolume, 1) }}</output>
                </label>
                <label v-if="isAudioEmotionSupported(node)" class="audio-select-row">
                  <span>情绪</span>
                  <select v-model="node.audioEmotion">
                    <option value="">默认</option>
                    <option v-for="emotion in audioEmotionOptions" :key="emotion.value" :value="emotion.value">
                      {{ emotion.label }}
                    </option>
                  </select>
                </label>
              </section>
            </div>
          </div>
        </article>
      </div>

      <div
        v-if="directSelectionFrame.visible"
        class="direct-selection-frame"
        :class="{ 'is-grouped': directSelectionFrame.grouped }"
        :style="directSelectionFrameStyle"
      />

      <div
        v-if="directGroupToolbar.visible"
        class="direct-group-toolbar"
        :style="directGroupToolbarStyle"
        @pointerdown.stop
        @click.stop
      >
        <button
          v-if="directGroupToolbar.mode === 'group'"
          type="button"
          @click="groupSelectedDirectNodes"
        >
          <span>▦</span>
          打组 {{ selectedDirectNodeIds.length }} 个节点
        </button>
        <button
          v-else
          type="button"
          @click="ungroupSelectedDirectNodes"
        >
          <span>□</span>
          解组
        </button>
      </div>

      <div v-if="selectionBox.active" class="direct-selection-box" :style="selectionBoxStyle" />

      <input
        ref="deleteKeySink"
        class="delete-key-sink"
        aria-label="画布快捷键输入"
        autocomplete="off"
        readonly
        tabindex="-1"
        @keydown.stop="handleDeleteSinkKey"
        @keyup.stop="handleDeleteSinkKey"
      />

      <input
        ref="uploadInput"
        class="hidden-upload-input"
        type="file"
        accept="image/*,video/*,audio/*"
        @change="handleUploadInputChange"
      />
      <input
        ref="referenceUploadInput"
        class="hidden-upload-input"
        type="file"
        :accept="referenceUploadAccept"
        multiple
        @change="handleReferenceUploadInputChange"
      />

      <CommandBar
        v-model:title="projectTitle"
        :save-status="saveStatus"
        :save-error="lastSaveError"
        @go-home="goHome"
        @logout="logoutCanvas"
        @save="saveCanvasNow"
        @publish="openPublishDialog"
      />

      <CanvasToolRail
        :can-undo="canUndo"
        :help-visible="helpVisible"
        :active-panel="activeRailPanel"
        @open-add-menu="openAddMenuFromButton"
        @open-toolbox="toggleRailPanel('toolbox')"
        @open-assets="toggleRailPanel('assets')"
        @open-history="toggleRailPanel('history')"
        @toggle-help="toggleHelp"
        @support="handleSupport"
      />

      <button
        v-if="!agentPanel.visible"
        class="canvas-agent-trigger"
        type="button"
        title="打开创作总监"
        @click.stop="toggleAgentPanel"
      >
        <Bot :size="19" />
        <span>创作总监</span>
        <small v-if="pendingAgentActionCount">{{ pendingAgentActionCount }}</small>
      </button>

      <aside v-if="agentPanel.visible" class="canvas-agent-panel" @click.stop @pointerdown.stop @contextmenu.prevent.stop>
        <header class="canvas-agent-panel__header">
          <div>
            <span>Canvas Agent Studio</span>
            <h2>创作总监</h2>
            <p>{{ agentPanel.busy ? '正在协调专业 Agent' : '对话驱动画布产物' }}</p>
          </div>
          <button type="button" aria-label="收起 Agent 面板" @click="setAgentPanelVisible(false)">
            <X :size="22" />
          </button>
        </header>

        <section class="canvas-agent-panel__mode">
          <strong>自由画布</strong>
          <span>{{ getAgentPanelModeSummary() }}</span>
          <button type="button" @click="agentPanel.advancedOpen = !agentPanel.advancedOpen">
            <SlidersHorizontal :size="15" />
            Agent Team
          </button>
        </section>

        <section v-if="agentPanel.advancedOpen" class="canvas-agent-panel__controls">
          <label>
            Agent
            <select v-model="agentPanel.profile">
              <option value="auto">自动派发（推荐）</option>
              <optgroup label="我的 Agent">
                <option v-for="agent in agentPanel.templates" :key="agent.id" :value="agent.id">{{ agent.name }}</option>
              </optgroup>
              <optgroup label="官方 starter">
                <option v-for="profile in agentProfiles.filter((profile) => profile.id !== 'auto')" :key="profile.id" :value="profile.id">{{ profile.label }}</option>
              </optgroup>
            </select>
          </label>
          <label>
            模型
            <select v-model="agentPanel.modelCode">
              <option v-for="model in agentModelOptions" :key="model.id" :value="model.id">{{ model.label }}</option>
            </select>
          </label>
          <div class="canvas-agent-panel__template-actions">
            <button type="button" @click="openAgentTemplateEditor()">新建 Agent</button>
            <button type="button" @click="createAgentFromStarter()">从 starter 复制</button>
            <button type="button" :disabled="!hasAgentTemplateSelection" @click="openAgentTemplateEditor(getSelectedAgentTemplate())">编辑</button>
            <button type="button" :disabled="!hasAgentTemplateSelection" @click="deleteSelectedAgentTemplate">删除</button>
          </div>
          <form v-if="agentPanel.agentEditorOpen" class="canvas-agent-template-form" @submit.prevent="saveAgentTemplate">
            <input v-model="agentPanel.agentForm.name" type="text" placeholder="Agent 名称" maxlength="80" />
            <input v-model="agentPanel.agentForm.description" type="text" placeholder="一句话说明它擅长什么" maxlength="180" />
            <select v-model="agentPanel.agentForm.modelCode">
              <option v-for="model in agentModelOptions" :key="model.id" :value="model.id">{{ model.label }}</option>
            </select>
            <textarea v-model="agentPanel.agentForm.rolePrompt" rows="3" placeholder="角色提示词：说明这个 Agent 的职责、边界和输出方式。" />
            <input v-model="agentPanel.agentForm.useCasesText" type="text" placeholder="用例，用逗号分隔" />
            <input v-model="agentPanel.agentForm.inputTypesText" type="text" placeholder="输入类型，如 text,image" />
            <input v-model="agentPanel.agentForm.outputTypesText" type="text" placeholder="输出类型，如 note,image,video" />
            <footer>
              <button type="button" @click="closeAgentTemplateEditor">取消</button>
              <button class="canvas-agent-template-form__primary" type="submit">{{ agentPanel.editingAgentId ? '保存 Agent' : '创建 Agent' }}</button>
            </footer>
          </form>
        </section>

        <section class="canvas-agent-panel__context">
          <button type="button" @click="startAgentWithSelection('请把当前故事目标拆成故事总览、角色场景、分镜计划和生成占位。')">拆故事</button>
          <button type="button" @click="startAgentWithSelection('请提取当前目标或选区里的角色、场景、道具和一致性锚点。')">提角色场景</button>
          <button type="button" @click="startAgentWithSelection('请根据当前选区生成分镜链路、首帧图片占位和视频生成占位。')">生成分镜链路</button>
          <button type="button" :disabled="selectedDirectNodeIds.length === 0" @click="startAgentWithSelection('请检查当前选区的角色、场景、道具和风格一致性。')">检查一致性</button>
          <button type="button" @click="startAgentWithSelection('请创建下一批图片和视频生成任务，但所有扣费媒体任务必须先等待确认。')">创建生成任务</button>
        </section>

        <section v-if="agentRunHistory.length" class="canvas-agent-history">
          <header>
            <strong>Run 历史</strong>
            <button type="button" :disabled="agentPanel.loadingRuns" @click="loadAgentRuns({ restore: false })">刷新</button>
          </header>
          <button
            v-for="item in agentRunHistory"
            :key="item.run.id"
            type="button"
            :class="{ 'is-active': item.run.id === agentPanel.runId }"
            @click="restoreAgentRun(item)"
          >
            <span>{{ item.run.title || 'Agent Run' }}</span>
            <small>{{ getAgentRunHistorySummary(item) }}</small>
          </button>
        </section>

        <section class="canvas-agent-run">
          <div v-if="agentPanel.activeRun" class="canvas-agent-run__summary">
            <span>{{ getAgentRunStatusLabel(agentPanel.activeRun.run.status) }}</span>
            <strong>{{ agentPanel.activeRun.run.goal }}</strong>
            <small>{{ getAgentRunMeta(agentPanel.activeRun) }}</small>
          </div>
          <div v-if="agentPanel.activeRun?.steps?.length" class="canvas-agent-timeline">
            <article v-for="step in agentPanel.activeRun.steps" :key="step.id" class="canvas-agent-step">
              <header>
                <div>
                  <span>{{ step.agentName || 'Agent' }} · {{ getAgentModelLabel(step.modelCode) }}</span>
                  <strong>{{ step.title }}</strong>
                </div>
                <b :class="`is-${step.status}`">{{ getAgentStepStatusLabel(step.status) }}</b>
              </header>
              <p v-if="getAgentStepInputSummary(step)">{{ getAgentStepInputSummary(step) }}</p>
              <div v-if="step.artifacts?.length" class="canvas-agent-artifacts">
                <section v-for="artifact in step.artifacts" :key="artifact.id" class="canvas-agent-artifact">
                  <header>
                    <strong>{{ artifact.title }}</strong>
                    <span>{{ getAgentArtifactTypeLabel(artifact.artifactType) }} · {{ getAgentArtifactStatusLabel(artifact.status) }}</span>
                  </header>
                  <p>{{ getAgentArtifactPreview(artifact) }}</p>
                  <small v-if="artifact.canvasNodeId">已写入画布节点</small>
                  <small v-if="artifact.generationRecordId">生成记录 {{ artifact.generationRecordId }}</small>
                </section>
              </div>
              <footer v-if="step.status === 'failed'">
                <span>{{ step.error?.message || '阶段执行失败' }}</span>
                <button type="button" :disabled="agentPanel.busy" @click="retryAgentRunStep(step)">重试阶段</button>
              </footer>
            </article>
          </div>
          <p v-else class="canvas-agent-panel__empty">输入一个目标后，创作总监会按 Run → Step → Artifact 展开多 Agent 时间线，并把文本与媒体占位节点写入画布。</p>
          <footer v-if="agentPanel.activeRun?.run?.status === 'waiting_cost_confirmation'" class="canvas-agent-run__cost">
            <span>媒体生成等待确认，预计消耗 {{ getAgentRunEstimatePoints(agentPanel.activeRun) }} 灵感值。</span>
            <button type="button" :disabled="agentPanel.confirmingCost" @click="confirmAgentRunCost">
              <Check :size="16" />
              确认并提交生成
            </button>
          </footer>
        </section>

        <section v-if="agentPanel.pendingAction" class="canvas-agent-action">
          <div>
            <strong>{{ agentPanel.pendingAction.summary || agentPanel.pendingAction.actionType }}</strong>
            <span>{{ getAgentActionStats(agentPanel.pendingAction) }}</span>
            <small>{{ getAgentRoutingLabel(agentPanel.pendingAction) }}</small>
          </div>
          <ul v-if="getAgentActionPreviewNodes(agentPanel.pendingAction).length" class="canvas-agent-action__preview">
            <li v-for="node in getAgentActionPreviewNodes(agentPanel.pendingAction)" :key="node.key">
              <b>{{ node.title }}</b>
              <span>{{ node.type }}</span>
            </li>
          </ul>
          <ul v-if="getAgentActionPreviewEdges(agentPanel.pendingAction).length" class="canvas-agent-action__preview canvas-agent-action__preview--edges">
            <li v-for="edge in getAgentActionPreviewEdges(agentPanel.pendingAction)" :key="edge.key">
              <b>{{ edge.label }}</b>
              <span>{{ edge.type }}</span>
            </li>
          </ul>
          <p v-if="agentPanel.pendingAction.status === 'failed'" class="canvas-agent-action__error">
            {{ agentPanel.pendingAction.error?.message || '提案写入失败，可调整后重试或取消。' }}
          </p>
          <footer>
            <button type="button" :disabled="agentPanel.busy" @click="cancelAgentAction">
              <X :size="16" />
              取消
            </button>
            <button class="canvas-agent-action__primary" type="button" :disabled="agentPanel.busy" @click="approveAgentAction">
              <Check :size="16" />
              批准写入
            </button>
          </footer>
        </section>

        <form class="canvas-agent-panel__composer" @submit.prevent="sendAgentPrompt">
          <textarea v-model="agentPanel.input" rows="3" placeholder="例如：一个雨夜少年追逐神秘信号的动画短片，帮我提取角色、场景、道具并拆分镜。" />
          <button type="submit" :disabled="agentPanel.busy || !agentPanel.input.trim()">
            <Send :size="17" />
          </button>
        </form>
        <p v-if="agentPanel.error" class="canvas-agent-panel__error">{{ agentPanel.error }}</p>
      </aside>

      <StarterSkillStrip v-if="showStarterStrip" @select-node="handleStarterSelect" />

      <CanvasBottomControls
        :zoom-label="zoomLabel"
        :grid-visible="gridVisible"
        :snap-enabled="snapEnabled"
        :minimap-visible="minimapVisible"
        @toggle-grid="toggleGrid"
        @toggle-minimap="toggleMinimap"
        @locate="locateCanvas"
        @toggle-snap="toggleSnap"
        @zoom-in="handleZoomIn"
        @zoom-out="handleZoomOut"
      />

      <Transition name="canvas-minimap-pop">
        <div v-if="minimapVisible" class="canvas-minimap" @click.stop>
        <svg class="canvas-minimap__viewport" viewBox="0 0 180 82" aria-hidden="true">
          <rect class="canvas-minimap__world" x="0" y="0" width="180" height="82" rx="2" />
          <rect
            v-for="item in minimapRects"
            :key="item.id"
            class="canvas-minimap__node"
            :class="`canvas-minimap__node--${item.kind}`"
            :x="item.x"
            :y="item.y"
            :width="item.width"
            :height="item.height"
            rx="1.5"
          />
          <rect
            class="canvas-minimap__camera"
            :x="minimapViewportRect.x"
            :y="minimapViewportRect.y"
            :width="minimapViewportRect.width"
            :height="minimapViewportRect.height"
            rx="1.5"
          />
        </svg>
        <span class="canvas-minimap__label">画布小地图</span>
        </div>
      </Transition>

      <Transition name="canvas-panel-pop">
        <aside v-if="activeRailPanel === 'toolbox'" class="rail-panel rail-panel--side rail-panel--toolbox" @click.stop>
          <header class="rail-panel__header">
            <h2>我的工具箱</h2>
            <button class="rail-panel__close" type="button" title="关闭" @click="closeRailPanel">
              <X :size="26" />
            </button>
          </header>
          <div class="rail-panel__coming-soon">
            <strong>正在上架中！</strong>
            <span>更多创作工具即将开放</span>
          </div>
        </aside>
      </Transition>

      <Transition name="canvas-panel-pop">
        <aside v-if="activeRailPanel === 'assets'" class="rail-panel rail-panel--side rail-panel--assets" @click.stop>
          <header class="rail-panel__header">
            <div class="rail-panel__tabs rail-panel__tabs--title">
              <button :class="{ 'is-active': activeAssetLibrary === 'assets' }" type="button" @click="activeAssetLibrary = 'assets'">我的素材</button>
              <button :class="{ 'is-active': activeAssetLibrary === 'subjects' }" type="button" @click="activeAssetLibrary = 'subjects'">我的主体库</button>
            </div>
            <button class="rail-panel__close" type="button" title="关闭" @click="closeRailPanel">
              <X :size="26" />
            </button>
          </header>
          <nav class="asset-tabs" aria-label="素材分类">
            <button v-for="tab in assetTabs" :key="tab" :class="{ 'is-active': activeAssetTab === tab }" type="button" @click="activeAssetTab = tab">
              {{ tab }}
            </button>
          </nav>
          <div class="rail-panel__empty">{{ activeAssetLibrary === 'assets' ? '暂无素材' : '暂无主体' }}</div>
        </aside>
      </Transition>

      <Transition name="history-panel-fade">
        <div v-if="activeRailPanel === 'history'" class="history-overlay" @click.stop>
          <section class="history-panel">
            <header class="history-panel__header">
              <nav class="history-panel__tabs" aria-label="历史分类">
                <button v-for="tab in historyTabs" :key="tab.id" :class="{ 'is-active': activeHistoryTab === tab.id }" type="button" @click="activeHistoryTab = tab.id">
                  {{ tab.label }}
                </button>
              </nav>
              <div class="history-panel__actions">
                <button class="history-panel__batch" :class="{ 'is-active': historyBatchMode }" type="button" @click="historyBatchMode = !historyBatchMode">
                  <ListChecks :size="17" />
                  批量操作
                </button>
                <div class="history-panel__zoom">
                  <button type="button" @click="handleZoomOut"><Minus :size="17" /></button>
                  <span>{{ zoomLabel }}</span>
                  <button type="button" @click="handleZoomIn"><Plus :size="17" /></button>
                </div>
                <button class="history-panel__icon" :class="{ 'is-active': historySortAscending }" type="button" title="排序" @click="historySortAscending = !historySortAscending">
                  <ArrowUpDown :size="20" />
                </button>
                <button class="history-panel__icon" type="button" title="关闭" @click="closeRailPanel">
                  <X :size="26" />
                </button>
              </div>
            </header>
            <div class="history-panel__empty">{{ activeHistoryLabel }}</div>
          </section>
        </div>
      </Transition>

      <Transition name="library-picker-fade">
        <div v-if="libraryPicker.visible" class="library-picker-overlay" @click.stop>
          <section class="library-picker">
            <header class="library-picker__header">
              <h2>选择图片</h2>
              <button type="button" title="关闭" @click="closeLibraryPicker">
                <X :size="27" />
              </button>
            </header>
            <div class="library-picker__top">
              <nav class="library-picker__source-tabs" aria-label="图库来源">
                <button
                  v-for="tab in librarySourceTabs"
                  :key="tab"
                  :class="{ 'is-active': libraryPicker.source === tab }"
                  type="button"
                  @click="libraryPicker.source = tab"
                >
                  {{ tab }}
                </button>
              </nav>
              <span>已选 <b>{{ libraryPicker.selected }}</b>/10 张</span>
            </div>
            <nav class="library-picker__type-tabs" aria-label="素材类型">
              <button
                v-for="tab in libraryTypeTabs"
                :key="tab"
                :class="{ 'is-active': libraryPicker.type === tab }"
                type="button"
                @click="libraryPicker.type = tab"
              >
                {{ tab }}
              </button>
            </nav>
            <div class="library-picker__empty">暂无数据</div>
            <footer class="library-picker__footer">
              <button type="button" @click="confirmLibraryPicker">确定</button>
            </footer>
          </section>
        </div>
      </Transition>

      <AddNodeMenu
        v-if="addMenu.visible"
        :position="addMenu.screen"
        :show-resources="!pendingDirectConnection.sourceId"
        :allowed-items="getPendingConnectionAllowedMenuItems()"
        :on-select="handleMenuSelect"
        @click.stop
        @select-node="handleMenuSelect"
      />

      <AddNodeMenu
        v-if="referenceMenu.visible"
        title="引用该节点生成"
        variant="reference"
        :position="referenceMenu.screen"
        :show-resources="false"
        :disabled-items="['compose']"
        :on-select="handleReferenceSelect"
        @click.stop
        @select-node="handleReferenceSelect"
      />

      <div v-if="contextMenu.visible" class="canvas-context-menu" :style="contextMenuStyle" @click.stop>
        <button type="button" @click="handleContextUpload">上传</button>
        <button type="button" :disabled="selectedDirectNodeIds.length === 0" @click="handleContextAgentAnalyze">让 Agent 分析</button>
        <button type="button" :disabled="selectedDirectNodeIds.length === 0" @click="handleContextAgentDownstream">生成下游节点</button>
        <button type="button" :disabled="selectedDirectNodeIds.length === 0" @click="handleContextAgentConsistency">检查一致性</button>
        <button type="button" :disabled="!canUndo" @click="handleContextUndo">
          <span>撤销</span>
          <kbd>Ctrl Z</kbd>
        </button>
        <button type="button" :disabled="!canRedo" @click="handleContextRedo">
          <span>重做</span>
          <kbd>Ctrl Shift Z</kbd>
        </button>
      </div>

      <Transition name="canvas-panel-pop">
        <aside v-if="helpVisible" class="canvas-help-panel" @click.stop>
          <header class="canvas-help-panel__header">
            <div>
              <span>快捷键与画布操作</span>
              <h2>{{ copy.helpTitle }}</h2>
            </div>
            <button type="button" aria-label="关闭帮助" @click="toggleHelp">
              <X :size="28" />
            </button>
          </header>
          <div class="canvas-help-panel__body">
            <section v-for="section in helpShortcutSections" :key="section.title" class="canvas-help-section">
              <h3>{{ section.title }}</h3>
              <div class="canvas-help-shortcuts">
                <article v-for="item in section.items" :key="item.label">
                  <span>{{ item.label }}</span>
                  <div>
                    <kbd v-for="key in item.keys" :key="key">{{ key }}</kbd>
                  </div>
                </article>
              </div>
            </section>
          </div>
          <footer class="canvas-help-panel__footer">
            <span>普通滚轮上下移动画布，按住 Ctrl / Cmd 再滚动即可缩放。</span>
          </footer>
        </aside>
      </Transition>

      <div
        v-if="imagePreview.visible"
        class="image-preview-overlay"
        role="dialog"
        aria-modal="true"
        aria-label="图片预览"
        @click="closeImagePreview"
        @pointerdown.stop
        @contextmenu.prevent.stop
      >
        <button class="image-preview-overlay__close" type="button" aria-label="关闭预览" @click.stop="closeImagePreview">
          <X :size="32" />
        </button>
        <img :src="imagePreview.url" :alt="imagePreview.alt" draggable="false" @click.stop />
      </div>

      <div v-if="audioVoicePicker.visible" class="audio-voice-overlay" role="dialog" aria-modal="true" aria-label="音色选择" @click.stop>
        <section class="audio-voice-dialog">
          <header>
            <h2>音色选择</h2>
            <button type="button" aria-label="关闭" @click="closeAudioVoicePicker">
              <X :size="28" />
            </button>
          </header>
          <div class="audio-voice-dialog__tools">
            <nav>
              <button v-for="tab in audioVoiceTabs" :key="tab.id" :class="{ 'is-active': audioVoicePicker.tab === tab.id }" type="button" @click="audioVoicePicker.tab = tab.id">
                {{ tab.label }}
              </button>
            </nav>
            <label>
              <span>⌕</span>
              <input v-model="audioVoicePicker.query" type="search" placeholder="搜索音色库" />
            </label>
            <button type="button">筛选</button>
          </div>
          <div class="audio-voice-list">
            <article
              v-for="voice in filteredAudioVoiceOptions"
              :key="voice.voiceId"
              class="audio-voice-item"
              :class="{ 'is-selected': voice.voiceId === getActiveAudioVoiceId() }"
            >
              <span class="audio-voice-item__icon"><Music2 :size="22" /></span>
              <strong>{{ voice.label }}</strong>
              <span class="audio-voice-item__tag">{{ voice.categoryLabel || '中文(普通话)' }}</span>
              <span class="audio-voice-item__tag">{{ voice.styleLabel || 'Voice' }}</span>
              <button class="audio-voice-item__select" type="button" :disabled="voice.voiceId === getActiveAudioVoiceId()" @click.stop="selectAudioVoice(voice)">
                {{ voice.voiceId === getActiveAudioVoiceId() ? '已选' : '选择' }}
              </button>
              <button
                class="audio-voice-item__star"
                type="button"
                :class="{ 'is-active': isAudioVoiceFavorite(voice) }"
                :title="isAudioVoiceFavorite(voice) ? '取消收藏' : '收藏音色'"
                @click.stop="toggleAudioVoiceFavorite(voice)"
              >
                {{ isAudioVoiceFavorite(voice) ? '★' : '☆' }}
              </button>
              <span class="audio-voice-item__more">•••</span>
            </article>
            <p v-if="filteredAudioVoiceOptions.length === 0" class="audio-voice-list__empty">暂无匹配音色</p>
          </div>
          <footer>
            <span>共 {{ filteredAudioVoiceOptions.length }} 条</span>
          </footer>
        </section>
      </div>

      <div v-if="publishDialog.visible" class="publish-overlay" role="dialog" aria-modal="true" aria-label="发布到社区" @click.stop>
        <section class="publish-dialog">
          <header>
            <div>
              <span>开放画布社区</span>
              <h2>{{ publishDialog.publicationId ? '更新发布版本' : '发布到社区' }}</h2>
            </div>
            <button type="button" aria-label="关闭" @click="closePublishDialog">
              <X :size="24" />
            </button>
          </header>
          <label>
            标题
            <input v-model="publishForm.title" type="text" maxlength="80" />
          </label>
          <label>
            简介
            <textarea v-model="publishForm.description" rows="4" maxlength="280" />
          </label>
          <label>
            标签
            <input v-model="publishForm.tagsText" type="text" placeholder="漫剧, 分镜, 角色设定" />
          </label>
          <label>
            封面 URL
            <input v-model="publishForm.coverUrl" type="url" placeholder="默认使用项目第一张图片" />
          </label>
          <p v-if="publishDialog.error" class="publish-dialog__error">{{ publishDialog.error }}</p>
          <footer>
            <button v-if="publishDialog.publicationId" type="button" :disabled="publishDialog.submitting" @click="unpublishCurrentCanvas">取消发布</button>
            <button type="button" @click="closePublishDialog">稍后</button>
            <button class="publish-dialog__primary" type="button" :disabled="publishDialog.submitting" @click="publishCurrentCanvas">
              {{ publishDialog.submitting ? '发布中' : (publishDialog.publicationId ? '更新发布版本' : '发布到社区') }}
            </button>
          </footer>
        </section>
      </div>

      <div v-if="toastMessage" class="canvas-toast">{{ toastMessage }}</div>
    </section>
  </div>
</template>

<script setup>
import { computed, nextTick, onBeforeUnmount, onMounted, reactive, ref, watch } from 'vue'
import { onBeforeRouteLeave, onBeforeRouteUpdate, useRoute, useRouter } from 'vue-router'
import { MarkerType, VueFlow, useVueFlow } from '@vue-flow/core'
import { Background } from '@vue-flow/background'
import { ArrowUp, ArrowUpDown, AudioWaveform, Bot, Check, ChevronDown, Download, Eye, Languages, ListChecks, Minus, Music2, Plus, Send, SlidersHorizontal, Star, Upload, X } from 'lucide-vue-next'
import CommandBar from '../components/layout/CommandBar.vue'
import AddNodeMenu from '../components/canvas/AddNodeMenu.vue'
import CanvasBottomControls from '../components/canvas/CanvasBottomControls.vue'
import CanvasToolRail from '../components/canvas/CanvasToolRail.vue'
import StarterSkillStrip from '../components/canvas/StarterSkillStrip.vue'
import WorkflowEdge from '../canvas/edges/WorkflowEdge.vue'
import WorkflowNode from '../canvas/nodes/WorkflowNode.vue'
import {
  estimateCreativeAudio,
  estimateCreativeVideo,
  fetchCreativeAudioCatalog,
  fetchCreativeImageCatalog,
  fetchCreativeVideoCatalog,
  fetchCreativeVoiceAssets,
  fetchCreativeRecord,
  fetchCreativeRecords,
  fetchTask,
  submitCreativeAudio,
  submitCreativeImage,
  submitCreativeVideo
} from '../api/creativeApi'
import {
  analyzeSluvoTextNode,
  approveSluvoAgentAction,
  cancelSluvoAgentAction,
  confirmSluvoAgentRunCost,
  continueSluvoAgentRun,
  createSluvoAgent,
  createSluvoAgentRun,
  createSluvoAgentSession,
  deleteSluvoAgent,
  fetchSluvoAgents,
  fetchSluvoAgentRun,
  fetchSluvoProjectAgentRuns,
  fetchSluvoProjectAgentSessions,
  fetchSluvoProjectCanvas,
  publishSluvoProjectToCommunity,
  saveSluvoCanvasBatch,
  sendSluvoAgentMessage,
  SluvoRevisionConflictError,
  retrySluvoAgentStep,
  updateSluvoAgent,
  unpublishSluvoCommunityCanvas,
  uploadSluvoCanvasAsset
} from '../api/sluvoApi'
import { buildApiUrl } from '../api/client'
import { useCanvasStore } from '../stores/canvasStore'
import { useProjectStore } from '../stores/projectStore'


const copy = {
  untitled: '\u672a\u547d\u540d',
  duplicate: '\u590d\u5236\u8282\u70b9',
  group: '\u6253\u7ec4',
  delete: '\u5220\u9664',
  helpTitle: '\u753b\u5e03\u64cd\u4f5c',
  helpAdd: '\u53cc\u51fb\u7a7a\u767d\u5904\u6dfb\u52a0\u8282\u70b9\uff0c\u53f3\u952e\u6253\u5f00\u5feb\u6377\u83dc\u5355',
  helpPan: '\u62d6\u52a8\u753b\u5e03\u5e73\u79fb\uff0c\u6eda\u8f6e\u6216\u89e6\u63a7\u677f\u7f29\u653e',
  helpSelect: 'Shift \u62d6\u62fd\u6846\u9009\uff0c\u62d6\u62fd\u8282\u70b9\u79fb\u52a8\uff0c\u8fde\u63a5\u7aef\u53e3\u5efa\u7acb\u5173\u7cfb',
  helpCopy: 'Ctrl/Cmd+C \u590d\u5236\uff0cCtrl/Cmd+V \u7c98\u8d34\uff0cCtrl/Cmd+G \u6253\u7ec4',
  helpZoom: 'Ctrl/Cmd+0 \u5b9a\u4f4d\uff0cCtrl/Cmd+\u52a0\u51cf\u7f29\u653e\uff0cCtrl/Cmd+Z \u64a4\u9500'
}

const helpShortcutSections = [
  {
    title: '画布导航',
    items: [
      { label: '上下移动画布', keys: ['鼠标滚轮'] },
      { label: '缩放画布', keys: ['Ctrl / Cmd', '鼠标滚轮'] },
      { label: '拖拽平移画布', keys: ['空格', '拖拽'] },
      { label: '方向键平移', keys: ['↑', '↓', '←', '→'] },
      { label: '定位画布', keys: ['Ctrl / Cmd', '0'] },
      { label: '放大 / 缩小', keys: ['Ctrl / Cmd', '+ / -'] }
    ]
  },
  {
    title: '节点操作',
    items: [
      { label: '添加节点', keys: ['双击空白处'] },
      { label: '打开快捷菜单', keys: ['右键空白处'] },
      { label: '框选节点', keys: ['Shift', '拖拽'] },
      { label: '移动节点', keys: ['拖拽节点'] },
      { label: '连接节点', keys: ['拖拽连接点'] },
      { label: '删除节点', keys: ['Delete / Backspace'] }
    ]
  },
  {
    title: '编辑与历史',
    items: [
      { label: '复制', keys: ['Ctrl / Cmd', 'C'] },
      { label: '粘贴', keys: ['Ctrl / Cmd', 'V'] },
      { label: '复制一份', keys: ['Ctrl / Cmd', 'D'] },
      { label: '打组', keys: ['Ctrl / Cmd', 'G'] },
      { label: '撤销', keys: ['Ctrl / Cmd', 'Z'] },
      { label: '关闭弹窗 / 菜单', keys: ['Esc'] }
    ]
  },
  {
    title: '音频输入',
    items: [
      { label: '插入普通文本', keys: ['直接输入'] },
      { label: '插入停顿 / 语气词', keys: ['点击标签'] },
      { label: '设置区内滚动', keys: ['鼠标滚轮'] },
      { label: '选择音色', keys: ['音色卡片'] }
    ]
  }
]

const starterPositions = {
  script_episode: { x: 80, y: 140 },
  asset_table: { x: 440, y: 140 },
  video_unit: { x: 800, y: 140 },
  audio_unit: { x: 1160, y: 140 }
}

const nodeMeta = {
  prompt_note: {
    label: '\u6587\u672c',
    accent: '#e9e9e9',
    icon: '\u6587',
    title: '\u6587\u672c\u8282\u70b9',
    body: '\u5199\u4e0b\u521b\u610f\u3001\u63d0\u793a\u8bcd\u3001\u5bf9\u767d\u6216\u65c1\u767d\uff0c\u4f5c\u4e3a\u4e0b\u6e38\u751f\u6210\u8282\u70b9\u7684\u8f93\u5165\u3002',
    action: '\u7f16\u8f91\u6587\u672c'
  },
  image_unit: {
    label: '\u56fe\u7247',
    accent: '#f5d36d',
    icon: '\u56fe',
    title: '\u56fe\u7247\u751f\u6210',
    body: '\u8f93\u5165\u63d0\u793a\u8bcd\u5e76\u8fde\u63a5\u53c2\u8003\u8d44\u6e90\uff0c\u751f\u6210\u89d2\u8272\u56fe\u3001\u573a\u666f\u56fe\u6216\u9996\u5e27\u56fe\u3002',
    action: '\u751f\u6210\u56fe\u7247'
  },
  video_unit: {
    label: '\u89c6\u9891',
    accent: '#82d6ff',
    icon: '\u89c6',
    title: '\u89c6\u9891\u751f\u6210',
    body: '\u8fde\u63a5\u811a\u672c\u3001\u56fe\u7247\u6216\u97f3\u9891\u8282\u70b9\uff0c\u751f\u6210\u52a8\u6001\u955c\u5934\u548c\u77ed\u7247\u7247\u6bb5\u3002',
    action: '\u751f\u6210\u89c6\u9891'
  },
  audio_unit: {
    label: '\u97f3\u9891',
    accent: '#98f0bd',
    icon: '\u97f3',
    title: '\u97f3\u9891\u8282\u70b9',
    body: '\u751f\u6210\u6216\u5bfc\u5165\u65c1\u767d\u3001\u97f3\u4e50\u548c\u97f3\u6548\uff0c\u5e76\u9a71\u52a8\u89c6\u9891\u8282\u594f\u3002',
    action: '\u751f\u6210\u97f3\u9891'
  },
  script_episode: {
    label: '\u811a\u672c',
    accent: '#ffb45e',
    icon: '\u811a',
    title: '\u6545\u4e8b\u811a\u672c',
    body: '\u4ece\u6545\u4e8b\u6897\u6982\u751f\u6210\u5267\u672c\u7ed3\u6784\u3001\u955c\u5934\u8282\u62cd\u548c\u53ef\u6267\u884c\u521b\u4f5c\u94fe\u8def\u3002',
    action: '\u751f\u6210\u811a\u672c'
  },
  asset_table: {
    label: '\u8d44\u6e90',
    accent: '#b8a7ff',
    icon: '\u8d44',
    title: '\u8d44\u6e90\u8282\u70b9',
    body: '\u4e0a\u4f20\u6216\u9009\u62e9\u89d2\u8272\u3001\u573a\u666f\u3001\u9053\u5177\u548c\u98ce\u683c\u53c2\u8003\uff0c\u4f9b\u751f\u6210\u8282\u70b9\u590d\u7528\u3002',
    action: '\u9009\u62e9\u8d44\u6e90'
  },
  storyboard_table: {
    label: '\u5206\u955c',
    accent: '#ff8e88',
    icon: '\u955c',
    title: '\u5206\u955c\u8282\u70b9',
    body: '\u628a\u811a\u672c\u62c6\u6210\u955c\u5934\u5217\u8868\uff0c\u5e76\u7ec4\u7ec7\u753b\u9762\u3001\u673a\u4f4d\u548c\u8fd0\u52a8\u8bf4\u660e\u3002',
    action: '\u751f\u6210\u5206\u955c'
  },
  media_board: {
    label: '\u5408\u6210',
    accent: '#73e6dd',
    icon: '\u5408',
    title: '\u89c6\u9891\u5408\u6210',
    body: '\u6c47\u603b\u591a\u4e2a\u7d20\u6750\u548c\u7247\u6bb5\uff0c\u5f62\u6210\u53ef\u9884\u89c8\u3001\u53ef\u5bfc\u51fa\u7684\u6210\u7247\u7ed3\u679c\u3002',
    action: '\u5f00\u59cb\u5408\u6210'
  },
  agent_node: {
    label: 'Agent',
    accent: '#c9f36f',
    icon: '智',
    title: 'Agent 节点',
    body: '读取连接的文本、素材和生成节点，提出可审阅、可批准、可撤销的画布创作建议。',
    action: '运行 Agent'
  }
}

const route = useRoute()
const router = useRouter()
const canvasStore = useCanvasStore()
const projectStore = useProjectStore()
const projectTitle = ref(copy.untitled)
const saveStatus = ref('idle')
const lastSaveError = ref('')
const canvasFrame = ref(null)
const deleteKeySink = ref(null)
const uploadInput = ref(null)
const referenceUploadInput = ref(null)
const publishForm = reactive({
  title: '',
  description: '',
  tagsText: '',
  coverUrl: ''
})
const publishDialog = reactive({
  visible: false,
  submitting: false,
  error: '',
  publicationId: ''
})
const agentProfiles = [
  { id: 'auto', label: '自动派发（推荐）' },
  { id: 'canvas_agent', label: '画布协作 Agent' },
  { id: 'story_director', label: '故事发展 Agent' },
  { id: 'storyboard_director', label: '分镜导演 Agent' },
  { id: 'prompt_polisher', label: 'Prompt 精修 Agent' },
  { id: 'consistency_checker', label: '一致性检查 Agent' },
  { id: 'production_planner', label: '制片调度 Agent' }
]
const agentStarterTemplates = [
  {
    name: '角色设定师',
    description: '提取角色、外观、道具和关系，形成可继续生成的角色设定。',
    profileKey: 'custom_agent',
    rolePrompt: '你是漫剧角色设定 Agent，只处理角色、服装、道具和关系设定，输出能写入文本节点的结构化设定。',
    useCases: ['角色提取', '道具设定', '角色一致性'],
    inputTypes: ['text', 'image'],
    outputTypes: ['note', 'image_prompt'],
    tools: ['read_canvas', 'propose_canvas_patch']
  },
  {
    name: '分镜规划师',
    description: '把故事或选区拆成镜头计划、首帧图片和视频链路。',
    profileKey: 'storyboard_director',
    rolePrompt: '你是分镜规划 Agent，优先输出镜号、景别、动作、情绪、画面提示词和下游生成链路。',
    useCases: ['分镜拆解', '首帧规划', '视频链路'],
    inputTypes: ['text', 'image'],
    outputTypes: ['storyboard', 'image', 'video'],
    tools: ['read_canvas', 'propose_canvas_patch']
  },
  {
    name: 'Prompt 精修师',
    description: '把口语化描述改写成适合图片和视频生成的提示词。',
    profileKey: 'prompt_polisher',
    rolePrompt: '你是 Prompt 精修 Agent，只输出可直接用于生成节点的提示词和必要的约束说明。',
    useCases: ['提示词润色', '图生图描述', '视频动作描述'],
    inputTypes: ['text'],
    outputTypes: ['note'],
    tools: ['read_canvas', 'propose_canvas_patch']
  }
]
const agentModelOptions = [
  { id: 'deepseek-v4-flash', label: 'DeepSeek v4 Flash' },
  { id: 'deepseek-v4-pro', label: 'DeepSeek v4 Pro' }
]
const agentPanel = reactive({
  visible: true,
  advancedOpen: false,
  profile: 'auto',
  modelCode: 'deepseek-v4-flash',
  sessionId: '',
  input: '',
  busy: false,
  error: '',
  targetNodeId: '',
  sourceSurface: 'panel',
  pendingAction: null,
  activeRun: null,
  runId: '',
  runs: [],
  loadingRuns: false,
  confirmingCost: false,
  messages: [],
  templates: [],
  history: [],
  loadingTemplates: false,
  loadingHistory: false,
  agentEditorOpen: false,
  editingAgentId: '',
  agentForm: {
    name: '',
    description: '',
    modelCode: 'deepseek-v4-flash',
    rolePrompt: '',
    useCasesText: '',
    inputTypesText: '',
    outputTypesText: '',
    toolsText: 'read_canvas, propose_canvas_patch'
  }
})
const textNodeComposer = reactive({
  input: '',
  modelCode: 'deepseek-v4-flash',
  busy: false,
  error: ''
})
const AGENT_PANEL_VISIBILITY_STORAGE_KEY = 'sluvo_agent_panel_visible'
const referenceUploadAccept = ref('image/*')
const referenceUploadTargetSlot = ref('')
const directNodeElements = new Map()
const directPromptEditorElements = new Map()
const directPromptEditorSignatures = new Map()
let previousDocumentKeydown = null
let previousWindowKeydown = null
let frameResizeObserver = null
let uploadTimer = null
let autoSaveTimer = null
let suppressCanvasSaveScheduling = false
let suppressAgentSelectionWatch = false
const imageGenerationTimers = new Map()
const videoGenerationTimers = new Map()
const videoEstimateTimers = new Map()
const audioGenerationTimers = new Map()
const audioEstimateTimers = new Map()
const uploadFileMap = new Map()
const localUploadPreviewUrls = new Map()
const activeUploadSignatures = new Map()
const uploadSignatureByNodeId = new Map()
let uploadDialogOpening = false
let lastUploadSelection = { signature: '', at: 0 }
let lastClipboardImagePasteAt = 0
let clipboardPasteFallbackTimer = null
let undoShortcutLocked = false
let lastUndoShortcutAt = 0
let directPortLayoutRaf = 0
const promptEditorSelection = { nodeId: '', range: null }
const nodes = ref([])
const edges = ref([])
const directNodes = ref([])
const directEdges = ref([])
const activeCanvas = ref(null)
const nodeRevisionMap = ref({})
const edgeRevisionMap = ref({})
const isHydratingCanvas = ref(false)
const saveAfterHydration = ref(false)
const saveAfterUploads = ref(false)
const activeTextEditNodeId = ref('')
const saveAfterTextEdit = ref(false)
const isSavingCanvas = ref(false)
const saveAfterCurrentSave = ref(false)
const saveAfterActiveInteraction = ref(false)
const directPortLayoutRevision = ref(0)
const selectedDirectNodeIds = ref([])
const focusedDirectNodeId = ref('')
const activeDirectNodeId = ref('')
const activeVideoSettingsNodeId = ref('')
const lastTouchedDirectNodeId = ref('')
const gridVisible = ref(true)
const snapEnabled = ref(true)
const minimapVisible = ref(false)
const helpVisible = ref(false)
const activeRailPanel = ref('')
const activeAssetLibrary = ref('assets')
const activeAssetTab = ref('全部')
const activeHistoryTab = ref('image')
const historyBatchMode = ref(false)
const historySortAscending = ref(false)
const pendingUploadFlowPosition = ref(null)
const replacingUploadNodeId = ref('')
const referenceUploadTargetNodeId = ref('')
const toastMessage = ref('')
const historyStack = ref([])
const redoStack = ref([])
const clipboardNodes = ref([])
const clipboardEdges = ref([])
const suppressHistory = ref(false)
const spacePanning = ref(false)
const selectedEdgeIds = ref([])
const canvasActivated = ref(false)
const suppressNextPaneClick = ref(false)
const addMenu = reactive({
  visible: false,
  screen: { x: 404, y: 76 },
  originScreen: { x: 520, y: 280 },
  flow: { x: 520, y: 280 }
})
const referenceMenu = reactive({
  visible: false,
  sourceId: '',
  sourceHandle: 'out',
  screen: { x: 0, y: 0 },
  flow: { x: 0, y: 0 }
})
const connectionDraft = reactive({
  active: false,
  sourceId: '',
  sourceHandle: 'out',
  edgeCount: 0
})
const contextMenu = reactive({
  visible: false,
  screen: { x: 0, y: 0 },
  flow: { x: 0, y: 0 }
})
const selectionBox = reactive({
  active: false,
  start: { x: 0, y: 0 },
  current: { x: 0, y: 0 }
})
const directDrag = reactive({
  active: false,
  startScreen: { x: 0, y: 0 },
  originals: []
})
const imagePreview = reactive({
  visible: false,
  url: '',
  alt: ''
})
const audioVoicePicker = reactive({
  visible: false,
  nodeId: '',
  tab: 'library',
  query: ''
})
const audioVoiceTabs = [
  { id: 'library', label: '音色库' },
  { id: 'mine', label: '我的音色' },
  { id: 'favorites', label: '收藏音色' }
]
const AUDIO_VOICE_FAVORITES_STORAGE_KEY = 'sluvo_audio_voice_favorites'
const audioFavoriteVoiceIds = ref(new Set())
const referenceDrag = reactive({
  nodeId: '',
  referenceId: ''
})
const directConnection = reactive({
  active: false,
  sourceId: '',
  sourceSide: 'right',
  start: { x: 0, y: 0 },
  current: { x: 0, y: 0 }
})
const pendingDirectConnection = reactive({
  sourceId: '',
  sourceSide: 'right',
  start: { x: 0, y: 0 },
  point: { x: 0, y: 0 }
})
const frameSize = reactive({
  width: 1,
  height: 1
})

const assetTabs = ['全部', '人物', '场景', '物品', '风格', '音效', '其他']
const historyTabs = [
  { id: 'image', label: '图片历史(0)' },
  { id: 'video', label: '视频历史(0)' },
  { id: 'audio', label: '音频历史(0)' }
]
const fallbackImagePricingRules = {
  'nano-banana-pro': { '1k': 9, '2k': 11, '4k': 16 },
  'nano-banana-2': { '1k': 9, '2k': 11, '4k': 13 },
  'nano-banana-2-低价版': { '1k': 2, '2k': 2, '4k': 3 },
  'nano-banana-2-low': { '1k': 2, '2k': 2, '4k': 3 },
  'nano-banana-pro-低价版': { '1k': 5, '2k': 5, '4k': 6 },
  'nano-banana-pro-low': { '1k': 5, '2k': 5, '4k': 6 },
  'gpt-image-2-fast': { fixed: 3 },
  'gpt-image-2': { '1k': 7, '2k': 10, '4k': 15 }
}
const fallbackImageAspectRatioOptions = ['16:9', '9:16', '1:1', '4:3', '3:4', '3:2', '2:3', '5:4', '4:5', '21:9']
const fallbackImageResolutionOptions = [
  { id: '1k', label: '1K' },
  { id: '2k', label: '2K' },
  { id: '4k', label: '4K' }
]
const fallbackImageQualityOptions = [
  { id: 'low', label: 'Low' },
  { id: 'medium', label: 'Medium' },
  { id: 'high', label: 'High' }
]
const fallbackImageModelOptions = [
  { id: 'nano-banana-pro', label: 'nano-banana-pro' },
  { id: 'nano-banana-2', label: 'nano-banana-2' },
  { id: 'nano-banana-2-low', label: 'nano-banana-2-低价版' },
  { id: 'nano-banana-pro-low', label: 'nano-banana-pro-低价版' },
  { id: 'gpt-image-2-fast', label: 'gpt-image-2-fast' },
  { id: 'gpt-image-2', label: 'gpt-image-2' }
].map((model) => ({
  ...model,
  features: buildFallbackImageFeatures(model.id),
  pricingRules: buildFallbackImagePricingRules(model.id)
}))
const imageModelOptions = ref([...fallbackImageModelOptions])
const imageAspectRatioOptions = ref([...fallbackImageAspectRatioOptions])
const imageResolutionOptions = ref([...fallbackImageResolutionOptions])
const fallbackVideoAspectRatioOptions = ['16:9', '9:16', '1:1', '4:3', '3:4', '21:9', 'adaptive'].map((ratio) => ({ id: ratio, label: ratio }))
const fallbackVideoResolutionOptions = ['480p', '720p', '1080p', '4k'].map((resolution) => ({ id: resolution, label: resolution.toUpperCase() }))
const fallbackVideoDurationOptions = [4, 5, 8, 10].map((duration) => ({ id: String(duration), label: `${duration}s` }))
const fallbackVideoQualityModeOptions = [
  { id: 'std', label: 'Std' },
  { id: 'pro', label: 'Pro' }
]
const fallbackVideoMotionStrengthOptions = [
  { id: 'auto', label: 'Auto' },
  { id: 'low', label: 'Low' },
  { id: 'medium', label: 'Medium' },
  { id: 'high', label: 'High' }
]
const startEndFrameSlots = [
  { id: 'first', label: '首帧' },
  { id: 'last', label: '尾帧' }
]
const fallbackVideoModelOptions = [
  { id: 'seedance_20_fast', label: 'Seedance 2.0 Fast', startPoints: 65 },
  { id: 'seedance_20', label: 'Seedance 2.0', startPoints: 90 },
  { id: 'vidu_q3_turbo', label: 'Vidu Q3 Turbo', startPoints: 20 },
  { id: 'vidu_q3_pro', label: 'Vidu Q3 Pro', startPoints: 10 },
  { id: 'kling_o3_std', label: 'Kling O3 Std', startPoints: 26 },
  { id: 'kling_o3_pro', label: 'Kling O3 Pro', startPoints: 35 },
  { id: 'veo_31_fast_official', label: 'Veo 3.1 Fast Official', startPoints: 30 },
  { id: 'veo_31_pro_official', label: 'Veo 3.1 Pro Official', startPoints: 80 }
].map((model) => ({
  ...model,
  defaultGenerationType: 'text_to_video',
  features: buildFallbackVideoFeatures(model.id)
}))
const videoModelOptions = ref([...fallbackVideoModelOptions])
const fallbackAudioAbilityOptions = [
  {
    id: 'realtime_dubbing',
    label: '实时配音',
    defaultTier: 'hd',
    tiers: [
      { id: 'hd', label: 'Minimax-speech-2.8-hd', modelCode: 'speech-2.8-hd', pointsPer10k: 53 },
      { id: 'turbo', label: 'Minimax-speech-2.8-turbo', modelCode: 'speech-2.8-turbo', pointsPer10k: 30 }
    ]
  },
  {
    id: 'long_narration',
    label: '长文本旁白',
    defaultTier: 'hd',
    tiers: [
      { id: 'hd', label: 'Minimax-speech-2.8-hd', modelCode: 'speech-2.8-hd', pointsPer10k: 53 },
      { id: 'turbo', label: 'Minimax-speech-2.8-turbo', modelCode: 'speech-2.8-turbo', pointsPer10k: 30 }
    ]
  }
]
const audioAbilityOptions = ref([...fallbackAudioAbilityOptions])
const audioVoiceOptions = ref([])
const audioEmotionOptions = [
  { value: 'happy', label: '开心' },
  { value: 'sad', label: '伤感' },
  { value: 'angry', label: '愤怒' },
  { value: 'calm', label: '平静' },
  { value: 'fluent', label: '流畅' },
  { value: 'whisper', label: '耳语' }
]
const audioPauseOptions = [
  { value: '0.25', label: '0.25s', text: '<#0.25#>' },
  { value: '0.5', label: '0.5s', text: '<#0.5#>' },
  { value: '1.0', label: '1.0s', text: '<#1.0#>' },
  { value: '1.5', label: '1.5s', text: '<#1.5#>' }
]
const audioInterjectionOptions = ['笑声', '轻笑', '咳嗽', '清嗓子', '正常换气', '喘气']
const librarySourceTabs = ['Sluvo', 'Sluvo生成器', 'WebUI', 'ComfyUI', 'AI应用']
const libraryTypeTabs = ['图片', '视频', '音频']
const libraryPicker = reactive({
  visible: false,
  source: 'Sluvo',
  type: '图片',
  selected: 0
})

const nodeTypes = {
  workflowNode: WorkflowNode,
  groupFrame: WorkflowNode
}
const edgeTypes = {
  workflow: WorkflowEdge
}
const defaultEdgeOptions = {
  type: 'workflow',
  markerEnd: MarkerType.ArrowClosed,
  style: {
    stroke: '#777f8e',
    strokeWidth: 1.6
  },
  labelBgStyle: { fill: '#252525', color: '#cfcfcf' },
  labelBgBorderRadius: 8,
  labelBgPadding: [8, 4]
}

const {
  fitView,
  getViewport,
  panBy,
  screenToFlowCoordinate,
  setViewport,
  viewport,
  zoomIn,
  zoomOut,
  zoomTo
} = useVueFlow()

const canUndo = computed(() => historyStack.value.length > 0)
const canRedo = computed(() => redoStack.value.length > 0)
const zoomLabel = computed(() => `${Math.round((viewport.value?.zoom || 1) * 100)}%`)
const isCompactCanvas = computed(() => frameSize.width <= 900)
const pendingAgentActionCount = computed(() => (agentPanel.pendingAction ? 1 : 0) + (agentPanel.activeRun?.status === 'waiting_cost_confirmation' ? 1 : 0))
const hasAgentTemplateSelection = computed(() => Boolean(getSelectedAgentTemplate()))
const agentSessionHistory = computed(() => agentPanel.history.slice(0, 8))
const agentRunHistory = computed(() => agentPanel.runs.slice(0, 8))
const showStarterStrip = computed(
  () =>
    !canvasActivated.value &&
    nodes.value.length === 0 &&
    directNodes.value.length === 0 &&
    !addMenu.visible &&
    !activeRailPanel.value
)
const directLayerStyle = computed(() => {
  const zoom = Number(viewport.value?.zoom || 1)
  const safeZoom = zoom > 0 ? zoom : 1
  return {
    '--direct-viewport-zoom': safeZoom,
    '--direct-fixed-panel-scale': 1 / safeZoom,
    transform: `translate3d(${viewport.value?.x || 0}px, ${viewport.value?.y || 0}px, 0) scale(${safeZoom})`
  }
})
const selectionBoxStyle = computed(() => {
  const rect = getSelectionRect()
  return {
    left: `${rect.x}px`,
    top: `${rect.y}px`,
    width: `${rect.width}px`,
    height: `${rect.height}px`
  }
})
const selectedDirectNodes = computed(() => directNodes.value.filter((node) => selectedDirectNodeIds.value.includes(node.id)))
const selectedDirectGroupId = computed(() => {
  const groups = [...new Set(selectedDirectNodes.value.map((node) => node.groupId).filter(Boolean))]
  if (groups.length !== 1) return ''
  const groupId = groups[0]
  const groupMemberIds = directNodes.value.filter((node) => node.groupId === groupId).map((node) => node.id)
  if (groupMemberIds.length < 2) return ''
  const selectedIds = new Set(selectedDirectNodeIds.value)
  return groupMemberIds.every((id) => selectedIds.has(id)) ? groupId : ''
})
const directNodeGroups = computed(() => {
  const groups = new Map()
  directNodes.value.forEach((node) => {
    if (!node.groupId) return
    if (!groups.has(node.groupId)) {
      groups.set(node.groupId, {
        id: node.groupId,
        title: node.groupTitle || '分组',
        nodes: []
      })
    }
    groups.get(node.groupId).nodes.push(node)
  })

  return [...groups.values()]
    .filter((group) => group.nodes.length >= 2)
    .map((group) => {
      const bounds = getDirectNodeFlowBounds(group.nodes)
      return {
        ...group,
        title: group.title || `分组 ${group.nodes.length} 个节点`,
        count: group.nodes.length,
        bounds
      }
    })
})
const directGroupToolbar = computed(() => {
  if (selectionBox.active || directDrag.active || directConnection.active) return { visible: false }
  if (selectedDirectGroupId.value && selectedDirectNodes.value.every((node) => node.groupId === selectedDirectGroupId.value)) {
    return { visible: true, mode: 'ungroup' }
  }
  if (selectedDirectNodes.value.length >= 2) return { visible: true, mode: 'group' }
  return { visible: false }
})
const directSelectionFrame = computed(() => {
  const grouped = Boolean(selectedDirectGroupId.value && selectedDirectNodes.value.every((node) => node.groupId === selectedDirectGroupId.value))
  const visible = !grouped && !selectionBox.active && !directConnection.active && selectedDirectNodes.value.length >= 2
  return {
    visible,
    grouped
  }
})
const directSelectionFrameStyle = computed(() => {
  const bounds = getSelectedDirectScreenBounds()
  if (!bounds) return {}
  const padding = 24
  return {
    left: `${bounds.x - padding}px`,
    top: `${bounds.y - padding}px`,
    width: `${bounds.width + padding * 2}px`,
    height: `${bounds.height + padding * 2}px`
  }
})
const directGroupToolbarStyle = computed(() => {
  const bounds = getSelectedDirectScreenBounds()
  if (!bounds) return {}
  const width = directGroupToolbar.value.mode === 'group' ? 172 : 96
  const padding = 24
  return {
    left: `${Math.max(12, bounds.x + bounds.width / 2 - width / 2)}px`,
    top: `${Math.max(12, bounds.y - padding - 58)}px`
  }
})
const contextMenuStyle = computed(() => ({
  left: `${contextMenu.screen.x}px`,
  top: `${contextMenu.screen.y}px`
}))
const activeHistoryLabel = computed(() => {
  const labels = {
    image: '暂无图片历史记录',
    video: '暂无视频历史记录',
    audio: '暂无音频历史记录'
  }
  return labels[activeHistoryTab.value] || '暂无历史记录'
})
const filteredAudioVoiceOptions = computed(() => {
  const query = audioVoicePicker.query.trim().toLowerCase()
  return audioVoiceOptions.value.filter((voice) => {
    if (audioVoicePicker.tab === 'mine' && !isAudioVoiceMine(voice)) return false
    if (audioVoicePicker.tab === 'favorites' && !isAudioVoiceFavorite(voice)) return false
    if (!query) return true
    return [voice.label, voice.voiceId, voice.categoryLabel, voice.styleLabel, voice.description, voice.searchText]
      .filter(Boolean)
      .some((value) => String(value).toLowerCase().includes(query))
  })
})
const minimapItems = computed(() => {
  const vueNodes = nodes.value.map((node) => {
    const size = getWorkflowNodeSize(node)
    return {
      id: node.id,
      kind: node.data?.nodeType || 'node',
      x: node.position?.x || 0,
      y: node.position?.y || 0,
      width: size.width,
      height: size.height
    }
  })
  const directItems = directNodes.value.map((node) => {
    const size = getDirectNodeSize(node.type)
    return {
      id: node.id,
      kind: node.type,
      x: node.x,
      y: node.y,
      width: size.width,
      height: size.height
    }
  })

  return [...vueNodes, ...directItems]
})
const visibleFlowRect = computed(() => {
  const zoom = viewport.value?.zoom || 1
  return {
    x: -((viewport.value?.x || 0) / zoom),
    y: -((viewport.value?.y || 0) / zoom),
    width: frameSize.width / zoom,
    height: frameSize.height / zoom
  }
})
const minimapBounds = computed(() => {
  const rects = [...minimapItems.value, visibleFlowRect.value]
  const left = Math.min(...rects.map((rect) => rect.x))
  const top = Math.min(...rects.map((rect) => rect.y))
  const right = Math.max(...rects.map((rect) => rect.x + rect.width))
  const bottom = Math.max(...rects.map((rect) => rect.y + rect.height))
  const padding = 120

  return {
    x: left - padding,
    y: top - padding,
    width: Math.max(right - left + padding * 2, 1),
    height: Math.max(bottom - top + padding * 2, 1)
  }
})
const minimapRects = computed(() => minimapItems.value.map((item) => ({ ...item, ...projectMinimapRect(item) })))
const minimapViewportRect = computed(() => projectMinimapRect(visibleFlowRect.value))

watch(
  nodes,
  () => {
    if (nodes.value.length === 0 && directNodes.value.length === 0) {
      canvasActivated.value = false
    }
    syncSelectionFromNodes()
    scheduleCanvasSave()
  },
  { deep: true }
)

watch(
  directNodes,
  () => {
    if (nodes.value.length === 0 && directNodes.value.length === 0) {
      canvasActivated.value = false
    }
    scheduleDirectPortLayoutRefresh()
    scheduleCanvasSave()
  },
  { deep: true }
)

watch(
  edges,
  () => {
    selectedEdgeIds.value = edges.value.filter((edge) => edge.selected).map((edge) => edge.id)
  },
  { deep: true }
)

watch(
  directEdges,
  () => {
    scheduleCanvasSave()
  },
  { deep: true }
)

watch(projectTitle, () => {
  scheduleCanvasSave()
})

watch(
  () => [agentPanel.profile, agentPanel.modelCode],
  (next, previous = []) => {
    if (suppressAgentSelectionWatch) return
    agentPanel.sessionId = ''
    agentPanel.runId = ''
    agentPanel.activeRun = null
    agentPanel.pendingAction = null
    agentPanel.targetNodeId = ''
    const template = getSelectedAgentTemplate()
    if (template?.modelCode && next[0] !== previous[0]) agentPanel.modelCode = template.modelCode
  }
)

watch(
  () => agentPanel.visible,
  (visible) => {
    if (typeof window !== 'undefined') {
      window.localStorage.setItem(AGENT_PANEL_VISIBILITY_STORAGE_KEY, visible ? 'true' : 'false')
    }
  }
)

watch(
  () => route.params.projectId,
  () => {
    loadProjectCanvas()
  }
)

watch(
  () => [viewport.value?.x, viewport.value?.y, viewport.value?.zoom],
  () => {
    syncPendingReferenceMenuScreen()
  }
)

onMounted(() => {
  previousDocumentKeydown = document.onkeydown
  previousWindowKeydown = window.onkeydown
  const storedAgentPanelVisible = window.localStorage.getItem(AGENT_PANEL_VISIBILITY_STORAGE_KEY)
  if (storedAgentPanelVisible === 'false') {
    agentPanel.visible = false
  }
  loadAudioVoiceFavorites()
  document.onkeydown = handleGlobalDeleteShortcut
  window.onkeydown = handleGlobalDeleteShortcut
  nextTick(() => {
    deleteKeySink.value?.addEventListener('keydown', handleDeleteSinkNative, true)
    deleteKeySink.value?.addEventListener('keyup', handleDeleteSinkNative, true)
  })
  document.addEventListener('keydown', handleDocumentKeydown, true)
  document.addEventListener('keyup', handleDocumentKeyup, true)
  document.addEventListener('paste', handleWindowPaste, true)
  window.addEventListener('keydown', handleWindowKeyEvent, true)
  window.addEventListener('keyup', handleWindowKeyEvent, true)
  window.addEventListener('keydown', handleKeydown)
  window.addEventListener('keyup', handleKeyup)
  window.addEventListener('paste', handleWindowPaste)
  window.addEventListener('pointermove', handleWindowPointerMove)
  window.addEventListener('pointerup', handleWindowPointerUp)
  window.addEventListener('mousemove', handleWindowPointerMove)
  window.addEventListener('mouseup', handleWindowPointerUp)
  window.addEventListener('mouseleave', resetHoverEffects)
  window.addEventListener('beforeunload', handleBeforeUnload)
  window.addEventListener('pagehide', flushCanvasSaveOnPageHide)
  document.addEventListener('visibilitychange', handleVisibilityChange)
  updateFrameSize()
  loadImageGenerationCatalog()
  loadVideoGenerationCatalog()
  loadAudioGenerationCatalog()
  loadAudioVoiceAssets()
  loadProjectCanvas()
  if (typeof ResizeObserver !== 'undefined' && canvasFrame.value) {
    frameResizeObserver = new ResizeObserver(updateFrameSize)
    frameResizeObserver.observe(canvasFrame.value)
  }
})

onBeforeRouteLeave(() => flushCanvasSaveBeforeLeaving())
onBeforeRouteUpdate(() => flushCanvasSaveBeforeLeaving())

onBeforeUnmount(() => {
  deleteKeySink.value?.removeEventListener('keydown', handleDeleteSinkNative, true)
  deleteKeySink.value?.removeEventListener('keyup', handleDeleteSinkNative, true)
  document.onkeydown = previousDocumentKeydown
  window.onkeydown = previousWindowKeydown
  document.removeEventListener('keydown', handleDocumentKeydown, true)
  document.removeEventListener('keyup', handleDocumentKeyup, true)
  document.removeEventListener('paste', handleWindowPaste, true)
  window.removeEventListener('keydown', handleWindowKeyEvent, true)
  window.removeEventListener('keyup', handleWindowKeyEvent, true)
  window.removeEventListener('keydown', handleKeydown)
  window.removeEventListener('keyup', handleKeyup)
  window.removeEventListener('paste', handleWindowPaste)
  window.removeEventListener('pointermove', handleWindowPointerMove)
  window.removeEventListener('pointerup', handleWindowPointerUp)
  window.removeEventListener('mousemove', handleWindowPointerMove)
  window.removeEventListener('mouseup', handleWindowPointerUp)
  window.removeEventListener('mouseleave', resetHoverEffects)
  window.removeEventListener('beforeunload', handleBeforeUnload)
  window.removeEventListener('pagehide', flushCanvasSaveOnPageHide)
  document.removeEventListener('visibilitychange', handleVisibilityChange)
  frameResizeObserver?.disconnect()
  window.clearTimeout(autoSaveTimer)
  window.clearInterval(uploadTimer)
  window.clearTimeout(clipboardPasteFallbackTimer)
  window.cancelAnimationFrame(directPortLayoutRaf)
  clearLocalPreviewUrls()
  clearImageGenerationTimers()
  clearVideoGenerationTimers()
  clearVideoEstimateTimers()
  clearAudioGenerationTimers()
  clearAudioEstimateTimers()
  resetHoverEffects()
})

async function loadProjectCanvas() {
  const projectId = String(route.params.projectId || '')
  if (!projectId) return

  saveStatus.value = 'loading'
  isHydratingCanvas.value = true
  try {
    const workspace = await fetchSluvoProjectCanvas(projectId)
    projectStore.setWorkspace(workspace)
    hydrateCanvasWorkspace(workspace)
    await Promise.allSettled([loadAgentTemplates(), loadAgentHistory(), loadAgentRuns()])
    saveStatus.value = 'idle'
  } catch (error) {
    saveStatus.value = 'error'
    showToast(error instanceof Error ? error.message : '画布加载失败')
    if (error?.status === 401) router.push({ name: 'login', query: { redirect: route.fullPath } })
  } finally {
    nextTick(() => {
      isHydratingCanvas.value = false
      if (saveAfterHydration.value) {
        saveAfterHydration.value = false
        scheduleCanvasSave(220)
      }
    })
  }
}

function hydrateCanvasWorkspace(workspace, options = {}) {
  activeCanvas.value = workspace?.canvas || null
  projectTitle.value = getWorkspaceTitle(workspace)
  nodeRevisionMap.value = Object.fromEntries((workspace?.nodes || []).map((node) => [node.id, node.revision || 1]))
  edgeRevisionMap.value = Object.fromEntries((workspace?.edges || []).map((edge) => [edge.id, edge.revision || 1]))
  nodes.value = []
  edges.value = []
  directNodes.value = (workspace?.nodes || []).map(mapBackendNodeToDirectNode)
  directEdges.value = (workspace?.edges || [])
    .map(mapBackendEdgeToDirectEdge)
    .filter((edge) => isDirectEndpointAvailable(edge.sourceId) && isDirectEndpointAvailable(edge.targetId))
  const directNodeCountBeforeDedupe = directNodes.value.length
  dedupeUploadedAssetNodes({ silent: true })
  if (directNodes.value.length !== directNodeCountBeforeDedupe) saveAfterHydration.value = true
  selectedDirectNodeIds.value = []
  selectedEdgeIds.value = []
  canvasStore.clearSelection()
  saveAfterUploads.value = false
  canvasActivated.value = directNodes.value.length > 0 || directEdges.value.length > 0
  if (!options.preserveHistory) {
    historyStack.value = []
    redoStack.value = []
  }
  const nextViewport = workspace?.canvas?.viewport
  if (nextViewport && Number.isFinite(Number(nextViewport.zoom))) {
    setViewport(
      {
        x: Number(nextViewport.x || 0),
        y: Number(nextViewport.y || 0),
        zoom: Number(nextViewport.zoom || 1)
      },
      { duration: 0 }
    )
  }
}

function getWorkspaceTitle(workspace) {
  const canvasTitle = String(workspace?.canvas?.title || '').trim()
  if (canvasTitle && canvasTitle !== 'Main Canvas') return canvasTitle
  return workspace?.project?.title || canvasTitle || copy.untitled
}

function openPublishDialog() {
  const project = projectStore.activeProject || {}
  const settings = project.settings || {}
  publishForm.title = projectTitle.value || project.title || copy.untitled
  publishForm.description = project.description || ''
  publishForm.tagsText = Array.isArray(settings.communityTags) ? settings.communityTags.join(', ') : ''
  publishForm.coverUrl = project.coverUrl || project.firstImageUrl || ''
  publishDialog.publicationId = project.communityPublication?.id || settings.communityPublicationId || ''
  publishDialog.error = ''
  publishDialog.visible = true
}

function closePublishDialog() {
  if (publishDialog.submitting) return
  publishDialog.visible = false
  publishDialog.error = ''
}

async function publishCurrentCanvas() {
  const projectId = projectStore.activeProject?.id || String(route.params.projectId || '')
  if (!projectId || publishDialog.submitting) return
  publishDialog.submitting = true
  publishDialog.error = ''
  try {
    const canContinue = await saveBeforeCriticalCanvasAction()
    if (!canContinue) return
    const payload = await publishSluvoProjectToCommunity(projectId, {
      title: publishForm.title.trim() || projectTitle.value || copy.untitled,
      description: publishForm.description.trim() || null,
      tags: parsePublishTags(publishForm.tagsText),
      coverUrl: publishForm.coverUrl.trim() || null
    })
    const publication = payload?.publication
    publishDialog.publicationId = publication?.id || ''
    publishDialog.visible = false
    showToast('已发布到开放画布社区')
  } catch (error) {
    publishDialog.error = error instanceof Error ? error.message : '发布失败，请稍后重试'
    if (error?.status === 401) router.push({ name: 'login', query: { redirect: route.fullPath } })
  } finally {
    publishDialog.submitting = false
  }
}

function toggleAgentPanel() {
  setAgentPanelVisible(!agentPanel.visible)
}

function setAgentPanelVisible(visible) {
  agentPanel.visible = visible
  if (agentPanel.visible) {
    addMenu.visible = false
    referenceMenu.visible = false
    contextMenu.visible = false
  }
}

function serializeAgentContextNode(node) {
  return {
    id: node.id,
    clientId: node.clientId || node.id,
    title: node.title,
    nodeType: mapDirectTypeToBackendType(node.type),
    directType: node.type,
    position: { x: node.x, y: node.y },
    prompt: node.prompt || '',
    status: node.generationStatus || 'idle',
    media: node.media ? { kind: node.media.kind, name: node.media.name, url: node.media.url } : null,
    agentTemplateId: node.agentTemplateId || '',
    agentName: node.agentName || ''
  }
}

function buildAgentContextSnapshot(options = {}) {
  const targetNode = options.targetNode || null
  const sourceSurface = options.sourceSurface || 'panel'
  const contextIds = options.contextNodeIds
    ? new Set(options.contextNodeIds)
    : new Set(selectedDirectNodeIds.value)
  const selectedNodes = directNodes.value
    .filter((node) => contextIds.has(node.id))
    .map(serializeAgentContextNode)
  const agentTemplateId = options.agentTemplateId ?? targetNode?.agentTemplateId ?? getSelectedAgentTemplate()?.id ?? ''
  const agentName = options.agentName ?? targetNode?.agentName ?? getAgentProfileLabel(agentTemplateId || agentPanel.profile)
  const selectedEdgeIds = new Set(directEdges.value
    .filter((edge) => contextIds.has(edge.sourceId) || contextIds.has(edge.targetId) || edge.targetId === targetNode?.id)
    .map((edge) => edge.id))
  const relatedEdges = directEdges.value
    .filter((edge) => selectedEdgeIds.has(edge.id))
    .map((edge) => ({
      id: edge.id,
      sourceNodeId: edge.sourceId,
      targetNodeId: edge.targetId,
      sourcePortId: edge.sourcePortId,
      targetPortId: edge.targetPortId
    }))
  return {
    project: {
      id: projectStore.activeProject?.id || String(route.params.projectId || ''),
      title: projectTitle.value
    },
    canvas: {
      id: activeCanvas.value?.id || '',
      revision: activeCanvas.value?.revision || 1
    },
    selectedNodes,
    relatedEdges,
    targetNode: targetNode ? serializeAgentContextNode(targetNode) : null,
    targetNodeId: targetNode?.id || '',
    sourceSurface,
    agentProfile: options.agentProfile || agentTemplateId || agentPanel.profile,
    agentTemplateId,
    agentName,
    modelCode: options.modelCode || targetNode?.agentModelCode || agentPanel.modelCode,
    agentModelCode: options.modelCode || targetNode?.agentModelCode || agentPanel.modelCode
  }
}

async function ensureAgentSession(options = {}) {
  if (!options.forceNew && agentPanel.sessionId) return agentPanel.sessionId
  const projectId = projectStore.activeProject?.id || String(route.params.projectId || '')
  if (!projectId) throw new Error('缺少项目 ID')
  const targetNode = options.targetNode || null
  const contextSnapshot = buildAgentContextSnapshot(options)
  const response = await createSluvoAgentSession(projectId, {
    canvasId: activeCanvas.value?.id || null,
    targetNodeId: targetNode?.id || null,
    title: targetNode?.title || contextSnapshot.agentName || '创作总监',
    agentProfile: contextSnapshot.agentTemplateId || contextSnapshot.agentProfile || agentPanel.profile,
    modelCode: contextSnapshot.modelCode || agentPanel.modelCode,
    mode: 'semi_auto',
    contextSnapshot
  })
  agentPanel.sessionId = response?.session?.id || ''
  agentPanel.targetNodeId = targetNode?.id || ''
  agentPanel.sourceSurface = contextSnapshot.sourceSurface || 'panel'
  return agentPanel.sessionId
}

async function sendAgentPrompt() {
  const content = agentPanel.input.trim()
  if (!content || agentPanel.busy) return
  if (agentPanel.runId && agentPanel.activeRun) {
    await continueAgentRun(content)
  } else {
    await runAgentPrompt(content)
  }
}

async function startAgentWithSelection(content) {
  agentPanel.input = content
  await runAgentPrompt(content)
}

async function runAgentPrompt(content, options = {}) {
  setAgentPanelVisible(true)
  agentPanel.busy = true
  agentPanel.error = ''
  agentPanel.pendingAction = null
  agentPanel.targetNodeId = options.targetNode?.id || ''
  agentPanel.sourceSurface = options.sourceSurface || 'panel'
  try {
    await saveCanvasNow()
    const resolvedOptions = options.targetNode ? { ...options, targetNode: resolveLatestDirectNode(options.targetNode) || options.targetNode } : options
    const contextSnapshot = buildAgentContextSnapshot(resolvedOptions)
    const projectId = projectStore.activeProject?.id || String(route.params.projectId || '')
    const response = await createSluvoAgentRun(projectId, {
      canvasId: activeCanvas.value?.id || null,
      targetNodeId: resolvedOptions.targetNode?.id || null,
      goal: content,
      sourceSurface: contextSnapshot.sourceSurface,
      agentProfile: contextSnapshot.agentProfile || agentPanel.profile,
      agentTemplateId: contextSnapshot.agentTemplateId || null,
      modelCode: contextSnapshot.modelCode || agentPanel.modelCode,
      mode: 'semi_auto',
      contextSnapshot
    })
    setActiveAgentRun(response)
    await Promise.allSettled([loadAgentRuns({ restore: false }), loadAgentHistory(), loadProjectCanvas()])
    agentPanel.input = ''
  } catch (error) {
    agentPanel.error = error instanceof Error ? error.message : 'Agent Run 创建失败'
    if (error?.status === 401) router.push({ name: 'login', query: { redirect: route.fullPath } })
  } finally {
    agentPanel.busy = false
  }
}

async function continueAgentRun(content) {
  if (!agentPanel.runId || agentPanel.busy) return
  agentPanel.busy = true
  agentPanel.error = ''
  try {
    await saveCanvasNow()
    const response = await continueSluvoAgentRun(agentPanel.runId, {
      content,
      contextSnapshot: buildAgentContextSnapshot({ sourceSurface: agentPanel.sourceSurface || 'panel' })
    })
    setActiveAgentRun(response)
    await Promise.allSettled([loadAgentRuns({ restore: false }), loadProjectCanvas()])
    agentPanel.input = ''
  } catch (error) {
    agentPanel.error = error instanceof Error ? error.message : '继续补充失败'
  } finally {
    agentPanel.busy = false
  }
}

function resolveLatestDirectNode(node) {
  return directNodes.value.find((item) => item.id === node.id || (node.clientId && item.clientId === node.clientId)) || null
}

function normalizeAgentAction(action) {
  if (!action) return null
  const contextSummary = action.input?.contextSummary || {}
  return {
    ...action,
    summary: action.result?.summary || contextSummary.agentName || contextSummary.resolvedProfileLabel || contextSummary.profile || getAgentActionSummary(action.actionType)
  }
}

function getAgentActionSummary(actionType) {
  const map = {
    'agent.report': '生成检查报告节点',
    'prompt.rewrite': '生成精修提示词节点',
    'workflow.plan': '生成创作链路',
    'canvas.patch': '生成画布建议'
  }
  return map[actionType] || '生成画布建议'
}

function getAgentActionStats(action) {
  const patch = action?.patch || {}
  const nodeCount = Array.isArray(patch.nodes) ? patch.nodes.length : 0
  const edgeCount = Array.isArray(patch.edges) ? patch.edges.length : 0
  const summary = action?.input?.contextSummary || {}
  const source = summary.sourceSurface === 'node' ? 'Agent 节点' : '创作总监'
  return `${nodeCount} 个节点 · ${edgeCount} 条连线 · ${source} · ${getAgentActionStatusLabel(action.status)}`
}

function getAgentEventRoutingLabel(payload) {
  if (!payload) return ''
  const profile = payload.agentName || payload.resolvedProfileLabel || getAgentProfileLabel(payload.agentTemplateId || payload.resolvedProfile || payload.profile)
  const model = getAgentModelLabel(payload.modelCode)
  const reason = payload.routingReason || ''
  return [profile ? `主导：${profile}` : '', model, reason].filter(Boolean).join(' · ')
}

function getAgentRoutingLabel(action) {
  const summary = action?.input?.contextSummary || {}
  const profile = summary.agentName || summary.resolvedProfileLabel || getAgentProfileLabel(summary.agentTemplateId || summary.resolvedProfile || summary.profile)
  const model = getAgentModelLabel(summary.modelCode)
  const reason = summary.routingReason || ''
  return [profile ? `主导：${profile}` : '', model, reason].filter(Boolean).join(' · ')
}

function getAgentProfileLabel(profileId) {
  return agentPanel.templates.find((agent) => agent.id === profileId)?.name || agentProfiles.find((profile) => profile.id === profileId)?.label || profileId || ''
}

function getAgentModelLabel(modelCode) {
  return agentModelOptions.find((model) => model.id === modelCode)?.label || modelCode || ''
}

function getAgentActionPreviewNodes(action) {
  const nodes = Array.isArray(action?.patch?.nodes) ? action.patch.nodes : []
  return nodes.slice(0, 8).map((node, index) => ({
    key: node.id || node.clientId || node.data?.clientId || `${index}`,
    title: node.title || node.data?.title || `节点 ${index + 1}`,
    type: node.nodeType || node.data?.directType || 'node'
  }))
}

function getAgentActionPreviewEdges(action) {
  const edges = Array.isArray(action?.patch?.edges) ? action.patch.edges : []
  return edges.slice(0, 6).map((edge, index) => ({
    key: edge.id || `${edge.data?.sourceClientId || edge.sourceNodeId || 'source'}-${edge.data?.targetClientId || edge.targetNodeId || 'target'}-${index}`,
    label: edge.label || `连线 ${index + 1}`,
    type: edge.edgeType || 'reference'
  }))
}

function getAgentActionStatusLabel(status) {
  const map = {
    proposed: '待批准',
    approved: '待写入',
    running: '写入中',
    succeeded: '已写入',
    failed: '写入失败',
    cancelled: '已取消'
  }
  return map[status] || '待批准'
}

function getAgentPanelModeSummary() {
  const template = getSelectedAgentTemplate()
  const contextText = selectedDirectNodeIds.value.length > 0 ? `已带入 ${selectedDirectNodeIds.value.length} 个选区节点` : '未选择节点，将基于项目画布理解需求'
  return template ? `${template.name} · ${contextText}` : contextText
}

function getSelectedAgentTemplate() {
  return agentPanel.templates.find((item) => item.id === agentPanel.profile) || null
}

function getAgentHistorySummary(item) {
  const action = item?.pendingAction || item?.latestAction
  const event = item?.events?.at?.(-1)
  const status = action ? getAgentActionStatusLabel(action.status) : '无提案'
  const count = action ? getAgentActionStats(action).split(' · ').slice(0, 2).join(' · ') : event?.payload?.content || '暂无消息'
  return `${status} · ${count}`
}

function setActiveAgentRun(timeline) {
  if (!timeline?.run?.id) return
  agentPanel.activeRun = timeline
  agentPanel.runId = timeline.run.id
  agentPanel.sessionId = timeline.run.sessionId || timeline.latestSession?.id || agentPanel.sessionId
  agentPanel.targetNodeId = timeline.run.targetNodeId || ''
  agentPanel.sourceSurface = timeline.run.sourceSurface || 'panel'
}

function getAgentRunHistorySummary(item) {
  const run = item?.run || {}
  const summary = run.summary || {}
  const status = getAgentRunStatusLabel(run.status)
  const stepCount = Array.isArray(item?.steps) ? item.steps.length : 0
  const artifactCount = summary.artifactCount || item?.steps?.reduce?.((sum, step) => sum + (step.artifacts?.length || 0), 0) || 0
  return `${status} · ${stepCount} 阶段 · ${artifactCount} 产物`
}

function getAgentRunStatusLabel(status) {
  return {
    drafting: '起草中',
    running: '运行中',
    waiting_user: '等待确认',
    waiting_cost_confirmation: '等待扣费确认',
    succeeded: '已完成',
    failed: '失败',
    cancelled: '已取消'
  }[status] || status || '未知'
}

function getAgentStepStatusLabel(status) {
  return {
    queued: '排队',
    running: '运行中',
    waiting_user: '等待确认',
    waiting_cost_confirmation: '等待扣费确认',
    succeeded: '已完成',
    failed: '失败',
    skipped: '已跳过',
    cancelled: '已取消'
  }[status] || status || '未知'
}

function getAgentArtifactStatusLabel(status) {
  return {
    draft: '草稿',
    ready: '已准备',
    written: '已写入',
    waiting_cost_confirmation: '待确认',
    submitted: '已提交',
    failed: '失败'
  }[status] || status || '未知'
}

function getAgentArtifactTypeLabel(type) {
  return {
    text_node: '文本节点',
    storyboard_plan: '分镜计划',
    character_brief: '角色设定',
    scene_brief: '场景设定',
    prompt: 'Prompt',
    image_placeholder: '图片占位',
    video_placeholder: '视频占位',
    audio_placeholder: '音频占位',
    media_result: '媒体结果',
    report: '报告'
  }[type] || type || '产物'
}

function getAgentRunMeta(timeline) {
  const run = timeline?.run || {}
  const summary = run.summary || {}
  const contextCount = summary.contextCount ?? run.contextSnapshot?.selectedNodes?.length ?? 0
  const artifactCount = summary.artifactCount || timeline?.steps?.reduce?.((sum, step) => sum + (step.artifacts?.length || 0), 0) || 0
  return `${summary.agentName || 'Agent Team'} · ${getAgentModelLabel(summary.modelCode || agentPanel.modelCode)} · 上下文 ${contextCount} · 产物 ${artifactCount}`
}

function getAgentStepInputSummary(step) {
  const input = step?.input || {}
  if (input.content) return input.content
  if (input.goal) return `目标：${input.goal}`
  if (Number.isFinite(Number(input.contextCount))) return `上下文 ${input.contextCount} 个节点`
  return ''
}

function getAgentArtifactPreview(artifact) {
  const payload = artifact?.payload || {}
  const text = String(payload.body || payload.prompt || '').replace(/\s+/g, ' ').trim()
  return text.length > 140 ? `${text.slice(0, 140)}...` : text || '暂无预览'
}

function getAgentRunEstimatePoints(timeline) {
  const fromSummary = Number(timeline?.run?.summary?.estimatePoints)
  if (Number.isFinite(fromSummary) && fromSummary > 0) return fromSummary
  return (timeline?.steps || []).reduce((sum, step) => sum + (step.artifacts || []).reduce((itemSum, artifact) => itemSum + Number(artifact.preview?.estimatePoints || 0), 0), 0)
}

async function confirmAgentRunCost() {
  if (!agentPanel.runId || agentPanel.confirmingCost) return
  agentPanel.confirmingCost = true
  agentPanel.error = ''
  try {
    const artifactIds = (agentPanel.activeRun?.steps || [])
      .flatMap((step) => step.artifacts || [])
      .filter((artifact) => artifact.status === 'waiting_cost_confirmation')
      .map((artifact) => artifact.id)
    const response = await confirmSluvoAgentRunCost(agentPanel.runId, { artifactIds, confirmed: true })
    setActiveAgentRun(response)
    await Promise.allSettled([loadAgentRuns({ restore: false }), loadProjectCanvas()])
    showToast('媒体生成已确认，任务进入队列')
  } catch (error) {
    agentPanel.error = error instanceof Error ? error.message : '确认媒体生成失败'
  } finally {
    agentPanel.confirmingCost = false
  }
}

async function retryAgentRunStep(step) {
  if (!step?.id || agentPanel.busy) return
  agentPanel.busy = true
  agentPanel.error = ''
  try {
    const response = await retrySluvoAgentStep(step.id)
    setActiveAgentRun(response)
    await Promise.allSettled([loadAgentRuns({ restore: false }), loadProjectCanvas()])
  } catch (error) {
    agentPanel.error = error instanceof Error ? error.message : '重试阶段失败'
  } finally {
    agentPanel.busy = false
  }
}

function restoreAgentRun(item) {
  setActiveAgentRun(item)
  agentPanel.error = ''
  setAgentPanelVisible(true)
}

async function loadAgentRuns({ restore = true } = {}) {
  const projectId = projectStore.activeProject?.id || String(route.params.projectId || '')
  if (!projectId || agentPanel.loadingRuns) return
  agentPanel.loadingRuns = true
  try {
    agentPanel.runs = await fetchSluvoProjectAgentRuns(projectId, { limit: 12 })
    if (restore && !agentPanel.runId) {
      const restorable = agentPanel.runs.find((item) => !['failed', 'cancelled'].includes(item.run?.status))
        || agentPanel.runs[0]
      if (restorable) setActiveAgentRun(restorable)
    } else if (agentPanel.runId) {
      const current = agentPanel.runs.find((item) => item.run?.id === agentPanel.runId)
      if (current) setActiveAgentRun(current)
    }
  } catch (error) {
    if (error?.status === 401) router.push({ name: 'login', query: { redirect: route.fullPath } })
  } finally {
    agentPanel.loadingRuns = false
  }
}

function restoreAgentSession(item) {
  if (!item?.session?.id) return
  const restoredAction = item.pendingAction || null
  suppressAgentSelectionWatch = true
  agentPanel.sessionId = item.session.id
  agentPanel.profile = item.session.contextSnapshot?.agentTemplateId || item.session.agentProfile || 'auto'
  agentPanel.modelCode = item.session.contextSnapshot?.modelCode || agentPanel.modelCode
  agentPanel.targetNodeId = item.session.targetNodeId || ''
  agentPanel.sourceSurface = item.session.contextSnapshot?.sourceSurface || 'panel'
  nextTick(() => {
    suppressAgentSelectionWatch = false
  })
  agentPanel.messages = (item.events || []).map((event) => ({
    id: event.id,
    role: event.role === 'user' ? 'user' : 'agent',
    content: event.payload?.content || (event.eventType === 'proposal' ? 'Agent 已生成一条可审阅提案。' : ''),
    routing: getAgentEventRoutingLabel(event.payload)
  })).filter((message) => message.content)
  agentPanel.pendingAction = normalizeAgentAction(restoredAction && restoredAction.status !== 'failed' ? restoredAction : null)
  if (!agentPanel.pendingAction && item.latestAction?.status === 'failed') {
    agentPanel.error = item.latestAction.error?.message || '上一条 Agent 提案写入失败，可重新生成。'
  }
  setAgentPanelVisible(true)
}

async function loadAgentTemplates() {
  if (agentPanel.loadingTemplates) return
  agentPanel.loadingTemplates = true
  try {
    agentPanel.templates = await fetchSluvoAgents()
  } catch (error) {
    if (error?.status === 401) router.push({ name: 'login', query: { redirect: route.fullPath } })
  } finally {
    agentPanel.loadingTemplates = false
  }
}

async function loadAgentHistory() {
  const projectId = projectStore.activeProject?.id || String(route.params.projectId || '')
  if (!projectId || agentPanel.loadingHistory) return
  agentPanel.loadingHistory = true
  try {
    agentPanel.history = await fetchSluvoProjectAgentSessions(projectId, { limit: 12 })
    if (!agentPanel.sessionId) {
      const restorable = agentPanel.history.find((item) => item.pendingAction?.status && item.pendingAction.status !== 'failed')
        || agentPanel.history.find((item) => item.events?.length && item.latestAction?.status !== 'failed')
      if (restorable) restoreAgentSession(restorable)
    }
  } catch (error) {
    if (error?.status === 401) router.push({ name: 'login', query: { redirect: route.fullPath } })
  } finally {
    agentPanel.loadingHistory = false
  }
}

function openAgentTemplateEditor(agent = null) {
  agentPanel.agentEditorOpen = true
  agentPanel.editingAgentId = agent?.id || ''
  agentPanel.agentForm.name = agent?.name || ''
  agentPanel.agentForm.description = agent?.description || ''
  agentPanel.agentForm.modelCode = agent?.modelCode || agentPanel.modelCode || 'deepseek-v4-flash'
  agentPanel.agentForm.rolePrompt = agent?.rolePrompt || ''
  agentPanel.agentForm.useCasesText = (agent?.useCases || []).join(', ')
  agentPanel.agentForm.inputTypesText = (agent?.inputTypes || []).join(', ')
  agentPanel.agentForm.outputTypesText = (agent?.outputTypes || []).join(', ')
  agentPanel.agentForm.toolsText = (agent?.tools || ['read_canvas', 'propose_canvas_patch']).join(', ')
}

function closeAgentTemplateEditor() {
  agentPanel.agentEditorOpen = false
  agentPanel.editingAgentId = ''
}

async function createAgentFromStarter() {
  const starter = agentStarterTemplates[agentPanel.templates.length % agentStarterTemplates.length]
  try {
    const response = await createSluvoAgent({
      ...starter,
      modelCode: agentPanel.modelCode,
      approvalPolicy: { mode: 'always_review' },
      examples: []
    })
    await loadAgentTemplates()
    agentPanel.profile = response?.agent?.id || agentPanel.templates[0]?.id || agentPanel.profile
    showToast('已从 starter 创建 Agent')
  } catch (error) {
    agentPanel.error = error instanceof Error ? error.message : '创建 Agent 失败'
  }
}

async function saveAgentTemplate() {
  const payload = {
    name: agentPanel.agentForm.name.trim() || '未命名 Agent',
    description: agentPanel.agentForm.description.trim(),
    profileKey: 'custom_agent',
    modelCode: agentPanel.agentForm.modelCode,
    rolePrompt: agentPanel.agentForm.rolePrompt.trim(),
    useCases: splitCsv(agentPanel.agentForm.useCasesText),
    inputTypes: splitCsv(agentPanel.agentForm.inputTypesText),
    outputTypes: splitCsv(agentPanel.agentForm.outputTypesText),
    tools: splitCsv(agentPanel.agentForm.toolsText),
    approvalPolicy: { mode: 'always_review' },
    examples: []
  }
  try {
    const response = agentPanel.editingAgentId
      ? await updateSluvoAgent(agentPanel.editingAgentId, payload)
      : await createSluvoAgent(payload)
    await loadAgentTemplates()
    agentPanel.profile = response?.agent?.id || agentPanel.profile
    agentPanel.modelCode = response?.agent?.modelCode || agentPanel.modelCode
    closeAgentTemplateEditor()
    showToast('Agent 已保存')
  } catch (error) {
    agentPanel.error = error instanceof Error ? error.message : '保存 Agent 失败'
  }
}

async function deleteSelectedAgentTemplate() {
  const template = getSelectedAgentTemplate()
  if (!template) return
  try {
    await deleteSluvoAgent(template.id)
    agentPanel.profile = 'auto'
    await loadAgentTemplates()
    showToast('Agent 已删除')
  } catch (error) {
    agentPanel.error = error instanceof Error ? error.message : '删除 Agent 失败'
  }
}

function splitCsv(value) {
  return String(value || '')
    .split(/[,，\n]/)
    .map((item) => item.trim())
    .filter(Boolean)
}

function getUpstreamAgentContextNodeIds(agentNode) {
  const upstreamIds = directEdges.value
    .filter((edge) => edge.targetId === agentNode.id)
    .map((edge) => edge.sourceId)
    .filter((id) => id && id !== agentNode.id)
  return [...new Set(upstreamIds)]
}

function getAgentNodeContextSummary(node) {
  const count = getUpstreamAgentContextNodeIds(node).length
  return count > 0 ? `已连接 ${count} 个上游节点` : '未连接上游，将读取自身指令'
}

function syncAgentNodeFromPanel(node) {
  const template = getSelectedAgentTemplate()
  rememberHistory()
  updateDirectNode(node.id, {
    agentTemplateId: template?.id || '',
    agentName: template?.name || getAgentProfileLabel(agentPanel.profile),
    agentProfile: agentPanel.profile,
    agentModelCode: agentPanel.modelCode,
    agentRolePromptSummary: summarizeAgentRolePrompt(template?.rolePrompt || ''),
    agentInputTypes: template?.inputTypes || [],
    agentOutputTypes: template?.outputTypes || []
  })
  scheduleCanvasSave(180)
  showToast('Agent 节点已同步面板设置')
}

function applyAgentTemplateToNode(node) {
  const template = agentPanel.templates.find((item) => item.id === node.agentTemplateId)
  node.agentName = template?.name || ''
  node.agentProfile = node.agentTemplateId || 'auto'
  node.agentModelCode = template?.modelCode || node.agentModelCode || 'deepseek-v4-flash'
  node.agentRolePromptSummary = summarizeAgentRolePrompt(template?.rolePrompt || '')
  node.agentInputTypes = template?.inputTypes || []
  node.agentOutputTypes = template?.outputTypes || []
  scheduleCanvasSave(180)
}

function summarizeAgentRolePrompt(value) {
  const text = String(value || '').replace(/\s+/g, ' ').trim()
  return text.length > 88 ? `${text.slice(0, 88)}...` : text
}

async function runAgentNode(node) {
  if (!node?.id || agentPanel.busy) return
  const upstreamIds = getUpstreamAgentContextNodeIds(node)
  const contextNodeIds = upstreamIds.length ? upstreamIds : [node.id]
  const template = agentPanel.templates.find((item) => item.id === node.agentTemplateId)
  const content = node.prompt.trim() || `请读取 ${node.title} 的上游节点，生成可审阅的画布提案。`
  rememberHistory()
  updateDirectNode(node.id, {
    generationStatus: 'running',
    generationMessage: 'Agent 正在读取连接上下文',
    agentLastActionStatus: 'running',
    agentLastMessage: '提案生成中'
  })
  scheduleCanvasSave(180)
  await runAgentPrompt(content, {
    forceNew: true,
    targetNode: node,
    sourceSurface: 'node',
    contextNodeIds,
    agentProfile: node.agentTemplateId || node.agentProfile || 'auto',
    agentTemplateId: node.agentTemplateId || '',
    agentName: template?.name || node.agentName || node.title,
    modelCode: node.agentModelCode || template?.modelCode || agentPanel.modelCode
  })
  const latestNode = resolveLatestDirectNode(node) || node
  const runSucceeded = Boolean(agentPanel.activeRun?.run?.id)
  updateDirectNode(latestNode.id, {
    generationStatus: runSucceeded ? 'idle' : 'error',
    generationMessage: runSucceeded ? 'Agent Run 已写入时间线' : (agentPanel.error || 'Agent Run 创建失败'),
    agentLastActionId: agentPanel.activeRun?.run?.id || node.agentLastActionId,
    agentLastActionStatus: agentPanel.activeRun?.run?.status || 'failed',
    agentLastProposal: agentPanel.activeRun?.run?.title || node.agentLastProposal,
    agentLastMessage: runSucceeded ? 'Run 时间线已生成' : (agentPanel.error || 'Run 创建失败')
  })
  scheduleCanvasSave(180)
}

function writeTextComposerToNode(node) {
  const content = textNodeComposer.input.trim()
  if (!node?.id || !content) return
  rememberHistory()
  updateDirectNode(node.id, {
    prompt: content,
    promptSegments: [{ type: 'text', text: content }]
  })
  directPromptEditorSignatures.delete(node.id)
  textNodeComposer.input = ''
  scheduleCanvasSave(180)
  showToast('已写入文本节点')
}

async function submitTextNodeAnalysis(node) {
  if (!node?.id || textNodeComposer.busy) return
  const question = textNodeComposer.input.trim()
  const source = node.prompt.trim()
  if (!question && !source) return
  const projectId = projectStore.activeProject?.id || String(route.params.projectId || '')
  if (!projectId) {
    textNodeComposer.error = '缺少项目 ID，无法调用文本节点模型。'
    return
  }
  textNodeComposer.busy = true
  textNodeComposer.error = ''
  try {
    const response = await analyzeSluvoTextNode(projectId, {
      nodeTitle: node.title,
      content: source,
      instruction: question || '请分析这个文本节点，提取角色、场景、道具，并给出下一步创作建议。',
      modelCode: textNodeComposer.modelCode
    })
    const nextContent = String(response?.content || '').trim()
    if (!nextContent) throw new Error('模型没有返回可写入的内容')
    rememberHistory()
    updateDirectNode(node.id, {
      prompt: nextContent,
      promptSegments: [{ type: 'text', text: nextContent }],
      agentModelCode: response?.modelCode || textNodeComposer.modelCode
    })
    directPromptEditorSignatures.delete(node.id)
    textNodeComposer.input = ''
    scheduleCanvasSave(180)
    showToast(response?.llmUsed ? '文本节点已由模型更新' : '文本节点已生成本地分析')
  } catch (error) {
    textNodeComposer.error = error instanceof Error ? error.message : '文本节点分析失败'
    if (error?.status === 401) router.push({ name: 'login', query: { redirect: route.fullPath } })
  } finally {
    textNodeComposer.busy = false
  }
}

function renderDirectMarkdown(value) {
  const lines = String(value || '').replace(/\r\n/g, '\n').split('\n')
  const html = []
  let listOpen = false
  const closeList = () => {
    if (listOpen) {
      html.push('</ul>')
      listOpen = false
    }
  }
  lines.forEach((rawLine) => {
    const line = rawLine.trimEnd()
    if (!line.trim()) {
      closeList()
      return
    }
    const heading = /^(#{1,3})\s+(.+)$/.exec(line)
    if (heading) {
      closeList()
      const level = heading[1].length
      html.push(`<h${level}>${renderMarkdownInline(heading[2])}</h${level}>`)
      return
    }
    const bullet = /^[-*]\s+(.+)$/.exec(line)
    if (bullet) {
      if (!listOpen) {
        html.push('<ul>')
        listOpen = true
      }
      html.push(`<li>${renderMarkdownInline(bullet[1])}</li>`)
      return
    }
    const numbered = /^\d+[.)]\s+(.+)$/.exec(line)
    if (numbered) {
      if (!listOpen) {
        html.push('<ul>')
        listOpen = true
      }
      html.push(`<li>${renderMarkdownInline(numbered[1])}</li>`)
      return
    }
    closeList()
    html.push(`<p>${renderMarkdownInline(line)}</p>`)
  })
  closeList()
  return html.join('')
}

function renderMarkdownInline(value) {
  return escapeHtml(value)
    .replace(/`([^`]+)`/g, '<code>$1</code>')
    .replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>')
    .replace(/\*([^*]+)\*/g, '<em>$1</em>')
}

function escapeHtml(value) {
  return String(value || '')
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;')
}

async function approveAgentAction() {
  if (!agentPanel.pendingAction?.id || agentPanel.busy) return
  agentPanel.busy = true
  agentPanel.error = ''
  try {
    const canContinue = await saveBeforeCriticalCanvasAction()
    if (!canContinue) return
    const targetNodeId = agentPanel.pendingAction.targetNodeId || agentPanel.pendingAction.input?.contextSummary?.targetNodeId || ''
    const response = await approveSluvoAgentAction(agentPanel.pendingAction.id)
    if (targetNodeId) {
      updateDirectNode(targetNodeId, {
        generationStatus: 'idle',
        generationMessage: '提案已写入画布',
        agentLastActionStatus: response?.action?.status || 'succeeded',
        agentLastActionId: response?.action?.id || agentPanel.pendingAction.id,
        agentLastMessage: '提案已写入画布'
      })
    }
    agentPanel.messages.push({ id: `approved-${Date.now()}`, role: 'agent', content: '提案已写入画布。' })
    agentPanel.pendingAction = null
    await loadAgentHistory()
    await loadProjectCanvas()
    showToast('Agent 提案已写入画布')
  } catch (error) {
    agentPanel.error = error instanceof Error ? error.message : '批准失败，请刷新后重试'
  } finally {
    agentPanel.busy = false
  }
}

async function cancelAgentAction() {
  if (!agentPanel.pendingAction?.id || agentPanel.busy) return
  agentPanel.busy = true
  agentPanel.error = ''
  try {
    const targetNodeId = agentPanel.pendingAction.targetNodeId || agentPanel.pendingAction.input?.contextSummary?.targetNodeId || ''
    await cancelSluvoAgentAction(agentPanel.pendingAction.id)
    if (targetNodeId) {
      updateDirectNode(targetNodeId, {
        generationStatus: 'idle',
        generationMessage: '提案已取消',
        agentLastActionStatus: 'cancelled',
        agentLastActionId: agentPanel.pendingAction.id,
        agentLastMessage: '提案已取消'
      })
    }
    agentPanel.messages.push({ id: `cancelled-${Date.now()}`, role: 'agent', content: '提案已取消，画布未改变。' })
    agentPanel.pendingAction = null
    await loadAgentHistory()
  } catch (error) {
    agentPanel.error = error instanceof Error ? error.message : '取消失败'
  } finally {
    agentPanel.busy = false
  }
}

async function unpublishCurrentCanvas() {
  if (!publishDialog.publicationId || publishDialog.submitting) return
  publishDialog.submitting = true
  publishDialog.error = ''
  try {
    await unpublishSluvoCommunityCanvas(publishDialog.publicationId)
    publishDialog.visible = false
    publishDialog.publicationId = ''
    showToast('已取消发布')
  } catch (error) {
    publishDialog.error = error instanceof Error ? error.message : '取消发布失败'
  } finally {
    publishDialog.submitting = false
  }
}

function parsePublishTags(value) {
  return String(value || '')
    .split(/[，,]/)
    .map((item) => item.trim())
    .filter(Boolean)
    .slice(0, 8)
}

function syncCanvasRevisionState(workspace) {
  if (workspace?.canvas) activeCanvas.value = workspace.canvas
  nodeRevisionMap.value = Object.fromEntries((workspace?.nodes || []).map((node) => [node.id, node.revision || 1]))
  edgeRevisionMap.value = Object.fromEntries((workspace?.edges || []).map((edge) => [edge.id, edge.revision || 1]))
}

function syncCanvasSaveResultToLocal(workspace) {
  if (workspace?.canvas) activeCanvas.value = workspace.canvas
  if (workspace?.project) projectStore.setWorkspace({ ...workspace, canvas: activeCanvas.value })

  const serverNodes = Array.isArray(workspace?.nodes) ? workspace.nodes : []
  const serverEdges = Array.isArray(workspace?.edges) ? workspace.edges : []
  const nodeIdMap = buildServerIdMap(serverNodes)
  const edgeIdMap = buildServerIdMap(serverEdges)
  const remapNodeId = (id) => nodeIdMap.get(id) || id
  const remapEdgeId = (id) => edgeIdMap.get(id) || id

  suppressCanvasSaveScheduling = true
  try {
    directNodes.value = directNodes.value.map((node) => {
      const nextId = remapNodeId(node.id)
      if (nextId === node.id) return node
      remapPromptEditorMaps(node.id, nextId)
      return {
        ...node,
        id: nextId,
        clientId: node.clientId || node.id
      }
    })
    nodes.value = nodes.value.map((node) => {
      const nextId = remapNodeId(node.id)
      if (nextId === node.id) return node
      return {
        ...node,
        id: nextId,
        data: {
          ...(node.data || {}),
          clientId: node.data?.clientId || node.id
        }
      }
    })
    directEdges.value = directEdges.value.map((edge) => {
      const nextId = remapEdgeId(edge.id)
      return {
        ...edge,
        id: nextId,
        clientId: edge.clientId || edge.id,
        sourceId: remapNodeId(edge.sourceId),
        targetId: remapNodeId(edge.targetId)
      }
    })
    edges.value = edges.value.map((edge) => {
      const nextId = remapEdgeId(edge.id)
      return {
        ...edge,
        id: nextId,
        source: remapNodeId(edge.source),
        target: remapNodeId(edge.target),
        data: {
          ...(edge.data || {}),
          clientId: edge.data?.clientId || edge.id
        }
      }
    })
    selectedDirectNodeIds.value = selectedDirectNodeIds.value.map(remapNodeId)
    focusedDirectNodeId.value = remapNodeId(focusedDirectNodeId.value)
    activeDirectNodeId.value = remapNodeId(activeDirectNodeId.value)
    lastTouchedDirectNodeId.value = remapNodeId(lastTouchedDirectNodeId.value)
    activeTextEditNodeId.value = remapNodeId(activeTextEditNodeId.value)
    if (promptEditorSelection.nodeId) promptEditorSelection.nodeId = remapNodeId(promptEditorSelection.nodeId)
    selectedEdgeIds.value = selectedEdgeIds.value.map(remapEdgeId)
    if (canvasStore.selectedNodeIds.length > 0) {
      canvasStore.setSelection(canvasStore.selectedNodeIds.map(remapNodeId))
    }
    nodeRevisionMap.value = Object.fromEntries(serverNodes.map((node) => [node.id, node.revision || 1]))
    edgeRevisionMap.value = Object.fromEntries(serverEdges.map((edge) => [edge.id, edge.revision || 1]))
  } finally {
    nextTick(() => {
      suppressCanvasSaveScheduling = false
    })
  }
}

function buildServerIdMap(items) {
  const idMap = new Map()
  items.forEach((item) => {
    const id = String(item?.id || '')
    const clientId = String(item?.data?.clientId || '')
    if (id && clientId && id !== clientId) idMap.set(clientId, id)
  })
  return idMap
}

function remapPromptEditorMaps(previousId, nextId) {
  if (!previousId || !nextId || previousId === nextId) return
  remapMapKey(directPromptEditorElements, previousId, nextId)
  remapMapKey(directPromptEditorSignatures, previousId, nextId)
}

function remapMapKey(map, previousId, nextId) {
  if (!map.has(previousId) || map.has(nextId)) return
  const value = map.get(previousId)
  map.delete(previousId)
  map.set(nextId, value)
}

function mapBackendNodeToDirectNode(node) {
  const data = node?.data || {}
  const directType = normalizeBackendDirectType(node.nodeType, data.directType)
  const size = getDirectNodeSize(directType)
  return {
    id: node.id,
    type: directType,
    title: node.title || data.title || (nodeMeta[directType]?.title ?? nodeMeta.prompt_note.title),
    icon: data.icon || getDirectNodeIcon(directType),
    x: Number(node.position?.x || 0),
    y: Number(node.position?.y || 0),
    width: Number(node.size?.width || size.width),
    height: Number(node.size?.height || size.height),
    actions: Array.isArray(data.actions) ? data.actions : getDirectNodeActions(directType),
    prompt: data.prompt || data.body || '',
    promptSegments: normalizePromptSegments(data.promptSegments, data),
    promptPlaceholder: data.promptPlaceholder || getDirectNodePrompt(directType),
    groupId: data.groupId || '',
    groupTitle: data.groupTitle || '',
    media: data.media || null,
    upload: data.upload || null,
    imageModelId: data.imageModelId || fallbackImageModelOptions[0].id,
    imageResolution: normalizeImageResolutionValue(data.imageResolution || data.resolution),
    imageQuality: normalizeImageQualityValue(data.imageQuality || data.quality),
    videoModelId: data.videoModelId || data.modelCode || fallbackVideoModelOptions[0].id,
    videoGenerationType: data.videoGenerationType || data.generationType || getDefaultVideoGenerationType(data.videoModelId || data.modelCode || fallbackVideoModelOptions[0].id),
    videoResolution: normalizeVideoResolutionValue(data.videoResolution || data.resolution),
    videoDuration: normalizeVideoDurationValue(data.videoDuration || data.duration),
    videoQualityMode: data.videoQualityMode || data.qualityMode || '',
    videoMotionStrength: data.videoMotionStrength || data.motionStrength || '',
    videoAudioEnabled: Boolean(data.videoAudioEnabled || data.audioEnabled),
    videoWebSearch: Boolean(data.videoWebSearch || data.webSearch || data.web_search),
    videoEstimatePoints: Number.isFinite(Number(data.videoEstimatePoints)) ? Number(data.videoEstimatePoints) : null,
    videoEstimateStatus: data.videoEstimateStatus || 'idle',
    audioAbilityType: data.audioAbilityType || data.abilityType || fallbackAudioAbilityOptions[0].id,
    audioTierCode: data.audioTierCode || data.tierCode || fallbackAudioAbilityOptions[0].defaultTier,
    audioModelCode: data.audioModelCode || data.modelCode || fallbackAudioAbilityOptions[0].tiers[0].modelCode,
    audioVoiceId: data.audioVoiceId || data.voiceId || '',
    audioVoiceSourceType: data.audioVoiceSourceType || data.voiceSourceType || 'system',
    audioEmotion: data.audioEmotion || data.emotion || '',
    audioSpeed: data.audioSpeed ?? data.speed ?? 1,
    audioVolume: data.audioVolume ?? data.volume ?? 1,
    audioPitch: data.audioPitch ?? data.pitch ?? 0,
    audioFormat: data.audioFormat || 'mp3',
    audioSampleRate: Number(data.audioSampleRate || 32000),
    audioBitrate: Number(data.audioBitrate || 128000),
    audioChannelCount: Number(data.audioChannelCount || 1),
    audioLanguageBoost: data.audioLanguageBoost || data.languageBoost || 'none',
    audioSettingsOpen: Boolean(data.audioSettingsOpen),
    audioEstimatePoints: Number.isFinite(Number(data.audioEstimatePoints)) ? Number(data.audioEstimatePoints) : null,
    audioEstimateStatus: data.audioEstimateStatus || 'idle',
    agentProfile: data.agentProfile || 'canvas_agent',
    agentTemplateId: data.agentTemplateId || '',
    agentName: data.agentName || '',
    agentRolePromptSummary: data.agentRolePromptSummary || '',
    agentInputTypes: Array.isArray(data.agentInputTypes) ? data.agentInputTypes : [],
    agentOutputTypes: Array.isArray(data.agentOutputTypes) ? data.agentOutputTypes : [],
    agentModelCode: data.modelCode || data.agentModelCode || 'deepseek-v4-flash',
    agentLastProposal: data.lastProposal || '',
    agentLastActionId: data.agentLastActionId || '',
    agentLastActionStatus: data.agentLastActionStatus || '',
    agentLastMessage: data.agentLastMessage || '',
    agentLastRunAt: data.agentLastRunAt || '',
    aspectRatio: data.aspectRatio || fallbackImageAspectRatioOptions[0],
    referenceImages: normalizeManualReferenceImages(data.referenceImages),
    referenceOrder: Array.isArray(data.referenceOrder) ? data.referenceOrder : [],
    referenceMentions: normalizeReferenceMentions(data.referenceMentions),
    generationStatus: data.generationStatus || node.status || 'idle',
    generationMessage: data.generationMessage || '',
    generationTaskId: data.generationTaskId || '',
    generationRecordId: data.generationRecordId || '',
    generatedImage: data.generatedImage || null,
    generatedVideo: data.generatedVideo || null,
    generatedAudio: data.generatedAudio || null,
    clientId: data.clientId || node.id
  }
}

function mapBackendEdgeToDirectEdge(edge) {
  return {
    id: edge.id,
    sourceId: edge.sourceNodeId || edge.data?.sourceClientId || '',
    targetId: edge.targetNodeId || edge.data?.targetClientId || '',
    sourcePortId: edge.sourcePortId || 'right',
    targetPortId: edge.targetPortId || 'left'
  }
}

function normalizeBackendDirectType(nodeType, directType = '') {
  const directTypes = new Set(['prompt_note', 'image_unit', 'video_unit', 'audio_unit', 'uploaded_asset', 'script_episode', 'asset_table', 'storyboard_table', 'media_board', 'agent_node'])
  if (directTypes.has(directType)) return directType
  const map = {
    text: 'prompt_note',
    note: 'prompt_note',
    image: 'image_unit',
    generation: 'image_unit',
    video: 'video_unit',
    audio: 'audio_unit',
    upload: 'uploaded_asset',
    group: 'media_board',
    agent: 'agent_node'
  }
  return map[nodeType] || 'prompt_note'
}

function hasActiveCanvasUploads() {
  return directNodes.value.some((node) => {
    if (node.upload?.status === 'uploading') return true
    return normalizeManualReferenceImages(node.referenceImages).some((reference) => reference.status === 'uploading')
  })
}

function flushDeferredCanvasSave(delay = 180) {
  if (!saveAfterUploads.value || hasActiveCanvasUploads()) return
  saveAfterUploads.value = false
  scheduleCanvasSave(delay)
}

function hasActiveCanvasInteraction() {
  return (
    directDrag.active ||
    directConnection.active ||
    selectionBox.active ||
    addMenu.visible ||
    referenceMenu.visible ||
    contextMenu.visible ||
    uploadDialogOpening ||
    Boolean(activeRailPanel.value)
  )
}

function flushDeferredInteractionSave(delay = 650) {
  if (!saveAfterActiveInteraction.value || hasActiveCanvasInteraction()) return
  saveAfterActiveInteraction.value = false
  scheduleCanvasSave(delay)
}

function isDirectTextEditing() {
  return Boolean(activeTextEditNodeId.value)
}

function startDirectTextEdit(nodeId) {
  activeTextEditNodeId.value = nodeId
  window.clearTimeout(autoSaveTimer)
}

function registerDirectPromptEditor(nodeId, element, node = null) {
  if (element instanceof HTMLElement) {
    directPromptEditorElements.set(nodeId, element)
    const signature = getPromptEditorSignature(node)
    if (activeTextEditNodeId.value !== nodeId && directPromptEditorSignatures.get(nodeId) !== signature) {
      hydrateDirectPromptEditor(element, node)
      directPromptEditorSignatures.set(nodeId, signature)
    }
  } else {
    directPromptEditorElements.delete(nodeId)
    directPromptEditorSignatures.delete(nodeId)
  }
}

function markDirectTextEditDirty() {
  if (!isDirectTextEditing()) return
  saveAfterTextEdit.value = true
  saveStatus.value = 'dirty'
  window.clearTimeout(autoSaveTimer)
}

function handleDirectPromptInput(nodeId, event) {
  const editor = event.currentTarget
  const segments = extractPromptEditorSegments(editor)
  updateDirectNode(nodeId, {
    prompt: getPromptTextFromSegments(segments),
    promptSegments: segments,
    referenceMentions: getReferenceMentionsFromSegments(segments)
  })
  directPromptEditorSignatures.set(nodeId, getPromptEditorSignature({ promptSegments: segments, prompt: getPromptTextFromSegments(segments) }))
  saveDirectPromptSelection(nodeId, event)
  const node = directNodes.value.find((item) => item.id === nodeId)
  if (node?.type === 'audio_unit') refreshAudioEstimate(node)
  markDirectTextEditDirty()
}

function handleDirectPromptPaste(nodeId, event) {
  event.preventDefault()
  const text = event.clipboardData?.getData('text/plain') || ''
  insertPlainTextAtSelection(text)
  handleDirectPromptInput(nodeId, event)
}

function insertPlainTextAtSelection(text) {
  const selection = window.getSelection?.()
  if (!selection || selection.rangeCount === 0) return
  selection.deleteFromDocument()
  const range = selection.getRangeAt(0)
  const textNode = document.createTextNode(text)
  range.insertNode(textNode)
  range.setStartAfter(textNode)
  range.collapse(true)
  selection.removeAllRanges()
  selection.addRange(range)
}

function focusDirectPromptEditor(nodeId) {
  const editor = directPromptEditorElements.get(nodeId)
  if (!editor) return
  editor.focus({ preventScroll: true })
  if (!restoreDirectPromptSelection(nodeId)) {
    const range = placeCaretAtEnd(editor)
    if (range) {
      promptEditorSelection.nodeId = nodeId
      promptEditorSelection.range = range.cloneRange()
    }
  }
}

function handlePromptFieldPointerDown(nodeId, event) {
  const target = event?.target instanceof HTMLElement ? event.target : null
  if (target?.closest?.('.direct-workflow-node__prompt')) return
  focusDirectPromptEditor(nodeId)
}

function isDirectPromptEditTarget(target) {
  return (
    target instanceof HTMLElement &&
    Boolean(target.closest('.direct-workflow-node__prompt-field, .direct-workflow-node__markdown, .direct-workflow-node__references, .direct-workflow-node__generation-controls, .text-node-ai-composer, .canvas-agent-panel, .publish-dialog'))
  )
}

function handleDirectNodeSelectStart(event) {
  if (isTextInteractionTarget(event.target) || isDirectPromptEditTarget(event.target)) return
  event.preventDefault()
}

function hydrateDirectPromptEditor(element, node = null) {
  element.replaceChildren()
  normalizePromptSegments(node?.promptSegments, node).forEach((segment) => {
    if (segment.type === 'reference') {
      element.appendChild(createPromptReferenceToken(segment, node?.id))
      return
    }
    if (segment.type === 'audio_token') {
      element.appendChild(createPromptAudioToken(segment))
      return
    }
    element.appendChild(document.createTextNode(segment.text || ''))
  })
}

function createPromptReferenceToken(mention, nodeId = '') {
  const token = document.createElement('span')
  token.className = 'direct-workflow-node__mention-chip'
  token.contentEditable = 'false'
  token.draggable = false
  token.dataset.promptToken = 'reference'
  token.dataset.mentionId = mention.id || `reference-mention-${Date.now()}-${Math.round(Math.random() * 10000)}`
  token.dataset.referenceId = mention.referenceId || ''
  token.dataset.label = mention.label || '图片'

  const reference = getDirectImageReferenceItems(nodeId).find((item) => item.id === token.dataset.referenceId)
  const previewUrl = mention.previewUrl || reference?.previewUrl || reference?.url || ''
  if (previewUrl) {
    const image = document.createElement('img')
    image.src = previewUrl
    image.alt = ''
    image.draggable = false
    token.appendChild(image)
  }
  const label = document.createElement('span')
  label.textContent = token.dataset.label
  token.appendChild(label)
  return token
}

function createPromptAudioToken(segment) {
  const token = document.createElement('span')
  token.className = `direct-workflow-node__audio-token-chip direct-workflow-node__audio-token-chip--${segment.tokenKind || 'tag'}`
  token.contentEditable = 'false'
  token.draggable = false
  token.dataset.promptToken = 'audio_token'
  token.dataset.tokenId = segment.id || `audio-token-${Date.now()}-${Math.round(Math.random() * 10000)}`
  token.dataset.value = segment.value || segment.text || ''
  token.dataset.label = segment.label || segment.value || segment.text || ''
  token.dataset.tokenKind = segment.tokenKind || 'tag'
  token.textContent = token.dataset.label
  return token
}

function extractPromptEditorSegments(element) {
  if (!(element instanceof HTMLElement)) return []
  const segments = []
  const appendText = (text) => {
    const normalized = String(text || '').replace(/\u00a0/g, ' ')
    if (!normalized) return
    const previous = segments.at(-1)
    if (previous?.type === 'text') {
      previous.text += normalized
    } else {
      segments.push({ type: 'text', text: normalized })
    }
  }
  element.childNodes.forEach((child) => {
    if (child.nodeType === Node.TEXT_NODE) {
      appendText(child.textContent)
      return
    }
    if (!(child instanceof HTMLElement)) return
    if (child.dataset.promptToken === 'audio_token' || child.classList.contains('direct-workflow-node__audio-token-chip')) {
      segments.push({
        type: 'audio_token',
        id: child.dataset.tokenId || `audio-token-${Date.now()}-${Math.round(Math.random() * 10000)}`,
        value: child.dataset.value || child.innerText || child.textContent || '',
        label: child.dataset.label || child.innerText || child.textContent || '',
        tokenKind: child.dataset.tokenKind || 'tag'
      })
      return
    }
    if (child.dataset.promptToken === 'reference' || child.classList.contains('direct-workflow-node__mention-chip')) {
      segments.push({
        type: 'reference',
        id: child.dataset.mentionId || `reference-mention-${Date.now()}-${Math.round(Math.random() * 10000)}`,
        referenceId: child.dataset.referenceId || '',
        label: child.dataset.label || child.innerText || '图片'
      })
      return
    }
    appendText(child.innerText || child.textContent)
  })
  return normalizePromptSegments(segments)
}

function getPromptTextFromSegments(segments) {
  return normalizePromptSegments(segments)
    .filter((segment) => segment.type === 'text' || segment.type === 'audio_token')
    .map((segment) => (segment.type === 'audio_token' ? segment.value : segment.text))
    .join('')
}

function getReferenceMentionsFromSegments(segments) {
  return normalizePromptSegments(segments)
    .filter((segment) => segment.type === 'reference')
    .map((segment) => ({
      id: segment.id,
      referenceId: segment.referenceId,
      label: segment.label
    }))
}

function getPromptEditorSignature(node = null) {
  return JSON.stringify(normalizePromptSegments(node?.promptSegments, node))
}

function isDirectPromptEditorEmpty(node) {
  return normalizePromptSegments(node?.promptSegments, node).length === 0
}

function isSingleSelectedDirectNode(nodeId) {
  return selectedDirectNodeIds.value.length === 1 && selectedDirectNodeIds.value[0] === nodeId
}

function findPreviousPromptToken(editor, range) {
  let node = range.startContainer
  let offset = range.startOffset
  if (node.nodeType === Node.TEXT_NODE && offset > 0) return null
  if (node.nodeType === Node.ELEMENT_NODE && offset > 0) {
    const child = node.childNodes[offset - 1]
    const token = findLastTokenInside(child)
    if (token) return token
  }
  while (node && node !== editor) {
    let previous = node.previousSibling
    while (previous) {
      const token = findLastTokenInside(previous)
      if (token) return token
      if (getNodeTextLength(previous) > 0) return null
      previous = previous.previousSibling
    }
    node = node.parentNode
  }
  return null
}

function findNextPromptToken(editor, range) {
  let node = range.startContainer
  let offset = range.startOffset
  if (node.nodeType === Node.TEXT_NODE && offset < String(node.textContent || '').length) return null
  if (node.nodeType === Node.ELEMENT_NODE && offset < node.childNodes.length) {
    const child = node.childNodes[offset]
    const token = findFirstTokenInside(child)
    if (token) return token
  }
  while (node && node !== editor) {
    let next = node.nextSibling
    while (next) {
      const token = findFirstTokenInside(next)
      if (token) return token
      if (getNodeTextLength(next) > 0) return null
      next = next.nextSibling
    }
    node = node.parentNode
  }
  return null
}

function findLastTokenInside(node) {
  if (!(node instanceof HTMLElement) && node?.nodeType !== Node.TEXT_NODE) return null
  if (node instanceof HTMLElement && (node.classList.contains('direct-workflow-node__mention-chip') || node.classList.contains('direct-workflow-node__audio-token-chip'))) return node
  if (!(node instanceof HTMLElement)) return null
  for (let index = node.childNodes.length - 1; index >= 0; index -= 1) {
    const token = findLastTokenInside(node.childNodes[index])
    if (token) return token
  }
  return null
}

function findFirstTokenInside(node) {
  if (!(node instanceof HTMLElement) && node?.nodeType !== Node.TEXT_NODE) return null
  if (node instanceof HTMLElement && (node.classList.contains('direct-workflow-node__mention-chip') || node.classList.contains('direct-workflow-node__audio-token-chip'))) return node
  if (!(node instanceof HTMLElement)) return null
  for (const child of node.childNodes) {
    const token = findFirstTokenInside(child)
    if (token) return token
  }
  return null
}

function getNodeTextLength(node) {
  return String(node?.textContent || '').length
}

function saveDirectPromptSelection(nodeId, event = null) {
  const editor = directPromptEditorElements.get(nodeId)
  const selection = window.getSelection?.()
  if (!editor || !selection || selection.rangeCount === 0) return
  const range = selection.getRangeAt(0)
  if (!editor.contains(range.startContainer) || !editor.contains(range.endContainer)) return
  promptEditorSelection.nodeId = nodeId
  promptEditorSelection.range = range.cloneRange()
}

function restoreDirectPromptSelection(nodeId) {
  const editor = directPromptEditorElements.get(nodeId)
  const selection = window.getSelection?.()
  if (!editor || !selection) return false
  const savedRange = promptEditorSelection.nodeId === nodeId ? promptEditorSelection.range : null
  if (!savedRange || !editor.contains(savedRange.startContainer) || !editor.contains(savedRange.endContainer)) return false
  selection.removeAllRanges()
  selection.addRange(savedRange)
  return true
}

function placeCaretAtEnd(element) {
  const selection = window.getSelection?.()
  const range = document.createRange?.()
  if (!selection || !range) return null
  range.selectNodeContents(element)
  range.collapse(false)
  selection.removeAllRanges()
  selection.addRange(range)
  return range
}

function handleDirectPromptKeydown(nodeId, event) {
  if ((event.ctrlKey || event.metaKey) && event.key === 'Enter') {
    event.preventDefault()
    event.stopPropagation()
    finishDirectTextEdit()
    return
  }
  if (event.key !== 'Backspace' && event.key !== 'Delete') {
    event.stopPropagation()
    return
  }
  const editor = directPromptEditorElements.get(nodeId)
  if (!editor || removeAdjacentPromptToken(editor, event.key === 'Backspace' ? 'backward' : 'forward') === false) {
    event.stopPropagation()
    return
  }
  event.preventDefault()
  event.stopPropagation()
  handleDirectPromptInput(nodeId, { currentTarget: editor })
}

function removeAdjacentPromptToken(editor, direction) {
  const selection = window.getSelection?.()
  if (!selection || selection.rangeCount === 0 || !selection.isCollapsed) return false
  const range = selection.getRangeAt(0)
  if (!editor.contains(range.startContainer)) return false
  const token = direction === 'backward' ? findPreviousPromptToken(editor, range) : findNextPromptToken(editor, range)
  if (!token) return false
  const nextRange = document.createRange()
  if (direction === 'backward') {
    nextRange.setStartBefore(token)
  } else {
    nextRange.setStartAfter(token)
  }
  token.remove()
  nextRange.collapse(true)
  selection.removeAllRanges()
  selection.addRange(nextRange)
  return true
}

function finishDirectTextEdit() {
  if (!isDirectTextEditing()) return
  const nodeId = activeTextEditNodeId.value
  const editor = directPromptEditorElements.get(nodeId)
  if (editor) {
    const segments = extractPromptEditorSegments(editor)
    updateDirectNode(nodeId, {
      prompt: getPromptTextFromSegments(segments),
      promptSegments: segments,
      referenceMentions: getReferenceMentionsFromSegments(segments)
    })
  }
  activeTextEditNodeId.value = ''
  if (!saveAfterTextEdit.value) return
  saveAfterTextEdit.value = false
  scheduleCanvasSave(700)
}

function scheduleCanvasSave(delay = 1200) {
  if (suppressCanvasSaveScheduling) return
  if (isHydratingCanvas.value || !activeCanvas.value?.id) return
  if (isSavingCanvas.value) {
    saveAfterCurrentSave.value = true
    saveStatus.value = 'dirty'
    window.clearTimeout(autoSaveTimer)
    return
  }
  if (isDirectTextEditing()) {
    saveAfterTextEdit.value = true
    saveStatus.value = 'dirty'
    window.clearTimeout(autoSaveTimer)
    return
  }
  if (hasActiveCanvasInteraction()) {
    saveAfterActiveInteraction.value = true
    saveStatus.value = 'dirty'
    window.clearTimeout(autoSaveTimer)
    return
  }
  if (hasActiveCanvasUploads()) {
    saveAfterUploads.value = true
    saveStatus.value = 'dirty'
    window.clearTimeout(autoSaveTimer)
    return
  }
  saveStatus.value = saveStatus.value === 'saving' ? 'saving' : 'dirty'
  window.clearTimeout(autoSaveTimer)
  autoSaveTimer = window.setTimeout(() => {
    saveCanvasNow()
  }, delay)
}

function hasUnsavedCanvasChanges() {
  return (
    saveStatus.value === 'dirty' ||
    saveStatus.value === 'saving' ||
    saveStatus.value === 'error' ||
    saveStatus.value === 'conflict' ||
    isSavingCanvas.value ||
    saveAfterCurrentSave.value ||
    saveAfterActiveInteraction.value ||
    saveAfterTextEdit.value ||
    saveAfterUploads.value
  )
}

function persistCriticalCanvasChange(delay = 120) {
  if (!activeCanvas.value?.id || isHydratingCanvas.value) return
  finishDirectTextEdit()
  saveCanvasNow({ ignoreInteraction: true })
  scheduleCanvasSave(delay)
}

async function saveBeforeCriticalCanvasAction() {
  finishDirectTextEdit()
  if (hasActiveCanvasUploads()) {
    saveStatus.value = 'dirty'
    saveAfterUploads.value = true
    showToast('文件上传中，上传完成后会自动保存')
    return false
  }
  if (!hasUnsavedCanvasChanges()) return true
  await saveCanvasNow({ ignoreInteraction: true })
  return saveStatus.value !== 'error' && saveStatus.value !== 'conflict'
}

async function flushCanvasSaveBeforeLeaving() {
  finishDirectTextEdit()
  if (!hasUnsavedCanvasChanges()) return true
  if (hasActiveCanvasUploads()) {
    return window.confirm('文件还在上传，离开后未完成的素材可能不会保存。确定要离开吗？')
  }
  await saveCanvasNow({ ignoreInteraction: true })
  if (!hasUnsavedCanvasChanges() || saveStatus.value === 'saved') return true
  return window.confirm('画布还没有保存完成，确定要离开吗？')
}

function handleBeforeUnload(event) {
  finishDirectTextEdit()
  if (!hasUnsavedCanvasChanges()) return
  event.preventDefault()
  event.returnValue = ''
}

function flushCanvasSaveOnPageHide() {
  if (!hasUnsavedCanvasChanges() || hasActiveCanvasUploads()) return
  finishDirectTextEdit()
  saveCanvasNow({ ignoreInteraction: true })
}

function handleVisibilityChange() {
  if (document.visibilityState === 'hidden') flushCanvasSaveOnPageHide()
}

async function saveCanvasNow(options = {}) {
  const ignoreInteraction = Boolean(options.ignoreInteraction)
  if (suppressCanvasSaveScheduling) return
  if (isHydratingCanvas.value || !activeCanvas.value?.id) return
  if (isSavingCanvas.value) {
    saveAfterCurrentSave.value = true
    saveStatus.value = 'dirty'
    window.clearTimeout(autoSaveTimer)
    return
  }
  if (isDirectTextEditing() && !ignoreInteraction) {
    saveAfterTextEdit.value = true
    saveStatus.value = 'dirty'
    window.clearTimeout(autoSaveTimer)
    return
  }
  if (hasActiveCanvasInteraction() && !ignoreInteraction) {
    saveAfterActiveInteraction.value = true
    saveStatus.value = 'dirty'
    window.clearTimeout(autoSaveTimer)
    return
  }
  if (hasActiveCanvasUploads()) {
    saveAfterUploads.value = true
    saveStatus.value = 'dirty'
    window.clearTimeout(autoSaveTimer)
    showToast('文件上传中，上传完成后自动保存')
    return
  }
  if (ignoreInteraction) {
    saveAfterActiveInteraction.value = false
    saveAfterTextEdit.value = false
    saveAfterUploads.value = false
  }
  window.clearTimeout(autoSaveTimer)
  lastSaveError.value = ''
  const savePlan = buildCanvasSavePlan()
  isSavingCanvas.value = true
  saveStatus.value = 'saving'
  try {
    const response = await saveSluvoCanvasBatch(activeCanvas.value.id, savePlan.payload)
    const omittedEdges = savePlan.omittedEdges
    const renamedProject = await syncActiveProjectTitle(savePlan.payload.title)
    syncCanvasSaveResultToLocal({
      ...response,
      project: renamedProject || response?.project || projectStore.activeProject
    })
    if (omittedEdges.length > 0) saveAfterCurrentSave.value = true
    if (
      saveAfterCurrentSave.value ||
      saveAfterActiveInteraction.value ||
      saveAfterTextEdit.value ||
      saveAfterUploads.value ||
      hasActiveCanvasInteraction() ||
      isDirectTextEditing() ||
      hasActiveCanvasUploads()
    ) {
      saveStatus.value = 'dirty'
    } else {
      saveStatus.value = 'saved'
    }
  } catch (error) {
    if (error instanceof SluvoRevisionConflictError) {
      saveStatus.value = 'conflict'
      lastSaveError.value = error.message || 'Canvas revision conflict'
      showToast('画布已在其他地方更新，正在刷新')
      await loadProjectCanvas()
      return
    }
    saveStatus.value = 'error'
    lastSaveError.value = error instanceof Error ? error.message : 'Canvas save failed'
    console.error('[Sluvo] canvas save failed', {
      message: lastSaveError.value,
      status: error?.status,
      payload: error?.payload,
      canvasId: activeCanvas.value?.id,
      nodeCount: directNodes.value.length + nodes.value.length,
      edgeCount: directEdges.value.length + edges.value.length,
      payloadBytes: measureCanvasSavePayloadBytes(savePlan.payload)
    })
    showToast(error instanceof Error ? error.message : '画布保存失败')
  } finally {
    isSavingCanvas.value = false
    if (saveStatus.value === 'dirty') {
      const shouldWaitForInteraction = saveAfterActiveInteraction.value || hasActiveCanvasInteraction()
      const shouldWaitForText = saveAfterTextEdit.value || isDirectTextEditing()
      const shouldWaitForUpload = saveAfterUploads.value || hasActiveCanvasUploads()
      saveAfterCurrentSave.value = false
      if (!shouldWaitForInteraction && !shouldWaitForText && !shouldWaitForUpload) {
        nextTick(() => scheduleCanvasSave(900))
      }
    }
  }
}

function captureDirectSelection() {
  return {
    selectedIds: [...selectedDirectNodeIds.value],
    focusedId: focusedDirectNodeId.value,
    activeId: activeDirectNodeId.value,
    lastTouchedId: lastTouchedDirectNodeId.value
  }
}

function restoreDirectSelection(snapshot) {
  const existingIds = new Set(directNodes.value.map((node) => node.id))
  const selectedIds = (snapshot?.selectedIds || []).filter((id) => existingIds.has(id))
  selectedDirectNodeIds.value = selectedIds
  focusedDirectNodeId.value = existingIds.has(snapshot?.focusedId) ? snapshot.focusedId : selectedIds.at(-1) || ''
  activeDirectNodeId.value = existingIds.has(snapshot?.activeId) ? snapshot.activeId : selectedIds.at(-1) || ''
  lastTouchedDirectNodeId.value = existingIds.has(snapshot?.lastTouchedId)
    ? snapshot.lastTouchedId
    : activeDirectNodeId.value || focusedDirectNodeId.value
}

async function syncActiveProjectTitle(title) {
  const nextTitle = String(title || '').trim() || copy.untitled
  if (!projectStore.activeProject?.id || projectStore.activeProject.title === nextTitle) {
    return projectStore.activeProject
  }
  try {
    return await projectStore.renameActiveProject(nextTitle)
  } catch (error) {
    showToast(error instanceof Error ? error.message : '项目重命名同步失败')
    return projectStore.activeProject
  }
}

function buildCanvasSavePlan() {
  const serializedNodes = [...directNodes.value.map(serializeDirectNodeForSave), ...nodes.value.map(serializeVueNodeForSave)]
  const currentNodeIds = new Set(serializedNodes.map((node) => node.id).filter(Boolean))
  const deletedNodeIds = Object.keys(nodeRevisionMap.value).filter((id) => !currentNodeIds.has(id))
  const serializedEdges = []
  const omittedEdges = []

  for (const edge of [...directEdges.value.map(serializeDirectEdgeForSave), ...edges.value.map(serializeVueEdgeForSave)]) {
    if (canPersistSerializedEdge(edge)) {
      serializedEdges.push(edge)
    } else {
      omittedEdges.push(edge)
    }
  }

  const currentEdgeIds = new Set(serializedEdges.map((edge) => edge.id).filter(Boolean))
  const deletedEdgeIds = Object.keys(edgeRevisionMap.value).filter((id) => !currentEdgeIds.has(id))

  return {
    omittedEdges,
    payload: {
      expectedRevision: activeCanvas.value.revision,
      title: projectTitle.value,
      viewport: getViewport(),
      snapshot: buildCanvasSnapshot(),
      nodes: serializedNodes,
      edges: serializedEdges,
      deletedNodeIds,
      deletedEdgeIds
    }
  }
}

function canPersistSerializedEdge(edge) {
  const sourceRef = edge.sourceNodeId || edge.data?.sourceClientId
  const targetRef = edge.targetNodeId || edge.data?.targetClientId
  return Boolean(sourceRef && targetRef)
}

function serializeDirectNodeForSave(node, index = 0) {
  const size = getDirectNodeSize(node.type)
  const clientId = node.clientId || node.id
  const media = sanitizeMediaForPersistence(node.media)
  const payload = {
    nodeType: mapDirectTypeToBackendType(node.type),
    title: node.title || nodeMeta[node.type]?.title || '节点',
    position: { x: Number(node.x || 0), y: Number(node.y || 0) },
    size: { width: Number(node.width || size.width), height: Number(node.height || size.height) },
    zIndex: index,
    status: normalizeNodeStatus(node.generationStatus || 'draft'),
    data: {
      clientId,
      directType: node.type,
      title: node.title,
      icon: node.icon,
      actions: node.actions || [],
      groupId: node.groupId || '',
      groupTitle: node.groupTitle || '',
      prompt: node.prompt || '',
      body: node.prompt || '',
      promptSegments: normalizePromptSegments(node.promptSegments, node),
      promptPlaceholder: node.promptPlaceholder || '',
      media,
      upload: node.upload || null,
      imageModelId: node.imageModelId || '',
      imageResolution: normalizeImageResolutionValue(node.imageResolution),
      imageQuality: normalizeImageQualityValue(node.imageQuality),
      videoModelId: node.videoModelId || '',
      videoGenerationType: node.videoGenerationType || '',
      videoResolution: normalizeVideoResolutionValue(node.videoResolution),
      videoDuration: normalizeVideoDurationValue(node.videoDuration),
      videoQualityMode: node.videoQualityMode || '',
      videoMotionStrength: node.videoMotionStrength || '',
      videoAudioEnabled: Boolean(node.videoAudioEnabled),
      videoWebSearch: Boolean(node.videoWebSearch),
      videoEstimatePoints: node.videoEstimatePoints ?? null,
      videoEstimateStatus: node.videoEstimateStatus || 'idle',
      audioAbilityType: node.audioAbilityType || '',
      audioTierCode: node.audioTierCode || '',
      audioModelCode: node.audioModelCode || '',
      audioVoiceId: node.audioVoiceId || '',
      audioVoiceSourceType: node.audioVoiceSourceType || 'system',
      audioEmotion: node.audioEmotion || '',
      audioSpeed: node.audioSpeed ?? 1,
      audioVolume: node.audioVolume ?? 1,
      audioPitch: node.audioPitch ?? 0,
      audioFormat: node.audioFormat || 'mp3',
      audioSampleRate: Number(node.audioSampleRate || 32000),
      audioBitrate: Number(node.audioBitrate || 128000),
      audioChannelCount: Number(node.audioChannelCount || 1),
      audioLanguageBoost: node.audioLanguageBoost || 'none',
      audioSettingsOpen: Boolean(node.audioSettingsOpen),
      audioEstimatePoints: node.audioEstimatePoints ?? null,
      audioEstimateStatus: node.audioEstimateStatus || 'idle',
      agentProfile: node.agentProfile || '',
      agentTemplateId: node.agentTemplateId || '',
      agentName: node.agentName || '',
      agentRolePromptSummary: node.agentRolePromptSummary || '',
      agentInputTypes: Array.isArray(node.agentInputTypes) ? node.agentInputTypes : [],
      agentOutputTypes: Array.isArray(node.agentOutputTypes) ? node.agentOutputTypes : [],
      agentModelCode: node.agentModelCode || '',
      modelCode: node.agentModelCode || '',
      lastProposal: node.agentLastProposal || '',
      agentLastActionId: node.agentLastActionId || '',
      agentLastActionStatus: node.agentLastActionStatus || '',
      agentLastMessage: node.agentLastMessage || '',
      agentLastRunAt: node.agentLastRunAt || '',
      aspectRatio: node.aspectRatio || '',
      referenceImages: normalizeManualReferenceImages(node.referenceImages)
        .filter((item) => item.status !== 'uploading')
        .map((item) => ({
          ...item,
          previewUrl: item.previewUrl?.startsWith('blob:') || item.previewUrl?.startsWith('data:') ? '' : item.previewUrl
        })),
      referenceOrder: Array.isArray(node.referenceOrder) ? node.referenceOrder : [],
      referenceMentions: normalizeReferenceMentions(node.referenceMentions),
      generationStatus: node.generationStatus || 'idle',
      generationMessage: node.generationMessage || '',
      generationTaskId: node.generationTaskId || '',
      generationRecordId: node.generationRecordId || '',
      generatedImage: sanitizeGeneratedMediaForPersistence('image', node.generatedImage),
      generatedVideo: sanitizeGeneratedMediaForPersistence('video', node.generatedVideo),
      generatedAudio: sanitizeGeneratedMediaForPersistence('audio', node.generatedAudio)
    },
    ports: { left: true, right: true },
    style: {}
  }
  if (nodeRevisionMap.value[node.id]) {
    payload.id = node.id
    payload.expectedRevision = nodeRevisionMap.value[node.id]
  }
  return payload
}

function sanitizeMediaForPersistence(media) {
  if (!media) return null
  const url = String(media.url || '')
  if (media.isLocalPreview || url.startsWith('blob:') || url.startsWith('data:')) {
    return {
      ...media,
      url: media.assetId && !url.startsWith('data:') ? media.url : '',
      previewUrl: '',
      isLocalPreview: false,
      localPreviewDropped: true
    }
  }
  const previewUrl = String(media.previewUrl || '')
  const thumbnailUrl = String(media.thumbnailUrl || '')
  if (previewUrl.startsWith('blob:') || previewUrl.startsWith('data:') || thumbnailUrl.startsWith('blob:') || thumbnailUrl.startsWith('data:')) {
    return {
      ...media,
      previewUrl: previewUrl.startsWith('blob:') || previewUrl.startsWith('data:') ? '' : media.previewUrl,
      thumbnailUrl: thumbnailUrl.startsWith('blob:') || thumbnailUrl.startsWith('data:') ? '' : media.thumbnailUrl
    }
  }
  return media
}

function sanitizeGeneratedMediaForPersistence(kind, media) {
  if (!media) return null
  const next = { ...media }
  const urlKeys =
    kind === 'audio'
      ? ['url', 'previewUrl']
      : kind === 'video'
        ? ['url', 'previewUrl', 'thumbnailUrl', 'posterUrl']
        : ['url', 'previewUrl', 'thumbnailUrl']

  for (const key of urlKeys) {
    if (next[key] && !isPersistableMediaUrl(next[key], kind)) {
      next[key] = ''
      next.localPreviewDropped = true
    }
  }

  if (!next.url) {
    const fallback = kind === 'image' ? next.thumbnailUrl || next.previewUrl : kind === 'video' ? next.previewUrl : ''
    if (fallback && isPersistableMediaUrl(fallback, kind)) next.url = fallback
  }

  return next
}

function isPersistableMediaUrl(value, kind = '') {
  const source = String(value || '').trim()
  if (!source) return false
  if (/^blob:/i.test(source)) return false
  if (/^data:/i.test(source)) return false
  if (/^https?:\/\//i.test(source)) return true
  if (source.startsWith('/')) return true
  return kind === 'image' && /^\/\/.+/i.test(source)
}

function sanitizeDirectNodeForSnapshot(node) {
  return {
    ...node,
    media: sanitizeMediaForPersistence(node.media),
    generatedImage: sanitizeGeneratedMediaForPersistence('image', node.generatedImage),
    generatedVideo: sanitizeGeneratedMediaForPersistence('video', node.generatedVideo),
    generatedAudio: sanitizeGeneratedMediaForPersistence('audio', node.generatedAudio)
  }
}

function measureCanvasSavePayloadBytes(payload) {
  try {
    return new Blob([JSON.stringify(payload)]).size
  } catch {
    try {
      return JSON.stringify(payload).length
    } catch {
      return 0
    }
  }
}

function serializeVueNodeForSave(node, index = 0) {
  const type = node.data?.nodeType || 'prompt_note'
  const size = getWorkflowNodeSize(node)
  const payload = {
    nodeType: mapDirectTypeToBackendType(type),
    title: node.data?.title || '节点',
    position: { x: Number(node.position?.x || 0), y: Number(node.position?.y || 0) },
    size: { width: Number(size.width), height: Number(size.height) },
    zIndex: directNodes.value.length + index,
    status: node.data?.status || 'draft',
    data: {
      ...(node.data || {}),
      clientId: node.data?.clientId || node.id,
      directType: type,
      prompt: node.data?.prompt || node.data?.body || ''
    },
    ports: { in: true, out: true },
    style: node.style || {}
  }
  if (nodeRevisionMap.value[node.id]) {
    payload.id = node.id
    payload.expectedRevision = nodeRevisionMap.value[node.id]
  }
  return payload
}

function serializeDirectEdgeForSave(edge) {
  const sourceNodeId = getPersistedNodeId(edge.sourceId)
  const targetNodeId = getPersistedNodeId(edge.targetId)
  const payload = {
    sourceNodeId,
    targetNodeId,
    sourcePortId: edge.sourcePortId || 'right',
    targetPortId: edge.targetPortId || 'left',
    edgeType: 'reference',
    label: edge.label || '引用',
    data: {
      clientId: edge.clientId || edge.id,
      sourceClientId: getNodeClientId(edge.sourceId),
      targetClientId: getNodeClientId(edge.targetId)
    },
    style: {}
  }
  if (edgeRevisionMap.value[edge.id]) {
    payload.id = edge.id
    payload.expectedRevision = edgeRevisionMap.value[edge.id]
  }
  return payload
}

function serializeVueEdgeForSave(edge) {
  const payload = {
    sourceNodeId: getPersistedNodeId(edge.source),
    targetNodeId: getPersistedNodeId(edge.target),
    sourcePortId: edge.sourceHandle || 'out',
    targetPortId: edge.targetHandle || 'in',
    edgeType: edge.label === '生成' ? 'generation' : 'reference',
    label: edge.label || '引用',
    data: {
      clientId: edge.data?.clientId || edge.id,
      sourceClientId: getNodeClientId(edge.source),
      targetClientId: getNodeClientId(edge.target)
    },
    style: edge.style || {}
  }
  if (edgeRevisionMap.value[edge.id]) {
    payload.id = edge.id
    payload.expectedRevision = edgeRevisionMap.value[edge.id]
  }
  return payload
}

function mapOmittedEdgesAfterHydration(omittedEdges) {
  const clientToServerNodeId = new Map(directNodes.value.map((node) => [node.clientId || node.id, node.id]))
  return omittedEdges
    .map((edge) => {
      const sourceId = edge.sourceNodeId || clientToServerNodeId.get(edge.data?.sourceClientId)
      const targetId = edge.targetNodeId || clientToServerNodeId.get(edge.data?.targetClientId)
      if (!sourceId || !targetId) return null
      return {
        id: `direct-edge-${Date.now()}-${Math.round(Math.random() * 10000)}`,
        sourceId,
        targetId,
        sourcePortId: edge.sourcePortId || 'right',
        targetPortId: edge.targetPortId || 'left',
        clientId: edge.data?.clientId || edge.id
      }
    })
    .filter(Boolean)
}

function getPersistedNodeId(nodeId) {
  return nodeRevisionMap.value[nodeId] ? nodeId : ''
}

function getNodeClientId(nodeId) {
  const node = directNodes.value.find((item) => item.id === nodeId) || nodes.value.find((item) => item.id === nodeId)
  return node?.clientId || node?.data?.clientId || nodeId
}

function mapDirectTypeToBackendType(type) {
  const map = {
    prompt_note: 'note',
    image_unit: 'image',
    video_unit: 'video',
    audio_unit: 'audio',
    uploaded_asset: 'upload',
    media_board: 'group',
    script_episode: 'text',
    asset_table: 'note',
    storyboard_table: 'note',
    agent_node: 'agent'
  }
  return map[type] || 'note'
}

function normalizeNodeStatus(status) {
  const normalized = String(status || '').toLowerCase()
  if (normalized === 'running') return 'running'
  if (normalized === 'success') return 'done'
  if (normalized === 'error') return 'failed'
  return normalized || 'draft'
}

function buildCanvasSnapshot() {
  return {
    version: 1,
    savedAt: new Date().toISOString(),
    viewport: getViewport(),
    directNodes: cloneCanvasValue(directNodes.value).map(sanitizeDirectNodeForSnapshot),
    directEdges: cloneCanvasValue(directEdges.value),
    nodes: cloneCanvasValue(nodes.value),
    edges: cloneCanvasValue(edges.value)
  }
}

function handleDocumentKeydown(event) {
  if (handleGlobalUndoShortcut(event)) return
  if (handleCanvasPasteShortcutEvent(event)) return
  if (!isDeleteKey(event) || shouldIgnoreDeleteEventTarget(event.target)) return
  if (deleteActiveDirectNodes(event)) return
}

function handleDocumentKeyup(event) {
  releaseUndoShortcut(event)
  if (!isDeleteKey(event) || shouldIgnoreDeleteEventTarget(event.target)) return
  deleteActiveDirectNodes(event)
}

function handleWindowKeyEvent(event) {
  if (event.type === 'keydown' && handleCanvasPasteShortcutEvent(event)) return
  if (!isDeleteKey(event) || shouldIgnoreDeleteEventTarget(event.target)) return
  deleteActiveDirectNodes(event)
}

function handleCanvasKeyEvent(event) {
  if (handleGlobalUndoShortcut(event)) return
  if (handleCanvasPasteShortcutEvent(event)) return
  if (!isDeleteKey(event) || shouldIgnoreDeleteEventTarget(event.target)) return
  deleteActiveDirectNodes(event)
}

function handleGlobalDeleteShortcut(event) {
  if (handleGlobalUndoShortcut(event)) {
    return false
  }

  if (isDeleteKey(event) && !shouldIgnoreDeleteEventTarget(event.target) && deleteActiveDirectNodes(event)) {
    return false
  }

  if (event?.currentTarget === document && typeof previousDocumentKeydown === 'function') {
    return previousDocumentKeydown.call(document, event)
  }

  if (event?.currentTarget === window && typeof previousWindowKeydown === 'function') {
    return previousWindowKeydown.call(window, event)
  }

  return true
}

function handleGlobalUndoShortcut(event) {
  const command = event?.ctrlKey || event?.metaKey
  if (
    event?.__sluvoUndoHandled ||
    !command ||
    event?.key?.toLowerCase?.() !== 'z' ||
    shouldIgnoreDeleteEventTarget(event.target)
  ) {
    return false
  }

  event.__sluvoUndoHandled = true
  event.preventDefault()
  event.stopPropagation()
  event.stopImmediatePropagation?.()
  if (!undoShortcutLocked && !event.repeat && window.performance.now() - lastUndoShortcutAt > 180) {
    undoShortcutLocked = true
    lastUndoShortcutAt = window.performance.now()
    if (event.shiftKey) {
      redoLastChange()
    } else {
      undoLastChange()
    }
  }
  return true
}

function releaseUndoShortcut(event) {
  if (event?.key?.toLowerCase?.() === 'z' || event?.key === 'Control' || event?.key === 'Meta') {
    undoShortcutLocked = false
  }
}

function updateFrameSize() {
  const rect = canvasFrame.value?.getBoundingClientRect?.()
  frameSize.width = Math.max(rect?.width || window.innerWidth || 1, 1)
  frameSize.height = Math.max(rect?.height || window.innerHeight || 1, 1)
  scheduleDirectPortLayoutRefresh()
}

function scheduleDirectPortLayoutRefresh() {
  window.cancelAnimationFrame(directPortLayoutRaf)
  directPortLayoutRaf = window.requestAnimationFrame(() => {
    directPortLayoutRaf = 0
    directPortLayoutRevision.value += 1
  })
}

function updateCanvasSpotlight(event) {
  const frame = canvasFrame.value
  if (!frame || !event || typeof event.clientX !== 'number') return

  const rect = frame.getBoundingClientRect()
  const inside =
    event.clientX >= rect.left &&
    event.clientX <= rect.right &&
    event.clientY >= rect.top &&
    event.clientY <= rect.bottom

  if (!inside) {
    resetCanvasSpotlight()
    return
  }

  frame.style.setProperty('--canvas-focus-x', `${event.clientX - rect.left}px`)
  frame.style.setProperty('--canvas-focus-y', `${event.clientY - rect.top}px`)
  frame.style.setProperty('--canvas-focus-opacity', '1')
}

function resetCanvasSpotlight() {
  const frame = canvasFrame.value
  if (!frame) return
  frame.style.setProperty('--canvas-focus-opacity', '0')
}

function projectMinimapRect(rect) {
  const bounds = minimapBounds.value
  const mapWidth = 180
  const mapHeight = 82
  const scale = Math.min(mapWidth / bounds.width, mapHeight / bounds.height)
  const drawnWidth = bounds.width * scale
  const drawnHeight = bounds.height * scale
  const offsetX = (mapWidth - drawnWidth) / 2
  const offsetY = (mapHeight - drawnHeight) / 2

  return {
    x: offsetX + (rect.x - bounds.x) * scale,
    y: offsetY + (rect.y - bounds.y) * scale,
    width: Math.max(rect.width * scale, 2),
    height: Math.max(rect.height * scale, 2)
  }
}

function getWorkflowNodeSize(node) {
  if (node.data?.kind === 'group') {
    return {
      width: Number.parseFloat(node.style?.width) || node.width || 520,
      height: Number.parseFloat(node.style?.height) || node.height || 320
    }
  }

  const type = node.data?.nodeType
  if (type === 'image_unit') return { width: 780, height: 620 }
  if (type === 'video_unit' || type === 'media_board') return { width: 560, height: 560 }
  if (type === 'script_episode' || type === 'storyboard_table') return { width: 480, height: 520 }
  if (type === 'asset_table') return { width: 520, height: 500 }
  return { width: 440, height: 520 }
}

function updateMagneticTargets(event) {
  if (!event || typeof event.clientX !== 'number' || typeof document === 'undefined') return

  const range = 72
  document.querySelectorAll('.magnetic-target').forEach((target) => {
    if (!(target instanceof HTMLElement)) return
    const rect = target.getBoundingClientRect()
    const centerX = rect.left + rect.width / 2
    const centerY = rect.top + rect.height / 2
    const distance = Math.hypot(event.clientX - centerX, event.clientY - centerY)

    if (distance > range) {
      resetMagneticTarget(target)
      return
    }

    const pull = (1 - distance / range) * 0.34
    target.style.setProperty('--magnet-x', `${(event.clientX - centerX) * pull}px`)
    target.style.setProperty('--magnet-y', `${(event.clientY - centerY) * pull}px`)
    target.style.setProperty('--magnet-scale', `${1 + (1 - distance / range) * 0.16}`)
    target.classList.add('is-magnetized')
  })
}

function resetMagneticTarget(target) {
  target.style.removeProperty('--magnet-x')
  target.style.removeProperty('--magnet-y')
  target.style.removeProperty('--magnet-scale')
  target.classList.remove('is-magnetized')
}

function resetMagneticTargets() {
  if (typeof document === 'undefined') return
  document.querySelectorAll('.magnetic-target').forEach((target) => {
    if (target instanceof HTMLElement) resetMagneticTarget(target)
  })
}

function resetHoverEffects() {
  resetMagneticTargets()
  resetCanvasSpotlight()
}

function getDirectNodeIdFromEvent(event) {
  const target = event.target instanceof Element ? event.target : null
  return target?.closest('.direct-workflow-node')?.getAttribute('data-direct-node-id') || ''
}

function isDeleteKey(event) {
  return (
    event.key === 'Delete' ||
    event.key === 'Backspace' ||
    event.key === 'Del' ||
    event.key === 'Back' ||
    event.code === 'Delete' ||
    event.code === 'Backspace' ||
    event.keyCode === 46 ||
    event.keyCode === 8
  )
}

function isPasteShortcut(event) {
  return Boolean((event.ctrlKey || event.metaKey) && event.key?.toLowerCase?.() === 'v' && !event.altKey)
}

function shouldIgnorePasteEventTarget(target) {
  return isTypingTarget(target) && !isDeleteKeySinkTarget(target)
}

function handleCanvasPasteShortcutEvent(event) {
  if (!isPasteShortcut(event) || shouldIgnorePasteEventTarget(event.target)) return false

  queueCanvasClipboardPasteFallback()
  return true
}

function shouldIgnoreDeleteEventTarget(target) {
  return isTypingTarget(target) && !(target instanceof HTMLElement && target.classList.contains('delete-key-sink'))
}

function deleteActiveDirectNodes(event) {
  const targetNodeId = getDirectNodeIdFromEvent(event)
  const ids = new Set(selectedDirectNodeIds.value)
  if (targetNodeId && !ids.has(targetNodeId)) ids.add(targetNodeId)
  if (ids.size === 0 && activeDirectNodeId.value) ids.add(activeDirectNodeId.value)
  const existingIds = [...ids].filter((id) => directNodes.value.some((node) => node.id === id))
  if (existingIds.length === 0) return false

  event.preventDefault()
  event.stopPropagation()
  event.stopImmediatePropagation?.()
  deleteDirectNodesByIds(existingIds)
  return true
}

function deleteLastTouchedDirectNode(event) {
  const targetNodeId = getDirectNodeIdFromEvent(event)
  const candidates = [
    targetNodeId,
    activeDirectNodeId.value,
    ...selectedDirectNodeIds.value,
    focusedDirectNodeId.value,
    lastTouchedDirectNodeId.value
  ].filter(Boolean)
  const nodeId = candidates.find((id) => directNodes.value.some((node) => node.id === id))
  if (!nodeId) return false

  event.preventDefault()
  event.stopPropagation()
  event.stopImmediatePropagation?.()
  deleteDirectNodesByIds([nodeId])
  return true
}

function handleDeleteSinkKey(event) {
  if (event.type === 'keydown' && handleCanvasPasteShortcutEvent(event)) return
  if (!isDeleteKey(event)) return
  event.preventDefault()
  event.stopPropagation()
  event.stopImmediatePropagation?.()
  if (!deleteActiveDirectNodes(event) && directNodes.value.length > 0) {
    const fallbackId = activeDirectNodeId.value || selectedDirectNodeIds.value[0] || focusedDirectNodeId.value || lastTouchedDirectNodeId.value
    if (fallbackId) deleteDirectNodesByIds([fallbackId])
  }
}

function handleDeleteSinkNative(event) {
  if (!isDeleteKey(event)) return
  if (!deleteActiveDirectNodes(event) && directNodes.value.length > 0) {
    event.preventDefault()
    event.stopPropagation()
    event.stopImmediatePropagation?.()
    const fallbackId = activeDirectNodeId.value || selectedDirectNodeIds.value[0] || focusedDirectNodeId.value || lastTouchedDirectNodeId.value
    if (fallbackId) deleteDirectNodesByIds([fallbackId])
  }
}

function handleKeydown(event) {
  if (handleGlobalUndoShortcut(event)) return
  const command = event.ctrlKey || event.metaKey

  if (event.code === 'Space' && !isTypingTarget(event.target)) {
    spacePanning.value = true
  }

  if (command && event.key.toLowerCase() === 'c') {
    if (isTextInteractionTarget(event.target) || hasNativeTextSelection()) return
    event.preventDefault()
    copySelection()
    return
  }

  if (handleCanvasPasteShortcutEvent(event)) return

  if (command && event.key.toLowerCase() === 'd') {
    event.preventDefault()
    duplicateSelection()
    return
  }

  if (command && event.key.toLowerCase() === 'g') {
    event.preventDefault()
    groupSelection()
    return
  }

  if (command && event.key === '0') {
    event.preventDefault()
    locateCanvas()
    return
  }

  if (command && (event.key === '=' || event.key === '+')) {
    event.preventDefault()
    handleZoomIn()
    return
  }

  if (command && event.key === '-') {
    event.preventDefault()
    handleZoomOut()
    return
  }

  if (isDeleteKey(event) && !shouldIgnoreDeleteEventTarget(event.target)) {
    event.preventDefault()
    if (deleteActiveDirectNodes(event)) return
    deleteSelection()
    return
  }

  if (event.key === 'Escape') {
    if (imagePreview.visible) {
      closeImagePreview()
      return
    }
    if (audioVoicePicker.visible) {
      closeAudioVoicePicker()
      return
    }
    closeFloatingPanels()
  }

  if (!command && !event.shiftKey && !event.altKey && !isTypingTarget(event.target)) {
    const panStep = 80
    if (event.key === 'ArrowLeft') panBy({ x: panStep, y: 0 })
    if (event.key === 'ArrowRight') panBy({ x: -panStep, y: 0 })
    if (event.key === 'ArrowUp') panBy({ x: 0, y: panStep })
    if (event.key === 'ArrowDown') panBy({ x: 0, y: -panStep })
  }
}

function handleKeyup(event) {
  releaseUndoShortcut(event)

  if (isDeleteKey(event) && !shouldIgnoreDeleteEventTarget(event.target)) {
    deleteActiveDirectNodes(event)
    return
  }

  if (event.code === 'Space') {
    spacePanning.value = false
  }
}

function isTypingTarget(target) {
  return (
    target instanceof HTMLElement &&
    (['INPUT', 'TEXTAREA', 'SELECT'].includes(target.tagName) || Boolean(target.closest('[contenteditable="true"], .text-node-ai-composer, .canvas-agent-panel, .publish-dialog')))
  )
}

function isTextInteractionTarget(target) {
  return (
    target instanceof HTMLElement &&
    Boolean(target.closest('input, textarea, select, [contenteditable="true"], .direct-workflow-node__markdown, .direct-workflow-node__prompt, .text-node-ai-composer, .canvas-agent-panel, .publish-dialog'))
  )
}

function hasNativeTextSelection() {
  const selection = window.getSelection?.()
  return Boolean(selection && !selection.isCollapsed && String(selection.toString() || '').trim())
}

function isSelectAllShortcut(event) {
  return Boolean((event.ctrlKey || event.metaKey) && !event.altKey && event.key?.toLowerCase?.() === 'a')
}

function selectTextElementContents(element) {
  if (!(element instanceof HTMLElement)) return false
  const selection = window.getSelection?.()
  const range = document.createRange?.()
  if (!selection || !range) return false
  range.selectNodeContents(element)
  selection.removeAllRanges()
  selection.addRange(range)
  return true
}

function handleMarkdownKeydown(event) {
  if (!isSelectAllShortcut(event)) return
  event.preventDefault()
  event.stopPropagation()
  selectTextElementContents(event.currentTarget)
}

function handleFramePointerDown(event) {
  if (event.button !== 0 || isTypingTarget(event.target)) return

  const target = event.target instanceof Element ? event.target : null
  if (
    target?.closest(
      '.direct-workflow-node, .direct-group-frame, .direct-group-toolbar, .direct-selection-frame, .vue-flow__node, .add-node-menu, .libtv-topbar, .canvas-tool-rail, .canvas-bottom-controls, .canvas-minimap, .rail-panel, .history-overlay, .library-picker-overlay, .starter-strip, .canvas-help-panel, .canvas-context-menu, .publish-overlay, .audio-voice-overlay, .canvas-agent-panel, .canvas-agent-trigger'
    )
  ) {
    return
  }

  closeFloatingPanels()
  canvasStore.clearSelection()
  selectedDirectNodeIds.value = []
  focusedDirectNodeId.value = ''
  activeDirectNodeId.value = ''
  lastTouchedDirectNodeId.value = ''
  suppressNextPaneClick.value = false
  selectionBox.active = true
  selectionBox.start = { x: event.clientX, y: event.clientY }
  selectionBox.current = { x: event.clientX, y: event.clientY }
}

function handleCanvasWheel(event) {
  if (!isCanvasWheelPanTarget(event.target)) return
  if (handleScrollableCanvasControlWheel(event)) return

  event.preventDefault()
  event.stopPropagation()

  if (event.ctrlKey || event.metaKey) {
    zoomCanvasByWheel(event)
    return
  }

  const nextViewport = {
    x: Number(viewport.value?.x || 0) - normalizeWheelDelta(event.deltaX),
    y: Number(viewport.value?.y || 0) - normalizeWheelDelta(event.deltaY),
    zoom: Number(viewport.value?.zoom || 1)
  }

  setViewport(nextViewport, { duration: 0 })
  canvasStore.setViewport(nextViewport)
  syncPendingReferenceMenuScreen()
  scheduleCanvasSave(900)
}

function zoomCanvasByWheel(event) {
  const frame = canvasFrame.value
  const rect = frame?.getBoundingClientRect?.()
  if (!rect) return

  const currentZoom = Number(viewport.value?.zoom || 1)
  const nextZoom = clampNumber(currentZoom * Math.exp(-event.deltaY * 0.0012), 0.22, 2)
  if (!Number.isFinite(nextZoom) || Math.abs(nextZoom - currentZoom) < 0.001) return

  const flowPoint = screenToFlowCoordinate({ x: event.clientX, y: event.clientY })
  const pointerX = event.clientX - rect.left
  const pointerY = event.clientY - rect.top
  const nextViewport = {
    x: pointerX - flowPoint.x * nextZoom,
    y: pointerY - flowPoint.y * nextZoom,
    zoom: nextZoom
  }

  setViewport(nextViewport, { duration: 0 })
  canvasStore.setViewport(nextViewport)
  syncPendingReferenceMenuScreen()
  scheduleCanvasSave(900)
}

function isCanvasWheelPanTarget(target) {
  const element = target instanceof Element ? target : null
  if (!element) return true
  return !element.closest(
    '.libtv-topbar, .canvas-tool-rail, .canvas-bottom-controls, .canvas-minimap, .rail-panel, .history-overlay, .library-picker-overlay, .starter-strip, .canvas-help-panel, .canvas-context-menu, .add-node-menu, .publish-overlay, .canvas-agent-panel, .canvas-agent-trigger'
  )
}

function handleScrollableCanvasControlWheel(event) {
  const element = event.target instanceof Element ? event.target : null
  const scrollable = element?.closest?.(
    'textarea, .direct-workflow-node__markdown, .direct-workflow-node__prompt, .direct-workflow-node__prompt-field, .text-node-ai-composer, .canvas-agent-panel__messages, .canvas-agent-panel__composer textarea, .canvas-agent-template-form textarea, .audio-inline-settings, .audio-voice-list, .generated-audio__preview'
  )
  if (!(scrollable instanceof HTMLElement)) return false

  event.preventDefault()
  event.stopPropagation()

  if (scrollable.scrollHeight > scrollable.clientHeight + 1) {
    scrollable.scrollTop += getWheelScrollDelta(event)
  }
  return true
}

function normalizeWheelDelta(value) {
  if (!Number.isFinite(value)) return 0
  return clampNumber(value, -120, 120)
}

function getWheelScrollDelta(event) {
  const delta = Number(event.deltaY || 0)
  if (!Number.isFinite(delta)) return 0
  if (event.deltaMode === WheelEvent.DOM_DELTA_LINE) return delta * 16
  if (event.deltaMode === WheelEvent.DOM_DELTA_PAGE) {
    const element = event.target instanceof Element
      ? event.target.closest?.(
          'textarea, .direct-workflow-node__markdown, .direct-workflow-node__prompt, .direct-workflow-node__prompt-field, .text-node-ai-composer, .canvas-agent-panel__messages, .canvas-agent-panel__composer textarea, .canvas-agent-template-form textarea, .audio-inline-settings, .audio-voice-list, .generated-audio__preview'
        )
      : null
    return delta * Math.max(element?.clientHeight || 360, 1)
  }
  return delta
}

function clampNumber(value, min, max) {
  return Math.min(Math.max(value, min), max)
}

function handleWindowPointerMove(event) {
  updateCanvasSpotlight(event)
  updateMagneticTargets(event)

  if (directConnection.active) {
    directConnection.current = screenToFlowCoordinate({ x: event.clientX, y: event.clientY })
    return
  }

  if (directDrag.active) {
    moveDirectNodes(event)
    return
  }

  if (!selectionBox.active) return
  selectionBox.current = { x: event.clientX, y: event.clientY }
  const rect = getSelectionRect()
  if (rect.width > 4 || rect.height > 4) {
    suppressNextPaneClick.value = true
    selectedDirectNodeIds.value = expandDirectGroupSelection(directNodes.value
      .filter((node) => intersectsRect(rect, getDirectNodeScreenRect(node)))
      .map((node) => node.id))
    activeDirectNodeId.value = selectedDirectNodeIds.value.at(-1) || ''
    focusedDirectNodeId.value = activeDirectNodeId.value
  }
}

function handleWindowPointerUp(event) {
  resetMagneticTargets()

  if (directConnection.active) {
    finishDirectConnection(event)
    return
  }

  if (directDrag.active) {
    directDrag.active = false
    directDrag.originals = []
    flushDeferredInteractionSave()
    return
  }

  if (!selectionBox.active) return

  const rect = getSelectionRect()
  const wasDraggingSelection = rect.width > 4 || rect.height > 4
  selectedDirectNodeIds.value = expandDirectGroupSelection(directNodes.value
    .filter((node) => intersectsRect(rect, getDirectNodeScreenRect(node)))
    .map((node) => node.id))
  activeDirectNodeId.value = selectedDirectNodeIds.value.at(-1) || ''
  focusedDirectNodeId.value = activeDirectNodeId.value
  lastTouchedDirectNodeId.value = activeDirectNodeId.value
  if (activeDirectNodeId.value) focusDeleteKeySink()
  suppressNextPaneClick.value = wasDraggingSelection
  selectionBox.active = false
  flushDeferredInteractionSave()
}

function startDirectConnection(event, nodeId, side = 'right') {
  if (event.pointerId !== undefined) {
    event.target?.setPointerCapture?.(event.pointerId)
  }
  const sourceNode = directNodes.value.find((node) => node.id === nodeId)
  if (!sourceNode) return

  const sourceSide = side === 'left' ? 'left' : 'right'
  const start = getDirectNodePortPosition(sourceNode, sourceSide)
  directConnection.active = true
  directConnection.sourceId = nodeId
  directConnection.sourceSide = sourceSide
  directConnection.start = start
  directConnection.current = screenToFlowCoordinate({ x: event.clientX, y: event.clientY })
  pendingDirectConnection.sourceId = nodeId
  pendingDirectConnection.sourceSide = sourceSide
  pendingDirectConnection.start = start
  pendingDirectConnection.point = directConnection.current
  selectedDirectNodeIds.value = [nodeId]
  activeDirectNodeId.value = nodeId
  lastTouchedDirectNodeId.value = nodeId
}

function startDirectGroupConnection(event, group, side = 'right') {
  if (event.pointerId !== undefined) {
    event.target?.setPointerCapture?.(event.pointerId)
  }
  if (!group?.id || !group?.bounds) return

  const sourceSide = side === 'left' ? 'left' : 'right'
  const start = getDirectGroupPortFlowPosition(group, sourceSide)
  directConnection.active = true
  directConnection.sourceId = group.id
  directConnection.sourceSide = sourceSide
  directConnection.start = start
  directConnection.current = screenToFlowCoordinate({ x: event.clientX, y: event.clientY })
  pendingDirectConnection.sourceId = group.id
  pendingDirectConnection.sourceSide = sourceSide
  pendingDirectConnection.start = start
  pendingDirectConnection.point = directConnection.current
  selectedDirectNodeIds.value = getDirectGroupMemberIds(group.id)
  activeDirectNodeId.value = selectedDirectNodeIds.value.at(-1) || ''
  focusedDirectNodeId.value = activeDirectNodeId.value
  lastTouchedDirectNodeId.value = activeDirectNodeId.value
  canvasStore.clearSelection()
}

function finishDirectConnection(event) {
  const point = { ...directConnection.current }
  const sourceId = directConnection.sourceId
  const sourceSide = directConnection.sourceSide
  const targetId = findDirectConnectionTarget(event, sourceId, point)
  pendingDirectConnection.sourceId = directConnection.sourceId
  pendingDirectConnection.sourceSide = sourceSide
  pendingDirectConnection.start = { ...directConnection.start }
  pendingDirectConnection.point = point
  directConnection.active = false

  if (targetId) {
    rememberHistory()
    const edgeSourceId = sourceSide === 'left' ? targetId : sourceId
    const edgeTargetId = sourceSide === 'left' ? sourceId : targetId
    directEdges.value = upsertDirectEdge(edgeSourceId, edgeTargetId)
    clearPendingDirectConnection()
    selectedDirectNodeIds.value = [targetId]
    activeDirectNodeId.value = targetId
    focusedDirectNodeId.value = targetId
    lastTouchedDirectNodeId.value = targetId
    showToast('\u5df2\u8fde\u63a5\u8282\u70b9')
    flushDeferredInteractionSave()
    return
  }

  if (isDirectGroupId(sourceId)) {
    referenceMenu.visible = false
    addMenu.visible = true
    addMenu.screen = clampMenuPosition(flowToScreenCoordinate(point), 300, 580)
    addMenu.originScreen = flowToScreenCoordinate(point)
    addMenu.flow = point
  } else {
    referenceMenu.visible = true
    referenceMenu.sourceId = ''
    referenceMenu.sourceHandle = 'direct'
    referenceMenu.flow = point
    syncPendingReferenceMenuScreen()
    addMenu.visible = false
  }
  contextMenu.visible = false
}

function findDirectConnectionTarget(event, sourceId, flowPoint = null) {
  const point = getPointerPoint(event)

  if (point) {
    const hovered = document.elementFromPoint(point.x, point.y)
    const directNodeId = hovered?.closest?.('.direct-workflow-node')?.getAttribute('data-direct-node-id') || ''
    if (directNodeId && isValidDirectConnectionTarget(sourceId, directNodeId)) return directNodeId
  }

  const targetNode = directNodes.value.find((node) => {
    if (!isValidDirectConnectionTarget(sourceId, node.id)) return false
    if (point) {
      const rect = getDirectNodeScreenRect(node)
      return point.x >= rect.x && point.x <= rect.x + rect.width && point.y >= rect.y && point.y <= rect.y + rect.height
    }

    if (!flowPoint) return false
    const size = getDirectNodeSize(node.type)
    return flowPoint.x >= node.x && flowPoint.x <= node.x + size.width && flowPoint.y >= node.y && flowPoint.y <= node.y + size.height
  })

  return targetNode?.id || ''
}

function isValidDirectConnectionTarget(sourceId, targetId) {
  if (!targetId || targetId === sourceId) return false
  if (isDirectGroupId(sourceId) && getDirectGroupMemberIds(sourceId).includes(targetId)) return false
  if (isDirectImageOnlyGroup(sourceId)) {
    const target = directNodes.value.find((node) => node.id === targetId)
    return target?.type === 'image_unit' || target?.type === 'video_unit'
  }
  return true
}

function isDirectEndpointAvailable(endpointId) {
  if (!endpointId) return false
  return directNodes.value.some((node) => node.id === endpointId) || directNodeGroups.value.some((group) => group.id === endpointId)
}

function isDirectGroupId(groupId) {
  return Boolean(groupId && directNodes.value.some((node) => node.groupId === groupId))
}

function getDirectGroupMemberIds(groupId) {
  if (!groupId) return []
  return directNodes.value.filter((node) => node.groupId === groupId).map((node) => node.id)
}

function getDirectGroupMembers(groupId) {
  if (!groupId) return []
  return directNodes.value.filter((node) => node.groupId === groupId)
}

function isDirectImageReferenceSource(node) {
  return Boolean(getDirectImageReferenceFromNode(node))
}

function isDirectImageOnlyGroup(groupId) {
  const members = getDirectGroupMembers(groupId)
  return members.length > 0 && members.every(isDirectImageReferenceSource)
}

function getPendingConnectionAllowedMenuItems() {
  if (pendingDirectConnection.sourceId && isDirectImageOnlyGroup(pendingDirectConnection.sourceId)) {
    return ['image', 'video']
  }
  return []
}

function upsertDirectEdge(sourceId, targetId) {
  const exists = directEdges.value.some((edge) => edge.sourceId === sourceId && edge.targetId === targetId)
  if (exists) return directEdges.value

  return [
    ...directEdges.value,
    {
      id: `direct-edge-${Date.now()}-${Math.round(Math.random() * 10000)}`,
      clientId: `direct-edge-client-${Date.now()}-${Math.round(Math.random() * 10000)}`,
      sourceId,
      targetId
    }
  ]
}

function getDirectEdgePath(edge) {
  directPortLayoutRevision.value
  const sourcePosition = getDirectEndpointPortPosition(edge.sourceId, 'right')
  const targetPosition = getDirectEndpointPortPosition(edge.targetId, 'left')
  if (!sourcePosition || !targetPosition) return ''

  return buildDirectCurvePath(sourcePosition, targetPosition)
}

function getDraftEdgePath() {
  const targetSide = directConnection.sourceSide === 'left' ? 'right' : 'left'
  return buildDirectCurvePath(directConnection.start, directConnection.current, directConnection.sourceSide, targetSide)
}

function getPendingDirectEdgePath() {
  const targetSide = pendingDirectConnection.sourceSide === 'left' ? 'right' : 'left'
  return buildDirectCurvePath(
    pendingDirectConnection.start,
    pendingDirectConnection.point,
    pendingDirectConnection.sourceSide,
    targetSide
  )
}

function syncPendingReferenceMenuScreen() {
  if (!referenceMenu.visible || !pendingDirectConnection.sourceId) return

  const screen = flowToScreenCoordinate(referenceMenu.flow)
  referenceMenu.screen = clampMenuPosition({ x: screen.x + 20, y: screen.y - 150 }, 300, 460)
}

function buildDirectCurvePath(source, target, sourceSide = 'right', targetSide = 'left') {
  if (!source || !target) return ''

  const distance = Math.max(140, Math.abs(target.x - source.x) * 0.5)
  const sourceDirection = sourceSide === 'left' ? -1 : 1
  const targetDirection = targetSide === 'right' ? 1 : -1
  const sourceControlX = source.x + distance * sourceDirection
  const targetControlX = target.x + distance * targetDirection

  return `M ${source.x} ${source.y} C ${sourceControlX} ${source.y}, ${targetControlX} ${target.y}, ${target.x} ${target.y}`
}

function getDirectNodePortPosition(node, side) {
  const domPosition = getDirectNodePortLocalDomPosition(node.id, side)
  if (domPosition) return domPosition

  return getDirectNodePortFlowPosition(node, side)
}

function getDirectEndpointPortPosition(endpointId, side = 'right') {
  const node = directNodes.value.find((item) => item.id === endpointId)
  if (node) return getDirectNodePortPosition(node, side)

  const group = directNodeGroups.value.find((item) => item.id === endpointId)
  if (group) return getDirectGroupPortFlowPosition(group, side)

  return null
}

function getDirectNodePortFlowPosition(node, side) {
  return {
    x: side === 'right' ? node.x + getDirectNodeSize(node.type).width : node.x,
    y: node.y + getDirectNodePortOffsetY(node.type)
  }
}

function getDirectNodePortLocalDomPosition(nodeId, side) {
  const nodeElement = directNodeElements.get(nodeId)
  const portElement = nodeElement?.querySelector?.(`.direct-workflow-node__port--${side}`)
  if (!nodeElement || !portElement) return null

  let left = 0
  let top = 0
  let current = portElement
  while (current && current !== nodeElement) {
    left += current.offsetLeft || 0
    top += current.offsetTop || 0
    current = current.offsetParent
  }
  if (current !== nodeElement) return null
  const node = directNodes.value.find((item) => item.id === nodeId)
  if (!node) return null

  return {
    x: node.x + left + portElement.offsetWidth / 2,
    y: node.y + top
  }
}

function getDirectNodePortOffsetY(type) {
  const size = getDirectNodeSize(type)
  const titleHeight = isCompactCanvas.value ? 24 : 30
  const defaultFrameHeight = isCompactCanvas.value ? 346 : 470
  const frameHeight = type === 'uploaded_asset' ? size.height - titleHeight - 8 : defaultFrameHeight
  return titleHeight + frameHeight / 2
}

function flowToScreenCoordinate(point) {
  const zoom = viewport.value?.zoom || 1

  return {
    x: (viewport.value?.x || 0) + point.x * zoom,
    y: (viewport.value?.y || 0) + point.y * zoom
  }
}

function flowBoundsToScreenBounds(bounds) {
  if (!bounds) return null
  const zoom = Number(viewport.value?.zoom || 1)
  const safeZoom = zoom > 0 ? zoom : 1
  return {
    x: Number(viewport.value?.x || 0) + bounds.x * safeZoom,
    y: Number(viewport.value?.y || 0) + bounds.y * safeZoom,
    width: bounds.width * safeZoom,
    height: bounds.height * safeZoom
  }
}

function handleDirectNodePointerDown(event, nodeId) {
  if (event.button !== 0) return
  closeFloatingPanels()
  const currentNode = directNodes.value.find((node) => node.id === nodeId)
  if (isDirectPromptEditTarget(event.target)) {
    focusedDirectNodeId.value = nodeId
    activeDirectNodeId.value = nodeId
    lastTouchedDirectNodeId.value = nodeId
    if (!selectedDirectNodeIds.value.includes(nodeId)) {
      selectedDirectNodeIds.value = [nodeId]
    }
    canvasStore.clearSelection()
    return
  }
  event.preventDefault()
  canvasFrame.value?.focus?.({ preventScroll: true })
  focusedDirectNodeId.value = nodeId
  activeDirectNodeId.value = nodeId
  lastTouchedDirectNodeId.value = nodeId
  focusDeleteKeySink()

  if (event.shiftKey) {
    const groupIds = getDirectNodeGroupMembers(nodeId)
    const current = new Set(selectedDirectNodeIds.value)
    const shouldRemove = groupIds.every((id) => current.has(id))
    groupIds.forEach((id) => {
      if (shouldRemove) current.delete(id)
      else current.add(id)
    })
    selectedDirectNodeIds.value = [...current].filter((id) => directNodes.value.some((node) => node.id === id))
    return
  }

  if (currentNode?.groupId) {
    selectedDirectNodeIds.value = [nodeId]
  } else if (!selectedDirectNodeIds.value.includes(nodeId)) {
    selectedDirectNodeIds.value = [nodeId]
  } else {
    selectedDirectNodeIds.value = [nodeId]
  }
  canvasStore.clearSelection()
  directDrag.active = true
  directDrag.startScreen = { x: event.clientX, y: event.clientY }
  directDrag.originals = directNodes.value
    .filter((node) => selectedDirectNodeIds.value.includes(node.id))
    .map((node) => ({ id: node.id, x: node.x, y: node.y }))
}

function handleDirectGroupPointerDown(event, groupId) {
  if (event.button !== 0) return
  const ids = directNodes.value.filter((node) => node.groupId === groupId).map((node) => node.id)
  if (ids.length < 2) return

  closeFloatingPanels()
  event.preventDefault()
  canvasFrame.value?.focus?.({ preventScroll: true })
  selectedDirectNodeIds.value = ids
  activeDirectNodeId.value = ids.at(-1) || ''
  focusedDirectNodeId.value = activeDirectNodeId.value
  lastTouchedDirectNodeId.value = activeDirectNodeId.value
  canvasStore.clearSelection()
  focusDeleteKeySink()

  directDrag.active = true
  directDrag.startScreen = { x: event.clientX, y: event.clientY }
  directDrag.originals = directNodes.value
    .filter((node) => ids.includes(node.id))
    .map((node) => ({ id: node.id, x: node.x, y: node.y }))
}

function registerDirectNodeElement(nodeId, element) {
  if (element) {
    directNodeElements.set(nodeId, element)
  } else {
    directNodeElements.delete(nodeId)
  }
}

function focusDirectNode(nodeId) {
  nextTick(() => {
    directNodeElements.get(nodeId)?.focus?.({ preventScroll: true })
  })
}

function focusDeleteKeySink() {
  nextTick(() => {
    deleteKeySink.value?.focus?.({ preventScroll: true })
  })
}

function moveDirectNodes(event) {
  const zoom = viewport.value?.zoom || 1
  const dx = (event.clientX - directDrag.startScreen.x) / zoom
  const dy = (event.clientY - directDrag.startScreen.y) / zoom
  const originalMap = new Map(directDrag.originals.map((node) => [node.id, node]))

  directNodes.value = directNodes.value.map((node) => {
    const original = originalMap.get(node.id)
    if (!original) return node
    return {
      ...node,
      x: original.x + dx,
      y: original.y + dy
    }
  })
}

function getDirectNodeGroupMembers(nodeId) {
  const node = directNodes.value.find((item) => item.id === nodeId)
  if (!node?.groupId) return node ? [node.id] : []
  return directNodes.value.filter((item) => item.groupId === node.groupId).map((item) => item.id)
}

function expandDirectGroupSelection(ids) {
  const next = new Set(ids)
  ids.forEach((id) => getDirectNodeGroupMembers(id).forEach((memberId) => next.add(memberId)))
  return [...next].filter((id) => directNodes.value.some((node) => node.id === id))
}

function getDirectNodeGroupSelection(nodeId) {
  const selected = new Set(selectedDirectNodeIds.value)
  getDirectNodeGroupMembers(nodeId).forEach((id) => selected.add(id))
  return [...selected].filter((id) => directNodes.value.some((node) => node.id === id))
}

function getDirectNodeScreenBounds(items) {
  if (!items.length) return null
  const rects = items.map(getDirectNodeScreenRect)
  const left = Math.min(...rects.map((rect) => rect.x))
  const top = Math.min(...rects.map((rect) => rect.y))
  const right = Math.max(...rects.map((rect) => rect.x + rect.width))
  const bottom = Math.max(...rects.map((rect) => rect.y + rect.height))
  return { x: left, y: top, width: right - left, height: bottom - top }
}

function getDirectNodeFlowBounds(items) {
  if (!items.length) return null
  const left = Math.min(...items.map((node) => node.x))
  const top = Math.min(...items.map((node) => node.y))
  const right = Math.max(...items.map((node) => node.x + getDirectNodeSize(node.type).width))
  const bottom = Math.max(...items.map((node) => node.y + getDirectNodeSize(node.type).height))
  return { x: left, y: top, width: right - left, height: bottom - top }
}

function getSelectedDirectScreenBounds() {
  return flowBoundsToScreenBounds(getDirectNodeFlowBounds(selectedDirectNodes.value))
}

function getDirectGroupFrameStyle(group) {
  const frame = getDirectGroupFrameFlowBounds(group)
  if (!frame) return {}
  return {
    left: `${frame.x}px`,
    top: `${frame.y}px`,
    width: `${frame.width}px`,
    height: `${frame.height}px`
  }
}

function getDirectGroupFrameFlowBounds(group) {
  const bounds = group?.bounds
  if (!bounds) return null
  const paddingX = 70
  const paddingTop = 54
  const paddingBottom = 28
  return {
    x: bounds.x - paddingX,
    y: bounds.y - paddingTop,
    width: bounds.width + paddingX * 2,
    height: bounds.height + paddingTop + paddingBottom
  }
}

function getDirectGroupPortFlowPosition(group, side = 'right') {
  const frame = getDirectGroupFrameFlowBounds(group)
  if (!frame) return { x: 0, y: 0 }
  return {
    x: side === 'left' ? frame.x : frame.x + frame.width,
    y: frame.y + frame.height / 2
  }
}

function groupSelectedDirectNodes() {
  const selectedIds = new Set(selectedDirectNodeIds.value)
  const ids = directNodes.value.filter((node) => selectedIds.has(node.id)).map((node) => node.id)
  if (ids.length < 2) {
    showToast('至少选择两个节点才能打组')
    return
  }
  rememberHistory()
  const groupId = `direct-group-${Date.now()}-${Math.round(Math.random() * 10000)}`
  const groupTitle = `分组 ${ids.length} 个节点`
  directNodes.value = directNodes.value.map((node) => (ids.includes(node.id) ? { ...node, groupId, groupTitle } : node))
  selectedDirectNodeIds.value = ids
  activeDirectNodeId.value = ids.at(-1) || ''
  focusedDirectNodeId.value = activeDirectNodeId.value
  lastTouchedDirectNodeId.value = activeDirectNodeId.value
  flushDeferredInteractionSave()
  showToast('已打组')
}

function ungroupSelectedDirectNodes() {
  const groupIds = new Set(selectedDirectNodes.value.map((node) => node.groupId).filter(Boolean))
  if (selectedDirectGroupId.value) groupIds.add(selectedDirectGroupId.value)
  if (groupIds.size === 0) return
  rememberHistory()
  const releasedIds = directNodes.value.filter((node) => groupIds.has(node.groupId)).map((node) => node.id)
  directNodes.value = directNodes.value.map((node) => (groupIds.has(node.groupId) ? { ...node, groupId: '', groupTitle: '' } : node))
  directEdges.value = directEdges.value.filter((edge) => !groupIds.has(edge.sourceId) && !groupIds.has(edge.targetId))
  selectedDirectNodeIds.value = releasedIds
  activeDirectNodeId.value = releasedIds.at(-1) || ''
  focusedDirectNodeId.value = activeDirectNodeId.value
  lastTouchedDirectNodeId.value = activeDirectNodeId.value
  flushDeferredInteractionSave()
  showToast('已解组')
}

function getSelectionRect() {
  const left = Math.min(selectionBox.start.x, selectionBox.current.x)
  const top = Math.min(selectionBox.start.y, selectionBox.current.y)
  return {
    x: left,
    y: top,
    width: Math.abs(selectionBox.current.x - selectionBox.start.x),
    height: Math.abs(selectionBox.current.y - selectionBox.start.y)
  }
}

function getDirectNodeScreenRect(node) {
  const elementRect = directNodeElements.get(node.id)?.getBoundingClientRect?.()
  if (elementRect) {
    return {
      x: elementRect.left,
      y: elementRect.top,
      width: elementRect.width,
      height: elementRect.height
    }
  }

  const zoom = viewport.value?.zoom || 1
  return {
    x: (viewport.value?.x || 0) + node.x * zoom,
    y: (viewport.value?.y || 0) + node.y * zoom,
    width: getDirectNodeSize(node.type).width * zoom,
    height: getDirectNodeSize(node.type).height * zoom
  }
}

function intersectsRect(a, b) {
  return a.x <= b.x + b.width && a.x + a.width >= b.x && a.y <= b.y + b.height && a.y + a.height >= b.y
}

function handlePaneClick() {
  if (suppressNextPaneClick.value) {
    suppressNextPaneClick.value = false
    return
  }

  closeFloatingPanels()
  canvasStore.clearSelection()
  selectedDirectNodeIds.value = []
}

function handleCanvasContextMenu(event) {
  event.preventDefault()
  event.stopPropagation()
  const target = event.target instanceof Element ? event.target : null
  if (!isCanvasContextMenuTarget(target)) {
    contextMenu.visible = false
    return
  }
  openCanvasContextMenu(event)
}

function isCanvasContextMenuTarget(target) {
  if (!target || !canvasFrame.value?.contains?.(target)) return false
  return !target.closest(
    [
      '.direct-workflow-node',
      '.vue-flow__node',
      '.direct-workflow-node__fixed-panel',
      '.generated-image__preview',
      '.uploaded-asset',
      '.add-node-menu',
      '.libtv-topbar',
      '.canvas-tool-rail',
      '.canvas-bottom-controls',
      '.canvas-minimap',
      '.rail-panel',
      '.history-overlay',
      '.library-picker-overlay',
      '.starter-strip',
      '.canvas-help-panel',
      '.canvas-context-menu',
      '.image-preview-overlay',
      '.publish-overlay',
      '.canvas-agent-panel',
      '.canvas-agent-trigger'
    ].join(', ')
  )
}

function openCanvasContextMenu(event) {
  if (!event || typeof event.clientX !== 'number') return
  closeFloatingPanels()
  contextMenu.visible = true
  contextMenu.screen = clampMenuPosition({ x: event.clientX, y: event.clientY }, 246, 176)
  contextMenu.flow = screenToFlowCoordinate({ x: event.clientX, y: event.clientY })
}

function handlePaneContextMenu(event) {
  event.preventDefault?.()
  const sourceEvent = event?.event || event
  openCanvasContextMenu(sourceEvent)
}

function handleNodeContextMenu({ event, node }) {
  event.preventDefault()
  contextMenu.visible = false
  if (node?.id) selectOnly(node.id)
}

function handleNodeDoubleClick({ node }) {
  if (node.data?.kind === 'group') {
    fitView({ duration: 260, padding: 0.24, nodes: getGroupChildren(node.id).map((child) => child.id) })
    return
  }

  runNode(node.id)
}

function handleCanvasDoubleClick(event) {
  const target = event.target instanceof Element ? event.target : null
  if (
    target?.closest(
      '.vue-flow__node, .add-node-menu, .libtv-topbar, .canvas-tool-rail, .canvas-bottom-controls, .canvas-minimap, .rail-panel, .history-overlay, .library-picker-overlay, .starter-strip, .canvas-help-panel, .canvas-context-menu, .publish-overlay, .canvas-agent-panel, .canvas-agent-trigger'
    )
  ) {
    return
  }

  const topbarRect = document.querySelector('.libtv-topbar')?.getBoundingClientRect?.()
  if (topbarRect && event.clientY <= topbarRect.bottom + 12) return

  openAddMenuAtEvent(event)
}

function openAddMenuFromButton(event) {
  event.stopPropagation()
  const buttonRect = event.currentTarget?.getBoundingClientRect?.()
  const screen = buttonRect
    ? { x: buttonRect.right + 28, y: Math.max(buttonRect.top - 2, 82) }
    : { x: 120, y: 92 }
  openAddMenu(screen, getViewportCenter())
}

function openAddMenuAtEvent(event) {
  const flow = screenToFlowCoordinate({ x: event.clientX, y: event.clientY })
  openAddMenu({ x: event.clientX, y: event.clientY }, flow)
}

function openAddMenu(screen, flow) {
  addMenu.visible = true
  addMenu.screen = clampMenuPosition(screen, 300, 580)
  addMenu.originScreen = screen
  addMenu.flow = flow
  contextMenu.visible = false
  activeRailPanel.value = ''
}

function closeFloatingPanels(clearPendingConnection = true) {
  addMenu.visible = false
  referenceMenu.visible = false
  contextMenu.visible = false
  if (audioVoicePicker.visible) closeAudioVoicePicker()
  activeRailPanel.value = ''
  if (clearPendingConnection) {
    clearPendingDirectConnection()
  }
  nextTick(() => flushDeferredInteractionSave())
}

function clearPendingDirectConnection() {
  pendingDirectConnection.sourceId = ''
  pendingDirectConnection.sourceSide = 'right'
  pendingDirectConnection.start = { x: 0, y: 0 }
  pendingDirectConnection.point = { x: 0, y: 0 }
}

function closeAddMenu() {
  addMenu.visible = false
  nextTick(() => flushDeferredInteractionSave())
}

function toggleRailPanel(panel) {
  addMenu.visible = false
  referenceMenu.visible = false
  contextMenu.visible = false
  helpVisible.value = false
  activeRailPanel.value = activeRailPanel.value === panel ? '' : panel
}

function closeRailPanel() {
  activeRailPanel.value = ''
  nextTick(() => flushDeferredInteractionSave())
}

function handleStarterSelect(type) {
  createNode(type, starterPositions[type] || getViewportCenter())
}

function handleMenuSelect(selection) {
  const item = normalizeMenuSelection(selection)
  if (pendingDirectConnection.sourceId) {
    createDirectNodeFromPendingConnection(item)
    return
  }

  const flowPosition = getAvailableDirectNodePosition(addMenu.flow)

  if (item.id === 'upload') {
    pendingUploadFlowPosition.value = flowPosition
    replacingUploadNodeId.value = ''
    closeFloatingPanels()
    openUploadDialog()
    return
  }

  if (item.id === 'library') {
    closeFloatingPanels()
    openLibraryPicker()
    return
  }

  canvasActivated.value = true
  rememberHistory()
  closeFloatingPanels()
  createDirectNodeAtFlow(item.type, flowPosition, item.patch)
  showToast('\u5df2\u6dfb\u52a0\u8282\u70b9')
}

function createDirectNodeFromPendingConnection(item) {
  canvasActivated.value = true
  rememberHistory()
  closeFloatingPanels(false)
  const createdPosition = getDirectNodePositionFromPortAnchor(
    item.type,
    pendingDirectConnection.point,
    pendingDirectConnection.sourceSide === 'left' ? 'right' : 'left'
  )
  const createdNode = createDirectNodeAtFlow(item.type, createdPosition, item.patch)
  if (pendingDirectConnection.sourceSide === 'left') {
    directEdges.value = upsertDirectEdge(createdNode.id, pendingDirectConnection.sourceId)
  } else {
    directEdges.value = upsertDirectEdge(pendingDirectConnection.sourceId, createdNode.id)
  }
  clearPendingDirectConnection()
  showToast('\u5df2\u8fde\u63a5\u8282\u70b9')
}

function handleReferenceSelect(selection) {
  const item = normalizeMenuSelection(selection)
  if (pendingDirectConnection.sourceId) {
    createDirectNodeFromPendingConnection(item)
    return
  }

  if (!referenceMenu.sourceId) return

  canvasActivated.value = true
  rememberHistory()
  const createdNode = buildCanvasNode(item.type, referenceMenu.flow, item.patch)
  nodes.value = [...nodes.value, createdNode]
  edges.value = [
    ...edges.value,
    buildEdge(referenceMenu.sourceId, createdNode.id, '引用生成', {
      sourceHandle: referenceMenu.sourceHandle,
      targetHandle: 'in'
    })
  ]
  selectOnly(createdNode.id)
  referenceMenu.visible = false
  showToast('已引用节点生成')
}

function normalizeMenuSelection(selection) {
  if (typeof selection === 'string') return { type: selection, patch: {} }
  return {
    id: selection?.id || '',
    type: selection?.type || 'prompt_note',
    patch: selection?.patch || {}
  }
}

function openUploadDialog() {
  if (uploadDialogOpening) return
  uploadDialogOpening = true
  if (uploadInput.value) {
    uploadInput.value.value = ''
    uploadInput.value.click()
  }
  window.setTimeout(() => {
    uploadDialogOpening = false
  }, 500)
}

function openReferenceUploadDialog(nodeId, slot = '') {
  const node = directNodes.value.find((item) => item.id === nodeId)
  if (!canUploadDirectReference(node)) return
  referenceUploadTargetSlot.value = isStartEndVideoNode(node) ? slot : ''
  referenceUploadAccept.value = getReferenceUploadAccept(node)
  referenceUploadTargetNodeId.value = nodeId
  if (referenceUploadInput.value) {
    referenceUploadInput.value.value = ''
    referenceUploadInput.value.click()
  } else {
    window.setTimeout(() => {
      referenceUploadInput.value?.click?.()
    }, 0)
  }
}

function replaceUploadedNode(nodeId) {
  const node = directNodes.value.find((item) => item.id === nodeId)
  if (!node) return
  pendingUploadFlowPosition.value = { x: node.x, y: node.y }
  replacingUploadNodeId.value = nodeId
  openUploadDialog()
}

function handleCanvasDragOver(event) {
  if (!event.dataTransfer) return
  event.dataTransfer.dropEffect = hasImageDataTransfer(event.dataTransfer) ? 'copy' : 'none'
}

function handleCanvasFileDrop(event) {
  const files = getImageFilesFromDataTransfer(event.dataTransfer)
  if (files.length === 0) return

  event.preventDefault()
  event.stopPropagation()
  const flowPosition = getAvailableDirectNodePosition(screenToFlowCoordinate({ x: event.clientX, y: event.clientY }))
  uploadImageFilesToCanvas(files, flowPosition)
}

function handleWindowPaste(event) {
  if ((isTypingTarget(event.target) || isTextInteractionTarget(event.target)) && !isDeleteKeySinkTarget(event.target)) return

  const files = getImageFilesFromDataTransfer(event.clipboardData)
  if (files.length > 0) {
    lastClipboardImagePasteAt = window.performance.now()
    window.clearTimeout(clipboardPasteFallbackTimer)
    event.preventDefault()
    event.stopPropagation()
    uploadImageFilesToCanvas(files, getAvailableDirectNodePosition(getViewportCenter()))
    return
  }

  if (clipboardNodes.value.length > 0) {
    event.preventDefault()
    event.stopPropagation()
    pasteSelection()
  }
}

function isDeleteKeySinkTarget(target) {
  return target instanceof HTMLElement && target.classList.contains('delete-key-sink')
}

async function handleCanvasClipboardPasteShortcut() {
  const now = window.performance.now()
  if (now - lastClipboardImagePasteAt < 600) return

  const files = await readClipboardImageFiles()
  if (files.length > 0) {
    lastClipboardImagePasteAt = window.performance.now()
    uploadImageFilesToCanvas(files, getAvailableDirectNodePosition(getViewportCenter()))
    return
  }

  pasteSelection()
}

function queueCanvasClipboardPasteFallback() {
  window.clearTimeout(clipboardPasteFallbackTimer)
  clipboardPasteFallbackTimer = window.setTimeout(() => {
    if (window.performance.now() - lastClipboardImagePasteAt < 600) return
    handleCanvasClipboardPasteShortcut()
  }, 90)
}

async function readClipboardImageFiles() {
  if (!navigator.clipboard?.read) return []
  try {
    const items = await navigator.clipboard.read()
    const files = []
    for (const item of items) {
      const imageType = item.types.find((type) => type.startsWith('image/'))
      if (!imageType) continue
      const blob = await item.getType(imageType)
      const extension = imageType.split('/')[1] || 'png'
      files.push(new File([blob], `clipboard-image-${Date.now()}.${extension}`, { type: imageType }))
    }
    return files
  } catch {
    return []
  }
}

function getImageFilesFromDataTransfer(dataTransfer) {
  if (!dataTransfer) return []
  const files = []
  const seen = new Set()
  const addFile = (file) => {
    if (!file || !file.type?.startsWith('image/')) return
    const signature = getUploadFileSignature(file)
    if (seen.has(signature)) return
    seen.add(signature)
    files.push(file)
  }

  Array.from(dataTransfer.files || []).forEach(addFile)
  Array.from(dataTransfer.items || []).forEach((item) => {
    if (item.kind !== 'file' || !item.type?.startsWith('image/')) return
    addFile(item.getAsFile())
  })
  return files
}

function hasImageDataTransfer(dataTransfer) {
  return (
    Array.from(dataTransfer?.files || []).some((file) => file.type?.startsWith('image/')) ||
    Array.from(dataTransfer?.items || []).some((item) => item.type?.startsWith('image/'))
  )
}

function uploadImageFilesToCanvas(files, flowPosition) {
  const base = flowPosition || getViewportCenter()
  let createdCount = 0
  files.forEach((file, index) => {
    const position = getAvailableDirectNodePosition({
      x: base.x + index * 44,
      y: base.y + index * 44
    })
    const nodeId = startCanvasAssetUpload(file, {
      flowPosition: position,
      allowKinds: ['image'],
      rememberChange: createdCount === 0
    })
    if (nodeId) createdCount += 1
  })

  if (createdCount > 0) {
    showToast(createdCount > 1 ? `已添加 ${createdCount} 张图片` : '已添加图片')
  }
}

function handleUploadInputChange(event) {
  const file = event.target?.files?.[0]
  if (!file) return

  startCanvasAssetUpload(file, {
    flowPosition: pendingUploadFlowPosition.value,
    replacingNodeId: replacingUploadNodeId.value,
    allowKinds: ['image', 'video', 'audio']
  })
  event.target.value = ''
}

function handleReferenceUploadInputChange(event) {
  const nodeId = referenceUploadTargetNodeId.value
  const node = directNodes.value.find((item) => item.id === nodeId)
  const allowedKinds = getAllowedReferenceUploadKinds(node)
  const selectedFiles = Array.from(event.target?.files || [])
  const files = selectedFiles.filter((file) => allowedKinds.includes(getUploadKind(file)))
  if (!nodeId || files.length === 0) {
    if (event.target) event.target.value = ''
    if (nodeId) showToast(getReferenceUploadRejectMessage(node))
    referenceUploadTargetSlot.value = ''
    return
  }
  uploadReferenceFiles(nodeId, referenceUploadTargetSlot.value ? files.slice(0, 1) : files)
  referenceUploadTargetSlot.value = ''
  if (event.target) event.target.value = ''
}

function uploadReferenceFiles(nodeId, files) {
  const node = directNodes.value.find((item) => item.id === nodeId)
  if (!node) return
  if (!activeCanvas.value?.id) {
    showToast('画布尚未加载完成，请稍后重试')
    return
  }

  const validFiles = files.filter((file) => {
    const kind = getUploadKind(file)
    if (!getAllowedReferenceUploadKinds(node).includes(kind)) return false
    const limit = kind === 'image' ? 20 * 1024 * 1024 : 50 * 1024 * 1024
    if (file.size > limit) {
      showToast(kind === 'image' ? '参考图不能超过 20MB' : '参考素材不能超过 50MB')
      return false
    }
    return true
  })
  if (!validFiles.length) return

  rememberHistory()
  const targetSlot = isStartEndVideoNode(node) ? referenceUploadTargetSlot.value : ''
  const targetSlotIndex = targetSlot === 'first' ? 0 : targetSlot === 'last' ? 1 : -1
  const existingSlotReference = targetSlotIndex >= 0 ? getStartEndFrameReference(node, targetSlot) : null
  let nextReferences = normalizeManualReferenceImages(node.referenceImages)
  const nextOrder = Array.isArray(node.referenceOrder) ? [...node.referenceOrder] : getDirectVisualReferenceItems(nodeId).map((item) => item.id)
  if (existingSlotReference?.source === 'manual') {
    if (existingSlotReference.previewUrl?.startsWith('blob:')) URL.revokeObjectURL(existingSlotReference.previewUrl)
    nextReferences = nextReferences.filter((reference) => reference.id !== existingSlotReference.id)
    const existingOrderIndex = nextOrder.indexOf(existingSlotReference.id)
    if (existingOrderIndex >= 0) nextOrder.splice(existingOrderIndex, 1)
  }
  const refsToUpload = validFiles.map((file, index) => {
    const id = `manual-ref-${Date.now()}-${index}-${Math.round(Math.random() * 10000)}`
    const kind = getUploadKind(file)
    const previewUrl = URL.createObjectURL(file)
    const reference = {
      id,
      source: 'manual',
      kind,
      url: '',
      previewUrl,
      name: file.name || getReferenceKindLabel({ kind }),
      status: 'uploading',
      progress: 8,
      width: 0,
      height: 0,
      assetId: '',
      storageObjectId: ''
    }
    nextReferences.push(reference)
    if (targetSlotIndex >= 0) {
      nextOrder.splice(targetSlotIndex, 1, id)
    } else {
      nextOrder.push(id)
    }
    return { file, reference, previewUrl }
  })
  updateDirectNode(nodeId, { referenceImages: nextReferences, referenceOrder: nextOrder })

  refsToUpload.forEach(({ file, reference, previewUrl }) => uploadReferenceFile(nodeId, reference.id, file, previewUrl))
  showToast(validFiles.length > 1 ? `正在上传 ${validFiles.length} 个参考素材` : '正在上传参考素材')
}

async function uploadReferenceFile(nodeId, referenceId, file, previewUrl) {
  const kind = getUploadKind(file) || 'image'
  try {
    const metadata = await readUploadMetadata(kind, previewUrl)
    patchManualReferenceImage(nodeId, referenceId, {
      width: metadata?.width || 0,
      height: metadata?.height || 0,
      durationSeconds: metadata?.durationSeconds || 0
    })
    const response = await uploadSluvoCanvasAsset(activeCanvas.value.id, file, {
      mediaType: kind,
      width: metadata?.width,
      height: metadata?.height,
      durationSeconds: metadata?.durationSeconds,
      metadata: {
        localNodeId: nodeId,
        referenceId
      },
      onProgress: (progress) => {
        patchManualReferenceImage(nodeId, referenceId, { status: 'uploading', progress })
      }
    })
    const asset = response?.asset || {}
    const nextUrl = response?.fileUrl || asset.url
    if (!nextUrl) throw new Error('上传接口未返回文件地址')
    patchManualReferenceImage(nodeId, referenceId, {
      url: nextUrl,
      previewUrl,
      kind,
      status: 'success',
      progress: 100,
      width: asset.width || metadata?.width || 0,
      height: asset.height || metadata?.height || 0,
      durationSeconds: asset.durationSeconds || metadata?.durationSeconds || 0,
      assetId: asset.id || '',
      storageObjectId: response?.storageObjectId || asset.storageObjectId || ''
    })
    persistCriticalCanvasChange(120)
  } catch (error) {
    patchManualReferenceImage(nodeId, referenceId, {
      status: 'error',
      progress: 0,
      message: error instanceof Error ? error.message : '上传失败'
    })
    showToast(error instanceof Error ? error.message : '参考素材上传失败')
    flushDeferredCanvasSave(220)
  }
}

function startCanvasAssetUpload(file, options = {}) {
  const kind = getUploadKind(file)
  const allowKinds = options.allowKinds || ['image', 'video', 'audio']
  if (!kind || !allowKinds.includes(kind)) {
    showToast(allowKinds.length === 1 && allowKinds[0] === 'image' ? '请拖入或粘贴图片文件' : '请选择图片、视频或音频文件')
    return ''
  }
  if (file.size > 20 * 1024 * 1024) {
    showToast('上传文件不能超过 20MB')
    return ''
  }
  if (!activeCanvas.value?.id) {
    showToast('画布尚未加载完成，请稍后重试')
    return ''
  }

  const signature = getUploadFileSignature(file)
  const looseSignature = getUploadFileLooseSignature(file)
  const now = window.performance.now()
  const existingUploadedNodeId = options.replacingNodeId ? '' : findExistingUploadedAssetNode(file)
  if (existingUploadedNodeId) {
    selectedDirectNodeIds.value = [existingUploadedNodeId]
    activeDirectNodeId.value = existingUploadedNodeId
    focusedDirectNodeId.value = existingUploadedNodeId
    lastTouchedDirectNodeId.value = existingUploadedNodeId
    showToast('画布里已经有这张图了')
    return ''
  }
  const duplicateNodeId = activeUploadSignatures.get(signature)
  if (duplicateNodeId && directNodes.value.some((node) => node.id === duplicateNodeId && node.upload?.status === 'uploading')) {
    selectedDirectNodeIds.value = [duplicateNodeId]
    activeDirectNodeId.value = duplicateNodeId
    focusedDirectNodeId.value = duplicateNodeId
    lastTouchedDirectNodeId.value = duplicateNodeId
    showToast('这个文件正在上传')
    return ''
  }
  if (lastUploadSelection.signature === signature && now - lastUploadSelection.at < 1200) {
    return ''
  }
  lastUploadSelection = { signature, at: now }

  const url = URL.createObjectURL(file)
  const media = {
    kind,
    url,
    name: file.name,
    mime: file.type,
    fileSize: file.size,
    width: kind === 'audio' ? null : 1459,
    height: kind === 'audio' ? null : 2117,
    uploadSignature: signature,
    uploadLooseSignature: looseSignature,
    isLocalPreview: true
  }

  if (options.rememberChange !== false) rememberHistory()
  canvasActivated.value = true

  const existingId = options.replacingNodeId || ''
  let nodeId = existingId

  if (existingId) {
    revokeLocalPreviewForNode(existingId)
    directNodes.value = directNodes.value.map((node) =>
      node.id === existingId
        ? {
            ...node,
            title: getUploadedAssetTitle(kind),
            icon: getUploadedAssetIcon(kind),
            media,
            upload: { status: 'uploading', progress: 8, message: '正在准备上传' }
          }
        : node
    )
  } else {
    const position = options.flowPosition || getViewportCenter()
    const node = createDirectNodeAtFlow('uploaded_asset', position, {
      title: getUploadedAssetTitle(kind),
      icon: getUploadedAssetIcon(kind),
      media,
      upload: { status: 'uploading', progress: 8, message: '正在准备上传' }
    })
    nodeId = node.id
  }

  uploadFileMap.set(nodeId, file)
  rememberLocalUploadPreview(nodeId, kind === 'image' ? url : '')
  activeUploadSignatures.set(signature, nodeId)
  uploadSignatureByNodeId.set(nodeId, signature)
  selectedDirectNodeIds.value = [nodeId]
  activeDirectNodeId.value = nodeId
  focusedDirectNodeId.value = nodeId
  lastTouchedDirectNodeId.value = nodeId
  pendingUploadFlowPosition.value = null
  replacingUploadNodeId.value = ''
  const originalNodeId = nodeId
  const keptNodeId = dedupeUploadedAssetNodes({ preferId: nodeId, silent: true }) || nodeId
  if (keptNodeId !== originalNodeId) {
    selectedDirectNodeIds.value = [keptNodeId]
    activeDirectNodeId.value = keptNodeId
    focusedDirectNodeId.value = keptNodeId
    lastTouchedDirectNodeId.value = keptNodeId
    return ''
  }
  uploadFileForNode(nodeId, file, kind, url)
  return nodeId
}

function getUploadFileSignature(file) {
  return [file.name || '', file.size || 0, file.lastModified || 0, file.type || ''].join(':')
}

function getUploadFileLooseSignature(file) {
  return [file.name || '', file.size || 0, file.type || ''].join(':')
}

function findExistingUploadedAssetNode(file) {
  const signature = getUploadFileSignature(file)
  const looseSignature = getUploadFileLooseSignature(file)
  const kind = getUploadKind(file)
  const existing = directNodes.value.find((node) => {
    if (node.type !== 'uploaded_asset' || node.media?.kind !== kind) return false
    const media = node.media || {}
    if (media.uploadSignature && media.uploadSignature === signature) return true
    if (media.uploadLooseSignature && media.uploadLooseSignature === looseSignature) return true
    return media.name === file.name && Number(media.fileSize || 0) === Number(file.size || 0) && media.mime === file.type
  })
  return existing?.id || ''
}

function getUploadedAssetDuplicateKey(node) {
  if (node?.type !== 'uploaded_asset' || !node.media) return ''
  const media = node.media || {}
  const kind = media.kind || ''
  if (!kind) return ''
  if (media.uploadLooseSignature) return `${kind}:signature:${media.uploadLooseSignature}`
  if (media.uploadSignature) return `${kind}:signature:${media.uploadSignature}`
  const name = String(media.name || '').trim()
  const size = Number(media.fileSize || 0)
  const mime = String(media.mime || '').trim()
  if (name && size > 0 && mime) return `${kind}:file:${name}:${size}:${mime}`
  const stableId = media.storageObjectId || media.storageObjectKey || media.assetId
  if (stableId) return `${kind}:asset:${stableId}`
  const url = String(media.url || '')
  if (url && !url.startsWith('blob:')) return `${kind}:url:${url}`
  return ''
}

function pickUploadedAssetKeeper(nodesInGroup, preferId = '') {
  return [...nodesInGroup].sort((left, right) => {
    if (left.id === preferId) return -1
    if (right.id === preferId) return 1
    const leftDone = left.upload?.status === 'success' || Boolean(left.media?.url && !String(left.media.url).startsWith('blob:'))
    const rightDone = right.upload?.status === 'success' || Boolean(right.media?.url && !String(right.media.url).startsWith('blob:'))
    if (leftDone !== rightDone) return leftDone ? -1 : 1
    const leftUploading = left.upload?.status === 'uploading'
    const rightUploading = right.upload?.status === 'uploading'
    if (leftUploading !== rightUploading) return leftUploading ? 1 : -1
    return String(left.id).localeCompare(String(right.id))
  })[0]
}

function dedupeUploadedAssetNodes({ preferId = '', silent = false } = {}) {
  const groups = new Map()
  directNodes.value.forEach((node) => {
    const key = getUploadedAssetDuplicateKey(node)
    if (!key) return
    if (!groups.has(key)) groups.set(key, [])
    groups.get(key).push(node)
  })

  const duplicateToKeeper = new Map()
  groups.forEach((group) => {
    if (group.length < 2) return
    const keeper = pickUploadedAssetKeeper(group, preferId)
    group.forEach((node) => {
      if (node.id !== keeper.id) duplicateToKeeper.set(node.id, keeper.id)
    })
  })
  if (duplicateToKeeper.size === 0) return preferId || ''

  const duplicateIds = new Set(duplicateToKeeper.keys())
  duplicateIds.forEach((id) => {
    revokeLocalPreviewForNode(id)
    uploadFileMap.delete(id)
    releaseUploadSignature(id)
    directNodeElements.delete(id)
    clearImageGenerationTimer(id)
    clearVideoGenerationTimer(id)
    clearAudioGenerationTimer(id)
  })

  directEdges.value = directEdges.value
    .map((edge) => ({
      ...edge,
      sourceId: duplicateToKeeper.get(edge.sourceId) || edge.sourceId,
      targetId: duplicateToKeeper.get(edge.targetId) || edge.targetId
    }))
    .filter((edge, index, allEdges) => edge.sourceId !== edge.targetId && allEdges.findIndex((item) => item.sourceId === edge.sourceId && item.targetId === edge.targetId) === index)
  directNodes.value = directNodes.value.filter((node) => !duplicateIds.has(node.id))

  const selectedKeeperIds = selectedDirectNodeIds.value.map((id) => duplicateToKeeper.get(id) || id)
  selectedDirectNodeIds.value = [...new Set(selectedKeeperIds)].filter((id) => directNodes.value.some((node) => node.id === id))
  focusedDirectNodeId.value = duplicateToKeeper.get(focusedDirectNodeId.value) || focusedDirectNodeId.value
  activeDirectNodeId.value = duplicateToKeeper.get(activeDirectNodeId.value) || activeDirectNodeId.value
  lastTouchedDirectNodeId.value = duplicateToKeeper.get(lastTouchedDirectNodeId.value) || lastTouchedDirectNodeId.value
  const keptPreferId = duplicateToKeeper.get(preferId) || preferId
  if (!silent) showToast('已合并重复图片')
  return keptPreferId
}

function patchManualReferenceImage(nodeId, referenceId, patch) {
  directNodes.value = directNodes.value.map((node) => {
    if (node.id !== nodeId) return node
    return {
      ...node,
      referenceImages: normalizeManualReferenceImages(node.referenceImages).map((reference) =>
        reference.id === referenceId ? { ...reference, ...patch } : reference
      )
    }
  })
}

function removeManualReferenceImage(nodeId, referenceId) {
  rememberHistory()
  const node = directNodes.value.find((item) => item.id === nodeId)
  const reference = normalizeManualReferenceImages(node?.referenceImages).find((item) => item.id === referenceId)
  if (reference?.previewUrl?.startsWith('blob:')) URL.revokeObjectURL(reference.previewUrl)
  updateDirectNode(nodeId, {
    referenceImages: normalizeManualReferenceImages(node?.referenceImages).filter((item) => item.id !== referenceId),
    referenceOrder: (node?.referenceOrder || []).filter((id) => id !== referenceId),
    referenceMentions: normalizeReferenceMentions(node?.referenceMentions).filter((item) => item.referenceId !== referenceId),
    promptSegments: normalizePromptSegments(node?.promptSegments, node).filter((item) => item.type !== 'reference' || item.referenceId !== referenceId)
  })
  scheduleCanvasSave(180)
}

function startReferenceDrag(nodeId, referenceId) {
  referenceDrag.nodeId = nodeId
  referenceDrag.referenceId = referenceId
}

function dropReference(nodeId, targetReferenceId) {
  if (referenceDrag.nodeId !== nodeId || !referenceDrag.referenceId || referenceDrag.referenceId === targetReferenceId) return
  rememberHistory()
  const orderedIds = getDirectImageReferenceItems(nodeId).map((item) => item.id)
  const fromIndex = orderedIds.indexOf(referenceDrag.referenceId)
  const toIndex = orderedIds.indexOf(targetReferenceId)
  if (fromIndex < 0 || toIndex < 0) return
  orderedIds.splice(toIndex, 0, orderedIds.splice(fromIndex, 1)[0])
  updateDirectNode(nodeId, { referenceOrder: orderedIds })
  referenceDrag.nodeId = ''
  referenceDrag.referenceId = ''
  scheduleCanvasSave(180)
}

function releaseUploadSignature(nodeId) {
  const signature = uploadSignatureByNodeId.get(nodeId)
  if (signature && activeUploadSignatures.get(signature) === nodeId) {
    activeUploadSignatures.delete(signature)
  }
  uploadSignatureByNodeId.delete(nodeId)
}

function getUploadKind(file) {
  if (file.type.startsWith('image/')) return 'image'
  if (file.type.startsWith('video/')) return 'video'
  if (file.type.startsWith('audio/')) return 'audio'
  return ''
}

function getUploadedAssetTitle(kind) {
  const titles = {
    image: '图层 0 拷贝',
    video: '视频 0 拷贝',
    audio: '音频 0 拷贝'
  }
  return titles[kind] || '素材 0 拷贝'
}

function getUploadedAssetIcon(kind) {
  const icons = {
    image: '▧',
    video: '▣',
    audio: '≋'
  }
  return icons[kind] || '▧'
}

async function uploadFileForNode(nodeId, file, kind, localUrl) {
  try {
    const metadata = await readUploadMetadata(kind, localUrl)
    if (metadata) updateUploadedNodeMedia(localUrl, metadata)
    updateDirectNodeUpload(nodeId, {
      status: 'uploading',
      progress: 18,
      message: file.size <= 5 * 1024 * 1024 ? '正在读取文件' : '正在上传到 OSS'
    })
    const response = await uploadSluvoCanvasAsset(activeCanvas.value.id, file, {
      mediaType: kind,
      nodeId: nodeRevisionMap.value[nodeId] ? nodeId : '',
      width: metadata?.width,
      height: metadata?.height,
      durationSeconds: metadata?.durationSeconds,
      metadata: {
        localNodeId: nodeId
      },
      onProgress: (progress, message = '正在上传到 OSS') => {
        updateDirectNodeUpload(nodeId, {
          status: 'uploading',
          progress,
          message
        })
      }
    })
    completeUploadedNode(nodeId, response, file, kind, localUrl, metadata)
  } catch (error) {
    releaseUploadSignature(nodeId)
    updateDirectNodeUpload(nodeId, {
      status: 'error',
      progress: 0,
      message: error instanceof Error ? error.message : '上传失败，请重试'
    })
    showToast(error instanceof Error ? error.message : '上传失败，请重试')
    flushDeferredCanvasSave(220)
  }
}

function completeUploadedNode(nodeId, response, file, kind, localUrl, metadata = {}) {
  const asset = response?.asset || {}
  const nextUrl = response?.fileUrl || asset.url
  if (!nextUrl) {
    throw new Error('上传接口未返回文件地址')
  }
  rememberLocalUploadPreview(nodeId, kind === 'image' ? localUrl : '')
  directNodes.value = directNodes.value.map((node) =>
    node.id === nodeId
      ? {
          ...node,
          media: {
            kind,
            url: nextUrl,
            previewUrl: kind === 'image' && localUrl?.startsWith('blob:') ? localUrl : '',
            thumbnailUrl: response?.thumbnailUrl || asset.thumbnailUrl || '',
            name: file.name,
            mime: file.type,
            fileSize: file.size,
            uploadSignature: getUploadFileSignature(file),
            uploadLooseSignature: getUploadFileLooseSignature(file),
            width: asset.width || metadata?.width || node.media?.width || null,
            height: asset.height || metadata?.height || node.media?.height || null,
            durationSeconds: asset.durationSeconds || metadata?.durationSeconds || null,
            assetId: asset.id || '',
            storageObjectId: response?.storageObjectId || asset.storageObjectId || '',
            storageObjectKey: response?.storageObjectKey || asset.metadata?.storageObjectKey || '',
            isLocalPreview: false
          },
          upload: {
            status: 'success',
            progress: 100,
            message: '上传成功'
          }
        }
      : node
  )
  if (localUrl?.startsWith('blob:') && kind !== 'image') URL.revokeObjectURL(localUrl)
  releaseUploadSignature(nodeId)
  dedupeUploadedAssetNodes({ preferId: nodeId, silent: true })
  showToast('上传成功')
  persistCriticalCanvasChange(120)
}

function retryUploadedNode(nodeId) {
  const file = uploadFileMap.get(nodeId)
  const node = directNodes.value.find((item) => item.id === nodeId)
  if (!file || !node?.media?.url) {
    showToast('当前会话无法重试，请重新选择文件')
    return
  }
  updateDirectNodeUpload(nodeId, {
    status: 'uploading',
    progress: 8,
    message: '正在重新上传'
  })
  const signature = getUploadFileSignature(file)
  activeUploadSignatures.set(signature, nodeId)
  uploadSignatureByNodeId.set(nodeId, signature)
  uploadFileForNode(nodeId, file, node.media.kind || getUploadKind(file), node.media.url)
}

function updateDirectNodeUpload(nodeId, upload) {
  directNodes.value = directNodes.value.map((node) =>
    node.id === nodeId
      ? {
          ...node,
          upload: {
            ...(node.upload || {}),
            ...upload
          }
        }
      : node
  )
}

function readImageDimensions(url) {
  return new Promise((resolve) => {
    const image = new Image()
    image.onload = () => resolve({ width: image.naturalWidth, height: image.naturalHeight })
    image.onerror = () => resolve(null)
    image.src = url
  })
}

function readVideoDimensions(url) {
  return new Promise((resolve) => {
    const video = document.createElement('video')
    video.onloadedmetadata = () =>
      resolve({
        width: video.videoWidth,
        height: video.videoHeight,
        durationSeconds: Number.isFinite(video.duration) ? video.duration : null
      })
    video.onerror = () => resolve(null)
    video.src = url
  })
}

function readAudioMetadata(url) {
  return new Promise((resolve) => {
    const audio = document.createElement('audio')
    audio.onloadedmetadata = () =>
      resolve({
        durationSeconds: Number.isFinite(audio.duration) ? audio.duration : null
      })
    audio.onerror = () => resolve(null)
    audio.src = url
  })
}

function readUploadMetadata(kind, url) {
  if (kind === 'image') return readImageDimensions(url)
  if (kind === 'video') return readVideoDimensions(url)
  if (kind === 'audio') return readAudioMetadata(url)
  return Promise.resolve(null)
}

function updateUploadedNodeMedia(url, dimensions) {
  directNodes.value = directNodes.value.map((node) =>
    node.media?.url === url
      ? {
          ...node,
          media: {
            ...node.media,
            ...dimensions
          }
        }
      : node
  )
}

function getUploadedAssetDimensions(node) {
  if (node.media?.kind === 'audio') return '音频文件'
  const width = node.media?.width || 1459
  const height = node.media?.height || 2117
  return `${width} × ${height}`
}

function getUploadedImageSrc(node) {
  const media = node?.media || {}
  return getLocalUploadPreviewUrl(node) || media.previewUrl || media.thumbnailUrl || media.url || ''
}

function getGeneratedImageSrc(node) {
  const image = node?.generatedImage || {}
  return normalizeDisplayImageSrc(image.url || image.previewUrl || image.thumbnailUrl || '')
}

function getGeneratedVideoSrc(node) {
  const video = node?.generatedVideo || {}
  return normalizeDisplayVideoSrc(video.url || video.previewUrl || '')
}

function getGeneratedVideoPoster(node) {
  const video = node?.generatedVideo || {}
  return normalizeDisplayImageSrc(video.posterUrl || video.thumbnailUrl || '')
}

function getGeneratedAudioSrc(node) {
  const audio = node?.generatedAudio || {}
  return normalizeDisplayAudioSrc(audio.url || audio.previewUrl || '')
}

function normalizeDisplayImageSrc(value) {
  const source = String(value || '').trim()
  if (!source) return ''
  if (source.startsWith('//')) return `${window.location.protocol}${source}`
  if (/^(https?:|data:image\/|blob:)/i.test(source)) return source
  if (source.startsWith('/')) return buildApiUrl(source)
  return source
}

function normalizeDisplayVideoSrc(value) {
  const source = String(value || '').trim()
  if (!source) return ''
  if (source.startsWith('//')) return `${window.location.protocol}${source}`
  if (/^(https?:|blob:)/i.test(source)) return source
  if (source.startsWith('/')) return buildApiUrl(source)
  return source
}

function normalizeDisplayAudioSrc(value) {
  const source = String(value || '').trim()
  if (!source) return ''
  if (source.startsWith('//')) return `${window.location.protocol}${source}`
  if (/^(https?:|blob:|data:audio\/)/i.test(source)) return source
  if (source.startsWith('/')) return buildApiUrl(source)
  return source
}

function handleUploadedImageError(nodeId) {
  const node = directNodes.value.find((item) => item.id === nodeId)
  const localPreviewUrl = getLocalUploadPreviewUrl(node)
  const fallbackUrl = localPreviewUrl || node?.media?.previewUrl || ''
  if (!fallbackUrl || fallbackUrl === node?.media?.url) return
  directNodes.value = directNodes.value.map((item) =>
    item.id === nodeId
      ? {
          ...item,
          media: {
            ...item.media,
            thumbnailUrl: '',
            url: fallbackUrl,
            isLocalPreview: true
          }
        }
      : item
  )
}

async function handleGeneratedImageError(nodeId) {
  const node = directNodes.value.find((item) => item.id === nodeId)
  const image = node?.generatedImage || {}
  const currentUrl = normalizeDisplayImageSrc(image.url)
  const fallbackUrl = normalizeDisplayImageSrc(image.previewUrl || image.thumbnailUrl)

  if (fallbackUrl && fallbackUrl !== currentUrl) {
    updateDirectNode(nodeId, {
      generatedImage: {
        ...image,
        url: fallbackUrl
      }
    })
    return
  }

  const recordImage = image.recordId ? await fetchRecordImageResult(image.recordId) : null
  const nextUrl = normalizeDisplayImageSrc(recordImage?.url)
  if (nextUrl && nextUrl !== currentUrl) {
    updateDirectNode(nodeId, {
      generationStatus: 'success',
      generationMessage: '图片生成完成',
      generatedImage: {
        ...image,
        ...recordImage,
        url: nextUrl
      }
    })
    return
  }

  updateDirectNode(nodeId, {
    generationStatus: 'error',
    generationMessage: '图片已生成，但当前地址无法加载，请稍后在历史记录中查看'
  })
}

function previewGeneratedImage(node) {
  const url = getGeneratedImageSrc(node)
  if (!url) return
  imagePreview.url = url
  imagePreview.alt = node?.generatedImage?.prompt || node?.title || '图片预览'
  imagePreview.visible = true
}

function closeImagePreview() {
  imagePreview.visible = false
  imagePreview.url = ''
  imagePreview.alt = ''
}

function downloadGeneratedImage(node) {
  const url = getGeneratedImageSrc(node)
  if (!url) return
  const link = document.createElement('a')
  link.href = url
  link.download = buildGeneratedImageFilename(node)
  link.rel = 'noopener noreferrer'
  document.body.appendChild(link)
  link.click()
  link.remove()
}

async function handleGeneratedVideoError(nodeId, event = null) {
  const node = directNodes.value.find((item) => item.id === nodeId)
  const video = node?.generatedVideo || {}
  const recordVideo = video.recordId ? await fetchRecordVideoResult(video.recordId) : null
  const nextUrl = normalizeDisplayVideoSrc(recordVideo?.url)
  if (nextUrl && nextUrl !== normalizeDisplayVideoSrc(video.url)) {
    updateDirectNode(nodeId, {
      generationStatus: 'success',
      generationMessage: '视频生成完成',
      generatedVideo: {
        ...video,
        ...recordVideo,
        url: nextUrl
      }
    })
    return
  }

  updateDirectNode(nodeId, {
    generationStatus: 'success',
    generationMessage: '视频已生成，正在刷新播放地址',
    generatedVideo: {
      ...video,
      isPlayable: false,
      loadError: true,
      loadErrorMessage: getVideoElementErrorMessage(event)
    }
  })
}

function handleGeneratedVideoReady(nodeId) {
  const node = directNodes.value.find((item) => item.id === nodeId)
  const video = node?.generatedVideo || {}
  updateDirectNode(nodeId, {
    generationStatus: 'success',
    generationMessage: '视频生成完成',
    generatedVideo: {
      ...video,
      isPlayable: true,
      loadError: false,
      loadErrorMessage: ''
    }
  })
}

function getVideoElementErrorMessage(event) {
  const code = event?.target?.error?.code
  const messages = {
    1: '视频加载被中止，可以打开原视频检查地址',
    2: '网络加载失败，可能是本地网络或 OSS 地址暂不可访问',
    3: '浏览器无法解码这个视频格式',
    4: '当前地址不是浏览器可播放的视频文件'
  }
  return messages[code] || '视频地址暂时无法播放'
}

function openGeneratedVideo(node) {
  const url = getGeneratedVideoSrc(node)
  if (!url) return
  window.open(url, '_blank', 'noopener,noreferrer')
}

function downloadGeneratedVideo(node) {
  const url = getGeneratedVideoSrc(node)
  if (!url) return
  const link = document.createElement('a')
  link.href = url
  link.download = buildGeneratedVideoFilename(node)
  link.rel = 'noopener noreferrer'
  document.body.appendChild(link)
  link.click()
  link.remove()
}

function downloadGeneratedAudio(node) {
  const url = getGeneratedAudioSrc(node)
  if (!url) return
  const link = document.createElement('a')
  link.href = url
  link.download = buildGeneratedAudioFilename(node)
  link.rel = 'noopener noreferrer'
  document.body.appendChild(link)
  link.click()
  link.remove()
}

function buildGeneratedImageFilename(node) {
  const image = node?.generatedImage || {}
  const base = String(node?.title || 'sluvo-image').trim().replace(/[\\/:*?"<>|\s]+/g, '-')
  const extension = inferImageExtension(image.url || image.thumbnailUrl || '')
  return `${base || 'sluvo-image'}${extension}`
}

function buildGeneratedVideoFilename(node) {
  const video = node?.generatedVideo || {}
  const base = String(node?.title || 'sluvo-video').trim().replace(/[\\/:*?"<>|\s]+/g, '-')
  const extension = inferVideoExtension(video.url || '')
  return `${base || 'sluvo-video'}${extension}`
}

function buildGeneratedAudioFilename(node) {
  const audio = node?.generatedAudio || {}
  const base = String(node?.title || 'sluvo-audio').trim().replace(/[\\/:*?"<>|\s]+/g, '-')
  const extension = inferAudioExtension(audio.url || '')
  return `${base || 'sluvo-audio'}${extension}`
}

function inferImageExtension(url) {
  const source = String(url || '').split('?')[0].toLowerCase()
  if (source.includes('image/png') || source.endsWith('.png')) return '.png'
  if (source.includes('image/webp') || source.endsWith('.webp')) return '.webp'
  if (source.includes('image/gif') || source.endsWith('.gif')) return '.gif'
  return '.jpg'
}

function inferVideoExtension(url) {
  const source = String(url || '').split('?')[0].toLowerCase()
  if (source.endsWith('.webm')) return '.webm'
  if (source.endsWith('.mov')) return '.mov'
  if (source.endsWith('.m3u8')) return '.m3u8'
  return '.mp4'
}

function inferAudioExtension(url) {
  const source = String(url || '').split('?')[0].toLowerCase()
  if (source.endsWith('.wav')) return '.wav'
  if (source.endsWith('.m4a')) return '.m4a'
  if (source.endsWith('.ogg')) return '.ogg'
  return '.mp3'
}

function rememberLocalUploadPreview(nodeId, previewUrl) {
  if (!previewUrl?.startsWith?.('blob:')) return
  const node = directNodes.value.find((item) => item.id === nodeId)
  localUploadPreviewUrls.set(nodeId, previewUrl)
  if (node?.clientId) localUploadPreviewUrls.set(node.clientId, previewUrl)
}

function getLocalUploadPreviewUrl(node) {
  if (!node) return ''
  return localUploadPreviewUrls.get(node.id) || localUploadPreviewUrls.get(node.clientId) || ''
}

function releaseLocalUploadPreview(nodeId) {
  const node = directNodes.value.find((item) => item.id === nodeId)
  const keys = [nodeId, node?.clientId].filter(Boolean)
  const urls = new Set(keys.map((key) => localUploadPreviewUrls.get(key)).filter(Boolean))
  urls.forEach((url) => {
    if (url?.startsWith?.('blob:')) URL.revokeObjectURL(url)
  })
  keys.forEach((key) => localUploadPreviewUrls.delete(key))
}

function revokeLocalPreviewForNode(nodeId) {
  const node = directNodes.value.find((item) => item.id === nodeId)
  const url = node?.media?.isLocalPreview ? node.media.url : ''
  if (url?.startsWith('blob:')) URL.revokeObjectURL(url)
  const previewUrl = node?.media?.previewUrl || ''
  if (previewUrl?.startsWith('blob:') && previewUrl !== url) URL.revokeObjectURL(previewUrl)
  normalizeManualReferenceImages(node?.referenceImages).forEach((reference) => {
    if (reference.previewUrl?.startsWith('blob:')) URL.revokeObjectURL(reference.previewUrl)
  })
  releaseLocalUploadPreview(nodeId)
}

function clearLocalPreviewUrls() {
  directNodes.value.forEach((node) => {
    if (node.media?.isLocalPreview && node.media.url?.startsWith('blob:')) {
      URL.revokeObjectURL(node.media.url)
    }
    if (node.media?.previewUrl?.startsWith('blob:') && node.media.previewUrl !== node.media.url) {
      URL.revokeObjectURL(node.media.previewUrl)
    }
    normalizeManualReferenceImages(node.referenceImages).forEach((reference) => {
      if (reference.previewUrl?.startsWith('blob:')) URL.revokeObjectURL(reference.previewUrl)
    })
  })
  new Set(localUploadPreviewUrls.values()).forEach((url) => {
    if (url?.startsWith?.('blob:')) URL.revokeObjectURL(url)
  })
  localUploadPreviewUrls.clear()
}

function openLibraryPicker() {
  libraryPicker.visible = true
  libraryPicker.source = 'Sluvo'
  libraryPicker.type = '图片'
  libraryPicker.selected = 0
}

function closeLibraryPicker() {
  libraryPicker.visible = false
}

function confirmLibraryPicker() {
  libraryPicker.visible = false
  showToast('暂无可选择素材')
}

async function loadImageGenerationCatalog() {
  try {
    const catalog = await fetchCreativeImageCatalog()
    if (catalog?.success === false) return

    const models = normalizeImageCatalogModels(catalog)
    const ratios = normalizeImageCatalogRatios(catalog)
    const resolutions = normalizeImageCatalogResolutions(catalog)
    if (models.length > 0) imageModelOptions.value = models
    if (ratios.length > 0) imageAspectRatioOptions.value = ratios
    if (resolutions.length > 0) imageResolutionOptions.value = resolutions
  } catch {
    imageModelOptions.value = [...fallbackImageModelOptions]
    imageAspectRatioOptions.value = [...fallbackImageAspectRatioOptions]
    imageResolutionOptions.value = [...fallbackImageResolutionOptions]
  }
}

async function loadVideoGenerationCatalog() {
  try {
    const catalog = await fetchCreativeVideoCatalog()
    if (catalog?.success === false) return
    const models = normalizeVideoCatalogModels(catalog)
    if (models.length > 0) videoModelOptions.value = models
  } catch {
    videoModelOptions.value = [...fallbackVideoModelOptions]
  }
}

async function loadAudioGenerationCatalog() {
  try {
    const catalog = await fetchCreativeAudioCatalog()
    if (catalog?.success === false) return
    const abilities = normalizeAudioCatalogAbilities(catalog)
    if (abilities.length > 0) audioAbilityOptions.value = abilities
  } catch {
    audioAbilityOptions.value = [...fallbackAudioAbilityOptions]
  }
}

async function loadAudioVoiceAssets() {
  try {
    const payload = await fetchCreativeVoiceAssets()
    const voices = normalizeAudioVoiceOptions(payload)
    audioVoiceOptions.value = voices
    if (voices.length > 0) {
      directNodes.value = directNodes.value.map((node) => {
        if (node.type !== 'audio_unit' || node.audioVoiceId) return node
        return {
          ...node,
          audioVoiceId: voices[0].voiceId,
          audioVoiceSourceType: voices[0].sourceType || 'system'
        }
      })
    }
  } catch {
    audioVoiceOptions.value = []
  }
}

function normalizeAudioCatalogAbilities(catalog) {
  const abilityItems =
    (Array.isArray(catalog?.data?.abilities) && catalog.data.abilities) ||
    (Array.isArray(catalog?.abilities) && catalog.abilities) ||
    findArrayByKey(catalog, ['abilities', 'audio_abilities', 'audioAbilities'])
  if (!abilityItems) return []

  return abilityItems
    .map((item) => {
      const id = item?.ability_type || item?.abilityType || item?.id || item?.value
      if (!id) return null
      const tiers = normalizeAudioTierOptions(item?.tiers)
      return {
        id,
        label: item?.label || item?.name || id,
        defaultTier: item?.default_tier || item?.defaultTier || tiers[0]?.id || 'hd',
        startPoints: Number.isFinite(Number(item?.start_points ?? item?.startPoints)) ? Number(item?.start_points ?? item?.startPoints) : null,
        tiers: tiers.length > 0 ? tiers : getFallbackAudioAbility(id)?.tiers || fallbackAudioAbilityOptions[0].tiers
      }
    })
    .filter(Boolean)
}

function normalizeAudioTierOptions(tiers) {
  const items = Array.isArray(tiers) ? tiers : Object.values(tiers || {})
  return items
    .map((tier) => {
      const id = tier?.tier_code || tier?.tierCode || tier?.id || tier?.value
      if (!id) return null
      const modelCode = tier?.model_code || tier?.modelCode || tier?.model || id
      return {
        id,
        label: modelCode ? `Minimax-${modelCode}` : tier?.tier_label || tier?.label || id,
        tierLabel: tier?.tier_label || tier?.tierLabel || tier?.label || id,
        modelCode
      }
    })
    .filter(Boolean)
}

function normalizeAudioVoiceOptions(payload) {
  const items =
    (Array.isArray(payload?.data?.assets) && payload.data.assets) ||
    (Array.isArray(payload?.data?.items) && payload.data.items) ||
    (Array.isArray(payload?.data?.voices) && payload.data.voices) ||
    (Array.isArray(payload?.assets) && payload.assets) ||
    (Array.isArray(payload?.items) && payload.items) ||
    findArrayByKey(payload, ['assets', 'items', 'voices', 'voice_assets', 'voiceAssets'])
  return (items || [])
    .map((item) => {
      const voiceId = String(item?.voice_id || item?.voiceId || item?.id || '').trim()
      if (!voiceId) return null
      return {
        voiceId,
        label: item?.label || item?.display_name || item?.displayName || item?.voice_name || item?.voiceName || voiceId,
        sourceType: item?.source_type || item?.sourceType || (item?.voice_type === 'system_voice' ? 'system' : 'custom'),
        sourceLabel: item?.source_label || item?.sourceLabel || '',
        categoryLabel: item?.category_label || item?.categoryLabel || '',
        styleLabel: item?.style_label || item?.styleLabel || '',
        description: item?.description || '',
        previewAudioUrl: item?.preview_audio_url || item?.previewAudioUrl || '',
        isFavorite: Boolean(item?.is_favorite || item?.isFavorite || item?.favorite),
        searchText: item?.search_text || item?.searchText || ''
      }
    })
    .filter(Boolean)
}

function normalizeVideoCatalogModels(catalog) {
  const modelItems =
    (Array.isArray(catalog?.data?.models) && catalog.data.models) ||
    (Array.isArray(catalog?.models) && catalog.models) ||
    findArrayByKey(catalog, ['models', 'video_models', 'videoModels', 'model_options', 'modelOptions'])
  if (!modelItems) return []

  return modelItems
    .map((item) => {
      if (typeof item === 'string') return { id: item, label: item, features: buildFallbackVideoFeatures(item), startPoints: null }
      const id = item?.model_code || item?.code || item?.id || item?.value || item?.model || item?.name
      if (!id || item?.hidden) return null
      return {
        id,
        label: item?.display_name || item?.label || item?.title || item?.model_name || item?.name || id,
        startPoints: Number.isFinite(Number(item?.start_points ?? item?.startPoints)) ? Number(item?.start_points ?? item?.startPoints) : null,
        defaultGenerationType: item?.default_generation_type || item?.defaultGenerationType || '',
        features: normalizeVideoFeatures(item)
      }
    })
    .filter(Boolean)
}

function normalizeVideoFeatures(modelItem) {
  const features = Array.isArray(modelItem?.features) ? modelItem.features : []
  if (!features.length) return buildFallbackVideoFeatures(modelItem?.model_code || modelItem?.id || modelItem?.value)

  return features
    .map((feature) => {
      const generationType = feature?.generation_type || feature?.generationType || feature?.id || ''
      if (!generationType) return null
      return {
        generationType,
        label: feature?.generation_type_label || feature?.generationTypeLabel || feature?.label || generationType,
        defaults: feature?.defaults || {},
        fields: normalizeVideoFeatureFields(feature?.fields)
      }
    })
    .filter(Boolean)
}

function normalizeVideoFeatureFields(fields) {
  return (Array.isArray(fields) ? fields : [])
    .map((field) => {
      const key = field?.key || field?.name || field?.id
      if (!key) return null
      return {
        key,
        label: field?.label || key,
        required: Boolean(field?.required),
        options: normalizeImageFieldOptions(field?.options)
      }
    })
    .filter(Boolean)
}

function buildFallbackVideoFeatures(modelId) {
  const baseFields = [
    { key: 'duration', label: 'Duration', options: fallbackVideoDurationOptions },
    { key: 'resolution', label: 'Resolution', options: fallbackVideoResolutionOptions.filter((item) => item.id !== '4k') },
    { key: 'aspect_ratio', label: 'Aspect Ratio', options: fallbackVideoAspectRatioOptions.filter((item) => item.id !== 'adaptive') }
  ]
  const seedance20Fields = [
    baseFields[0],
    { key: 'resolution', label: 'Resolution', options: fallbackVideoResolutionOptions },
    { key: 'aspect_ratio', label: 'Aspect Ratio', options: fallbackVideoAspectRatioOptions },
    { key: 'audio_enabled', label: 'Audio', options: [] }
  ]
  const seedance20TextFields = [
    ...seedance20Fields,
    { key: 'web_search', label: 'Web Search', options: [] }
  ]
  const isSeedance20 = String(modelId || '').startsWith('seedance_20')
  return ['text_to_video', 'image_to_video'].map((generationType) => ({
    generationType,
    label: generationType === 'image_to_video' ? '图生视频' : '文生视频',
    defaults: {
      duration: 5,
      resolution: '720p',
      aspect_ratio: String(modelId || '').startsWith('seedance_20') && generationType === 'text_to_video' ? 'adaptive' : '16:9',
      audio_enabled: false
    },
    fields: isSeedance20 ? (generationType === 'text_to_video' ? seedance20TextFields : seedance20Fields) : baseFields
  }))
}

function normalizeImageCatalogModels(catalog) {
  const modelItems = findArrayByKey(catalog, ['models', 'image_models', 'imageModels', 'model_options', 'modelOptions'])
  if (!modelItems) return []

  return modelItems
    .map((item) => {
      if (typeof item === 'string') return { id: item, label: item }
      const id = item?.model_code || item?.code || item?.id || item?.value || item?.model || item?.name
      if (!id) return null
      return {
        id,
        label: item?.display_name || item?.label || item?.title || item?.model_name || item?.name || id,
        startPoints: item?.start_points ?? item?.startPoints ?? null,
        features: normalizeImageFeatures(item),
        pricingRules: normalizeImagePricingRules(item)
      }
    })
    .filter(Boolean)
}

function normalizeImageFeatures(modelItem) {
  const features = Array.isArray(modelItem?.features) ? modelItem.features : []
  if (!features.length) return buildFallbackImageFeatures(modelItem?.model_code || modelItem?.id || modelItem?.value)

  return features.map((feature) => ({
    generationType: feature?.generation_type || feature?.generationType || '',
    defaults: feature?.defaults || {},
    fields: normalizeImageFeatureFields(feature?.fields)
  }))
}

function normalizeImageFeatureFields(fields) {
  return (Array.isArray(fields) ? fields : [])
    .map((field) => {
      const key = field?.key || field?.name || field?.id
      if (!key) return null
      return {
        key,
        label: field?.label || key,
        options: normalizeImageFieldOptions(field?.options)
      }
    })
    .filter(Boolean)
}

function normalizeImageFieldOptions(options) {
  return (Array.isArray(options) ? options : [])
    .map((option) => {
      if (typeof option === 'string') return { id: option, label: option.toUpperCase?.() || option }
      if (typeof option === 'number') return { id: String(option), label: String(option) }
      const id = option?.value || option?.id || option?.key
      if (!id) return null
      return { id: String(id), label: option?.label || option?.name || String(id).toUpperCase() }
    })
    .filter(Boolean)
}

function buildFallbackImageFeatures(modelId) {
  const normalized = normalizeImageModelPricingAlias(modelId)
  const baseFields = [
    { key: 'prompt', label: '图片描述', options: [] },
    { key: 'resolution', label: '分辨率', options: fallbackImageResolutionOptions },
    { key: 'aspect_ratio', label: '画面比例', options: fallbackImageAspectRatioOptions.map((ratio) => ({ id: ratio, label: ratio })) }
  ]
  const fields =
    normalized === 'gpt-image-2-fast'
      ? baseFields.filter((field) => field.key !== 'resolution')
      : normalized === 'gpt-image-2'
        ? [
            baseFields[0],
            { key: 'quality', label: '画质等级', options: fallbackImageQualityOptions },
            ...baseFields.slice(1)
          ]
        : baseFields

  return ['text_to_image', 'image_to_image'].map((generationType) => ({
    generationType,
    defaults: {
      resolution: '2k',
      quality: 'medium',
      aspect_ratio: '16:9'
    },
    fields
  }))
}

function normalizeImagePricingRules(modelItem) {
  const features = Array.isArray(modelItem?.features) ? modelItem.features : []
  const rules = []
  features.forEach((feature) => {
    const generationType = feature?.generation_type || feature?.generationType || ''
    ;(feature?.pricing_rules || feature?.pricingRules || []).forEach((rule) => {
      const points = Number(rule?.sell_price_points ?? rule?.sellPricePoints ?? rule?.points)
      if (!Number.isFinite(points)) return
      rules.push({
        generationType: rule?.generation_type || rule?.generationType || generationType,
        pricingRuleType: rule?.pricing_rule_type || rule?.pricingRuleType || feature?.pricing_rule_type || '',
        resolution: String(rule?.resolution || rule?.pricing_details?.resolution || '').toLowerCase(),
        quality: String(rule?.quality || rule?.pricing_details?.quality || '').toLowerCase(),
        points
      })
    })
  })

  return rules.length > 0 ? rules : buildFallbackImagePricingRules(modelItem?.model_code || modelItem?.id || modelItem?.value)
}

function buildFallbackImagePricingRules(modelId) {
  const pricing = fallbackImagePricingRules[modelId] || fallbackImagePricingRules[normalizeImageModelPricingAlias(modelId)] || null
  if (!pricing) return []
  if (pricing.fixed) {
    return [{ generationType: '', pricingRuleType: 'single_fixed', resolution: '', quality: '', points: pricing.fixed }]
  }
  return Object.entries(pricing).map(([resolution, points]) => ({
    generationType: '',
    pricingRuleType: 'fixed_table',
    resolution,
    quality: '',
    points
  }))
}

function normalizeImageModelPricingAlias(modelId) {
  const value = String(modelId || '').trim().toLowerCase()
  const aliases = {
    low_cost: 'nano-banana-2-低价版',
    'shenlu-image-fast': 'nano-banana-2-低价版',
    'nano_banana_2_low': 'nano-banana-2-低价版',
    'nano-banana-2-low': 'nano-banana-2-低价版',
    'nano_banana_pro_low': 'nano-banana-pro-低价版',
    'nano-banana-pro-low': 'nano-banana-pro-低价版',
    'gpt_image_2_fast': 'gpt-image-2-fast',
    'gpt-image-2-low': 'gpt-image-2-fast'
  }
  return aliases[value] || modelId
}

function normalizeImageCatalogRatios(catalog) {
  const ratioItems =
    findArrayByKey(catalog, ['aspect_ratios', 'aspectRatios', 'ratios', 'ratio_options', 'ratioOptions']) ||
    findFirstStringArray(catalog, (item) => /^\d+:\d+$/.test(item))
  if (!ratioItems) return []

  return [...new Set(ratioItems.map((item) => (typeof item === 'string' ? item : item?.value || item?.id)).filter(Boolean))]
}

function normalizeImageCatalogResolutions(catalog) {
  const resolutionItems =
    findArrayByKey(catalog, ['resolutions', 'resolution_options', 'resolutionOptions', 'image_resolutions', 'imageResolutions']) ||
    findFirstStringArray(catalog, (item) => /^[124]k$/i.test(item))
  if (!resolutionItems) return []

  const seen = new Set()
  return resolutionItems
    .map((item) => {
      const id = String(typeof item === 'string' ? item : item?.value || item?.id || item?.key || '').trim().toLowerCase()
      if (!id || seen.has(id)) return null
      seen.add(id)
      return {
        id,
        label: item?.label || item?.name || id.toUpperCase()
      }
    })
    .filter(Boolean)
}

function findArrayByKey(value, keys, depth = 0) {
  if (!value || depth > 5) return null
  if (Array.isArray(value)) {
    for (const item of value) {
      const found = findArrayByKey(item, keys, depth + 1)
      if (found) return found
    }
    return null
  }
  if (typeof value !== 'object') return null

  for (const key of keys) {
    if (Array.isArray(value[key])) return value[key]
  }
  for (const item of Object.values(value)) {
    const found = findArrayByKey(item, keys, depth + 1)
    if (found) return found
  }
  return null
}

function findFirstStringArray(value, predicate, depth = 0) {
  if (!value || depth > 5) return null
  if (Array.isArray(value)) {
    const stringItems = value.filter((item) => typeof item === 'string')
    if (stringItems.length > 0 && stringItems.every(predicate)) return stringItems
    for (const item of value) {
      const found = findFirstStringArray(item, predicate, depth + 1)
      if (found) return found
    }
    return null
  }
  if (typeof value !== 'object') return null

  for (const item of Object.values(value)) {
    const found = findFirstStringArray(item, predicate, depth + 1)
    if (found) return found
  }
  return null
}

function getImageGenerationType(node) {
  return getDirectImageReferenceUrls(node?.id).length > 0 ? 'image_to_image' : 'text_to_image'
}

function hasPendingReferenceUploads(nodeId) {
  return getDirectVisualReferenceItems(nodeId).some((reference) => reference.status === 'uploading')
}

function normalizeManualReferenceImages(value) {
  return (Array.isArray(value) ? value : [])
    .map((item) => {
      const id = item?.id || `manual-ref-${Date.now()}-${Math.round(Math.random() * 10000)}`
      const url = item?.url || ''
      const previewUrl = item?.previewUrl || item?.thumbnailUrl || url
      if (!url && !previewUrl) return null
      const kind = normalizeReferenceKind(item?.kind || item?.mediaKind || item?.media_type || item?.type, url || previewUrl, item?.name)
      return {
        id,
        source: 'manual',
        kind,
        url,
        previewUrl,
        name: item?.name || getReferenceKindLabel({ kind }),
        status: item?.status || (url ? 'success' : 'uploading'),
        progress: Number(item?.progress || 0),
        width: Number(item?.width || 0),
        height: Number(item?.height || 0),
        durationSeconds: Number(item?.durationSeconds || item?.duration_seconds || 0),
        assetId: item?.assetId || '',
        storageObjectId: item?.storageObjectId || ''
      }
    })
    .filter(Boolean)
}

function normalizeReferenceMentions(value) {
  return (Array.isArray(value) ? value : [])
    .map((item, index) => {
      const referenceId = String(item?.referenceId || item?.reference_id || '')
      const label = String(item?.label || item?.name || `图片${index + 1}`)
      return {
        id: String(item?.id || `${referenceId || label || 'reference'}-${index}`),
        referenceId,
        label
      }
    })
    .filter((item) => item.referenceId || item.label)
}

function normalizePromptSegments(value, fallback = null) {
  const segments = Array.isArray(value)
    ? value
    : [
        ...normalizeReferenceMentions(fallback?.referenceMentions).map((mention) => ({ type: 'reference', ...mention })),
        ...(String(fallback?.prompt || fallback?.body || '') ? [{ type: 'text', text: String(fallback?.prompt || fallback?.body || '') }] : [])
      ]
  const normalized = []
  segments.forEach((segment, index) => {
    const type = segment?.type === 'reference' ? 'reference' : segment?.type === 'audio_token' ? 'audio_token' : 'text'
    if (type === 'reference') {
      const referenceId = String(segment.referenceId || segment.reference_id || '')
      const label = String(segment.label || segment.name || `图片${index + 1}`)
      if (!referenceId && !label) return
      normalized.push({
        type: 'reference',
        id: String(segment.id || `${referenceId || label || 'reference'}-${index}`),
        referenceId,
        label,
        previewUrl: segment.previewUrl || segment.url || ''
      })
      return
    }
    if (type === 'audio_token') {
      const value = String(segment.value ?? segment.text ?? '')
      if (!value) return
      normalized.push({
        type: 'audio_token',
        id: String(segment.id || `audio-token-${index}-${value}`),
        value,
        label: String(segment.label || value),
        tokenKind: segment.tokenKind || 'tag'
      })
      return
    }
    const text = String(segment?.text ?? segment?.value ?? '')
    if (!text) return
    const previous = normalized.at(-1)
    if (previous?.type === 'text') {
      previous.text += text
    } else {
      normalized.push({ type: 'text', text })
    }
  })
  return normalized
}

function getDirectImageReferenceItems(nodeId) {
  const node = directNodes.value.find((item) => item.id === nodeId)
  const connected = directEdges.value
    .filter((edge) => edge.targetId === nodeId)
    .flatMap((edge) => getDirectImageReferencesFromEndpoint(edge.sourceId))
  const manual = normalizeManualReferenceImages(node?.referenceImages).filter((reference) => getReferenceKind(reference) === 'image')
  const items = [...connected, ...manual]
  const order = Array.isArray(node?.referenceOrder) ? node.referenceOrder : []
  if (!order.length) return items

  const itemMap = new Map(items.map((item) => [item.id, item]))
  const ordered = order.map((id) => itemMap.get(id)).filter(Boolean)
  const orderedIds = new Set(ordered.map((item) => item.id))
  return [...ordered, ...items.filter((item) => !orderedIds.has(item.id))]
}

function getDirectImageReferencesFromEndpoint(endpointId) {
  if (isDirectGroupId(endpointId)) {
    return getDirectGroupMembers(endpointId)
      .map((node) => getDirectImageReferenceFromNode(node, `edge:${endpointId}:${node.id}`))
      .filter(Boolean)
  }

  const source = directNodes.value.find((item) => item.id === endpointId)
  const reference = getDirectImageReferenceFromNode(source, `edge:${endpointId}`)
  return reference ? [reference] : []
}

function getDirectImageReferenceFromNode(source, id = '') {
  if (!source) return null
  const url = source.generatedImage?.url || source.media?.url || ''
  const previewUrl =
    source.generatedImage?.url ||
    (source.type === 'uploaded_asset' ? getUploadedImageSrc(source) : '') ||
    source.media?.previewUrl ||
    source.media?.thumbnailUrl ||
    url
  if (!previewUrl && !url) return null
  if (source.media?.kind && getReferenceKind({ kind: source.media.kind, url, previewUrl, name: source.media.name }) !== 'image') return null

  return {
    id: id || `edge:${source.id}`,
    source: 'edge',
    url,
    previewUrl,
    name: source.title || source.media?.name || '连线参考图',
    status: 'success',
    kind: 'image',
    progress: 100,
    width: Number(source.generatedImage?.width || source.media?.width || 0),
    height: Number(source.generatedImage?.height || source.media?.height || 0)
  }
}

function getDirectVisualReferenceItems(nodeId) {
  const node = directNodes.value.find((item) => item.id === nodeId)
  if (node?.type !== 'video_unit') return getDirectImageReferenceItems(nodeId)
  return getDirectVideoReferenceItems(nodeId)
}

function getDirectVideoReferenceItems(nodeId) {
  const node = directNodes.value.find((item) => item.id === nodeId)
  const allowedKinds = getAllowedReferenceUploadKinds(node)
  if (!allowedKinds.length) return []

  const imageItems = allowedKinds.includes('image') ? getDirectImageReferenceItems(nodeId) : []
  const mediaItems = directEdges.value
    .filter((edge) => edge.targetId === nodeId)
    .map((edge) => {
      const source = directNodes.value.find((item) => item.id === edge.sourceId)
      const generatedVideoUrl = source?.generatedVideo?.url || ''
      const generatedAudioUrl = source?.generatedAudio?.url || ''
      const mediaUrl = source?.media?.url || ''
      const kind =
        source?.type === 'video_unit' && generatedVideoUrl
          ? 'video'
          : source?.type === 'audio_unit' && generatedAudioUrl
            ? 'audio'
            : source?.media?.kind || ''
      const url = source?.type === 'video_unit' ? generatedVideoUrl : source?.type === 'audio_unit' ? generatedAudioUrl : mediaUrl
      if (!allowedKinds.includes(kind) || !url) return null
      return {
        id: `edge:${edge.sourceId}:${kind}`,
        source: 'edge',
        kind,
        url,
        previewUrl: source?.media?.previewUrl || source?.media?.thumbnailUrl || url,
        name: source?.title || source?.media?.name || getReferenceKindLabel({ kind }),
        status: 'success',
        progress: 100,
        width: Number(source?.media?.width || 0),
        height: Number(source?.media?.height || 0),
        durationSeconds: Number(source?.media?.durationSeconds || 0)
      }
    })
    .filter(Boolean)
  const manualMedia = normalizeManualReferenceImages(node?.referenceImages).filter((reference) => {
    const kind = getReferenceKind(reference)
    return kind !== 'image' && allowedKinds.includes(kind)
  })
  const items = [...imageItems, ...mediaItems, ...manualMedia]
  const order = Array.isArray(node?.referenceOrder) ? node.referenceOrder : []
  if (!order.length) return items

  const itemMap = new Map(items.map((item) => [item.id, item]))
  const ordered = order.map((id) => itemMap.get(id)).filter(Boolean)
  const orderedIds = new Set(ordered.map((item) => item.id))
  return [...ordered, ...items.filter((item) => !orderedIds.has(item.id))]
}

function getDirectVideoReferencePayload(nodeId, generationType = '') {
  const node = directNodes.value.find((item) => item.id === nodeId)
  const mode = getVideoReferenceMode(node, generationType)
  if (mode === 'none') return { imageRefs: [], videoRefs: [], audioRefs: [], firstFrame: '', lastFrame: '' }

  const references = getDirectVideoReferenceItems(nodeId).filter((reference) => reference.status !== 'error')
  const imageRefs = references.filter((reference) => getReferenceKind(reference) === 'image').map((reference) => reference.url).filter(Boolean)
  const videoRefs = []
  const audioRefs = []
  if (mode === 'mixed') {
    references.forEach((reference) => {
      const kind = getReferenceKind(reference)
      if (kind === 'video' && reference.url) videoRefs.push(reference.url)
      if (kind === 'audio' && reference.url) audioRefs.push(reference.url)
    })
  }

  return {
    imageRefs: [...new Set(imageRefs)],
    videoRefs: [...new Set(videoRefs)],
    audioRefs: [...new Set(audioRefs)],
    firstFrame: imageRefs[0] || '',
    lastFrame: mode === 'start_end' ? imageRefs[1] || imageRefs.at(-1) || '' : ''
  }
}

function getReferenceMentionItems(node) {
  const references = getDirectImageReferenceItems(node?.id)
  const referenceMap = new Map(references.map((reference, index) => [reference.id, { ...reference, label: `图片${index + 1}` }]))
  return normalizeReferenceMentions(node?.referenceMentions).map((mention, index) => {
    const reference = referenceMap.get(mention.referenceId)
    return {
      ...mention,
      label: mention.label || reference?.label || `图片${index + 1}`,
      previewUrl: reference?.previewUrl || reference?.url || ''
    }
  })
}

function getReferenceAspectRatio(reference) {
  const width = Number(reference?.width || 0)
  const height = Number(reference?.height || 0)
  if (width > 0 && height > 0) return Math.min(Math.max(width / height, 0.42), 2.4)
  return 1
}

function insertReferenceToken(nodeId, index) {
  const node = directNodes.value.find((item) => item.id === nodeId)
  if (!node) return
  const reference = getDirectImageReferenceItems(nodeId)[index]
  if (!reference) return
  const label = `图片${index + 1}`
  const mention = {
    type: 'reference',
    id: `reference-mention-${Date.now()}-${Math.round(Math.random() * 10000)}`,
    referenceId: reference.id,
    label,
    previewUrl: reference.previewUrl || reference.url || ''
  }
  rememberHistory()
  insertPromptReferenceAtCaret(nodeId, mention)
  scheduleCanvasSave(180)
  showToast(`已引用${label}`)
}

function insertPromptReferenceAtCaret(nodeId, mention) {
  const editor = directPromptEditorElements.get(nodeId)
  if (!editor) {
    const node = directNodes.value.find((item) => item.id === nodeId)
    const segments = [...normalizePromptSegments(node?.promptSegments, node), mention]
    updateDirectNode(nodeId, {
      promptSegments: segments,
      prompt: getPromptTextFromSegments(segments),
      referenceMentions: getReferenceMentionsFromSegments(segments)
    })
    return
  }

  editor.focus({ preventScroll: true })
  if (!restoreDirectPromptSelection(nodeId)) {
    placeCaretAtEnd(editor)
  }
  const selection = window.getSelection?.()
  if (!selection || selection.rangeCount === 0) return
  const range = selection.getRangeAt(0)
  range.deleteContents()
  const token = createPromptReferenceToken(mention, nodeId)
  range.insertNode(token)
  const afterRange = document.createRange()
  afterRange.setStartAfter(token)
  afterRange.collapse(true)
  selection.removeAllRanges()
  selection.addRange(afterRange)
  saveDirectPromptSelection(nodeId)
  handleDirectPromptInput(nodeId, { currentTarget: editor })
}

function getImageModelLabel(modelId) {
  return imageModelOptions.value.find((model) => model.id === modelId)?.label || modelId || fallbackImageModelOptions[0].label
}

function getImageResolutionLabel(resolutionId) {
  const normalized = normalizeImageResolutionValue(resolutionId)
  return imageResolutionOptions.value.find((resolution) => resolution.id === normalized)?.label || normalized.toUpperCase()
}

function findImageModelOption(modelId) {
  const normalizedAlias = normalizeImageModelPricingAlias(modelId)
  return (
    imageModelOptions.value.find((model) => model.id === modelId) ||
    imageModelOptions.value.find((model) => model.id === normalizedAlias) ||
    fallbackImageModelOptions.find((model) => model.id === modelId) ||
    fallbackImageModelOptions.find((model) => model.id === normalizedAlias) ||
    null
  )
}

function getSelectedImageFeature(node) {
  const model = findImageModelOption(node?.imageModelId || fallbackImageModelOptions[0].id)
  const features = model?.features?.length ? model.features : buildFallbackImageFeatures(model?.id || node?.imageModelId)
  const generationType = getImageGenerationType(node)
  return features.find((feature) => feature.generationType === generationType) || features[0] || null
}

function getImageFieldConfig(node, key) {
  return getSelectedImageFeature(node)?.fields?.find((field) => field.key === key) || null
}

function hasImageField(node, key) {
  return Boolean(getImageFieldConfig(node, key))
}

function getImageFieldOptions(node, key, fallback) {
  const options = getImageFieldConfig(node, key)?.options || []
  if (options.length > 0) return options
  return Array.isArray(fallback) ? fallback.map((item) => (typeof item === 'string' ? { id: item, label: item } : item)) : []
}

function getImageDefaultValue(node, key, fallback) {
  const defaults = getSelectedImageFeature(node)?.defaults || {}
  return defaults[key] || defaults[snakeToCamel(key)] || fallback
}

function snakeToCamel(value) {
  return String(value || '').replace(/_([a-z])/g, (_, letter) => letter.toUpperCase())
}

function syncImageNodeSettings(node) {
  if (!node) return
  const resolutionOptions = getImageFieldOptions(node, 'resolution', fallbackImageResolutionOptions)
  const qualityOptions = getImageFieldOptions(node, 'quality', fallbackImageQualityOptions)
  const ratioOptions = getImageFieldOptions(node, 'aspect_ratio', imageAspectRatioOptions.value)
  const patch = {}

  if (hasImageField(node, 'resolution')) {
    const current = normalizeImageResolutionValue(node.imageResolution)
    const fallback = getImageDefaultValue(node, 'resolution', fallbackImageResolutionOptions[1].id)
    patch.imageResolution = resolutionOptions.some((option) => option.id === current) ? current : fallback
  }
  if (hasImageField(node, 'quality')) {
    const current = normalizeImageQualityValue(node.imageQuality)
    const fallback = getImageDefaultValue(node, 'quality', 'medium')
    patch.imageQuality = qualityOptions.some((option) => option.id === current) ? current : fallback
  }
  if (hasImageField(node, 'aspect_ratio')) {
    const current = node.aspectRatio || fallbackImageAspectRatioOptions[0]
    const fallback = getImageDefaultValue(node, 'aspect_ratio', fallbackImageAspectRatioOptions[0])
    patch.aspectRatio = ratioOptions.some((option) => (option.id || option) === current) ? current : fallback
  }
  updateDirectNode(node.id, patch)
}

function findVideoModelOption(modelId) {
  return (
    videoModelOptions.value.find((model) => model.id === modelId) ||
    fallbackVideoModelOptions.find((model) => model.id === modelId) ||
    fallbackVideoModelOptions[0] ||
    null
  )
}

function getDefaultVideoGenerationType(modelId) {
  const model = findVideoModelOption(modelId)
  return model?.defaultGenerationType || model?.features?.[0]?.generationType || 'text_to_video'
}

function getVideoFeatureOptions(node) {
  const model = findVideoModelOption(node?.videoModelId || fallbackVideoModelOptions[0].id)
  const features = model?.features?.length ? model.features : buildFallbackVideoFeatures(model?.id || node?.videoModelId)
  return features.map((feature) => ({
    id: feature.generationType,
    label: feature.label || feature.generationType
  }))
}

function getSelectedVideoFeature(node) {
  const model = findVideoModelOption(node?.videoModelId || fallbackVideoModelOptions[0].id)
  const features = model?.features?.length ? model.features : buildFallbackVideoFeatures(model?.id || node?.videoModelId)
  const generationType = getVideoGenerationType(node)
  return features.find((feature) => feature.generationType === generationType) || features[0] || null
}

function getVideoGenerationType(node) {
  const model = findVideoModelOption(node?.videoModelId || fallbackVideoModelOptions[0].id)
  const features = model?.features?.length ? model.features : buildFallbackVideoFeatures(model?.id || node?.videoModelId)
  const requested = String(node?.videoGenerationType || '').trim()
  if (requested && features.some((feature) => feature.generationType === requested)) return requested
  const imageRefs = node?.id ? getDirectImageReferenceUrls(node.id) : []
  if (imageRefs.length > 0 && features.some((feature) => feature.generationType === 'image_to_video')) return 'image_to_video'
  return model?.defaultGenerationType || features[0]?.generationType || 'text_to_video'
}

function getVideoReferenceMode(node, generationType = '') {
  const type = String(generationType || node?.videoGenerationType || '').trim().toLowerCase()
  if (type === 'text_to_video') return 'none'
  if (type === 'image_to_video') return 'image'
  if (type === 'start_end_to_video') return 'start_end'
  if (type === 'reference_to_video') return 'mixed'
  return 'none'
}

function getAllowedReferenceUploadKinds(node) {
  if (node?.type === 'image_unit') return ['image']
  if (node?.type !== 'video_unit') return []
  const mode = getVideoReferenceMode(node)
  if (mode === 'image' || mode === 'start_end') return ['image']
  if (mode === 'mixed') return ['image', 'video', 'audio']
  return []
}

function isStartEndVideoNode(node) {
  return node?.type === 'video_unit' && getVideoReferenceMode(node) === 'start_end'
}

function getStartEndFrameReference(node, slot) {
  if (!node?.id) return null
  const index = slot === 'last' ? 1 : 0
  return getDirectImageReferenceItems(node.id)[index] || null
}

function canUploadDirectReference(node) {
  return getAllowedReferenceUploadKinds(node).length > 0
}

function shouldShowReferenceStrip(node) {
  return node?.type === 'image_unit' || canUploadDirectReference(node)
}

function getReferenceUploadAccept(node) {
  const kinds = getAllowedReferenceUploadKinds(node)
  return kinds.map((kind) => `${kind}/*`).join(',') || 'image/*'
}

function getReferenceUploadTitle(node) {
  const kinds = getAllowedReferenceUploadKinds(node)
  if (kinds.includes('video') || kinds.includes('audio')) return '上传参考素材'
  return '上传参考图'
}

function getReferenceUploadRejectMessage(node) {
  const kinds = getAllowedReferenceUploadKinds(node)
  if (!kinds.length) return '当前视频类型不支持参考素材'
  return kinds.includes('video') || kinds.includes('audio') ? '请选择图片、视频或音频文件' : '请选择图片文件'
}

function normalizeReferenceKind(kind, url = '', name = '') {
  const value = String(kind || '').trim().toLowerCase()
  if (['image', 'video', 'audio'].includes(value)) return value
  const source = `${url || ''} ${name || ''}`.toLowerCase()
  if (/\.(mp4|webm|mov|m3u8)(\?|$|\s)/i.test(source)) return 'video'
  if (/\.(mp3|wav|m4a|aac|ogg|flac)(\?|$|\s)/i.test(source)) return 'audio'
  return 'image'
}

function getReferenceKind(reference) {
  return normalizeReferenceKind(reference?.kind || reference?.mediaKind || reference?.media_type, reference?.url || reference?.previewUrl, reference?.name)
}

function getReferenceKindLabel(reference) {
  const labels = {
    image: '参考图',
    video: '参考视频',
    audio: '参考音频'
  }
  return labels[getReferenceKind(reference)] || '参考素材'
}

function getVideoGenerationBlocker(node) {
  if (!node || node.type !== 'video_unit') return ''
  const mode = getVideoReferenceMode(node, getVideoGenerationType(node))
  const refs = getDirectVideoReferencePayload(node.id, getVideoGenerationType(node))
  if (mode === 'image' && refs.imageRefs.length < 1) return '图生视频需要先上传或连接一张参考图'
  if (mode === 'start_end' && refs.imageRefs.length < 2) return '首尾帧视频需要按顺序提供首帧和尾帧两张图'
  return ''
}

function getVideoFieldConfig(node, key) {
  return getSelectedVideoFeature(node)?.fields?.find((field) => field.key === key) || null
}

function hasVideoField(node, key) {
  return Boolean(getVideoFieldConfig(node, key))
}

function getVideoFieldOptions(node, key, fallback) {
  const options = getVideoFieldConfig(node, key)?.options || []
  if (options.length > 0) return options
  return Array.isArray(fallback) ? fallback.map((item) => (typeof item === 'string' ? { id: item, label: item } : item)) : []
}

function getVideoDurationOptions(node) {
  return getVideoFieldOptions(node, 'duration', fallbackVideoDurationOptions)
}

function formatVideoAspectRatioLabel(option) {
  const value = String(option?.id || option || '')
  if (value === 'adaptive') return 'Auto'
  return option?.label || value
}

function formatVideoDurationValue(duration) {
  return `${normalizeVideoDurationValue(duration)}秒`
}

function getVideoDurationOptionIndex(node) {
  const options = getVideoDurationOptions(node)
  const current = normalizeVideoDurationValue(node?.videoDuration)
  const index = options.findIndex((option) => Number(option.id) === current)
  return index >= 0 ? index : 0
}

function setVideoDurationByIndex(node, event) {
  const options = getVideoDurationOptions(node)
  const index = Number(event?.target?.value ?? 0)
  const option = options[Math.max(0, Math.min(options.length - 1, index))]
  if (option) setVideoNodeSetting(node, 'duration', Number(option.id))
}

function getVideoSettingsSummary(node) {
  const parts = []
  if (hasVideoField(node, 'aspect_ratio')) parts.push(formatVideoAspectRatioLabel({ id: node?.aspectRatio || getVideoDefaultValue(node, 'aspect_ratio', '16:9') }))
  if (hasVideoField(node, 'resolution')) parts.push(String(node?.videoResolution || getVideoDefaultValue(node, 'resolution', '720p')).toUpperCase())
  if (hasVideoField(node, 'duration')) parts.push(formatVideoDurationValue(node?.videoDuration))
  if (hasVideoField(node, 'audio_enabled') && node?.videoAudioEnabled) parts.push('原声')
  if (hasVideoField(node, 'web_search') && node?.videoWebSearch) parts.push('联网')
  return parts.join(' · ') || '参数'
}

function isVideoFieldOptionSelected(node, key, value) {
  const current =
    key === 'duration'
      ? normalizeVideoDurationValue(node?.videoDuration)
      : key === 'resolution'
        ? normalizeVideoResolutionValue(node?.videoResolution)
        : key === 'aspect_ratio'
          ? node?.aspectRatio
          : key === 'quality_mode'
            ? String(node?.videoQualityMode || '').trim().toLowerCase()
            : key === 'motion_strength'
              ? String(node?.videoMotionStrength || '').trim().toLowerCase()
              : ''
  const next = key === 'duration' ? Number(value) : String(value || '').trim().toLowerCase()
  return current === next
}

function setVideoNodeSetting(node, key, value) {
  if (!node || node.generationStatus === 'running') return
  const patch = {}
  if (key === 'duration') patch.videoDuration = normalizeVideoDurationValue(value)
  if (key === 'resolution') patch.videoResolution = normalizeVideoResolutionValue(value)
  if (key === 'aspect_ratio') patch.aspectRatio = value
  if (key === 'quality_mode') patch.videoQualityMode = String(value || '').trim().toLowerCase()
  if (key === 'motion_strength') patch.videoMotionStrength = String(value || '').trim().toLowerCase()
  if (Object.keys(patch).length === 0) return
  updateDirectNode(node.id, patch)
  refreshVideoEstimate({ ...node, ...patch })
}

function toggleVideoBooleanSetting(node, key) {
  if (!node || node.generationStatus === 'running') return
  const patch =
    key === 'audio_enabled'
      ? { videoAudioEnabled: !node.videoAudioEnabled }
      : key === 'web_search'
        ? { videoWebSearch: !node.videoWebSearch }
        : {}
  if (Object.keys(patch).length === 0) return
  updateDirectNode(node.id, patch)
  refreshVideoEstimate({ ...node, ...patch })
}

function handleVideoSettingsToggle(nodeId, event) {
  activeVideoSettingsNodeId.value = event?.target?.open ? nodeId : activeVideoSettingsNodeId.value === nodeId ? '' : activeVideoSettingsNodeId.value
}

function getVideoDefaultValue(node, key, fallback) {
  const defaults = getSelectedVideoFeature(node)?.defaults || {}
  return defaults[key] ?? defaults[snakeToCamel(key)] ?? fallback
}

function syncVideoNodeSettings(node) {
  if (!node) return
  const features = getVideoFeatureOptions(node)
  const generationType = features.some((feature) => feature.id === node.videoGenerationType)
    ? node.videoGenerationType
    : getDefaultVideoGenerationType(node.videoModelId)
  const patch = { videoGenerationType: generationType }

  const nextNode = { ...node, ...patch }
  const durationOptions = getVideoFieldOptions(nextNode, 'duration', fallbackVideoDurationOptions)
  const resolutionOptions = getVideoFieldOptions(nextNode, 'resolution', fallbackVideoResolutionOptions)
  const ratioOptions = getVideoFieldOptions(nextNode, 'aspect_ratio', fallbackVideoAspectRatioOptions)
  const qualityOptions = getVideoFieldOptions(nextNode, 'quality_mode', fallbackVideoQualityModeOptions)
  const motionOptions = getVideoFieldOptions(nextNode, 'motion_strength', fallbackVideoMotionStrengthOptions)

  if (hasVideoField(nextNode, 'duration')) {
    const current = normalizeVideoDurationValue(node.videoDuration)
    const fallback = normalizeVideoDurationValue(getVideoDefaultValue(nextNode, 'duration', fallbackVideoDurationOptions[1].id))
    patch.videoDuration = durationOptions.some((option) => Number(option.id) === current) ? current : fallback
  }
  if (hasVideoField(nextNode, 'resolution')) {
    const current = normalizeVideoResolutionValue(node.videoResolution)
    const fallback = normalizeVideoResolutionValue(getVideoDefaultValue(nextNode, 'resolution', '720p'))
    patch.videoResolution = resolutionOptions.some((option) => option.id === current) ? current : fallback
  }
  if (hasVideoField(nextNode, 'aspect_ratio')) {
    const current = node.aspectRatio || '16:9'
    const fallback = getVideoDefaultValue(nextNode, 'aspect_ratio', '16:9')
    patch.aspectRatio = ratioOptions.some((option) => option.id === current) ? current : fallback
  }
  if (hasVideoField(nextNode, 'quality_mode')) {
    const current = String(node.videoQualityMode || '').trim().toLowerCase()
    const fallback = String(getVideoDefaultValue(nextNode, 'quality_mode', qualityOptions[0]?.id || '') || '').trim().toLowerCase()
    patch.videoQualityMode = qualityOptions.some((option) => option.id === current) ? current : fallback
  }
  if (hasVideoField(nextNode, 'motion_strength')) {
    const current = String(node.videoMotionStrength || '').trim().toLowerCase()
    const fallback = String(getVideoDefaultValue(nextNode, 'motion_strength', motionOptions[0]?.id || '') || '').trim().toLowerCase()
    patch.videoMotionStrength = motionOptions.some((option) => option.id === current) ? current : fallback
  }
  if (hasVideoField(nextNode, 'audio_enabled')) {
    patch.videoAudioEnabled = Boolean(node.videoAudioEnabled ?? getVideoDefaultValue(nextNode, 'audio_enabled', false))
  }
  patch.videoWebSearch = hasVideoField(nextNode, 'web_search')
    ? Boolean(node.videoWebSearch ?? getVideoDefaultValue(nextNode, 'web_search', false))
    : false

  updateDirectNode(node.id, patch)
  refreshVideoEstimate({ ...node, ...patch })
}

function normalizeVideoResolutionValue(resolution) {
  return String(resolution || '720p').trim().toLowerCase()
}

function normalizeVideoDurationValue(duration) {
  const value = Number(duration || 5)
  return Number.isFinite(value) && value > 0 ? Math.round(value) : 5
}

function getDirectNodeZIndex(node, index = 0) {
  const base = index + 1
  if (node?.id && node.id === activeVideoSettingsNodeId.value) return 260
  if (node?.id && node.id === activeDirectNodeId.value) return 160
  if (node?.id && selectedDirectNodeIds.value.includes(node.id)) return 150
  if (node?.id && node.id === focusedDirectNodeId.value) return 140
  return base
}

function getImageGenerationPoints(node) {
  const modelId = node?.imageModelId || fallbackImageModelOptions[0].id
  const model = findImageModelOption(modelId)
  const rules = model?.pricingRules?.length ? model.pricingRules : buildFallbackImagePricingRules(modelId)
  if (!rules.length) return Number(model?.startPoints) || null

  const resolution = normalizeImageResolutionValue(node?.imageResolution)
  const preferredQuality = hasImageField(node, 'quality') ? normalizeImageQualityValue(node?.imageQuality) : ''
  const generationType = getImageGenerationType(node)
  const candidates = [
    (rule) => rule.generationType === generationType && rule.resolution === resolution && rule.quality === preferredQuality,
    (rule) => rule.generationType === generationType && rule.resolution === resolution && !rule.quality,
    (rule) => !rule.generationType && rule.resolution === resolution && !rule.quality,
    (rule) => rule.resolution === resolution && rule.quality === preferredQuality,
    (rule) => rule.resolution === resolution && !rule.quality,
    (rule) => rule.pricingRuleType === 'single_fixed' || !rule.resolution
  ]
  const matched = candidates.map((predicate) => rules.find(predicate)).find(Boolean)
  return Number.isFinite(Number(matched?.points)) ? Number(matched.points) : Number(model?.startPoints) || null
}

function getImageGenerationPointsButtonLabel(node) {
  const points = getImageGenerationPoints(node)
  return Number.isFinite(points) ? points : '--'
}

function normalizeImageResolutionValue(resolutionId) {
  return String(resolutionId || fallbackImageResolutionOptions[1].id).trim().toLowerCase()
}

function normalizeImageQualityValue(quality) {
  return String(quality || 'medium').trim().toLowerCase()
}

function buildDirectVideoPayload(node, options = {}) {
  const generationType = getVideoGenerationType(node)
  const refs = getDirectVideoReferencePayload(node?.id || '', generationType)
  const payload = {
    ownership_mode: 'standalone',
    model_code: node?.videoModelId || fallbackVideoModelOptions[0].id,
    generation_type: generationType,
    resolution: normalizeVideoResolutionValue(node?.videoResolution),
    duration: normalizeVideoDurationValue(node?.videoDuration),
    aspect_ratio: node?.aspectRatio || getVideoDefaultValue(node, 'aspect_ratio', '16:9'),
    image_refs: refs.imageRefs,
    reference_images: refs.imageRefs,
    video_refs: refs.videoRefs,
    reference_videos: refs.videoRefs,
    audio_refs: refs.audioRefs,
    audio_enabled: Boolean(node?.videoAudioEnabled),
    web_search: Boolean(node?.videoWebSearch),
    first_frame: refs.firstFrame || refs.imageRefs[0] || '',
    last_frame: refs.lastFrame || '',
    motion_strength: node?.videoMotionStrength || undefined,
    quality_mode: node?.videoQualityMode || undefined,
    prompt: options.prompt ?? node?.prompt ?? ''
  }
  Object.keys(payload).forEach((key) => {
    if (payload[key] === undefined || payload[key] === '') delete payload[key]
  })
  return payload
}

function isVideoEstimatePending(node) {
  return node?.videoEstimateStatus === 'pending'
}

function getVideoGenerationPoints(node) {
  const exact = Number(node?.videoEstimatePoints)
  if (Number.isFinite(exact) && exact > 0) return exact
  const model = findVideoModelOption(node?.videoModelId || fallbackVideoModelOptions[0].id)
  return Number.isFinite(Number(model?.startPoints)) ? Number(model.startPoints) : null
}

function getVideoGenerationPointsButtonLabel(node) {
  const points = getVideoGenerationPoints(node)
  if (!Number.isFinite(points)) return '--'
  return points
}

function refreshVideoEstimate(node) {
  if (!node?.id) return
  const existing = videoEstimateTimers.get(node.id)
  if (existing) window.clearTimeout(existing)
  updateDirectNode(node.id, { videoEstimateStatus: 'pending' })
  const timer = window.setTimeout(() => estimateDirectVideoNode(node.id), 360)
  videoEstimateTimers.set(node.id, timer)
}

async function estimateDirectVideoNode(nodeId) {
  const node = directNodes.value.find((item) => item.id === nodeId)
  if (!node) return
  videoEstimateTimers.delete(nodeId)
  if (getVideoGenerationBlocker(node)) {
    updateDirectNode(nodeId, {
      videoEstimateStatus: 'idle',
      videoEstimatePoints: null
    })
    return
  }

  try {
    const payload = buildDirectVideoPayload(node)
    delete payload.prompt
    const response = await estimateCreativeVideo(payload)
    if (response?.success === false) throw new Error(response.message || response.error || '视频估算失败')
    const points = Number(response?.estimate_points ?? response?.data?.estimate_points ?? response?.resolved?.sell_price_points)
    updateDirectNode(nodeId, {
      videoEstimatePoints: Number.isFinite(points) ? points : null,
      videoEstimateStatus: Number.isFinite(points) ? 'success' : 'idle'
    })
  } catch (error) {
    updateDirectNode(nodeId, {
      videoEstimateStatus: 'error',
      videoEstimatePoints: null,
      generationMessage: error?.message || node.generationMessage || ''
    })
  }
}

async function runDirectImageNode(node) {
  const prompt = node.prompt.trim()
  if (!prompt) {
    showToast('请先输入图片提示词')
    return
  }
  if (hasPendingReferenceUploads(node.id)) {
    showToast('参考素材还在上传中')
    return
  }
  const blocker = getVideoGenerationBlocker(node)
  if (blocker) {
    showToast(blocker)
    return
  }

  rememberHistory()
  clearImageGenerationTimer(node.id)
  const modelCode = node.imageModelId || fallbackImageModelOptions[0].id
  const resolution = normalizeImageResolutionValue(node.imageResolution)
  const quality = normalizeImageQualityValue(node.imageQuality)
  const aspectRatio = node.aspectRatio || fallbackImageAspectRatioOptions[0]
  updateDirectNode(node.id, {
    imageModelId: modelCode,
    imageResolution: resolution,
    imageQuality: quality,
    aspectRatio,
    generationStatus: 'running',
    generationMessage: '生成中...',
    generationTaskId: '',
    generationRecordId: '',
    generatedImage: null
  })

  try {
    const response = await submitCreativeImage({
      ownership_mode: 'standalone',
      mode: getImageGenerationType(node),
      model_code: modelCode,
      resolution,
      quality: hasImageField(node, 'quality') ? quality : undefined,
      aspect_ratio: aspectRatio,
      reference_images: getDirectImageReferenceUrls(node.id),
      prompt
    })

    if (response?.success === false) {
      throw new Error(response.message || response.error || '图片生成提交失败')
    }

    const result = extractImageGenerationResult(response)
    const recordImage = !result.url && result.recordId ? await fetchRecordImageResult(result.recordId) : null
    const directUrl = result.url || result.thumbnailUrl || recordImage?.url || recordImage?.thumbnailUrl

    if (directUrl) {
      completeDirectImageGeneration(node.id, {
        url: directUrl,
        thumbnailUrl: result.thumbnailUrl || recordImage?.thumbnailUrl || '',
        prompt,
        modelCode,
        resolution,
        quality,
        aspectRatio,
        taskId: result.taskId,
        recordId: result.recordId || recordImage?.recordId
      })
      return
    }

    if (!result.taskId) {
      throw new Error('接口未返回任务 ID')
    }

    updateDirectNode(node.id, {
      generationTaskId: result.taskId,
      generationRecordId: result.recordId || '',
      generationMessage: '生成中...'
    })
    scheduleImageTaskPoll(node.id, result.taskId, result.recordId || '', 0)
    showToast('图片生成任务已提交')
  } catch (error) {
    failDirectImageGeneration(node.id, error?.message || '图片生成提交失败')
  }
}

function scheduleImageTaskPoll(nodeId, taskId, recordId = '', attempt = 0) {
  clearImageGenerationTimer(nodeId)
  const delay = attempt === 0 ? 1200 : 2600
  const timer = window.setTimeout(() => pollImageTask(nodeId, taskId, recordId, attempt), delay)
  imageGenerationTimers.set(nodeId, timer)
}

async function pollImageTask(nodeId, taskId, recordId = '', attempt = 0) {
  const node = directNodes.value.find((item) => item.id === nodeId)
  if (!node || node.generationStatus !== 'running') {
    clearImageGenerationTimer(nodeId)
    return
  }

  try {
    const task = await fetchTask(taskId)
    if (task?.success === false) throw new Error(task.message || task.error || '图片生成失败')

    const result = extractImageGenerationResult(task)
    const nextRecordId = result.recordId || recordId
    const recordImage = !result.url && nextRecordId ? await fetchRecordImageResult(nextRecordId) : null
    const historyImage =
      !result.url && !recordImage?.url && (isFinishedTaskStatus(result.status) || (attempt + 1) % 4 === 0)
        ? await fetchLatestMatchingImageRecord(node.prompt, taskId, nextRecordId)
        : null
    const imageUrl = result.url || result.thumbnailUrl || recordImage?.url || recordImage?.thumbnailUrl || historyImage?.url || historyImage?.thumbnailUrl

    if (imageUrl) {
      completeDirectImageGeneration(nodeId, {
        url: imageUrl,
        thumbnailUrl: result.thumbnailUrl || recordImage?.thumbnailUrl || historyImage?.thumbnailUrl || '',
        prompt: node.prompt,
        modelCode: node.imageModelId,
        resolution: normalizeImageResolutionValue(node.imageResolution),
        quality: normalizeImageQualityValue(node.imageQuality),
        aspectRatio: node.aspectRatio,
        taskId,
        recordId: nextRecordId || recordImage?.recordId || historyImage?.recordId
      })
      return
    }

    if (isFailedTaskStatus(result.status)) {
      throw new Error(result.message || '图片生成失败')
    }

    if (attempt >= 90) {
      updateDirectNode(nodeId, {
        generationStatus: 'idle',
        generationMessage: '生成时间较长，可稍后在历史记录中查看'
      })
      clearImageGenerationTimer(nodeId)
      return
    }

    updateDirectNode(nodeId, {
      generationRecordId: nextRecordId || '',
      generationMessage: '生成中...'
    })
    scheduleImageTaskPoll(nodeId, taskId, nextRecordId, isFinishedTaskStatus(result.status) ? attempt + 2 : attempt + 1)
  } catch (error) {
    failDirectImageGeneration(nodeId, error?.message || '图片生成失败')
  }
}

async function fetchRecordImageResult(recordId) {
  try {
    const record = await fetchCreativeRecord(recordId)
    const result = extractImageGenerationResult(record)
    return result.url ? { ...result, recordId } : null
  } catch {
    return null
  }
}

async function fetchLatestMatchingImageRecord(prompt, taskId = '', recordId = '') {
  try {
    const records = await fetchCreativeRecords({
      record_type: 'image',
      ownership_mode: 'standalone',
      sort_by: 'created_at',
      sort_order: 'desc',
      page: 1,
      page_size: 8
    })
    const items = collectRecordItems(records)
    const matched = items.find((item) => {
      const itemResult = extractImageGenerationResult(item)
      if (!itemResult.url) return false
      if (recordId && itemResult.recordId === recordId) return true
      if (taskId && itemResult.taskId === taskId) return true
      const itemPrompt = String(findFirstValueByKeys(item, ['prompt', 'input_prompt', 'raw_prompt']) || '')
      return prompt && itemPrompt && itemPrompt.trim() === prompt.trim()
    })
    if (!matched) return null

    const result = extractImageGenerationResult(matched)
    return result.url ? result : null
  } catch {
    return null
  }
}

async function runDirectVideoNode(node) {
  const prompt = node.prompt.trim()
  if (!prompt) {
    showToast('请先输入视频提示词')
    return
  }
  if (hasPendingReferenceUploads(node.id)) {
    showToast('参考图还在上传中')
    return
  }

  rememberHistory()
  clearVideoGenerationTimer(node.id)
  const settings = buildDirectVideoPayload(node, { prompt })
  updateDirectNode(node.id, {
    videoModelId: settings.model_code,
    videoGenerationType: settings.generation_type,
    videoResolution: settings.resolution,
    videoDuration: settings.duration,
    aspectRatio: settings.aspect_ratio,
    videoAudioEnabled: Boolean(settings.audio_enabled),
    videoWebSearch: Boolean(settings.web_search),
    generationStatus: 'running',
    generationMessage: '视频生成中...',
    generationTaskId: '',
    generationRecordId: '',
    generatedVideo: null
  })

  try {
    const response = await submitCreativeVideo(settings)
    if (response?.success === false) {
      throw new Error(response.message || response.error || '视频生成提交失败')
    }

    const result = extractVideoGenerationResult(response)
    const recordVideo = !result.url && result.recordId ? await fetchRecordVideoResult(result.recordId) : null
    const directUrl = result.url || recordVideo?.url

    if (directUrl) {
      completeDirectVideoGeneration(node.id, {
        url: directUrl,
        thumbnailUrl: result.thumbnailUrl || recordVideo?.thumbnailUrl || '',
        prompt,
        modelCode: settings.model_code,
        generationType: settings.generation_type,
        resolution: settings.resolution,
        duration: settings.duration,
        aspectRatio: settings.aspect_ratio,
        taskId: result.taskId,
        recordId: result.recordId || recordVideo?.recordId
      })
      return
    }

    if (!result.taskId) {
      throw new Error('接口未返回任务 ID')
    }

    updateDirectNode(node.id, {
      generationTaskId: result.taskId,
      generationRecordId: result.recordId || '',
      generationMessage: '视频生成中...'
    })
    scheduleVideoTaskPoll(node.id, result.taskId, result.recordId || '', 0)
    showToast('视频生成任务已提交')
  } catch (error) {
    failDirectVideoGeneration(node.id, error?.message || '视频生成提交失败')
  }
}

function scheduleVideoTaskPoll(nodeId, taskId, recordId = '', attempt = 0) {
  clearVideoGenerationTimer(nodeId)
  const delay = attempt === 0 ? 1600 : 3200
  const timer = window.setTimeout(() => pollVideoTask(nodeId, taskId, recordId, attempt), delay)
  videoGenerationTimers.set(nodeId, timer)
}

async function pollVideoTask(nodeId, taskId, recordId = '', attempt = 0) {
  const node = directNodes.value.find((item) => item.id === nodeId)
  if (!node || node.generationStatus !== 'running') {
    clearVideoGenerationTimer(nodeId)
    return
  }

  try {
    const task = await fetchTask(taskId)
    if (task?.success === false) throw new Error(task.message || task.error || '视频生成失败')

    const result = extractVideoGenerationResult(task)
    const nextRecordId = result.recordId || recordId
    const recordVideo = !result.url && nextRecordId ? await fetchRecordVideoResult(nextRecordId) : null
    const historyVideo =
      !result.url && !recordVideo?.url && (isFinishedTaskStatus(result.status) || (attempt + 1) % 4 === 0)
        ? await fetchLatestMatchingVideoRecord(node.prompt, taskId, nextRecordId)
        : null
    const videoUrl = result.url || recordVideo?.url || historyVideo?.url

    if (videoUrl) {
      completeDirectVideoGeneration(nodeId, {
        url: videoUrl,
        thumbnailUrl: result.thumbnailUrl || recordVideo?.thumbnailUrl || historyVideo?.thumbnailUrl || '',
        prompt: node.prompt,
        modelCode: node.videoModelId,
        generationType: node.videoGenerationType,
        resolution: normalizeVideoResolutionValue(node.videoResolution),
        duration: normalizeVideoDurationValue(node.videoDuration),
        aspectRatio: node.aspectRatio,
        taskId,
        recordId: nextRecordId || recordVideo?.recordId || historyVideo?.recordId
      })
      return
    }

    if (isFailedTaskStatus(result.status)) {
      throw new Error(result.message || '视频生成失败')
    }

    if (attempt >= 120) {
      updateDirectNode(nodeId, {
        generationStatus: 'idle',
        generationMessage: '视频生成时间较长，可稍后在历史记录中查看'
      })
      clearVideoGenerationTimer(nodeId)
      return
    }

    updateDirectNode(nodeId, {
      generationRecordId: nextRecordId || '',
      generationMessage: getPollingMessage('视频生成中...', attempt + 1)
    })
    scheduleVideoTaskPoll(nodeId, taskId, nextRecordId, isFinishedTaskStatus(result.status) ? attempt + 2 : attempt + 1)
  } catch (error) {
    failDirectVideoGeneration(nodeId, error?.message || '视频生成失败')
  }
}

async function fetchRecordVideoResult(recordId) {
  try {
    const record = await fetchCreativeRecord(recordId)
    const result = extractVideoGenerationResult(record)
    return result.url ? { ...result, recordId } : null
  } catch {
    return null
  }
}

async function fetchLatestMatchingVideoRecord(prompt, taskId = '', recordId = '') {
  try {
    const records = await fetchCreativeRecords({
      record_type: 'video',
      ownership_mode: 'standalone',
      sort_by: 'created_at',
      sort_order: 'desc',
      page: 1,
      page_size: 8
    })
    const items = collectRecordItems(records)
    const matched = items.find((item) => {
      const itemResult = extractVideoGenerationResult(item)
      if (!itemResult.url) return false
      if (recordId && itemResult.recordId === recordId) return true
      if (taskId && itemResult.taskId === taskId) return true
      const itemPrompt = String(findFirstValueByKeys(item, ['prompt', 'input_prompt', 'raw_prompt']) || '')
      return prompt && itemPrompt && itemPrompt.trim() === prompt.trim()
    })
    if (!matched) return null

    const result = extractVideoGenerationResult(matched)
    return result.url ? result : null
  } catch {
    return null
  }
}

function getFallbackAudioAbility(abilityType) {
  return fallbackAudioAbilityOptions.find((ability) => ability.id === abilityType) || fallbackAudioAbilityOptions[0]
}

function findAudioAbilityOption(abilityType) {
  return audioAbilityOptions.value.find((ability) => ability.id === abilityType) || getFallbackAudioAbility(abilityType)
}

function getAudioTierOptions(node) {
  const ability = findAudioAbilityOption(node?.audioAbilityType || fallbackAudioAbilityOptions[0].id)
  return (ability?.tiers || fallbackAudioAbilityOptions[0].tiers).map((tier) => ({
    value: tier.id,
    label: tier.label || `Minimax-${tier.modelCode || tier.id}`,
    modelCode: tier.modelCode,
    pointsPer10k: tier.pointsPer10k
  }))
}

function getAudioTierSelectValue(node) {
  const tiers = getAudioTierOptions(node)
  return tiers.find((tier) => tier.value === node?.audioTierCode)?.value || tiers[0]?.value || 'hd'
}

function getAudioTierOption(node) {
  const tiers = getAudioTierOptions(node)
  return tiers.find((tier) => tier.value === getAudioTierSelectValue(node)) || tiers[0] || fallbackAudioAbilityOptions[0].tiers[0]
}

function getAudioModelLabel(node) {
  const tier = getAudioTierOption(node)
  return tier?.label || `Minimax-${node?.audioModelCode || 'speech-2.8-hd'}`
}

function setAudioTierFromSelect(node, event) {
  const value = event?.target?.value || 'hd'
  const tier = getAudioTierOptions(node).find((item) => item.value === value) || getAudioTierOptions(node)[0]
  updateDirectNode(node.id, {
    audioTierCode: tier?.value || value,
    audioModelCode: tier?.modelCode || node.audioModelCode || 'speech-2.8-hd',
    audioEstimateStatus: 'idle',
    audioEstimatePoints: null
  })
  refreshAudioEstimate({ ...node, audioTierCode: tier?.value || value, audioModelCode: tier?.modelCode || node.audioModelCode })
}

function syncAudioNodeSettings(node) {
  const ability = findAudioAbilityOption(node?.audioAbilityType || fallbackAudioAbilityOptions[0].id)
  const tierCode = ability?.tiers?.some((tier) => tier.id === node.audioTierCode) ? node.audioTierCode : ability?.defaultTier || ability?.tiers?.[0]?.id || 'hd'
  const tier = (ability?.tiers || []).find((item) => item.id === tierCode) || ability?.tiers?.[0]
  updateDirectNode(node.id, {
    audioTierCode: tierCode,
    audioModelCode: tier?.modelCode || node.audioModelCode || 'speech-2.8-hd',
    audioEstimateStatus: 'idle',
    audioEstimatePoints: null
  })
  refreshAudioEstimate({ ...node, audioTierCode: tierCode, audioModelCode: tier?.modelCode || node.audioModelCode })
}

function syncAudioVoiceSource(node) {
  const voice = audioVoiceOptions.value.find((item) => item.voiceId === node.audioVoiceId)
  updateDirectNode(node.id, { audioVoiceSourceType: voice?.sourceType || 'system' })
}

function getAudioVoiceLabel(node) {
  const voice = audioVoiceOptions.value.find((item) => item.voiceId === node?.audioVoiceId)
  return voice?.label || node?.audioVoiceId || '选择音色'
}

function getAudioVoiceLanguageLabel(node) {
  const voice = audioVoiceOptions.value.find((item) => item.voiceId === node?.audioVoiceId)
  return voice?.categoryLabel || '中文(普通话)'
}

function getActiveAudioVoiceId() {
  const node = directNodes.value.find((item) => item.id === audioVoicePicker.nodeId)
  return node?.audioVoiceId || ''
}

function isAudioVoiceMine(voice) {
  return String(voice?.sourceType || '').toLowerCase() !== 'system'
}

function isAudioVoiceFavorite(voice) {
  const voiceId = String(voice?.voiceId || '').trim()
  return Boolean(voiceId && (audioFavoriteVoiceIds.value.has(voiceId) || voice?.isFavorite))
}

function loadAudioVoiceFavorites() {
  if (typeof window === 'undefined') return
  try {
    const raw = window.localStorage.getItem(AUDIO_VOICE_FAVORITES_STORAGE_KEY)
    const ids = JSON.parse(raw || '[]')
    audioFavoriteVoiceIds.value = new Set(Array.isArray(ids) ? ids.map((item) => String(item).trim()).filter(Boolean) : [])
  } catch {
    audioFavoriteVoiceIds.value = new Set()
  }
}

function saveAudioVoiceFavorites() {
  if (typeof window === 'undefined') return
  window.localStorage.setItem(AUDIO_VOICE_FAVORITES_STORAGE_KEY, JSON.stringify([...audioFavoriteVoiceIds.value]))
}

function toggleAudioVoiceFavorite(voice) {
  const voiceId = String(voice?.voiceId || '').trim()
  if (!voiceId) return
  const next = new Set(audioFavoriteVoiceIds.value)
  if (next.has(voiceId)) {
    next.delete(voiceId)
  } else {
    next.add(voiceId)
  }
  audioFavoriteVoiceIds.value = next
  saveAudioVoiceFavorites()
}

function openAudioVoicePicker(node) {
  if (!audioVoiceOptions.value.length) {
    loadAudioVoiceAssets()
  }
  audioVoicePicker.visible = true
  audioVoicePicker.nodeId = node.id
  updateDirectNode(node.id, { audioSettingsOpen: true })
  audioVoicePicker.tab = 'library'
  audioVoicePicker.query = ''
}

function closeAudioVoicePicker() {
  audioVoicePicker.visible = false
  audioVoicePicker.nodeId = ''
  audioVoicePicker.query = ''
}

function selectAudioVoice(voice) {
  if (!audioVoicePicker.nodeId || !voice?.voiceId) return
  updateDirectNode(audioVoicePicker.nodeId, {
    audioVoiceId: voice.voiceId,
    audioVoiceSourceType: voice.sourceType || 'system'
  })
  const node = directNodes.value.find((item) => item.id === audioVoicePicker.nodeId)
  if (node) refreshAudioEstimate({ ...node, audioVoiceId: voice.voiceId, audioVoiceSourceType: voice.sourceType || 'system' })
  closeAudioVoicePicker()
  showToast(`已选择${voice.label || '音色'}`)
}

function toggleAudioSettingsPanel(node) {
  updateDirectNode(node.id, { audioSettingsOpen: !node.audioSettingsOpen })
}

function resetAudioNodeSettings(node) {
  updateDirectNode(node.id, {
    audioSpeed: 1,
    audioPitch: 0,
    audioVolume: 1,
    audioEmotion: '',
    audioLanguageBoost: 'none',
    audioFormat: 'mp3',
    audioSampleRate: 32000,
    audioBitrate: 128000,
    audioChannelCount: 1
  })
}

function isAudioEmotionSupported(node) {
  return (node?.audioAbilityType || fallbackAudioAbilityOptions[0].id) === 'realtime_dubbing'
}

function isAudioLanguageBoostSupported(node) {
  return (node?.audioAbilityType || fallbackAudioAbilityOptions[0].id) === 'long_narration'
}

function formatAudioNumber(value, digits = 1) {
  const number = Number(value)
  if (!Number.isFinite(number)) return digits === 0 ? '0' : '1.0'
  return digits === 0 ? String(Math.round(number)) : number.toFixed(digits)
}

function toggleAudioLanguageBoost(node) {
  const next = node.audioLanguageBoost === 'auto' ? 'none' : 'auto'
  updateDirectNode(node.id, { audioLanguageBoost: next })
  showToast(next === 'auto' ? '已开启语言增强' : '已关闭语言增强')
}

function insertAudioPromptToken(nodeId, value, label, tokenKind = 'tag', event = null) {
  closeAudioTokenMenu(event)
  const token = {
    type: 'audio_token',
    id: `audio-token-${Date.now()}-${Math.round(Math.random() * 10000)}`,
    value,
    label,
    tokenKind
  }
  const editor = directPromptEditorElements.get(nodeId)
  rememberHistory()
  if (!editor) {
    const node = directNodes.value.find((item) => item.id === nodeId)
    const segments = [...normalizePromptSegments(node?.promptSegments, node), token]
    updateDirectNode(nodeId, {
      promptSegments: segments,
      prompt: getPromptTextFromSegments(segments)
    })
    scheduleCanvasSave(180)
    return
  }
  focusDirectPromptEditor(nodeId)
  insertAudioTokenAtSelection(editor, token)
  handleDirectPromptInput(nodeId, { currentTarget: editor })
  scheduleCanvasSave(180)
}

function closeAudioTokenMenu(event = null) {
  const details = event?.currentTarget?.closest?.('details')
  if (details) details.open = false
}

function insertAudioTokenAtSelection(editor, tokenData) {
  const selection = window.getSelection?.()
  if (!selection || selection.rangeCount === 0) return
  const range = selection.getRangeAt(0)
  range.deleteContents()
  const token = createPromptAudioToken(tokenData)
  range.insertNode(token)
  const afterRange = document.createRange()
  afterRange.setStartAfter(token)
  afterRange.collapse(true)
  selection.removeAllRanges()
  selection.addRange(afterRange)
}

function calculateAudioBillingCharacters(text) {
  return Array.from(String(text || '')).reduce((total, char) => {
    return total + (/[\u4e00-\u9fff]/.test(char) ? 2 : 1)
  }, 0)
}

function getAudioCharacterLabel(node) {
  return `${calculateAudioBillingCharacters(node?.prompt || '')}/50000`
}

function estimateAudioPointsLocally(node) {
  const chars = Math.max(1, calculateAudioBillingCharacters(node?.prompt || ''))
  const tier = getAudioTierOption(node)
  const pointsPer10k = Number(tier?.pointsPer10k || (String(tier?.modelCode || '').includes('turbo') ? 30 : 53))
  return Math.max(1, Math.ceil(chars / (10000 / pointsPer10k)))
}

function isAudioEstimatePending(node) {
  return node?.audioEstimateStatus === 'pending'
}

function getAudioGenerationPoints(node) {
  const exact = Number(node?.audioEstimatePoints)
  if (Number.isFinite(exact) && exact > 0) return exact
  return null
}

function getAudioGenerationPointsButtonLabel(node) {
  if (node?.audioEstimateStatus === 'pending') return '估算中'
  const points = getAudioGenerationPoints(node)
  return Number.isFinite(points) ? points : '--'
}

function getAudioGenerationBlocker(node) {
  const characters = calculateAudioBillingCharacters(node?.prompt || '')
  if (!String(node?.audioVoiceId || '').trim()) return '请先在设置里选择音色'
  if (characters > 50000) return '配音文本不能超过 50000 字符'
  return ''
}

function buildDirectAudioPayload(node, patch = {}) {
  const tier = getAudioTierOption(node)
  const voice = audioVoiceOptions.value.find((item) => item.voiceId === node?.audioVoiceId)
  const payload = {
    ownership_mode: 'standalone',
    ability_type: node?.audioAbilityType || fallbackAudioAbilityOptions[0].id,
    tier_code: node?.audioTierCode || tier?.value || tier?.id || 'hd',
    model_code: node?.audioModelCode || tier?.modelCode || 'speech-2.8-hd',
    voice_id: node?.audioVoiceId || voice?.voiceId || '',
    voice_source_type: node?.audioVoiceSourceType || voice?.sourceType || 'system',
    script_text: patch.prompt ?? node?.prompt ?? '',
    emotion: isAudioEmotionSupported(node) ? node?.audioEmotion || undefined : undefined,
    speed: node?.audioSpeed ?? undefined,
    volume: node?.audioVolume ?? undefined,
    pitch: node?.audioPitch ?? undefined,
    audio_format: node?.audioFormat || 'mp3',
    sample_rate: Number(node?.audioSampleRate || 32000),
    bitrate: Number(node?.audioBitrate || 128000),
    channel_count: Number(node?.audioChannelCount || 1),
    language_boost: isAudioLanguageBoostSupported(node) ? node?.audioLanguageBoost || undefined : undefined,
    submit_mode: 'generate'
  }
  Object.keys(payload).forEach((key) => {
    if (payload[key] === undefined || payload[key] === '') delete payload[key]
  })
  return payload
}

function refreshAudioEstimate(node) {
  if (!node?.id) return
  const existing = audioEstimateTimers.get(node.id)
  if (existing) window.clearTimeout(existing)
  if (!String(node.prompt || '').trim() || getAudioGenerationBlocker(node)) {
    updateDirectNode(node.id, {
      audioEstimateStatus: 'idle',
      audioEstimatePoints: null
    })
    return
  }
  updateDirectNode(node.id, { audioEstimateStatus: 'pending', audioEstimatePoints: null })
  const timer = window.setTimeout(() => estimateDirectAudioNode(node.id), 360)
  audioEstimateTimers.set(node.id, timer)
}

function extractAudioEstimatePoints(response) {
  const directCandidates = [
    response?.estimate_points,
    response?.estimatePoints,
    response?.data?.estimate_points,
    response?.data?.estimatePoints,
    response?.data?.price?.sell_price_points,
    response?.data?.price?.sellPricePoints,
    response?.price?.sell_price_points,
    response?.price?.sellPricePoints,
    response?.resolved?.sell_price_points,
    response?.resolved?.sellPricePoints
  ]
  for (const candidate of directCandidates) {
    const points = Number(candidate)
    if (Number.isFinite(points) && points > 0) return points
  }

  const breakdown = Array.isArray(response?.breakdown)
    ? response.breakdown
    : Array.isArray(response?.data?.breakdown)
      ? response.data.breakdown
      : []
  const total = breakdown.reduce((sum, item) => {
    const points = Number(item?.sell_price_points ?? item?.sellPricePoints ?? item?.points)
    return Number.isFinite(points) && points > 0 ? sum + points : sum
  }, 0)
  return total > 0 ? total : null
}

async function estimateDirectAudioNode(nodeId) {
  const node = directNodes.value.find((item) => item.id === nodeId)
  if (!node) return
  audioEstimateTimers.delete(nodeId)
  if (getAudioGenerationBlocker(node)) {
    updateDirectNode(nodeId, {
      audioEstimateStatus: 'idle',
      audioEstimatePoints: null
    })
    return
  }
  try {
    const response = await estimateCreativeAudio(buildDirectAudioPayload(node))
    if (response?.success === false) throw new Error(response.message || response.error || '音频估算失败')
    const points = extractAudioEstimatePoints(response)
    if (!Number.isFinite(points)) throw new Error('音频估算结果缺少灵感值')
    updateDirectNode(nodeId, {
      audioEstimatePoints: points,
      audioEstimateStatus: 'success'
    })
  } catch (error) {
    updateDirectNode(nodeId, {
      audioEstimateStatus: 'error',
      audioEstimatePoints: null,
      generationMessage: error?.message || node.generationMessage || ''
    })
  }
}

async function runDirectAudioNode(node) {
  const prompt = node.prompt.trim()
  if (!prompt) {
    showToast('请先输入配音文本')
    return
  }
  const blocker = getAudioGenerationBlocker(node)
  if (blocker) {
    showToast(blocker)
    return
  }

  rememberHistory()
  clearAudioGenerationTimer(node.id)
  const settings = buildDirectAudioPayload(node, { prompt })
  updateDirectNode(node.id, {
    audioAbilityType: settings.ability_type,
    audioTierCode: settings.tier_code,
    audioModelCode: settings.model_code,
    generationStatus: 'running',
    generationMessage: '音频生成中...',
    generationTaskId: '',
    generationRecordId: '',
    generatedAudio: null
  })

  try {
    const response = await submitCreativeAudio(settings)
    if (response?.success === false) {
      throw new Error(response.message || response.error || '音频生成提交失败')
    }

    const result = extractAudioGenerationResult(response)
    const recordAudio = !result.url && result.recordId ? await fetchRecordAudioResult(result.recordId) : null
    const directUrl = result.url || recordAudio?.url

    if (directUrl) {
      completeDirectAudioGeneration(node.id, {
        url: directUrl,
        prompt,
        modelCode: settings.model_code,
        abilityType: settings.ability_type,
        tierCode: settings.tier_code,
        taskId: result.taskId,
        recordId: result.recordId || recordAudio?.recordId,
        title: '配音结果'
      })
      return
    }

    if (!result.taskId) {
      throw new Error('接口未返回任务 ID')
    }

    updateDirectNode(node.id, {
      generationTaskId: result.taskId,
      generationRecordId: result.recordId || '',
      generationMessage: '音频生成中...'
    })
    scheduleAudioTaskPoll(node.id, result.taskId, result.recordId || '', 0)
    showToast('音频生成任务已提交')
  } catch (error) {
    failDirectAudioGeneration(node.id, error?.message || '音频生成提交失败')
  }
}

function scheduleAudioTaskPoll(nodeId, taskId, recordId = '', attempt = 0) {
  clearAudioGenerationTimer(nodeId)
  const delay = attempt === 0 ? 1200 : 2600
  const timer = window.setTimeout(() => pollAudioTask(nodeId, taskId, recordId, attempt), delay)
  audioGenerationTimers.set(nodeId, timer)
}

async function pollAudioTask(nodeId, taskId, recordId = '', attempt = 0) {
  const node = directNodes.value.find((item) => item.id === nodeId)
  if (!node || node.generationStatus !== 'running') {
    clearAudioGenerationTimer(nodeId)
    return
  }

  try {
    const task = await fetchTask(taskId)
    if (task?.success === false) throw new Error(task.message || task.error || '音频生成失败')

    const result = extractAudioGenerationResult(task)
    const nextRecordId = result.recordId || recordId
    const recordAudio = !result.url && nextRecordId ? await fetchRecordAudioResult(nextRecordId) : null
    const historyAudio =
      !result.url && !recordAudio?.url && (isFinishedTaskStatus(result.status) || (attempt + 1) % 4 === 0)
        ? await fetchLatestMatchingAudioRecord(node.prompt, taskId, nextRecordId)
        : null
    const audioUrl = result.url || recordAudio?.url || historyAudio?.url

    if (audioUrl) {
      completeDirectAudioGeneration(nodeId, {
        url: audioUrl,
        prompt: node.prompt,
        modelCode: node.audioModelCode,
        abilityType: node.audioAbilityType,
        tierCode: node.audioTierCode,
        taskId,
        recordId: nextRecordId || recordAudio?.recordId || historyAudio?.recordId,
        title: '配音结果'
      })
      return
    }

    if (isFailedTaskStatus(result.status)) {
      throw new Error(result.message || '音频生成失败')
    }

    if (attempt >= 90) {
      updateDirectNode(nodeId, {
        generationStatus: 'idle',
        generationMessage: '音频生成时间较长，可稍后在历史记录中查看'
      })
      clearAudioGenerationTimer(nodeId)
      return
    }

    updateDirectNode(nodeId, {
      generationRecordId: nextRecordId || '',
      generationMessage: getPollingMessage('音频生成中...', attempt + 1)
    })
    scheduleAudioTaskPoll(nodeId, taskId, nextRecordId, isFinishedTaskStatus(result.status) ? attempt + 2 : attempt + 1)
  } catch (error) {
    failDirectAudioGeneration(nodeId, error?.message || '音频生成失败')
  }
}

async function fetchRecordAudioResult(recordId) {
  try {
    const record = await fetchCreativeRecord(recordId)
    const result = extractAudioGenerationResult(record)
    return result.url ? { ...result, recordId } : null
  } catch {
    return null
  }
}

async function fetchLatestMatchingAudioRecord(prompt, taskId = '', recordId = '') {
  try {
    const records = await fetchCreativeRecords({
      record_type: 'audio',
      ownership_mode: 'standalone',
      sort_by: 'created_at',
      sort_order: 'desc',
      page: 1,
      page_size: 8
    })
    const items = collectRecordItems(records)
    const matched = items.find((item) => {
      const itemResult = extractAudioGenerationResult(item)
      if (!itemResult.url) return false
      if (recordId && itemResult.recordId === recordId) return true
      if (taskId && itemResult.taskId === taskId) return true
      const itemPrompt = String(findFirstValueByKeys(item, ['prompt', 'input_prompt', 'raw_prompt', 'script_text']) || '')
      return prompt && itemPrompt && itemPrompt.trim() === prompt.trim()
    })
    if (!matched) return null

    const result = extractAudioGenerationResult(matched)
    return result.url ? result : null
  } catch {
    return null
  }
}

function collectRecordItems(payload) {
  if (Array.isArray(payload)) return payload
  const candidates = [
    payload?.records,
    payload?.items,
    payload?.list,
    payload?.data?.records,
    payload?.data?.items,
    payload?.data?.list,
    payload?.result?.records,
    payload?.result?.items
  ]
  return candidates.find(Array.isArray) || []
}

function getPollingMessage(message, attempts) {
  if (attempts >= 24) return '上游仍在排队，已为你继续查询结果'
  if (attempts >= 10) return '模型生成时间较长，正在同步任务记录'
  return message || `生成中，已轮询 ${attempts} 次`
}

function completeDirectImageGeneration(nodeId, image) {
  clearImageGenerationTimer(nodeId)
  const imageUrl = normalizeDisplayImageSrc(image.url)
  const thumbnailUrl = normalizeDisplayImageSrc(image.thumbnailUrl)
  updateDirectNode(nodeId, {
    generationStatus: 'success',
    generationMessage: '图片生成完成',
    generationTaskId: image.taskId || '',
    generationRecordId: image.recordId || '',
    generatedImage: {
      ...image,
      url: imageUrl || thumbnailUrl,
      thumbnailUrl
    }
  })
  showToast('图片生成完成')
  persistCriticalCanvasChange(120)
}

function completeDirectVideoGeneration(nodeId, video) {
  clearVideoGenerationTimer(nodeId)
  updateDirectNode(nodeId, {
    generationStatus: 'success',
    generationMessage: '视频生成完成',
    generationTaskId: video.taskId || '',
    generationRecordId: video.recordId || '',
    generatedVideo: {
      ...video,
      url: normalizeDisplayVideoSrc(video.url),
      thumbnailUrl: normalizeDisplayImageSrc(video.thumbnailUrl),
      isPlayable: false,
      loadError: false,
      loadErrorMessage: ''
    }
  })
  showToast('视频生成完成')
  persistCriticalCanvasChange(120)
}

function completeDirectAudioGeneration(nodeId, audio) {
  clearAudioGenerationTimer(nodeId)
  updateDirectNode(nodeId, {
    generationStatus: 'success',
    generationMessage: '音频生成完成',
    generationTaskId: audio.taskId || '',
    generationRecordId: audio.recordId || '',
    generatedAudio: {
      ...audio,
      url: normalizeDisplayAudioSrc(audio.url)
    }
  })
  showToast('音频生成完成')
  persistCriticalCanvasChange(120)
}

function failDirectImageGeneration(nodeId, message) {
  clearImageGenerationTimer(nodeId)
  updateDirectNode(nodeId, {
    generationStatus: 'error',
    generationMessage: message
  })
  showToast(message)
}

function failDirectVideoGeneration(nodeId, message) {
  clearVideoGenerationTimer(nodeId)
  updateDirectNode(nodeId, {
    generationStatus: 'error',
    generationMessage: message
  })
  showToast(message)
}

function failDirectAudioGeneration(nodeId, message) {
  clearAudioGenerationTimer(nodeId)
  updateDirectNode(nodeId, {
    generationStatus: 'error',
    generationMessage: message
  })
  showToast(message)
}

function updateDirectNode(nodeId, patch) {
  directNodes.value = directNodes.value.map((item) => (item.id === nodeId ? { ...item, ...patch } : item))
}

function clearImageGenerationTimer(nodeId) {
  const timer = imageGenerationTimers.get(nodeId)
  if (timer) window.clearTimeout(timer)
  imageGenerationTimers.delete(nodeId)
}

function clearImageGenerationTimers() {
  imageGenerationTimers.forEach((timer) => window.clearTimeout(timer))
  imageGenerationTimers.clear()
}

function clearVideoGenerationTimer(nodeId) {
  const timer = videoGenerationTimers.get(nodeId)
  if (timer) window.clearTimeout(timer)
  videoGenerationTimers.delete(nodeId)
}

function clearVideoGenerationTimers() {
  videoGenerationTimers.forEach((timer) => window.clearTimeout(timer))
  videoGenerationTimers.clear()
}

function clearAudioGenerationTimer(nodeId) {
  const timer = audioGenerationTimers.get(nodeId)
  if (timer) window.clearTimeout(timer)
  audioGenerationTimers.delete(nodeId)
}

function clearAudioGenerationTimers() {
  audioGenerationTimers.forEach((timer) => window.clearTimeout(timer))
  audioGenerationTimers.clear()
}

function clearVideoEstimateTimers() {
  videoEstimateTimers.forEach((timer) => window.clearTimeout(timer))
  videoEstimateTimers.clear()
}

function clearAudioEstimateTimers() {
  audioEstimateTimers.forEach((timer) => window.clearTimeout(timer))
  audioEstimateTimers.clear()
}

function getDirectImageReferenceUrls(nodeId) {
  return getDirectImageReferenceItems(nodeId)
    .map((reference) => reference.url || '')
    .filter((url) => /^https?:\/\//.test(url))
}

function extractImageGenerationResult(payload) {
  const output = findFirstImageOutput(payload)
  return {
    taskId: findFirstValueByKeys(payload, ['taskId', 'task_id', 'id']),
    recordId: findFirstExternalRecordId(payload),
    status: String(findFirstValueByKeys(payload, ['status', 'state', 'task_status']) || '').toLowerCase(),
    message: findFirstValueByKeys(payload, ['message', 'error', 'detail']),
    url: output.url,
    thumbnailUrl: output.thumbnailUrl
  }
}

function extractVideoGenerationResult(payload) {
  return {
    taskId: findFirstValueByKeys(payload, ['taskId', 'task_id', 'id']),
    recordId: findFirstExternalRecordId(payload),
    status: String(findFirstValueByKeys(payload, ['status', 'state', 'task_status']) || '').toLowerCase(),
    message: findFirstValueByKeys(payload, ['message', 'error', 'detail']),
    url: findFirstVideoOutputUrl(payload),
    thumbnailUrl: findFirstImageUrl(payload, { thumbnail: true }) || findFirstImageUrl(payload, { thumbnail: false })
  }
}

function extractAudioGenerationResult(payload) {
  return {
    taskId: findFirstValueByKeys(payload, ['taskId', 'task_id', 'id']),
    recordId: findFirstExternalRecordId(payload),
    status: String(findFirstValueByKeys(payload, ['status', 'state', 'task_status']) || '').toLowerCase(),
    message: findFirstValueByKeys(payload, ['message', 'error', 'detail']),
    url: findFirstAudioOutputUrl(payload)
  }
}

function findFirstExternalRecordId(value, depth = 0) {
  if (!value || depth > 7) return ''
  if (Array.isArray(value)) {
    for (const item of value) {
      const found = findFirstExternalRecordId(item, depth + 1)
      if (found) return found
    }
    return ''
  }
  if (typeof value !== 'object') return ''

  const keys = ['recordId', 'record_id', 'generation_record_id']
  for (const key of keys) {
    const candidate = value[key]
    if (typeof candidate === 'string' || typeof candidate === 'number') {
      const normalized = String(candidate).trim()
      if (normalized && !/^\d+$/.test(normalized)) return normalized
    }
  }
  for (const item of Object.values(value)) {
    const found = findFirstExternalRecordId(item, depth + 1)
    if (found) return found
  }
  return ''
}

function findFirstValueByKeys(value, keys, depth = 0) {
  if (!value || depth > 7) return ''
  if (Array.isArray(value)) {
    for (const item of value) {
      const found = findFirstValueByKeys(item, keys, depth + 1)
      if (found) return found
    }
    return ''
  }
  if (typeof value !== 'object') return ''

  for (const key of keys) {
    const candidate = value[key]
    if (typeof candidate === 'string' || typeof candidate === 'number') return String(candidate)
  }
  for (const item of Object.values(value)) {
    const found = findFirstValueByKeys(item, keys, depth + 1)
    if (found) return found
  }
  return ''
}

function findFirstImageOutput(value) {
  return {
    url: findFirstImageUrl(value, { thumbnail: false }),
    thumbnailUrl: findFirstImageUrl(value, { thumbnail: true })
  }
}

function findFirstImageUrl(value, options = {}, depth = 0) {
  if (!value || depth > 7) return ''
  if (typeof value === 'string') return isLikelyImageUrl(value) ? normalizeDisplayImageSrc(value) : ''
  if (Array.isArray(value)) {
    for (const item of value) {
      const found = findFirstImageUrl(item, options, depth + 1)
      if (found) return found
    }
    return ''
  }
  if (typeof value !== 'object') return ''

  const priorityKeys = options.thumbnail
    ? ['thumbnail_url', 'thumbnailUrl', 'cover_url', 'coverUrl']
    : [
        'preview_url',
        'previewUrl',
        'image_url',
        'imageUrl',
        'output_url',
        'outputUrl',
        'result_url',
        'resultUrl',
        'media_url',
        'mediaUrl',
        'file_url',
        'fileUrl',
        'url'
      ]
  for (const key of priorityKeys) {
    const candidate = value[key]
    if (typeof candidate === 'string' && isLikelyImageUrl(candidate)) return normalizeDisplayImageSrc(candidate)
  }

  const skippedKeys = new Set([
    'params',
    'internal_request',
    'request_payload',
    'reference_images',
    'referenceImages',
    'image_refs',
    'imageRefs',
    'image_ref_entries',
    'imageRefEntries',
    'first_frame',
    'firstFrame',
    'last_frame',
    'lastFrame',
    'input_image',
    'inputImage'
  ])
  for (const [key, item] of Object.entries(value)) {
    if (skippedKeys.has(key)) continue
    const found = findFirstImageUrl(item, options, depth + 1)
    if (found) return found
  }
  return ''
}

function isLikelyImageUrl(value) {
  const source = String(value || '').trim()
  return /^(data:image\/|blob:)/i.test(source) || /^\/.+(\.png|\.jpe?g|\.webp|\.gif|image|oss|cos|cdn)/i.test(source) || /^https?:\/\/.+(\.png|\.jpe?g|\.webp|\.gif|image|oss|cos|cdn)/i.test(source)
}

function findFirstVideoOutputUrl(value, depth = 0) {
  if (!value || depth > 7) return ''
  if (typeof value === 'string') return isLikelyVideoUrl(value) ? normalizeDisplayVideoSrc(value) : ''
  if (Array.isArray(value)) {
    for (const item of value) {
      const found = findFirstVideoOutputUrl(item, depth + 1)
      if (found) return found
    }
    return ''
  }
  if (typeof value !== 'object') return ''

  const priorityKeys = [
    'preview_url',
    'previewUrl',
    'video_url',
    'videoUrl',
    'play_url',
    'playUrl',
    'output_url',
    'outputUrl',
    'result_url',
    'resultUrl',
    'media_url',
    'mediaUrl',
    'file_url',
    'fileUrl',
    'url'
  ]
  for (const key of priorityKeys) {
    const candidate = value[key]
    if (typeof candidate === 'string' && isPotentialVideoOutputUrl(candidate)) return normalizeDisplayVideoSrc(candidate)
  }
  const skippedKeys = new Set([
    'thumbnail_url',
    'thumbnailUrl',
    'cover_url',
    'coverUrl',
    'poster_url',
    'posterUrl',
    'image_url',
    'imageUrl',
    'first_frame',
    'firstFrame',
    'last_frame',
    'lastFrame',
    'reference_images',
    'referenceImages',
    'image_refs',
    'imageRefs'
  ])
  for (const [key, item] of Object.entries(value)) {
    if (skippedKeys.has(key)) continue
    const found = findFirstVideoOutputUrl(item, depth + 1)
    if (found) return found
  }
  return ''
}

function findFirstAudioOutputUrl(value, depth = 0) {
  if (!value || depth > 7) return ''
  if (typeof value === 'string') return isLikelyAudioUrl(value) ? normalizeDisplayAudioSrc(value) : ''
  if (Array.isArray(value)) {
    for (const item of value) {
      const found = findFirstAudioOutputUrl(item, depth + 1)
      if (found) return found
    }
    return ''
  }
  if (typeof value !== 'object') return ''

  const priorityKeys = [
    'preview_url',
    'previewUrl',
    'audio_url',
    'audioUrl',
    'output_url',
    'outputUrl',
    'result_url',
    'resultUrl',
    'media_url',
    'mediaUrl',
    'file_url',
    'fileUrl',
    'url'
  ]
  for (const key of priorityKeys) {
    const candidate = value[key]
    if (typeof candidate === 'string' && isPotentialAudioOutputUrl(candidate, value)) return normalizeDisplayAudioSrc(candidate)
  }
  const skippedKeys = new Set([
    'params',
    'internal_request',
    'request_payload',
    'thumbnail_url',
    'thumbnailUrl',
    'cover_url',
    'coverUrl',
    'image_url',
    'imageUrl',
    'video_url',
    'videoUrl',
    'reference_images',
    'referenceImages',
    'image_refs',
    'imageRefs',
    'video_refs',
    'videoRefs'
  ])
  for (const [key, item] of Object.entries(value)) {
    if (skippedKeys.has(key)) continue
    const found = findFirstAudioOutputUrl(item, depth + 1)
    if (found) return found
  }
  return ''
}

function isLikelyVideoUrl(value) {
  const source = String(value || '').trim()
  if (!source || /\.(png|jpe?g|webp|gif|avif)(\?|$)/i.test(source)) return false
  return /^(blob:)/i.test(source) || /^\/.+(\.mp4|\.webm|\.mov|\.m3u8)(\?|$)/i.test(source) || /^https?:\/\/.+(\.mp4|\.webm|\.mov|\.m3u8)(\?|$)/i.test(source)
}

function isPotentialVideoOutputUrl(value) {
  const source = String(value || '').trim()
  if (!source || /\.(png|jpe?g|webp|gif|avif)(\?|$)/i.test(source)) return false
  return /^(https?:\/\/|\/|blob:)/i.test(source)
}

function isLikelyAudioUrl(value) {
  const source = String(value || '').trim()
  if (!source || /\.(png|jpe?g|webp|gif|avif|mp4|webm|mov|m3u8)(\?|$)/i.test(source)) return false
  return /^(data:audio\/|blob:)/i.test(source) || /^\/.+(\.mp3|\.wav|\.m4a|\.ogg|audio|oss|cos|cdn)/i.test(source) || /^https?:\/\/.+(\.mp3|\.wav|\.m4a|\.ogg|audio|oss|cos|cdn)/i.test(source)
}

function isPotentialAudioOutputUrl(value, owner = null) {
  const source = String(value || '').trim()
  if (!source || /\.(png|jpe?g|webp|gif|avif|mp4|webm|mov|m3u8)(\?|$)/i.test(source)) return false
  if (isLikelyAudioUrl(source)) return true
  const recordType = String(owner?.record_type || owner?.recordType || '').toLowerCase()
  return recordType === 'audio' && /^(https?:\/\/|\/|blob:)/i.test(source)
}

function isFinishedTaskStatus(status) {
  return ['success', 'succeeded', 'completed', 'complete', 'done', 'finished'].includes(status)
}

function isFailedTaskStatus(status) {
  return ['failed', 'failure', 'error', 'cancelled', 'canceled'].includes(status)
}

function createNode(type, position, patch = {}, options = {}) {
  canvasActivated.value = true
  rememberHistory()
  const node = buildCanvasNode(type, position, patch)
  const nextNodes = options.replaceWhenEmpty && nodes.value.length === 0 ? [node] : [...nodes.value, node]
  nodes.value = nextNodes.map((item) => ({ ...item, selected: item.id === node.id }))
  canvasStore.setSelection([node.id])
  showToast('\u5df2\u6dfb\u52a0\u8282\u70b9')
  return node
}

function createDirectNode(type, screen, patch = {}) {
  const meta = nodeMeta[type] || nodeMeta.prompt_note
  const count = directNodes.value.filter((node) => node.type === type).length + 1
  const local = getFlowNodePosition(screen, type)
  return createDirectNodeAtFlow(type, local, patch, count)
}

function createDirectNodeAtFlow(type, flowPosition, patch = {}, explicitCount = 0) {
  const meta = nodeMeta[type] || nodeMeta.prompt_note
  const count = explicitCount || directNodes.value.filter((node) => node.type === type).length + 1
  const node = {
    id: `direct-${type}-${Date.now()}-${Math.round(Math.random() * 10000)}`,
    clientId: patch.clientId || `direct-client-${Date.now()}-${Math.round(Math.random() * 10000)}`,
    type,
    title: patch.numberedTitle ? `${patch.title || meta.title} ${count}` : patch.title || `${meta.title} ${count}`,
    icon: patch.icon || getDirectNodeIcon(type),
    x: flowPosition.x,
    y: flowPosition.y,
    actions: getDirectNodeActions(type),
    prompt: patch.prompt || '',
    promptSegments: normalizePromptSegments(patch.promptSegments, patch),
    promptPlaceholder: patch.promptPlaceholder || getDirectNodePrompt(type),
    groupId: patch.groupId || '',
    groupTitle: patch.groupTitle || '',
    media: patch.media || null,
    upload: patch.upload || null,
    imageModelId: patch.imageModelId || fallbackImageModelOptions[0].id,
    imageResolution: normalizeImageResolutionValue(patch.imageResolution),
    imageQuality: normalizeImageQualityValue(patch.imageQuality),
    videoModelId: patch.videoModelId || fallbackVideoModelOptions[0].id,
    videoGenerationType: patch.videoGenerationType || getDefaultVideoGenerationType(patch.videoModelId || fallbackVideoModelOptions[0].id),
    videoResolution: normalizeVideoResolutionValue(patch.videoResolution),
    videoDuration: normalizeVideoDurationValue(patch.videoDuration),
    videoQualityMode: patch.videoQualityMode || '',
    videoMotionStrength: patch.videoMotionStrength || '',
    videoAudioEnabled: Boolean(patch.videoAudioEnabled),
    videoWebSearch: Boolean(patch.videoWebSearch),
    videoEstimatePoints: Number.isFinite(Number(patch.videoEstimatePoints)) ? Number(patch.videoEstimatePoints) : null,
    videoEstimateStatus: patch.videoEstimateStatus || 'idle',
    audioAbilityType: patch.audioAbilityType || fallbackAudioAbilityOptions[0].id,
    audioTierCode: patch.audioTierCode || fallbackAudioAbilityOptions[0].defaultTier,
    audioModelCode: patch.audioModelCode || fallbackAudioAbilityOptions[0].tiers[0].modelCode,
    audioVoiceId: patch.audioVoiceId || audioVoiceOptions.value[0]?.voiceId || '',
    audioVoiceSourceType: patch.audioVoiceSourceType || audioVoiceOptions.value[0]?.sourceType || 'system',
    audioEmotion: patch.audioEmotion || '',
    audioSpeed: patch.audioSpeed ?? 1,
    audioVolume: patch.audioVolume ?? 1,
    audioPitch: patch.audioPitch ?? 0,
    audioFormat: patch.audioFormat || 'mp3',
    audioSampleRate: Number(patch.audioSampleRate || 32000),
    audioBitrate: Number(patch.audioBitrate || 128000),
    audioChannelCount: Number(patch.audioChannelCount || 1),
    audioLanguageBoost: patch.audioLanguageBoost || 'none',
    audioSettingsOpen: Boolean(patch.audioSettingsOpen),
    audioEstimatePoints: Number.isFinite(Number(patch.audioEstimatePoints)) ? Number(patch.audioEstimatePoints) : null,
    audioEstimateStatus: patch.audioEstimateStatus || 'idle',
    agentProfile: patch.agentProfile || 'auto',
    agentTemplateId: patch.agentTemplateId || '',
    agentName: patch.agentName || '',
    agentRolePromptSummary: patch.agentRolePromptSummary || '',
    agentInputTypes: Array.isArray(patch.agentInputTypes) ? patch.agentInputTypes : [],
    agentOutputTypes: Array.isArray(patch.agentOutputTypes) ? patch.agentOutputTypes : [],
    agentModelCode: patch.agentModelCode || patch.modelCode || 'deepseek-v4-flash',
    agentLastProposal: patch.agentLastProposal || patch.lastProposal || '',
    agentLastActionId: patch.agentLastActionId || '',
    agentLastActionStatus: patch.agentLastActionStatus || '',
    agentLastMessage: patch.agentLastMessage || '',
    agentLastRunAt: patch.agentLastRunAt || '',
    aspectRatio: patch.aspectRatio || fallbackImageAspectRatioOptions[0],
    referenceImages: normalizeManualReferenceImages(patch.referenceImages),
    referenceOrder: Array.isArray(patch.referenceOrder) ? patch.referenceOrder : [],
    referenceMentions: normalizeReferenceMentions(patch.referenceMentions),
    generationStatus: patch.generationStatus || 'idle',
    generationMessage: patch.generationMessage || '',
    generationTaskId: patch.generationTaskId || '',
    generationRecordId: patch.generationRecordId || '',
    generatedImage: patch.generatedImage || null,
    generatedVideo: patch.generatedVideo || null,
    generatedAudio: patch.generatedAudio || null
  }

  directNodes.value = [...directNodes.value, node]
  selectedDirectNodeIds.value = [node.id]
  focusedDirectNodeId.value = node.id
  activeDirectNodeId.value = node.id
  lastTouchedDirectNodeId.value = node.id
  nextTick(() => {
    selectedDirectNodeIds.value = [node.id]
    focusedDirectNodeId.value = node.id
    activeDirectNodeId.value = node.id
    lastTouchedDirectNodeId.value = node.id
    canvasFrame.value?.focus?.({ preventScroll: true })
    focusDeleteKeySink()
  })
  return node
}

function getDirectNodePositionFromPortAnchor(type, anchor, side) {
  const size = getDirectNodeSize(type)
  const portOffsetY = getDirectNodePortOffsetY(type)
  return {
    x: side === 'right' ? anchor.x - size.width : anchor.x,
    y: anchor.y - portOffsetY
  }
}

function getFlowNodePosition(screen, type) {
  const flow = screenToFlowCoordinate({ x: screen.x, y: screen.y })
  const zoom = viewport.value?.zoom || 1

  return {
    x: flow.x - 34 / zoom,
    y: flow.y - 28 / zoom
  }
}

function getAvailableDirectNodePosition(position) {
  const base = { x: position.x, y: position.y }
  const stepX = isCompactCanvas.value ? 420 : 700
  const stepY = isCompactCanvas.value ? 100 : 140
  const candidates = [
    base,
    { x: base.x - stepX, y: base.y },
    { x: base.x + stepX, y: base.y },
    { x: base.x - stepX, y: base.y + stepY },
    { x: base.x + stepX, y: base.y + stepY },
    { x: base.x, y: base.y + stepY * 2 }
  ]

  return candidates.find((candidate) => !isDirectNodePortBlocked(candidate)) || candidates.at(-1)
}

function isDirectNodePortBlocked(position) {
  return directNodes.value.some((node) => {
    const size = getDirectNodeSize(node.type)
    const horizontalOverlap = position.x > node.x - 80 && position.x < node.x + size.width + 80
    const verticalOverlap = position.y > node.y - 80 && position.y < node.y + size.height + 80
    return horizontalOverlap && verticalOverlap
  })
}

function getDirectNodeSize(type) {
  if (isCompactCanvas.value) return { width: 320, height: type === 'uploaded_asset' ? 470 : 520 }
  if (type === 'uploaded_asset') return { width: 410, height: 594 }
  if (type === 'agent_node') return { width: 500, height: 560 }
  if (type === 'image_unit') return { width: 860, height: 690 }
  if (type === 'audio_unit') return { width: 660, height: 620 }
  if (type === 'video_unit' || type === 'media_board') return { width: 620, height: 690 }
  return { width: 500, height: 690 }
}

function getDirectNodeIcon(type) {
  const icons = {
    prompt_note: '▤',
    image_unit: '▧',
    video_unit: '▣',
    media_board: '✂',
    uploaded_asset: '▧',
    audio_unit: '≋',
    script_episode: '▰',
    asset_table: '↥',
    agent_node: '智'
  }
  return icons[type] || '▤'
}

function getDirectNodeActions(type) {
  const actions = {
    prompt_note: ['自己编写内容', '文生视频', '图片反推提示词', '文字生音乐'],
    image_unit: ['图生图', '图片高清'],
    video_unit: ['文生视频', '图生视频', '首尾帧生成'],
    media_board: ['合并片段', '从历史选择', '导出预览'],
    uploaded_asset: [],
    audio_unit: ['音效', '配音', '音乐'],
    script_episode: ['创意脚本', '生成故事板', '分镜拆解'],
    asset_table: ['上传图片', '上传视频', '上传音频'],
    agent_node: ['分析选区', '生成下游', '检查一致性']
  }
  return actions[type] || actions.prompt_note
}

function getDirectNodeTextareaPlaceholder(node) {
  if (node?.type === 'image_unit') return '描述你想要生成的画面内容~ 单击可以引用参考图'
  return node?.promptPlaceholder || getDirectNodePrompt(node?.type)
}

function getDirectNodePrompt(type) {
  const prompts = {
    prompt_note: '写下你想讲的故事、场景或角色设定。例如：一个来自未来的机器人，在城市屋顶看星星。',
    image_unit: '描述你想要生成的画面内容~ 单击可以引用参考图',
    video_unit: '描述镜头运动、角色动作和画面节奏，也可以引用图片或文本节点。',
    media_board: '选择历史素材或多个视频片段，合成为一个可预览的结果。',
    uploaded_asset: '',
    audio_unit: '描述音效、配音语气或音乐氛围。',
    script_episode: '输入创意方向，生成故事脚本、分镜节拍和创作链路。',
    asset_table: '上传图片、视频、音频文件，整理可复用素材。',
    agent_node: '描述你希望 Agent 完成的创作任务。'
  }
  return prompts[type] || prompts.prompt_note
}

function buildCanvasNode(type, position, patch = {}) {
  const meta = nodeMeta[type] || nodeMeta.prompt_note
  const count = nodes.value.filter((node) => node.data?.nodeType === type).length + 1
  const title = patch.numberedTitle ? `${patch.title || meta.title} ${count}` : patch.title || `${meta.title} ${count}`

  return {
    id: `${type}-${Date.now()}-${Math.round(Math.random() * 10000)}`,
    type: patch.kind === 'group' ? 'groupFrame' : 'workflowNode',
    position,
    width: patch.kind === 'group' ? patch.width || 520 : undefined,
    height: patch.kind === 'group' ? patch.height || 320 : undefined,
    draggable: true,
    selectable: true,
    connectable: patch.kind !== 'group',
    data: {
      nodeType: type,
      kind: patch.kind || 'node',
      title,
      body: patch.body || meta.body,
      status: patch.status || 'draft',
      icon: patch.icon || meta.icon,
      kindLabel: patch.kindLabel || meta.label,
      accent: patch.accent || meta.accent,
      action: patch.action || meta.action,
      collapsed: false,
      progress: patch.progress || 0,
      portLabels: {
        in: '\u8f93\u5165',
        out: '\u8f93\u51fa'
      }
    },
    style: patch.kind === 'group' ? { width: `${patch.width || 520}px`, height: `${patch.height || 320}px` } : undefined,
    class: patch.kind === 'group' ? 'vue-flow__node-group-frame' : undefined
  }
}

function handleCreateWorkflow() {
  rememberHistory()

  if (nodes.value.length === 0) {
    const createdNodes = [
      buildCanvasNode('script_episode', { x: 80, y: 120 }, { title: '\u9996\u5e27\u56fe\u7247\u751f\u6210' }),
      buildCanvasNode('asset_table', { x: 430, y: 120 }, { title: '\u89d2\u8272\u4e09\u89c6\u56fe' }),
      buildCanvasNode('storyboard_table', { x: 780, y: 120 }, { title: '\u5206\u955c\u62c6\u89e3' }),
      buildCanvasNode('image_unit', { x: 1130, y: 120 }, { title: '\u9996\u5e27\u56fe\u7247\u751f\u6210' }),
      buildCanvasNode('video_unit', { x: 1480, y: 120 }, { title: '\u5206\u955c\u62c6\u89e3' }),
      buildCanvasNode('media_board', { x: 1830, y: 120 }, { title: '\u5206\u955c\u62c6\u89e3' })
    ]

    nodes.value = createdNodes
    edges.value = createdNodes.slice(0, -1).map((node, index) => buildEdge(node.id, createdNodes[index + 1].id, '\u751f\u6210'))
  } else {
    autoArrangeNodes()
  }

  nextTick(() => fitView({ duration: 320, padding: 0.18 }))
  showToast('\u5df2\u751f\u6210\u5de5\u4f5c\u6d41')
}

function autoArrangeNodes() {
  nodes.value = nodes.value.map((node, index) => ({
    ...node,
    position: {
      x: 120 + index * 340,
      y: node.data?.kind === 'group' ? 80 : index % 2 === 0 ? 120 : 340
    }
  }))
}

function handleAddResource() {
  createNode('asset_table', getViewportCenter(), { title: '上传资源节点', kindLabel: '资源' })
  showToast('已添加资源节点')
}

function runNode(nodeId) {
  rememberHistory()
  nodes.value = nodes.value.map((node) => {
    if (node.id !== nodeId || node.data?.kind === 'group') return node
    return {
      ...node,
      data: {
        ...node.data,
        status: 'running',
        progress: 68,
        body: `${node.data.body} ${'\u6b63\u5728\u751f\u6210\u9884\u89c8\u7ed3\u679c\u3002'}`
      }
    }
  })
  showToast('\u652f\u6301\u5165\u53e3\u5df2\u6253\u5f00')
}

function handleNodesChange(changes) {
  const selected = changes.filter((change) => change.type === 'select' && change.selected).map((change) => change.id)
  if (selected.length > 0 || changes.some((change) => change.type === 'select')) {
    canvasStore.setSelection(selected)
  }
}

function handleEdgesChange(changes) {
  const selected = changes.filter((change) => change.type === 'select' && change.selected).map((change) => change.id)
  if (selected.length > 0 || changes.some((change) => change.type === 'select')) {
    selectedEdgeIds.value = selected
  }
}

function syncSelectionFromNodes() {
  const selectedIds = nodes.value.filter((node) => node.selected).map((node) => node.id)
  if (selectedIds.join('|') !== canvasStore.selectedNodeIds.join('|')) {
    canvasStore.setSelection(selectedIds)
  }
}

function handleConnect(connection) {
  rememberHistory()
  edges.value = [...edges.value, buildEdge(connection.source, connection.target, '\u5f15\u7528', connection)]
  referenceMenu.visible = false
  connectionDraft.active = false
  showToast('已建立引用连线')
}

function handleConnectStart(payload, maybeParams) {
  const params = maybeParams || payload || {}
  const event = params.event || payload?.event || payload
  const nodeElement = event?.target instanceof Element ? event.target.closest('.vue-flow__node') : null
  connectionDraft.active = true
  connectionDraft.sourceId = params.nodeId || params.source || payload?.nodeId || nodeElement?.getAttribute('data-id') || ''
  connectionDraft.sourceHandle = params.handleId || params.sourceHandle || 'out'
  connectionDraft.edgeCount = edges.value.length
}

function handleConnectEnd(payload) {
  const event = payload?.event || payload
  const point = getPointerPoint(event)

  if (!connectionDraft.active || !connectionDraft.sourceId || !point) {
    connectionDraft.active = false
    return
  }

  window.setTimeout(() => {
    const connected = edges.value.length > connectionDraft.edgeCount
    if (connected) {
      connectionDraft.active = false
      return
    }

    referenceMenu.visible = true
    referenceMenu.sourceId = connectionDraft.sourceId
    referenceMenu.sourceHandle = connectionDraft.sourceHandle
    referenceMenu.screen = clampMenuPosition({ x: point.x + 22, y: point.y - 168 }, 300, 460)
    referenceMenu.flow = screenToFlowCoordinate({ x: point.x + 360, y: point.y - 28 })
    addMenu.visible = false
    contextMenu.visible = false
    connectionDraft.active = false
  }, 0)
}

function getPointerPoint(event) {
  if (!event) return null
  if ('clientX' in event && 'clientY' in event) return { x: event.clientX, y: event.clientY }
  const touch = event.changedTouches?.[0] || event.touches?.[0]
  if (touch) return { x: touch.clientX, y: touch.clientY }
  return null
}

function buildEdge(source, target, label, connection = {}) {
  return {
    id: `edge-${Date.now()}-${Math.round(Math.random() * 10000)}`,
    source,
    target,
    sourceHandle: connection.sourceHandle,
    targetHandle: connection.targetHandle,
    label,
    type: 'workflow',
    markerEnd: MarkerType.ArrowClosed,
    interactionWidth: 24
  }
}

function deleteSelection() {
  const selectedNodeIds = new Set(canvasStore.selectedNodeIds)
  const selectedEdges = new Set(selectedEdgeIds.value)
  const selectedDirectIds = new Set(selectedDirectNodeIds.value)
  if (selectedNodeIds.size === 0 && selectedEdges.size === 0 && selectedDirectIds.size === 0) return

  rememberHistory()
  nodes.value = nodes.value.filter((node) => !selectedNodeIds.has(node.id))
  if (selectedDirectIds.size > 0) {
    directNodes.value = directNodes.value.filter((node) => !selectedDirectIds.has(node.id))
    directEdges.value = directEdges.value.filter(
      (edge) => !selectedDirectIds.has(edge.sourceId) && !selectedDirectIds.has(edge.targetId)
    )
    directEdges.value = directEdges.value.filter((edge) => isDirectEndpointAvailable(edge.sourceId) && isDirectEndpointAvailable(edge.targetId))
    selectedDirectIds.forEach((id) => directNodeElements.delete(id))
  }
  edges.value = edges.value.filter(
    (edge) => !selectedEdges.has(edge.id) && !selectedNodeIds.has(edge.source) && !selectedNodeIds.has(edge.target)
  )
  canvasStore.clearSelection()
  selectedDirectNodeIds.value = []
  selectedEdgeIds.value = []
  contextMenu.visible = false
  showToast('\u5df2\u64cd\u4f5c')
}

function deleteDirectSelection() {
  const selectedDirectIds = new Set(selectedDirectNodeIds.value)
  if (selectedDirectIds.size === 0) return

  deleteDirectNodesByIds([...selectedDirectIds])
}

function deleteDirectNodesByIds(ids) {
  const idSet = new Set(ids)
  if (idSet.size === 0) return

  rememberHistory()
  const nextDirectNodes = directNodes.value.filter((node) => !idSet.has(node.id))
  directNodes.value = nextDirectNodes
  directEdges.value = directEdges.value.filter((edge) => !idSet.has(edge.sourceId) && !idSet.has(edge.targetId))
  directEdges.value = directEdges.value.filter((edge) => isDirectEndpointAvailable(edge.sourceId) && isDirectEndpointAvailable(edge.targetId))
  idSet.forEach((id) => {
    revokeLocalPreviewForNode(id)
    uploadFileMap.delete(id)
    releaseUploadSignature(id)
    directNodeElements.delete(id)
    clearImageGenerationTimer(id)
    clearVideoGenerationTimer(id)
    clearAudioGenerationTimer(id)
  })
  selectedDirectNodeIds.value = selectedDirectNodeIds.value.filter((id) => !idSet.has(id))
  if (idSet.has(focusedDirectNodeId.value)) focusedDirectNodeId.value = ''
  if (idSet.has(activeDirectNodeId.value)) activeDirectNodeId.value = selectedDirectNodeIds.value.at(-1) || ''
  if (idSet.has(lastTouchedDirectNodeId.value)) lastTouchedDirectNodeId.value = activeDirectNodeId.value || ''

  if (nodes.value.length === 0 && nextDirectNodes.length === 0) {
    canvasStore.clearSelection()
    selectedEdgeIds.value = []
    selectedDirectNodeIds.value = []
    focusedDirectNodeId.value = ''
    activeDirectNodeId.value = ''
    lastTouchedDirectNodeId.value = ''
    canvasActivated.value = false
  } else {
    selectedDirectNodeIds.value = []
    focusedDirectNodeId.value = ''
    activeDirectNodeId.value = ''
    lastTouchedDirectNodeId.value = ''
    canvasActivated.value = true
    focusDeleteKeySink()
  }

  showToast('已删除节点')
}

function deleteDirectNode(nodeId) {
  if (!selectedDirectNodeIds.value.includes(nodeId)) {
    selectedDirectNodeIds.value = [nodeId]
  }
  deleteDirectSelection()
}

function copySelection() {
  const selectedIds = new Set(canvasStore.selectedNodeIds)
  const selectedNodes = nodes.value.filter((node) => selectedIds.has(node.id))
  if (selectedNodes.length === 0) return

  clipboardNodes.value = cloneCanvasValue(selectedNodes)
  clipboardEdges.value = cloneCanvasValue(edges.value.filter((edge) => selectedIds.has(edge.source) && selectedIds.has(edge.target)))
  showToast('\u5df2\u64cd\u4f5c')
}

function pasteSelection() {
  if (clipboardNodes.value.length === 0) return
  rememberHistory()

  const idMap = new Map()
  const pastedNodes = clipboardNodes.value.map((node) => {
    const nextId = `${node.data.nodeType}-${Date.now()}-${Math.round(Math.random() * 10000)}`
    idMap.set(node.id, nextId)
    return {
      ...cloneCanvasValue(node),
      id: nextId,
      selected: false,
      position: {
        x: node.position.x + 56,
        y: node.position.y + 56
      }
    }
  })

  const pastedEdges = clipboardEdges.value
    .filter((edge) => idMap.has(edge.source) && idMap.has(edge.target))
    .map((edge) => ({
      ...cloneCanvasValue(edge),
      id: `edge-${Date.now()}-${Math.round(Math.random() * 10000)}`,
      source: idMap.get(edge.source),
      target: idMap.get(edge.target),
      selected: false
    }))

  nodes.value = [...nodes.value, ...pastedNodes]
  edges.value = [...edges.value, ...pastedEdges]
  canvasStore.setSelection(pastedNodes.map((node) => node.id))
  showToast('\u5df2\u64cd\u4f5c')
}

function handleContextUpload() {
  pendingUploadFlowPosition.value = getAvailableDirectNodePosition(contextMenu.flow || getViewportCenter())
  replacingUploadNodeId.value = ''
  contextMenu.visible = false
  openUploadDialog()
}

function handleContextAgentAnalyze() {
  contextMenu.visible = false
  startAgentWithSelection('请分析当前选区，并给出下一步创作建议。')
}

function handleContextAgentDownstream() {
  contextMenu.visible = false
  startAgentWithSelection('请根据当前选区生成下游分镜、首帧和视频生成链路。')
}

function handleContextAgentConsistency() {
  contextMenu.visible = false
  startAgentWithSelection('请检查当前选区的角色、场景、道具和风格一致性。')
}

function handleContextUndo() {
  contextMenu.visible = false
  undoLastChange()
}

function handleContextRedo() {
  contextMenu.visible = false
  redoLastChange()
}

function duplicateSelection() {
  copySelection()
  pasteSelection()
  contextMenu.visible = false
}

function groupSelection() {
  if (selectedDirectGroupId.value) {
    ungroupSelectedDirectNodes()
    return
  }
  if (selectedDirectNodes.value.length >= 2) {
    groupSelectedDirectNodes()
    return
  }

  const selectedIds = new Set(canvasStore.selectedNodeIds)
  const selectedNodes = nodes.value.filter((node) => selectedIds.has(node.id) && node.data?.kind !== 'group')
  if (selectedNodes.length < 2) {
    showToast('\u81f3\u5c11\u9009\u62e9\u4e24\u4e2a\u8282\u70b9\u624d\u80fd\u6253\u7ec4')
    return
  }

  rememberHistory()
  const bounds = getNodeBounds(selectedNodes)
  const group = buildCanvasNode(
    'media_board',
    { x: bounds.x - 38, y: bounds.y - 58 },
    {
      kind: 'group',
      title: '\u8282\u70b9\u5206\u7ec4',
      body: `${selectedNodes.length} ${'\u4e2a\u8282\u70b9'}`,
      kindLabel: '\u5206\u7ec4',
      icon: '?',
      accent: '#707070',
      status: 'idle',
      width: bounds.width + 76,
      height: bounds.height + 106
    }
  )

  nodes.value = [group, ...nodes.value]
  selectOnly(group.id)
  contextMenu.visible = false
  showToast('\u5df2\u64cd\u4f5c')
}

function getNodeBounds(items) {
  const left = Math.min(...items.map((node) => node.position.x))
  const top = Math.min(...items.map((node) => node.position.y))
  const right = Math.max(...items.map((node) => node.position.x + (node.dimensions?.width || node.width || 270)))
  const bottom = Math.max(...items.map((node) => node.position.y + (node.dimensions?.height || node.height || 132)))
  return {
    x: left,
    y: top,
    width: right - left,
    height: bottom - top
  }
}

function getGroupChildren(groupId) {
  const group = nodes.value.find((node) => node.id === groupId)
  if (!group) return []
  const gx = group.position.x
  const gy = group.position.y
  const gw = Number.parseFloat(group.style?.width) || group.width || 520
  const gh = Number.parseFloat(group.style?.height) || group.height || 320
  return nodes.value.filter((node) => {
    if (node.id === groupId || node.data?.kind === 'group') return false
    return node.position.x >= gx && node.position.x <= gx + gw && node.position.y >= gy && node.position.y <= gy + gh
  })
}

function selectOnly(nodeId) {
  nodes.value = nodes.value.map((node) => ({ ...node, selected: node.id === nodeId }))
  canvasStore.setSelection([nodeId])
}

function toggleGrid() {
  gridVisible.value = !gridVisible.value
  showToast(gridVisible.value ? '\u7f51\u683c\u5df2\u663e\u793a' : '\u7f51\u683c\u5df2\u9690\u85cf')
}

function toggleMinimap() {
  minimapVisible.value = !minimapVisible.value
}

function toggleSnap() {
  snapEnabled.value = !snapEnabled.value
  showToast(snapEnabled.value ? '\u5df2\u5f00\u542f\u5438\u9644' : '\u5df2\u5173\u95ed\u5438\u9644')
}

function goHome() {
  router.push({ name: 'workspace' })
}

function logoutCanvas() {
  window.localStorage.removeItem('shenlu_token')
  window.localStorage.removeItem('shenlu_nickname')
  router.push({ name: 'home' })
}

function locateCanvas() {
  if (nodes.value.length > 0) {
    fitView({ duration: 280, padding: 0.2 })
  } else {
    setViewport({ x: 0, y: 0, zoom: 1 }, { duration: 240 })
  }
  showToast('已定位画布')
}

function handleZoomIn() {
  zoomIn({ duration: 160 })
}

function handleZoomOut() {
  zoomOut({ duration: 160 })
}

function toggleHelp() {
  helpVisible.value = !helpVisible.value
}

function handleSupport() {
  showToast('\u652f\u6301\u5165\u53e3\u5df2\u6253\u5f00')
}

function handleMoveEnd(event) {
  canvasStore.setViewport(event.flowTransform)
  scheduleCanvasSave()
  syncPendingReferenceMenuScreen()
}

function rememberHistory() {
  if (suppressHistory.value) return
  historyStack.value.push(captureCanvasHistorySnapshot())
  redoStack.value = []
  if (historyStack.value.length > 40) historyStack.value.shift()
}

function captureCanvasHistorySnapshot() {
  return {
    nodes: cloneCanvasValue(nodes.value),
    edges: cloneCanvasValue(edges.value),
    directNodes: cloneCanvasValue(directNodes.value),
    directEdges: cloneCanvasValue(directEdges.value)
  }
}

function cloneCanvasValue(value) {
  return JSON.parse(JSON.stringify(value))
}

function undoLastChange() {
  const previous = historyStack.value.pop()
  if (!previous) {
    showToast('\u6ca1\u6709\u53ef\u64a4\u9500\u7684\u64cd\u4f5c')
    return
  }
  redoStack.value.push(captureCanvasHistorySnapshot())
  if (redoStack.value.length > 40) redoStack.value.shift()
  restoreCanvasHistorySnapshot(previous)
  showToast('\u5df2\u64a4\u9500')
}

function redoLastChange() {
  const next = redoStack.value.pop()
  if (!next) {
    showToast('没有可重做的操作')
    return
  }
  historyStack.value.push(captureCanvasHistorySnapshot())
  if (historyStack.value.length > 40) historyStack.value.shift()
  restoreCanvasHistorySnapshot(next)
  showToast('已重做')
}

function restoreCanvasHistorySnapshot(snapshot) {
  suppressHistory.value = true
  nodes.value = snapshot.nodes || []
  edges.value = snapshot.edges || []
  directNodes.value = snapshot.directNodes || []
  directEdges.value = snapshot.directEdges || []
  canvasStore.clearSelection()
  selectedEdgeIds.value = []
  selectedDirectNodeIds.value = []
  focusedDirectNodeId.value = ''
  activeDirectNodeId.value = ''
  lastTouchedDirectNodeId.value = ''
  nextTick(() => {
    suppressHistory.value = false
  })
}

function getViewportCenter() {
  return screenToFlowCoordinate({
    x: window.innerWidth / 2,
    y: window.innerHeight / 2
  })
}

function clampMenuPosition(screen, menuWidth, menuHeight) {
  const padding = 8
  const topSafeArea = 78
  const rect = canvasFrame.value?.getBoundingClientRect?.()
  const bounds = rect || { left: 0, top: 0, right: window.innerWidth, bottom: window.innerHeight }
  const maxX = bounds.right - menuWidth - padding
  const maxY = bounds.bottom - menuHeight - padding
  return {
    x: Math.min(Math.max(screen.x, bounds.left + padding), Math.max(bounds.left + padding, maxX)),
    y: Math.min(Math.max(screen.y, bounds.top + topSafeArea), Math.max(bounds.top + topSafeArea, maxY))
  }
}

function showToast(message) {
  toastMessage.value = message
  window.clearTimeout(showToast.timer)
  showToast.timer = window.setTimeout(() => {
    toastMessage.value = ''
  }, 1500)
}
</script>
