/**
 * useMaterialUpload — 文件上传 + 状态轮询 hook
 *
 * 支持：
 * - PDF 文件上传（multipart/form-data）
 * - GitHub / 网页 URL 粘贴上传
 * - 上传后每 2s 轮询状态，直到 ready / error
 */

import { useCallback, useRef } from 'react'
import { useSourceStore } from '../store/sourceStore'
import type { Material } from '../types'

const API = '/api'
const POLL_INTERVAL = 2000
const MAX_POLLS = 30  // 最多轮询 60s

export function useMaterialUpload(planId: string) {
  const { addMaterial, updateMaterialStatus } = useSourceStore()
  const pollTimers = useRef<Record<string, ReturnType<typeof setInterval>>>({})

  const _startPolling = useCallback((materialId: string) => {
    let count = 0
    const timer = setInterval(async () => {
      count++
      try {
        const res = await fetch(`${API}/material/${materialId}/status?plan_id=${planId}`)
        if (!res.ok) { clearInterval(timer); return }
        const data = await res.json()
        const status = data.status as Material['status']
        updateMaterialStatus(materialId, status)
        if (status === 'ready' || status === 'error' || count >= MAX_POLLS) {
          clearInterval(timer)
          delete pollTimers.current[materialId]
        }
      } catch {
        clearInterval(timer)
      }
    }, POLL_INTERVAL)
    pollTimers.current[materialId] = timer
  }, [planId, updateMaterialStatus])

  const uploadFile = useCallback(async (file: File) => {
    const form = new FormData()
    form.append('file', file)

    // 乐观更新：立即显示 parsing 状态
    const tempId = `temp-${Date.now()}`
    addMaterial({
      id: tempId,
      type: 'pdf' as any,
      name: file.name,
      status: 'parsing',
      addedAt: new Date().toISOString(),
    })

    try {
      const res = await fetch(`${API}/upload?plan_id=${planId}`, {
        method: 'POST',
        body: form,
      })
      if (!res.ok) throw new Error(`Upload failed: ${res.status}`)
      const data = await res.json()

      // 用真实 id 替换临时 id
      useSourceStore.getState().removeMaterial(tempId)
      addMaterial({
        id: data.id,
        type: (data.type || 'pdf') as any,
        name: data.name,
        status: data.status,
        addedAt: data.addedAt,
      })

      if (data.status !== 'ready') {
        _startPolling(data.id)
      }
      return data
    } catch (err) {
      updateMaterialStatus(tempId, 'error')
      throw err
    }
  }, [planId, addMaterial, updateMaterialStatus, _startPolling])

  const uploadUrl = useCallback(async (url: string) => {
    const tempId = `temp-${Date.now()}`
    const name = url.split('/').filter(Boolean).pop() || url.slice(0, 30)
    const type = url.includes('github.com') ? 'github' : 'other'

    addMaterial({
      id: tempId,
      type: type as any,
      name,
      url,
      status: 'parsing',
      addedAt: new Date().toISOString(),
    })

    try {
      const res = await fetch(`${API}/upload/url`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ planId, url }),
      })
      if (!res.ok) throw new Error(`URL upload failed: ${res.status}`)
      const data = await res.json()

      useSourceStore.getState().removeMaterial(tempId)
      addMaterial({
        id: data.id,
        type: (data.type || type) as any,
        name: data.name,
        url,
        status: data.status,
        addedAt: data.addedAt,
      })

      if (data.status !== 'ready') {
        _startPolling(data.id)
      }
      return data
    } catch (err) {
      updateMaterialStatus(tempId, 'error')
      throw err
    }
  }, [planId, addMaterial, updateMaterialStatus, _startPolling])

  return { uploadFile, uploadUrl }
}
