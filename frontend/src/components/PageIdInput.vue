<template>
  <el-input
    :model-value="model"
    :placeholder="placeholder"
    :aria-invalid="model ? !valid : undefined"
    @update:model-value="onInput"
  >
    <template #append>
      <span :class="['pid-mark', model ? (valid ? 'ok' : 'err') : 'empty']">{{ mark }}</span>
    </template>
  </el-input>
</template>

<script setup lang="ts">
import { ref, computed } from 'vue'
import { normalizePageId } from '@/utils/pageId'

/** 统一的 Page/DataSource ID 输入框：输入即规范化，并在右侧给出校验标记。
 *  - v-model 绑定规范化后的 ID
 *  - @valid 事件在外部输入校验结果变化时触发，供父组件控制按钮 disabled 等 */
const model = defineModel<string>({ default: '' })
const props = defineProps<{ placeholder?: string }>()
const placeholder = props.placeholder ?? '粘贴 Notion 页面 ID 或链接'
const valid = ref(false)
let lastValid = false

const mark = computed(() => (model.value ? (valid.value ? '✓' : '✗') : ''))

const emit = defineEmits<{ (e: 'valid', ok: boolean): void }>()

function onInput(v: string) {
  const r = normalizePageId(v)
  valid.value = r.ok
  model.value = r.ok ? r.value : v
  if (r.ok !== lastValid) {
    lastValid = r.ok
    emit('valid', r.ok)
  }
}
</script>

<style scoped>
.pid-mark {
  font-weight: 700;
  min-width: 14px;
  display: inline-block;
  text-align: center;
}
.pid-mark.ok {
  color: var(--app-success);
}
.pid-mark.err {
  color: var(--app-danger);
}
.pid-mark.empty {
  color: var(--app-muted);
}
</style>
