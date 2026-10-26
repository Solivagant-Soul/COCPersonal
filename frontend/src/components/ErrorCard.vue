<template>
  <el-card class="error-card" shadow="never">
    <div class="error-card__title">查询失败</div>
    <div class="error-card__message">{{ message }}</div>
    <el-button class="error-card__retry" type="primary" @click="emit('retry')">
      重试
    </el-button>
  </el-card>
</template>

<script setup lang="ts">
import { computed } from 'vue'

import type { ApiError } from '../api/request'

const props = defineProps<{ error: ApiError }>()
const emit = defineEmits<{ retry: [] }>()

/** 按后端 `error.code` 给中文文案；表里没有就退回后端 message。 */
const MESSAGES: Record<string, string> = {
  PLAYER_NOT_FOUND: '玩家不存在，请检查标签是否输错',
  CLAN_NOT_FOUND: '部落不存在，请检查标签是否输错',
  CLAN_NOT_IN_WAR: '该部落当前没有进行中的战争',
  WARLOG_PRIVATE: '该部落的战争日志未公开',
  INVALID_TAG: '标签格式不对，请重新输入',
  INVALID_PARAMS: '请求参数不合法',
  UPSTREAM_UNAVAILABLE: '上游服务暂时不可用，请稍后重试',
  UPSTREAM_THROTTLED: '上游限流中，请稍后重试',
  BAD_RESPONSE: '响应格式异常，请稍后重试',
  BAD_REQUEST: '请求有误，请稍后重试',
  NETWORK_ERROR: '网络异常，请检查连接后重试',
}

const message = computed(
  () => MESSAGES[props.error.code] ?? props.error.message ?? '请求失败，请稍后重试',
)
</script>

<style scoped>
.error-card__title {
  font-size: 1.0625rem;
  font-weight: 600;
  margin-bottom: 8px;
}
.error-card__message {
  color: var(--el-text-color-regular);
  margin-bottom: 16px;
}
</style>
