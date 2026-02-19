# DegreeFYD — Deep Technical Interview Notes

> Every concept explained from first principles. Every decision justified. Every tradeoff documented.
> Read this before your interview. You built this — own it.

---

## Table of Contents
1. [Project Overview](#1-project-overview)
2. [RAG — The Core Concept](#2-rag--the-core-concept)
3. [Self-RAG — The Upgrade](#3-self-rag--the-upgrade)
4. [Embeddings & Vector Search — How Semantic Search Works](#4-embeddings--vector-search--how-semantic-search-works)
5. [The Tech Stack — Every Tool Justified](#5-the-tech-stack--every-tool-justified)
6. [The Data — What You're Working With](#6-the-data--what-youre-working-with)
7. [Ingestion Pipeline — Raw Text to Searchable DB](#7-ingestion-pipeline--raw-text-to-searchable-db)
8. [Query Router — How the System Classifies Intent](#8-query-router--how-the-system-classifies-intent)
9. [Category Handlers — The Retrieval Layer](#9-category-handlers--the-retrieval-layer)
10. [The RAG Chain — Full Orchestration](#10-the-rag-chain--full-orchestration)
11. [Web Search Integration — Groq compound-beta](#11-web-search-integration--groq-compound-beta)
12. [FastAPI Backend — The API Layer](#12-fastapi-backend--the-api-layer)
13. [SSE Streaming — How Real-Time Output Works](#13-sse-streaming--how-real-time-output-works)
14. [React Frontend — Architecture & State](#14-react-frontend--architecture--state)
15. [UI Design Decisions — Every Choice Explained](#15-ui-design-decisions--every-choice-explained)
16. [Performance Optimizations — Deep Dive](#16-performance-optimizations--deep-dive)
17. [Key Design Decisions — The "Why" Behind Everything](#17-key-design-decisions--the-why-behind-everything)
18. [Tradeoffs & Limitations — Be Honest](#18-tradeoffs--limitations--be-honest)
19. [Interview Q&A — 25 Questions With Full Answers](#19-interview-qa--25-questions-with-full-answers)
20. [Debugging Playbook](#20-debugging-playbook)
21. [File-by-File Reference](#21-file-by-file-reference)

---

## 1. Project Overview

**DegreeFYD** is an AI chatbot for Indian college admissions. Think of it like ChatGPT but specifically trained on data about Indian colleges, entrance exams, rankings, and comparisons.

A user can ask:
- "What is the fee at VIT Vellore?"
- "Compare IIT Bombay vs IIT Delhi"
- "Which colleges can I get with JEE rank 5000?"
- "When is JEE Main 2026?"

The system answers using **real data** from the DegreeFYD website — not just LLM hallucinations.

**The core problem it solves**: LLMs like GPT-4 don't have accurate, up-to-date data about specific Indian colleges. RAG fixes this by giving the LLM real data at query time.

---

## 2. What is RAG?

**RAG = Retrieval Augmented Generation**

Think of it like an open-book exam vs a closed-book exam.

- **Closed-book (pure LLM)**: The model answers from memory. It might hallucinate or have outdated info.
- **Open-book (RAG)**: Before answering, the model first looks up relevant documents from a database, then answers using those documents as reference.

### The 3 steps of RAG:

```
Step 1: RETRIEVE
User asks "What is the fee at DTU?"
→ Search database for documents about DTU fees
→ Get back 5 relevant text chunks

Step 2: AUGMENT
Take those 5 chunks and add them to the LLM prompt as "context"
→ "Here is information about DTU: [chunks]. Now answer: What is the fee at DTU?"

Step 3: GENERATE
LLM reads the context and generates an accurate answer
→ "The fee at DTU ranges from ₹1.5L to ₹2.5L per year..."
```

### Why RAG over fine-tuning?
- **Fine-tuning** = baking knowledge into the model weights. Expensive, slow, hard to update.
- **RAG** = plug in a database. Cheap, fast, easy to update. Just add new documents.

---

## 3. What is Self-RAG?

**Self-RAG** adds a "self-check" step. The LLM reflects on whether retrieved documents are actually useful before generating.

### The problem it solves:
Sometimes vector search returns documents that are technically similar in embedding space but don't actually answer the question. Example:
- Query: "IIT Delhi placement stats"
- Retrieved doc: "IIT Ropar placement 2024 report" ← wrong IIT, not useful

Standard RAG would use this bad context and generate a wrong answer. Self-RAG catches this.

### How it works in this project:

```
Step 1: Retrieve docs (same as standard RAG)

Step 2: ISREL Check — "Are these docs relevant?"
→ Send top-3 doc snippets + query to a fast LLM (llama-3.1-8b-instant)
→ LLM returns: "relevant" / "partial" / "irrelevant"
→ Cost: ~300ms, ~50 tokens

Step 3a: If "relevant" or "partial" → proceed normally

Step 3b: If "irrelevant":
→ Rephrase the query (expand abbreviations, add keywords)
→ Retry retrieval with rephrased query
→ Check relevance again

Step 4: If STILL irrelevant after retry:
→ Auto-enable web search (even if user didn't toggle it)
→ Show ⚡ "Auto Web" badge on the response
```

**Key insight**: Self-RAG doesn't change the data or the database. It's purely a **runtime quality gate**. No re-ingestion needed.

---

## 4. The Tech Stack — Why each tool?

| Tool | What it does | Why this and not X |
|---|---|---|
| **Groq** | LLM API (fast inference) | 10x faster than OpenAI for same models. `compound-beta` supports native web search. |
| **ChromaDB** | Vector database | Simple, runs locally, no server needed. Good for prototypes. |
| **SQLite** | Structured database | Built into Python, zero setup. For exact lookups (fees, NIRF rank). |
| **FastAPI** | Python web framework | Auto-generates docs, async support, Pydantic validation. |
| **sentence-transformers** | Embedding model | Free, runs locally. `all-MiniLM-L6-v2` is fast and small (80MB). |
| **React + Vite** | Frontend | Fast dev server, TypeScript support, modern. |
| **Tailwind CSS** | Styling | Utility-first, no CSS files needed, fast to prototype. |

**What is NOT used**: No LangChain (adds abstraction layers, harder to debug, adds latency — direct SDK calls give full control).

---

## 5. The Data

**Source**: `degreefyd_data.jsonl` — scraped from degreefyd.com

**Format**: JSONL = JSON Lines. Each line is one JSON object.
```json
{"url": "https://degreefyd.com/college/vit-vellore", "type": "college", "content": "VIT Vellore..."}
{"url": "https://degreefyd.com/compare/vit-vs-srm", "type": "comparison", "content": "Compare VIT and SRM..."}
```

**Distribution** (~14,810 total records):
| Type | Count | Used for |
|---|---|---|
| `comparison` | 12,559 | College vs college queries |
| `college` | 1,903 | Individual college info |
| `blog` | 161 | General advice, tips |
| `exam` | 141 | Exam dates, patterns |

**Key insight**: 85% of the data is comparisons. The system is very good at comparison queries but weaker for standalone college info — especially IITs which have very few records (IIT Delhi: only 9 mentions).

---

## 6. How data gets into the system (Ingestion)

Ingestion is a **one-time process** that runs before the server starts. It converts raw JSONL into two databases.

### Step 1: `data_extractor.py` — Parse raw text into structured fields

The raw content is messy text scraped from web pages. The extractor uses **regex patterns** to pull out structured fields.

Example raw content:
```
"VIT Vellore NIRF Rank: #11 4.2 College Type Private
 Established Year 1984 Fee starting from INR 1,98,000"
```
Extractors pull out: `nirf_rank=11`, `rating=4.2`, `college_type="Private"`, `established_year=1984`, `fee_range="1,98,000"`

### Step 2: `db_setup.py` — Insert into SQLite

Structured data goes into 4 SQLite tables: `colleges`, `exams`, `comparisons`, `blogs`.

`get_unique_colleges()` merges thousands of comparison records into one college row. Strategy: best NIRF rank (lowest number) wins; missing fields filled from later records.

### Step 3: `vector_store.py` — Chunk and embed into ChromaDB

Every record's raw `content` field is:
1. **Chunked**: Split into ~1000 character pieces with 200 char overlap
2. **Embedded**: Converted to a 384-dimensional vector using `all-MiniLM-L6-v2`
3. **Stored** in ChromaDB with metadata: `type`, `url`, `college_names`, `exam_names`

**Why chunking?** LLMs have token limits. We split large pages into chunks so we can retrieve only the relevant piece.

**Why overlap?** If a sentence is split across two chunks, overlap ensures neither chunk loses context at the boundary.

---

## 7. The Full Query Pipeline — Step by Step

When a user types "Compare VIT Vellore vs SRM Chennai fees":

```
1. Frontend (React) → POST /chat/stream

2. FastAPI → calls process_query() in rag_chain.py

3. Query Router
   → "vs" detected → COMPARISON
   → Extracts: college_names = ["VIT Vellore", "SRM Chennai"]

4. Self-RAG ISREL Check
   → ChromaDB search for comparison docs
   → check_relevance() → "relevant" ✓ → proceed

5. comparison_handler.py
   → SQLite: query comparisons table
   → ChromaDB: semantic search for comparison docs
   → Returns: (context_string, has_results=True, needs_web=False)

6. Web Search Decision
   → has_results=True, user toggle=OFF, auto_web=False → use_web=False

7. Groq compound-beta streams response tokens

8. SSE Stream
   → { type: "meta", category: "COMPARISON", web_search_used: false }
   → { type: "chunk", content: "VIT" } { type: "chunk", content: " Vellore" } ...
   → { type: "done" }

9. Frontend
   → meta: set badges on message
   → chunks: append to message content, re-render each time
   → done: stop loading spinner
```

---

## 8. The Query Router

**File**: `src/query_router.py`

### Two-stage routing:

**Stage 1: Regex fast-path** (no API call, instant, ~70% of queries)
```python
if "vs" or "compare" in query → COMPARISON
if "top colleges" in query → TOP_COLLEGES
if "admission to X" or "fee at X" in query → COLLEGE  ← checked BEFORE predictor
if rank/percentile number in query → PREDICTOR
if JEE/NEET/GATE in query → EXAM
```

**Stage 2: LLM fallback** (if regex doesn't match)
- Sends query to `llama-3.1-8b-instant` with a classification prompt
- Prompt includes examples to distinguish tricky cases

**Also extracts entities**: `college_names`, `exam_names`, `location`, `rank_score`

**Why regex first?** Regex is instant (microseconds). LLM call is ~500ms. Skipping LLM for 70% of queries is a big speed win.

---

## 9. Vector Store (ChromaDB)

**What is a vector database?**

Normal databases search by exact match: `WHERE name = 'VIT'`

Vector databases search by **meaning similarity**. Every piece of text is converted to a list of numbers (a vector/embedding) that captures its meaning. Similar texts have vectors that are close together in space.

```
"VIT Vellore fees"  → [0.23, -0.45, 0.12, ...] (384 numbers)
"VIT tuition cost"  → [0.21, -0.43, 0.14, ...] (very close! → similar meaning)
"JEE exam date"     → [-0.67, 0.89, -0.34, ...] (far away → different meaning)
```

**Cosine distance**: 0 = identical, 1 = completely different. Threshold 0.5 used to decide if results are good enough.

**Singleton pattern**: The embedding model loads once at startup and is reused for all requests. Without this, every request would reload the model (~3 seconds overhead).

---

## 10. SQLite — Why two databases?

| | SQLite | ChromaDB |
|---|---|---|
| **Good for** | Exact lookups, numbers | Fuzzy text search, semantic similarity |
| **Example** | "NIRF rank of VIT" → exact number | "Tell me about VIT campus life" → text chunks |
| **Search type** | `WHERE name LIKE '%VIT%'` | Cosine similarity of embeddings |

**The hybrid approach**: Each handler calls both. SQLite gives precise facts (fees, ranks, dates). ChromaDB gives rich text context (descriptions, comparisons). The handler combines both into one context string for the LLM.

---

## 11. Streaming — How SSE works

**SSE = Server-Sent Events** — server pushes data to browser over a single HTTP connection.

**Why streaming?** Without it: user waits 3-5 seconds staring at a spinner. With it: user sees the first word in ~500ms, then watches the answer build word by word. Feels much faster.

**Server side** (FastAPI):
```python
def generate():
    yield f"data: {json.dumps(meta)}\n\n"       # metadata first
    for chunk in groq_stream:
        yield f"data: {json.dumps({'type': 'chunk', 'content': chunk})}\n\n"
    yield f"data: {json.dumps({'type': 'done'})}\n\n"

return StreamingResponse(generate(), media_type="text/event-stream")
```

**Client side** (React):
```typescript
const reader = res.body.getReader()
while (true) {
    const { done, value } = await reader.read()
    if (done) break
    // Parse SSE lines, update React state on each chunk
    // React re-renders → text appears word by word
}
```

**Streaming glitch fix**: Animation class `animate-msg-in` was applied to ALL messages on every re-render. During streaming (~100 re-renders per response), this caused scroll glitching. Fix: only animate the LAST message (`idx === messages.length - 1`).

---

## 12. Performance Optimizations

| Optimization | Problem | Fix | Result |
|---|---|---|---|
| **Singleton pattern** | Embedding model reloaded per request (~3s) | Cache in global variable, load once | 3-5x faster after first request |
| **LRU cache** | Same query hits full pipeline every time | MD5 hash → dict cache, max 128 entries | Repeated queries: <100ms |
| **Startup warmup** | First request slow (cold start) | `lifespan` pre-loads ChromaDB + embeddings | First request now fast |
| **Regex fast-path** | Every query called LLM for routing (~500ms) | Regex checks common patterns first | 70% of queries skip LLM router |

---

## 13. Key Design Decisions — The "Why"

**Why no LangChain?** Adds abstraction layers → harder to debug, hides what's happening (bad for interviews), adds latency. Direct SDK calls are explicit, fast, and easy to explain.

**Why hybrid retrieval (SQLite + ChromaDB)?** Pure vector search misses exact facts. Pure SQL misses semantic queries. Together: SQL gives exact facts, ChromaDB gives rich context.

**Why per-category message history?** Users switch between topics (colleges → exams → back to colleges). Per-category history keeps each conversation clean and focused.

**Why `compound-beta` for generation but `llama-3.1-8b-instant` for routing/reflection?** `compound-beta` has web search capability needed for final answers. `llama-3.1-8b-instant` is smaller, faster, cheaper — perfect for routing (outputs one word) and Self-RAG checks (outputs "relevant"/"irrelevant"). Using the big model everywhere would be 3-4x more expensive.

**Why SSE instead of WebSockets?** SSE is one-directional (server → client) — perfect for streaming responses. WebSockets are bidirectional — overkill here. SSE works over regular HTTP and reconnects automatically.

---

## 14. Common Interview Questions + Answers

**"What is RAG and why did you use it?"**
RAG = Retrieval Augmented Generation. Instead of relying on the LLM's training data (which may be outdated or wrong), we first retrieve relevant documents from our own database, then give those documents to the LLM as context. I used it because LLMs don't have accurate data about specific Indian colleges — fees, NIRF ranks, exam dates change every year. RAG lets me keep the data fresh without retraining the model.

**"What is the difference between vector search and keyword search?"**
Keyword search matches exact words. If you search "tuition cost", it won't find documents that say "fee structure". Vector search converts text to embeddings (numerical representations of meaning) and finds semantically similar documents — so "tuition cost" and "fee structure" would be close in vector space. I use vector search for semantic queries and SQL for exact lookups.

**"How does streaming work in your app?"**
The FastAPI backend uses Server-Sent Events (SSE). As Groq generates tokens, we immediately forward each token to the frontend as a `data: {...}` event. The React frontend reads these events using the Fetch API's `ReadableStream`, and updates the message state on each chunk, causing React to re-render and show text appearing word by word.

**"What is Self-RAG and how did you implement it?"**
Self-RAG adds a relevance check before generation. After retrieving documents, I ask a fast LLM: "Are these documents relevant to the query?" If yes, proceed. If no, rephrase the query and retry. If still irrelevant after retry, automatically enable web search. Implemented in `self_rag.py` with `check_relevance()` (returns relevant/partial/irrelevant) and `rephrase_query()` (expands abbreviations, adds domain keywords). Adds ~300-600ms latency but significantly improves answer quality for edge cases.

**"Why did you use ChromaDB instead of Pinecone?"**
For a prototype, ChromaDB is ideal: runs locally, no cloud account needed, simple Python API, free. In production I'd consider Pinecone for managed scaling. The code is structured so swapping the vector store only requires changing `vector_store.py`.

**"How do you handle wrong information from the LLM?"**
Three layers: (1) RAG context gives the LLM real data, reducing hallucination. (2) Self-RAG ISREL check — if retrieved docs are irrelevant, retry or fall back to web search. (3) Web search fallback via Groq `compound-beta` for queries where local data is insufficient. Plus a disclaimer in the UI: "DegreeFYD AI is experimental — verify important information independently."

**"What would you improve if you had more time?"**
1. ISSUP check (Self-RAG step 2): verify the generated answer is actually supported by retrieved docs — currently only ISREL is implemented.
2. IIT data gap: EDA showed IIT Delhi has only 9 mentions in the dataset. I'd either scrape more IIT data or always enable web search for IIT queries.
3. sessionStorage: save chat history to browser sessionStorage so it survives page refresh but clears when tab closes.
4. Redis cache: replace in-memory LRU with Redis for persistence across server restarts.

**"Explain your data ingestion pipeline."**
The raw data is a JSONL file with ~14,810 records scraped from degreefyd.com. Ingestion has two paths: (1) Structured path — `data_extractor.py` uses regex to pull out fields like NIRF rank, fees, exam dates from raw text. These go into SQLite via `db_setup.py`. (2) Semantic path — `vector_store.py` chunks each record's raw content into ~1000 character pieces with 200 char overlap, embeds them using `all-MiniLM-L6-v2`, and stores them in ChromaDB with metadata. At query time, both databases are searched and their results are combined as context for the LLM.

**"How does the query router work?"**
Two stages. First, a regex fast-path checks common patterns like "vs" → COMPARISON, "top colleges" → TOP_COLLEGES, rank numbers → PREDICTOR. This handles ~70% of queries instantly with no API call. For the remaining 30%, I call `llama-3.1-8b-instant` with a classification prompt that includes examples to distinguish tricky cases (e.g., "admission to VIT" → COLLEGE, not PREDICTOR). The router also extracts entities like college names, exam names, location, and rank/score from the query.

**"What is cosine similarity and why does it matter for RAG?"**
Cosine similarity measures the angle between two vectors. If two text embeddings point in the same direction (small angle), they're semantically similar. In ChromaDB, I use cosine distance (1 - cosine similarity), where 0 = identical and 1 = completely different. I use 0.5 as a threshold: if all retrieved documents have distance > 0.5, the results are poor quality and I flag `needs_web = True`. This is how the system decides whether local data is good enough or web search is needed.

---

## 15. Architecture Diagram (Final)

```
User (Browser)
     │
     │  POST /chat/stream (SSE)
     ▼
┌─────────────────────────────────────────────────────────┐
│  FastAPI  (api/main.py, port 8000)                      │
│  - CORS middleware                                      │
│  - Startup warmup (ChromaDB + embeddings)               │
└──────────────────────┬──────────────────────────────────┘
                       │
                       ▼
┌─────────────────────────────────────────────────────────┐
│  rag_chain.py  (Main Orchestrator)                      │
│                                                         │
│  1. route_query() → category + entities                 │
│  2. _get_raw_docs() → vector fetch for ISREL            │
│  3. check_relevance() [Self-RAG ISREL]                  │
│     ├─ relevant → proceed                               │
│     └─ irrelevant → rephrase → retry → auto web         │
│  4. _build_context() → handler → SQL + vector           │
│  5. query_with_web_search() → Groq → stream             │
└──────────────────────┬──────────────────────────────────┘
                       │
        ┌──────────────┼──────────────┐
        ▼              ▼              ▼
   SQLite DB      ChromaDB        Groq API
   (structured)   (semantic)      (generation
   colleges       all-MiniLM      + web search)
   exams          embeddings
   comparisons    cosine dist
   blogs
```

---

## 16. File-by-File Quick Reference

| File | What it does | Key function |
|---|---|---|
| `src/config.py` | All constants (paths, model names, settings) | — |
| `src/data_extractor.py` | Parse raw JSONL text → structured fields using regex | `extract_all_data()` |
| `src/db_setup.py` | SQLite schema + insert data + query helpers | `setup_database()`, `query_college()` |
| `src/vector_store.py` | ChromaDB ingestion + semantic search + singleton caching | `ingest_documents()`, `search_documents()` |
| `src/query_router.py` | Regex fast-path + LLM classifier → category + entities | `route_query()` |
| `src/self_rag.py` | ISREL relevance check + query rephrasing | `check_relevance()`, `rephrase_query()` |
| `src/rag_chain.py` | Main pipeline orchestrator + LRU cache | `process_query()` |
| `src/web_search.py` | Groq compound-beta wrapper + web search toggle | `query_with_web_search()` |
| `src/handlers/college_handler.py` | SQL + vector context for college queries | `build_prompt_context()` |
| `api/main.py` | FastAPI endpoints + SSE streaming + CORS | `/chat/stream` |
| `frontend/src/App.tsx` | React UI — sidebar, chat, streaming, animations, Self-RAG indicator | `handleSend()` |
| `frontend/src/api.ts` | Fetch + SSE stream client | `sendChatStream()` |
| `frontend/src/types.ts` | TypeScript interfaces | `Message`, `Category`, `CategoryConfig` |
| `frontend/src/constants.ts` | Category configs, sample questions, per-sub-tab samples | `CATEGORY_CONFIG` |

---

## 17. Recent UI Changes (Feb 2026) — What to say in interview

### Sub-Tab Sample Questions
Each sub-tab (e.g. "Admissions", "Fees", "Placements") now shows **different sample questions** on the welcome screen. This is a UX improvement — instead of generic questions, the user sees contextually relevant ones based on what they're interested in.

**How it works**:
- `constants.ts` has a `subTabSamples: Record<string, string[]>` field on every category config
- Welcome screen renders: `config.subTabSamples[activeSubTab] ?? config.samples`
- Clicking a sub-tab pill updates `activeSubTab` state → React re-renders with new questions + staggered slide-up animation

**Interview angle**: "I used a `Record<string, string[]>` map keyed by tab name so adding new tabs just means adding a new key — no component changes needed."

---

### Sub-Tab Placement
Sub-tabs were moved from the top header bar into the welcome screen, sitting between the subtitle and the sample cards.

**Why**: The header was getting crowded. Sub-tabs are only relevant on the welcome/discovery screen — once a chat starts, they're hidden. Moving them into the welcome screen makes the header clean and gives the tabs more visual prominence where they matter.

**Style**: Pill-shaped (`rounded-full`), dark fill when active, white with border when inactive. Centered with `flex-wrap` so they wrap on narrow screens.

---

### Self-RAG Auto-Web Indicator
When Self-RAG detects that local docs are irrelevant and auto-triggers web search, an **⚡ "Auto web search was used"** orange pill appears in the controls row above the input bar.

**How it works**:
```tsx
const lastBotMsg = [...messages].reverse().find(m => m.role === 'assistant')

{lastBotMsg?.autoWebTriggered && (
  <div className="animate-fade-in ...">
    <Zap size={12} className="animate-pulse" />
    <span>Auto web search was used</span>
  </div>
)}
```
- `lastBotMsg` is a derived value (not state) — recomputed on every render
- Disappears automatically when you switch categories or clear chat
- Distinct from the amber "Web ON" toggle — this is informational, not a control

**Interview angle**: "I derived `lastBotMsg` from the messages array instead of storing it as separate state — this avoids state sync bugs. The indicator is purely presentational and always reflects the current truth."

---

### Chat Bubble Polish
| Element | Before | After |
|---|---|---|
| User bubble | Flat `bg-indigo-600` | Gradient `from-indigo-500 to-indigo-700` |
| User timestamp | Missing | Below bubble, right-aligned |
| Bot avatar | Flat indigo square | Indigo→violet gradient + white ring |
| Bot bubble | Plain white border | Left indigo accent stripe (`border-l-4`) |
| Typing dots | Small, uniform color | Larger, fading opacity (dark→light wave) |

**The left accent stripe** (`border-l-4 border-l-indigo-400`) is a common chat UI pattern — it visually connects the bubble to the avatar and makes it clear which side is the AI.

---

### Scroll Glitch Fix
**Problem**: During streaming, React re-renders ~100 times (once per token). The `animate-msg-in` class was on every message, so every re-render restarted all animations → the page would jump/scroll erratically.

**Fix**: Only apply the animation to the last message:
```tsx
className={idx === messages.length - 1 ? 'animate-msg-in' : ''}
```

**Interview angle**: "This is a classic React performance issue — animations triggered on every re-render during streaming. The fix is minimal: one conditional class on the last item only. The key insight is that only the newest message needs to animate in; older messages are already settled."

---

## 18. Things That Could Go Wrong — Debugging Tips

**Self-RAG always returns "irrelevant"**:
- Check if ChromaDB has data: `collection.count()` — if 0, ingestion didn't run
- Check if the GROQ_API_KEY is valid — `check_relevance()` calls Groq
- The `llama-3.1-8b-instant` model prompt asks for exactly one word — if it returns a sentence, the `if verdict in (...)` check fails and defaults to "partial"

**Streaming stops mid-response**:
- Groq has rate limits — check the error in the SSE `error` event
- The `for chunk in completion` loop in `web_search.py` — if Groq throws mid-stream, the generator stops
- Frontend: check browser console for `ReadableStream` errors

**Wrong category detected**:
- Check `query_router.py` `fast_route()` — regex patterns are checked in order, earlier patterns win
- Add a `print(f"[Router] fast_route matched: {category}")` to debug
- If LLM fallback is wrong, check the prompt in `route_query()` — add more examples

**ChromaDB returns wrong results**:
- Cosine distance > 0.5 means poor match — this triggers `needs_web = True`
- Check if the query is too short/vague — embedding model needs enough tokens to find similarity
- Check `doc_type` filter — `search_by_type(query, doc_type='college')` only searches college docs

**Frontend shows "Auto Web" badge incorrectly**:
- `lastBotMsg` is derived from `messages` (current category) — switching categories resets it correctly
- If it persists after clear, check that `setAllMessages` is resetting the full array to `[]`
