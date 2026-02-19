import { ChatResponse } from './types'
import { API_BASE } from './constants'

export async function sendChat(
  query: string,
  category: string,
  webSearchEnabled: boolean
): Promise<ChatResponse> {
  const res = await fetch(`${API_BASE}/chat`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      query,
      category,
      web_search_enabled: webSearchEnabled,
    }),
  })

  if (!res.ok) {
    const err = await res.text()
    throw new Error(err || 'API request failed')
  }

  return res.json()
}

export async function* sendChatStream(
  query: string,
  category: string,
  webSearchEnabled: boolean
): AsyncGenerator<{ type: string; content?: string; category?: string; web_search_used?: boolean; auto_web_triggered?: boolean }> {
  const res = await fetch(`${API_BASE}/chat/stream`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      query,
      category,
      web_search_enabled: webSearchEnabled,
    }),
  })

  if (!res.ok || !res.body) {
    throw new Error('Stream request failed')
  }

  const reader = res.body.getReader()
  const decoder = new TextDecoder()
  let buffer = ''

  while (true) {
    const { done, value } = await reader.read()
    if (done) break

    buffer += decoder.decode(value, { stream: true })
    const lines = buffer.split('\n')
    buffer = lines.pop() ?? ''

    for (const line of lines) {
      if (line.startsWith('data: ')) {
        try {
          const data = JSON.parse(line.slice(6))
          yield data
        } catch {
          // skip malformed lines
        }
      }
    }
  }
}
