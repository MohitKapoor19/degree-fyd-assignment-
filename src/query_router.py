import re
from typing import Dict, Tuple, Optional
from groq import Groq
from config import GROQ_API_KEY, GROQ_ROUTER_MODEL, CATEGORIES


client = Groq(api_key=GROQ_API_KEY)


ROUTER_PROMPT = """You are a query classifier for an education chatbot. Classify the user's query into ONE category.

Categories and rules:
1. COLLEGE - Questions about a SPECIFIC named college: admissions process, fees, facilities, placements, hostel, scholarships, courses offered, campus life. The college name is mentioned.
   Examples: "How to get admission to VIT Vellore", "Fee at DTU", "IIT Bombay hostel facilities", "LPU placements"

2. EXAM - Questions about entrance exams: dates, patterns, admit cards, results, syllabus, registration, mock tests.
   Examples: "JEE Main exam pattern", "MHT CET admit card", "GATE 2026 syllabus", "CLAT exam date"

3. COMPARISON - Comparing TWO or more colleges against each other.
   Examples: "VIT vs Amrita", "Compare IIM Indore and IIM Kozhikode", "Which is better DTU or NSIT"

4. PREDICTOR - User has a rank/score/percentile and wants to know which colleges they can get into.
   Examples: "Which colleges with JEE rank 5000", "70 percentile in MHT CET colleges", "Can I get NIT with rank 10000"
   IMPORTANT: "How to get admission" or "admission process" is COLLEGE, NOT PREDICTOR.

5. TOP_COLLEGES - Finding top/best/popular colleges by location, ranking, or course type WITHOUT a specific rank.
   Examples: "Top B.Tech colleges in Mumbai", "Best engineering colleges in Bangalore", "Top ranked NITs"

6. GENERAL - General advice, career guidance, blog content.

Extract entities:
- college_names: List of college names mentioned
- exam_names: List of exam names mentioned  
- location: City/State if mentioned
- rank_score: Any rank or percentile mentioned

Query: {query}

Respond in this exact format:
CATEGORY: <category>
COLLEGE_NAMES: <comma-separated names or NONE>
EXAM_NAMES: <comma-separated names or NONE>
LOCATION: <location or NONE>
RANK_SCORE: <rank/percentile or NONE>"""


def parse_router_response(response: str) -> Dict:
    """Parse the router LLM response."""
    result = {
        'category': 'GENERAL',
        'college_names': [],
        'exam_names': [],
        'location': None,
        'rank_score': None
    }
    
    lines = response.strip().split('\n')
    for line in lines:
        if ':' in line:
            key, value = line.split(':', 1)
            key = key.strip().upper()
            value = value.strip()
            
            if key == 'CATEGORY' and value in CATEGORIES:
                result['category'] = value
            elif key == 'COLLEGE_NAMES' and value != 'NONE':
                result['college_names'] = [n.strip() for n in value.split(',') if n.strip()]
            elif key == 'EXAM_NAMES' and value != 'NONE':
                result['exam_names'] = [n.strip() for n in value.split(',') if n.strip()]
            elif key == 'LOCATION' and value != 'NONE':
                result['location'] = value
            elif key == 'RANK_SCORE' and value != 'NONE':
                result['rank_score'] = value
    
    return result


def fast_route(query: str) -> Optional[str]:
    """Fast pattern-based routing for obvious cases."""
    query_lower = query.lower()

    # Comparison patterns — must come first
    if re.search(r'\bvs\b|\bversus\b|\bcompare\b|\bcomparison\b', query_lower):
        return 'COMPARISON'

    # Exam patterns
    exam_keywords = ['exam date', 'admit card', 'exam pattern', 'syllabus', 'result date',
                     'application form', 'mock test', 'registration deadline']
    if any(kw in query_lower for kw in exam_keywords):
        return 'EXAM'

    # COLLEGE — specific college queries (admission process, fees, facilities)
    # Must check BEFORE predictor to avoid misclassifying "admission to VIT" as PREDICTOR
    college_specific = [
        'admission to', 'admission in', 'admission process', 'how to get into',
        'fee at', 'fees at', 'fee structure', 'hostel at', 'placement at',
        'scholarship at', 'campus life', 'courses at', 'facilities at'
    ]
    if any(kw in query_lower for kw in college_specific):
        return 'COLLEGE'

    # Top colleges patterns (no rank mentioned)
    if re.search(r'\btop\b.*\bcollege|\bbest\b.*\bcollege|\branked\b.*\bcollege|\bpopular\b.*\bcollege', query_lower):
        if not re.search(r'\d+\s*(?:rank|percentile|score)', query_lower):
            return 'TOP_COLLEGES'

    # Predictor — user has a rank/score and wants college suggestions
    if re.search(r'\d+\s*(?:rank|percentile)|(?:rank|percentile|score)\s*\d+|\bcan i get\b|\bwhich colleges.*\d+', query_lower):
        return 'PREDICTOR'

    return None


def route_query(query: str) -> Dict:
    """Route query to appropriate category with entity extraction."""
    # Try fast routing first
    fast_category = fast_route(query)
    
    # Use LLM for entity extraction and ambiguous cases
    try:
        completion = client.chat.completions.create(
            model=GROQ_ROUTER_MODEL,
            messages=[
                {"role": "user", "content": ROUTER_PROMPT.format(query=query)}
            ],
            temperature=0,
            max_tokens=200
        )
        
        response = completion.choices[0].message.content
        result = parse_router_response(response)
        
        # Override with fast route if available (more reliable for obvious patterns)
        if fast_category:
            result['category'] = fast_category
        
        return result
        
    except Exception as e:
        print(f"Router error: {e}")
        # Fallback to fast route or GENERAL
        return {
            'category': fast_category or 'GENERAL',
            'college_names': [],
            'exam_names': [],
            'location': None,
            'rank_score': None
        }


def extract_college_names_from_query(query: str) -> list:
    """Extract college names from query using patterns."""
    # Common college name patterns
    patterns = [
        r'(?:at|about|of|for)\s+([A-Z][A-Za-z\s]+(?:University|Institute|College|IIM|IIT|NIT|BITS)[A-Za-z\s]*)',
        r'([A-Z]{2,}(?:\s+[A-Z][a-z]+)*)',  # Acronyms like IIT, IIM, VIT
        r'((?:IIT|IIM|NIT|BITS|VIT|SRM|LPU|Amity|Manipal|NMIMS)[A-Za-z\s]*)'
    ]
    
    names = []
    for pattern in patterns:
        matches = re.findall(pattern, query)
        names.extend(matches)
    
    return list(set([n.strip() for n in names if len(n) > 2]))


def extract_exam_names_from_query(query: str) -> list:
    """Extract exam names from query."""
    exam_patterns = [
        r'\b(JEE\s*(?:Main|Advanced|Mains)?)\b',
        r'\b(NEET(?:\s*UG)?)\b',
        r'\b(CAT)\b',
        r'\b(GATE)\b',
        r'\b(CLAT)\b',
        r'\b(MHT[\s-]*CET)\b',
        r'\b(TS[\s-]*EAMCET)\b',
        r'\b(AP[\s-]*EAMCET)\b',
        r'\b(BITSAT)\b',
        r'\b(VITEEE)\b',
        r'\b(COMEDK)\b',
        r'\b(KCET)\b',
        r'\b(WBJEE)\b'
    ]
    
    exams = []
    for pattern in exam_patterns:
        matches = re.findall(pattern, query, re.IGNORECASE)
        exams.extend(matches)
    
    return list(set([e.upper().replace(' ', '') for e in exams]))


if __name__ == "__main__":
    # Test queries
    test_queries = [
        "How can I get admission to VIT Vellore?",
        "Compare IIM Indore vs IIM Kozhikode",
        "What is the exam pattern for JEE Main?",
        "Which colleges accept 70 rank in JEE Main?",
        "Top B.Tech colleges in Mumbai",
        "Best NMIMS Online MBA Specializations"
    ]
    
    for query in test_queries:
        result = route_query(query)
        print(f"\nQuery: {query}")
        print(f"Result: {result}")
