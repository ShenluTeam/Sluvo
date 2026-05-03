<template>
  <div class="libtv-canvas-shell" :class="{ 'is-space-panning': spacePanning }" @click="closeFloatingPanels" @contextmenu.capture="handleCanvasContextMenu">
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
        :zoom-on-scroll="true"
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
            v-if="referenceMenu.visible && pendingDirectConnection.sourceId"
            class="direct-edge__draft"
            :d="getPendingDirectEdgePath()"
            pathLength="1"
          />
        </svg>

        <article
          v-for="(node, index) in directNodes"
          :key="node.id"
          :ref="(element) => registerDirectNodeElement(node.id, element)"
          class="direct-workflow-node"
          :class="[`direct-workflow-node--${node.type}`, { 'is-selected': selectedDirectNodeIds.includes(node.id) }]"
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
                <small v-if="node.upload.message">{{ node.upload.message }}</small>
                <div class="uploaded-asset__progress">
                  <span :style="{ width: `${node.upload.progress}%` }" />
                </div>
              </div>
              <div v-else class="uploaded-asset__state">上传成功</div>
              <div v-if="node.upload?.status === 'uploading' && node.media?.url" class="uploaded-asset__overlay">
                <span>上传中 {{ node.upload.progress }}%</span>
                <small v-if="node.upload.message">{{ node.upload.message }}</small>
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
              <div class="generated-image__actions" @click.stop @pointerdown.stop @contextmenu.prevent.stop>
                <button type="button" title="预览图片" @click.stop="previewGeneratedImage(node)">
                  <Eye :size="16" />
                </button>
                <button type="button" title="下载图片" @click.stop="downloadGeneratedImage(node)">
                  <Download :size="16" />
                </button>
              </div>
            </div>

            <template v-else>
            <div class="direct-workflow-node__hero">
              <span v-if="node.type === 'prompt_note'" class="direct-workflow-node__lines" />
              <span v-else class="direct-workflow-node__icon">{{ node.icon }}</span>
            </div>

            <p>尝试:</p>
            <button v-for="action in node.actions" :key="action" type="button">{{ action }}</button>
            </template>
          </div>

          <div
            v-if="node.type !== 'uploaded_asset' && selectedDirectNodeIds.includes(node.id)"
            class="direct-workflow-node__fixed-panel"
          >
            <div
              v-if="node.type === 'image_unit'"
              class="direct-workflow-node__references"
              @click.stop
              @dblclick.stop
              @keydown.stop
              @keyup.stop
              @pointerdown.stop
              @mousedown.stop
              @dragover.prevent.stop
            >
              <button
                class="direct-workflow-node__reference-upload"
                type="button"
                title="上传参考图"
                @click.stop="openReferenceUploadDialog(node.id)"
              >
                <Upload :size="17" />
              </button>
              <div
                v-for="(reference, index) in getDirectImageReferenceItems(node.id)"
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
                <img :src="reference.previewUrl || reference.url" :alt="reference.name || `参考图 ${index + 1}`" draggable="false" />
                <div class="direct-workflow-node__reference-popout" aria-hidden="true">
                  <img :src="reference.previewUrl || reference.url" alt="" draggable="false" />
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
            </div>
            <div
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
          </div>
        </article>
      </div>

      <div v-if="selectionBox.active" class="direct-selection-box" :style="selectionBoxStyle" />

      <input
        ref="deleteKeySink"
        class="delete-key-sink"
        aria-hidden="true"
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
        accept="image/*"
        multiple
        @change="handleReferenceUploadInputChange"
      />

      <CommandBar
        v-model:title="projectTitle"
        :save-status="saveStatus"
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
        <button type="button" :disabled="!canUndo" @click="handleContextUndo">
          <span>撤销</span>
          <kbd>Ctrl Z</kbd>
        </button>
        <button type="button" :disabled="!canRedo" @click="handleContextRedo">
          <span>重做</span>
          <kbd>Ctrl Shift Z</kbd>
        </button>
      </div>

      <div v-if="helpVisible" class="canvas-help-panel" @click.stop>
        <strong>{{ copy.helpTitle }}</strong>
        <span>{{ copy.helpAdd }}</span>
        <span>{{ copy.helpPan }}</span>
        <span>{{ copy.helpSelect }}</span>
        <span>{{ copy.helpCopy }}</span>
        <span>{{ copy.helpZoom }}</span>
      </div>

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
import { useRoute, useRouter } from 'vue-router'
import { MarkerType, VueFlow, useVueFlow } from '@vue-flow/core'
import { Background } from '@vue-flow/background'
import { ArrowUpDown, Download, Eye, ListChecks, Minus, Music2, Plus, Star, Upload, X } from 'lucide-vue-next'
import CommandBar from '../components/layout/CommandBar.vue'
import AddNodeMenu from '../components/canvas/AddNodeMenu.vue'
import CanvasBottomControls from '../components/canvas/CanvasBottomControls.vue'
import CanvasToolRail from '../components/canvas/CanvasToolRail.vue'
import StarterSkillStrip from '../components/canvas/StarterSkillStrip.vue'
import WorkflowEdge from '../canvas/edges/WorkflowEdge.vue'
import WorkflowNode from '../canvas/nodes/WorkflowNode.vue'
import {
  fetchCreativeImageCatalog,
  fetchCreativeRecord,
  fetchCreativeRecords,
  fetchTask,
  submitCreativeImage
} from '../api/creativeApi'
import {
  fetchSluvoProjectCanvas,
  publishSluvoProjectToCommunity,
  saveSluvoCanvasBatch,
  SluvoRevisionConflictError,
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
  }
}

const route = useRoute()
const router = useRouter()
const canvasStore = useCanvasStore()
const projectStore = useProjectStore()
const projectTitle = ref(copy.untitled)
const saveStatus = ref('idle')
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
const directNodeElements = new Map()
const directPromptEditorElements = new Map()
const directPromptEditorSignatures = new Map()
let previousDocumentKeydown = null
let previousWindowKeydown = null
let frameResizeObserver = null
let uploadTimer = null
let autoSaveTimer = null
let suppressCanvasSaveScheduling = false
const imageGenerationTimers = new Map()
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
  updateFrameSize()
  loadImageGenerationCatalog()
  loadProjectCanvas()
  if (typeof ResizeObserver !== 'undefined' && canvasFrame.value) {
    frameResizeObserver = new ResizeObserver(updateFrameSize)
    frameResizeObserver.observe(canvasFrame.value)
  }
})

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
  frameResizeObserver?.disconnect()
  window.clearTimeout(autoSaveTimer)
  window.clearInterval(uploadTimer)
  window.clearTimeout(clipboardPasteFallbackTimer)
  window.cancelAnimationFrame(directPortLayoutRaf)
  clearLocalPreviewUrls()
  clearImageGenerationTimers()
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
    .filter((edge) => directNodes.value.some((node) => node.id === edge.sourceId) && directNodes.value.some((node) => node.id === edge.targetId))
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
    await saveCanvasNow()
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
    media: data.media || null,
    upload: data.upload || null,
    imageModelId: data.imageModelId || fallbackImageModelOptions[0].id,
    imageResolution: normalizeImageResolutionValue(data.imageResolution || data.resolution),
    imageQuality: normalizeImageQualityValue(data.imageQuality || data.quality),
    aspectRatio: data.aspectRatio || fallbackImageAspectRatioOptions[0],
    referenceImages: normalizeManualReferenceImages(data.referenceImages),
    referenceOrder: Array.isArray(data.referenceOrder) ? data.referenceOrder : [],
    referenceMentions: normalizeReferenceMentions(data.referenceMentions),
    generationStatus: data.generationStatus || node.status || 'idle',
    generationMessage: data.generationMessage || '',
    generationTaskId: data.generationTaskId || '',
    generationRecordId: data.generationRecordId || '',
    generatedImage: data.generatedImage || null,
    clientId: data.clientId || node.id
  }
}

function mapBackendEdgeToDirectEdge(edge) {
  return {
    id: edge.id,
    sourceId: edge.sourceNodeId,
    targetId: edge.targetNodeId,
    sourcePortId: edge.sourcePortId || 'right',
    targetPortId: edge.targetPortId || 'left'
  }
}

function normalizeBackendDirectType(nodeType, directType = '') {
  const directTypes = new Set(['prompt_note', 'image_unit', 'video_unit', 'audio_unit', 'uploaded_asset', 'script_episode', 'asset_table', 'storyboard_table', 'media_board'])
  if (directTypes.has(directType)) return directType
  const map = {
    text: 'prompt_note',
    note: 'prompt_note',
    image: 'image_unit',
    generation: 'image_unit',
    video: 'video_unit',
    audio: 'audio_unit',
    upload: 'uploaded_asset',
    group: 'media_board'
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
    Boolean(target.closest('.direct-workflow-node__prompt-field, .direct-workflow-node__references, .direct-workflow-node__generation-controls'))
  )
}

function handleDirectNodeSelectStart(event) {
  if (isDirectPromptEditTarget(event.target)) return
  event.preventDefault()
}

function hydrateDirectPromptEditor(element, node = null) {
  element.replaceChildren()
  normalizePromptSegments(node?.promptSegments, node).forEach((segment) => {
    if (segment.type === 'reference') {
      element.appendChild(createPromptReferenceToken(segment, node?.id))
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
    .filter((segment) => segment.type === 'text')
    .map((segment) => segment.text)
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
  if (node instanceof HTMLElement && node.classList.contains('direct-workflow-node__mention-chip')) return node
  if (!(node instanceof HTMLElement)) return null
  for (let index = node.childNodes.length - 1; index >= 0; index -= 1) {
    const token = findLastTokenInside(node.childNodes[index])
    if (token) return token
  }
  return null
}

function findFirstTokenInside(node) {
  if (!(node instanceof HTMLElement) && node?.nodeType !== Node.TEXT_NODE) return null
  if (node instanceof HTMLElement && node.classList.contains('direct-workflow-node__mention-chip')) return node
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

async function saveCanvasNow() {
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
    showToast('文件上传中，上传完成后自动保存')
    return
  }
  window.clearTimeout(autoSaveTimer)
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
      showToast('画布已在其他地方更新，正在刷新')
      await loadProjectCanvas()
      return
    }
    saveStatus.value = 'error'
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
    if (edge.sourceNodeId && edge.targetNodeId) {
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
      prompt: node.prompt || '',
      body: node.prompt || '',
      promptSegments: normalizePromptSegments(node.promptSegments, node),
      promptPlaceholder: node.promptPlaceholder || '',
      media,
      upload: node.upload || null,
      imageModelId: node.imageModelId || '',
      imageResolution: normalizeImageResolutionValue(node.imageResolution),
      imageQuality: normalizeImageQualityValue(node.imageQuality),
      aspectRatio: node.aspectRatio || '',
      referenceImages: normalizeManualReferenceImages(node.referenceImages)
        .filter((item) => item.status !== 'uploading')
        .map((item) => ({
          ...item,
          previewUrl: item.previewUrl?.startsWith('blob:') ? '' : item.previewUrl
        })),
      referenceOrder: Array.isArray(node.referenceOrder) ? node.referenceOrder : [],
      referenceMentions: normalizeReferenceMentions(node.referenceMentions),
      generationStatus: node.generationStatus || 'idle',
      generationMessage: node.generationMessage || '',
      generationTaskId: node.generationTaskId || '',
      generationRecordId: node.generationRecordId || '',
      generatedImage: node.generatedImage || null
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
  if (media.isLocalPreview || String(media.url || '').startsWith('blob:')) {
    return {
      ...media,
      url: media.assetId ? media.url : '',
      previewUrl: '',
      isLocalPreview: false,
      localPreviewDropped: true
    }
  }
  const previewUrl = String(media.previewUrl || '')
  if (previewUrl.startsWith('blob:')) {
    return {
      ...media,
      previewUrl: ''
    }
  }
  return media
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
    storyboard_table: 'note'
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
    directNodes: cloneCanvasValue(directNodes.value).map((node) => ({
      ...node,
      media: sanitizeMediaForPersistence(node.media)
    })),
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
    (['INPUT', 'TEXTAREA', 'SELECT'].includes(target.tagName) || Boolean(target.closest('[contenteditable="true"]')))
  )
}

function handleFramePointerDown(event) {
  if (event.button !== 0 || isTypingTarget(event.target)) return

  const target = event.target instanceof Element ? event.target : null
  if (
    target?.closest(
      '.direct-workflow-node, .vue-flow__node, .add-node-menu, .libtv-topbar, .canvas-tool-rail, .canvas-bottom-controls, .canvas-minimap, .rail-panel, .history-overlay, .library-picker-overlay, .starter-strip, .canvas-help-panel, .canvas-context-menu'
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
  if (!isCanvasWheelZoomTarget(event.target)) return
  const frame = canvasFrame.value
  const rect = frame?.getBoundingClientRect?.()
  if (!rect) return

  event.preventDefault()
  event.stopPropagation()

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

function isCanvasWheelZoomTarget(target) {
  const element = target instanceof Element ? target : null
  if (!element) return true
  return !element.closest(
    '.libtv-topbar, .canvas-tool-rail, .canvas-bottom-controls, .canvas-minimap, .rail-panel, .history-overlay, .library-picker-overlay, .starter-strip, .canvas-help-panel, .canvas-context-menu, .add-node-menu'
  )
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
    selectedDirectNodeIds.value = directNodes.value
      .filter((node) => intersectsRect(rect, getDirectNodeScreenRect(node)))
      .map((node) => node.id)
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
  selectedDirectNodeIds.value = directNodes.value
    .filter((node) => intersectsRect(rect, getDirectNodeScreenRect(node)))
    .map((node) => node.id)
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
    pendingDirectConnection.sourceId = ''
    pendingDirectConnection.sourceSide = 'right'
    selectedDirectNodeIds.value = [targetId]
    activeDirectNodeId.value = targetId
    focusedDirectNodeId.value = targetId
    lastTouchedDirectNodeId.value = targetId
    showToast('\u5df2\u8fde\u63a5\u8282\u70b9')
    flushDeferredInteractionSave()
    return
  }

  referenceMenu.visible = true
  referenceMenu.sourceId = ''
  referenceMenu.sourceHandle = 'direct'
  referenceMenu.flow = point
  syncPendingReferenceMenuScreen()
  addMenu.visible = false
  contextMenu.visible = false
}

function findDirectConnectionTarget(event, sourceId, flowPoint = null) {
  const point = getPointerPoint(event)

  if (point) {
    const hovered = document.elementFromPoint(point.x, point.y)
    const directNodeId = hovered?.closest?.('.direct-workflow-node')?.getAttribute('data-direct-node-id') || ''
    if (directNodeId && directNodeId !== sourceId) return directNodeId
  }

  const targetNode = directNodes.value.find((node) => {
    if (node.id === sourceId) return false
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
  const sourceNode = directNodes.value.find((node) => node.id === edge.sourceId)
  const targetNode = directNodes.value.find((node) => node.id === edge.targetId)
  if (!sourceNode || !targetNode) return ''

  return buildDirectCurvePath(getDirectNodePortPosition(sourceNode, 'right'), getDirectNodePortPosition(targetNode, 'left'))
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

function handleDirectNodePointerDown(event, nodeId) {
  if (event.button !== 0) return
  closeFloatingPanels()
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
    selectedDirectNodeIds.value = selectedDirectNodeIds.value.includes(nodeId)
      ? selectedDirectNodeIds.value.filter((id) => id !== nodeId)
      : [...selectedDirectNodeIds.value, nodeId]
    return
  }

  if (!selectedDirectNodeIds.value.includes(nodeId)) {
    selectedDirectNodeIds.value = [nodeId]
  }
  canvasStore.clearSelection()
  directDrag.active = true
  directDrag.startScreen = { x: event.clientX, y: event.clientY }
  directDrag.originals = directNodes.value
    .filter((node) => selectedDirectNodeIds.value.includes(node.id))
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
      '.image-preview-overlay'
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
      '.vue-flow__node, .add-node-menu, .libtv-topbar, .canvas-tool-rail, .canvas-bottom-controls, .canvas-minimap, .rail-panel, .history-overlay, .library-picker-overlay, .starter-strip, .canvas-help-panel, .canvas-context-menu'
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
  activeRailPanel.value = ''
  if (clearPendingConnection) {
    pendingDirectConnection.sourceId = ''
    pendingDirectConnection.sourceSide = 'right'
    pendingDirectConnection.start = { x: 0, y: 0 }
    pendingDirectConnection.point = { x: 0, y: 0 }
  }
  nextTick(() => flushDeferredInteractionSave())
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

function handleReferenceSelect(selection) {
  const item = normalizeMenuSelection(selection)
  if (pendingDirectConnection.sourceId) {
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
    pendingDirectConnection.sourceId = ''
    pendingDirectConnection.sourceSide = 'right'
    pendingDirectConnection.start = { x: 0, y: 0 }
    pendingDirectConnection.point = { x: 0, y: 0 }
    showToast('\u5df2\u8fde\u63a5\u8282\u70b9')
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

function openReferenceUploadDialog(nodeId) {
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
  if (isTypingTarget(event.target) && !isDeleteKeySinkTarget(event.target)) return

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
  const files = Array.from(event.target?.files || []).filter((file) => file.type?.startsWith('image/'))
  if (!nodeId || files.length === 0) {
    if (event.target) event.target.value = ''
    return
  }
  uploadReferenceImages(nodeId, files)
  if (event.target) event.target.value = ''
}

function uploadReferenceImages(nodeId, files) {
  const node = directNodes.value.find((item) => item.id === nodeId)
  if (!node) return
  if (!activeCanvas.value?.id) {
    showToast('画布尚未加载完成，请稍后重试')
    return
  }

  const validFiles = files.filter((file) => {
    if (!file.type?.startsWith('image/')) return false
    if (file.size > 20 * 1024 * 1024) {
      showToast('参考图不能超过 20MB')
      return false
    }
    return true
  })
  if (!validFiles.length) return

  rememberHistory()
  const nextReferences = normalizeManualReferenceImages(node.referenceImages)
  const nextOrder = Array.isArray(node.referenceOrder) ? [...node.referenceOrder] : getDirectImageReferenceItems(nodeId).map((item) => item.id)
  const refsToUpload = validFiles.map((file, index) => {
    const id = `manual-ref-${Date.now()}-${index}-${Math.round(Math.random() * 10000)}`
    const previewUrl = URL.createObjectURL(file)
    const reference = {
      id,
      source: 'manual',
      url: '',
      previewUrl,
      name: file.name || '参考图',
      status: 'uploading',
      progress: 8,
      width: 0,
      height: 0,
      assetId: '',
      storageObjectId: ''
    }
    nextReferences.push(reference)
    nextOrder.push(id)
    return { file, reference, previewUrl }
  })
  updateDirectNode(nodeId, { referenceImages: nextReferences, referenceOrder: nextOrder })

  refsToUpload.forEach(({ file, reference, previewUrl }) => uploadReferenceImage(nodeId, reference.id, file, previewUrl))
  showToast(validFiles.length > 1 ? `正在上传 ${validFiles.length} 张参考图` : '正在上传参考图')
}

async function uploadReferenceImage(nodeId, referenceId, file, previewUrl) {
  try {
    const metadata = await readUploadMetadata('image', previewUrl)
    patchManualReferenceImage(nodeId, referenceId, {
      width: metadata?.width || 0,
      height: metadata?.height || 0
    })
    const response = await uploadSluvoCanvasAsset(activeCanvas.value.id, file, {
      mediaType: 'image',
      width: metadata?.width,
      height: metadata?.height,
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
      status: 'success',
      progress: 100,
      width: asset.width || metadata?.width || 0,
      height: asset.height || metadata?.height || 0,
      assetId: asset.id || '',
      storageObjectId: response?.storageObjectId || asset.storageObjectId || ''
    })
    flushDeferredCanvasSave(220)
  } catch (error) {
    patchManualReferenceImage(nodeId, referenceId, {
      status: 'error',
      progress: 0,
      message: error instanceof Error ? error.message : '上传失败'
    })
    showToast(error instanceof Error ? error.message : '参考图上传失败')
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
  flushDeferredCanvasSave(120)
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

function normalizeDisplayImageSrc(value) {
  const source = String(value || '').trim()
  if (!source) return ''
  if (source.startsWith('//')) return `${window.location.protocol}${source}`
  if (/^(https?:|data:image\/|blob:)/i.test(source)) return source
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

function buildGeneratedImageFilename(node) {
  const image = node?.generatedImage || {}
  const base = String(node?.title || 'sluvo-image').trim().replace(/[\\/:*?"<>|\s]+/g, '-')
  const extension = inferImageExtension(image.url || image.thumbnailUrl || '')
  return `${base || 'sluvo-image'}${extension}`
}

function inferImageExtension(url) {
  const source = String(url || '').split('?')[0].toLowerCase()
  if (source.includes('image/png') || source.endsWith('.png')) return '.png'
  if (source.includes('image/webp') || source.endsWith('.webp')) return '.webp'
  if (source.includes('image/gif') || source.endsWith('.gif')) return '.gif'
  return '.jpg'
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
  return getDirectImageReferenceItems(nodeId).some((reference) => reference.status === 'uploading')
}

function normalizeManualReferenceImages(value) {
  return (Array.isArray(value) ? value : [])
    .map((item) => {
      const id = item?.id || `manual-ref-${Date.now()}-${Math.round(Math.random() * 10000)}`
      const url = item?.url || ''
      const previewUrl = item?.previewUrl || item?.thumbnailUrl || url
      if (!url && !previewUrl) return null
      return {
        id,
        source: 'manual',
        url,
        previewUrl,
        name: item?.name || '参考图',
        status: item?.status || (url ? 'success' : 'uploading'),
        progress: Number(item?.progress || 0),
        width: Number(item?.width || 0),
        height: Number(item?.height || 0),
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
    const type = segment?.type === 'reference' ? 'reference' : 'text'
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
    .map((edge) => {
      const source = directNodes.value.find((item) => item.id === edge.sourceId)
      const url = source?.generatedImage?.url || source?.media?.url || ''
      const previewUrl =
        source?.generatedImage?.url ||
        (source?.type === 'uploaded_asset' ? getUploadedImageSrc(source) : '') ||
        source?.media?.previewUrl ||
        source?.media?.thumbnailUrl ||
        url
      if (!previewUrl && !url) return null
      return {
        id: `edge:${edge.sourceId}`,
        source: 'edge',
        url,
        previewUrl,
        name: source?.title || source?.media?.name || '连线参考图',
        status: 'success',
        progress: 100,
        width: Number(source?.generatedImage?.width || source?.media?.width || 0),
        height: Number(source?.generatedImage?.height || source?.media?.height || 0)
      }
    })
    .filter(Boolean)
  const manual = normalizeManualReferenceImages(node?.referenceImages)
  const items = [...connected, ...manual]
  const order = Array.isArray(node?.referenceOrder) ? node.referenceOrder : []
  if (!order.length) return items

  const itemMap = new Map(items.map((item) => [item.id, item]))
  const ordered = order.map((id) => itemMap.get(id)).filter(Boolean)
  const orderedIds = new Set(ordered.map((item) => item.id))
  return [...ordered, ...items.filter((item) => !orderedIds.has(item.id))]
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

function getDirectNodeZIndex(node, index = 0) {
  const base = index + 1
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

async function runDirectImageNode(node) {
  const prompt = node.prompt.trim()
  if (!prompt) {
    showToast('请先输入图片提示词')
    return
  }
  if (hasPendingReferenceUploads(node.id)) {
    showToast('参考图还在上传中')
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
}

function failDirectImageGeneration(nodeId, message) {
  clearImageGenerationTimer(nodeId)
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
    media: patch.media || null,
    upload: patch.upload || null,
    imageModelId: patch.imageModelId || fallbackImageModelOptions[0].id,
    imageResolution: normalizeImageResolutionValue(patch.imageResolution),
    imageQuality: normalizeImageQualityValue(patch.imageQuality),
    aspectRatio: patch.aspectRatio || fallbackImageAspectRatioOptions[0],
    referenceImages: normalizeManualReferenceImages(patch.referenceImages),
    referenceOrder: Array.isArray(patch.referenceOrder) ? patch.referenceOrder : [],
    referenceMentions: normalizeReferenceMentions(patch.referenceMentions),
    generationStatus: patch.generationStatus || 'idle',
    generationMessage: patch.generationMessage || '',
    generationTaskId: patch.generationTaskId || '',
    generationRecordId: patch.generationRecordId || '',
    generatedImage: patch.generatedImage || null
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
  if (type === 'image_unit') return { width: 860, height: 690 }
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
    asset_table: '↥'
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
    asset_table: ['上传图片', '上传视频', '上传音频']
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
    asset_table: '上传图片、视频、音频文件，整理可复用素材。'
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
  idSet.forEach((id) => {
    revokeLocalPreviewForNode(id)
    uploadFileMap.delete(id)
    releaseUploadSignature(id)
    directNodeElements.delete(id)
    clearImageGenerationTimer(id)
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
  router.push({ name: 'home' })
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
