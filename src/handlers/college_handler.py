from typing import Dict, List, Optional
from db_setup import query_college, query_top_colleges, get_connection
from vector_store import search_by_type


class CollegeHandler:
    """Handles queries about specific colleges - admissions, fees, facilities, placements."""

    def get_context(self, query: str, college_names: List[str], location: Optional[str] = None) -> Dict:
        """
        Retrieve relevant context for a college query.

        Returns:
            Dict with 'sql_data', 'vector_data', 'has_results'
        """
        sql_results = []
        vector_results = []

        # SQL lookup for each college name
        for name in college_names:
            college = query_college(name)
            if college:
                sql_results.append(college)

        # If no specific college names, try location-based
        if not sql_results and location:
            sql_results = query_top_colleges(limit=5, location=location)

        # Semantic search in vector store
        vector_results = search_by_type(query, doc_type='college', n_results=5)

        # Also search comparison docs that mention the college
        if college_names:
            comp_results = search_by_type(
                f"{' '.join(college_names)} {query}",
                doc_type='comparison',
                n_results=3
            )
            vector_results.extend(comp_results)

        has_results = bool(sql_results or vector_results)

        return {
            'sql_data': sql_results,
            'vector_data': vector_results,
            'has_results': has_results
        }

    def format_sql_context(self, sql_results: List[Dict]) -> str:
        """Format SQL results into readable context."""
        if not sql_results:
            return ""

        parts = []
        for college in sql_results:
            name = college.get('name', 'Unknown')
            nirf = college.get('nirf_rank')
            rating = college.get('rating')
            fee = college.get('fee_range')
            courses = college.get('courses_offered')
            students = college.get('total_students')
            year = college.get('established_year')
            location = college.get('location')
            college_type = college.get('college_type')

            info = f"College: {name}\n"
            if nirf:
                info += f"  NIRF Rank: #{nirf}\n"
            if rating:
                info += f"  Rating: {rating}/5\n"
            if college_type:
                info += f"  Type: {college_type}\n"
            if fee:
                info += f"  Fee Range: INR {fee}\n"
            if courses:
                info += f"  Courses Offered: {courses}\n"
            if students:
                info += f"  Total Students: {students:,}\n"
            if year:
                info += f"  Established: {year}\n"
            if location:
                info += f"  Location: {location}\n"

            parts.append(info)

        return "\n".join(parts)

    def build_prompt_context(self, query: str, college_names: List[str], location: Optional[str] = None) -> tuple:
        """
        Build full context for LLM prompt.

        Returns:
            (context_str, has_results, used_web_search_needed)
        """
        data = self.get_context(query, college_names, location)

        context_parts = []

        # Add structured SQL data
        sql_context = self.format_sql_context(data['sql_data'])
        if sql_context:
            context_parts.append("=== Structured College Data ===\n" + sql_context)

        # Add vector search results
        if data['vector_data']:
            vector_texts = []
            for r in data['vector_data'][:4]:
                content = r.get('content', '')
                url = r.get('metadata', {}).get('url', '')
                vector_texts.append(f"{content}\nSource: {url}")
            context_parts.append("=== Detailed Information ===\n" + "\n---\n".join(vector_texts))

        full_context = "\n\n".join(context_parts)
        needs_web = not data['has_results']

        return full_context, data['has_results'], needs_web
