import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

from fastapi import FastAPI, HTTPException
from fastapi.responses import StreamingResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Optional, List, Dict, Any
import json
import time
import logging
from collections import deque

from rag_chain import process_query, get_sample_questions, warmup
import rag_chain as _rag_chain_module
from contextlib import asynccontextmanager


# ── RAG Logger ────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [RAG] %(message)s",
    datefmt="%H:%M:%S"
)
_rag_logger = logging.getLogger("rag")

_RAG_LOG_MAX = 50
_rag_log: deque = deque(maxlen=_RAG_LOG_MAX)   # ring-buffer of recent traces


class _RAGLogEntry:
    """One complete RAG trace: query → raw_docs → context mapping."""
    __slots__ = (
        "ts", "query", "category", "attempt",
        "raw_docs", "doc_count", "doc_ids", "doc_sources",
        "context_snippet"
    )

    def __init__(self, ts, query, category, attempt, raw_docs):
        self.ts = ts
        self.query = query
        self.category = category
        self.attempt = attempt
        self.raw_docs = raw_docs
        self.doc_count = len(raw_docs)
        self.doc_ids = [
            d.get("id", d.get("metadata", {}).get("id", "?")) for d in raw_docs
        ]
        self.doc_sources = [
            d.get("metadata", {}).get("url",
                d.get("metadata", {}).get("source", "?"))
            for d in raw_docs
        ]
        self.context_snippet = " | ".join(
            d.get("content", "")[:80].replace("\n", " ") for d in raw_docs[:3]
        )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "ts": self.ts,
            "query": self.query,
            "category": self.category,
            "attempt": self.attempt,
            "doc_count": self.doc_count,
            "doc_ids": self.doc_ids,
            "doc_sources": self.doc_sources,
            "context_snippet": self.context_snippet,
        }


_original_get_raw_docs = _rag_chain_module._get_raw_docs


def _instrumented_get_raw_docs(
    query: str,
    category: str,
    college_names,
    exam_names,
    location,
    rank_score,
    _attempt: int = 1,
):
    """Wraps _get_raw_docs, logs every retrieval call into _rag_log."""
    docs = _original_get_raw_docs(
        query, category, college_names, exam_names, location, rank_score
    )
    entry = _RAGLogEntry(
        ts=time.strftime("%H:%M:%S"),
        query=query,
        category=category,
        attempt=_attempt,
        raw_docs=docs,
    )
    _rag_log.append(entry)
    _rag_logger.info(
        "get_raw_docs() | attempt=%d | category=%-12s | docs=%d | query=%s",
        _attempt, category, entry.doc_count, query[:70],
    )
    for i, d in enumerate(docs):
        src = entry.doc_sources[i]
        snippet = d.get("content", "")[:100].replace("\n", " ")
        _rag_logger.info("  doc[%d] src=%-50s  '%s'", i, src, snippet)
    return docs


_rag_chain_module._get_raw_docs = _instrumented_get_raw_docs


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Warm up connections on startup."""
    print("[API] Warming up ChromaDB + embedding model...")
    warmup()
    print("[API] Ready.")
    yield


app = FastAPI(
    title="DegreeFYD RAG API",
    description="Education chatbot API powered by Groq and ChromaDB",
    version="1.0.0",
    lifespan=lifespan
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class ChatRequest(BaseModel):
    query: str
    category: Optional[str] = None
    web_search_enabled: bool = False


class ChatResponse(BaseModel):
    answer: str
    category_detected: str
    web_search_used: bool
    has_local_results: bool
    entities: dict


@app.get("/")
def root():
    return {"message": "DegreeFYD RAG API is running", "docs": "/docs"}


@app.get("/health")
def health():
    from rag_chain import _query_cache
    return {"status": "ok", "cached_queries": len(_query_cache)}


@app.get("/rag-log")
def rag_log(limit: int = 20):
    """Return the last `limit` RAG retrieval traces (get_raw_docs calls)."""
    entries = list(_rag_log)[-limit:]
    return {
        "total_logged": len(_rag_log),
        "returned": len(entries),
        "traces": [e.to_dict() for e in reversed(entries)],
    }


@app.get("/categories")
def get_categories():
    """Return all categories with sample questions."""
    categories = ["COLLEGE", "EXAM", "COMPARISON", "PREDICTOR", "TOP_COLLEGES"]
    return {
        cat: {
            "label": cat.replace("_", " ").title(),
            "sample_questions": get_sample_questions(cat)
        }
        for cat in categories
    }


@app.post("/chat", response_model=ChatResponse)
def chat(request: ChatRequest):
    """Non-streaming chat endpoint."""
    try:
        result = process_query(
            query=request.query,
            web_search_enabled=request.web_search_enabled,
            stream=False
        )

        return ChatResponse(
            answer=result['response'],
            category_detected=result['category'],
            web_search_used=result['web_search_used'],
            has_local_results=result['has_local_results'],
            entities=result['entities']
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/chat/stream")
def chat_stream(request: ChatRequest):
    """Streaming chat endpoint - returns Server-Sent Events."""
    def generate():
        try:
            result = process_query(
                query=request.query,
                web_search_enabled=request.web_search_enabled,
                stream=True
            )

            # Send metadata first
            meta = {
                "type": "meta",
                "category": result['category'],
                "web_search_used": result['web_search_used'],
                "has_local_results": result['has_local_results'],
                "auto_web_triggered": result.get('auto_web_triggered', False)
            }
            yield f"data: {json.dumps(meta)}\n\n"

            # Stream response chunks
            for chunk in result['response']:
                payload = {"type": "chunk", "content": chunk}
                yield f"data: {json.dumps(payload)}\n\n"

            # Send done signal
            yield f"data: {json.dumps({'type': 'done'})}\n\n"

        except Exception as e:
            yield f"data: {json.dumps({'type': 'error', 'message': str(e)})}\n\n"

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no"
        }
    )


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
