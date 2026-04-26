import { createRouter, createWebHistory } from 'vue-router'
import CanvasWorkspaceView from '../views/CanvasWorkspaceView.vue'

const router = createRouter({
  history: createWebHistory(),
  routes: [
    {
      path: '/',
      name: 'canvas',
      component: CanvasWorkspaceView
    },
    {
      path: '/projects/:projectId/canvas',
      redirect: '/'
    },
    {
      path: '/projects',
      redirect: '/'
    }
  ]
})

export default router
