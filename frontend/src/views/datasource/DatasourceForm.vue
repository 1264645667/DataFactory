<template>
  <!-- 新增/编辑数据源表单弹窗（PRD 8.3） -->
  <n-modal :show="show" preset="card" :title="isEdit ? '编辑数据源' : '新增数据源'" style="width: 560px" @update:show="close">
    <n-form ref="formRef" :model="form" :rules="rules" label-placement="left" label-width="90px" size="small">
      <n-form-item label="数据源名称" path="name">
        <n-input v-model:value="form.name" placeholder="1~50 字，全局唯一" />
      </n-form-item>
      <n-form-item label="数据库类型" path="db_type">
        <n-select v-model:value="form.db_type" :options="[{ label: 'MySQL', value: 'MySQL' }]" disabled />
      </n-form-item>
      <n-form-item label="Host" path="host">
        <n-input v-model:value="form.host" placeholder="合法 IP 或域名" />
      </n-form-item>
      <n-form-item label="Port" path="port">
        <n-input-number v-model:value="form.port" :min="1" :max="65535" style="width: 160px" />
      </n-form-item>
      <n-form-item label="Database" path="database_name">
        <n-input v-model:value="form.database_name" placeholder="数据库名" />
      </n-form-item>
      <n-form-item label="用户名" path="username">
        <n-input v-model:value="form.username" placeholder="数据库用户名" />
      </n-form-item>
      <n-form-item label="密码" path="password">
        <n-input
          v-model:value="form.password"
          type="password"
          show-password-on="click"
          :placeholder="isEdit ? '不填则保持原密码' : '数据库密码'"
        />
      </n-form-item>
      <n-form-item label="所属分组" path="group_type">
        <n-select
          v-model:value="form.group_type"
          :options="[
            { label: '销项组', value: 1 },
            { label: '申报组', value: 2 },
          ]"
          :disabled="!isAdmin"
        />
      </n-form-item>
      <n-form-item label="备注" path="remark">
        <n-input v-model:value="form.remark" type="textarea" :rows="2" maxlength="500" show-count placeholder="选填" />
      </n-form-item>
    </n-form>

    <!-- 测试连接结果 -->
    <n-alert v-if="testResult" :type="testResult.ok ? 'success' : 'error'" class="mb-3" :show-icon="false">
      {{ testResult.text }}
    </n-alert>

    <template #footer>
      <div class="form-actions">
        <n-button size="small" :loading="testing" @click="handleTest">测试连接</n-button>
        <div class="form-actions-right">
          <n-button size="small" @click="close">取消</n-button>
          <n-button size="small" class="gradient-btn" :loading="saving" @click="handleSave">保存</n-button>
        </div>
      </div>
    </template>
  </n-modal>
</template>

<script setup lang="ts">
import { computed, reactive, ref, watch } from 'vue'
import type { FormInst, FormRules } from 'naive-ui'
import { datasourceApi } from '@/api/datasource'
import type { Datasource, DatasourceForm } from '@/api/types'
import { useAuth } from '@/composables/useAuth'

const props = defineProps<{
  show: boolean
  /** 编辑时传入数据源对象，新增为 null */
  datasource: Datasource | null
}>()

const emit = defineEmits<{
  (e: 'update:show', v: boolean): void
  (e: 'saved', payload: { id: number | null; isEdit: boolean }): void
}>()

const { isAdmin, user } = useAuth()

const formRef = ref<FormInst | null>(null)
const testing = ref(false)
const saving = ref(false)
const testResult = ref<{ ok: boolean; text: string } | null>(null)

const isEdit = computed(() => !!props.datasource)

const form = reactive<DatasourceForm>({
  name: '',
  db_type: 'MySQL',
  host: '',
  port: 3306,
  database_name: '',
  username: '',
  password: '',
  group_type: 1,
  remark: '',
})

const rules: FormRules = {
  name: [
    { required: true, message: '请输入数据源名称', trigger: ['input', 'blur'] },
    { pattern: /^[a-zA-Z0-9_一-龥-]{1,50}$/, message: '1~50 字，不含特殊字符', trigger: ['input', 'blur'] },
  ],
  host: [
    { required: true, message: '请输入 Host', trigger: ['input', 'blur'] },
    {
      pattern: /^[a-zA-Z0-9][a-zA-Z0-9.\-]*$/,
      message: '请输入合法 IP 或域名',
      trigger: ['input', 'blur'],
    },
  ],
  port: [{ required: true, type: 'number', message: '请输入端口', trigger: ['input', 'blur'] }],
  database_name: [{ required: true, message: '请输入数据库名', trigger: ['input', 'blur'] }],
  username: [{ required: true, message: '请输入用户名', trigger: ['input', 'blur'] }],
  password: [
    {
      validator: (_r, v) => isEdit.value || (v != null && v !== ''),
      message: '请输入密码',
      trigger: ['input', 'blur'],
    },
  ],
  group_type: [{ required: true, type: 'number', message: '请选择所属分组', trigger: ['change'] }],
}

// 打开弹窗时回显 / 重置表单
watch(
  () => props.show,
  (v) => {
    if (!v) return
    testResult.value = null
    if (props.datasource) {
      const d = props.datasource
      Object.assign(form, {
        name: d.name,
        db_type: d.db_type,
        host: d.host,
        port: d.port,
        database_name: d.database_name,
        username: d.username,
        password: '',
        group_type: d.group_type,
        remark: d.remark ?? '',
      })
    } else {
      Object.assign(form, {
        name: '',
        db_type: 'MySQL',
        host: '',
        port: 3306,
        database_name: '',
        username: '',
        password: '',
        group_type: user.value?.group_type === 2 ? 2 : 1,
        remark: '',
      })
    }
  },
)

function close(): void {
  emit('update:show', false)
}

/** 测试连接：显示数据库版本或错误详情（后端失败时 code=0 但 success=false） */
async function handleTest(): Promise<void> {
  try {
    await formRef.value?.validate()
  } catch {
    return
  }
  testing.value = true
  testResult.value = null
  try {
    const res = await datasourceApi.test({ ...form })
    if (res.data.success) {
      testResult.value = { ok: true, text: res.data.message }
    } else {
      testResult.value = { ok: false, text: res.data.message }
    }
  } catch (e) {
    testResult.value = { ok: false, text: (e as Error).message || '连接失败' }
  } finally {
    testing.value = false
  }
}

/** 保存：新增 / 编辑；保存后后台异步初始化表结构 */
async function handleSave(): Promise<void> {
  try {
    await formRef.value?.validate()
  } catch {
    return
  }
  saving.value = true
  try {
    let id: number | null = null
    if (isEdit.value && props.datasource) {
      const payload: Partial<DatasourceForm> = { ...form }
      if (!payload.password) delete payload.password // 编辑不填密码则保持原密码
      await datasourceApi.update(props.datasource.id, payload)
      id = props.datasource.id
    } else {
      const res = await datasourceApi.create({ ...form })
      id = res.data.id
    }
    window.$message.success('数据源已保存，正在后台初始化表结构，预计需要 10~60 秒…')
    close()
    emit('saved', { id, isEdit: isEdit.value })
  } finally {
    saving.value = false
  }
}
</script>

<style scoped>
.form-actions {
  display: flex;
  justify-content: space-between;
}
.form-actions-right {
  display: flex;
  gap: 10px;
}
.mb-3 {
  margin-bottom: 12px;
}
</style>
