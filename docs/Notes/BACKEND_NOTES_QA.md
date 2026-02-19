# DegreeFYD — Interview Q&A and Debugging Playbook
> Part 4 of the technical notes series. 30 interview questions with detailed answers,
> plus a systematic debugging playbook for every failure mode.
> **Read after `BACKEND_NOTES.md` and `BACKEND_NOTES_2.md`.**

---

## Table of Contents
1. [Interview Q&A — 30 Questions](#1-interview-qa)
2. [Debugging Playbook](#2-debugging-playbook)

---

## 1. Interview Q&A

### RAG & Architecture

**Q1. What is RAG and why did you use it instead of fine-tuning?**

RAG (Retrieval-Augmented Generation) retrieves relevant documents from a knowledge base at query time and injects them into the LLM prompt as context before generating.

I chose RAG over fine-tuning for four reasons:
1. **Data freshness**: Fine-tuning bakes data into weights — updating requires retraining (days, $$$). RAG updates by adding documents (minutes, free).
2. **Hallucination reduction**: Fine-tuned models still hallucinate. RAG grounds the LLM in retrieved documents — it can only say what's in the context.
3. **Transparency**: RAG can show source URLs. Fine-tuning is a black box.
4. **Cost**: Fine-tuning a 7B+ model costs thousands of dollars. RAG with a local embedding model costs near zero.

Tradeoff: RAG adds retrieval latency (~50ms) and depends on retrieval quality. For a domain with frequently-changing data (college fees, exam dates), RAG is clearly the right choice.

---

**Q2. Why build from scratch instead of using LangChain or LlamaIndex?**

1. **Full control**: I know exactly what every line does. When something breaks, I can pinpoint it immediately.
2. **Interview value**: I can explain every decision — why cosine distance, why two models, why a regex fast-path. With LangChain, the answer is often "the framework handles it."
3. **Performance**: No framework overhead. LangChain adds ~200ms per call from its abstraction layers.

Tradeoff: more code to write and maintain. For a project where I need to explain every decision, building from scratch is the right call.

---

**Q3. Why do you use two different Groq models?**

- **`compound-beta`** for final generation: has built-in web search capability. Slower and more expensive but produces the best answers.
- **`llama-3.1-8b-instant`** for routing and Self-RAG reflection: fast (~100ms), cheap, used for classification tasks that just need a short output (one word or a JSON object).

Key insight: not all LLM calls need the same model. Match the model to the task's requirements.

---

**Q4. Walk me through what happens when a user sends a message.**

1. Frontend sends `POST /chat/stream` with query, web search flag, conversation history.
2. FastAPI validates with Pydantic, calls `process_query()`.
3. Query router classifies (regex fast-path → LLM fallback), extracts entities.
4. Self-RAG retrieves documents, checks relevance, optionally rephrases and retries. Sets `auto_web_triggered` if local retrieval is insufficient.
5. Handler retrieves structured data from SQLite + semantic context from ChromaDB, formats into a context string.
6. `query_with_web_search()` builds the system prompt, calls Groq API with streaming.
7. FastAPI streams SSE events: `meta` (category, flags) → `chunk` events (one per token group) → `done`.
8. Frontend reads stream, appends each chunk to the message, triggers React re-renders — text appears word by word.

Time to first visible character: ~500–800ms.

---

**Q5. What is the system prompt and why does it matter?**

The system prompt is the LLM's instruction manual — sent as the first message in every conversation. It tells the LLM its role, how to use the provided context, what to do when context is insufficient, how to handle time-sensitive data, and tone/style.

Without a good system prompt, the LLM might ignore the context and answer from its training data (outdated), or present stale fee data as current fact, or hallucinate NIRF ranks.

---

**Q6. How does conversation history work?**

`conversation_history` is a list of `{role, content}` dicts passed with every request and sent to the Groq API as the `messages` array. The LLM sees the full conversation and can answer follow-up questions with context from previous turns.

The frontend maintains this list in React state and sends it with every new message. Stateless server design — the server doesn't remember anything between requests.

**Limitation**: History is lost when the browser is closed. The pending `sessionStorage` feature would persist history within a browser session.

---

**Q7. How does the frontend know to show the "Auto Web" badge?**

The SSE stream's first event is always a `meta` event containing `auto_web_triggered`. The frontend reads this and updates state. The badge is shown conditionally on `lastBotMsg?.auto_web_triggered`. `lastBotMsg` is derived from the messages array — it resets correctly when the user switches categories or clears the chat.

---

**Q8. What would you change to scale to 10,000 concurrent users?**

1. **Multiple uvicorn workers**: `--workers 4` — each worker is a separate process with its own singleton. 4x throughput.
2. **GPU for embeddings**: ~10ms → ~1ms. Or use an embedding API to offload compute.
3. **Redis for caching**: Replace in-memory dict with Redis. Shared across workers, persistent across restarts.
4. **Managed vector DB**: ChromaDB is single-node. Pinecone/Weaviate for horizontal scaling.
5. **Rate limiting**: Middleware to prevent abuse.

---

### Data & Ingestion

**Q9. Describe the data and its structure.**

`degreefyd_data.jsonl` — 14,810 lines. Each line: `{"url": "...", "type": "comparison|college|blog|exam", "content": "..."}`.

Distribution: comparison 84.8%, college 12.8%, blog 1.1%, exam 0.95%. Critical insight: 85% is comparison data — comparison queries work extremely well, but individual college queries (especially IITs with only 5–9 documents) are weaker.

---

**Q10. Why JSONL instead of JSON?**

1. **Streamable**: Read line by line without loading all 14,810 records into memory.
2. **Fault tolerant**: One malformed line doesn't break the whole file — `try/except json.JSONDecodeError: continue`.
3. **Appendable**: Add new records by appending lines. A JSON array requires reading and rewriting the entire file.

---

**Q11. Why use regex for data extraction instead of an LLM?**

Speed and cost. 14,810 records × ~500ms per LLM call = **2+ hours** and significant API costs. Regex processes all records in **under 30 seconds** and costs nothing. The data has consistent enough patterns (scraped from a single website) that regex works well (~85–90% accuracy). The `raw_content` fallback ensures the LLM can still access the original text.

---

**Q12. How does `INSERT OR IGNORE` work and why is it important?**

If an `INSERT` would violate a `UNIQUE` constraint, `INSERT OR IGNORE` silently skips it instead of raising an error. Makes ingestion **idempotent** — running it multiple times produces the same result as running it once. Critical for development: re-run ingestion after fixing a bug without wiping the database first.

---

**Q13. How do you handle duplicate college entries?**

`data_extractor.py`'s `get_unique_colleges()` deduplicates by normalized college name (lowercase, stripped) before insertion, keeping the entry with the most complete data. The `UNIQUE` constraint on `colleges.name` + `INSERT OR IGNORE` provides a second layer at the database level.

---

**Q14. What is the ingestion pipeline flow?**

```
degreefyd_data.jsonl
  → data_extractor.py: load_jsonl() → parse_*_record() (regex extraction)
  → db_setup.py: CREATE tables → INSERT OR IGNORE records
  → vector_store.py: chunk_text() → extract metadata → batch insert into ChromaDB
```
Total time: ~15–30 minutes (dominated by embedding 129,000 chunks on CPU).

---

### Retrieval & Search

**Q15. How does ChromaDB's vector search work?**

1. Query text is embedded using `all-MiniLM-L6-v2` → 384-dim vector
2. HNSW index finds approximate K nearest vectors using cosine distance
3. Returns K most similar chunks with metadata and distance scores

Optional `where` clause filters by metadata before search — e.g., `where={"doc_type": "college"}` only searches college documents.

---

**Q16. What is cosine distance and why use it over Euclidean?**

Cosine distance = `1 - cosine_similarity(A, B)`. Measures the **angle** between vectors, not magnitude. Two documents about the same topic but different lengths have similar cosine distance. Euclidean distance penalizes length differences — a long document about VIT would be "far" from a short query about VIT even if the topic is identical. For text, cosine is almost always correct.

---

**Q17. How do you decide when to use web search vs local retrieval?**

Three conditions trigger web search:
1. **User toggle**: explicit "Web ON" in the frontend
2. **Self-RAG auto-trigger**: `check_relevance()` returns `"partial"` or `"irrelevant"` after both retrieval attempts
3. **Distance threshold**: best ChromaDB result has cosine distance > 0.5 → poor match → web search

---

**Q18. Why does the comparison handler over-fetch and then filter?**

ChromaDB's `where` clause only supports exact metadata matches. College names in metadata might differ from the query (e.g., metadata has `"VIT Vellore"` but query says `"VIT"`). Python substring check (`name.lower() in content.lower()`) handles partial names, abbreviations, and case differences. Over-fetching by 2x ensures enough results remain after filtering.

---

**Q19. What metadata do you store with each ChromaDB document?**

```python
{"url": "...", "doc_type": "comparison|college|exam|blog",
 "college_1": "VIT Vellore", "college_2": "SRM University"}  # for comparison docs
# OR
{"url": "...", "doc_type": "college", "college": "DTU Delhi"}
# OR
{"url": "...", "doc_type": "exam", "exam": "JEE Advanced"}
```
Metadata enables filtered search — a query about JEE only searches exam documents, not comparison pages that happen to mention JEE.

---

**Q20. How does the predictor handler work and what are its limitations?**

Parses rank/score from query with regex → maps rank to NIRF threshold (`nirf_threshold = max(10, rank // 100)`) → queries SQLite for colleges with `nirf_rank <= threshold`.

**Limitations**: NIRF rank ≠ admission cutoff rank. No branch-specific or category-specific cutoffs. No year-specific data. The system prompt explicitly tells the LLM to present results as "colleges you might consider" and recommend official counselling portals.

---

### API & Streaming

**Q21. What is FastAPI and why use it over Flask?**

FastAPI is an async Python web framework. Key advantages over Flask:
1. **Native async**: `async def` route handlers work natively
2. **Auto validation**: Pydantic models validate request/response automatically
3. **Auto docs**: Swagger UI at `/docs` generated automatically
4. **Performance**: One of the fastest Python frameworks due to async I/O

For a streaming API with async Groq calls, FastAPI is the natural choice.

---

**Q22. How does `StreamingResponse` work in FastAPI?**

Takes an async generator and streams its yielded values to the client as they're produced. FastAPI iterates the generator and sends each yielded value immediately — doesn't wait for the generator to finish. The client receives chunks as they're produced, appearing word by word in the browser.

---

**Q23. Why does `/chat/stream` use POST instead of GET?**

1. **Length**: Queries can be long. URLs have ~2000 char limits; request bodies have no practical limit.
2. **Privacy**: URLs are logged by servers and proxies. Request bodies are not.
3. **Semantics**: POST is correct for operations that trigger computation.

Tradeoff: `EventSource` (native SSE API) only supports GET. We use `fetch()` + `ReadableStream` instead, which supports POST but requires manual SSE parsing.

---

**Q24. What does `X-Accel-Buffering: no` do?**

Nginx buffers HTTP responses by default — waits until the full response is ready before sending. This completely defeats SSE streaming. `X-Accel-Buffering: no` tells nginx to pass each chunk through immediately. Without it: SSE works locally (no nginx) but silently buffers in production. A common production gotcha.

---

**Q25. How does CORS work and why is it needed?**

The browser's Same-Origin Policy blocks JavaScript from requesting a different origin (different port = different origin). React on 5173, FastAPI on 8000 → different origins → CORS required.

The server adds `Access-Control-Allow-Origin` headers. `CORSMiddleware` in FastAPI adds these automatically. Specific origins (not `"*"`) are required because `allow_credentials=True` — browsers reject `credentials: include` with wildcard origins.

---

### Self-RAG & Advanced

**Q26. Explain Self-RAG in simple terms.**

Standard RAG: retrieve → inject → generate. No quality check on retrieved documents.

Self-RAG adds a reflection step: after retrieving, ask the LLM *"are these documents actually relevant?"* If yes, proceed. If no, rephrase the query and try again. If still insufficient, fall back to web search.

Like a researcher who, after finding papers, pauses to ask "do these actually answer my question?" before writing. If off-topic, they search again with better keywords.

---

**Q27. Why use `llama-3.1-8b-instant` for Self-RAG instead of the main model?**

For relevance check and query rephrasing, we only need a short output (one word or a short sentence). `llama-3.1-8b-instant` is ~100ms vs ~500ms for `compound-beta`. Using the powerful model for classification tasks would be slower, more expensive, and unnecessary. Use the smallest model that can do the job.

---

**Q28. What happens if the Groq API is down?**

The system degrades gracefully:
- **Routing fails**: returns `{"category": "general", "entities": []}` — proceeds with general vector search
- **Self-RAG check fails**: returns `"partial"` (safe default) — proceeds with whatever was retrieved
- **Final generation fails**: raises exception → FastAPI returns HTTP 500 → frontend shows error state

Failures in routing or Self-RAG don't crash the pipeline — they use safe defaults.

---

**Q29. How would you add a new query category (e.g., "scholarships")?**

1. Add to `CATEGORIES` in `config.py`
2. Add regex pattern in `query_router.py` `fast_route()`
3. Create `scholarship_handler.py` in `src/handlers/` with `build_prompt_context()`
4. Add to `handler_map` in `rag_chain.py`
5. Add SQL table in `db_setup.py` if needed
6. Add extraction logic in `data_extractor.py` if needed
7. Add frontend category in `constants.ts`

The handler pattern makes adding categories straightforward — each is isolated, changes don't affect others.

---

**Q30. What are the biggest technical risks in this system?**

1. **Groq API dependency**: Entire system depends on Groq availability. Mitigation: fallback to local model (Ollama) or different provider.
2. **Embedding model drift**: If `all-MiniLM-L6-v2` is updated, stored vectors become inconsistent with new query vectors. Mitigation: pin model version, re-embed if changed.
3. **ChromaDB corruption**: Process killed mid-write could corrupt the HNSW index. Mitigation: ChromaDB has WAL for crash recovery; use managed vector DB in production.
4. **Data staleness**: Fees, exam dates, NIRF ranks change annually. Mitigation: scheduled re-scraping, or always use web search for time-sensitive queries.
5. **Regex extraction brittleness**: If degreefyd.com changes templates, patterns break. Mitigation: add test cases for extraction, monitor success rates.

---

## 2. Debugging Playbook

### Self-RAG always returns "irrelevant"
**Symptom**: Every query triggers auto web search. "Auto Web" badge on every response.

**Diagnose**:
```python
from src.vector_store import get_collection
print(get_collection().count())  # should be ~129,000. If 0, ingestion didn't run.

import os; print(os.getenv("GROQ_API_KEY"))  # should not be None

from src.self_rag import check_relevance
import asyncio
docs = [{"content": "VIT Vellore fee is 1,98,000 per year", "url": "test"}]
print(asyncio.run(check_relevance("What is the fee at VIT?", docs)))  # should be "relevant"
```

**Fix**:
- `count() == 0` → run `python ingest.py`
- `GROQ_API_KEY` is None → set in `.env`
- LLM returns a sentence instead of one word → the `if verdict in (...)` check fails, defaults to `"partial"`. Make the prompt more explicit: add `"Do not explain. Reply with exactly one word only."`

---

### Streaming stops mid-response
**Symptom**: Response starts appearing but cuts off. Typing indicator disappears without a `done` event.

**Diagnose**:
```bash
# Check FastAPI logs for:
# "groq.RateLimitError" — hit rate limit
# "groq.APIConnectionError" — network issue

# Test stream directly:
curl -X POST http://localhost:8000/chat/stream \
  -H "Content-Type: application/json" \
  -d '{"query": "What is VIT?"}' --no-buffer
```

**Fix**:
- Rate limit → add retry with exponential backoff in `web_search.py`
- Timeout → increase: `Groq(timeout=60.0)`
- Client disconnect (user navigated away) → add `try/except GeneratorExit: return` in `event_generator()`

---

### Wrong category detected
**Symptom**: Comparison query classified as `college`, or exam query as `general`.

**Diagnose**:
```python
from src.query_router import route_query, fast_route
import asyncio
print(fast_route("Compare VIT and SRM fees"))          # should be {"category": "comparison"}
print(asyncio.run(route_query("Compare VIT and SRM"))) # should include entities
```

**Fix**:
- Regex fast-path: check pattern order in `fast_route()` — earlier patterns win. Reorder or make patterns more specific.
- LLM fallback: add more examples of the misclassified query type to `ROUTER_PROMPT`.
- Entity extraction: check `parse_router_response()` — LLM might return malformed JSON. The regex fallback might extract the wrong category.

---

### ChromaDB returns wrong/irrelevant results
**Symptom**: Queries return unrelated documents. Self-RAG always returns `"irrelevant"` for queries that should have good local data.

**Diagnose**:
```python
from src.vector_store import search_by_type
results = search_by_type("fee at VIT Vellore", doc_type='college', n_results=5)
for r in results:
    print(r['distance'], r['content'][:100])
# distance < 0.3 = good match, > 0.5 = poor match
```

**Fix**:
- High distances (> 0.5): query is too short/vague. Try a more specific query.
- Wrong `doc_type` filter: check that metadata was correctly set during ingestion. `search_by_type(query, doc_type='college')` only searches college docs.
- Stale index: delete `data/chroma_db/` and re-run ingestion.

---

### Frontend shows "Auto Web" badge incorrectly
**Symptom**: Badge appears when web search wasn't triggered, or persists after clearing chat.

**Diagnose**:
- Check the `meta` SSE event in browser DevTools → Network → `/chat/stream` → EventStream tab. Verify `auto_web_triggered` value.
- Check `lastBotMsg` derivation in `App.tsx` — it should be derived from `messages` filtered to the current category.

**Fix**:
- If `auto_web_triggered` is wrong in the `meta` event: trace back to `rag_chain.py` — check `auto_web_triggered` value before it's passed to `query_with_web_search()`.
- If badge persists after clear: check that `setAllMessages({})` (or equivalent) resets the full messages object to empty. `lastBotMsg` should be `undefined` when messages is empty.

---

### Backend starts but first query is very slow (3–5 seconds)
**Symptom**: Server starts fine, but the first query takes 3–5 seconds. Subsequent queries are fast.

**Cause**: `warmup()` failed silently. The singleton wasn't initialized at startup, so the first query triggers model loading.

**Diagnose**:
```bash
# Check startup logs for:
# "Warmup complete — models ready"  ← good
# "Warmup failed: ..."              ← bad
```

**Fix**:
- Check ChromaDB path: `data/chroma_db/` must exist and be readable. If ingestion hasn't run, the directory might not exist.
- Check sentence-transformer model: first run downloads the model (~80MB). If download failed, warmup fails. Check internet connectivity or manually download: `python -c "from sentence_transformers import SentenceTransformer; SentenceTransformer('all-MiniLM-L6-v2')"`

---

### SQL queries return no results for known colleges
**Symptom**: `query_college("VIT Vellore")` returns `None` even though VIT is in the dataset.

**Diagnose**:
```python
import sqlite3
from src.config import SQLITE_DB
conn = sqlite3.connect(SQLITE_DB)
# Check if table exists and has data
print(conn.execute("SELECT COUNT(*) FROM colleges").fetchone())
# Check exact name stored
rows = conn.execute("SELECT name FROM colleges WHERE name LIKE '%VIT%'").fetchall()
print(rows)
```

**Fix**:
- Table empty → run ingestion
- Name mismatch: the stored name might be `"VIT"` but the query is `"VIT Vellore"`. Check `query_college()` — it uses `LIKE '%{name}%'` for fuzzy matching. If the name is too short (e.g., just `"VIT"`), it might match multiple colleges. Make the entity extraction more specific.
- Encoding issue: Indian college names with special characters might be stored with different encoding. Check `encoding='utf-8'` in `load_jsonl()`.

---

### Port already in use error on startup
**Symptom**: `uvicorn: error: [Errno 10048] Only one usage of each socket address` (Windows) or `Address already in use` (Linux/Mac).

**Fix**:
```powershell
# Windows: find and kill process on port 8000
netstat -ano | findstr :8000
taskkill /PID <PID> /F

# Or kill all relevant ports at once:
@(8000, 5173, 5174) | ForEach-Object { 
    $p = netstat -ano | findstr ":$_" | ForEach-Object { ($_ -split '\s+')[-1] }
    if ($p) { taskkill /PID $p /F }
}
```

---

### `GROQ_API_KEY` not found
**Symptom**: `groq.AuthenticationError: No API key provided`.

**Fix**:
1. Create `.env` file in project root: `GROQ_API_KEY=gsk_your_key_here`
2. Ensure `load_dotenv()` is called in `config.py` before `os.getenv("GROQ_API_KEY")`
3. Verify: `python -c "from src.config import GROQ_API_KEY; print(GROQ_API_KEY[:10])"`

Never commit the `.env` file to git. Add it to `.gitignore`.
