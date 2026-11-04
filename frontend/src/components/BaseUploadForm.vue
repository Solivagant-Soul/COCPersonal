<template>
  <div class="base-upload">
    <el-form label-position="top" class="base-upload__form">
      <el-form-item label="标题（必填）">
        <el-input
          v-model="title"
          class="upload-title"
          maxlength="100"
          placeholder="如 #1 18本传奇防守阵"
        />
      </el-form-item>

      <el-form-item label="大本等级">
        <el-input-number v-model="thLevel" :min="1" :max="100" />
      </el-form-item>

      <el-form-item label="阵型链接">
        <el-input
          v-model="layoutLink"
          class="upload-link"
          placeholder="https://link.clashofclans.com/?action=OpenLayout&id=..."
        />
      </el-form-item>

      <el-form-item label="阵型图片（与链接至少给一个）">
        <el-upload
          class="upload-image"
          :auto-upload="false"
          :limit="1"
          accept="image/jpeg,image/png,image/webp"
          list-type="picture"
          :on-change="onFileChange"
          :on-remove="onFileRemove"
        >
          <el-button>选择图片</el-button>
        </el-upload>
        <p class="base-upload__hint">支持 JPEG / PNG / WebP，单张不超过 5 MiB。</p>
      </el-form-item>

      <el-form-item label="来源 URL（选填）">
        <el-input v-model="sourceUrl" class="upload-source" placeholder="https://..." />
      </el-form-item>

      <el-form-item label="管理员账号">
        <el-input v-model="username" class="upload-user" autocomplete="username" />
      </el-form-item>

      <el-form-item label="管理员口令">
        <el-input
          v-model="password"
          class="upload-pass"
          type="password"
          show-password
          autocomplete="current-password"
        />
      </el-form-item>

      <p v-if="error" class="upload-error">{{ error }}</p>

      <div class="base-upload__actions">
        <el-button type="primary" class="upload-submit" :loading="submitting" @click="submit">
          上传
        </el-button>
      </div>
    </el-form>
  </div>
</template>

<script setup lang="ts">
import { ref } from 'vue'
import type { UploadFile } from 'element-plus'

import { uploadBase } from '../api/endpoints'
import { ApiError } from '../api/request'

const emit = defineEmits<{ uploaded: [] }>()

// 凭据只存 sessionStorage：关掉标签页就失效，不写进前端产物。
const username = ref(sessionStorage.getItem('cocAdminUser') ?? '')
const password = ref(sessionStorage.getItem('cocAdminPass') ?? '')

const title = ref('')
const thLevel = ref(18)
const layoutLink = ref('')
const sourceUrl = ref('')
const image = ref<File | null>(null)
const error = ref('')
const submitting = ref(false)

function onFileChange(file: UploadFile) {
  image.value = file.raw ?? null
  error.value = ''
}

function onFileRemove() {
  image.value = null
}

async function submit() {
  error.value = ''
  const trimmedTitle = title.value.trim()
  if (!trimmedTitle) {
    error.value = '请填写标题'
    return
  }
  const link = layoutLink.value.trim()
  if (!link && !image.value) {
    error.value = '阵型链接或图片至少填一个'
    return
  }
  if (!username.value || !password.value) {
    error.value = '请填写管理员账号或密码'
    return
  }

  submitting.value = true
  try {
    await uploadBase(
      {
        title: trimmedTitle,
        thLevel: thLevel.value,
        layoutLink: link || null,
        image: image.value,
        sourceUrl: sourceUrl.value.trim() || null,
      },
      username.value,
      password.value,
    )
    sessionStorage.setItem('cocAdminUser', username.value)
    sessionStorage.setItem('cocAdminPass', password.value)
    emit('uploaded')
    title.value = ''
    layoutLink.value = ''
    sourceUrl.value = ''
    image.value = null
  } catch (err) {
    if (err instanceof ApiError && err.status === 401) {
      error.value = '管理员账号或密码错误'
    } else if (err instanceof Error) {
      error.value = err.message
    } else {
      error.value = '上传失败，请稍后重试'
    }
  } finally {
    submitting.value = false
  }
}
</script>

<style scoped>
.base-upload__form {
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.base-upload__hint {
  margin: 6px 0 0;
  font-size: 12px;
  color: var(--text-muted);
}

.upload-error {
  margin: 4px 0 12px;
  color: var(--danger, #f56c6c);
  font-size: 13px;
}

.base-upload__actions {
  display: flex;
  justify-content: flex-end;
}
</style>
