from typing import Dict, Generator, Optional, List
from functools import lru_cache
import hashlib
from query_router import route_query
from web_search import query_with_web_search, should_use_web_search
from vector_store import search_by_type, get_or_create_collection, search_documents
from self_rag import check_relevance, rephrase_query
from handlers.college_handler import CollegeHandler
from handlers.exam_handler import ExamHandler
from handlers.comparison_handler import ComparisonHandler
from handlers.predictor_handler import PredictorHandler
from handlers.top_colleges_handler import TopCollegesHandler


college_handler = CollegeHandler()
exam_handler = ExamHandler()
comparison_handler = ComparisonHandler()
predictor_handler = PredictorHandler()
top_colleges_handler = TopCollegesHandler()

# ── In-memory LRU cache for repeated queries (max 128 entries) ────────────────
_query_cache: Dict[str, Dict] = {}
_CACHE_MAX = 128
_cache_keys: list = []

# ── Out-of-scope redirect response ────────────────────────────────────────────
_OUT_OF_SCOPE_RESPONSE = (
    "I'm DegreeFYD Assistant, specialised in Indian colleges, universities, and entrance exams. "
    "I can't help with that topic, but I'd be happy to answer questions like:\n\n"
    "- Fees, admissions, placements, or facilities at a specific college\n"
    "- Entrance exam dates, patterns, or syllabus (JEE, NEET, GATE, CAT, etc.)\n"
    "- Comparing two colleges\n"
    "- Finding top colleges by location or course\n"
    "- College predictions based on your rank/percentile\n\n"
    "What would you like to know?"
)


def _cache_key(query: str, web_search_enabled: bool) -> str:
    raw = f"{query.strip().lower()}|{web_search_enabled}"
    return hashlib.md5(raw.encode()).hexdigest()


def _get_cached(key: str) -> Optional[Dict]:
    return _query_cache.get(key)


def _set_cached(key: str, value: Dict):
    global _cache_keys
    if len(_cache_keys) >= _CACHE_MAX:
        oldest = _cache_keys.pop(0)
        _query_cache.pop(oldest, None)
    _query_cache[key] = value
    _cache_keys.append(key)


def warmup():
    """Pre-load ChromaDB collection and embedding model at startup."""
    try:
        get_or_create_collection()
        print("[STARTUP] ChromaDB collection loaded and ready.")
    except Exception as e:
        print(f"[STARTUP] WARNING — ChromaDB warmup failed: {e}")


def _get_raw_docs(query: str, category: str,
                  college_names: List[str], exam_names: List[str],
                  location: Optional[str], rank_score: Optional[str]) -> List[Dict]:
    """
    Fetch raw vector docs for a query without building the full prompt context.
    Used by Self-RAG for the ISREL relevance check.
    Enriches the query with extracted entities for better retrieval specificity,
    then post-filters results to keep only docs mentioning the requested college(s).
    """
    # Enrich query with extracted entities for better retrieval specificity
    enriched_query = query
    if college_names:
        enriched_query = f"{' '.join(college_names)} {query}"
    elif exam_names:
        enriched_query = f"{' '.join(exam_names)} {query}"

    if category == 'COLLEGE':
        docs = search_by_type(enriched_query, doc_type='college', n_results=5)
        # Post-filter: keep only docs that mention the requested college(s)
        if college_names:
            college_names_lower = [n.lower() for n in college_names]
            filtered = [
                d for d in docs
                if any(cn in d.get('content', '').lower() or
                       cn in d.get('metadata', {}).get('url', '').lower()
                       for cn in college_names_lower)
            ]
            docs = filtered if filtered else docs
    elif category == 'EXAM':
        docs = search_by_type(enriched_query, doc_type='exam', n_results=5)
    elif category == 'COMPARISON':
        docs = search_by_type(enriched_query, doc_type='comparison', n_results=5)
    elif category in ('PREDICTOR', 'TOP_COLLEGES'):
        docs = search_by_type(enriched_query, doc_type='college', n_results=5)
    else:
        docs = search_documents(enriched_query, n_results=5)

    # Log retrieved sources
    print(f"[RETRIEVAL] {len(docs)} doc(s) fetched | category={category} | enriched_query='{enriched_query[:60]}'")
    if docs:
        for i, d in enumerate(docs):
            url = d.get('metadata', {}).get('url', 'N/A')
            snippet = d.get('content', '')[:100].replace('\n', ' ')
            dist = d.get('distance')
            dist_str = f" | dist={dist:.3f}" if dist is not None else ""
            print(f"[RETRIEVAL]   [{i}] {url}{dist_str}")
            print(f"[RETRIEVAL]       snippet: '{snippet}'")
    else:
        print(f"[RETRIEVAL]   (no docs matched — will trigger web search fallback)")

    return docs


def _out_of_scope_generator(stream: bool):
    """Return the out-of-scope redirect as a generator or string."""
    if stream:
        def _gen():
            yield _OUT_OF_SCOPE_RESPONSE
        return _gen()
    return _OUT_OF_SCOPE_RESPONSE


def handle_general(query: str, raw_docs: List[Dict] = None) -> tuple:
    """
    Handle GENERAL category queries using the already-fetched raw docs.
    Accepts pre-fetched docs to avoid a duplicate vector search.
    """
    results = raw_docs if raw_docs is not None else search_documents(query, n_results=5)

    context_parts = []
    for r in results[:5]:
        content = r.get('content', '')
        url = r.get('metadata', {}).get('url', '')
        context_parts.append(f"{content}\nSource: {url}")

    context = "\n---\n".join(context_parts)
    has_results = bool(results)
    needs_web = should_use_web_search(results)

    return context, has_results, needs_web


def _build_context(query: str, category: str,
                   college_names: List[str], exam_names: List[str],
                   location: Optional[str], rank_score: Optional[str],
                   raw_docs: List[Dict] = None) -> tuple:
    """Call the appropriate handler and return (context, has_results, needs_web)."""
    if category == 'COLLEGE':
        return college_handler.build_prompt_context(query, college_names, location)
    elif category == 'EXAM':
        return exam_handler.build_prompt_context(query, exam_names)
    elif category == 'COMPARISON':
        return comparison_handler.build_prompt_context(query, college_names)
    elif category == 'PREDICTOR':
        return predictor_handler.build_prompt_context(query, exam_names, rank_score)
    elif category == 'TOP_COLLEGES':
        return top_colleges_handler.build_prompt_context(query, location)
    else:
        # Pass already-fetched docs to avoid a second vector search
        return handle_general(query, raw_docs=raw_docs)


def process_query(
    query: str,
    web_search_enabled: bool = False,
    stream: bool = True
) -> Dict:
    """
    Main RAG pipeline with Self-RAG relevance checking.

    Pipeline:
      1. Route query → category + entities
      2. Fetch raw docs → ISREL check (Self-RAG)
      3a. relevant/partial → build context + generate
      3b. GENERAL + irrelevant after both attempts → out-of-scope redirect (no web search)
      3c. non-GENERAL irrelevant → rephrase → retry → auto web search
      4. Generate response via Groq (streaming or not)
    """
    # ── Cache check ───────────────────────────────────────────────────────────
    if not stream:
        key = _cache_key(query, web_search_enabled)
        cached = _get_cached(key)
        if cached:
            print(f"[CACHE] HIT — returning cached result for: '{query[:60]}'")
            return cached

    # ── Step 1: Route ────────────────────────────────────────────────────────
    route_result = route_query(query)
    category = route_result.get('category', 'GENERAL')
    college_names = route_result.get('college_names', [])
    exam_names = route_result.get('exam_names', [])
    location = route_result.get('location')
    rank_score = route_result.get('rank_score')

    print(f"")
    print(f"{'='*70}")
    print(f"[PIPELINE] START  query='{query[:80]}'")
    print(f"[PIPELINE] STEP 1 — Router → category={category} | colleges={college_names} | exams={exam_names} | location={location} | rank={rank_score}")

    # ── Step 2: Self-RAG — ISREL check ───────────────────────────────────────
    auto_web_triggered = False
    out_of_scope = False
    active_query = query
    entities = (college_names or []) + (exam_names or [])

    print(f"[PIPELINE] STEP 2 — Self-RAG retrieval (attempt 1)")
    raw_docs = _get_raw_docs(query, category, college_names, exam_names, location, rank_score)
    relevance = check_relevance(query, raw_docs, entities=entities or None)
    print(f"[SELF-RAG] Attempt 1 verdict: {relevance.upper()} | docs_checked={len(raw_docs)} | entities={entities}")

    if relevance == "irrelevant":
        rephrased = rephrase_query(query, category)
        if rephrased != query:
            print(f"[PIPELINE] STEP 2 — Self-RAG retrieval (attempt 2 with rephrased query)")
            raw_docs2 = _get_raw_docs(rephrased, category, college_names, exam_names, location, rank_score)
            relevance2 = check_relevance(rephrased, raw_docs2, entities=entities or None)
            print(f"[SELF-RAG] Attempt 2 verdict: {relevance2.upper()} | docs_checked={len(raw_docs2)}")

            if relevance2 in ("relevant", "partial"):
                active_query = rephrased
                raw_docs = raw_docs2
                print(f"[SELF-RAG] Using rephrased query for generation.")
            else:
                # Both attempts irrelevant
                if category == 'GENERAL':
                    # Out-of-scope query — redirect instead of web search
                    out_of_scope = True
                    print(f"[SELF-RAG] GENERAL + both attempts IRRELEVANT — query is out of scope. Redirecting.")
                else:
                    auto_web_triggered = True
                    print(f"[SELF-RAG] Both attempts IRRELEVANT — auto web search will be triggered.")
        else:
            print(f"[SELF-RAG] Rephrase returned same query.")
            if category == 'GENERAL':
                out_of_scope = True
                print(f"[SELF-RAG] GENERAL + no rephrase change — query is out of scope. Redirecting.")
            else:
                auto_web_triggered = True
                print(f"[SELF-RAG] Auto web search will be triggered.")

    # ── Step 3: Out-of-scope early return ────────────────────────────────────
    if out_of_scope:
        print(f"[PIPELINE] STEP 3 — OUT OF SCOPE: returning redirect response (no web search, no LLM call)")
        print(f"[PIPELINE] DONE   web_search_used=False | out_of_scope=True")
        print(f"{'='*70}")
        result = {
            'response': _out_of_scope_generator(stream),
            'category': category,
            'web_search_used': False,
            'has_local_results': False,
            'auto_web_triggered': False,
            'out_of_scope': True,
            'entities': {
                'college_names': college_names,
                'exam_names': exam_names,
                'location': location,
                'rank_score': rank_score
            }
        }
        return result

    # ── Step 3: Build full context ───────────────────────────────────────────
    print(f"[PIPELINE] STEP 3 — Building context via {category} handler")
    context, has_results, needs_web = _build_context(
        active_query, category, college_names, exam_names, location, rank_score,
        raw_docs=raw_docs
    )
    print(f"[CONTEXT]  has_local_results={has_results} | context_chars={len(context)}")

    # ── Step 4: Decide web search ────────────────────────────────────────────
    use_web = web_search_enabled or auto_web_triggered
    web_reason = []
    if web_search_enabled:
        web_reason.append("user_toggled=ON")
    if auto_web_triggered:
        web_reason.append("self_rag=irrelevant")
    if not web_reason:
        web_reason.append("not_needed")
    print(f"[PIPELINE] STEP 4 — Web search: {'ENABLED' if use_web else 'DISABLED'} | reason={', '.join(web_reason)}")

    # ── Step 5: Generate ─────────────────────────────────────────────────────
    print(f"[PIPELINE] STEP 5 — Generating response (stream={stream})")
    response = query_with_web_search(
        query=active_query,
        context=context,
        web_search_enabled=use_web,
        stream=stream
    )

    result = {
        'response': response,
        'category': category,
        'web_search_used': use_web,
        'has_local_results': has_results,
        'auto_web_triggered': auto_web_triggered,
        'out_of_scope': False,
        'entities': {
            'college_names': college_names,
            'exam_names': exam_names,
            'location': location,
            'rank_score': rank_score
        }
    }

    if not stream:
        _set_cached(_cache_key(query, web_search_enabled), result)

    print(f"[PIPELINE] DONE   web_search_used={use_web} | auto_triggered={auto_web_triggered}")
    print(f"{'='*70}")
    return result


def get_sample_questions(category: str) -> list:
    """Return sample questions for each category tab."""
    samples = {
        'COLLEGE': [
            "How can I get admission to VIT Vellore?",
            "How much is the fee at DTU?",
            "What are the hostel facilities like at IIT Bombay?",
            "Which companies visited LPU for placements this year?",
            "What need-based scholarships are available at Amity University?"
        ],
        'EXAM': [
            "What is the exam pattern for JEE Main?",
            "Where can I download MHT CET admit card?",
            "When will the application for JEE Advanced begin?",
            "What is the CLAT 2026 exam date?",
            "What is the syllabus for GATE 2026?"
        ],
        'COMPARISON': [
            "Which has better placements, VIT Vellore or Amrita?",
            "Compare IIM Indore vs IIM Kozhikode",
            "Which college has a better NIRF ranking, LPU or Chandigarh University?",
            "What is the fee difference between Amity Gurugram and Amity Lucknow?",
            "How do campus facilities compare between IIT Bombay and IIT Delhi?"
        ],
        'PREDICTOR': [
            "Which colleges accept 70 rank in JEE Main?",
            "What are the best colleges for 70 percentile in MHT CET?",
            "Can I get into top colleges with 70 rank in TS EAMCET?",
            "Cutoffs for all branches at DTU?",
            "What is the entrance exam cutoff for VIT Vellore this year?"
        ],
        'TOP_COLLEGES': [
            "B.E. / B.Tech colleges in India",
            "Top Ranked B.E. / B.Tech colleges in Mumbai",
            "Private B.E. / B.Tech colleges in Bangalore",
            "Which are the Top Ranked colleges in Jaipur?",
            "Popular colleges in Kolkata"
        ]
    }
    return samples.get(category, [])
