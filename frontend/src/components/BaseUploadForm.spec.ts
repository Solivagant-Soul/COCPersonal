import { flushPromises, mount } from '@vue/test-utils'
import { beforeEach, describe, expect, it, vi } from 'vitest'

vi.mock('../api/endpoints', () => ({ uploadBase: vi.fn() }))

import { uploadBase } from '../api/endpoints'
import { ApiError } from '../api/request'
import { installElementPlus } from '../plugins/element'
import BaseUploadForm from './BaseUploadForm.vue'

function mountForm() {
  return mount(BaseUploadForm, { global: { plugins: [{ install: installElementPlus }] } })
}

beforeEach(() => {
  vi.mocked(uploadBase).mockReset()
  sessionStorage.clear()
})

it('缺标题时不发请求并提示', async () => {
  const w = mountForm()
  await w.find('.upload-submit').trigger('click')
  expect(uploadBase).not.toHaveBeenCalled()
  expect(w.find('.upload-error').text()).toContain('标题')
})

it('链接和图片都缺时不发请求', async () => {
  const w = mountForm()
  await w.find('.upload-title input').setValue('阵型A')
  await w.find('.upload-submit').trigger('click')
  expect(uploadBase).not.toHaveBeenCalled()
  expect(w.find('.upload-error').text()).toContain('链接或图片')
})

it('401 提示账号密码错误且不 emit', async () => {
  vi.mocked(uploadBase).mockRejectedValue(new ApiError('UNAUTHORIZED', 'no', 401))
  const w = mountForm()
  await w.find('.upload-title input').setValue('阵型A')
  await w.find('.upload-link input').setValue('https://link.clashofclans.com/?id=a')
  await w.find('.upload-user input').setValue('boss')
  await w.find('.upload-pass input').setValue('wrong-pass')
  await w.find('.upload-submit').trigger('click')
  await flushPromises()
  expect(w.find('.upload-error').text()).toContain('账号或密码')
  expect(w.emitted('uploaded')).toBeUndefined()
})

it('成功后 emit uploaded 并记住凭据', async () => {
  vi.mocked(uploadBase).mockResolvedValue({ data: { id: 1, duplicated: false }, meta: {} } as never)
  const w = mountForm()
  await w.find('.upload-title input').setValue('阵型A')
  await w.find('.upload-user input').setValue('boss')
  await w.find('.upload-pass input').setValue('s3cret')
  await w.find('.upload-link input').setValue('https://link.clashofclans.com/?id=a')
  await w.find('.upload-submit').trigger('click')
  await flushPromises()
  expect(w.emitted('uploaded')).toHaveLength(1)
  expect(sessionStorage.getItem('cocAdminUser')).toBe('boss')
})
