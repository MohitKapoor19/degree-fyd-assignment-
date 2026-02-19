# DegreeFYD — Backend Deep Dive: SSE, Databases, Self-RAG, Performance, Embeddings
> Part 3 of the technical notes series.
> **Read after `BACKEND_NOTES.md`.**
> See also: `BACKEND_NOTES_QA.md` for 30 interview Q&A and the debugging playbook.

---

## Table of Contents
1. [SSE Streaming — How It Actually Works](#1-sse-streaming)
2. [SQLite vs ChromaDB — Why Both Exist](#2-sqlite-vs-chromadb)
3. [Self-RAG — Deep Dive](#3-self-rag-deep-dive)
4. [Performance: Singletons, Warmup, LRU Cache, Async](#4-performance)
5. [Embeddings — From Text to Numbers](#5-embeddings)
6. [Chunking Strategy — Why 1000/200](#6-chunking-strategy)
7. [Query Routing — Two-Stage Design](#7-query-routing)
8. [The System Prompt — Why It Matters](#8-the-system-prompt)
9. [Tradeoffs and Limitations](#9-tradeoffs-and-limitations)

---

## 1. SSE Streaming

### What is SSE?
Server-Sent Events: one-directional HTTP where the server pushes data to the client over a **persistent connection**. Client makes one HTTP request; server sends many responses over time.

### Wire format
```
data: {"type": "meta",  "data": {"category": "comparison", "used_web_search": false}}\n\n
data: {"type": "chunk", "data": "VIT Vellore and SRM"}\n\n
data: {"type": "chunk", "data": " University are both"}\n\n
data: {"type": "done"}\n\n
```
Each event: starts with `data: `, ends with **double newline** `\n\n` (the event delimiter).

### SSE vs WebSockets vs Polling

| | SSE | WebSocket | Polling |
|---|---|---|---|
| Direction | Server→Client only | Bidirectional | Client→Server |
| Protocol | HTTP/1.1 | WS upgrade | HTTP |
| Auto-reconnect | Built-in | Manual | N/A |
| Proxy support | Works everywhere | Sometimes blocked | Works |
| Right for this app? | **Yes** | Overkill | Wasteful |

For a chat app, the client sends one message and the server streams back one response — inherently one-directional. SSE is the right tool. WebSockets add bidirectional complexity that isn't needed. Polling wastes requests and adds latency.

### FastAPI server side
```python
return StreamingResponse(
    event_generator(),
    media_type="text/event-stream",
    headers={
        "Cache-Control":     "no-cache",
        "X-Accel-Buffering": "no",   # disable nginx buffering — critical for production
    },
)
```
`X-Accel-Buffering: no` tells nginx to pass chunks through immediately. Without it, SSE works locally but silently buffers in production — user sees nothing until the full response is ready.

### Frontend client side
```typescript
// Why fetch + ReadableStream instead of EventSource?
// EventSource only supports GET. Our endpoint is POST (query in body).
const response = await fetch('/chat/stream', { method: 'POST', body: JSON.stringify({...}) });
const reader   = response.body!.getReader();
let buffer     = '';

while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    buffer += new TextDecoder().decode(value, { stream: true });
    const lines = buffer.split('\n\n');
    buffer = lines.pop()!;  // keep incomplete event in buffer
    for (const line of lines) {
        if (!line.startsWith('data: ')) continue;
        const event = JSON.parse(line.slice(6));
        if (event.type === 'meta')  onMeta(event.data);
        if (event.type === 'chunk') onChunk(event.data);
        if (event.type === 'done')  onDone();
    }
}
```

**The buffer pattern**: Network packets don't align with SSE events. One `reader.read()` might return half an event or multiple events. The buffer accumulates data; `split('\n\n')` splits on the delimiter; `lines.pop()` saves the incomplete last element back to the buffer.

### Why three event types?
- **`meta`**: Sent first. Carries category, `used_web_search`, `auto_web_triggered`. Frontend shows correct badge immediately.
- **`chunk`**: One per token group. Frontend appends each chunk, triggering re-renders that show text appearing word by word.
- **`done`**: Stream complete. Frontend stops typing indicator, enables follow-up suggestions.

---

## 2. SQLite vs ChromaDB

### The fundamental difference

**SQLite** → exact structured lookups: `SELECT fee_range FROM colleges WHERE name = 'VIT Vellore'`
**ChromaDB** → semantic similarity: *"find content about research-focused engineering colleges"*

Neither alone is sufficient. Together they cover both exact facts and narrative context.

### Why you need both
```
Query: "Compare fees at VIT and SRM"
        ┌──────────────┬──────────────┐
        ▼              ▼
    SQLite          ChromaDB
  exact numbers   narrative context
  "1,98,000"      "VIT offers competitive
                   fee structures with..."
        └──────────────┴──────────────┘
                       ▼
              LLM gets both → best answer
```

### SQLite schema decisions

**`fee_range` is TEXT not NUMERIC**: Fees are ranges like `"1,50,000 - 2,50,000"`, not single numbers. TEXT preserves the original format.

**`raw_content` column**: Stores original scraped text. Safety net — if regex extraction missed something, the LLM can still read the raw text. Also useful for debugging.

**`UNIQUE(college_1, college_2)` on comparisons**: Prevents duplicate comparison rows. Combined with `INSERT OR IGNORE`, running ingestion twice is safe.

### `INSERT OR IGNORE` — idempotency
```python
conn.execute(
    "INSERT OR IGNORE INTO colleges (name, nirf_rank, ...) VALUES (?, ?, ...)",
    (name, nirf_rank, ...)
)
```
If a row with the same `UNIQUE` key exists, the insert is silently skipped. Makes ingestion **idempotent** — safe to run multiple times without corrupting data.

### Parameterized queries — SQL injection prevention
```python
# WRONG — vulnerable:
conn.execute(f"SELECT * FROM colleges WHERE name = '{user_input}'")

# RIGHT — safe:
conn.execute("SELECT * FROM colleges WHERE name = ?", (user_input,))
```
The `?` placeholder treats the value as data, never as SQL code. `"'; DROP TABLE colleges; --"` becomes a harmless literal string search.

### ChromaDB internals

**HNSW index**: Hierarchical Navigable Small World graphs for approximate nearest-neighbor search. Builds a multi-layer graph; search traverses from sparse top layer to dense bottom layer, converging on nearest neighbors in O(log n) time.

**Why approximate?** Exact nearest-neighbor search across 129,000 vectors in 384 dimensions is too slow. HNSW finds approximate nearest neighbors with >99% accuracy — the small accuracy loss is irrelevant for RAG.

**Cosine distance**: `1 - cosine_similarity(A, B)`. Measures the **angle** between vectors, not magnitude. Two documents about the same topic but different lengths have similar cosine distance. Euclidean distance would penalize length differences — wrong for text.

**Persistent storage**: ChromaDB stores its HNSW index in `data/chroma_db/`. On restart, it loads from disk — no need to re-embed 129,000 documents. Ingestion runs once; retrieval is instant on every restart.

---

## 3. Self-RAG Deep Dive

### The problem it solves
Standard RAG retrieves documents regardless of quality. If retrieved docs are irrelevant, the LLM hallucinates or says "I don't know." Self-RAG adds a **reflection step**: check relevance before generating.

### The three-verdict system
```python
async def check_relevance(query: str, docs: list[dict]) -> str:
    prompt = f"""Query: {query}
Documents: {doc_snippets}
Are these documents relevant to answer the query?
Reply with exactly one word: relevant, partial, or irrelevant."""

    response = groq_client.chat.completions.create(
        model=GROQ_ROUTER_MODEL,  # llama-3.1-8b-instant
        max_tokens=10,            # only need one word — ~50ms not ~500ms
    )
    verdict = response.choices[0].message.content.strip().lower()
    return verdict if verdict in ("relevant", "partial", "irrelevant") else "partial"
```

- `"relevant"`: proceed with local context
- `"partial"`: use local context AND trigger web search as supplement
- `"irrelevant"`: rephrase query and retry, then fall back to web search

**`max_tokens=10`**: The model only needs one word. Limiting tokens cuts this call from ~500ms to ~50ms.

**Fallback to `"partial"`**: If the LLM returns anything unexpected, default to `"partial"`. Safe — never crashes, never blocks.

### Query rephrasing
```python
async def rephrase_query(original_query: str, category: str) -> str:
    prompt = f"""The query "{original_query}" didn't retrieve good results from a college database.
Rephrase it to be more specific and likely to match database content about Indian colleges.
Category hint: {category}
Return only the rephrased query, nothing else."""
```

Examples:
- `"IIT Delhi placement stats"` → `"Indian Institute of Technology Delhi campus placements salary packages"`
- `"best college for CS"` → `"top computer science engineering colleges India NIRF ranking"`

Rephrased queries use formal/complete terms that match the scraped content's vocabulary better than colloquial shorthand.

### The full flow
```
Attempt 1: retrieve with original query
    → check_relevance()
    → "relevant"  → return docs, auto_web=False
    → "partial"   → return docs, auto_web=True
    → "irrelevant" → rephrase_query()

Attempt 2: retrieve with rephrased query
    → check_relevance()
    → "relevant"/"partial" → return docs2, auto_web=(verdict2=="partial")
    → "irrelevant" → return docs2, auto_web=True (both failed → web search)
```

**Why only one retry?** Two LLM calls already add ~200–400ms. A second retry adds another ~200ms for marginal benefit. If rephrasing didn't help, the data isn't in the local store — fall back to web search.

### The IIT problem — why Self-RAG was built
From EDA: IIT Delhi appears in only 9 documents, IIT Madras in 5. Vector search returns documents mentioning IIT Delhi in passing (comparison pages) but without detailed IIT-specific information.

Without Self-RAG: LLM receives weak context → hallucinates or gives vague answer.
With Self-RAG: `check_relevance` returns `"partial"` → `auto_web_triggered=True` → `compound-beta` searches the web → accurate, up-to-date answer.

**Interview angle**: *"I discovered through EDA that IITs are underrepresented — only 5–9 documents each. Rather than re-scraping data, I built Self-RAG to automatically detect when local retrieval is insufficient and fall back to web search. Runtime solution, no data changes needed."*

---

## 4. Performance

### Singleton pattern
```python
_embedding_fn = None

def get_embedding_function():
    global _embedding_fn
    if _embedding_fn is None:
        _embedding_fn = SentenceTransformerEmbeddingFunction(model_name=EMBEDDING_MODEL)
    return _embedding_fn
```
Loading `all-MiniLM-L6-v2` takes ~2 seconds and ~80MB RAM. The singleton ensures it's loaded once at startup and reused for every query. Same pattern for `_chroma_client` and `_collection`.

### Warmup at startup
```python
def warmup():
    get_collection()          # opens ChromaDB, loads HNSW index from disk
    get_embedding_function()  # loads model weights into RAM
```
Without warmup: first query = 3–5 seconds. With warmup (called in `lifespan`): every query = ~200ms. Users never experience the cold start.

### LRU cache — non-streaming only
100-entry manual dict. Cache key = `"category::normalized_query"`. Only for non-streaming `/chat` endpoint — streaming responses can't be cached (they're generators, consumed once).

### Async throughout
```python
async def process_query(...):
    route_result = await route_query(query)         # non-blocking
    rag_result   = await self_rag_retrieve(...)     # non-blocking
    response     = await query_with_web_search(...) # non-blocking
```
All Groq API calls are `async`. FastAPI's event loop handles other requests while waiting for Groq. This is why FastAPI handles concurrent users without threading — cooperative multitasking via `await`.

### Batch insertion during ingestion
```python
for i in range(0, len(documents), BATCH_SIZE):  # BATCH_SIZE = 100
    batch = documents[i:i + BATCH_SIZE]
    collection.add(ids=[...], documents=[...], metadatas=[...])
```
129,000 documents ÷ 100 per batch = ~1,290 calls instead of 129,000. ChromaDB also embeds in batches internally — much more efficient.

---

## 5. Embeddings

### What is an embedding?
A dense vector representing the **semantic meaning** of text. Similar meanings → similar vectors (small cosine distance).

```
"fee at VIT"       → [0.12, -0.34, 0.89, ...]  (384 numbers)
"VIT tuition cost" → [0.11, -0.33, 0.91, ...]  (very similar — same meaning)
"cricket score"    → [-0.45, 0.67, -0.12, ...]  (very different)
```

### `all-MiniLM-L6-v2` — why this model

| Model | Dims | Size | Speed | Cost |
|---|---|---|---|---|
| `all-MiniLM-L6-v2` | 384 | 80MB | ~10ms | Free, local |
| `all-mpnet-base-v2` | 768 | 420MB | ~30ms | Free, local |
| `text-embedding-ada-002` | 1536 | N/A | ~100ms | $0.0001/1K tokens |

For 129,000 chunks, `text-embedding-ada-002` would cost ~$1.29 for ingestion — not expensive, but it requires internet and an API key. `all-MiniLM-L6-v2` is free, local, fast, and good enough.

**Why 384 dimensions?** Higher dims = more expressive but more storage and slower search. 384 is the sweet spot. Storage: 129,000 × 384 × 4 bytes ≈ 198MB of vector data.

### Semantic vs keyword search
```
Keyword: "fee VIT" → finds docs containing the words "fee" and "VIT"
Semantic: "fee VIT" → finds docs about VIT's cost/tuition/charges

Query: "how much does it cost to study at VIT?"
Keyword: misses docs saying "fee structure" instead of "cost"
Semantic: finds VIT fee docs regardless of exact wording
```
Vector search handles paraphrasing, synonyms, and natural language variation automatically — the core advantage for RAG.

---

## 6. Chunking Strategy

### Why chunk?
Long documents (2,000–5,000 chars) cause problems:
1. **Context window**: 5 full documents might exceed the LLM's token limit
2. **Retrieval precision**: A document about fees + placements + campus life retrieves everything when you only want fees
3. **Embedding quality**: One vector for a 5,000-char document averages all topics — poor match for specific queries

### The algorithm
```python
def chunk_text(text, chunk_size=1000, overlap=200):
    chunks = []
    start = 0
    while start < len(text):
        end = start + chunk_size
        if end < len(text):
            # Break at sentence boundary if possible
            boundary = text.rfind('. ', start, end)
            if boundary != -1 and boundary > start + chunk_size // 2:
                end = boundary + 1
        chunks.append(text[start:end].strip())
        start = end - overlap  # overlap: next chunk starts 200 chars before end of current
    return [c for c in chunks if c]
```

### Why 1000 characters?
- Too small (200 chars): too little context, too many chunks (645k+), slower search
- Too large (3000 chars): multiple topics per chunk, poor precision, approaches context window limit
- 1000 chars ≈ 150–200 tokens: 5 chunks × 200 tokens = 1000 tokens of context — comfortable

### Why 200-character overlap?
Without overlap, information at chunk boundaries gets split mid-sentence. With 200-char overlap, each chunk includes the end of the previous chunk — no information lost at boundaries.

### Sentence boundary detection
`text.rfind('. ', start, end)` finds the last period+space within the chunk range. If found in the second half of the chunk, break there instead of at the hard character limit. Produces natural chunks that end at sentence boundaries — easier for the embedding model to understand.

### Scale
14,810 documents × ~8 chunks average = **~129,000 chunks** in ChromaDB. Total ChromaDB size: ~500MB on disk.

---

## 7. Query Routing — Two-Stage Design

### Why routing?
Different query types need different retrieval strategies. Without routing, every query would use the same generic vector search — missing the structured SQL data that makes answers precise.

### Stage 1: Regex fast-path
```python
def fast_route(query: str) -> dict | None:
    q = query.lower()
    # Order matters — more specific patterns first
    if re.search(r'\b(vs|versus|compare|comparison|difference between)\b', q):
        return {"category": "comparison"}
    if re.search(r'\b(rank|ranking|top\s+\d+|best\s+colleges?)\b', q):
        return {"category": "top_colleges"}
    if re.search(r'\b(jee|neet|cat|gate|gmat|clat|exam|entrance)\b', q):
        return {"category": "exam"}
    if re.search(r'\b(rank\s+\d+|\d+\s+rank|percentile|score|predict)\b', q):
        return {"category": "predictor"}
    return None  # fall through to LLM
```

**Why regex first?** For obvious patterns like "VIT vs SRM", regex is ~1ms. An LLM call is ~100–200ms. For 80% of queries, regex is sufficient — the LLM is only called for ambiguous cases.

**Order matters**: `"compare top 10 colleges"` matches both `comparison` and `top_colleges`. Since `comparison` is checked first, it wins. The order encodes priority.

### Stage 2: LLM fallback
```python
ROUTER_PROMPT = """Classify this query about Indian colleges into one category.
Categories: college, comparison, exam, predictor, top_colleges, general
Also extract any college names, exam names, or ranks mentioned.

Query: {query}

Respond in JSON: {"category": "...", "entities": [...]}"""
```

The LLM handles ambiguous queries that regex can't classify: *"Tell me about the best IIT for computer science"* — is this `top_colleges` or `college`? The LLM understands context and intent.

**`parse_router_response()`** handles malformed LLM output:
```python
try:
    return json.loads(response_text)
except json.JSONDecodeError:
    # Extract with regex as fallback
    category_match = re.search(r'"category"\s*:\s*"(\w+)"', response_text)
    return {"category": category_match.group(1) if category_match else "general", "entities": []}
```
The LLM sometimes returns JSON with extra text around it. The regex fallback extracts the category even from malformed responses.

---

## 8. The System Prompt

### Why the system prompt matters
The system prompt is the LLM's instruction manual. It determines:
- Tone and style of responses
- How to use the provided context
- What to do when context is insufficient
- Honesty about limitations

### The prompt structure
```python
SYSTEM_PROMPT = """You are DegreeFYD Assistant, an expert on Indian colleges and entrance exams.

You have access to a database of {college_count} colleges and {exam_count} exams.

Guidelines:
1. Answer based on the provided context. If context is insufficient, say so clearly.
2. For fees, always mention the range and note that fees may have changed since data collection.
3. For NIRF ranks, note the year of ranking if known.
4. For exam dates, always recommend checking the official website for current dates.
5. Be concise but complete. Use bullet points for lists.
6. Never make up information not in the context.
"""
```

**Why "never make up information"?** Without this instruction, LLMs tend to fill gaps with plausible-sounding but incorrect information (hallucination). The explicit instruction reduces (but doesn't eliminate) hallucination.

**Why mention data staleness?** Fees and exam dates change. Telling the LLM to caveat time-sensitive information is more honest than presenting potentially stale data as current fact.

---

## 9. Tradeoffs and Limitations

### Data coverage gaps
- **IIT underrepresentation**: IITs appear in only 5–9 documents each. Mitigated by Self-RAG → web search fallback.
- **Regional colleges**: Many tier-3 colleges have no data. Queries about them will always trigger web search.
- **Data staleness**: Scraped at a point in time. Fees, exam dates, NIRF ranks change annually.

### Regex extraction accuracy
`data_extractor.py` uses regex to extract fees, ranks, locations from messy scraped text. Accuracy is ~85–90% — some fields are missed or incorrectly extracted. The `raw_content` column in SQLite is the safety net.

### NIRF rank as admission proxy
`predictor_handler.py` uses NIRF rank as a proxy for admission difficulty. This is a rough heuristic — actual cutoffs depend on category, branch, year, and seat availability. Documented in the system prompt.

### No conversation memory beyond context window
`conversation_history` is passed to the LLM but there's no persistent storage. If the user closes the browser, history is lost. The `sessionStorage` feature (pending) would add temporary persistence within a session.

### Single-threaded embedding
The sentence-transformer model runs on CPU in a single thread. For high concurrency (many simultaneous users), embedding becomes a bottleneck. Mitigation: GPU deployment, or using an embedding API.

### LLM non-determinism
The same query can produce different answers on different runs. The LLM is stochastic — `temperature > 0` means different token sampling each time. For factual queries, this is mostly fine. For exact numbers (fees, ranks), the SQL context anchors the answer.
