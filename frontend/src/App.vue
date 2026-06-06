<template>
  <div id="app">
    <router-view v-slot="{ Component, route }">
      <transition :name="route.meta.transition || 'fade'" mode="out-in">
        <component :is="Component" :key="route.path" />
      </transition>
    </router-view>
  </div>
</template>

<script setup lang="ts">
import { onMounted } from 'vue'

onMounted(() => {
  console.log('🎯 本地活动规划助手已启动')
})
</script>

<style>
/* ============================================================================
   全局重置 & 基础样式
   ============================================================================ */

*,
*::before,
*::after {
  margin: 0;
  padding: 0;
  box-sizing: border-box;
}

html {
  font-size: 16px;
  -webkit-font-smoothing: antialiased;
  -moz-osx-font-smoothing: grayscale;
  scroll-behavior: smooth;
}

body {
  font-family:
    -apple-system,
    BlinkMacSystemFont,
    'Segoe UI',
    'PingFang SC',
    'Hiragino Sans GB',
    'Microsoft YaHei',
    'Helvetica Neue',
    Arial,
    sans-serif;
  color: #1e293b;
  background: #f8fafc;
  line-height: 1.6;
  min-height: 100vh;
}

a {
  color: inherit;
  text-decoration: none;
}

button {
  font-family: inherit;
  border: none;
  outline: none;
  cursor: pointer;
}

input,
textarea,
select {
  font-family: inherit;
  outline: none;
}

img {
  max-width: 100%;
  display: block;
}

ul,
ol {
  list-style: none;
}

/* ============================================================================
   滚动条美化（WebKit）
   ============================================================================ */

::-webkit-scrollbar {
  width: 6px;
  height: 6px;
}

::-webkit-scrollbar-track {
  background: transparent;
}

::-webkit-scrollbar-thumb {
  background: #cbd5e1;
  border-radius: 3px;
}

::-webkit-scrollbar-thumb:hover {
  background: #94a3b8;
}

/* ============================================================================
   路由过渡动画
   ============================================================================ */

/* 默认 fade */
.fade-enter-active,
.fade-leave-active {
  transition: opacity 0.25s ease;
}

.fade-enter-from,
.fade-leave-to {
  opacity: 0;
}

/* slide-left：从右侧滑入（前进） */
.slide-left-enter-active,
.slide-left-leave-active {
  transition: all 0.3s ease;
}

.slide-left-enter-from {
  transform: translateX(30px);
  opacity: 0;
}

.slide-left-leave-to {
  transform: translateX(-30px);
  opacity: 0;
}

/* slide-right：从左侧滑入（后退） */
.slide-right-enter-active,
.slide-right-leave-active {
  transition: all 0.3s ease;
}

.slide-right-enter-from {
  transform: translateX(-30px);
  opacity: 0;
}

.slide-right-leave-to {
  transform: translateX(30px);
  opacity: 0;
}

/* ============================================================================
   通用工具类
   ============================================================================ */

.text-center {
  text-align: center;
}

.text-muted {
  color: #94a3b8;
}

.mt-1 { margin-top: 4px; }
.mt-2 { margin-top: 8px; }
.mt-3 { margin-top: 12px; }
.mt-4 { margin-top: 16px; }

.mb-1 { margin-bottom: 4px; }
.mb-2 { margin-bottom: 8px; }
.mb-3 { margin-bottom: 12px; }
.mb-4 { margin-bottom: 16px; }

/* ============================================================================
   移动端全局优化
   ============================================================================ */

@media (max-width: 640px) {
  html {
    font-size: 15px;
  }

  body {
    -webkit-tap-highlight-color: transparent;
    -webkit-touch-callout: none;
  }
}
</style>
