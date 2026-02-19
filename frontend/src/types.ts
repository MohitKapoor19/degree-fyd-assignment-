export type Category = 'COLLEGE' | 'EXAM' | 'COMPARISON' | 'PREDICTOR' | 'TOP_COLLEGES'

export interface CategoryConfig {
  label: string
  icon: string
  desc: string
  subTabs: string[]
  samples: string[]
  subTabSamples: Record<string, string[]>
}

export interface Message {
  id: string
  role: 'user' | 'assistant'
  content: string
  category?: string
  webSearchUsed?: boolean
  hasLocalResults?: boolean
  autoWebTriggered?: boolean
  timestamp: Date
}

export interface ChatResponse {
  answer: string
  category_detected: string
  web_search_used: boolean
  has_local_results: boolean
  entities: {
    college_names: string[]
    exam_names: string[]
    location: string | null
    rank_score: string | null
  }
}
