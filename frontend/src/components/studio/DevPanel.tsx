/**
 * DevPanel — 开发者调试面板
 * 展示 LLM Provider 切换、LangSmith 状态、Agent 调用 Trace
 */
import React, { useState, useEffect, useCallback } from 'react'

interface TraceEntry {
  id: string
  type: string
  name: string
  startTime: string
  duration: number
  status: string
  input: string
  output: string
  tokens: { prompt: number; completion: number; total: number }
  metadata: Record<string, any>
}

interface DevStatus {
  langsmith: {
    enabled: boolean
    connected: boolean
    hasApiKey: boolean
    packageInstalled: boolean
    project: string
  }
  system: {
    provider: string
    model: string
    tracesCount: number
  }
}

interface ProviderInfo {
  label: string
  models: string[]
  default_model: string
  hasApiKey: boolean
  maskedKey: string
}

interface ProviderConfig {
  current: string
  currentModel: string
  providers: Record<string, ProviderInfo>
}

export const DevPanel: React.FC = () => {
  const [status, setStatus] = useState<DevStatus | null>(null)
  const [traces, setTraces] = useState<TraceEntry[]>([])
  const [expandedId, setExpandedId] = useState<string | null>(null)
  const [loading, setLoading] = useState(true)

  // Provider 切换状态
  const [providerConfig, setProviderConfig] = useState<ProviderConfig | null>(null)
  const [selectedProvider, setSelectedProvider] = useState('')
  const [selectedModel, setSelectedModel] = useState('')
  const [apiKeyInput, setApiKeyInput] = useState('')
  const [showApiKey, setShowApiKey] = useState(false)
  const [saving, setSaving] = useState(false)
  const [saveMsg, setSaveMsg] = useState('')
  const [graphMermaid, setGraphMermaid] = useState<string | null>(null)

  const fetchData = useCallback(async () => {
    try {
      // 各请求独立 try-catch，一个失败不影响其他
      const [statusRes, tracesRes, providerRes, graphRes] = await Promise.allSettled([
        fetch('/api/dev/status'),
        fetch('/api/dev/traces?limit=20'),
        fetch('/api/provider/config'),
        fetch('/api/dev/graph'),
      ])
      if (statusRes.status === 'fulfilled' && statusRes.value.ok)
        setStatus(await statusRes.value.json())
      if (tracesRes.status === 'fulfilled' && tracesRes.value.ok)
        setTraces(await tracesRes.value.json())
      if (graphRes.status === 'fulfilled' && graphRes.value.ok) {
        const gd = await graphRes.value.json()
        if (gd.mermaid) setGraphMermaid(gd.mermaid)
        else if (gd.error) setGraphMermaid(null)
      }
      if (providerRes.status === 'fulfilled' && providerRes.value.ok) {
        const cfg: ProviderConfig = await providerRes.value.json()
        setProviderConfig(cfg)
        if (!selectedProvider) {
          setSelectedProvider(cfg.current)
          setSelectedModel(cfg.currentModel)
        }
      }
    } catch { /* 全局兜底 */ }
    finally { setLoading(false) }
  }, [selectedProvider])

  useEffect(() => { fetchData() }, [fetchData])
  useEffect(() => {
    const timer = setInterval(fetchData, 5000)
    return () => clearInterval(timer)
  }, [fetchData])

  const toggleLangSmith = async () => {
    if (!status) return
    const next = !status.langsmith.enabled
    try {
      await fetch('/api/dev/langsmith', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ enabled: next }),
      })
      setStatus(s => s ? { ...s, langsmith: { ...s.langsmith, enabled: next, connected: next && s.langsmith.hasApiKey && s.langsmith.packageInstalled } } : s)
    } catch { /* 静默 */ }
  }

  // 切换 provider 时自动更新 model 为该 provider 的默认模型
  const handleProviderChange = (name: string) => {
    setSelectedProvider(name)
    const info = providerConfig?.providers[name]
    if (info) {
      // 如果当前 model 不在新 provider 的列表里，切到默认
      if (!info.models.includes(selectedModel)) {
        setSelectedModel(info.default_model)
      }
    }
    setApiKeyInput('')
    setSaveMsg('')
  }

  const handleSaveProvider = async () => {
    setSaving(true)
    setSaveMsg('')
    try {
      const res = await fetch('/api/provider/config', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          provider: selectedProvider,
          model: selectedModel,
          apiKey: apiKeyInput || undefined,
        }),
      })
      const data = await res.json()
      if (data.ok) {
        setSaveMsg('✅ 已切换')
        setApiKeyInput('')
        // 刷新配置
        fetchData()
      } else {
        setSaveMsg(`❌ ${data.error}`)
      }
    } catch {
      setSaveMsg('❌ 网络错误')
    } finally {
      setSaving(false)
    }
  }

  const fmtDuration = (ms: number) => ms < 1000 ? `${ms}ms` : `${(ms / 1000).toFixed(1)}s`
  const fmtTime = (iso: string) => {
    try { return new Date(iso).toLocaleTimeString('zh-CN', { hour12: false }) } catch { return iso }
  }

  const typeColors: Record<string, string> = {
    chain: 'bg-orange-100 text-orange-700',
    llm: 'bg-purple-100 text-purple-700',
    tool: 'bg-green-100 text-green-700',
    retriever: 'bg-orange-100 text-orange-700',
  }

  const currentProviderInfo = providerConfig?.providers[selectedProvider]

  if (loading) {
    return (
      <div className="flex items-center justify-center py-12">
        <div className="w-5 h-5 border-2 border-blue-500 border-t-transparent rounded-full animate-spin" />
      </div>
    )
  }

  return (
    <div className="flex flex-col gap-4 px-6 py-4 text-sm">

      {/* Provider 切换卡片 */}
      <div className="rounded-xl border border-[#E0E0E0] p-4">
        <span className="font-medium text-[#202124] block mb-3">🤖 LLM Provider</span>

        {/* Provider 选择 */}
        <div className="space-y-2.5">
          <div>
            <label className="text-xs text-[#5F6368] block mb-1">Provider</label>
            <select
              value={selectedProvider}
              onChange={e => handleProviderChange(e.target.value)}
              className="w-full px-2.5 py-1.5 rounded-lg border border-[#E0E0E0] text-xs bg-white focus:outline-none focus:border-[#D97757]"
            >
              {providerConfig && Object.entries(providerConfig.providers).map(([name, info]) => (
                <option key={name} value={name}>{info.label}</option>
              ))}
            </select>
          </div>

          {/* Model 选择 */}
          <div>
            <label className="text-xs text-[#5F6368] block mb-1">Model</label>
            <select
              value={selectedModel}
              onChange={e => setSelectedModel(e.target.value)}
              className="w-full px-2.5 py-1.5 rounded-lg border border-[#E0E0E0] text-xs bg-white focus:outline-none focus:border-[#D97757]"
            >
              {currentProviderInfo?.models.map(m => (
                <option key={m} value={m}>{m}</option>
              ))}
            </select>
          </div>

          {/* API Key 输入 */}
          <div>
            <label className="text-xs text-[#5F6368] block mb-1">
              API Key
              {currentProviderInfo?.hasApiKey && <span className="ml-1 text-green-600">（已配置）</span>}
            </label>
            <div className="relative">
              <input
                type={showApiKey ? 'text' : 'password'}
                value={apiKeyInput}
                onChange={e => setApiKeyInput(e.target.value)}
                placeholder={currentProviderInfo?.hasApiKey ? `当前: ${currentProviderInfo.maskedKey}` : '输入 API Key'}
                className="w-full px-2.5 py-1.5 pr-8 rounded-lg border border-[#E0E0E0] text-xs bg-white focus:outline-none focus:border-[#D97757]"
              />
              <button
                onClick={() => setShowApiKey(!showApiKey)}
                className="absolute right-2 top-1/2 -translate-y-1/2 text-[#9AA0A6] hover:text-[#5F6368] text-xs"
                aria-label={showApiKey ? '隐藏' : '显示'}
              >
                {showApiKey ? '🙈' : '👁'}
              </button>
            </div>
          </div>

          {/* 保存按钮 */}
          <div className="flex items-center gap-2">
            <button
              onClick={handleSaveProvider}
              disabled={saving}
              className="px-3 py-1.5 rounded-lg bg-[#D97757] text-white text-xs hover:bg-[#c5684a] disabled:opacity-50 transition-colors"
            >
              {saving ? '切换中...' : '保存并切换'}
            </button>
            {saveMsg && <span className="text-xs">{saveMsg}</span>}
          </div>

          {/* 当前状态 */}
          <div className="flex flex-wrap gap-1.5 pt-1">
            <span className="px-2 py-0.5 rounded-full bg-[#F2DFD3] text-[#D97757] text-[10px]">
              当前: {providerConfig?.current}/{providerConfig?.currentModel}
            </span>
          </div>
        </div>
      </div>

      {/* LangSmith 状态卡片 */}
      <div className="rounded-xl border border-[#E0E0E0] p-4">
        <div className="flex items-center justify-between mb-3">
          <span className="font-medium text-[#202124]">🔗 LangSmith</span>
          <button
            onClick={toggleLangSmith}
            className={`relative w-10 h-5 rounded-full transition-colors duration-50 ${status?.langsmith.enabled ? 'bg-orange-500' : 'bg-gray-300'}`}
            aria-label="切换 LangSmith"
          >
            <span className={`absolute top-0.5 w-4 h-4 rounded-full bg-white shadow transition-transform duration-50 ${status?.langsmith.enabled ? 'translate-x-5' : 'translate-x-0.5'}`} />
          </button>
        </div>
        <div className="grid grid-cols-2 gap-2 text-xs">
          <div className="flex items-center gap-1.5">
            <span className={`w-2 h-2 rounded-full ${status?.langsmith.connected ? 'bg-green-500' : 'bg-gray-300'}`} />
            <span className="text-[#5F6368]">{status?.langsmith.connected ? '已连接' : '未连接'}</span>
          </div>
          <div className="flex items-center gap-1.5">
            <span className={`w-2 h-2 rounded-full ${status?.langsmith.hasApiKey ? 'bg-green-500' : 'bg-red-400'}`} />
            <span className="text-[#5F6368]">{status?.langsmith.hasApiKey ? 'API Key ✓' : 'API Key ✗'}</span>
          </div>
          <div className="flex items-center gap-1.5">
            <span className={`w-2 h-2 rounded-full ${status?.langsmith.packageInstalled ? 'bg-green-500' : 'bg-red-400'}`} />
            <span className="text-[#5F6368]">{status?.langsmith.packageInstalled ? 'SDK ✓' : 'SDK ✗'}</span>
          </div>
          <div className="text-[#5F6368]">📁 {status?.langsmith.project}</div>
        </div>
      </div>

      {/* 图定义卡片 */}
      <div className="rounded-xl border border-[#E0E0E0] p-4">
        <div className="flex items-center justify-between mb-3">
          <span className="font-medium text-[#202124]">🔀 图定义</span>
          <button
            onClick={() => {
              if (graphMermaid) navigator.clipboard.writeText(graphMermaid)
            }}
            className="text-xs text-[#D97757] hover:underline"
          >
            复制 Mermaid
          </button>
        </div>
        {graphMermaid ? (
          <pre className="p-3 rounded-lg bg-[#F8F9FA] text-[11px] font-mono whitespace-pre-wrap overflow-x-auto max-h-48 border border-[#E0E0E0]">
            {graphMermaid}
          </pre>
        ) : (
          <p className="text-xs text-[#9AA0A6] text-center py-4">加载中...</p>
        )}
      </div>

      {/* Trace 列表 */}
      <div>
        <div className="flex items-center justify-between mb-2">
          <span className="font-medium text-[#202124]">📊 调用记录</span>
          <button onClick={fetchData} className="text-xs text-[#D97757] hover:underline">刷新</button>
        </div>
        {traces.length === 0 ? (
          <p className="text-xs text-[#9AA0A6] text-center py-6">暂无调用记录，发送消息后会自动记录</p>
        ) : (
          <ul className="flex flex-col gap-1">
            {traces.map(t => (
              <li key={t.id}>
                <button
                  onClick={() => setExpandedId(expandedId === t.id ? null : t.id)}
                  className="w-full flex items-center gap-2 px-3 py-2 rounded-lg hover:bg-gray-50 transition-colors text-left"
                >
                  <span className={`px-1.5 py-0.5 rounded text-[10px] font-mono ${typeColors[t.type] || 'bg-gray-100 text-gray-600'}`}>
                    {t.type}
                  </span>
                  <span className="flex-1 truncate text-xs text-[#202124]">{t.name}</span>
                  <span className={`text-[10px] font-mono ${t.status === 'ok' ? 'text-green-600' : 'text-red-500'}`}>
                    {fmtDuration(t.duration)}
                  </span>
                </button>
                {expandedId === t.id && (
                  <div className="mx-3 mb-2 p-3 rounded-lg bg-[#F8F9FA] text-xs space-y-2">
                    <div>
                      <span className="text-[#9AA0A6]">时间</span>
                      <span className="ml-2 text-[#202124]">{fmtTime(t.startTime)}</span>
                    </div>
                    <div>
                      <span className="text-[#9AA0A6]">输入</span>
                      <pre className="mt-1 p-2 rounded bg-white border border-[#E0E0E0] text-[11px] whitespace-pre-wrap break-all max-h-24 overflow-y-auto">{t.input || '(空)'}</pre>
                    </div>
                    <div>
                      <span className="text-[#9AA0A6]">输出</span>
                      <pre className="mt-1 p-2 rounded bg-white border border-[#E0E0E0] text-[11px] whitespace-pre-wrap break-all max-h-24 overflow-y-auto">{t.output || '(空)'}</pre>
                    </div>
                    {Object.keys(t.metadata).length > 0 && (
                      <div>
                        <span className="text-[#9AA0A6]">元数据</span>
                        <pre className="mt-1 p-2 rounded bg-white border border-[#E0E0E0] text-[11px] whitespace-pre-wrap">{JSON.stringify(t.metadata, null, 2)}</pre>
                      </div>
                    )}
                  </div>
                )}
              </li>
            ))}
          </ul>
        )}
      </div>
    </div>
  )
}
