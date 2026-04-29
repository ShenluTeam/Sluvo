<template>
  <div class="libtv-canvas-shell" :class="{ 'is-space-panning': spacePanning }" @click="closeFloatingPanels">
    <section
      ref="canvasFrame"
      class="libtv-canvas-frame"
      tabindex="-1"
      @keydown.capture="handleCanvasKeyEvent"
      @keyup.capture="handleCanvasKeyEvent"
      @pointerdown.capture="handleFramePointerDown"
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
        </svg>

        <article
          v-for="node in directNodes"
          :key="node.id"
          :ref="(element) => registerDirectNodeElement(node.id, element)"
          class="direct-workflow-node"
          :class="[`direct-workflow-node--${node.type}`, { 'is-selected': selectedDirectNodeIds.includes(node.id) }]"
          :style="{ left: `${node.x}px`, top: `${node.y}px` }"
          :data-direct-node-id="node.id"
          draggable="false"
          tabindex="0"
          @click.stop
          @dragstart.prevent
          @selectstart.prevent
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
            <button class="direct-workflow-node__port direct-workflow-node__port--left magnetic-target" type="button">+</button>
            <button
              class="direct-workflow-node__port direct-workflow-node__port--right magnetic-target"
              type="button"
              draggable="false"
              @pointerdown.stop.prevent="startDirectConnection($event, node.id)"
              @mousedown.stop.prevent="startDirectConnection($event, node.id)"
            >
              +
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
              <div v-if="node.upload?.status === 'uploading'" class="uploaded-asset__state">
                <span>上传中 {{ node.upload.progress }}%</span>
                <div class="uploaded-asset__progress">
                  <span :style="{ width: `${node.upload.progress}%` }" />
                </div>
              </div>
              <div v-else-if="node.upload?.status === 'success' && node.media?.kind === 'image'" class="uploaded-asset__preview">
                <img :src="node.media.url" :alt="node.media.name" draggable="false" />
              </div>
              <div v-else-if="node.upload?.status === 'success' && node.media?.kind === 'video'" class="uploaded-asset__preview">
                <video :src="node.media.url" controls />
              </div>
              <div v-else-if="node.upload?.status === 'success' && node.media?.kind === 'audio'" class="uploaded-asset__audio">
                <Music2 :size="42" />
                <strong>{{ node.media.name }}</strong>
                <audio :src="node.media.url" controls />
              </div>
              <div v-else class="uploaded-asset__state">上传成功</div>
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

          <div v-if="node.type !== 'uploaded_asset'" class="direct-workflow-node__prompt">{{ node.prompt }}</div>
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
        @keydown.stop.prevent="handleDeleteSinkKey"
        @keyup.stop.prevent="handleDeleteSinkKey"
      />

      <input
        ref="uploadInput"
        class="hidden-upload-input"
        type="file"
        accept="image/*,video/*,audio/*"
        @change="handleUploadInputChange"
      />

      <CommandBar :title="copy.untitled" />

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
        <button type="button" @click="duplicateSelection">{{ copy.duplicate }}</button>
        <button type="button" @click="groupSelection">{{ copy.group }}</button>
        <button type="button" @click="deleteSelection">{{ copy.delete }}</button>
      </div>

      <div v-if="helpVisible" class="canvas-help-panel" @click.stop>
        <strong>{{ copy.helpTitle }}</strong>
        <span>{{ copy.helpAdd }}</span>
        <span>{{ copy.helpPan }}</span>
        <span>{{ copy.helpSelect }}</span>
        <span>{{ copy.helpCopy }}</span>
        <span>{{ copy.helpZoom }}</span>
      </div>

      <div v-if="toastMessage" class="canvas-toast">{{ toastMessage }}</div>
    </section>
  </div>
</template>

<script setup>
import { computed, nextTick, onBeforeUnmount, onMounted, reactive, ref, watch } from 'vue'
import { MarkerType, VueFlow, useVueFlow } from '@vue-flow/core'
import { Background } from '@vue-flow/background'
import { ArrowUpDown, ListChecks, Minus, Music2, Plus, Upload, X } from 'lucide-vue-next'
import CommandBar from '../components/layout/CommandBar.vue'
import AddNodeMenu from '../components/canvas/AddNodeMenu.vue'
import CanvasBottomControls from '../components/canvas/CanvasBottomControls.vue'
import CanvasToolRail from '../components/canvas/CanvasToolRail.vue'
import StarterSkillStrip from '../components/canvas/StarterSkillStrip.vue'
import WorkflowEdge from '../canvas/edges/WorkflowEdge.vue'
import WorkflowNode from '../canvas/nodes/WorkflowNode.vue'
import { useCanvasStore } from '../stores/canvasStore'


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

const canvasStore = useCanvasStore()
const canvasFrame = ref(null)
const deleteKeySink = ref(null)
const uploadInput = ref(null)
const directNodeElements = new Map()
let previousDocumentKeydown = null
let previousWindowKeydown = null
let frameResizeObserver = null
let uploadTimer = null
let undoShortcutLocked = false
let lastUndoShortcutAt = 0
const nodes = ref([])
const edges = ref([])
const directNodes = ref([])
const directEdges = ref([])
const selectedDirectNodeIds = ref([])
const focusedDirectNodeId = ref('')
const activeDirectNodeId = ref('')
const lastTouchedDirectNodeId = ref('')
const gridVisible = ref(true)
const snapEnabled = ref(true)
const minimapVisible = ref(true)
const helpVisible = ref(false)
const activeRailPanel = ref('')
const activeAssetLibrary = ref('assets')
const activeAssetTab = ref('全部')
const activeHistoryTab = ref('image')
const historyBatchMode = ref(false)
const historySortAscending = ref(false)
const pendingUploadFlowPosition = ref(null)
const replacingUploadNodeId = ref('')
const toastMessage = ref('')
const historyStack = ref([])
const clipboardNodes = ref([])
const clipboardEdges = ref([])
const suppressHistory = ref(false)
const spacePanning = ref(false)
const selectedEdgeIds = ref([])
const canvasActivated = ref(false)
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
const directConnection = reactive({
  active: false,
  sourceId: '',
  start: { x: 0, y: 0 },
  current: { x: 0, y: 0 }
})
const pendingDirectConnection = reactive({
  sourceId: '',
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
const zoomLabel = computed(() => `${Math.round((viewport.value?.zoom || 1) * 100)}%`)
const showStarterStrip = computed(
  () =>
    !canvasActivated.value &&
    nodes.value.length === 0 &&
    directNodes.value.length === 0 &&
    !addMenu.visible &&
    !activeRailPanel.value
)
const directLayerStyle = computed(() => ({
  transform: `translate(${viewport.value?.x || 0}px, ${viewport.value?.y || 0}px) scale(${viewport.value?.zoom || 1})`
}))
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
  },
  { deep: true }
)

watch(
  directNodes,
  () => {
    if (nodes.value.length === 0 && directNodes.value.length === 0) {
      canvasActivated.value = false
    }
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
  window.addEventListener('keydown', handleWindowKeyEvent, true)
  window.addEventListener('keyup', handleWindowKeyEvent, true)
  window.addEventListener('keydown', handleKeydown)
  window.addEventListener('keyup', handleKeyup)
  window.addEventListener('pointermove', handleWindowPointerMove)
  window.addEventListener('pointerup', handleWindowPointerUp)
  window.addEventListener('mousemove', handleWindowPointerMove)
  window.addEventListener('mouseup', handleWindowPointerUp)
  window.addEventListener('mouseleave', resetHoverEffects)
  updateFrameSize()
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
  window.removeEventListener('keydown', handleWindowKeyEvent, true)
  window.removeEventListener('keyup', handleWindowKeyEvent, true)
  window.removeEventListener('keydown', handleKeydown)
  window.removeEventListener('keyup', handleKeyup)
  window.removeEventListener('pointermove', handleWindowPointerMove)
  window.removeEventListener('pointerup', handleWindowPointerUp)
  window.removeEventListener('mousemove', handleWindowPointerMove)
  window.removeEventListener('mouseup', handleWindowPointerUp)
  window.removeEventListener('mouseleave', resetHoverEffects)
  frameResizeObserver?.disconnect()
  window.clearInterval(uploadTimer)
  resetHoverEffects()
})

function handleDocumentKeydown(event) {
  if (handleGlobalUndoShortcut(event)) return
  if (!isDeleteKey(event) || shouldIgnoreDeleteEventTarget(event.target)) return
  if (deleteActiveDirectNodes(event)) return
}

function handleDocumentKeyup(event) {
  releaseUndoShortcut(event)
  if (!isDeleteKey(event) || shouldIgnoreDeleteEventTarget(event.target)) return
  deleteActiveDirectNodes(event)
}

function handleWindowKeyEvent(event) {
  if (!isDeleteKey(event) || shouldIgnoreDeleteEventTarget(event.target)) return
  deleteLastTouchedDirectNode(event)
}

function handleCanvasKeyEvent(event) {
  if (handleGlobalUndoShortcut(event)) return
  if (!isDeleteKey(event) || shouldIgnoreDeleteEventTarget(event.target)) return
  deleteLastTouchedDirectNode(event)
}

function handleGlobalDeleteShortcut(event) {
  if (handleGlobalUndoShortcut(event)) {
    return false
  }

  if (isDeleteKey(event) && !shouldIgnoreDeleteEventTarget(event.target) && deleteLastTouchedDirectNode(event)) {
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
    event.shiftKey ||
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
    undoLastChange()
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

function shouldIgnoreDeleteEventTarget(target) {
  return isTypingTarget(target) && !(target instanceof HTMLElement && target.classList.contains('delete-key-sink'))
}

function deleteActiveDirectNodes(event) {
  const targetNodeId = getDirectNodeIdFromEvent(event)
  const ids = new Set(targetNodeId ? [targetNodeId] : selectedDirectNodeIds.value)
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
  if (!isDeleteKey(event)) return
  if (!deleteLastTouchedDirectNode(event) && directNodes.value.length > 0) {
    event.preventDefault()
    event.stopPropagation()
    event.stopImmediatePropagation?.()
    const fallbackId = activeDirectNodeId.value || selectedDirectNodeIds.value[0] || focusedDirectNodeId.value || lastTouchedDirectNodeId.value
    if (fallbackId) deleteDirectNodesByIds([fallbackId])
  }
}

function handleDeleteSinkNative(event) {
  if (!isDeleteKey(event)) return
  if (!deleteLastTouchedDirectNode(event) && directNodes.value.length > 0) {
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

  if (command && event.key.toLowerCase() === 'v') {
    event.preventDefault()
    pasteSelection()
    return
  }

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
  return target instanceof HTMLElement && ['INPUT', 'TEXTAREA', 'SELECT'].includes(target.tagName)
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
  selectionBox.active = true
  selectionBox.start = { x: event.clientX, y: event.clientY }
  selectionBox.current = { x: event.clientX, y: event.clientY }
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
    return
  }

  if (!selectionBox.active) return

  const rect = getSelectionRect()
  selectedDirectNodeIds.value = directNodes.value
    .filter((node) => intersectsRect(rect, getDirectNodeScreenRect(node)))
    .map((node) => node.id)
  activeDirectNodeId.value = selectedDirectNodeIds.value.at(-1) || ''
  focusedDirectNodeId.value = activeDirectNodeId.value
  lastTouchedDirectNodeId.value = activeDirectNodeId.value
  if (activeDirectNodeId.value) focusDeleteKeySink()
  selectionBox.active = false
}

function startDirectConnection(event, nodeId) {
  if (event.pointerId !== undefined) {
    event.target?.setPointerCapture?.(event.pointerId)
  }
  const sourceNode = directNodes.value.find((node) => node.id === nodeId)
  if (!sourceNode) return

  const start = getDirectNodePortPosition(sourceNode, 'right')
  directConnection.active = true
  directConnection.sourceId = nodeId
  directConnection.start = start
  directConnection.current = screenToFlowCoordinate({ x: event.clientX, y: event.clientY })
  pendingDirectConnection.sourceId = nodeId
  pendingDirectConnection.point = directConnection.current
  selectedDirectNodeIds.value = [nodeId]
  activeDirectNodeId.value = nodeId
  lastTouchedDirectNodeId.value = nodeId
}

function finishDirectConnection(event) {
  const point = { ...directConnection.current }
  const sourceId = directConnection.sourceId
  const targetId = findDirectConnectionTarget(event, sourceId, point)
  pendingDirectConnection.sourceId = directConnection.sourceId
  pendingDirectConnection.point = point
  directConnection.active = false

  if (targetId) {
    rememberHistory()
    directEdges.value = upsertDirectEdge(sourceId, targetId)
    pendingDirectConnection.sourceId = ''
    selectedDirectNodeIds.value = [targetId]
    activeDirectNodeId.value = targetId
    focusedDirectNodeId.value = targetId
    lastTouchedDirectNodeId.value = targetId
    showToast('\u5df2\u8fde\u63a5\u8282\u70b9')
    return
  }

  const screen = flowToScreenCoordinate(point)
  referenceMenu.visible = true
  referenceMenu.sourceId = ''
  referenceMenu.sourceHandle = 'direct'
  referenceMenu.screen = clampMenuPosition({ x: screen.x + 20, y: screen.y - 150 }, 300, 460)
  referenceMenu.flow = point
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
      sourceId,
      targetId
    }
  ]
}

function getDirectEdgePath(edge) {
  const sourceNode = directNodes.value.find((node) => node.id === edge.sourceId)
  const targetNode = directNodes.value.find((node) => node.id === edge.targetId)
  if (!sourceNode || !targetNode) return ''

  return buildDirectCurvePath(getDirectNodePortPosition(sourceNode, 'right'), getDirectNodePortPosition(targetNode, 'left'))
}

function getDraftEdgePath() {
  return buildDirectCurvePath(directConnection.start, directConnection.current)
}

function buildDirectCurvePath(source, target) {
  if (!source || !target) return ''

  const distance = Math.max(140, Math.abs(target.x - source.x) * 0.5)
  const sourceControlX = source.x + distance
  const targetControlX = target.x - distance

  return `M ${source.x} ${source.y} C ${sourceControlX} ${source.y}, ${targetControlX} ${target.y}, ${target.x} ${target.y}`
}

function getDirectNodePortPosition(node, side) {
  const size = getDirectNodeSize(node.type)
  const titleHeight = 26
  const frameHeight = node.type === 'uploaded_asset' ? size.height - titleHeight - 8 : 438

  return {
    x: side === 'right' ? node.x + size.width : node.x,
    y: node.y + titleHeight + frameHeight / 2
  }
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
  const zoom = viewport.value?.zoom || 1
  return {
    x: (viewport.value?.x || 0) + node.x * zoom,
    y: (viewport.value?.y || 0) + node.y * zoom,
    width: getDirectNodeSize(node.type).width * zoom,
    height: getDirectNodeSize(node.type).height * zoom
  }
}

function intersectsRect(a, b) {
  return a.x < b.x + b.width && a.x + a.width > b.x && a.y < b.y + b.height && a.y + a.height > b.y
}

function handlePaneClick() {
  closeFloatingPanels()
  canvasStore.clearSelection()
  selectedDirectNodeIds.value = []
}

function handlePaneContextMenu(event) {
  event.preventDefault()
  openAddMenuAtEvent(event)
}

function handleNodeContextMenu({ event, node }) {
  event.preventDefault()
  closeAddMenu()
  selectOnly(node.id)
  contextMenu.visible = true
  contextMenu.screen = clampMenuPosition({ x: event.clientX, y: event.clientY }, 180, 132)
  contextMenu.flow = screenToFlowCoordinate({ x: event.clientX, y: event.clientY })
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

  openAddMenuAtEvent(event)
}

function openAddMenuFromButton(event) {
  event.stopPropagation()
  const buttonRect = event.currentTarget?.getBoundingClientRect?.()
  const screen = buttonRect
    ? { x: buttonRect.right + 14, y: buttonRect.top - 2 }
    : { x: 104, y: 76 }
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
  }
}

function closeAddMenu() {
  addMenu.visible = false
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
    const createdNode = createDirectNodeAtFlow(item.type, pendingDirectConnection.point, item.patch)
    directEdges.value = upsertDirectEdge(pendingDirectConnection.sourceId, createdNode.id)
    pendingDirectConnection.sourceId = ''
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
  nextTick(() => {
    if (!uploadInput.value) return
    uploadInput.value.value = ''
    uploadInput.value.click()
  })
}

function replaceUploadedNode(nodeId) {
  const node = directNodes.value.find((item) => item.id === nodeId)
  if (!node) return
  pendingUploadFlowPosition.value = { x: node.x, y: node.y }
  replacingUploadNodeId.value = nodeId
  openUploadDialog()
}

function handleUploadInputChange(event) {
  const file = event.target?.files?.[0]
  if (!file) return

  const kind = getUploadKind(file)
  if (!kind) {
    showToast('请选择图片、视频或音频文件')
    return
  }

  const url = URL.createObjectURL(file)
  const media = {
    kind,
    url,
    name: file.name,
    mime: file.type,
    width: 1459,
    height: 2117
  }

  if (kind === 'image') {
    readImageDimensions(url).then((dimensions) => {
      if (dimensions) updateUploadedNodeMedia(url, dimensions)
    })
  } else if (kind === 'video') {
    readVideoDimensions(url).then((dimensions) => {
      if (dimensions) updateUploadedNodeMedia(url, dimensions)
    })
  }

  rememberHistory()
  canvasActivated.value = true

  const existingId = replacingUploadNodeId.value
  let nodeId = existingId

  if (existingId) {
    directNodes.value = directNodes.value.map((node) =>
      node.id === existingId
        ? {
            ...node,
            title: getUploadedAssetTitle(kind),
            icon: getUploadedAssetIcon(kind),
            media,
            upload: { status: 'uploading', progress: 8 }
          }
        : node
    )
  } else {
    const position = pendingUploadFlowPosition.value || getViewportCenter()
    const node = createDirectNodeAtFlow('uploaded_asset', position, {
      title: getUploadedAssetTitle(kind),
      icon: getUploadedAssetIcon(kind),
      media,
      upload: { status: 'uploading', progress: 8 }
    })
    nodeId = node.id
  }

  selectedDirectNodeIds.value = [nodeId]
  activeDirectNodeId.value = nodeId
  focusedDirectNodeId.value = nodeId
  lastTouchedDirectNodeId.value = nodeId
  pendingUploadFlowPosition.value = null
  replacingUploadNodeId.value = ''
  simulateUploadProgress(nodeId)
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

function simulateUploadProgress(nodeId) {
  window.clearInterval(uploadTimer)
  uploadTimer = window.setInterval(() => {
    const node = directNodes.value.find((item) => item.id === nodeId)
    if (!node) {
      window.clearInterval(uploadTimer)
      return
    }

    const progress = Math.min((node.upload?.progress || 0) + 14, 100)
    directNodes.value = directNodes.value.map((item) =>
      item.id === nodeId
        ? {
            ...item,
            upload: {
              ...item.upload,
              status: progress >= 100 ? 'success' : 'uploading',
              progress
            }
          }
        : item
    )

    if (progress >= 100) {
      window.clearInterval(uploadTimer)
      showToast('上传成功')
    }
  }, 160)
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
    video.onloadedmetadata = () => resolve({ width: video.videoWidth, height: video.videoHeight })
    video.onerror = () => resolve(null)
    video.src = url
  })
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
    type,
    title: patch.numberedTitle ? `${patch.title || meta.title} ${count}` : patch.title || `${meta.title} ${count}`,
    icon: patch.icon || getDirectNodeIcon(type),
    x: flowPosition.x,
    y: flowPosition.y,
    actions: getDirectNodeActions(type),
    prompt: getDirectNodePrompt(type),
    media: patch.media || null,
    upload: patch.upload || null
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
  const stepX = 620
  const stepY = 120
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
  if (type === 'uploaded_asset') return { width: 370, height: 560 }
  if (type === 'image_unit') return { width: 780, height: 640 }
  if (type === 'video_unit' || type === 'media_board') return { width: 560, height: 600 }
  return { width: 440, height: 640 }
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

function getDirectNodePrompt(type) {
  const prompts = {
    prompt_note: '写下你想讲的故事、场景或角色设定。例如：一个来自未来的机器人，在城市屋顶看星星。',
    image_unit: '描述你想要生成的画面内容，按 / 呼出指令，@ 引用素材',
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
  idSet.forEach((id) => directNodeElements.delete(id))
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
  selectedDirectNodeIds.value = [nodeId]
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
}

function rememberHistory() {
  if (suppressHistory.value) return
  historyStack.value.push({
    nodes: cloneCanvasValue(nodes.value),
    edges: cloneCanvasValue(edges.value),
    directNodes: cloneCanvasValue(directNodes.value),
    directEdges: cloneCanvasValue(directEdges.value)
  })
  if (historyStack.value.length > 40) historyStack.value.shift()
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

  suppressHistory.value = true
  nodes.value = previous.nodes
  edges.value = previous.edges
  directNodes.value = previous.directNodes || []
  directEdges.value = previous.directEdges || []
  canvasStore.clearSelection()
  selectedEdgeIds.value = []
  selectedDirectNodeIds.value = []
  focusedDirectNodeId.value = ''
  activeDirectNodeId.value = ''
  lastTouchedDirectNodeId.value = ''
  nextTick(() => {
    suppressHistory.value = false
  })
  showToast('\u5df2\u64cd\u4f5c')
}

function getViewportCenter() {
  return screenToFlowCoordinate({
    x: window.innerWidth / 2,
    y: window.innerHeight / 2
  })
}

function clampMenuPosition(screen, menuWidth, menuHeight) {
  const padding = 8
  const rect = canvasFrame.value?.getBoundingClientRect?.()
  const bounds = rect || { left: 0, top: 0, right: window.innerWidth, bottom: window.innerHeight }
  const maxX = bounds.right - menuWidth - padding
  const maxY = bounds.bottom - menuHeight - padding
  return {
    x: Math.min(Math.max(screen.x, bounds.left + padding), Math.max(bounds.left + padding, maxX)),
    y: Math.min(Math.max(screen.y, bounds.top + padding), Math.max(bounds.top + padding, maxY))
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
