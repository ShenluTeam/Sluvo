import { computed, ref } from 'vue'
import { defineStore } from 'pinia'

export const useCanvasStore = defineStore('canvas', () => {
  const selectedNodeIds = ref([])
  const viewport = ref({ x: 0, y: 0, zoom: 1 })
  const activePanel = ref('library')

  const primarySelectionId = computed(() => selectedNodeIds.value[0] || '')
  const selectionCount = computed(() => selectedNodeIds.value.length)

  function setSelection(ids) {
    selectedNodeIds.value = ids
  }

  function setViewport(nextViewport) {
    viewport.value = nextViewport
  }

  function setActivePanel(panel) {
    activePanel.value = panel
  }

  function clearSelection() {
    selectedNodeIds.value = []
  }

  return {
    selectedNodeIds,
    viewport,
    activePanel,
    primarySelectionId,
    selectionCount,
    setSelection,
    setViewport,
    setActivePanel,
    clearSelection
  }
})
