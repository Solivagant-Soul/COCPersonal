<template>
  <div class="tag-input">
    <el-input
      v-model="raw"
      placeholder="输入玩家标签，如 #8QU8J9J 或 8qu8j9j"
      clearable
      @keyup.enter="submit"
    >
      <template #append>
        <el-button type="primary" @click="submit">查询</el-button>
      </template>
    </el-input>
    <div v-if="error" class="tag-input__error">{{ error }}</div>
  </div>
</template>

<script setup lang="ts">
import { ref } from 'vue'

import { normalizeTag } from '../utils/format'

const emit = defineEmits<{ submit: [tag: string] }>()

const raw = ref('')
const error = ref('')

function submit() {
  const tag = normalizeTag(raw.value)
  if (!tag) {
    // 非法标签就地拦截：不构造注定被后端 400 的请求
    error.value = '标签格式不对：应为 3-10 位字母数字（如 #8QU8J9J）'
    return
  }
  error.value = ''
  emit('submit', tag)
}
</script>

<style scoped>
.tag-input__error {
  margin-top: 8px;
  color: var(--el-color-danger);
  font-size: 13px;
}
</style>
