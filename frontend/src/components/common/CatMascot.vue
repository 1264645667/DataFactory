<template>
  <!-- 线条猫咪吉祥物（内联 SVG 自绘，支持多种姿态） -->
  <span class="cat-mascot" :style="{ width: sizeCss, height: sizeCss, display: 'inline-flex' }">
    <svg
      viewBox="0 0 120 120"
      fill="none"
      stroke="currentColor"
      stroke-width="3"
      stroke-linecap="round"
      stroke-linejoin="round"
      style="width: 100%; height: 100%"
    >
      <g :class="{ 'cat-breathe': pose !== 'walk', 'cat-walking': pose === 'walk' }">
        <!-- 耳朵 -->
        <path d="M36 34 L31 10 L54 24" />
        <path d="M84 34 L89 10 L66 24" />
        <!-- 头 -->
        <circle cx="60" cy="50" r="25" />

        <!-- 眼睛：按姿态切换 -->
        <template v-if="pose === 'sleep'">
          <path d="M44 48 Q50 53 56 48" />
          <path d="M64 48 Q70 53 76 48" />
        </template>
        <template v-else-if="pose === 'celebrate'">
          <path d="M44 50 Q50 43 56 50" />
          <path d="M64 50 Q70 43 76 50" />
        </template>
        <template v-else>
          <circle cx="50" cy="48" r="2.5" fill="currentColor" stroke="none" />
          <circle cx="70" cy="48" r="2.5" fill="currentColor" stroke="none" />
        </template>

        <!-- 鼻子 + 嘴 -->
        <path d="M57 56 L60 59 L63 56" />
        <path d="M60 59 Q56 63 53 60 M60 59 Q64 63 67 60" />
        <!-- 胡须 -->
        <path d="M34 50 L18 46 M34 56 L18 58 M86 50 L102 46 M86 56 L102 58" />

        <!-- 身体与四肢：按姿态切换 -->
        <template v-if="pose === 'walk'">
          <!-- 行走：横卧身体 + 四条腿 -->
          <ellipse cx="62" cy="88" rx="26" ry="13" />
          <path d="M44 96 L42 110" />
          <path d="M54 98 L54 110" />
          <path d="M70 98 L70 110" />
          <path d="M80 96 L82 110" />
          <path d="M88 84 C100 80 104 68 98 62" />
        </template>
        <template v-else>
          <!-- 坐姿身体 -->
          <path d="M35 108 C35 88 45 78 60 78 C75 78 85 88 85 108" />
          <path d="M52 108 L52 92" />
          <path d="M68 108 L68 92" />
          <!-- 尾巴 -->
          <path v-if="pose === 'sleep'" d="M85 102 C100 106 108 100 104 92" />
          <path v-else class="cat-tail" d="M85 104 C102 102 108 88 100 80" />
          <!-- 庆祝：举起的爪子 + 速度线 -->
          <template v-if="pose === 'celebrate'">
            <path d="M36 96 C28 92 24 82 27 74" />
            <path d="M20 66 L16 60" />
            <path d="M28 62 L26 54" />
          </template>
        </template>
      </g>

      <!-- 睡觉 Zzz -->
      <template v-if="pose === 'sleep'">
        <text x="88" y="34" font-size="13" fill="currentColor" stroke="none" class="cat-zzz">Z</text>
        <text x="98" y="22" font-size="10" fill="currentColor" stroke="none" class="cat-zzz" style="animation-delay: 0.8s">Z</text>
      </template>
    </svg>
  </span>
</template>

<script setup lang="ts">
import { computed } from 'vue'

// 猫咪吉祥物组件：size 支持数字(px)或 CSS 尺寸；pose 支持 坐/睡/走/庆祝/等待
const props = withDefaults(
  defineProps<{
    size?: number | string
    pose?: 'sit' | 'sleep' | 'walk' | 'celebrate' | 'wait'
  }>(),
  { size: 120, pose: 'sit' },
)

const sizeCss = computed(() => (typeof props.size === 'number' ? `${props.size}px` : props.size))
</script>
