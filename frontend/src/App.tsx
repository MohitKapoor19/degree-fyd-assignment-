import { useState, useRef, useEffect } from 'react'
import { Send, Globe, Globe2, Trash2, ChevronRight, Loader2, Database, Zap } from 'lucide-react'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import rehypeRaw from 'rehype-raw'
import { Category, Message } from './types'
import { CATEGORY_CONFIG } from './constants'
import { sendChatStream } from './api'

const CATEGORIES: Category[] = ['COLLEGE', 'EXAM', 'COMPARISON', 'PREDICTOR', 'TOP_COLLEGES']

function generateId() {
  return Math.random().toString(36).slice(2)
}

export default function App() {
  const [activeCategory, setActiveCategory] = useState<Category>('COLLEGE')
  const [activeSubTab, setActiveSubTab] = useState<string>('All')
  const [allMessages, setAllMessages] = useState<Record<Category, Message[]>>({
    COLLEGE: [], EXAM: [], COMPARISON: [], PREDICTOR: [], TOP_COLLEGES: []
  })
  const [input, setInput] = useState('')
  const [loading, setLoading] = useState(false)
  const [webSearch, setWebSearch] = useState(false)
  const [responseMode, setResponseMode] = useState<'concise' | 'detailed'>('detailed')
  const bottomRef = useRef<HTMLDivElement>(null)

  const config = CATEGORY_CONFIG[activeCategory]
  const messages = allMessages[activeCategory]
  const lastBotMsg = [...messages].reverse().find(m => m.role === 'assistant')


  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [allMessages, loading])

  useEffect(() => {
    setActiveSubTab('All')
  }, [activeCategory])

  function formatTime(d: Date) {
    return d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })
  }

  async function handleSend(query: string) {
    if (!query.trim() || loading) return
    const cat = activeCategory
    const modePrefix = responseMode === 'concise'
      ? 'Give a concise answer in 2-3 sentences. '
      : ''
    const finalQuery = modePrefix + query.trim()

    const userMsg: Message = { id: generateId(), role: 'user', content: query.trim(), timestamp: new Date() }
    setAllMessages(prev => ({ ...prev, [cat]: [...prev[cat], userMsg] }))
    setInput('')
    setLoading(true)

    const botId = generateId()
    setAllMessages(prev => ({ ...prev, [cat]: [...prev[cat], { id: botId, role: 'assistant', content: '', timestamp: new Date() }] }))

    try {
      let fullContent = ''
      let detectedCategory = ''
      let webSearchUsed = false
      let hasLocalResults = false

      for await (const chunk of sendChatStream(finalQuery, cat, webSearch)) {
        if (chunk.type === 'meta') {
          detectedCategory = chunk.category ?? ''
          webSearchUsed = chunk.web_search_used ?? false
          hasLocalResults = (chunk as any).has_local_results ?? false
          const autoWebTriggered = chunk.auto_web_triggered ?? false
          setAllMessages(prev => ({ ...prev, [cat]: prev[cat].map(m =>
            m.id === botId ? { ...m, category: detectedCategory, webSearchUsed, hasLocalResults, autoWebTriggered } : m
          )}))
        } else if (chunk.type === 'chunk' && chunk.content) {
          fullContent += chunk.content
          setAllMessages(prev => ({ ...prev, [cat]: prev[cat].map(m =>
            m.id === botId ? { ...m, content: fullContent } : m
          )}))
        } else if (chunk.type === 'done') {
          setLoading(false)
        } else if (chunk.type === 'error') {
          setAllMessages(prev => ({ ...prev, [cat]: prev[cat].map(m =>
            m.id === botId ? { ...m, content: `⚠️ Error: ${(chunk as any).message}` } : m
          )}))
          setLoading(false)
        }
      }
    } catch {
      setAllMessages(prev => ({ ...prev, [cat]: prev[cat].map(m =>
        m.id === botId
          ? { ...m, content: '⚠️ Cannot connect to API server. Make sure it is running on port 8000.' }
          : m
      )}))
    } finally {
      setLoading(false)
    }
  }

  function handleKeyDown(e: React.KeyboardEvent<HTMLInputElement>) {
    if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); handleSend(input) }
  }

  const showWelcome = messages.length === 0
  const lastMsg = messages[messages.length - 1]
  const showFollowUps = !loading && lastMsg?.role === 'assistant' && lastMsg.content.length > 0

  const FOLLOW_UPS: Record<Category, string[]> = {
    COLLEGE: ['What are the hostel facilities?', 'Tell me about placements', 'What courses are offered?', 'What is the fee structure?'],
    EXAM: ['What is the syllabus?', 'How to prepare?', 'What are the important dates?', 'What is the exam pattern?'],
    COMPARISON: ['Which has better placements?', 'Compare fees of both', 'Which has better NIRF rank?', 'Compare hostel facilities'],
    PREDICTOR: ['What branches can I get?', 'Show private college options', 'What about government colleges?', 'What is the cutoff trend?'],
    TOP_COLLEGES: ['Show colleges in another city', 'Which has best placements?', 'Filter by government colleges', 'Which has lowest fees?'],
  }

  return (
    <div className="h-screen bg-gray-50 flex overflow-hidden">

      {/* ── Left Sidebar ── */}
      <aside className="w-60 bg-white border-r border-gray-100 flex flex-col flex-shrink-0">
        <div className="px-4 py-4 border-b border-gray-100">
          <div className="flex items-center gap-2.5">
            <div className="w-8 h-8 rounded-lg bg-indigo-600 flex items-center justify-center text-white font-black text-sm shadow-sm">D</div>
            <div>
              <p className="font-bold text-gray-900 text-sm">DegreeFYD</p>
              <p className="text-[10px] text-gray-400">AI Assistant</p>
            </div>
          </div>
        </div>
        <nav className="flex-1 px-2 py-3 space-y-0.5 overflow-y-auto">
          <p className="text-[10px] font-semibold text-gray-400 uppercase tracking-wider px-2 mb-2">Categories</p>
          {CATEGORIES.map((cat) => {
            const c = CATEGORY_CONFIG[cat]
            const isActive = activeCategory === cat
            const hasHistory = allMessages[cat].length > 0
            return (
              <button key={cat} onClick={() => setActiveCategory(cat)}
                className={`w-full flex items-center gap-2.5 px-3 py-2.5 rounded-xl text-left transition-all ${
                  isActive ? 'bg-indigo-50 text-indigo-700' : 'text-gray-600 hover:bg-gray-50 hover:text-gray-900'
                }`}>
                <span className="text-base leading-none">{c.icon}</span>
                <span className="text-sm font-medium flex-1">{c.label}</span>
                {hasHistory && !isActive && <span className="w-1.5 h-1.5 rounded-full bg-indigo-400" />}
                {isActive && <span className="w-1 h-4 rounded-full bg-indigo-500" />}
              </button>
            )
          })}
        </nav>
        <div className="px-3 py-3 border-t border-gray-100">
          <a href="https://degreefyd.com/" target="_blank" rel="noopener noreferrer"
            className="flex items-center gap-2 w-full px-3 py-2 rounded-xl bg-emerald-50 hover:bg-emerald-100 transition-all">
            <span className="w-2 h-2 rounded-full bg-emerald-500 flex-shrink-0" />
            <span className="text-xs font-semibold text-emerald-700">Get Free Counselling</span>
          </a>
        </div>
      </aside>

      {/* ── Main area ── */}
      <main className="flex-1 flex flex-col min-w-0">

        {/* ── Chat header ── */}
        <header className="bg-white border-b border-gray-100 px-6 py-4 flex items-center justify-between flex-shrink-0 gap-4">
          <div className="flex items-center gap-3 min-w-0">
            <span className="text-2xl flex-shrink-0">{config.icon}</span>
            <div className="min-w-0">
              <h1 className="font-bold text-gray-900 text-base leading-tight">{config.label}</h1>
              <p className="text-xs text-gray-400 truncate mt-0.5">{config.desc}</p>
            </div>
          </div>
          <div className="flex items-center gap-2 flex-shrink-0">
            {messages.length > 0 && (
              <button onClick={() => setAllMessages(prev => ({ ...prev, [activeCategory]: [] }))}
                className="p-2 rounded-xl text-gray-400 hover:text-red-500 hover:bg-red-50 transition-all duration-150" title="Clear chat">
                <Trash2 size={15} />
              </button>
            )}
          </div>
        </header>

        {/* ── Messages ── */}
        <div className="flex-1 overflow-y-auto px-6 py-6">
          {showWelcome ? (
            <div className="max-w-2xl mx-auto">
              <div className="text-center mb-6 mt-4">
                <div className="w-14 h-14 rounded-2xl bg-indigo-600 flex items-center justify-center mx-auto mb-4 shadow-md">
                  <span className="text-white text-2xl font-black">D</span>
                </div>
                <h2 className="text-xl font-bold text-gray-900">How can I help you?</h2>
                <p className="text-gray-400 mt-1 text-sm">Ask anything about {config.label.toLowerCase()}</p>
              </div>
              {/* Sub-tabs below subtitle */}
              <div className="flex items-center gap-2 flex-wrap justify-center mb-5">
                {config.subTabs.map((tab) => (
                  <button key={tab} onClick={() => setActiveSubTab(tab)}
                    className={`px-4 py-1.5 rounded-full text-xs font-semibold whitespace-nowrap transition-all duration-150 border ${
                      activeSubTab === tab
                        ? 'bg-gray-900 text-white border-gray-900'
                        : 'bg-white text-gray-500 border-gray-200 hover:border-indigo-300 hover:text-indigo-600'
                    }`}>{tab}</button>
                ))}
              </div>
              <div className="space-y-2">
                {(config.subTabSamples[activeSubTab] ?? config.samples).map((sample, i) => (
                  <button key={sample} onClick={() => handleSend(sample)}
                    className="animate-slide-up w-full flex items-center justify-between px-4 py-3.5 rounded-xl bg-white border border-gray-200 hover:border-indigo-300 hover:bg-indigo-50 text-left text-sm text-gray-700 transition-all group shadow-sm"
                    style={{ animationDelay: `${i * 60}ms` }}>
                    <span className="leading-snug font-medium">{sample}</span>
                    <ChevronRight size={15} className="text-gray-300 group-hover:text-indigo-500 flex-shrink-0 ml-3 transition-colors" />
                  </button>
                ))}
              </div>
            </div>
          ) : (
            <div className="max-w-3xl mx-auto space-y-5">
              {messages.map((msg, idx) => (
                <div key={msg.id} className={idx === messages.length - 1 ? 'animate-msg-in' : ''}>
                  {msg.role === 'user' ? (
                    <div className="flex justify-end">
                      <div className="flex flex-col items-end gap-1">
                        <div className="max-w-[68%] bg-gradient-to-br from-indigo-500 to-indigo-700 text-white px-4 py-3 rounded-2xl rounded-tr-sm text-sm leading-relaxed shadow-md">
                          {msg.content}
                        </div>
                        <span className="text-[10px] text-gray-400 mr-1">{formatTime(msg.timestamp)}</span>
                      </div>
                    </div>
                  ) : (
                    <div className="flex gap-3">
                      <div className="w-8 h-8 rounded-xl bg-gradient-to-br from-indigo-500 to-violet-600 flex items-center justify-center text-white font-bold text-xs flex-shrink-0 mt-0.5 shadow-md ring-2 ring-indigo-100">D</div>
                      <div className="flex-1 min-w-0">
                        {(msg.category || msg.hasLocalResults || msg.webSearchUsed || msg.autoWebTriggered) && (
                          <div className="flex items-center gap-1.5 mb-2 flex-wrap">
                            {msg.category && <span className="text-[10px] px-2 py-0.5 rounded-full bg-indigo-100 text-indigo-700 font-semibold uppercase tracking-wide">{msg.category}</span>}
                            {msg.hasLocalResults && <span className="text-[10px] px-2 py-0.5 rounded-full bg-emerald-100 text-emerald-700 font-semibold flex items-center gap-1"><Database size={8} />Local</span>}
                            {msg.webSearchUsed && !msg.autoWebTriggered && <span className="text-[10px] px-2 py-0.5 rounded-full bg-amber-100 text-amber-700 font-semibold flex items-center gap-1"><Globe size={8} />Web</span>}
                            {msg.autoWebTriggered && <span className="text-[10px] px-2 py-0.5 rounded-full bg-orange-100 text-orange-700 font-semibold flex items-center gap-1"><Zap size={8} />Auto Web</span>}
                          </div>
                        )}
                        <div className="bg-white border-l-4 border-l-indigo-400 border border-gray-100 rounded-2xl rounded-tl-none px-5 py-4 text-sm text-gray-800 shadow-sm overflow-x-auto">
                          {msg.content ? (
                            <div className="prose prose-sm max-w-none prose-p:my-1.5 prose-p:leading-relaxed prose-headings:font-bold prose-headings:text-gray-900 prose-h1:text-base prose-h2:text-sm prose-h3:text-sm prose-headings:mt-3 prose-headings:mb-1.5 prose-strong:text-gray-900 prose-li:my-0.5 prose-ul:my-1.5 prose-ol:my-1.5 prose-table:text-xs prose-table:border-collapse prose-th:bg-indigo-50 prose-th:text-indigo-800 prose-th:font-semibold prose-th:px-3 prose-th:py-2 prose-th:border prose-th:border-indigo-100 prose-td:px-3 prose-td:py-2 prose-td:border prose-td:border-gray-100 prose-td:align-top prose-code:bg-gray-100 prose-code:px-1.5 prose-code:py-0.5 prose-code:rounded prose-code:text-indigo-700 prose-code:text-xs prose-a:text-indigo-600">
                              <ReactMarkdown remarkPlugins={[remarkGfm]} rehypePlugins={[rehypeRaw]}>{msg.content}</ReactMarkdown>
                            </div>
                          ) : (
                            <span className="flex gap-1.5 items-center h-5">
                              <span className="w-2.5 h-2.5 bg-indigo-400 rounded-full animate-bounce" style={{animationDelay:'0ms'}} />
                              <span className="w-2.5 h-2.5 bg-indigo-300 rounded-full animate-bounce" style={{animationDelay:'160ms'}} />
                              <span className="w-2.5 h-2.5 bg-indigo-200 rounded-full animate-bounce" style={{animationDelay:'320ms'}} />
                            </span>
                          )}
                        </div>
                        <div className="text-[10px] text-gray-400 mt-1.5 ml-1">{formatTime(msg.timestamp)}</div>
                      </div>
                    </div>
                  )}
                </div>
              ))}
              {showFollowUps && (
                <div className="pl-11 animate-fade-in">
                  <p className="text-xs text-gray-400 mb-2 font-medium">You might also ask:</p>
                  <div className="flex flex-wrap gap-2">
                    {FOLLOW_UPS[activeCategory].map((q, i) => (
                      <button key={q} onClick={() => handleSend(q)}
                        className="animate-slide-up text-xs px-3 py-1.5 rounded-full bg-white border border-gray-200 text-gray-600 hover:border-indigo-300 hover:text-indigo-700 hover:bg-indigo-50 transition-all font-medium shadow-sm"
                        style={{ animationDelay: `${i * 50}ms` }}>
                        {q}
                      </button>
                    ))}
                  </div>
                </div>
              )}
              <div ref={bottomRef} />
            </div>
          )}
        </div>

        {/* ── Input bar ── */}
        <div className="bg-white border-t border-gray-100 px-6 py-5 flex-shrink-0">
          <div className="max-w-3xl mx-auto">
            {/* Controls row above input */}
            <div className="flex items-center gap-2 mb-3">
              <div className="flex items-center bg-gray-100 rounded-xl p-1 gap-0.5">
                <button onClick={() => setResponseMode('concise')}
                  className={`px-3.5 py-1.5 rounded-lg text-xs font-semibold transition-all duration-150 ${
                    responseMode === 'concise' ? 'bg-white text-indigo-700 shadow-sm' : 'text-gray-400 hover:text-gray-700'
                  }`}>Concise</button>
                <button onClick={() => setResponseMode('detailed')}
                  className={`px-3.5 py-1.5 rounded-lg text-xs font-semibold transition-all duration-150 ${
                    responseMode === 'detailed' ? 'bg-white text-indigo-700 shadow-sm' : 'text-gray-400 hover:text-gray-700'
                  }`}>Detailed</button>
              </div>
              <button onClick={() => setWebSearch(v => !v)}
                className={`flex items-center gap-1.5 px-3.5 py-1.5 rounded-xl text-xs font-semibold border transition-all duration-150 ${
                  webSearch ? 'bg-amber-50 border-amber-200 text-amber-700' : 'bg-white border-gray-200 text-gray-500 hover:border-indigo-200 hover:text-indigo-600'
                }`}>
                {webSearch ? <Globe size={13} /> : <Globe2 size={13} />}
                {webSearch ? 'Web ON' : 'Web OFF'}
              </button>
              {/* Self-RAG auto-web indicator */}
              {lastBotMsg?.autoWebTriggered && (
                <div className="animate-fade-in flex items-center gap-1.5 px-3 py-1.5 rounded-xl text-xs font-semibold bg-orange-50 border border-orange-200 text-orange-600">
                  <Zap size={12} className="animate-pulse" />
                  <span>Auto web search was used</span>
                </div>
              )}
            </div>
            <div className="flex items-center gap-3 bg-gray-50 border-2 border-gray-200 rounded-2xl px-5 py-3.5 focus-within:border-indigo-400 focus-within:bg-white focus-within:shadow-lg focus-within:shadow-indigo-50 transition-all duration-200">
              <input
                type="text"
                value={input}
                onChange={(e) => setInput(e.target.value)}
                onKeyDown={handleKeyDown}
                placeholder={`Ask about ${config.label.toLowerCase()}…`}
                className="flex-1 bg-transparent text-sm text-gray-800 placeholder-gray-400 outline-none"
                disabled={loading}
              />
              <button onClick={() => handleSend(input)} disabled={!input.trim() || loading}
                className="w-10 h-10 rounded-xl bg-indigo-600 hover:bg-indigo-700 active:scale-95 disabled:bg-gray-200 disabled:cursor-not-allowed flex items-center justify-center transition-all duration-150 flex-shrink-0 shadow-sm">
                {loading ? <Loader2 size={16} className="text-white animate-spin" /> : <Send size={15} className="text-white" />}
              </button>
            </div>
            <p className="text-center text-[11px] text-gray-400 mt-2.5">DegreeFYD AI is experimental — verify important information independently</p>
          </div>
        </div>

      </main>
    </div>
  )
}
