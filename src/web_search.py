from groq import Groq
from typing import Optional, Generator
from config import GROQ_API_KEY


client = Groq(api_key=GROQ_API_KEY)


def query_with_web_search(
    query: str,
    context: str = "",
    web_search_enabled: bool = False,
    stream: bool = True
):
    """
    Query Groq compound model with optional web search.

    Args:
        query: User's question
        context: Retrieved context from local DB/vector store
        web_search_enabled: Whether to enable web search fallback
        stream: Whether to stream the response

    Returns:
        Generator yielding response chunks if stream=True, else full response string
    """
    if context:
        system_prompt = (
            "You are DegreeFYD Assistant, an expert on Indian colleges, universities, and entrance exams.\n"
            "Answer based on the provided context. If the context doesn't contain enough information and "
            "web search is available, you may use it to supplement your answer. Always be helpful and accurate.\n\n"
            "Context from DegreeFYD database:\n{context}"
        ).format(context=context)
    else:
        system_prompt = (
            "You are DegreeFYD Assistant, an expert on Indian colleges, universities, and entrance exams.\n"
            "If you don't have information in your knowledge and web search is enabled, use it to find accurate information.\n"
            "Always be helpful and provide accurate information about Indian education."
        )

    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": query}
    ]

    compound_config = None
    if web_search_enabled:
        compound_config = {
            "tools": {
                "enabled_tools": ["web_search"]
            }
        }

    try:
        completion = client.chat.completions.create(
            model="compound-beta",
            messages=messages,
            temperature=0.7,
            max_completion_tokens=1024,
            top_p=1,
            stream=stream,
            compound_custom=compound_config
        )

        if stream:
            def response_generator():
                for chunk in completion:
                    content = chunk.choices[0].delta.content
                    if content:
                        yield content
            return response_generator()
        else:
            return completion.choices[0].message.content

    except Exception as e:
        error_msg = f"Error querying Groq: {str(e)}"
        if stream:
            def error_generator():
                yield error_msg
            return error_generator()
        return error_msg


def format_context_for_llm(results: list) -> str:
    """Format search results into context string for LLM."""
    if not results:
        return ""

    context_parts = []
    for i, result in enumerate(results, 1):
        content = result.get('content', '')
        metadata = result.get('metadata', {})
        url = metadata.get('url', '')
        doc_type = metadata.get('type', '')
        context_parts.append(f"[Source {i}] ({doc_type})\n{content}\nURL: {url}")

    return "\n---\n".join(context_parts)


def should_use_web_search(results: list, confidence_threshold: float = 0.5) -> bool:
    """
    Determine if web search should be used based on local search results quality.

    Args:
        results: Search results from local DB/vector store
        confidence_threshold: Distance threshold (lower = more confident in cosine space)

    Returns:
        True if web search should be triggered
    """
    if not results:
        return True

    for result in results:
        distance = result.get('distance', 1.0)
        if distance is not None and distance < confidence_threshold:
            return False

    return True
