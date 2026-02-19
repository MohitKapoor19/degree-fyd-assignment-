import json
import re
from pathlib import Path
from typing import Dict, List, Optional, Tuple


# ─────────────────────────────────────────────────────────────────────────────
# File loader
# ─────────────────────────────────────────────────────────────────────────────

def load_jsonl(file_path: Path) -> List[Dict]:
    """Load JSONL file and return list of records, skipping malformed lines."""
    records = []
    with open(file_path, 'r', encoding='utf-8') as f:
        for line in f:
            line = line.strip()
            if line:
                try:
                    records.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
    return records


# ─────────────────────────────────────────────────────────────────────────────
# Low-level field extractors  (all based on actual JSONL patterns)
# ─────────────────────────────────────────────────────────────────────────────

def _clean_fee(raw: str) -> Optional[str]:
    """Remove internal spaces from fee strings like '2,00,000'."""
    return raw.replace(' ', '') if raw else None


def extract_college_names(content: str) -> Tuple[Optional[str], Optional[str]]:
    """
    Extract both college names.  Three fallback patterns:
      1. "Compare X and Y across various parameters"  (body sentence)
      2. "Login X vs Y Shortlist"                     (page header)
      3. "X vs Y Comparison"                          (title line)
    """
    m = re.search(r"Compare\s+(.+?)\s+and\s+(.+?)\s+across", content, re.IGNORECASE)
    if m:
        return m.group(1).strip(), m.group(2).strip()

    m = re.search(r"Login\s+(.+?)\s+vs\s+(.+?)\s+Shortlist", content, re.IGNORECASE)
    if m:
        return m.group(1).strip(), m.group(2).strip()

    m = re.search(r"^(.+?)\s+vs\s+(.+?)\s+Comparison", content, re.IGNORECASE | re.MULTILINE)
    if m:
        return m.group(1).strip(), m.group(2).strip()

    return None, None


def extract_all_fees(content: str) -> Tuple[Optional[str], Optional[str]]:
    """
    College 1 fee: "offers programmes starting from INR 41,000"
    College 2 fee: "course fees typically range between INR 1,000 and INR 64,000"
    Handles Indian number format: 2,00,000
    """
    starts = re.findall(
        r"offers programmes starting from INR\s*([\d,\s]+?)(?:\s*,|\s+while|\s*\.)",
        content, re.IGNORECASE
    )
    fee1 = _clean_fee(starts[0]) if starts else None

    m = re.search(
        r"course fees typically range between INR\s*([\d,\s]+?)\s+and\s+INR\s*([\d,\s]+?)(?:\s*\.\s*Candidates|\s*Candidates)",
        content, re.IGNORECASE
    )
    fee2 = f"{_clean_fee(m.group(1))} - {_clean_fee(m.group(2))}" if m else None

    return fee1, fee2


def extract_all_nirf_ranks(content: str) -> Tuple[Optional[int], Optional[int]]:
    """
    Primary:  "NIRF Rank: #56"  (appears twice in College Information block)
    Fallback: "NIRF Ranking #56 #1"  (highlights table)
    """
    ranks = re.findall(r"NIRF Rank:\s*#(\d+)", content)
    if len(ranks) >= 2:
        return int(ranks[0]), int(ranks[1])

    m = re.search(r"NIRF Ranking\s+#(\d+)\s+#(\d+)", content)
    if m:
        return int(m.group(1)), int(m.group(2))

    if len(ranks) == 1:
        return int(ranks[0]), None

    return None, None


def extract_all_courses_offered(content: str) -> Tuple[Optional[int], Optional[int]]:
    """
    Primary:  "6 courses offered by X and 285 courses offered by Y"
    Fallback: "Courses Offered 6 285"  (highlights table)
    """
    matches = re.findall(r"(\d+)\s+courses\s+offered\s+by", content, re.IGNORECASE)
    if len(matches) >= 2:
        return int(matches[0]), int(matches[1])

    m = re.search(r"Courses Offered\s+(\d+)\s+(\d+)", content)
    if m:
        return int(m.group(1)), int(m.group(2))

    if len(matches) == 1:
        return int(matches[0]), None

    return None, None


def extract_all_established_years(content: str) -> Tuple[Optional[int], Optional[int]]:
    """
    Pattern: "Established Year 1997 1985"  (highlights table, both on same line)
    """
    m = re.search(r"Established Year\s+(\d{4})\s+(\d{4})", content)
    if m:
        return int(m.group(1)), int(m.group(2))

    m = re.search(r"Established Year\s+(\d{4})", content)
    if m:
        return int(m.group(1)), None

    return None, None


def extract_all_total_students(content: str) -> Tuple[Optional[int], Optional[int]]:
    """
    Pattern: "Total Students 65000 3093583"
             "Total Students Not Available 11200"
    """
    def _parse(s: str) -> Optional[int]:
        return int(s.replace(',', '')) if s.strip() != 'Not Available' else None

    m = re.search(
        r"Total Students\s+([\d,]+|Not Available)\s+([\d,]+|Not Available)",
        content
    )
    if m:
        return _parse(m.group(1)), _parse(m.group(2))

    m = re.search(r"Total Students\s+([\d,]+)", content)
    if m:
        return _parse(m.group(1)), None

    return None, None


def extract_all_college_types(content: str) -> Tuple[Optional[str], Optional[str]]:
    """
    Pattern: "College Type Private Private"
             "College Type Government Private"
    """
    types = r"(Private|Government|Deemed|Public|Autonomous)"
    m = re.search(rf"College Type\s+{types}\s+{types}", content, re.IGNORECASE)
    if m:
        return m.group(1).strip(), m.group(2).strip()

    m = re.search(rf"College Type\s+{types}", content, re.IGNORECASE)
    if m:
        return m.group(1).strip(), None

    return None, None


def extract_all_ratings(content: str) -> Tuple[Optional[float], Optional[float]]:
    """
    Pattern: "NIRF Rank: #56 4.5"  — rating immediately follows rank on same line.
    """
    matches = re.findall(r"NIRF Rank:\s*#\d+\s+([\d.]+)", content)
    r1 = float(matches[0]) if len(matches) > 0 else None
    r2 = float(matches[1]) if len(matches) > 1 else None
    return r1, r2


def extract_college_locations(content: str) -> Tuple[Optional[str], Optional[str]]:
    """
    Pattern: "Salem, Tamil Nadu NIRF Rank: #56"
             "New Delhi, Delhi NIRF Rank: #1"
    Captures "City, State" strings that appear just before "NIRF Rank".
    """
    matches = re.findall(
        r"([A-Za-z][A-Za-z\s\-\.]+,\s*[A-Za-z][A-Za-z\s\-\.]+?)\s+NIRF Rank",
        content
    )
    loc1 = matches[0].strip() if len(matches) > 0 else None
    loc2 = matches[1].strip() if len(matches) > 1 else None
    return loc1, loc2


def extract_exam_info(content: str, url: str = '') -> Dict:
    """
    Extract structured exam data from actual table patterns:
      "Exam Name Common Law Admission Test (CLAT) 2026"
      "Conducting Body Consortium of National Law Universities"
      "CLAT Exam Date 7 December 2025"
      "Exam Mode Offline (Pen-and-paper based)"
      "Duration of Exam 2 hours"
    """
    info: Dict = {
        'exam_name': None,
        'full_name': None,
        'exam_date': None,
        'application_start': None,
        'application_end': None,
        'result_date': None,
        'conducting_body': None,
        'exam_mode': None,
        'duration': None,
        'url': url,
        'raw_content': content
    }

    # Short name from URL slug: "clat-exam-date" → "CLAT"
    if url:
        slug = url.rstrip('/').split('/')[-1]
        info['exam_name'] = slug.split('-exam-')[0].replace('-', ' ').upper()

    # Full name from table
    m = re.search(r"Exam Name\s+([^\n]+?)(?:\s+Conducting Body|\n)", content)
    if m:
        info['full_name'] = m.group(1).strip()

    # Exam date — table row like "CLAT Exam Date 7 December 2025"
    m = re.search(
        r"(?:Exam Date|exam.*?(?:scheduled for|held on|conducted on|is))\s*"
        r"(\d{1,2}\s+\w+\s*,?\s*\d{4})",
        content, re.IGNORECASE
    )
    if m:
        info['exam_date'] = m.group(1).strip()

    # Conducting body
    m = re.search(r"Conducting Body\s+(.+?)(?:\n|\s{2,}|\d{1,2}\s+\w+\s+\d{4})", content)
    if m:
        info['conducting_body'] = m.group(1).strip()

    # Exam mode
    m = re.search(r"Exam Mode\s+(.+?)(?:\n|\s{2,})", content)
    if m:
        info['exam_mode'] = m.group(1).strip()

    # Duration
    m = re.search(r"Duration(?:\s+of\s+Exam)?\s+(\d+\s*hours?(?:\s+\d+\s*minutes?)?)", content, re.IGNORECASE)
    if m:
        info['duration'] = m.group(1).strip()

    # Application start / end
    m = re.search(r"Application\s+(?:Start|Begin|Open)\s+(?:Date\s+)?(\d{1,2}\s+\w+\s*\d{4})", content, re.IGNORECASE)
    if m:
        info['application_start'] = m.group(1).strip()

    m = re.search(r"Application\s+(?:End|Last|Close)\s+(?:Date\s+)?(\d{1,2}\s+\w+\s*\d{4})", content, re.IGNORECASE)
    if m:
        info['application_end'] = m.group(1).strip()

    # Result date
    m = re.search(r"Result\s+(?:Date\s+)?(\d{1,2}\s+\w+\s*\d{4})", content, re.IGNORECASE)
    if m:
        info['result_date'] = m.group(1).strip()

    return info


def extract_blog_info(content: str, url: str = '') -> Dict:
    """
    Extract structured blog data.
    Patterns:
      Title: "Best NMIMS Online MBA Specializations in 2025 | Find Your Perfect Career Fit"
      Date:  "5 Nov 2025"
      Author: "yogita Content Creator at DegreeFYD"  or  "By Silki Joshi , Author"
    """
    info: Dict = {
        'title': None,
        'author': None,
        'date': None,
        'college_mentioned': None,
        'url': url,
        'content': content
    }

    m = re.search(r"^(.+?)\s*(?:\||\s+Search here)", content)
    if m:
        info['title'] = m.group(1).strip()

    m = re.search(r"(\d{1,2}\s+\w{3,9}\s+\d{4})", content)
    if m:
        info['date'] = m.group(1).strip()

    m = re.search(r"By\s+([A-Za-z\s]+?)\s*,\s*Author", content)
    if m:
        info['author'] = m.group(1).strip()
    else:
        m = re.search(r"([A-Za-z]+)\s+Content Creator at DegreeFYD", content)
        if m:
            info['author'] = m.group(1).strip()

    m = re.search(
        r"((?:IIT|IIM|NIT|BITS|VIT|SRM|LPU|Amity|Manipal|NMIMS|Chandigarh|Lovely)[A-Za-z\s]*(?:University|Institute|College)?)",
        content
    )
    if m:
        info['college_mentioned'] = m.group(1).strip()

    return info


# ─────────────────────────────────────────────────────────────────────────────
# Record parsers
# ─────────────────────────────────────────────────────────────────────────────

def parse_comparison_record(record: Dict) -> Dict:
    """
    Parse a comparison/college type record into a fully structured dict.
    Uses all improved extractors so every field is populated where possible.
    """
    content = record.get('content', '')
    url = record.get('url', '')

    college1, college2 = extract_college_names(content)
    fee1, fee2 = extract_all_fees(content)
    nirf1, nirf2 = extract_all_nirf_ranks(content)
    courses1, courses2 = extract_all_courses_offered(content)
    year1, year2 = extract_all_established_years(content)
    students1, students2 = extract_all_total_students(content)
    type1, type2 = extract_all_college_types(content)
    rating1, rating2 = extract_all_ratings(content)
    loc1, loc2 = extract_college_locations(content)

    return {
        'college_1': college1,
        'college_2': college2,
        'college_1_fees': fee1,
        'college_2_fees': fee2,
        'college_1_nirf': nirf1,
        'college_2_nirf': nirf2,
        'college_1_courses': courses1,
        'college_2_courses': courses2,
        'college_1_year': year1,
        'college_2_year': year2,
        'college_1_students': students1,
        'college_2_students': students2,
        'college_1_type': type1,
        'college_2_type': type2,
        'college_1_rating': rating1,
        'college_2_rating': rating2,
        'college_1_location': loc1,
        'college_2_location': loc2,
        'url': url,
        'raw_content': content
    }


def parse_college_record(record: Dict) -> Dict:
    """
    College-type records are structurally identical to comparison records
    (same page layout, just tagged differently in the source).
    Reuse parse_comparison_record and expose college_1 fields as primary.
    """
    comp = parse_comparison_record(record)
    return {
        'name': comp['college_1'],
        'compared_with': comp['college_2'],
        'location': comp['college_1_location'],
        'nirf_rank': comp['college_1_nirf'],
        'established_year': comp['college_1_year'],
        'total_students': comp['college_1_students'],
        'courses_offered': comp['college_1_courses'],
        'college_type': comp['college_1_type'],
        'rating': comp['college_1_rating'],
        'fee_range': comp['college_1_fees'],
        'url': comp['url'],
        'raw_content': comp['raw_content']
    }


def parse_exam_record(record: Dict) -> Dict:
    """Parse an exam type record using the improved exam extractor."""
    content = record.get('content', '')
    url = record.get('url', '')
    return extract_exam_info(content, url=url)


def parse_blog_record(record: Dict) -> Dict:
    """Parse a blog type record using the blog extractor."""
    content = record.get('content', '')
    url = record.get('url', '')
    return extract_blog_info(content, url=url)


# ─────────────────────────────────────────────────────────────────────────────
# Main extraction pipeline
# ─────────────────────────────────────────────────────────────────────────────

def extract_all_data(jsonl_path: Path) -> Dict[str, List[Dict]]:
    """Load JSONL and route every record to the correct parser."""
    records = load_jsonl(jsonl_path)

    extracted: Dict[str, List[Dict]] = {
        'comparisons': [],
        'colleges': [],
        'exams': [],
        'blogs': [],
        'courses': [],
        'pages': []
    }

    for record in records:
        record_type = record.get('type', 'page')

        if record_type == 'comparison':
            extracted['comparisons'].append(parse_comparison_record(record))
        elif record_type == 'college':
            extracted['colleges'].append(parse_college_record(record))
        elif record_type == 'exam':
            extracted['exams'].append(parse_exam_record(record))
        elif record_type == 'blog':
            extracted['blogs'].append(parse_blog_record(record))
        elif record_type == 'course':
            extracted['courses'].append({
                'url': record.get('url', ''),
                'content': record.get('content', '')
            })
        else:
            extracted['pages'].append({
                'url': record.get('url', ''),
                'content': record.get('content', '')
            })

    return extracted


def get_unique_colleges(extracted_data: Dict) -> List[Dict]:
    """
    Build a deduplicated college registry from comparison records.

    Strategy:
    - First occurrence wins for identity fields (name, year, type).
    - Best (non-None) value wins for numeric fields (nirf_rank, students, courses).
      For NIRF rank, lower number = better, so we keep the lowest non-None value.
    """
    colleges: Dict[str, Dict] = {}

    def _update(name: Optional[str], data: Dict) -> None:
        if not name:
            return
        if name not in colleges:
            colleges[name] = data.copy()
            return
        existing = colleges[name]
        # Keep best NIRF rank (lowest non-None)
        if data.get('nirf_rank') is not None:
            if existing.get('nirf_rank') is None or data['nirf_rank'] < existing['nirf_rank']:
                existing['nirf_rank'] = data['nirf_rank']
        # Fill in missing fields with new data
        for field in ('courses_offered', 'established_year', 'total_students',
                      'college_type', 'rating', 'location', 'fee_range'):
            if existing.get(field) is None and data.get(field) is not None:
                existing[field] = data[field]

    for comp in extracted_data['comparisons']:
        _update(comp.get('college_1'), {
            'name': comp.get('college_1'),
            'nirf_rank': comp.get('college_1_nirf'),
            'courses_offered': comp.get('college_1_courses'),
            'established_year': comp.get('college_1_year'),
            'total_students': comp.get('college_1_students'),
            'college_type': comp.get('college_1_type'),
            'rating': comp.get('college_1_rating'),
            'location': comp.get('college_1_location'),
            'fee_range': comp.get('college_1_fees'),
        })
        _update(comp.get('college_2'), {
            'name': comp.get('college_2'),
            'nirf_rank': comp.get('college_2_nirf'),
            'courses_offered': comp.get('college_2_courses'),
            'established_year': comp.get('college_2_year'),
            'total_students': comp.get('college_2_students'),
            'college_type': comp.get('college_2_type'),
            'rating': comp.get('college_2_rating'),
            'location': comp.get('college_2_location'),
            'fee_range': comp.get('college_2_fees'),
        })

    # Also pull in standalone college records
    for col in extracted_data.get('colleges', []):
        _update(col.get('name'), {
            'name': col.get('name'),
            'nirf_rank': col.get('nirf_rank'),
            'courses_offered': col.get('courses_offered'),
            'established_year': col.get('established_year'),
            'total_students': col.get('total_students'),
            'college_type': col.get('college_type'),
            'rating': col.get('rating'),
            'location': col.get('location'),
            'fee_range': col.get('fee_range'),
        })

    return list(colleges.values())


if __name__ == "__main__":
    import sys
    import os
    sys.path.insert(0, os.path.dirname(__file__))
    from config import JSONL_FILE

    print(f"Loading data from {JSONL_FILE}...")
    extracted = extract_all_data(JSONL_FILE)

    print("\nExtracted data summary:")
    for key, value in extracted.items():
        print(f"  {key}: {len(value)} records")

    unique_colleges = get_unique_colleges(extracted)
    print(f"\nUnique colleges: {len(unique_colleges)}")

    if extracted['comparisons']:
        print("\nSample comparison record:")
        sample = extracted['comparisons'][0]
        for k, v in sample.items():
            if k != 'raw_content':
                print(f"  {k}: {v}")

    if extracted['exams']:
        print("\nSample exam record:")
        sample = extracted['exams'][0]
        for k, v in sample.items():
            if k != 'raw_content':
                print(f"  {k}: {v}")

    if extracted['blogs']:
        print("\nSample blog record:")
        sample = extracted['blogs'][0]
        for k, v in sample.items():
            if k != 'content':
                print(f"  {k}: {v}")
