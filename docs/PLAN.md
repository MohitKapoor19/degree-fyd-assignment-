# DegreeFYD RAG Chatbot - Implementation Plan

## Project Overview

Building a **ShikshaGPT-style** education chatbot using RAG (Retrieval Augmented Generation) with:
- **Groq API** for LLM (`compound-beta` for web search, `llama-3.1-8b-instant` for routing)
- **ChromaDB** for vector/semantic storage
- **SQLite** for structured data queries
- **Category-based routing** for different query types
- **No LangChain** — direct SDK calls for full control and speed

---

## Data Analysis

### Source File
- **File**: `degreefyd_data.jsonl`
- **Total Records**: ~14,810

### Data Distribution by Type
| Type | Count | Description |
|------|-------|-------------|
| `comparison` | 12,559 | College vs College comparisons |
| `college` | 1,903 | Individual college information |
| `blog` | 161 | Educational articles |
| `exam` | 141 | Exam dates, patterns, tips |
| `course` | 34 | Course-specific information |
| `page` | 12 | General pages |

### Data Structure (per record)
```json
{
  "url": "https://degreefyd.com/...",
  "type": "comparison|college|blog|exam|course|page",
  "content": "Raw text content from the page..."
}
```

### Key Content Patterns (used by data_extractor.py)
| Field | Pattern in content |
|-------|-------------------|
| College names | `"Compare X and Y across"` / `"Login X vs Y Shortlist"` |
| NIRF Rank | `"NIRF Rank: #56 4.5"` (rating follows rank) |
| Fees | `"starting from INR 41,000"` / `"range between INR X and INR Y"` |
| Established Year | `"Established Year 1997 1985"` (both on same line) |
| Total Students | `"Total Students 65000 Not Available"` |
| College Type | `"College Type Private Private"` |
| Location | `"Salem, Tamil Nadu NIRF Rank: #56"` |
| Exam Date | `"CLAT Exam Date 7 December 2025"` |
| Conducting Body | `"Conducting Body Consortium of NLUs"` |

---

## Architecture

```
┌──────────────────────────────────────────────────────────────────────┐
│                          USER INTERFACES                             │
│                                                                      │
│  Streamlit (port 8501)          Vite + React (port 5173)             │
│  ui/app.py                      frontend/src/App.tsx                 │
│                                                                      │
│  ┌──────────┬────────┬─────────────┬───────────┬─────────────┐       │
│  │ Colleges │ Exams  │ Comparisons │Predictors │ Top Colleges│       │
│  └──────────┴────────┴─────────────┴───────────┴─────────────┘       │
│  [Web Search Toggle: ON/OFF]                                         │
└──────────────────────────────┬───────────────────────────────────────┘
                               │ HTTP POST /chat
                               ▼
┌──────────────────────────────────────────────────────────────────────┐
│                    FastAPI Backend (port 8000)                       │
│                         api/main.py                                  │
│              /chat  (non-streaming)                                  │
│              /chat/stream  (SSE streaming)                           │
└──────────────────────────────┬───────────────────────────────────────┘
                               │
                               ▼
┌──────────────────────────────────────────────────────────────────────┐
│                    QUERY ROUTER (Groq LLM)                           │
│              llama-3.1-8b-instant + regex fast-path                  │
│         Categories: COLLEGE, EXAM, COMPARISON, PREDICTOR,            │
│                     TOP_COLLEGES, GENERAL                            │
│         Extracts: college_names, exam_names, location, rank_score    │
└──────────────────────────────┬───────────────────────────────────────┘
                               │
        ┌──────────────────────┼──────────────────────┐
        ▼                      ▼                      ▼
┌───────────────┐    ┌─────────────────┐    ┌───────────────┐
│   SQLite DB   │    │    ChromaDB     │    │  Web Search   │
│  (Structured) │    │   (Semantic)    │    │  (Fallback)   │
│               │    │                 │    │               │
│ - colleges    │    │ all-MiniLM-L6   │    │ Only if:      │
│ - exams       │    │ -v2 embeddings  │    │ 1. No local   │
│ - comparisons │    │ - type metadata │    │    results    │
│ - blogs       │    │ - url metadata  │    │ 2. Toggle ON  │
└───────┬───────┘    └────────┬────────┘    └───────┬───────┘
        │                     │                     │
        └─────────────────────┼─────────────────────┘
                              ▼
┌──────────────────────────────────────────────────────────────────────┐
│                   GROQ LLM (compound-beta)                           │
│              Generates final conversational response                 │
│              Web search via Groq tool_choice when needed             │
└──────────────────────────────────────────────────────────────────────┘
```

---

## Query Flow Logic

```
User Query
    │
    ▼
┌─────────────────────────────────┐
│ 1. Fast Regex Router            │
│    Common patterns matched      │
│    instantly (no API call)      │
│    Falls back to Groq LLM       │
└───────────────┬─────────────────┘
                │
                ▼
┌─────────────────────────────────┐
│ 2. Category Handler             │
│    SQLite structured lookup     │
│    ChromaDB semantic search     │
│    Both combined as context     │
└───────────────┬─────────────────┘
                │
                ▼
┌─────────────────────────────────┐
│ 3. Web Search Decision          │
│    has_local_results=False      │
│    AND web_search_enabled=True  │
│    → use Groq compound-beta     │
│    Otherwise → local only       │
└───────────────┬─────────────────┘
                │
                ▼
┌─────────────────────────────────┐
│ 4. Generate Response            │
│    Groq LLM with full context   │
│    Streaming or non-streaming   │
└─────────────────────────────────┘
```

---

## Category Handlers

### 1. COLLEGE (`handlers/college_handler.py`)
**Queries**: Admissions, fees, facilities, placements, hostel

**Handler Logic**:
1. Extract college names → SQLite `colleges` table lookup
2. If no names but location given → `query_top_colleges(location=...)`
3. ChromaDB semantic search (`type='college'` + `type='comparison'`)
4. Format: NIRF rank, rating, type, fees, courses, students, location → LLM

### 2. EXAM (`handlers/exam_handler.py`)
**Queries**: Exam dates, admit cards, patterns, results, syllabus

**Handler Logic**:
1. Extract exam names → SQLite `exams` table lookup
2. ChromaDB semantic search (`type='exam'` + `type='blog'`)
3. Format: exam date, conducting body, mode, duration, application dates → LLM

### 3. COMPARISON (`handlers/comparison_handler.py`)
**Queries**: Compare colleges on fees, rankings, placements, facilities

**Handler Logic**:
1. Extract both college names → SQLite `comparisons` table lookup
2. Also fetch individual college records for each
3. ChromaDB semantic search for comparison docs
4. Format as structured table with 8 fields: fees, NIRF, rating, type, location, courses, year, students → LLM

### 4. PREDICTOR (`handlers/predictor_handler.py`)
**Queries**: College predictions based on rank/score/percentile

**Handler Logic**:
1. Parse rank/score from query string
2. Query SQLite: `nirf_rank <= max_rank` (rank used as NIRF proxy)
3. ChromaDB semantic search for cutoff/predictor content
4. Format ranked list with NIRF, rating, fees, location, type → LLM

### 5. TOP_COLLEGES (`handlers/top_colleges_handler.py`)
**Queries**: Rankings by location, type, course

**Handler Logic**:
1. Extract location → `query_top_colleges(location=...)` from SQLite
2. ChromaDB semantic search for additional context
3. Format ranked list sorted by NIRF rank → LLM

### 6. GENERAL
**Queries**: Blogs, advice, general education questions

**Handler Logic**:
1. ChromaDB semantic search (no category filter)
2. Retrieve top 5 relevant chunks
3. RAG → LLM generates response

---

## Web Search Integration

### How It Works (`src/web_search.py`)
- Model: `compound-beta` (Groq) — supports native web search tool
- Web search is triggered **only when**:
  1. Local results are insufficient (`has_local_results = False`)
  2. AND user toggle is `ON` (`web_search_enabled = True`)
- Both streaming and non-streaming modes supported
- `should_use_web_search(results)` helper checks result quality

---

## Database Schema

### SQLite Tables (actual schema in `db_setup.py`)

#### `colleges`
```sql
CREATE TABLE colleges (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE,
    location TEXT,           -- "Salem, Tamil Nadu"
    college_type TEXT,       -- "Private" / "Government"
    established_year INTEGER,
    nirf_rank INTEGER,
    rating REAL,             -- e.g. 4.5 (out of 5)
    total_students INTEGER,
    courses_offered INTEGER,
    fee_range TEXT,          -- "41,000" or "1,000 - 64,000"
    url TEXT
);
```

#### `exams`
```sql
CREATE TABLE exams (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    full_name TEXT,
    exam_date TEXT,
    application_start TEXT,
    application_end TEXT,
    result_date TEXT,
    conducting_body TEXT,
    exam_mode TEXT,
    duration TEXT,
    url TEXT,
    raw_content TEXT
);
```

#### `comparisons`
```sql
CREATE TABLE comparisons (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    college_1 TEXT NOT NULL,
    college_2 TEXT NOT NULL,
    college_1_fees TEXT,      college_2_fees TEXT,
    college_1_nirf INTEGER,   college_2_nirf INTEGER,
    college_1_courses INTEGER,college_2_courses INTEGER,
    college_1_year INTEGER,   college_2_year INTEGER,
    college_1_students INTEGER,college_2_students INTEGER,
    college_1_type TEXT,      college_2_type TEXT,
    college_1_rating REAL,    college_2_rating REAL,
    college_1_location TEXT,  college_2_location TEXT,
    url TEXT,
    UNIQUE(college_1, college_2)
);
```

#### `blogs`
```sql
CREATE TABLE blogs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    title TEXT,
    author TEXT,
    date TEXT,
    college_mentioned TEXT,
    url TEXT UNIQUE,
    content TEXT
);
```

---

## ChromaDB Collection

### Collection: `degreefyd_docs`
**Embedding Model**: `sentence-transformers/all-MiniLM-L6-v2` (free, runs locally)

**Metadata Fields per document**:
- `type`: `comparison | college | exam | blog | course | page`
- `url`: Source URL
- `college_names`: Comma-separated college names (for filtering)
- `exam_names`: Comma-separated exam names (for filtering)

---

## Project Structure

```
DegreeFYD Assignment/
├── README.md                   # Setup and run instructions
├── requirements.txt            # Python dependencies (no LangChain)
├── .env                        # GROQ_API_KEY
├── .env.example                # Template
├── degreefyd_data.jsonl        # Source data (~14,810 records)
│
├── docs/
│   └── PLAN.md                 # This file
│
├── src/
│   ├── __init__.py
│   ├── config.py               # Paths, model names, settings
│   ├── data_extractor.py       # Parse JSONL → structured fields
│   │                           # Extractors: names, fees, NIRF, rating,
│   │                           # type, location, year, students, exam info
│   ├── db_setup.py             # SQLite schema + ingestion + query helpers
│   ├── vector_store.py         # ChromaDB ingestion + semantic search
│   ├── query_router.py         # Regex fast-path + Groq LLM classifier
│   ├── web_search.py           # Groq compound-beta web search wrapper
│   ├── rag_chain.py            # Main RAG pipeline orchestrator
│   └── handlers/
│       ├── __init__.py
│       ├── college_handler.py
│       ├── exam_handler.py
│       ├── comparison_handler.py
│       ├── predictor_handler.py
│       └── top_colleges_handler.py
│
├── data/                       # Auto-created on ingestion
│   ├── degreefyd.db            # SQLite database
│   └── chroma_db/              # ChromaDB vector store
│
├── api/
│   └── main.py                 # FastAPI backend (port 8000)
│
├── ui/
│   └── app.py                  # Streamlit UI (port 8501)
│
├── frontend/                   # Vite + React UI (port 5173)
│   ├── src/
│   │   ├── App.tsx             # Main chat component
│   │   ├── api.ts              # Fetch + SSE streaming client
│   │   ├── constants.ts        # Category configs + sample questions
│   │   ├── types.ts            # TypeScript interfaces
│   │   ├── main.tsx
│   │   └── index.css
│   ├── package.json
│   ├── vite.config.ts          # Proxy /api → localhost:8000
│   └── tailwind.config.js
│
└── scripts/
    ├── ingest_data.py          # One-time ingestion runner
    └── test_queries.py         # Test all 5 categories
```

---

## Dependencies (`requirements.txt`)

```
# LLM & RAG
groq>=0.4.0
chromadb>=0.4.0
sentence-transformers>=2.2.0

# Data Processing
pandas>=2.0.0
regex>=2023.0.0

# API & UI
fastapi>=0.100.0
uvicorn>=0.23.0
streamlit>=1.28.0

# Utilities
python-dotenv>=1.0.0
pydantic>=2.0.0
```

> `sqlite3` is Python built-in — no install needed.
> LangChain is **not used** — direct SDK calls throughout.

---

## Models Used

| Component | Model |
|-----------|-------|
| **LLM + Web Search** | `compound-beta` (Groq) |
| **Query Router** | `llama-3.1-8b-instant` (Groq) |
| **Embeddings** | `all-MiniLM-L6-v2` (local, free) |

---

## Environment Variables

```
GROQ_API_KEY=your_groq_api_key_here
```

---

## How to Run

```bash
# 1. Install Python deps
pip install -r requirements.txt

# 2. Ingest data (one-time, ~15-20 min)
python scripts/ingest_data.py

# 3. Start API
python api/main.py

# 4a. Streamlit UI
streamlit run ui/app.py

# 4b. OR Vite + React
cd frontend && npm install && npm run dev
```

---

## API Endpoints

### POST `/chat`
```json
Request:
{
  "query": "How much is the fee at DTU?",
  "category": "COLLEGE",
  "web_search_enabled": false
}

Response:
{
  "answer": "The fee at DTU...",
  "category_detected": "COLLEGE",
  "web_search_used": false,
  "has_local_results": true,
  "entities": {
    "college_names": ["DTU"],
    "exam_names": [],
    "location": null,
    "rank_score": null
  }
}
```

### POST `/chat/stream`
Same request body — returns SSE stream of JSON chunks.

### GET `/categories`
Returns all categories with sample questions.

### GET `/`
Health check.

---

## Key Design Decisions

- **No LangChain**: Direct `groq` + `chromadb` + `sqlite3` SDK calls — faster, simpler, easier to debug
- **Hybrid retrieval**: SQLite for exact structured lookups + ChromaDB for semantic similarity
- **Regex fast-path router**: Common patterns ("vs", "compare", "rank", "top colleges") matched instantly without an LLM call
- **`get_unique_colleges` merge strategy**: Best NIRF rank (lowest) wins across all comparison appearances; missing fields filled from later records
- **`row_factory` for raw SQL**: Handlers using raw SQL use `conn.row_factory` to return named dicts, immune to column order changes
- **Web search is conservative**: Only fires when `has_local_results=False` AND toggle is ON — minimises Groq API usage
- **Streaming**: FastAPI SSE endpoint for real-time token streaming in both UIs

---

## Performance Optimizations (Feb 2026)

### 1. **Connection Caching (Singleton Pattern)**
**File**: `src/vector_store.py`

**Problem**: Every query reconnected to ChromaDB and reloaded the embedding model (~2-3s overhead per request)

**Solution**: Implemented singleton pattern with global caches:
```python
_embedding_fn = None      # Loaded once at startup
_chroma_client = None     # Persistent client cached
_collection = None        # Collection cached
```

**Impact**: 
- First query: normal speed
- Subsequent queries: **3-5x faster** (no reconnection overhead)
- Memory: ~500MB for embedding model (loaded once, shared across all requests)

---

### 2. **LRU Query Cache**
**File**: `src/rag_chain.py`

**Problem**: Repeated identical queries (e.g., sample questions) hit the full RAG pipeline every time

**Solution**: In-memory LRU cache (max 128 queries):
```python
_query_cache: Dict[str, Dict] = {}
_cache_key(query, web_search_enabled) → md5 hash
```

**Behavior**:
- Only caches **non-streaming** responses (streaming must be live)
- Cache key includes query + web_search_enabled flag
- FIFO eviction when cache exceeds 128 entries

**Impact**:
- Repeated queries: **instant response** from cache
- Check cache stats: `GET /health` returns `cached_queries` count

---

### 3. **FastAPI Startup Warmup**
**File**: `api/main.py`

**Problem**: First query after server start was very slow (loading ChromaDB + embeddings)

**Solution**: Added `lifespan` event handler:
```python
@asynccontextmanager
async def lifespan(app: FastAPI):
    print("[API] Warming up ChromaDB + embedding model...")
    warmup()  # Pre-loads collection and embeddings
    yield
```

**Impact**: 
- First query is now fast
- Server startup takes ~5-10s longer (acceptable trade-off)

---

### 4. **Query Router Accuracy Improvements**
**File**: `src/query_router.py`

**Problem**: Queries like "How to get admission to VIT Vellore?" were misclassified as PREDICTOR instead of COLLEGE

**Root Cause**: 
- `fast_route()` checked PREDICTOR patterns before COLLEGE patterns
- LLM prompt lacked clear examples distinguishing the two

**Solution**:
1. **Reordered `fast_route()` checks**:
   ```python
   # COLLEGE patterns checked BEFORE PREDICTOR
   college_specific = ['admission to', 'admission in', 'fee at', 'hostel at', ...]
   if any(kw in query_lower for kw in college_specific):
       return 'COLLEGE'
   
   # PREDICTOR only if rank/score mentioned
   if re.search(r'\d+\s*(?:rank|percentile)', query_lower):
       return 'PREDICTOR'
   ```

2. **Enhanced LLM prompt with examples**:
   ```
   COLLEGE: "How to get admission to VIT Vellore" ← specific college
   PREDICTOR: "Which colleges with JEE rank 5000" ← has rank, wants suggestions
   ```

**Impact**:
- Admission queries now correctly route to COLLEGE
- Predictor queries with explicit ranks route correctly
- Fast-path hits ~70% of queries (no LLM call needed)

---

### 5. **React Frontend: Streaming + Markdown**
**Files**: `frontend/src/App.tsx`, `frontend/src/api.ts`

**Changes**:
1. **Switched from `/chat` to `/chat/stream`**:
   - Live token-by-token output using Server-Sent Events (SSE)
   - Placeholder message with bouncing dots while streaming
   - Real-time content updates as tokens arrive

2. **Added `react-markdown` rendering**:
   ```tsx
   <ReactMarkdown>{msg.content}</ReactMarkdown>
   ```
   - **Bold**, `code`, tables, lists now render properly
   - Added `@tailwindcss/typography` for prose styling

3. **Improved loading UX**:
   - Empty bot message appears immediately when user sends query
   - Bouncing dots show while waiting for first token
   - Content streams in character-by-character
   - Badges (category, local/web) appear when metadata arrives

**Impact**:
- Feels **much faster** (user sees response start immediately)
- Markdown formatting makes responses more readable
- Better visual feedback during generation

---

### 6. **Streamlit UI Redesign**
**File**: `ui/app.py`

**Changes**: Complete redesign to match ShikshaGPT mobile UI:
- **Centered narrow layout** (max-width: 520px, no sidebar)
- **Blob logo** at top center (organic gradient shape)
- **Horizontal category cards** (scrollable, icon + label + active dot)
- **Watermark icon** in card header (opacity 0.08)
- **Plain sample rows** with `▶` arrow
- **"Get Free Counselling"** pill with green dot
- **Markdown rendering** for bot responses

**Impact**: Modern, mobile-first design matching industry standards

---

## Performance Metrics Summary

| Metric | Before | After | Improvement |
|--------|--------|-------|-------------|
| First query (cold start) | ~8-12s | ~8-12s | Same (warmup at startup) |
| Subsequent queries | ~5-8s | ~1-3s | **3-5x faster** |
| Repeated queries | ~5-8s | <100ms | **50-80x faster** (cache) |
| Time to first token (streaming) | N/A | ~500ms | New feature |
| Router accuracy (admission queries) | ~60% | ~95% | **+35%** |

---

## Cache Statistics (Runtime)

Check current cache status:
```bash
curl http://localhost:8000/health
# Returns: {"status": "ok", "cached_queries": 12}
```

Cache behavior:
- Max size: 128 queries
- Eviction: FIFO (oldest first)
- Key: MD5(query + web_search_enabled)
- Stored: Full response dict (answer, category, metadata)

---

## Self-RAG Implementation (Feb 2026)

### What is Self-RAG?
Standard RAG: `query → retrieve → generate`
Self-RAG adds LLM self-reflection steps before generation to verify retrieval quality.

### Implementation: `src/self_rag.py`

**ISREL Check** (`check_relevance`):
- Sends top-3 retrieved doc snippets + query to `llama-3.1-8b-instant`
- Returns: `relevant` / `partial` / `irrelevant`
- Cost: ~300ms, ~50 tokens

**Query Rephrasing** (`rephrase_query`):
- Called only when ISREL returns `irrelevant`
- Expands abbreviations, adds domain keywords
- Example: "IIT fees" → "IIT Indian Institute of Technology annual tuition fee structure"

### New Pipeline in `src/rag_chain.py`

```
Query
  │
  ▼
Route → category + entities
  │
  ▼
_get_raw_docs() → fast vector fetch (no full context build)
  │
  ▼
check_relevance() [ISREL]
  │
  ├─ relevant / partial ──────────────────────────────────────────────┐
  │                                                                   │
  └─ irrelevant                                                       │
       │                                                              │
       ▼                                                              │
  rephrase_query() → retry _get_raw_docs() → check_relevance()       │
       │                                                              │
       ├─ relevant / partial ──────────────────────────────────────── ┤
       │                                                              │
       └─ still irrelevant → auto_web_triggered = True               │
                                                                      │
                                                                      ▼
                                                          _build_context() → full handler
                                                                      │
                                                                      ▼
                                                          query_with_web_search()
                                                          (use_web = user_toggle OR auto_web)
                                                                      │
                                                                      ▼
                                                              Stream to frontend
```

### Frontend Changes for Self-RAG
- New **⚡ Auto Web** orange badge on bot messages when auto-triggered
- Distinct from amber **Web** badge (user-toggled)
- `autoWebTriggered` field added to `Message` type in `types.ts`
- `auto_web_triggered` exposed in SSE meta event from API

### Performance Impact
| Scenario | Extra Latency |
|---|---|
| Relevant docs found | +~300ms (ISREL check) |
| Irrelevant → rephrase → relevant | +~600ms |
| Both fail → auto web | +~600ms then web search |

---

## React UI Overhaul (Feb 2026)

### Layout Change: Card → Sidebar + Chat
**Before**: Centered card with horizontal category scroll, fixed `maxHeight: 380px`
**After**: Full-height `h-screen` sidebar + main chat area (like ChatGPT/Claude)

**Sidebar** (`w-60`):
- Brand logo + "AI Assistant" label
- Category nav with active indicator bar + unread dot
- "Get Free Counselling" link → `https://degreefyd.com/` (opens new tab)

**Chat header**: Category icon + name + desc + sub-tabs + clear button

**Messages area**: `flex-1 overflow-y-auto` — truly full height, no fixed max

**Input bar**: Sticky bottom, `border-2` with focus glow (`shadow-indigo-50`), `w-10 h-10` send button with `active:scale-95`

**Controls row** (above input): Concise/Detailed toggle + Web ON/OFF toggle

### Animations Added (`src/index.css`)
```css
@keyframes msg-in    { from: opacity:0, translateY(10px) → to: opacity:1, translateY(0) }
@keyframes fade-in   { from: opacity:0 → to: opacity:1 }
@keyframes slide-up  { from: opacity:0, translateY(16px) → to: opacity:1, translateY(0) }
```
- Welcome cards: staggered `slide-up` (60ms per card)
- Chat messages: `msg-in` on last message only (prevents streaming glitch)
- Follow-up chips: staggered `slide-up` (50ms per chip)

### Markdown Fixes
- Added `rehype-raw` plugin → `<br>` and other HTML tags in content now render correctly
- `remark-gfm` already present → tables, bold, lists render properly

### Follow-up Questions
- After every bot response: 4 contextual follow-up chips per category
- Staggered animation on appearance

### Per-Category Chat History
- `allMessages: Record<Category, Message[]>` — each category has its own message array
- Blue dot on sidebar category when it has history but isn't active
- Switching categories preserves all chat history

---

## Updated Project Structure

```
DegreeFYD Assignment/
├── README.md
├── requirements.txt
├── .env
├── degreefyd_data.jsonl        # 14,810 records
│
├── docs/
│   ├── PLAN.md                 # This file — implementation details
│   ├── NOTES.md                # Zero-to-hero interview prep notes
│   └── eda.ipynb               # EDA notebook (IIT coverage analysis)
│
├── src/
│   ├── config.py
│   ├── data_extractor.py
│   ├── db_setup.py
│   ├── vector_store.py
│   ├── query_router.py
│   ├── web_search.py
│   ├── self_rag.py             # NEW: ISREL check + query rephrasing
│   ├── rag_chain.py            # UPDATED: Self-RAG pipeline
│   └── handlers/
│       ├── college_handler.py
│       ├── exam_handler.py
│       ├── comparison_handler.py
│       ├── predictor_handler.py
│       └── top_colleges_handler.py
│
├── api/
│   └── main.py                 # UPDATED: auto_web_triggered in SSE meta
│
├── frontend/
│   └── src/
│       ├── App.tsx             # UPDATED: sidebar layout, animations, Self-RAG badges
│       ├── api.ts              # UPDATED: auto_web_triggered in stream type
│       ├── types.ts            # UPDATED: autoWebTriggered on Message
│       ├── constants.ts
│       ├── index.css           # UPDATED: msg-in, fade-in, slide-up animations
│       └── main.tsx
│
└── data/
    ├── degreefyd.db
    └── chroma_db/
```

---

## Updated API Response (SSE Meta Event)

```json
{
  "type": "meta",
  "category": "COLLEGE",
  "web_search_used": true,
  "has_local_results": false,
  "auto_web_triggered": true
}
```

`auto_web_triggered: true` means Self-RAG detected irrelevant local docs and automatically enabled web search — user did NOT manually toggle it.

---

## Per-Sub-Tab Sample Questions (Feb 2026)

### What changed
Sub-tabs (e.g. "Admissions", "Fees", "Facility", "Placements") now show **different sample questions** on the welcome screen depending on which tab is active.

### Data: `frontend/src/constants.ts`
Added `subTabSamples: Record<string, string[]>` field to every category config. Each sub-tab has 5 unique, contextually relevant questions:

| Category | Sub-tabs |
|---|---|
| COLLEGE | All, Admissions, Fees, Facility, Placements |
| EXAM | All, Admit Card, Mock Test, Results, Dates |
| COMPARISON | All, Compare Colleges |
| PREDICTOR | All, College Predictor, Admission Chances |
| TOP_COLLEGES | All, Colleges by Location, Top Ranked Colleges |

### Type: `frontend/src/types.ts`
Added `subTabSamples: Record<string, string[]>` to `CategoryConfig` interface.

### Welcome screen: `frontend/src/App.tsx`
One-line change — samples now keyed by `activeSubTab`:
```tsx
config.subTabSamples[activeSubTab] ?? config.samples
```
Fallback to `config.samples` if sub-tab key not found.

---

## Sub-Tab Placement Redesign (Feb 2026)

### What changed
Sub-tabs moved **out of the top header bar** and into the **welcome screen**, sitting between the "Ask anything about X" subtitle and the sample question cards.

### Before
```
┌─ Header ─────────────────────────────────────────────────────┐
│  🏫 Colleges  Ask your query...   [All][Admissions][Fees]  🗑 │
└──────────────────────────────────────────────────────────────┘
```

### After
```
┌─ Header ──────────────────────────────────────────┐
│  🏫 Colleges  Ask your query...                🗑  │
└───────────────────────────────────────────────────┘

        [D logo]
   How can I help you?
   Ask anything about colleges

  [All] [Admissions] [Fees] [Facility] [Placements]

  ┌──────────────────────────────────────────────┐
  │ How can I get admission to VIT Vellore?   → │
  │ How much is the fee at DTU?               → │
  └──────────────────────────────────────────────┘
```

### Style
- Sub-tabs are **pill-style** (`rounded-full`) — dark fill + white text when active, white bg + gray border when inactive
- Centered horizontally with `justify-center flex-wrap` (wraps on narrow screens)
- Only visible on the welcome screen — hidden once a chat starts
- Header is now clean — only the trash icon remains when there are messages

---

## Chat Bubble UI Polish (Feb 2026)

### Changes in `frontend/src/App.tsx`

**User bubble**:
- Gradient fill: `bg-gradient-to-br from-indigo-500 to-indigo-700` (was flat `bg-indigo-600`)
- Deeper shadow: `shadow-md`
- Timestamp now shown **below** the bubble (right-aligned) — previously only bot had a timestamp

**Bot avatar**:
- Gradient: `bg-gradient-to-br from-indigo-500 to-violet-600`
- Ring: `ring-2 ring-indigo-100` — subtle white halo
- Deeper shadow: `shadow-md`

**Bot bubble**:
- Left accent stripe: `border-l-4 border-l-indigo-400` — visual anchor connecting to avatar
- `rounded-tl-none` — sharp top-left corner (connects to avatar visually)

**Typing indicator (loading dots)**:
- Larger: `w-2.5 h-2.5` (was `w-2 h-2`)
- Fading opacity: `bg-indigo-400` → `bg-indigo-300` → `bg-indigo-200`
- Delays: 0ms / 160ms / 320ms (was 0/150/300) — smoother wave

### Self-RAG Auto-Web Indicator
Added to the controls row (above input bar):
```tsx
{lastBotMsg?.autoWebTriggered && (
  <div className="animate-fade-in flex items-center gap-1.5 px-3 py-1.5 rounded-xl text-xs font-semibold bg-orange-50 border border-orange-200 text-orange-600">
    <Zap size={12} className="animate-pulse" />
    <span>Auto web search was used</span>
  </div>
)}
```
- `lastBotMsg` derived from `[...messages].reverse().find(m => m.role === 'assistant')`
- Disappears automatically when category is switched or chat is cleared

### Scroll Glitch Fix
`animate-msg-in` was applied to ALL messages on every re-render. During streaming (~100 re-renders), this restarted the animation each time causing a scroll jump.

**Fix**: Only animate the last message:
```tsx
className={idx === messages.length - 1 ? 'animate-msg-in' : ''}
```

---

## Future Optimization Opportunities

1. **ChromaDB doc_type filtering**: Currently searches all chunks; could filter by `doc_type` metadata in handlers for faster/cleaner results

2. **Redis cache layer**: Replace in-memory LRU with Redis for persistence across restarts and TTL-based expiration

3. **sessionStorage chat persistence**: Save `allMessages` to `sessionStorage` on every update, hydrate on page load — chats survive refresh but clear on tab close

4. **ISSUP check (Self-RAG step 2)**: After generation, verify answer is supported by retrieved docs — currently only ISREL is implemented

5. **Groq rate limiting**: Add exponential backoff retry logic for rate limit errors

6. **IIT data gap**: EDA showed only IIT Ropar has meaningful coverage (338 mentions). Other top IITs (Delhi: 9, Madras: 5) are severely underrepresented — need data enrichment or always-on web search for IIT queries
