<template>
  <!-- 空状态：猫咪睡觉插画 + 文案 + 可选操作按钮 -->
  <div class="empty-state">
    <CatMascot pose="sleep" :size="size" style="color: #7c6aa8" />
    <p class="empty-desc">{{ description }}</p>
    <p v-if="hint" class="empty-hint">{{ hint }}</p>
    <n-button v-if="buttonText" class="gradient-btn mt-3" @click="emit('action')">
      {{ buttonText }}
    </n-button>
  </div>
</template>

<script setup lang="ts">
import CatMascot from './CatMascot.vue'

withDefaults(
  defineProps<{
    description?: string
    hint?: string
    buttonText?: string
    size?: number
  }>(),
  {
    description: '暂无数据，小猫在打盹～',
    hint: '',
    buttonText: '',
    size: 110,
  },
)

const emit = defineEmits<{ (e: 'action'): void }>()
</script>

<style scoped>
.empty-state {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  padding: 48px 16px;
  text-align: center;
}
.empty-desc {
  margin: 12px 0 0;
  color: #94a3b8;
  font-size: 14px;
}
.empty-hint {
  margin: 6px 0 0;
  color: #64748b;
  font-size: 12px;
}
</style>
