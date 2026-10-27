<template>
  <div class="tag-input">
    <div class="tag-input__row">
      <el-input
        v-model="raw"
        class="tag-input__field"
        :placeholder="placeholder"
        clearable
        @keyup.enter="submit"
      >
        <!-- 放大镜用内联 SVG：为一个图标引整套 @element-plus/icons-vue 不值 -->
        <template #prefix>
          <svg
            class="tag-input__icon"
            viewBox="0 0 24 24"
            fill="none"
            stroke="currentColor"
            stroke-width="2"
            stroke-linecap="round"
            aria-hidden="true"
          >
            <circle cx="10.5" cy="10.5" r="6.5" />
            <path d="m15.5 15.5 4 4" />
          </svg>
        </template>
      </el-input>

      <el-button type="primary" class="tag-input__submit" @click="submit">
        查询
      </el-button>
    </div>

    <div v-if="error" class="tag-input__error">{{ error }}</div>
  </div>
</template>

<script setup lang="ts">
import { ref } from 'vue'

import { normalizeTag } from '../utils/format'

withDefaults(defineProps<{ placeholder?: string }>(), {
  placeholder: '输入玩家标签，如 #8QU8J9J 或 8qu8j9j',
})

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
/* 输入框与按钮并排：按钮不再是 input 的 append 内嵌块，
 * 这样窄屏下两者能各自折行，输入框也能吃掉剩余宽度。 */
.tag-input__row {
  display: flex;
  align-items: center;
  gap: 12px;
}
.tag-input__field {
  flex: 1 1 auto;
  min-width: 0;
}
.tag-input__submit {
  flex-shrink: 0;
}
.tag-input__icon {
  width: 18px;
  height: 18px;
  color: var(--text-faint);
}
.tag-input__error {
  margin-top: 8px;
  color: var(--el-color-danger);
  font-size: 0.875rem;
}

/* 很窄的屏幕上按钮换到下一行并撑满，指头更好按 */
@media (max-width: 480px) {
  .tag-input__row {
    flex-wrap: wrap;
  }
  .tag-input__submit {
    width: 100%;
  }
}
</style>
