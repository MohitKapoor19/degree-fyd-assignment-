# DegreeFYD RAG Chatbot

A ShikshaGPT-style education chatbot built with **Groq + ChromaDB + SQLite + LangChain**.

---

## Features

- **5 Category Tabs**: Colleges, Exams, Comparisons, Predictors, Top Colleges
- **Hybrid Retrieval**: SQLite for structured data + ChromaDB for semantic search
- **Web Search Toggle**: Groq `compound-beta` web search — only triggers when local data is insufficient AND toggle is ON
- **Two UIs**: Streamlit (quick) and Vite + React (production)
- **Streaming responses** via FastAPI SSE

---

## Project Structure

```
DegreeFYD Assignment/
├── degreefyd_data.jsonl        # Source data (~14,800 records)
├── requirements.txt            # Python dependencies
├── .env                        # Your API keys (create from .env.example)
├── PLAN.md                     # Full architecture documentation
│
├── src/
│   ├── config.py               # Paths, model names, settings
│   ├── data_extractor.py       # Parse JSONL → structured fields
│   ├── db_setup.py             # SQLite schema + ingestion
│   ├── vector_store.py         # ChromaDB setup + ingestion
│   ├── query_router.py         # Category classifier (Groq LLM)
│   ├── web_search.py           # Groq compound-beta web search
│   ├── rag_chain.py            # Main RAG pipeline
│   └── handlers/
│       ├── college_handler.py
│       ├── exam_handler.py
│       ├── comparison_handler.py
│       ├── predictor_handler.py
│       └── top_colleges_handler.py
│
├── api/
│   └── main.py                 # FastAPI backend (port 8000)
│
├── ui/
│   └── app.py                  # Streamlit UI (port 8501)
│
├── frontend/                   # Vite + React UI (port 5173)
│   ├── src/
│   │   ├── App.tsx
│   │   ├── api.ts
│   │   ├── constants.ts
│   │   └── types.ts
│   └── package.json
│
├── scripts/
│   ├── ingest_data.py          # One-time data ingestion
│   └── test_queries.py         # Test the RAG pipeline
│
└── data/                       # Auto-created on ingestion
    ├── degreefyd.db            # SQLite database
    └── chroma_db/              # ChromaDB vector store
```

---

## Setup

### 1. Create `.env` file

```bash
copy .env.example .env
```

Edit `.env` and add your Groq API key:
```
GROQ_API_KEY=your_groq_api_key_here
```

Get a free key at: https://console.groq.com

---

### 2. Install Python dependencies

```bash
pip install -r requirements.txt
```

> **Note**: `sentence-transformers` will download the embedding model (~90MB) on first run.

---

### 3. Run Data Ingestion (One-time)

```bash
python scripts/ingest_data.py
```

This will:
- Parse all 14,800 JSONL records
- Create SQLite database with structured tables
- Generate embeddings and store in ChromaDB

> Takes ~10-20 minutes depending on your machine (embedding generation).

---

### 4. Start the API Server

```bash
python api/main.py
```

API runs at: http://localhost:8000  
Docs at: http://localhost:8000/docs

---

### 5. Choose Your UI

#### Option A: Streamlit (Quick)
```bash
streamlit run ui/app.py
```
Opens at: http://localhost:8501

#### Option B: Vite + React (Production)

Install Node dependencies (first time only):
```bash
cd frontend
npm install
```

Start dev server:
```bash
npm run dev
```
Opens at: http://localhost:5173

---

## Usage

### Web Search Toggle

| State | Behavior |
|-------|----------|
| **OFF** (default) | Only uses local DegreeFYD data (SQLite + ChromaDB) |
| **ON** | If local data is insufficient, Groq `compound-beta` searches the web |

> Web search uses Groq API credits. Keep it OFF for most queries.

---

## API Endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/` | Health check |
| `GET` | `/categories` | All categories + sample questions |
| `POST` | `/chat` | Non-streaming chat |
| `POST` | `/chat/stream` | Streaming chat (SSE) |

### Example Request

```bash
curl -X POST http://localhost:8000/chat \
  -H "Content-Type: application/json" \
  -d '{"query": "Compare IIM Indore vs IIM Kozhikode", "web_search_enabled": false}'
```

---

## Models Used

| Component | Model |
|-----------|-------|
| **LLM + Web Search** | `compound-beta` (Groq) |
| **Query Router** | `llama-3.1-8b-instant` (Groq) |
| **Embeddings** | `all-MiniLM-L6-v2` (local, free) |

---

## Troubleshooting

**`GROQ_API_KEY not found`** → Make sure `.env` file exists with your key.

**`Cannot connect to API server`** → Start `python api/main.py` first before running the UI.

**`ChromaDB collection empty`** → Run `python scripts/ingest_data.py` first.

**Slow first response** → Embedding model loads on first query. Subsequent queries are faster.
