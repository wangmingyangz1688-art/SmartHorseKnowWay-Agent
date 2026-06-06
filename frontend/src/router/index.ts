/**
 * Vue Router 路由配置 — 本地活动规划助手
 */

import { createRouter, createWebHistory } from 'vue-router'
import type { RouteRecordRaw } from 'vue-router'

const routes: RouteRecordRaw[] = [
  {
    path: '/',
    name: 'Home',
    component: () => import('@/views/Home.vue'),
    meta: {
      title: '今天去哪玩？',
      transition: 'fade',
    },
  },
  {
    path: '/result',
    name: 'Result',
    component: () => import('@/views/Result.vue'),
    meta: {
      title: '活动方案',
      transition: 'slide-left',
    },
  },
  // 兼容旧路径（如果有人收藏了旧链接）
  {
    path: '/trip',
    redirect: '/',
  },
  {
    path: '/trip-result',
    redirect: '/',
  },
  // 404 兜底
  {
    path: '/:pathMatch(.*)*',
    name: 'NotFound',
    redirect: '/',
  },
]

const router = createRouter({
  history: createWebHistory(),
  routes,
  scrollBehavior(_to, _from, savedPosition) {
    // 浏览器后退时恢复滚动位置，否则回到顶部
    return savedPosition || { top: 0 }
  },
})

// 全局前置守卫：更新页面标题
router.beforeEach((to, _from, next) => {
  const title = (to.meta?.title as string) || '本地活动规划助手'
  document.title = `${title} | 活动规划助手`
  next()
})

export default router
