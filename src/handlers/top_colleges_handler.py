from typing import Dict, List, Optional
from db_setup import query_top_colleges, get_connection
from vector_store import search_by_type


class TopCollegesHandler:
    """Handles queries for top/best colleges by location, ranking, or course type."""

    def get_colleges_by_location(self, location: str, limit: int = 10) -> List[Dict]:
        """Get top colleges filtered by location."""
        return query_top_colleges(limit=limit, location=location)

    def get_colleges_by_course(self, course_keyword: str, limit: int = 10) -> List[Dict]:
        """Get colleges offering a specific course."""
        conn = get_connection()
        conn.row_factory = lambda c, r: dict(zip([col[0] for col in c.description], r))
        cursor = conn.cursor()
        cursor.execute('''
            SELECT name, nirf_rank, rating, fee_range, courses_offered, location,
                   established_year, college_type
            FROM colleges
            WHERE nirf_rank IS NOT NULL
            ORDER BY nirf_rank ASC
            LIMIT ?
        ''', (limit,))
        rows = cursor.fetchall()
        conn.close()
        return rows

    def get_context(self, query: str, location: Optional[str] = None) -> Dict:
        """Retrieve context for top colleges query."""
        sql_results = []
        vector_results = []

        if location:
            sql_results = self.get_colleges_by_location(location, limit=10)
        else:
            sql_results = query_top_colleges(limit=10)

        # Semantic search for additional context
        search_query = f"top colleges {location or ''} {query}"
        vector_results = search_by_type(search_query, doc_type='college', n_results=5)
        blog_results = search_by_type(search_query, doc_type='blog', n_results=2)
        vector_results.extend(blog_results)

        has_results = bool(sql_results or vector_results)

        return {
            'sql_data': sql_results,
            'vector_data': vector_results,
            'location': location,
            'has_results': has_results
        }

    def format_college_ranking(self, colleges: List[Dict], location: Optional[str] = None) -> str:
        """Format college ranking list."""
        if not colleges:
            return ""

        header = "Top Colleges"
        if location:
            header += f" in {location}"
        header += ":\n"

        rows = [header]
        for i, c in enumerate(colleges, 1):
            name = c.get('name', 'Unknown')
            nirf = c.get('nirf_rank', 'N/A')
            fee = c.get('fee_range', 'N/A')
            loc = c.get('location', '')
            rows.append(f"  {i}. {name} | NIRF #{nirf} | Fee: INR {fee} | {loc}")

        return "\n".join(rows)

    def build_prompt_context(self, query: str, location: Optional[str] = None) -> tuple:
        """
        Build full context for LLM prompt.

        Returns:
            (context_str, has_results, needs_web_search)
        """
        data = self.get_context(query, location)

        context_parts = []

        if data['sql_data']:
            ranking_text = self.format_college_ranking(data['sql_data'], data['location'])
            context_parts.append("=== Top Colleges Ranking ===\n" + ranking_text)

        if data['vector_data']:
            vector_texts = []
            for r in data['vector_data'][:3]:
                content = r.get('content', '')
                url = r.get('metadata', {}).get('url', '')
                vector_texts.append(f"{content}\nSource: {url}")
            context_parts.append("=== Detailed Information ===\n" + "\n---\n".join(vector_texts))

        full_context = "\n\n".join(context_parts)
        needs_web = not data['has_results']

        return full_context, data['has_results'], needs_web
