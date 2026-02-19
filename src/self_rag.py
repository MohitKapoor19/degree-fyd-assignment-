"""
Self-RAG: Retrieval-Augmented Generation with self-reflection.

Adds an ISREL (relevance check) step before generation:
  1. Retrieve docs from vector store
  2. Ask LLM: are these docs relevant to the query? (fast, non-streaming)
  3. If irrelevant → rephrase query and retry once
  4. If still irrelevant → auto-enable web search fallback

Uses llama-3.1-8b-instant for all reflection calls (fast + cheap).
"""

from groq import Groq
from typing import List, Dict, Tuple
from config import GROQ_API_KEY, GROQ_ROUTER_MODEL

_client = None


def _get_client() -> Groq:
    global _client
    if _client is None:
        _client = Groq(api_key=GROQ_API_KEY)
    return _client


def check_relevance(query: str, docs: List[Dict]) -> str:
    """
    ISREL: Check if retrieved documents are relevant to the query.

    Returns:
        "relevant"   — docs clearly answer the query
        "partial"    — docs have some useful info but incomplete
        "irrelevant" — docs are off-topic or empty
    """
    if not docs:
        return "irrelevant"

    # Use top-3 docs for the check (enough signal, saves tokens)
    context_snippet = "\n---\n".join(
        d.get("content", "")[:400] for d in docs[:3]
    )

    prompt = (
        "You are a relevance judge. Given a user query and retrieved document snippets, "
        "decide if the documents are useful for answering the query.\n\n"
        f"Query: {query}\n\n"
        f"Retrieved snippets:\n{context_snippet}\n\n"
        "Reply with EXACTLY one word: relevant, partial, or irrelevant.\n"
        "- relevant: documents directly answer the query\n"
        "- partial: documents have some related info but are incomplete\n"
        "- irrelevant: documents are off-topic or contain no useful information"
    )

    try:
        client = _get_client()
        resp = client.chat.completions.create(
            model=GROQ_ROUTER_MODEL,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.0,
            max_completion_tokens=5,
            stream=False,
        )
        verdict = resp.choices[0].message.content.strip().lower()
        if verdict in ("relevant", "partial", "irrelevant"):
            return verdict
        return "partial"
    except Exception as e:
        print(f"[Self-RAG] check_relevance error: {e}")
        return "partial"


def rephrase_query(query: str, category: str) -> str:
    """
    Rephrase the query to improve retrieval when first attempt was irrelevant.
    Expands abbreviations, adds domain context, removes noise.
    """
    prompt = (
        f"Rephrase the following search query to improve document retrieval for the '{category}' category "
        f"in an Indian college/education context. "
        f"Expand abbreviations, add relevant keywords, keep it concise (max 20 words).\n\n"
        f"Original query: {query}\n\n"
        f"Rephrased query (return ONLY the rephrased query, nothing else):"
    )

    try:
        client = _get_client()
        resp = client.chat.completions.create(
            model=GROQ_ROUTER_MODEL,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.3,
            max_completion_tokens=40,
            stream=False,
        )
        rephrased = resp.choices[0].message.content.strip().strip('"').strip("'")
        print(f"[Self-RAG] Rephrased: '{query}' → '{rephrased}'")
        return rephrased if rephrased else query
    except Exception as e:
        print(f"[Self-RAG] rephrase_query error: {e}")
        return query


def self_rag_retrieve(
    query: str,
    category: str,
    retrieve_fn,
    retrieve_kwargs: dict,
) -> Tuple[str, List[Dict], bool, bool]:
    """
    Full Self-RAG retrieval pipeline.

    Args:
        query:           Original user query
        category:        Detected category (COLLEGE, EXAM, etc.)
        retrieve_fn:     Callable — handler.build_prompt_context or similar
        retrieve_kwargs: kwargs to pass to retrieve_fn

    Returns:
        (context_str, docs, has_local_results, auto_web_triggered)
    """
    # ── Attempt 1: retrieve with original query ──────────────────────────────
    context, has_results, needs_web = retrieve_fn(query, **retrieve_kwargs)

    # Extract raw docs for relevance check (passed via retrieve_kwargs side-channel)
    raw_docs = retrieve_kwargs.get("_raw_docs", [])

    relevance = check_relevance(query, raw_docs) if raw_docs else (
        "relevant" if has_results else "irrelevant"
    )
    print(f"[Self-RAG] Attempt 1 relevance: {relevance}")

    if relevance == "relevant":
        return context, raw_docs, has_results, False

    # ── Attempt 2: rephrase + re-retrieve ────────────────────────────────────
    rephrased = rephrase_query(query, category)
    if rephrased != query:
        context2, has_results2, needs_web2 = retrieve_fn(rephrased, **retrieve_kwargs)
        raw_docs2 = retrieve_kwargs.get("_raw_docs", [])
        relevance2 = check_relevance(rephrased, raw_docs2) if raw_docs2 else (
            "relevant" if has_results2 else "irrelevant"
        )
        print(f"[Self-RAG] Attempt 2 relevance: {relevance2}")

        if relevance2 in ("relevant", "partial"):
            return context2, raw_docs2, has_results2, False

    # ── Both attempts failed → auto web search ───────────────────────────────
    print(f"[Self-RAG] Both retrieval attempts failed → auto web search ON")
    return context, raw_docs, has_results, True
