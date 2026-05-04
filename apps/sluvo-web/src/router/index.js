import { createRouter, createWebHistory } from 'vue-router'
import CanvasWorkspaceView from '../views/CanvasWorkspaceView.vue'
import CommunityCanvasView from '../views/CommunityCanvasView.vue'
import HomeView from '../views/HomeView.vue'
import LoginView from '../views/LoginView.vue'
import ProjectListView from '../views/ProjectListView.vue'
import TrashView from '../views/TrashView.vue'

const router = createRouter({
  history: createWebHistory(),
  scrollBehavior(to) {
    if (to.hash) {
      return {
        el: to.hash,
        behavior: 'smooth'
      }
    }
    return { top: 0 }
  },
  routes: [
    {
      path: '/',
      name: 'home',
      component: HomeView
    },
    {
      path: '/workspace',
      name: 'workspace',
      component: HomeView,
      meta: { requiresAuth: true }
    },
    {
      path: '/login',
      name: 'login',
      component: LoginView
    },
    {
      path: '/register',
      name: 'register',
      component: LoginView
    },
    {
      path: '/projects/:projectId/canvas',
      name: 'canvas',
      component: CanvasWorkspaceView,
      meta: { requiresAuth: true }
    },
    {
      path: '/community/canvases/:publicationId',
      name: 'community-canvas-detail',
      component: CommunityCanvasView,
      meta: { requiresAuth: true }
    },
    {
      path: '/projects',
      name: 'projects',
      component: ProjectListView,
      meta: { requiresAuth: true }
    },
    {
      path: '/trash',
      name: 'trash',
      component: TrashView,
      meta: { requiresAuth: true }
    }
  ]
})

router.beforeEach((to) => {
  if (!to.meta.requiresAuth) return true
  const token = window.localStorage.getItem('shenlu_token') || ''
  if (token) return true

  return {
    name: 'login',
    query: {
      redirect: to.fullPath
    }
  }
})

export default router
