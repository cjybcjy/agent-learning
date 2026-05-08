import { useState, useEffect, useCallback } from 'react'

interface Provider {
  provider: string
  display_name: string
  default_model: string
  api_key_env: string
}

interface ProviderStatus {
  configured: boolean
  source: string
  api_key_env: string
}

interface Props {
  open: boolean
  onClose: () => void
}

export default function SettingsPanel({ open, onClose }: Props) {
  const [providers, setProviders] = useState<Provider[]>([])
  const [providerStatus, setProviderStatus] = useState<Record<string, ProviderStatus>>({})
  const [currentProvider, setCurrentProvider] = useState<string>('deepseek')
  const [currentModel, setCurrentModel] = useState<string>('deepseek-chat')
  const [selectedProvider, setSelectedProvider] = useState<string>('deepseek')
  const [modelInput, setModelInput] = useState<string>('')
  const [apiKey, setApiKey] = useState('')
  const [saved, setSaved] = useState(false)
  const [switching, setSwitching] = useState(false)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')

  const fetchData = useCallback(async () => {
    try {
      const [modelsRes, currentRes, configRes] = await Promise.all([
        fetch('/api/models'),
        fetch('/api/models/current'),
        fetch('/api/config'),
      ])
      const modelsData = await modelsRes.json()
      const currentData = await currentRes.json()
      const configData = await configRes.json()

      setProviders(modelsData.providers || [])
      setCurrentProvider(currentData.provider || 'deepseek')
      setCurrentModel(currentData.model || 'deepseek-chat')
      setSelectedProvider(currentData.provider || 'deepseek')
      setProviderStatus(configData.providers || {})

      // Pre-fill model input with current model
      const prov = (modelsData.providers || []).find(
        (p: Provider) => p.provider === currentData.provider
      )
      setModelInput(currentData.model || prov?.default_model || '')
    } catch (e) {
      console.error(e)
    }
  }, [])

  useEffect(() => {
    if (!open) return
    fetchData()
  }, [open, fetchData])

  // Update model input when provider selection changes
  useEffect(() => {
    const prov = providers.find(p => p.provider === selectedProvider)
    if (prov) {
      // Only auto-fill if the current model input matches the old provider's default
      // or if it's empty
      const currentProv = providers.find(p => p.provider === currentProvider)
      if (!modelInput || modelInput === currentProv?.default_model || modelInput === currentModel) {
        setModelInput(prov.default_model)
      }
    }
  }, [selectedProvider, providers])

  const handleSaveKey = async () => {
    if (!apiKey.trim()) return
    const prov = providers.find(p => p.provider === selectedProvider)
    if (!prov) return

    setLoading(true)
    setError('')
    try {
      const res = await fetch('/api/config', {
        method: 'POST',
        headers: { 'content-type': 'application/json' },
        body: JSON.stringify({ key: prov.api_key_env, value: apiKey.trim() }),
      })
      if (res.ok) {
        setSaved(true)
        setApiKey('')
        setTimeout(() => setSaved(false), 2000)
        await fetchData()
      } else {
        setError('保存失败')
      }
    } catch (e) {
      setError('网络错误')
      console.error(e)
    } finally {
      setLoading(false)
    }
  }

  const handleSwitchProvider = async () => {
    setSwitching(true)
    setError('')
    try {
      const res = await fetch('/api/models/switch', {
        method: 'POST',
        headers: { 'content-type': 'application/json' },
        body: JSON.stringify({
          provider: selectedProvider,
          model: modelInput.trim() || undefined,
        }),
      })
      if (res.ok) {
        const data = await res.json()
        setCurrentProvider(data.provider)
        setCurrentModel(data.model)
        setSaved(true)
        setTimeout(() => setSaved(false), 2000)
        await fetchData()
      } else {
        const data = await res.json()
        setError(data.error || '切换失败')
      }
    } catch (e) {
      setError('网络错误')
      console.error(e)
    } finally {
      setSwitching(false)
    }
  }

  const selectedProv = providers.find(p => p.provider === selectedProvider)
  const status = providerStatus[selectedProvider]
  const isEnvOverride = status?.source === 'env'

  if (!open) return null

  return (
    <div
      style={{
        position: 'fixed',
        top: 0, left: 0, right: 0, bottom: 0,
        background: 'rgba(0,0,0,0.4)',
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        zIndex: 1000,
      }}
      onClick={onClose}
    >
      <div
        style={{
          background: '#fff',
          borderRadius: 8,
          padding: 24,
          width: 460,
          maxWidth: '92vw',
          maxHeight: '90vh',
          overflow: 'auto',
          boxShadow: '0 4px 20px rgba(0,0,0,0.15)',
        }}
        onClick={e => e.stopPropagation()}
      >
        <h3 style={{ margin: '0 0 16px' }}>模型设置</h3>

        {/* Current active model */}
        <div style={{
          padding: '10px 12px',
          background: '#f5f5f5',
          borderRadius: 4,
          fontSize: 13,
          marginBottom: 16,
          display: 'flex',
          justifyContent: 'space-between',
          alignItems: 'center',
        }}>
          <span style={{ color: '#666' }}>当前模型</span>
          <span style={{ fontWeight: 500, color: '#333' }}>
            {providers.find(p => p.provider === currentProvider)?.display_name || currentProvider}
            {' '}
            <span style={{ color: '#888', fontSize: 12 }}>({currentModel})</span>
          </span>
        </div>

        {error && (
          <div style={{
            padding: '8px 12px',
            background: '#ffebee',
            borderRadius: 4,
            fontSize: 13,
            color: '#c62828',
            marginBottom: 12,
          }}>
            {error}
          </div>
        )}

        {/* Provider selector */}
        <div style={{ marginBottom: 14 }}>
          <label style={{ display: 'block', fontSize: 13, marginBottom: 6, color: '#555' }}>
            选择服务商
          </label>
          <select
            value={selectedProvider}
            onChange={e => setSelectedProvider(e.target.value)}
            style={{
              width: '100%',
              padding: '8px 12px',
              border: '1px solid #ddd',
              borderRadius: 4,
              fontSize: 13,
              background: '#fff',
              boxSizing: 'border-box',
            }}
          >
            {providers.map(p => (
              <option key={p.provider} value={p.provider}>
                {p.display_name}
              </option>
            ))}
          </select>
        </div>

        {/* Model input */}
        <div style={{ marginBottom: 14 }}>
          <label style={{ display: 'block', fontSize: 13, marginBottom: 6, color: '#555' }}>
            模型名称
          </label>
          <input
            type="text"
            value={modelInput}
            onChange={e => setModelInput(e.target.value)}
            placeholder={selectedProv?.default_model || ''}
            style={{
              width: '100%',
              padding: '8px 12px',
              border: '1px solid #ddd',
              borderRadius: 4,
              fontSize: 13,
              boxSizing: 'border-box',
            }}
          />
          <p style={{ fontSize: 12, color: '#999', margin: '4px 0 0' }}>
            留空使用默认模型：{selectedProv?.default_model || '-'}
          </p>
        </div>

        {/* API Key status */}
        {status && (
          <div style={{
            padding: '8px 12px',
            background: status.configured ? '#e8f5e9' : '#fff3e0',
            borderRadius: 4,
            fontSize: 13,
            color: status.configured ? '#2e7d32' : '#e65100',
            marginBottom: 14,
            display: 'flex',
            justifyContent: 'space-between',
            alignItems: 'center',
          }}>
            <span>
              {status.configured
                ? 'API Key 已配置'
                : 'API Key 未配置'}
              {isEnvOverride && '（环境变量）'}
            </span>
            {status.configured && (
              <span style={{ fontSize: 12, opacity: 0.8 }}>✓</span>
            )}
          </div>
        )}

        {/* API Key input */}
        <div style={{ marginBottom: 16 }}>
          <label style={{ display: 'block', fontSize: 13, marginBottom: 6, color: '#555' }}>
            {selectedProv?.display_name || selectedProvider} API Key
          </label>
          <input
            type="password"
            value={apiKey}
            onChange={e => setApiKey(e.target.value)}
            placeholder={`${selectedProv?.api_key_env || 'API Key'}...`}
            disabled={isEnvOverride}
            style={{
              width: '100%',
              padding: '8px 12px',
              border: '1px solid #ddd',
              borderRadius: 4,
              fontSize: 13,
              boxSizing: 'border-box',
              background: isEnvOverride ? '#f5f5f5' : '#fff',
            }}
          />
          {isEnvOverride ? (
            <p style={{ fontSize: 12, color: '#1565c0', margin: '4px 0 0' }}>
              当前使用环境变量中的 API Key，页面配置不会生效。
            </p>
          ) : (
            <p style={{ fontSize: 12, color: '#999', margin: '4px 0 0' }}>
              Key 保存在服务器本地，文件权限仅限所有者读取。
            </p>
          )}
        </div>

        {/* Buttons */}
        <div style={{ display: 'flex', gap: 8, justifyContent: 'flex-end' }}>
          <button
            onClick={handleSaveKey}
            disabled={loading || !apiKey.trim() || isEnvOverride}
            style={{
              padding: '8px 16px',
              background: loading || !apiKey.trim() || isEnvOverride ? '#ccc' : '#f5f5f5',
              color: '#333',
              border: '1px solid #ddd',
              borderRadius: 4,
              cursor: loading || !apiKey.trim() || isEnvOverride ? 'not-allowed' : 'pointer',
              fontSize: 13,
            }}
          >
            {saved ? '已保存' : loading ? '保存中...' : '保存 Key'}
          </button>
          <button
            onClick={handleSwitchProvider}
            disabled={switching}
            style={{
              padding: '8px 16px',
              background: switching ? '#ccc' : '#1976d2',
              color: '#fff',
              border: 'none',
              borderRadius: 4,
              cursor: switching ? 'not-allowed' : 'pointer',
              fontSize: 13,
            }}
          >
            {saved ? '已切换' : switching ? '切换中...' : '切换模型'}
          </button>
        </div>
      </div>
    </div>
  )
}
