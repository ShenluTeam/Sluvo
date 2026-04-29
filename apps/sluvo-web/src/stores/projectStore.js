import { computed, ref } from 'vue'
import { defineStore } from 'pinia'
import { fetchProjects, fetchProjectWorkspace } from '../api/projectWorkspaceApi'
import { availableNodeTemplates, getNodeTemplate } from '../mock/projects'

const defaultInspectorDetails = {
  source: '画布内草稿',
  references: '尚未绑定引用',
  models: '尚未配置',
  history: '本地创建'
}

function createNodeData(type, index) {
  const template = getNodeTemplate(type)

  return {
    nodeType: type,
    title: `${template.label} ${index}`,
    body: '新建画布节点。可以在右侧检查器中编辑提示词、来源和引用。',
    status: 'draft',
    icon: template.icon,
    kindLabel: template.label,
    accent: template.accent,
    tags: ['新建'],
    metrics: [],
    portLabels: {
      in: '输入',
      out: '输出'
    },
    details: {
      ...defaultInspectorDetails
    }
  }
}

export const useProjectStore = defineStore('project', () => {
  const projects = ref([])
  const activeProject = ref(null)
  const workspace = ref(null)
  const loadingProjects = ref(false)
  const loadingWorkspace = ref(false)
  const error = ref('')

  const hasSelection = computed(() => workspace.value?.canvas?.nodes?.length > 0)

  async function loadProjects() {
    loadingProjects.value = true
    error.value = ''

    try {
      projects.value = await fetchProjects()
    } catch (err) {
      error.value = err instanceof Error ? err.message : '项目加载失败'
    } finally {
      loadingProjects.value = false
    }
  }

  async function openProject(projectId) {
    loadingWorkspace.value = true
    error.value = ''

    try {
      const nextWorkspace = await fetchProjectWorkspace(projectId)
      activeProject.value = nextWorkspace.project
      workspace.value = nextWorkspace
    } catch (err) {
      error.value = err instanceof Error ? err.message : '工作区加载失败'
    } finally {
      loadingWorkspace.value = false
    }
  }

  function setNodes(nodes) {
    if (!workspace.value) return
    workspace.value.canvas.nodes = nodes
  }

  function setEdges(edges) {
    if (!workspace.value) return
    workspace.value.canvas.edges = edges
  }

  function addNode(type, position) {
    if (!workspace.value) return null

    const index = workspace.value.canvas.nodes.filter((node) => node.data.nodeType === type).length + 1
    const id = `${type}-${Date.now()}`
    const node = {
      id,
      type: 'workflowNode',
      position,
      data: createNodeData(type, index)
    }

    workspace.value.canvas.nodes = [...workspace.value.canvas.nodes, node]
    return node
  }

  function deleteNodes(nodeIds) {
    if (!workspace.value || nodeIds.length === 0) return

    const nodeIdSet = new Set(nodeIds)
    workspace.value.canvas.nodes = workspace.value.canvas.nodes.filter((node) => !nodeIdSet.has(node.id))
    workspace.value.canvas.edges = workspace.value.canvas.edges.filter(
      (edge) => !nodeIdSet.has(edge.source) && !nodeIdSet.has(edge.target)
    )
  }

  function updateNodeContent(nodeId, patch) {
    if (!workspace.value) return

    workspace.value.canvas.nodes = workspace.value.canvas.nodes.map((node) => {
      if (node.id !== nodeId) {
        return node
      }

      return {
        ...node,
        data: {
          ...node.data,
          ...patch,
          details: {
            ...node.data.details,
            ...(patch.details || {})
          }
        }
      }
    })
  }

  return {
    projects,
    activeProject,
    workspace,
    loadingProjects,
    loadingWorkspace,
    error,
    hasSelection,
    availableNodeTemplates,
    loadProjects,
    openProject,
    setNodes,
    setEdges,
    addNode,
    deleteNodes,
    updateNodeContent
  }
})
