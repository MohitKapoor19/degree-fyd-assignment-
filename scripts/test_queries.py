import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

from rag_chain import process_query

TEST_QUERIES = [
    ("How can I get admission to VIT Vellore?", "COLLEGE"),
    ("Compare IIM Indore vs IIM Kozhikode", "COMPARISON"),
    ("What is the exam pattern for JEE Main?", "EXAM"),
    ("Which colleges accept 70 rank in JEE Main?", "PREDICTOR"),
    ("Top B.Tech colleges in Mumbai", "TOP_COLLEGES"),
]


def run_tests(web_search: bool = False):
    print("=" * 60)
    print(f"Running test queries (web_search={web_search})")
    print("=" * 60)

    for query, expected_cat in TEST_QUERIES:
        print(f"\nQuery: {query}")
        print(f"Expected category: {expected_cat}")

        result = process_query(query, web_search_enabled=web_search, stream=False)

        print(f"Detected category: {result['category']}")
        print(f"Web search used: {result['web_search_used']}")
        print(f"Has local results: {result['has_local_results']}")
        print(f"Answer (first 200 chars): {str(result['response'])[:200]}...")
        print("-" * 40)


if __name__ == "__main__":
    run_tests(web_search=False)
