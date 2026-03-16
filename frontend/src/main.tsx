import React from 'react'
import ReactDOM from 'react-dom/client'
import { BrowserRouter, Routes, Route } from 'react-router-dom'
import './index.css'

// 一次性 localStorage → SQLite 数据迁移 + 旧 key 清理
const LEGACY_KEYS = ['plan-store', 'chat-store', 'source-store', 'studio-store', 'search-history']

;(async function migrateLocalStorage() {
  const MIGRATION_KEY = '__sqlite_migrated__'
  if (localStorage.getItem(MIGRATION_KEY)) {
    // 已迁移，确保旧 key 被清理
    LEGACY_KEYS.forEach(k => localStorage.removeItem(k))
    return
  }

  const hasData = LEGACY_KEYS.some(k => localStorage.getItem(k))
  if (!hasData) {
    localStorage.setItem(MIGRATION_KEY, '1')
    return
  }

  try {
    const payload: Record<string, any> = {}

    // plans
    const planRaw = localStorage.getItem('plan-store')
    if (planRaw) {
      const parsed = JSON.parse(planRaw)
      const state = parsed?.state ?? parsed
      payload.plans = state?.plans ?? []
    }

    // chat messages — 旧 chatStore 按 planId 缓存在 _cache 中
    const chatRaw = localStorage.getItem('chat-store')
    if (chatRaw) {
      const parsed = JSON.parse(chatRaw)
      const state = parsed?.state ?? parsed
      const messages: any[] = []
      // _cache: { [planId]: { messages: [...] } }
      const cache = state?._cache ?? {}
      for (const [planId, data] of Object.entries(cache as Record<string, any>)) {
        for (const msg of data?.messages ?? []) {
          messages.push({ ...msg, planId })
        }
      }
      // 也检查顶层 messages（当前活跃 plan）
      if (state?.messages?.length && state?._activePlanId) {
        for (const msg of state.messages) {
          if (!messages.find((m: any) => m.id === msg.id)) {
            messages.push({ ...msg, planId: state._activePlanId })
          }
        }
      }
      payload.messages = messages
    }

    // materials — 旧 sourceStore 按 planId 缓存在 _cache 中
    const sourceRaw = localStorage.getItem('source-store')
    if (sourceRaw) {
      const parsed = JSON.parse(sourceRaw)
      const state = parsed?.state ?? parsed
      const materials: any[] = []
      const cache = state?._cache ?? {}
      for (const [planId, data] of Object.entries(cache as Record<string, any>)) {
        for (const mat of data?.materials ?? []) {
          materials.push({ ...mat, planId })
        }
      }
      if (state?.materials?.length && state?._activePlanId) {
        for (const mat of state.materials) {
          if (!materials.find((m: any) => m.id === mat.id)) {
            materials.push({ ...mat, planId: state._activePlanId })
          }
        }
      }
      payload.materials = materials
    }

    // studio — 旧 studioStore 按 planId 缓存在 _cache 中
    const studioRaw = localStorage.getItem('studio-store')
    if (studioRaw) {
      const parsed = JSON.parse(studioRaw)
      const state = parsed?.state ?? parsed
      const studio: Record<string, any> = {}
      const cache = state?._cache ?? {}
      for (const [planId, data] of Object.entries(cache as Record<string, any>)) {
        studio[planId] = data
      }
      // 也保存当前活跃 plan 的数据
      if (state?._activePlanId && (state?.allDays?.length || state?.notes?.length || state?.generatedContents?.length)) {
        studio[state._activePlanId] = {
          allDays: state.allDays ?? [],
          notes: state.notes ?? [],
          generatedContents: state.generatedContents ?? [],
        }
      }
      payload.studio = studio
    }

    // search history
    const searchRaw = localStorage.getItem('search-history')
    if (searchRaw) {
      const parsed = JSON.parse(searchRaw)
      const state = parsed?.state ?? parsed
      payload.searchHistory = state?.history ?? []
    }

    const res = await fetch('/api/migrate-local-data', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    })
    const result = await res.json()
    if (result.ok) {
      console.log('localStorage 数据迁移成功:', result.imported)
      // 清理旧 key
      LEGACY_KEYS.forEach(k => localStorage.removeItem(k))
    } else {
      console.warn('数据迁移部分失败:', result)
    }
  } catch (e) {
    console.error('数据迁移出错:', e)
  }

  localStorage.setItem(MIGRATION_KEY, '1')
})().then(() => {
  // 页面（懒加载）
  const HomePage = React.lazy(() => import('./pages/HomePage'))
  const WorkspacePage = React.lazy(() => import('./pages/WorkspacePage'))

  // 全局 Toast 组件（懒加载，不阻塞首屏）
  const Toast = React.lazy(() => import('./components/ui/Toast').then(m => ({ default: m.Toast })))

  ReactDOM.createRoot(document.getElementById('root')!).render(
    <React.StrictMode>
      <BrowserRouter>
        <React.Suspense fallback={<div className="flex h-screen items-center justify-center"><div className="animate-spin h-8 w-8 border-2 border-primary border-t-transparent rounded-full" /></div>}>
          <Routes>
            <Route path="/" element={<HomePage />} />
            <Route path="/workspace/:planId" element={<WorkspacePage />} />
          </Routes>
        </React.Suspense>
        {/* 全局 Toast：挂载在路由外部，始终可用 */}
        <React.Suspense fallback={null}>
          <Toast />
        </React.Suspense>
      </BrowserRouter>
    </React.StrictMode>
  )
})
