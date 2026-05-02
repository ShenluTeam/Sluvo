import { createRouter, createWebHistory } from 'vue-router'
import CanvasWorkspaceView from '../views/CanvasWorkspaceView.vue'
import HomeView from '../views/HomeView.vue'
import LoginView from '../views/LoginView.vue'

const router = createRouter({
  history: createWebHistory(),
  routes: [
    {
      path: '/',
      name: 'home',
      component: HomeView
    },
    {
      path: '/login',
      name: 'login',
      component: LoginView
    },
    {
      path: '/projects/:projectId/canvas',
      name: 'canvas',
      component: CanvasWorkspaceView,
      meta: { requiresAuth: true }
    },
    {
      path: '/projects',
      name: 'projects',
      component: HomeView,
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
