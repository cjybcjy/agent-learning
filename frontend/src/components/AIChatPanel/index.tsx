import { useState, useRef, useEffect } from 'react'

interface Message {
  role: 'user' | 'assistant'
  content: string
}

interface Props {
  focusedSymbol?: string | null
  context?: any
}

const QUICK_QUESTIONS = [
  '过去一周热度趋势如何？',
  '为什么热度飙升？',
  '主要驱动因素是什么？',
]

export default function AIChatPanel({ focusedSymbol, context }: Props) {
  const [messages, setMessages] = useState<Message[]>([])
  const [input, setInput] = useState('')
  const [streaming, setStreaming] = useState(false)
  const bottomRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages])

  const send = async (text: string) => {
    if (!text.trim() || streaming) return
    const userMsg: Message = { role: 'user', content: text }
    setMessages(prev => [...prev, userMsg])
    setInput('')
    setStreaming(true)

    try {
      const res = await fetch('/api/chat', {
        method: 'POST',
        headers: { 'content-type': 'application/json' },
        body: JSON.stringify({
          question: text,
          context: {
            focused_symbol: focusedSymbol,
            ...context,
          },
        }),
      })
      const reader = res.body?.getReader()
      if (!reader) return

      const assistantMsg: Message = { role: 'assistant', content: '' }
      setMessages(prev => [...prev, assistantMsg])

      const decoder = new TextDecoder()
      while (true) {
        const { done, value } = await reader.read()
        if (done) break
        const chunk = decoder.decode(value)
        const lines = chunk.split('\n')
        for (const line of lines) {
          if (!line.startsWith('data: ')) continue
          const data = line.slice(6).trim()
          if (!data || data === '[DONE]') continue
          try {
            const parsed = JSON.parse(data.replace(/'/g, '"'))
            if (parsed.chunk) {
              setMessages(prev => {
                const updated = [...prev]
                const last = updated[updated.length - 1]
                if (last.role === 'assistant') {
                  last.content += parsed.chunk
                }
                return updated
              })
            }
            if (parsed.done) break
          } catch {
            // ignore parse errors
          }
        }
      }
    } catch (e) {
      console.error('chat error', e)
    } finally {
      setStreaming(false)
    }
  }

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault()
    send(input)
  }

  return (
    <div style={{ display: 'flex', flexDirection: 'column', height: '100%' }}>
      <h3 style={{ margin: '0 0 12px' }}>AI 助手 {focusedSymbol ? `· ${focusedSymbol}` : ''}</h3>

      <div style={{ flex: 1, overflow: 'auto', marginBottom: 12 }}>
        {messages.length === 0 && (
          <div style={{ display: 'flex', flexWrap: 'wrap', gap: 8 }}>
            {QUICK_QUESTIONS.map(q => (
              <button
                key={q}
                onClick={() => send(q)}
                style={{
                  padding: '6px 12px',
                  fontSize: 12,
                  border: '1px solid #ddd',
                  background: '#f5f5f5',
                  borderRadius: 16,
                  cursor: 'pointer',
                }}
              >
                {q}
              </button>
            ))}
          </div>
        )}
        {messages.map((m, i) => (
          <div
            key={i}
            style={{
              marginBottom: 8,
              padding: '8px 12px',
              borderRadius: 8,
              background: m.role === 'user' ? '#e3f2fd' : '#f5f5f5',
              alignSelf: m.role === 'user' ? 'flex-end' : 'flex-start',
              maxWidth: '90%',
              fontSize: 13,
              lineHeight: 1.5,
            }}
          >
            {m.content || (streaming && i === messages.length - 1 ? '思考中...' : '')}
          </div>
        ))}
        <div ref={bottomRef} />
      </div>

      <form onSubmit={handleSubmit} style={{ display: 'flex', gap: 8 }}>
        <input
          value={input}
          onChange={e => setInput(e.target.value)}
          placeholder="输入问题..."
          style={{
            flex: 1,
            padding: '8px 12px',
            border: '1px solid #ddd',
            borderRadius: 4,
            fontSize: 13,
          }}
        />
        <button
          type="submit"
          disabled={streaming}
          style={{
            padding: '8px 16px',
            background: streaming ? '#ccc' : '#1976d2',
            color: '#fff',
            border: 'none',
            borderRadius: 4,
            cursor: streaming ? 'not-allowed' : 'pointer',
          }}
        >
          发送
        </button>
      </form>
    </div>
  )
}
