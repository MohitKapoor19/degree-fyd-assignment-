from typing import Dict, List, Optional
from db_setup import query_comparison, query_college
from vector_store import search_comparisons, search_by_type


class ComparisonHandler:
    """Handles college comparison queries."""

    def get_context(self, query: str, college_names: List[str]) -> Dict:
        """Retrieve comparison context for two colleges."""
        sql_result = None
        vector_results = []

        # Need at least 2 colleges to compare
        if len(college_names) >= 2:
            sql_result = query_comparison(college_names[0], college_names[1])

            # Also get individual college data for richer comparison
            college1_data = query_college(college_names[0])
            college2_data = query_college(college_names[1])

            # Semantic search for comparison docs
            vector_results = search_comparisons(college_names[0], college_names[1], n_results=3)

        elif len(college_names) == 1:
            # Single college mentioned - search for comparisons involving it
            vector_results = search_by_type(
                f"{college_names[0]} comparison",
                doc_type='comparison',
                n_results=5
            )

        else:
            # No college names extracted - general comparison search
            vector_results = search_by_type(query, doc_type='comparison', n_results=5)

        has_results = bool(sql_result or vector_results)

        return {
            'sql_data': sql_result,
            'college1_data': query_college(college_names[0]) if len(college_names) >= 1 else None,
            'college2_data': query_college(college_names[1]) if len(college_names) >= 2 else None,
            'vector_data': vector_results,
            'has_results': has_results,
        }

    def format_comparison_table(self, sql_result: Dict) -> str:
        """Format comparison data as a structured table."""
        if not sql_result:
            return ""

        c1 = sql_result.get('college_1', 'College 1')
        c2 = sql_result.get('college_2', 'College 2')

        rows = [
            f"{'Parameter':<25} {'':>2} {c1:<35} {c2:<35}",
            "-" * 100
        ]

        def add_row(label, val1, val2):
            v1 = str(val1) if val1 else "N/A"
            v2 = str(val2) if val2 else "N/A"
            rows.append(f"{label:<25} {'':>2} {v1:<35} {v2:<35}")

        add_row("Fees (Starting)", sql_result.get('college_1_fees'), sql_result.get('college_2_fees'))
        add_row("NIRF Rank", sql_result.get('college_1_nirf'), sql_result.get('college_2_nirf'))
        add_row("Rating", sql_result.get('college_1_rating'), sql_result.get('college_2_rating'))
        add_row("College Type", sql_result.get('college_1_type'), sql_result.get('college_2_type'))
        add_row("Location", sql_result.get('college_1_location'), sql_result.get('college_2_location'))
        add_row("Courses Offered", sql_result.get('college_1_courses'), sql_result.get('college_2_courses'))
        add_row("Established Year", sql_result.get('college_1_year'), sql_result.get('college_2_year'))
        add_row("Total Students", sql_result.get('college_1_students'), sql_result.get('college_2_students'))

        return "\n".join(rows)

    def build_prompt_context(self, query: str, college_names: List[str]) -> tuple:
        """
        Build full context for LLM prompt.

        Returns:
            (context_str, has_results, needs_web_search)
        """
        data = self.get_context(query, college_names)

        context_parts = []

        # Structured comparison table
        if data['sql_data']:
            table = self.format_comparison_table(data['sql_data'])
            context_parts.append("=== Structured Comparison Data ===\n" + table)

        # Individual college data
        for key in ['college1_data', 'college2_data']:
            college = data.get(key)
            if college:
                name = college.get('name', '')
                nirf = college.get('nirf_rank', 'N/A')
                fee = college.get('fee_range', 'N/A')
                courses = college.get('courses_offered', 'N/A')
                context_parts.append(
                    f"=== {name} ===\n"
                    f"  NIRF Rank: #{nirf}\n"
                    f"  Fee Range: INR {fee}\n"
                    f"  Courses: {courses}"
                )

        # Vector search results
        if data['vector_data']:
            vector_texts = []
            for r in data['vector_data'][:3]:
                content = r.get('content', '')
                url = r.get('metadata', {}).get('url', '')
                vector_texts.append(f"{content}\nSource: {url}")
            context_parts.append("=== Detailed Comparison Content ===\n" + "\n---\n".join(vector_texts))

        full_context = "\n\n".join(context_parts)
        needs_web = not data['has_results']

        return full_context, data['has_results'], needs_web
