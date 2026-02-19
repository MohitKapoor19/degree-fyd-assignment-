from typing import Dict, List, Optional
from db_setup import get_connection
from vector_store import search_by_type
import re


class PredictorHandler:
    """Handles college prediction queries based on rank/score/percentile."""

    def parse_rank_score(self, rank_score_str: Optional[str]) -> Optional[int]:
        """Parse rank or score from string."""
        if not rank_score_str:
            return None
        numbers = re.findall(r'\d+', str(rank_score_str))
        return int(numbers[0]) if numbers else None

    def get_colleges_by_nirf(self, max_rank: int = 50, limit: int = 10) -> List[Dict]:
        """Get colleges within a NIRF rank range."""
        conn = get_connection()
        conn.row_factory = lambda c, r: dict(zip([col[0] for col in c.description], r))
        cursor = conn.cursor()
        cursor.execute('''
            SELECT name, nirf_rank, rating, fee_range, courses_offered, location, college_type
            FROM colleges
            WHERE nirf_rank IS NOT NULL AND nirf_rank <= ?
            ORDER BY nirf_rank ASC
            LIMIT ?
        ''', (max_rank, limit))
        rows = cursor.fetchall()
        conn.close()
        return rows

    def get_context(self, query: str, exam_names: List[str], rank_score: Optional[str]) -> Dict:
        """Retrieve context for predictor query."""
        rank = self.parse_rank_score(rank_score)

        sql_results = []
        vector_results = []

        # If rank is provided, estimate eligible colleges
        if rank:
            # Use rank as a proxy for NIRF rank range (rough heuristic)
            max_nirf = min(rank * 2, 200) if rank < 100 else 200
            sql_results = self.get_colleges_by_nirf(max_rank=max_nirf, limit=15)

        # Semantic search for cutoff/predictor content
        search_query = query
        if exam_names:
            search_query = f"{' '.join(exam_names)} cutoff rank predictor {query}"

        vector_results = search_by_type(search_query, doc_type='college', n_results=5)
        blog_results = search_by_type(search_query, doc_type='blog', n_results=3)
        vector_results.extend(blog_results)

        has_results = bool(sql_results or vector_results)

        return {
            'sql_data': sql_results,
            'vector_data': vector_results,
            'rank': rank,
            'exam_names': exam_names,
            'has_results': has_results
        }

    def format_college_list(self, colleges: List[Dict], rank: Optional[int] = None) -> str:
        """Format college list as readable text."""
        if not colleges:
            return ""

        header = f"Colleges potentially eligible"
        if rank:
            header += f" for rank {rank}"
        header += ":\n"

        rows = [header]
        for i, c in enumerate(colleges, 1):
            name = c.get('name', 'Unknown')
            nirf = c.get('nirf_rank', 'N/A')
            fee = c.get('fee_range', 'N/A')
            location = c.get('location', '')
            rows.append(f"  {i}. {name} | NIRF #{nirf} | Fee: INR {fee} | {location}")

        return "\n".join(rows)

    def build_prompt_context(self, query: str, exam_names: List[str], rank_score: Optional[str]) -> tuple:
        """
        Build full context for LLM prompt.

        Returns:
            (context_str, has_results, needs_web_search)
        """
        data = self.get_context(query, exam_names, rank_score)

        context_parts = []

        if data['sql_data']:
            college_list = self.format_college_list(data['sql_data'], data['rank'])
            context_parts.append("=== College Predictor Results ===\n" + college_list)

        if data['vector_data']:
            vector_texts = []
            for r in data['vector_data'][:4]:
                content = r.get('content', '')
                url = r.get('metadata', {}).get('url', '')
                vector_texts.append(f"{content}\nSource: {url}")
            context_parts.append("=== Related Information ===\n" + "\n---\n".join(vector_texts))

        full_context = "\n\n".join(context_parts)
        needs_web = not data['has_results']

        return full_context, data['has_results'], needs_web
