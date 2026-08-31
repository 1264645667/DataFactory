<template>
  <!-- 全局暗色主题 + 中文语言包 -->
  <n-config-provider
    :theme="darkTheme"
    :theme-overrides="darkThemeOverrides"
    :locale="zhCN"
    :date-locale="dateZhCN"
  >
    <n-message-provider>
      <n-dialog-provider>
        <router-view />
        <!-- 登录过期重登弹窗（全局唯一，内部挂载 window.$message / $dialog） -->
        <ReloginModal />
      </n-dialog-provider>
    </n-message-provider>
  </n-config-provider>
</template>

<script setup lang="ts">
import { darkTheme, zhCN, dateZhCN } from 'naive-ui'
import { darkThemeOverrides } from '@/styles/theme'
import ReloginModal from '@/components/common/ReloginModal.vue'
</script>
