# DegreeFYD — Dual Database Deep Dive: SQLite + ChromaDB
> Interview-ready notes. Every design decision has a "why this, not that" justification.
> Every gap has a "how would you fix it" answer. Read this until you can explain
> any part of the database layer from first principles in an interview.

---

## How to Use These Notes
Each section has **`> Interview angle:`** callouts — these are the exact framings
you should use when an interviewer asks about that topic. Memorize the one-liner,
then expand with the detail below it.

---

## Table of Contents
1. [Why Two Databases?](#1-why-two-databases)
2. [SQLite — Design & Schema](#2-sqlite--design--schema)
3. [ChromaDB — Design & Schema](#3-chromadb--design--schema)
4. [Every SQL Query in the Codebase](#4-every-sql-query-in-the-codebase)
5. [Every Vector Query in the Codebase](#5-every-vector-query-in-the-codebase)
6. [Handler-by-Handler Breakdown](#6-handler-by-handler-breakdown)
7. [Query Scenario Matrix](#7-query-scenario-matrix)
8. [Known Gaps & How to Fix Them](#8-known-gaps--how-to-fix-them)

---

## 1. Why Two Databases?

**Concept**: A database is just a tool for storing and retrieving data. Different tools are optimized for different retrieval patterns. SQL databases are built for *exact, structured lookups* — give me the row where `name = 'VIT'`. Vector databases are built for *semantic similarity search* — give me the chunks most *similar in meaning* to this question. The problem is that a real-world dataset has both kinds of data: hard facts (rank = 11) and soft narrative ("vibrant campus culture"). No single database handles both well, so you use two — each doing what it's best at.

> **Interview one-liner**: *"I used a hybrid storage approach — SQLite for structured exact lookups and ChromaDB for semantic search over unstructured text. These two retrieval needs are fundamentally incompatible in a single system."*

The dataset has two types of information:
1. **Structured facts** — NIRF rank = 11, fee = 1,98,000, location = Vellore. Need exact retrieval.
2. **Unstructured narrative** — "VIT has strong industry connections, 400+ placement companies, vibrant campus." Needs semantic understanding.

### Why not SQL only?
SQL handles: `SELECT nirf_rank FROM colleges WHERE name LIKE '%VIT%'` — perfect.

SQL cannot handle: *"Which colleges have vibrant campus culture?"* — no column for that. It's buried in paragraphs of scraped text. SQLite's FTS5 (full-text search) is keyword-based, not meaning-based — *"vibrant"* wouldn't match *"lively student community"*.

> **Follow-up**: *"Could you use PostgreSQL + pgvector instead of two databases?"*
> **Answer**: Yes — pgvector adds vector search to Postgres. But that requires a Postgres server (not file-based like SQLite), adds operational complexity, and is overkill for a local dev project. SQLite + ChromaDB is zero-config and perfectly adequate for this scale.

### Why not ChromaDB only?
ChromaDB cannot reliably answer *"What is the exact NIRF rank of VIT Vellore?"* — it might return a chunk saying *"VIT is ranked among the top 15"* instead of the exact number `11`. No exact lookups, no range queries, no `ORDER BY`.

> **Follow-up**: *"Couldn't you store structured data as ChromaDB metadata?"*
> **Answer**: ChromaDB metadata only supports exact equality filters (`where={"nirf_rank": 11}`). You can't do range queries (`nirf_rank < 50`), can't sort by metadata, can't join two entities. For `WHERE nirf_rank <= threshold ORDER BY nirf_rank ASC`, ChromaDB metadata is completely inadequate.

### The decision matrix

| Need | Database | Why the other fails |
|---|---|---|
| Exact college facts (rank, fee, location) | SQLite | ChromaDB returns approximate matches |
| Top N colleges by rank | SQLite | ChromaDB can't `ORDER BY` metadata |
| VIT vs SRM side-by-side | SQLite | ChromaDB can't JOIN two entities |
| "Good placements", "campus life" | ChromaDB | No SQL column for narrative concepts |
| JEE preparation tips | ChromaDB | 161 blog posts — no SQL equivalent |
| Fallback when SQL has no match | ChromaDB | SQL returns NULL, ChromaDB always finds something |

**Mental model**: SQLite = fact sheet (numbers, ranks, dates). ChromaDB = library (all 14,810 scraped pages, searchable by meaning).

---

## 2. SQLite — Design & Schema

**Concept**: SQLite is a file-based relational database — the entire database lives in a single `.db` file, no server needed. You define a schema upfront (column names + types), insert rows, and query with SQL. "Schema design" means deciding: which facts deserve their own column (so SQL can filter/sort on them), and which facts are too messy to extract reliably (leave them as raw text). Every column is a bet that you can extract that value consistently from the scraped data. When that bet fails — like with `application_start` — you get a column that's always NULL.

> **Interview angle**: *"I designed the SQLite schema to match exactly what can be reliably extracted from the scraped data using regex. Every column has a corresponding extraction function in `data_extractor.py` — except for the exam table where I have a known gap I can explain."*

**File**: `data/degreefyd.db`
**Populated by**: `python db_setup.py` — runs once at setup, calls `data_extractor.py` regex parsers, inserts into 4 tables.

---

### Table 1: `colleges`

```sql
CREATE TABLE IF NOT EXISTS colleges (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    name             TEXT NOT NULL UNIQUE,  -- "VIT Vellore"
    location         TEXT,                  -- "Vellore, Tamil Nadu"
    college_type     TEXT,                  -- "Private" | "Government"
    established_year INTEGER,               -- 1984
    nirf_rank        INTEGER,               -- 11  ← only field usable for range queries
    rating           REAL,                  -- 4.2
    total_students   INTEGER,               -- 35000
    courses_offered  INTEGER,               -- 87  ← COUNT only, NOT course names
    fee_range        TEXT,                  -- "1,98,000 - 3,50,000" ← raw string, NOT a number
    url              TEXT
)
```

**Design decisions — each with interview justification:**

- **`name TEXT UNIQUE`**: Enforces deduplication at the DB level. Combined with `INSERT OR IGNORE`, running ingestion multiple times never creates duplicate rows — idempotency guaranteed.
  > **Follow-up**: *"Why not use a surrogate key and allow duplicate names?"*
  > **Answer**: College names are the natural key here. Duplicates would mean the same college appears twice with contradictory data — the LLM would get conflicting context. `UNIQUE` prevents this at the DB level so no application-level deduplication logic is needed.

- **`courses_offered INTEGER`**: A **count** (e.g., 87), NOT course names. The regex extracts *"87 courses offered"* from the page text. This is the biggest gap — you cannot filter by course name in SQL.
  > **Follow-up**: *"How would you fix this?"*
  > **Answer**: Add a separate `courses` table: `(id, college_id INTEGER REFERENCES colleges(id), course_name TEXT, fee INTEGER, duration TEXT)`. Then `WHERE course_name = 'MBA' AND fee < 150000` becomes a proper SQL query. The challenge is extraction — course names are buried in unstructured text and need more sophisticated regex or LLM-based extraction at ingestion time.

- **`fee_range TEXT`**: Raw string like `"1,98,000 - 3,50,000"`. NOT a number. Cannot do `WHERE fee < 150000`. The LLM must parse this string mentally.
  > **Follow-up**: *"Why not parse it into two integer columns?"*
  > **Answer**: I should have. The fix: `fee_min INTEGER, fee_max INTEGER` — strip commas from `"1,98,000"` → `198000`. Then `WHERE fee_min < 150000` works. I didn't do this because fee strings are inconsistent — some say `"1,98,000 per year"`, some say `"INR 1.98 Lakhs"`, some say `"2-4 Lakhs"`. A robust parser needs significant regex work.

- **`nirf_rank INTEGER`**: The only numeric field usable for range queries. Used by `PredictorHandler` (`nirf_rank <= threshold`) and `TopCollegesHandler` (`ORDER BY nirf_rank ASC`).

**What's NOT in this table**: course names, branch-specific fees, placement percentages, hostel details, accreditation. All of that is only in ChromaDB as raw scraped text.

---

### Table 2: `comparisons`

```sql
CREATE TABLE IF NOT EXISTS comparisons (
    id                 INTEGER PRIMARY KEY AUTOINCREMENT,
    college_1          TEXT NOT NULL,        -- "VIT Vellore"
    college_2          TEXT NOT NULL,        -- "SRM University"
    college_1_fees     TEXT,                 -- "1,98,000"
    college_2_fees     TEXT,                 -- "1,80,000"
    college_1_nirf     INTEGER,              -- 11
    college_2_nirf     INTEGER,              -- 36
    college_1_courses  INTEGER,              -- 87
    college_2_courses  INTEGER,              -- 120
    college_1_year     INTEGER,              -- 1984
    college_2_year     INTEGER,              -- 1985
    college_1_students INTEGER,              -- 35000
    college_2_students INTEGER,              -- 20000
    college_1_type     TEXT,                 -- "Private"
    college_2_type     TEXT,                 -- "Private"
    college_1_rating   REAL,                 -- 4.2
    college_2_rating   REAL,                 -- 4.0
    college_1_location TEXT,                 -- "Vellore, Tamil Nadu"
    college_2_location TEXT,                 -- "Chennai, Tamil Nadu"
    url                TEXT,
    UNIQUE(college_1, college_2)
)
```

**Design decisions — each with interview justification:**

- **Denormalized flat row**: Both colleges' data in one row, no JOIN needed. A normalized design would have a `colleges` table and a JOIN — but JOIN requires exact name matching, and college names are inconsistent across the dataset ("VIT" vs "VIT Vellore" vs "VIT University"). A flat denormalized row keeps each comparison page's data together and avoids name-matching failures.
  > **Follow-up**: *"Isn't denormalization bad practice?"*
  > **Answer**: Denormalization is a deliberate tradeoff — you trade storage efficiency for query simplicity and reliability. Here, the data source (comparison pages) is already denormalized — each page has both colleges' data. Mirroring that structure in the DB is the most faithful representation. Normalization would add JOIN complexity and name-matching fragility without any real benefit at this scale.

- **`UNIQUE(college_1, college_2)`**: Prevents duplicate pairs. `INSERT OR IGNORE` skips if the pair already exists. Note this is order-sensitive — `(VIT, SRM)` and `(SRM, VIT)` are treated as different pairs. The query handles both orderings with an `OR` clause.

- **Populated from 12,559 comparison pages**: Each "A vs B" page in the JSONL becomes one row. This is why comparison queries are the best-answered category — there's a purpose-built SQL row for almost every college pair in the dataset.

---

### Table 3: `exams`

```sql
CREATE TABLE IF NOT EXISTS exams (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    name              TEXT NOT NULL,   -- "JEE Main"
    full_name         TEXT,            -- ← ALWAYS NULL — schema exists, never inserted
    exam_date         TEXT,            -- "April 2024"
    application_start TEXT,            -- ← ALWAYS NULL — schema exists, never inserted
    application_end   TEXT,            -- ← ALWAYS NULL — schema exists, never inserted
    result_date       TEXT,            -- ← ALWAYS NULL — schema exists, never inserted
    conducting_body   TEXT,            -- "NTA"
    exam_mode         TEXT,            -- "Online"
    duration          TEXT,            -- "3 hours"
    url               TEXT,
    raw_content       TEXT             -- full scraped page text — the fallback
)
```

**Critical gap — 4 columns always NULL.** `insert_exams()` only inserts 7 fields:
```python
INSERT INTO exams (name, exam_date, conducting_body, exam_mode, duration, url, raw_content)
```
`full_name`, `application_start`, `application_end`, `result_date` are **defined in the schema but never populated** — `data_extractor.py` doesn't have regex patterns for them.

> **Interview angle**: *"This is a known gap I'd fix in the next iteration. The schema was designed optimistically — I added columns I intended to populate but didn't finish the extraction logic. The `raw_content` column is the safety net: the full page text is always stored, so the LLM can extract application dates from prose even when the structured field is NULL."*

**Real-world impact**: Queries like *"when do JEE application forms open?"* get `application_start=NULL` from SQL. The answer comes from `raw_content` (full page text blob) or ChromaDB vector chunks. This is exactly why Self-RAG returns `"partial"` for application date queries — the retrieved docs are about JEE generally, not specifically about application dates.

> **Follow-up**: *"How would you fix this?"*
> **Answer**: Add regex patterns in `data_extractor.py` to extract application dates. Exam pages have consistent patterns like *"Application Start Date: November 1, 2024"* or *"Registration opens: 01 Nov 2024"*. Two regex patterns with date parsing would populate `application_start` and `application_end`. Then `query_exam("JEE Main")` returns actual dates instead of NULL.

**`raw_content`**: The entire scraped page stored as TEXT. The LLM reads this when structured fields are NULL and extracts the answer from prose. It's the fallback that prevents total failure — even with 4 NULL columns, the exam handler still provides useful context.

---

### Table 4: `blogs`

```sql
CREATE TABLE IF NOT EXISTS blogs (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    title             TEXT,            -- "How to prepare for JEE Main 2024"
    author            TEXT,
    date              TEXT,
    college_mentioned TEXT,            -- first college name found in content
    url               TEXT UNIQUE,
    content           TEXT             -- full blog text
)
```

**This table is never queried at runtime by any handler.** All blog retrieval goes through ChromaDB (`search_by_type(query, doc_type='blog')`). The table exists for potential future use but is currently dead code at query time.

> **Interview angle**: *"The blogs table is a good example of designing for future extensibility. Right now blogs are only accessed via semantic search — but if I wanted to add a 'Recent Articles' feature, filter blogs by author, or show blogs published after a certain date, the SQL table is already there. The data is ingested once into both SQLite and ChromaDB, so adding SQL-based blog features later costs zero re-ingestion."*

---

## 3. ChromaDB — Design & Schema

**Concept**: A vector database stores text as numbers — specifically as a list of 384 numbers called an *embedding* or *vector*. The embedding model (`all-MiniLM-L6-v2`) reads a sentence and outputs 384 numbers that represent its *meaning*. Similar meanings → similar numbers → close together in 384-dimensional space. At query time, your question gets converted to the same 384 numbers, and the database finds the stored chunks whose numbers are closest. This is why it can match "vibrant campus" to "lively student community" — both map to nearby points in vector space, even though they share no keywords. ChromaDB is the library that stores these vectors, builds an index over them, and answers "find me the nearest N" in milliseconds.

> **Interview angle**: *"ChromaDB is the semantic layer of the system. Every one of the 14,810 scraped pages is chunked, embedded, and stored here. At query time, the user's question is embedded into the same vector space and the nearest chunks are retrieved — no keyword matching, pure meaning-based search."*

**Directory**: `data/chroma_db/`
**Collection**: `degreefyd_docs`
**Embedding model**: `all-MiniLM-L6-v2` (384-dim vectors, ~80MB, CPU)
**Index type**: HNSW with cosine distance

### Ingestion pipeline

```
JSONL record (content = ~2000 chars)
  → chunk_text(content, chunk_size=1000, overlap=200)
      → ["chunk_0", "chunk_1", ...]  (sentence-boundary aware)
  → extract_college_names_from_content() → ["VIT Vellore", "SRM University"]
  → extract_exam_names_from_content()    → ["JEE", "NEET"]
  → Build metadata per chunk:
      {type, url, chunk_index, total_chunks, college_names, exam_names}
  → collection.add(ids, documents, metadatas)
      ChromaDB auto-embeds each chunk → 384-dim vector
      Stores: vector + raw text + metadata
      Builds HNSW index on disk
```

Total: ~129,000 chunks from 14,810 pages. Ingestion time: ~15–30 min on CPU.

### Document "schema" (metadata per chunk)

Unlike SQL, ChromaDB has no fixed schema. Every document has:

```python
{
    "document": "VIT Vellore offers B.Tech in CSE with fees of 1,98,000...",
    "metadata": {
        "type":          "comparison",              # college|comparison|exam|blog
        "url":           "https://degreefyd.com/compare/vit-vs-srm",
        "chunk_index":   0,                         # which chunk of the original page
        "total_chunks":  3,                         # how many chunks this page split into
        "college_names": "VIT Vellore,SRM University",  # comma-separated string
        "exam_names":    ""                         # comma-separated string (if any)
    },
    "id":       "4521_0",   # f"{record_index}_{chunk_index}"
    "distance": 0.23        # cosine distance from query (returned at search time)
}
```

> **Follow-up**: *"Why store `college_names` as a comma-separated string instead of an array?"*
> **Answer**: ChromaDB metadata values must be strings, integers, floats, or booleans — no arrays. Comma-separated string is the only option. The downside: filtering by college name requires a Python substring check after retrieval, not a ChromaDB `where` clause.

### Chunking strategy — every decision justified

```python
def chunk_text(text, chunk_size=1000, overlap=200):
    while start < len(text):
        end = start + chunk_size
        # Try to break at sentence boundary
        for sep in ['. ', '.\n', '? ', '!\n']:
            last_sep = text[start:end].rfind(sep)
            if last_sep > chunk_size // 2:   # only if boundary is in second half
                end = start + last_sep + len(sep)
                break
        chunks.append(text[start:end].strip())
        start = end - overlap   # 200-char overlap
```

- **1000 chars**: Long enough to contain a complete fact with context. Short enough that the embedding captures a specific topic rather than a generic "this is about colleges" signal. Too long → diluted embedding. Too short → incomplete facts.
  > **Follow-up**: *"How did you choose 1000?"* Standard recommendation for RAG is 512–1500 chars. 1000 is the midpoint — works well for the ~2000-char average page length in this dataset (produces 2–3 chunks per page).

- **200-char overlap**: A fact might straddle a chunk boundary — *"The fee at VIT is"* ends chunk 0, *"1,98,000 per year"* starts chunk 1. Overlap ensures the complete sentence appears in at least one chunk.
  > **Follow-up**: *"What's the tradeoff of larger overlap?"* More overlap = more duplicate content stored = larger index = slower search. 200 chars (20% of chunk size) is the standard recommendation.

- **Sentence boundary detection**: Prevents chunks starting mid-sentence like *"...and the placement rate is 95%"*. The embedding model doesn't know what *"and"* refers to — it produces a poor embedding. Breaking at `'. '` or `'.\n'` keeps chunks semantically complete.

### HNSW + cosine distance — why these choices

**HNSW (Hierarchical Navigable Small World)**:
- Approximate nearest neighbor search: O(log n) instead of O(n) brute force
- Builds a multi-layer graph where each node connects to its nearest neighbors
- At query time: start at top layer, greedily navigate toward the query vector, descend layers
- "Approximate" means it might miss the absolute nearest neighbor, but finds a very good one in milliseconds

**Cosine distance** (`"hnsw:space": "cosine"`):
- Measures the **angle** between vectors, not their magnitude
- Two documents about the same topic but different lengths have similar cosine distance
- Euclidean distance would penalize length differences — a long VIT page would be "far" from a short VIT query even if the topic is identical
- For text embeddings, cosine is almost always the right choice

> **Follow-up**: *"What does a cosine distance of 0.23 mean?"*
> **Answer**: Cosine distance = `1 - cosine_similarity`. Distance 0 = identical direction (same meaning). Distance 1 = perpendicular (unrelated). Distance 2 = opposite. In practice: < 0.3 = strong match, 0.3–0.5 = moderate match, > 0.5 = poor match → triggers web search fallback.

**Persistent on disk**: Stored in `data/chroma_db/`. Loaded into memory at startup via `warmup()`. Without warmup, first query takes 3–5 seconds (loading HNSW index + embedding model). With warmup: ~200ms.

---

## 4. Every SQL Query in the Codebase

**Concept**: A SQL query is an instruction to the database: "find rows matching these conditions, in this order, up to this limit." `SELECT` picks columns, `WHERE` filters rows, `ORDER BY` sorts, `LIMIT` caps results. `LIKE '%VIT%'` is a wildcard match — the `%` means "anything before or after". Parameterized queries (`?` placeholders) are how you safely pass user input — the database treats the value as data, never as SQL code, which prevents SQL injection attacks. Every query here returns either one row (a dict) or a list of rows (a list of dicts), which the handler then formats into context for the LLM.

> **Interview angle**: *"There are only 5 SQL queries in the entire system. Each is a simple single-table SELECT — no JOINs, no subqueries, no transactions. The complexity lives in the Python layer, not the SQL layer."*

---

### `query_college(name)` — `db_setup.py:259`
```sql
SELECT * FROM colleges WHERE name LIKE ? LIMIT 1
-- param: '%VIT Vellore%'
```
**Returns**: one dict with all 11 columns, or `None`.
**Used by**: `CollegeHandler`, `ComparisonHandler` (×2 — once per college), `PredictorHandler`.

**Known issue**: `LIKE '%VIT%'` matches "VIT Vellore", "VIT University", "VIT Chennai" — returns whichever SQLite finds first (undefined order, depends on insertion order).
> **Fix**: `ORDER BY LENGTH(name) ASC LIMIT 1` — prefers the shortest (most exact) match. Or try exact match first, fall back to fuzzy: `WHERE name = ? OR name LIKE ?`.

**Security**: Uses parameterized query (`?`) — immune to SQL injection. Never use f-strings for SQL.

---

### `query_comparison(college1, college2)` — `db_setup.py:281`
```sql
SELECT * FROM comparisons
WHERE (college_1 LIKE ? AND college_2 LIKE ?)
   OR (college_1 LIKE ? AND college_2 LIKE ?)
LIMIT 1
-- params: ('%VIT%', '%SRM%', '%SRM%', '%VIT%')
```
**Why the `OR` clause?** The table stores pairs in the order they appear on the scraped page — sometimes "VIT vs SRM", sometimes "SRM vs VIT". The `OR` handles both orderings so the query always finds the pair regardless of which college is listed first.

**Returns**: one dict with all 19 comparison columns, or `None`.

> **Follow-up**: *"Why not normalize the pair order at insertion time (always store alphabetically)?"*
> **Answer**: That would work and remove the need for the `OR` clause. The current approach is simpler at insertion time (no sorting logic) but slightly more complex at query time. Both are valid — the `OR` approach is fine at this scale.

---

### `query_exam(name)` — `db_setup.py:313`
```sql
SELECT * FROM exams WHERE name LIKE ? OR full_name LIKE ? LIMIT 1
-- params: ('%JEE%', '%JEE%')
```
**Dead code alert**: `full_name` is always NULL (never inserted), so `OR full_name LIKE ?` never matches anything. Only `name LIKE ?` ever fires. The second condition is wasted work.

> **Interview angle**: *"This is a bug I can identify — the `OR full_name LIKE ?` clause is dead code because `full_name` is never populated. In a code review I'd flag this and either remove the clause or fix the insertion to populate `full_name`."*

---

### `query_top_colleges(limit, location)` — `db_setup.py:330`
```sql
-- With location:
SELECT * FROM colleges
WHERE nirf_rank IS NOT NULL AND location LIKE ?
ORDER BY nirf_rank ASC LIMIT ?
-- params: ('%Bangalore%', 10)

-- Without location:
SELECT * FROM colleges
WHERE nirf_rank IS NOT NULL
ORDER BY nirf_rank ASC LIMIT ?
-- params: (10,)
```
**Key points**:
- `nirf_rank IS NOT NULL` — filters out colleges where rank wasn't extracted. Prevents NULL values appearing in the ranked list.
- `ORDER BY nirf_rank ASC` — rank 1 is best, so ascending = best first.
- **No course filter. No fee filter.** Returns top-N by NIRF rank only. Course/fee constraints are handled by the LLM reasoning over the results.

---

### `get_colleges_by_course(course_keyword, limit)` — `top_colleges_handler.py:18`
```sql
SELECT name, nirf_rank, rating, fee_range, courses_offered, location,
       established_year, college_type
FROM colleges
WHERE nirf_rank IS NOT NULL
ORDER BY nirf_rank ASC LIMIT ?
```
**Misleading name**: Despite being called `get_colleges_by_course`, there is **no course filter**. The `course_keyword` parameter is accepted but silently ignored. Returns top-N by NIRF rank regardless of course.

> **Interview angle**: *"This is a function naming bug — the name promises filtering by course but the implementation doesn't deliver it. In a code review I'd either rename it to `get_top_colleges_by_rank` or implement the course filter. The root cause is that `courses_offered` is a count, not names — you can't filter by course name in SQL without a separate courses table."*

---

## 5. Every Vector Query in the Codebase

**Concept**: A vector query works in three steps: (1) embed the query string into a 384-dim vector, (2) search the HNSW index for the nearest stored vectors, (3) return the raw text chunks those vectors came from. The `where` filter narrows the search to a subset of the index before the nearest-neighbor search runs — like telling the library "only search the exam section." Post-filtering in Python happens *after* retrieval — ChromaDB gives you 5 chunks, then Python throws away the ones that don't meet an extra condition. This two-stage pattern (coarse DB filter → fine Python filter) is the standard approach when the DB's filtering capability is limited.

> **Interview angle**: *"There are only 3 vector search functions. They all call one base function. The key design pattern is: use ChromaDB's `where` filter for coarse type-based filtering, then Python post-processing for fine-grained filtering that ChromaDB can't express."*

---

### `search_documents(query, n_results, doc_type, college_name)` — `vector_store.py:195`
The base function. All other search functions call this.
```python
collection.query(
    query_texts=[query],           # ChromaDB embeds this at query time
    n_results=n_results,
    where={"type": doc_type},      # None = no filter = search all 129,000 chunks
    include=["documents", "metadatas", "distances"]
)
```
**What ChromaDB does internally**:
1. Embeds `query` → 384-dim vector using `all-MiniLM-L6-v2`
2. Filters HNSW index to only nodes where `metadata.type == doc_type`
3. Finds `n_results` nearest vectors by cosine distance
4. Returns raw text chunks + metadata + distances

**Optional Python post-filter** by `college_name` (substring check on content + metadata). Used when you need chunks that specifically mention a college — ChromaDB's `where` can't do substring matching on metadata values.

> **Follow-up**: *"Why not use ChromaDB's `where` clause to filter by college name?"*
> **Answer**: ChromaDB `where` only supports exact equality (`{"college_names": "VIT Vellore"}`). The metadata stores names as `"VIT Vellore,SRM University"` — an exact match would fail. Python `in` operator handles partial names, abbreviations, and case differences.

---

### `search_by_type(query, doc_type, n_results)` — `vector_store.py:239`
Thin wrapper — one line:
```python
return search_documents(query, n_results=n_results, doc_type=doc_type)
```
Used everywhere in the codebase. The `doc_type` maps to the `type` metadata field:
- `'college'` → only 1,903 college pages (~25,000 chunks)
- `'comparison'` → only 12,559 comparison pages (~100,000 chunks)
- `'exam'` → only 141 exam pages (~1,500 chunks)
- `'blog'` → only 161 blog pages (~1,700 chunks)
- `None` → all 129,000 chunks (used by `handle_general`)

**Why filter by type?** Without filtering, a query about JEE might return comparison pages that happen to mention JEE in passing. Type filtering ensures you get the most relevant document category first.

---

### `search_comparisons(college1, college2, n_results)` — `vector_store.py:244`
```python
query = f"Compare {college1} and {college2}"
results = search_documents(query, n_results=n_results, doc_type='comparison')

# Post-filter: both colleges must appear in the chunk text
filtered = [r for r in results
            if college1.lower() in r['content'].lower()
            and college2.lower() in r['content'].lower()]

return filtered if filtered else results  # fallback to unfiltered if nothing passes
```

**The over-fetch-then-filter pattern**: ChromaDB's `where` can't express "college_names contains VIT AND college_names contains SRM". Python substring check on the actual content text is more reliable — handles abbreviations ("VIT" matches "VIT Vellore"), case differences, and partial names.

**The fallback**: `return filtered if filtered else results` — if no chunk mentions both colleges (e.g., the comparison page only mentions one by abbreviation), return the unfiltered results rather than returning nothing. Graceful degradation.

> **Follow-up**: *"What's the risk of the fallback?"*
> **Answer**: The fallback might return chunks about only one of the colleges. The LLM then has less context for the comparison and might produce a one-sided answer. A better fallback would be to fetch chunks for each college separately and merge them.

---

## 6. Handler-by-Handler Breakdown

**Concept**: A handler is a class that knows how to answer one *category* of question. The router classifies the user's query ("this is a COMPARISON question") and picks the right handler. The handler then knows exactly which SQL tables to query, which ChromaDB doc types to search, and how to format the results into a context string for the LLM. The LLM never touches the database directly — it only sees the formatted context string the handler built. This separation means you can change the database schema without touching the LLM prompt, and change the LLM without touching the database logic.

> **Interview angle**: *"Each handler is responsible for one query category. They all expose the same interface — `build_prompt_context(query, entities) -> (context_str, has_results, needs_web)` — so `rag_chain.py` can call any handler identically without knowing what SQL tables exist. Single Responsibility Principle."*

---

### CollegeHandler
**Triggered by**: `category == 'COLLEGE'`
**Example**: *"What is the fee at VIT Vellore?"*

```
SQLite:   query_college("VIT Vellore")
            → colleges table → {nirf_rank=11, fee_range="1,98,000-3,50,000", location, ...}
            → formatted as structured facts block

ChromaDB: search_by_type(query, 'college', n_results=5)
            → 5 college page chunks about VIT

ChromaDB: search_by_type(query, 'comparison', n_results=3)
            → 3 comparison page chunks mentioning VIT
```

**Why also search comparison docs for a college query?** 84.8% of the dataset is comparison pages. A college page for VIT might have 1–2 documents, but there are hundreds of "VIT vs X" pages — all containing rich VIT-specific data (fees, placements, campus). Pulling 3 comparison chunks gives the LLM much richer context about VIT.

**No-name fallback** (*"colleges in Bangalore"*): no college name extracted → skips SQL entirely → pure vector search. ChromaDB finds college chunks mentioning Bangalore semantically.

> **Follow-up**: *"What if `query_college` returns None?"*
> **Answer**: The handler checks `if sql_results` before formatting. If None, the SQL block is simply omitted from the context. The LLM still gets the vector chunks and can answer from those. Graceful degradation — never crashes.

---

### ComparisonHandler
**Triggered by**: `category == 'COMPARISON'`
**Example**: *"VIT vs SRM"*

```
SQLite L1: query_comparison("VIT", "SRM")
             → comparisons table → pre-built row with both colleges' stats
             → formatted as ASCII side-by-side table (LLM mirrors this as markdown table)

SQLite L2: query_college("VIT") + query_college("SRM")
             → colleges table × 2 → fills NULL gaps in the comparison row

ChromaDB:  search_comparisons("VIT", "SRM", n_results=3)
             → 3 chunks from comparison pages mentioning both colleges
             → narrative context: placements, campus life, faculty quality
```

**Why 3 SQL sources?** The comparison row might have NULL fields (regex extraction isn't perfect). The individual college rows fill those gaps. The vector chunks add narrative that no SQL column captures.

**Best-answered category in the system** — 3 SQL sources + vector all pointing at the same pair. This is why comparison queries produce the most accurate, structured responses.

> **Follow-up**: *"Why format the SQL comparison as an ASCII table?"*
> **Answer**: The LLM naturally mirrors the structure of its input. An ASCII table in the context → the LLM produces a markdown table in its response → renders beautifully in the React frontend's `react-markdown`. If you give the LLM a prose paragraph, it gives back prose.

---

### ExamHandler
**Triggered by**: `category == 'EXAM'`
**Example**: *"when JEE main application forms open"*

```
SQLite:   query_exam("JEE Main")
            → exams table → {
                exam_date="April 2024",
                conducting_body="NTA",
                exam_mode="Online",
                duration="3 hours",
                application_start=NULL,   ← always NULL
                application_end=NULL,     ← always NULL
                raw_content="[full page text 2000+ chars]"
              }
            → SQL contributes: exam_date, mode, duration
            → raw_content passed as fallback prose blob

ChromaDB: search_by_type(query, 'exam', n_results=5)
            → 5 exam page chunks (may contain application date prose)

ChromaDB: search_by_type(query, 'blog', n_results=2)
            → 2 blog chunks (e.g., "JEE 2024 application dates announced")
```

**Why include blog docs for exam queries?** Many of the 161 blog posts are *"JEE Main 2024 Important Dates"* or *"How to fill JEE application form"* — exam-relevant info that isn't in the structured exam table.

**Why `relevance: partial` for application date queries?** The vector chunks retrieved are about JEE generally (syllabus, pattern, eligibility). The specific application date text might be in `raw_content` but not in the top-5 vector chunks. Self-RAG sees "JEE-related content but not directly about application dates" → `partial`. Doesn't trigger web search (only `irrelevant` does).

---

### PredictorHandler
**Triggered by**: `category == 'PREDICTOR'`
**Example**: *"JEE rank 5000 which colleges"*

```
Regex:    parse_rank_score(query)
            r'\b(\d{1,6})\s*(?:rank|AIR)' → rank=5000
            nirf_threshold = max(10, 5000 // 100) = 50

SQLite:   get_colleges_by_nirf(threshold=50)
            SELECT * FROM colleges WHERE nirf_rank IS NOT NULL
            ORDER BY nirf_rank ASC LIMIT 10
            → top 10 by NIRF (note: threshold not actually applied in SQL)

ChromaDB: search_by_type(query, 'college', n_results=5)
          search_by_type(query, 'blog', n_results=2)
```

**The NIRF proxy heuristic**:
```
JEE rank 1,000   → nirf_threshold = max(10, 10)  = 10  → top 10 colleges
JEE rank 5,000   → nirf_threshold = max(10, 50)  = 50  → top 50 colleges
JEE rank 50,000  → nirf_threshold = max(10, 500) = 500 → top 500 colleges
```

> **Interview angle**: *"NIRF rank measures research output, placements, and faculty — not admission difficulty. Using it as a proxy for JEE cutoffs is a rough heuristic. I'm transparent about this: the system prompt explicitly tells the LLM to present results as 'colleges you might consider' and recommend checking JoSAA/official counselling portals for actual cutoffs. Honest about limitations."*

---

### TopCollegesHandler
**Triggered by**: `category == 'TOP_COLLEGES'`
**Example A**: *"Top 10 engineering colleges in India"*
**Example B**: *"MBA colleges under 1.5 lakh"* (the hard case)

```
-- Example A (works well):
SQLite:   query_top_colleges(limit=10)
            SELECT * FROM colleges WHERE nirf_rank IS NOT NULL
            ORDER BY nirf_rank ASC LIMIT 10
            → clean NIRF-ranked list, SQL does the work

-- Example B (SQL blind to constraints):
SQLite:   query_top_colleges(limit=10)
            → same query — NO MBA filter, NO fee filter
            → returns top 10 by NIRF regardless of course or fee

ChromaDB: search_by_type("MBA colleges under 1.5 lakh", 'college', n_results=5)
          search_by_type(..., 'blog', n_results=2)
          → finds chunks mentioning MBA fees semantically
```

**For Example B, the LLM does the filtering** — reads `fee_range` strings and vector chunks, reasons about which are under 1.5 lakh. Accuracy depends on how parseable the fee strings are. This is the weakest query type in the system.

**With location** (*"Top colleges in Bangalore"*): `WHERE location LIKE '%Bangalore%'` works correctly — location is a text field that SQL can filter.

> **Follow-up**: *"How would you make MBA/fee queries work properly?"*
> **Answer**: Two changes: (1) Add a `courses` table with `(college_id, course_name, fee)`. (2) Parse `fee_range` into `fee_min INTEGER, fee_max INTEGER`. Then: `SELECT c.name FROM colleges c JOIN courses co ON c.id = co.college_id WHERE co.course_name = 'MBA' AND co.fee < 150000 ORDER BY c.nirf_rank ASC`. Proper SQL, no LLM guessing.

---

### handle_general (no handler class)
**Triggered by**: `category == 'GENERAL'` (router couldn't classify)
**Example**: *"What is NAAC accreditation?"*, *"Explain college rankings"*

```
ChromaDB: search_by_type(query, doc_type=None, n_results=5)
            → searches ALL 129,000 chunks across all types
            → no SQL at all
```

Pure vector search across the entire collection. The `doc_type=None` means no metadata filter — the HNSW index searches everything.

> **Interview angle**: *"GENERAL is the catch-all fallback. If the router can't classify the query, it still gets a reasonable answer from semantic search. The system never returns 'I don't know' due to routing failure — it always tries something."*

---

## 7. Query Scenario Matrix

**Concept**: Not every query uses both databases equally. Some queries are dominated by SQL (comparison queries — there's a pre-built row for almost every college pair). Some are dominated by vector search (general questions — no SQL table for "what is NAAC?"). Some fall in between where SQL provides the skeleton (rank, fee) and vector provides the flesh (placements, campus life). Understanding *which database does the real work* for each query type is the key to understanding where the system is strong and where it's weak.

> **Interview angle**: *"I can tell you exactly which database answers any query. SQL handles named entities and ranked lists. ChromaDB handles everything conceptual. The LLM bridges the gap when SQL data is incomplete."*

| Query | Category | SQL Table(s) | SQL Useful? | ChromaDB | Who Really Answers |
|---|---|---|---|---|---|
| "Tell me about VIT Vellore" | COLLEGE | `colleges` | ✅ facts | ✅ college+comparison | Both — SQL gives numbers, vector gives narrative |
| "Colleges in Bangalore" | COLLEGE | — | ❌ no name extracted | ✅ college | Pure vector |
| "VIT vs SRM" | COMPARISON | `comparisons`+`colleges`×2 | ✅✅ dominant | ✅ comparison | SQL dominant — best-answered type |
| "When is JEE Main?" | EXAM | `exams` | ✅ exam_date | ✅ exam+blog | Both |
| "When do JEE forms open?" | EXAM | `exams` | ❌ NULL fields | ✅ exam+blog | Vector + raw_content prose |
| "JEE rank 5000 colleges" | PREDICTOR | `colleges` | ✅ NIRF list | ✅ college+blog | Both (heuristic — NIRF ≠ cutoff) |
| "Top 10 engineering colleges" | TOP_COLLEGES | `colleges` | ✅ NIRF list | ✅ college+blog | SQL dominant |
| "MBA colleges under 1.5 lakh" | TOP_COLLEGES | `colleges` | ⚠️ no course/fee filter | ✅ college+blog | LLM reasoning over raw strings |
| "Top colleges in Bangalore" | TOP_COLLEGES | `colleges` | ✅ location filter | ✅ college | Both |
| "Best colleges for CSE" | TOP_COLLEGES | `colleges` | ⚠️ no course filter | ✅ college | LLM reasoning |
| "What is NAAC accreditation?" | GENERAL | — | ❌ | ✅ all types | Pure vector |

**Pattern to memorize**:
- ✅ SQL dominant = query has a **named entity** (college name, exam name) or needs a **ranked list**
- ⚠️ LLM reasoning = query has **course/fee constraints** that SQL can't express
- ❌ SQL = query is **conceptual** (campus life, placements, culture) or **no entity extracted**

---

## 8. Known Gaps & How to Fix Them

**Concept**: A "gap" is where the system's actual behavior doesn't match what a user would reasonably expect. Gaps come from two sources: (1) *schema gaps* — a column exists but was never populated (exam dates), or a needed column was never created (course names as text). (2) *logic gaps* — a function accepts a parameter but ignores it (`course_keyword`), or a query clause can never match (`OR full_name LIKE ?`). Being able to name your gaps, explain why they exist, and describe the fix is a sign of engineering maturity. It shows you understand the system deeply enough to know where it breaks.

> **Interview angle**: *"I can identify 7 specific gaps in the current implementation. I know exactly why each exists, what impact it has, and how I'd fix it. Being able to critique your own work is more impressive than pretending it's perfect."*

---

### Gap 1: No course names in SQL
**What**: `courses_offered = 87` is a count. Cannot do `WHERE course = 'MBA'`.
**Impact**: Queries like "MBA colleges under 1.5 lakh" are answered by LLM guessing, not SQL filtering.
**Fix**:
```sql
CREATE TABLE courses (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    college_id  INTEGER REFERENCES colleges(id),
    course_name TEXT,    -- "MBA", "B.Tech CSE", "BCA"
    fee         INTEGER, -- 150000
    duration    TEXT     -- "2 years"
);
-- Then:
SELECT c.name FROM colleges c
JOIN courses co ON c.id = co.college_id
WHERE co.course_name = 'MBA' AND co.fee < 150000
ORDER BY c.nirf_rank ASC;
```
**Challenge**: Course names are buried in unstructured text. Need LLM-based extraction at ingestion time (regex isn't reliable enough for course names).

---

### Gap 2: `fee_range` is a string, not a number
**What**: `fee_range = "1,98,000 - 3,50,000"`. Cannot do `WHERE fee < 150000`.
**Impact**: Fee-based filtering is impossible in SQL. LLM must parse the string mentally.
**Fix**: At ingestion time in `data_extractor.py`:
```python
def parse_fee_to_int(fee_str: str) -> int:
    # "1,98,000" -> 198000
    cleaned = re.sub(r'[^\d]', '', fee_str.split('-')[0].split('to')[0])
    return int(cleaned) if cleaned else None
```
Then store `fee_min INTEGER, fee_max INTEGER` instead of `fee_range TEXT`.

---

### Gap 3: 4 exam columns always NULL
**What**: `full_name`, `application_start`, `application_end`, `result_date` — defined in schema, never inserted.
**Impact**: Application date queries answered from `raw_content` prose, not structured fields. Self-RAG returns `"partial"` for these queries.
**Fix**: Add to `data_extractor.py`:
```python
# Exam pages have consistent patterns:
m = re.search(r'Application\s+Start\s+Date[:\s]+([\w\s,]+\d{4})', content)
if m: application_start = m.group(1).strip()
```
Then update `insert_exams()` to insert these 4 fields.

---

### Gap 4: `blogs` table never queried at runtime
**What**: All blog retrieval goes through ChromaDB. The SQLite `blogs` table is populated but never read.
**Impact**: None currently — blogs work fine via vector search.
**When it matters**: If you want to add "Recent Articles" (filter by date), "Articles by Author", or "Blogs mentioning VIT" features — the SQL table is already there, just not wired up.
**Fix**: Add `query_blogs_by_college(college_name)` in `db_setup.py` and call it from `CollegeHandler`.

---

### Gap 5: `query_college` returns first fuzzy match (undefined order)
**What**: `WHERE name LIKE '%VIT%' LIMIT 1` — returns whichever row SQLite finds first.
**Impact**: Could return "VIT Chennai" when user meant "VIT Vellore". Depends on insertion order.
**Fix**:
```sql
-- Prefer exact match, fall back to fuzzy:
SELECT * FROM colleges
WHERE name = ?
UNION ALL
SELECT * FROM colleges
WHERE name LIKE ? AND name != ?
ORDER BY LENGTH(name) ASC
LIMIT 1
```
Or simply: `ORDER BY LENGTH(name) ASC` — shorter name = more exact match.

---

### Gap 6: `get_colleges_by_course` ignores its `course_keyword` parameter
**What**: Function accepts `course_keyword` but never uses it in SQL.
**Impact**: Function name is misleading. Returns top-N by NIRF regardless of course.
**Fix**: Either rename to `get_top_colleges_by_rank(limit)` (honest name), or implement the course filter once Gap 1 is fixed.

---

### Gap 7: `OR full_name LIKE ?` in `query_exam` is dead code
**What**: `full_name` is always NULL, so this `OR` clause never matches.
**Impact**: Wastes a parameter bind on every exam query. Minor performance issue.
**Fix**: Remove the clause: `SELECT * FROM exams WHERE name LIKE ? LIMIT 1`. Or populate `full_name` during ingestion so the clause actually works.

---

> **Interview closing line**: *"These 7 gaps represent the difference between a v1 prototype and a production system. I built v1 to prove the concept works. Each gap has a clear fix path — none requires a fundamental redesign."*
