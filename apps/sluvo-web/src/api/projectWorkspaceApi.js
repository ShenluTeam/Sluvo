import { createProjectSummaryList, getMockWorkspaceByProjectId } from '../mock/projects'

function wait(ms = 120) {
  return new Promise((resolve) => {
    window.setTimeout(resolve, ms)
  })
}

export async function fetchProjects() {
  await wait()
  return createProjectSummaryList()
}

export async function fetchProjectWorkspace(projectId) {
  await wait()
  return getMockWorkspaceByProjectId(projectId)
}
