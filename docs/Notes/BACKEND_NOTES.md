# DegreeFYD — Backend Deep Dive: Handlers, RAG Chain, API
> Part 2 of the technical notes series. Covers every handler file, the RAG orchestrator,
> and the FastAPI layer with the full request lifecycle.
> **Read after `NOTES.md`** (config, data extractor, db_setup, vector_store, query_router, self_rag, web_search).
> See also: `BACKEND_NOTES_2.md` and `BACKEND_NOTES_QA.md`.

---

## Table of Contents
1. [The Handler Pattern — Why It Exists](#1-the-handler-pattern)
2. [`college_handler.py`](#2-college_handlerpy)
3. [`comparison_handler.py`](#3-comparison_handlerpy)
4. [`exam_handler.py`](#4-exam_handlerpy)
5. [`predictor_handler.py`](#5-predictor_handlerpy)
6. [`top_colleges_handler.py`](#6-top_colleges_handlerpy)
7. [`src/rag_chain.py` — The Orchestrator](#7-srcrag_chainpy)
8. [`api/main.py` — The FastAPI Layer](#8-apimainpy)
9. [Full Request Lifecycle — End to End](#9-full-request-lifecycle)

---

## 1. The Handler Pattern

After `query_router.py` classifies a query (e.g., `category="comparison"`, `entities=["VIT","SRM"]`), the system needs to **retrieve the right data** for that specific question type. A comparison query needs different tables and different formatting than a predictor query. Handlers encapsulate this category-specific retrieval + formatting logic.

Each handler exposes one uniform interface:
```python
def build_prompt_context(query: str, entities: list[str]) -> str:
    """Returns a formatted string ready to inject into the LLM prompt."""
```

This means `rag_chain.py` can call any handler identically:
```python
handler = handler_map.get(category)
context = handler.build_prompt_context(rephrased_query, entities)
```

`rag_chain.py` doesn't know what SQL tables exist or how ChromaDB is queried. That knowledge lives inside each handler — **Single Responsibility Principle**.

---

## 2. `college_handler.py`

**Purpose**: Single-college queries — fees, NIRF rank, location, programs.

### Two-source retrieval
```python
def get_context(college_names, query):
    sql_results    = [query_college(name) for name in college_names if query_college(name)]
    vector_results = search_by_type(query, doc_type='college',    n_results=TOP_K_RESULTS)
    vector_results+= search_by_type(query, doc_type='comparison', n_results=3)
    return sql_results, vector_results
```

Why pull from both `college` AND `comparison` vector docs? 85% of the dataset is comparison pages. Comparison pages (`VIT vs SRM`, `VIT vs Manipal`) contain rich VIT-specific data that sparse individual college pages might not have.

Why `n_results=3` for comparison docs but `TOP_K_RESULTS=5` for college docs? Comparison docs are secondary context — limiting to 3 prevents them from drowning out the primary college docs.

### `format_sql_context()` — selective field formatting
```python
def format_sql_context(college: dict) -> str:
    lines = [f"College: {college['name']}"]
    if college.get('nirf_rank'):    lines.append(f"NIRF Rank: #{college['nirf_rank']}")
    if college.get('fee_range'):    lines.append(f"Fee Range: {college['fee_range']}")
    if college.get('location'):     lines.append(f"Location: {college['location']}")
    if college.get('college_type'): lines.append(f"Type: {college['college_type']}")
    if college.get('rating'):       lines.append(f"Rating: {college['rating']}/5")
    return "\n".join(lines)
```

Every field uses `.get()` with no default — missing data is **silently omitted**. The LLM never sees `"Fee Range: None"`. If you pass `None` values, the LLM might say *"the fee is None"* — a hallucination of a database artifact.

### Location fallback
```python
if not sql_results and not entities:
    # "colleges in Bangalore" — no specific college named
    vector_results = search_by_type(query, doc_type='college', n_results=TOP_K_RESULTS)
```
When no college name is extracted, fall back to pure semantic search. The embedding model finds college documents mentioning the location.

---

## 3. `comparison_handler.py`

**Purpose**: "A vs B" queries — the most common type (85% of data).

### Three-layer retrieval
```python
def get_context(college_names, query):
    # Layer 1: Pre-extracted SQL comparison row
    comparison_row = query_comparison(college_names[0], college_names[1]) if len(college_names) >= 2 else None
    # Layer 2: Individual SQL college rows (fills gaps)
    college_rows = [r for r in [query_college(n) for n in college_names] if r]
    # Layer 3: Semantic vector search on comparison docs
    vector_results = search_comparisons(query, college_names, n_results=TOP_K_RESULTS)
    return comparison_row, college_rows, vector_results
```

- **Layer 1**: fastest, most structured, purpose-built for comparison queries
- **Layer 2**: fills gaps when the comparison row has missing fields (regex extraction isn't perfect)
- **Layer 3**: narrative context — *"VIT is known for industry connections while SRM has a larger campus"*

### `format_comparison_table()` — ASCII table for LLM
```python
rows = [
    ("NIRF Rank", f"#{c1.get('nirf_rank','N/A')}", f"#{c2.get('nirf_rank','N/A')}"),
    ("Fee Range", c1.get('fee_range','N/A'),         c2.get('fee_range','N/A')),
    ("Rating",    str(c1.get('rating','N/A')),        str(c2.get('rating','N/A'))),
    ("Location",  c1.get('location','N/A'),           c2.get('location','N/A')),
    ("Type",      c1.get('college_type','N/A'),       c2.get('college_type','N/A')),
]
```
An ASCII table is the most readable format for an LLM. The LLM naturally mirrors the tabular structure in its output, which renders as a proper markdown table in the frontend's `react-markdown`.

### `search_comparisons()` — both-college filter
```python
results  = search_by_type(query, doc_type='comparison', n_results=n_results * 2)
filtered = [doc for doc in results
            if all(name.lower() in doc['content'].lower() for name in college_names)]
return filtered[:n_results]
```
Over-fetch and Python-filter rather than relying on ChromaDB metadata. ChromaDB's `where` clause only supports exact metadata matches — college names in metadata might differ from the query. Python substring check handles partial names, abbreviations, and case differences.

---

## 4. `exam_handler.py`

**Purpose**: Entrance exam queries — JEE, NEET, CAT, GATE.

```python
def get_context(exam_names, query):
    sql_results    = [query_exam(name) for name in exam_names if query_exam(name)]
    vector_results = search_by_type(query, doc_type='exam',  n_results=TOP_K_RESULTS)
    vector_results+= search_by_type(query, doc_type='blog',  n_results=2)
    return sql_results, vector_results
```

Blog documents are included because many of the 161 blog posts are *"How to prepare for JEE"* or *"NEET 2024 cutoffs"* — exam-relevant info not in the structured exam table.

`format_sql_context()` surfaces: exam date, registration window, mode (online/offline), conducting body.

**Known limitation**: Exam dates are time-sensitive and change every year. The SQL data reflects scrape time. The system prompt tells the LLM to recommend checking the official website for current dates — honest about data staleness.

---

## 5. `predictor_handler.py`

**Purpose**: Rank/score → college prediction. *"I have JEE rank 5000, which colleges can I get?"*

### Rank/score parsing — regex not LLM
```python
def parse_rank_score(query: str) -> tuple[int | None, int | None]:
    rank_match  = re.search(r'\b(\d{1,6})\s*(?:rank|AIR|all\s*india\s*rank)', query, re.IGNORECASE)
    score_match = re.search(r'\b(\d{1,3}(?:\.\d+)?)\s*(?:score|percentile|marks)', query, re.IGNORECASE)
    return (int(rank_match.group(1)) if rank_match else None,
            float(score_match.group(1)) if score_match else None)
```
Regex here, not LLM — the rank/score is a number. Regex is exact and instant (~0.1ms). An LLM might return *"approximately 5000"* which requires further parsing.

### NIRF rank as proxy
```python
nirf_threshold = max(10, rank // 100)
# JEE rank 1000  → NIRF top-10
# JEE rank 10000 → NIRF top-100
```
**Caveat**: NIRF rank ≠ admission cutoff rank. This is a rough heuristic. The system prompt explicitly tells the LLM to present results as *"colleges you might consider"*, not *"guaranteed admissions"*.

---

## 6. `top_colleges_handler.py`

**Purpose**: *"Top 10 engineering colleges in India"*, *"Best private colleges by NIRF"*.

```python
base_query = "SELECT * FROM colleges WHERE nirf_rank IS NOT NULL"
if college_type:
    base_query += " AND college_type LIKE ?"
base_query += " ORDER BY nirf_rank ASC LIMIT ?"
```

`ORDER BY nirf_rank ASC` — lower rank number = better (NIRF #1 is the best). `IS NOT NULL` filter ensures only actually-ranked colleges appear. `LIMIT` prevents returning all 1,903 colleges.

---

## 7. `src/rag_chain.py`

### Role
The **conductor** of the entire pipeline. Imports every other module and orchestrates them. It's the only file that knows about all other files — all other files are isolated.

### LRU cache — non-streaming only
```python
_query_cache: dict[str, str] = {}
MAX_CACHE_SIZE = 100

def _get_cached(query, category):
    return _query_cache.get(f"{category}::{query.lower().strip()}")

def _set_cached(query, category, response):
    if len(_query_cache) >= MAX_CACHE_SIZE:
        del _query_cache[next(iter(_query_cache))]  # evict oldest (Python 3.7+ dict order)
    _query_cache[f"{category}::{query.lower().strip()}"] = response
```

**Why manual dict instead of `@lru_cache`?** `@lru_cache` can't cache streaming generators (consumed once). The manual dict is only used for non-streaming `/chat`. Streaming responses are never cached.

**Cache key**: `"comparison::vit vs srm"` — includes category so the same query string in different categories doesn't collide. Normalized with `.lower().strip()`.

**Why 100 entries?** Each response ≈ 500–2000 chars. 100 entries ≈ 200KB max. Trivial cost. Benefit: repeated identical queries (common in demos) return instantly without hitting Groq.

### `warmup()`
```python
def warmup():
    get_collection()          # ChromaDB: opens DB, loads HNSW index
    get_embedding_function()  # loads 80MB sentence-transformer model weights
```
Without warmup: first query takes 3–5 seconds. With warmup: every query takes ~200ms. Called during FastAPI `lifespan` startup — before the server accepts any requests.

### `process_query()` — step by step

```python
async def process_query(query, web_search_enabled=False, stream=False, conversation_history=None):
```

1. **Cache check** (non-streaming only): return cached response if exists
2. **Route**: `route_result = await route_query(query)` → `{category, entities}`
3. **Self-RAG**: `rag_result = await self_rag_retrieve(query, category, entities)` → `{docs, auto_web_triggered, rephrased_query}`
4. **Handler dispatch**: `context = handler_map[category].build_prompt_context(rephrased_query, entities)`
5. **Web search decision**: `use_web = web_search_enabled or auto_web_triggered`
6. **Generate**: `return await query_with_web_search(query=rephrased_query, context=context, stream=stream, ...)`

---

## 8. `api/main.py`

### `lifespan` — startup hook
```python
@asynccontextmanager
async def lifespan(app: FastAPI):
    warmup()   # runs BEFORE server accepts requests
    yield
    # cleanup after shutdown
```
`yield` divides startup (before) from shutdown (after). Replaced `@app.on_event("startup")` in FastAPI 0.93+.

### CORS middleware
```python
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://localhost:5174"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
```
**Why CORS?** Browser Same-Origin Policy blocks JS from requesting a different origin. Different port = different origin. React on 5173/5174, FastAPI on 8000 → CORS required.

**Why specific origins, not `"*"`?** `allow_credentials=True` requires explicit origins — browsers reject `credentials: include` with wildcard origins.

### Pydantic models
```python
class ChatRequest(BaseModel):
    query: str
    web_search: bool = False
    conversation_history: list[dict] = []
```
Auto-parses JSON body, validates types, returns HTTP 422 on failure, generates `/docs` Swagger UI.

### `/chat/stream` — SSE endpoint
```python
@app.post("/chat/stream")
async def chat_stream(request: ChatRequest):
    async def event_generator():
        # 1. Send metadata FIRST (category, web search flags)
        yield f"data: {json.dumps({'type': 'meta', 'data': meta})}\n\n"
        # 2. Stream response tokens
        async for chunk in response_stream:
            yield f"data: {json.dumps({'type': 'chunk', 'data': chunk})}\n\n"
        # 3. Signal completion
        yield f"data: {json.dumps({'type': 'done'})}\n\n"

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
```

**Why metadata first?** Frontend needs category and web-search flags before the response starts streaming — to show the correct badge immediately.

**`X-Accel-Buffering: no`**: Nginx buffers responses by default. This header forces pass-through. Without it, SSE works locally but buffers in production.

---

## 9. Full Request Lifecycle

Tracing: **"Compare VIT Vellore and SRM University fees"**

```
Browser → POST /chat/stream {query, web_search: false}
  │
  ▼ FastAPI: Pydantic validates → calls process_query()
  │
  ▼ query_router.py
  │   fast_route(): "vs" detected → category="comparison"
  │   LLM call: extract entities → ["VIT Vellore", "SRM University"]
  │
  ▼ self_rag.py
  │   search_comparisons(query, entities) → 5 docs
  │   check_relevance(query, docs) → LLM: "relevant"
  │   auto_web_triggered = False
  │
  ▼ comparison_handler.py
  │   query_comparison("VIT Vellore", "SRM University") → SQL row
  │   query_college("VIT Vellore"), query_college("SRM University") → SQL rows
  │   search_comparisons(...) → 5 vector docs
  │   format_comparison_table() → ASCII table
  │   returns full context string
  │
  ▼ web_search.py — query_with_web_search()
  │   use_web = False
  │   Build system prompt with context
  │   Groq API (compound-beta, stream=True) → AsyncGenerator
  │
  ▼ FastAPI event_generator()
  │   yield: {"type":"meta","data":{"category":"comparison","used_web_search":false,...}}
  │   yield: {"type":"chunk","data":"VIT Vellore and SRM..."}
  │   yield: {"type":"chunk","data":" are both private..."}
  │   ... (100-200 chunks)
  │   yield: {"type":"done"}
  │
  ▼ React sendChatStream()
      On "meta":  update badge state
      On "chunk": append to message, trigger re-render
      On "done":  mark streaming complete
      react-markdown renders accumulated text → user sees response word by word
```

### Latency breakdown
| Step | Time |
|---|---|
| Query routing (regex fast-path) | ~1ms |
| Self-RAG relevance check (LLM) | ~100–200ms |
| Handler retrieval (SQL + ChromaDB) | ~20–50ms |
| First token from Groq | ~300–500ms |
| **Time to first visible character** | **~500–800ms** |
