<template>
  <!-- 右下角悬浮球：显示进行中任务数角标 + 平均进度，点击展开最后活跃面板 -->
  <transition name="fade-slide">
    <div v-if="totalActive > 0" class="task-float-ball" @click="handleExpand">
      <n-badge :value="totalActive" :max="99" class="float-badge">
        <div class="ball-inner">
          <n-progress
            type="circle"
            :percentage="displayProgress"
            :stroke-width="10"
            :show-indicator="false"
            style="width: 52px; height: 52px"
          />
          <div class="ball-center">
            <CatMascot :size="22" pose="walk" style="color: #a78bfa" />
          </div>
        </div>
      </n-badge>
      <div class="ball-label">{{ displayProgress }}%</div>
    </div>
  </transition>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import { useTaskProgressStore } from '@/stores/taskProgress'
import { useSceneProgressStore } from '@/stores/sceneProgress'
import CatMascot from './CatMascot.vue'

// 悬浮球优先展示最新任务进度，多任务显示数量角标
const taskStore = useTaskProgressStore()
const sceneStore = useSceneProgressStore()

const totalActive = computed(() => taskStore.activeCount + sceneStore.activeCount)

// 显示进度：优先 Case 任务，其次场景任务（取最新提交者）
const displayProgress = computed(() => {
  if (taskStore.activeCount > 0) return taskStore.latestProgress
  if (sceneStore.activeCount > 0) return sceneStore.latestProgress
  return 0
})

/** 点击展开最后活跃的进度面板 */
function handleExpand(): void {
  if (taskStore.lastActiveTaskNo && taskStore.tasks.has(taskStore.lastActiveTaskNo)) {
    taskStore.expand(taskStore.lastActiveTaskNo)
    return
  }
  const lastTask = [...taskStore.tasks.values()].pop()
  if (lastTask) {
    taskStore.expand(lastTask.taskNo)
    return
  }
  if (sceneStore.lastActiveExecNo && sceneStore.scenes.has(sceneStore.lastActiveExecNo)) {
    sceneStore.expand(sceneStore.lastActiveExecNo)
    return
  }
  const lastScene = [...sceneStore.scenes.values()].pop()
  if (lastScene) sceneStore.expand(lastScene.sceneExecNo)
}
</script>

<style scoped>
.task-float-ball {
  position: fixed;
  right: 28px;
  bottom: 28px;
  z-index: 3000;
  cursor: pointer;
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 4px;
  transition: transform 0.2s ease;
}
.task-float-ball:hover {
  transform: scale(1.06);
}
.ball-inner {
  position: relative;
  width: 56px;
  height: 56px;
  border-radius: 50%;
  background: rgba(26, 26, 46, 0.85);
  backdrop-filter: blur(8px);
  box-shadow: 0 6px 24px rgba(124, 58, 237, 0.4);
  display: flex;
  align-items: center;
  justify-content: center;
}
.ball-center {
  position: absolute;
  inset: 0;
  display: flex;
  align-items: center;
  justify-content: center;
}
.ball-label {
  font-size: 11px;
  color: #a78bfa;
  font-weight: 600;
}
</style>
