import { computed, ref } from 'vue'
import { defineStore } from 'pinia'
import {
  createSluvoProject,
  deleteSluvoProject,
  fetchSluvoProjectCanvas,
  fetchSluvoProjects,
  updateSluvoProject
} from '../api/sluvoApi'

export const useProjectStore = defineStore('project', () => {
  const projects = ref([])
  const activeProject = ref(null)
  const activeCanvas = ref(null)
  const activeNodes = ref([])
  const activeEdges = ref([])
  const loadingProjects = ref(false)
  const loadingWorkspace = ref(false)
  const creatingProject = ref(false)
  const error = ref('')

  const hasProjects = computed(() => projects.value.length > 0)

  async function loadProjects() {
    loadingProjects.value = true
    error.value = ''
    try {
      projects.value = await fetchSluvoProjects()
      return projects.value
    } catch (err) {
      error.value = err instanceof Error ? err.message : '项目加载失败'
      throw err
    } finally {
      loadingProjects.value = false
    }
  }

  async function createProjectFromPrompt(promptText = '') {
    creatingProject.value = true
    error.value = ''
    const prompt = promptText.trim()
    const title = buildPromptProjectTitle(prompt)

    try {
      const payload = await createSluvoProject({
        title,
        description: prompt || null,
        visibility: 'project_members',
        settings: {
          source: 'sluvo_home_prompt',
          initialPrompt: prompt
        }
      })
      if (payload?.project) {
        activeProject.value = payload.project
        projects.value = upsertProject(projects.value, payload.project)
      }
      if (payload?.canvas) activeCanvas.value = payload.canvas
      return payload
    } catch (err) {
      error.value = err instanceof Error ? err.message : '项目创建失败'
      throw err
    } finally {
      creatingProject.value = false
    }
  }

  async function openProject(projectId) {
    loadingWorkspace.value = true
    error.value = ''
    try {
      const workspace = await fetchSluvoProjectCanvas(projectId)
      setWorkspace(workspace)
      return workspace
    } catch (err) {
      error.value = err instanceof Error ? err.message : '画布加载失败'
      throw err
    } finally {
      loadingWorkspace.value = false
    }
  }

  async function renameActiveProject(title) {
    if (!activeProject.value?.id) return null
    const payload = await updateSluvoProject(activeProject.value.id, { title })
    if (payload?.project) {
      activeProject.value = payload.project
      projects.value = upsertProject(projects.value, payload.project)
    }
    return payload?.project || null
  }

  async function deleteProject(projectId) {
    if (!projectId) return null
    const payload = await deleteSluvoProject(projectId)
    projects.value = projects.value.filter((project) => project.id !== projectId)
    if (activeProject.value?.id === projectId) clearWorkspace()
    return payload
  }

  function setWorkspace(workspace) {
    activeProject.value = workspace?.project || null
    activeCanvas.value = workspace?.canvas || null
    activeNodes.value = Array.isArray(workspace?.nodes) ? workspace.nodes : []
    activeEdges.value = Array.isArray(workspace?.edges) ? workspace.edges : []
    if (workspace?.project) {
      projects.value = upsertProject(projects.value, workspace.project)
    }
  }

  function clearWorkspace() {
    activeProject.value = null
    activeCanvas.value = null
    activeNodes.value = []
    activeEdges.value = []
  }

  return {
    projects,
    activeProject,
    activeCanvas,
    activeNodes,
    activeEdges,
    loadingProjects,
    loadingWorkspace,
    creatingProject,
    error,
    hasProjects,
    loadProjects,
    createProjectFromPrompt,
    openProject,
    renameActiveProject,
    deleteProject,
    setWorkspace,
    clearWorkspace
  }
})

function buildPromptProjectTitle(prompt) {
  if (!prompt) return '未命名画布'
  return prompt.replace(/\s+/g, ' ').slice(0, 24)
}

function upsertProject(items, project) {
  const rest = items.filter((item) => item.id !== project.id)
  return [project, ...rest]
}
