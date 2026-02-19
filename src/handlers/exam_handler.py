from typing import Dict, List, Optional
from db_setup import query_exam, get_connection
from vector_store import search_by_type


class ExamHandler:
    """Handles queries about entrance exams - dates, patterns, admit cards, results."""

    def get_context(self, query: str, exam_names: List[str]) -> Dict:
        """Retrieve relevant context for an exam query."""
        sql_results = []
        vector_results = []

        # SQL lookup for each exam
        for name in exam_names:
            exam = query_exam(name)
            if exam:
                sql_results.append(exam)

        # Semantic search in vector store
        vector_results = search_by_type(query, doc_type='exam', n_results=5)

        # Also search blogs for exam tips/patterns
        blog_results = search_by_type(query, doc_type='blog', n_results=2)
        vector_results.extend(blog_results)

        has_results = bool(sql_results or vector_results)

        return {
            'sql_data': sql_results,
            'vector_data': vector_results,
            'has_results': has_results
        }

    def format_sql_context(self, sql_results: List[Dict]) -> str:
        """Format SQL exam results into readable context."""
        if not sql_results:
            return ""

        parts = []
        for exam in sql_results:
            name = exam.get('name', 'Unknown')
            date = exam.get('exam_date')
            body = exam.get('conducting_body')
            mode = exam.get('exam_mode')
            duration = exam.get('duration')

            info = f"Exam: {name}\n"
            if date:
                info += f"  Exam Date: {date}\n"
            if body:
                info += f"  Conducting Body: {body}\n"
            if mode:
                info += f"  Mode: {mode}\n"
            if duration:
                info += f"  Duration: {duration}\n"

            parts.append(info)

        return "\n".join(parts)

    def build_prompt_context(self, query: str, exam_names: List[str]) -> tuple:
        """
        Build full context for LLM prompt.

        Returns:
            (context_str, has_results, needs_web_search)
        """
        data = self.get_context(query, exam_names)

        context_parts = []

        sql_context = self.format_sql_context(data['sql_data'])
        if sql_context:
            context_parts.append("=== Exam Schedule Data ===\n" + sql_context)

        if data['vector_data']:
            vector_texts = []
            for r in data['vector_data'][:4]:
                content = r.get('content', '')
                url = r.get('metadata', {}).get('url', '')
                vector_texts.append(f"{content}\nSource: {url}")
            context_parts.append("=== Detailed Exam Information ===\n" + "\n---\n".join(vector_texts))

        full_context = "\n\n".join(context_parts)
        needs_web = not data['has_results']

        return full_context, data['has_results'], needs_web
