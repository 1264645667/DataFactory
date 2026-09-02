<template>
  <!-- 主布局：侧边栏 + 顶栏 + 内容区；全局挂载进度面板 / 悬浮球 / 离线通知条 -->
  <div class="app-layout">
    <SideBar />
    <div class="app-main">
      <TopBar />
      <!-- 网络断开通知条 -->
      <n-alert v-if="offline" type="warning" closable class="offline-bar" @close="offline = false">
        网络连接已断开，部分功能不可用
      </n-alert>
      <div class="app-content">
        <!-- key 绑定路由路径确保组件重新渲染 -->
        <router-view :key="route.path" />
      </div>
    </div>

    <!-- 全局任务进度面板（可多个并存） -->
    <template v-for="[taskNo, entry] of taskStore.tasks" :key="taskNo">
      <TaskProgressPanel v-if="entry.panelVisible" :task-no="taskNo" />
    </template>
    <!-- 全局场景进度面板 -->
    <template v-for="[execNo, entry] of sceneStore.scenes" :key="execNo">
      <SceneProgressPanel v-if="entry.panelVisible" :scene-exec-no="execNo" />
    </template>
    <!-- 右下角悬浮球 -->
    <TaskFloatBall />
  </div>
</template>

<script setup lang="ts">
import { onBeforeUnmount, onMounted, ref } from 'vue'
import { useRoute } from 'vue-router'
import SideBar from './SideBar.vue'
import TopBar from './TopBar.vue'
import TaskProgressPanel from '@/components/common/TaskProgressPanel.vue'
import SceneProgressPanel from '@/components/common/SceneProgressPanel.vue'
import TaskFloatBall from '@/components/common/TaskFloatBall.vue'
import { useTaskProgressStore } from '@/stores/taskProgress'
import { useSceneProgressStore } from '@/stores/sceneProgress'

const route = useRoute()
const taskStore = useTaskProgressStore()
const sceneStore = useSceneProgressStore()

// 网络状态监听
const offline = ref(false)

function handleOffline(): void {
  offline.value = true
}

onMounted(() => window.addEventListener('offline', handleOffline))
onBeforeUnmount(() => window.removeEventListener('offline', handleOffline))
</script>

<style scoped>
.app-layout {
  display: flex;
  height: 100vh;
  overflow: hidden;
}
.app-main {
  flex: 1;
  display: flex;
  flex-direction: column;
  overflow: hidden;
}
.offline-bar {
  border-radius: 0;
}
.app-content {
  flex: 1;
  overflow-y: auto;
  padding: 20px 24px;
}
</style>
