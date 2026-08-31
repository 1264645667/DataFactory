<template>
  <!-- 造数快捷工具页（PRD 7.2）：卡片式瀑布流 + 名称搜索 -->
  <div class="tools-page">
    <div class="tools-header">
      <n-input v-model:value="keyword" size="small" clearable placeholder="按工具名称搜索" style="width: 260px">
        <template #prefix><n-icon><SearchOutline /></n-icon></template>
      </n-input>
    </div>
    <!-- 瀑布流布局 -->
    <div class="tools-masonry">
      <template v-for="tool in visibleTools" :key="tool.key">
        <component :is="tool.component" />
      </template>
    </div>
    <EmptyState v-if="visibleTools.length === 0" description="没有符合条件的工具，小猫在打盹～" />
  </div>
</template>

<script setup lang="ts">
import { computed, ref } from 'vue'
import { SearchOutline } from '@vicons/ionicons5'
import EmptyState from '@/components/common/EmptyState.vue'
import IdcardCard from './cards/IdcardCard.vue'
import PhoneCard from './cards/PhoneCard.vue'
import BankcardCard from './cards/BankcardCard.vue'
import NameCard from './cards/NameCard.vue'
import CreditCodeCard from './cards/CreditCodeCard.vue'
import TaxpayerCard from './cards/TaxpayerCard.vue'
import AddressCard from './cards/AddressCard.vue'
import DateCard from './cards/DateCard.vue'
import UuidCard from './cards/UuidCard.vue'
import SnowflakeCard from './cards/SnowflakeCard.vue'
import TimestampCard from './cards/TimestampCard.vue'
import Base64Card from './cards/Base64Card.vue'
import JsonFormatCard from './cards/JsonFormatCard.vue'
import SqlEscapeCard from './cards/SqlEscapeCard.vue'

// 14 个工具注册表
const TOOLS = [
  { key: 'idcard', name: '身份证号生成器', component: IdcardCard },
  { key: 'phone', name: '手机号生成器', component: PhoneCard },
  { key: 'bankcard', name: '银行卡号生成器', component: BankcardCard },
  { key: 'name', name: '随机姓名生成器', component: NameCard },
  { key: 'credit-code', name: '统一社会信用代码生成器', component: CreditCodeCard },
  { key: 'taxpayer-id', name: '纳税人识别号生成器', component: TaxpayerCard },
  { key: 'address', name: '随机地址生成器', component: AddressCard },
  { key: 'date', name: '日期批量生成器', component: DateCard },
  { key: 'uuid', name: 'UUID 批量生成器', component: UuidCard },
  { key: 'snowflake', name: '雪花 ID 生成器', component: SnowflakeCard },
  { key: 'timestamp', name: '时间戳转换工具', component: TimestampCard },
  { key: 'base64', name: 'Base64 编解码工具', component: Base64Card },
  { key: 'json', name: 'JSON 格式化工具', component: JsonFormatCard },
  { key: 'sql-escape', name: 'SQL 数据转义工具', component: SqlEscapeCard },
]

const keyword = ref('')

// 按工具名称搜索
const visibleTools = computed(() => {
  const kw = keyword.value.trim().toLowerCase()
  if (!kw) return TOOLS
  return TOOLS.filter((t) => t.name.toLowerCase().includes(kw))
})
</script>

<style scoped>
.tools-page {
  display: flex;
  flex-direction: column;
  gap: 16px;
}
.tools-header {
  display: flex;
  justify-content: flex-end;
}
/* CSS 多列瀑布流 */
.tools-masonry {
  column-count: 2;
  column-gap: 16px;
}
@media (max-width: 1200px) {
  .tools-masonry {
    column-count: 1;
  }
}
</style>
