import sqlite3
from pathlib import Path
from typing import Dict, List
from config import SQLITE_DB, JSONL_FILE
from data_extractor import extract_all_data, get_unique_colleges


def create_tables(conn: sqlite3.Connection):
    """Create database tables."""
    cursor = conn.cursor()
    
    # Colleges table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS colleges (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL UNIQUE,
            location TEXT,
            college_type TEXT,
            established_year INTEGER,
            nirf_rank INTEGER,
            rating REAL,
            total_students INTEGER,
            courses_offered INTEGER,
            fee_range TEXT,
            url TEXT
        )
    ''')
    
    # Exams table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS exams (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            full_name TEXT,
            exam_date TEXT,
            application_start TEXT,
            application_end TEXT,
            result_date TEXT,
            conducting_body TEXT,
            exam_mode TEXT,
            duration TEXT,
            url TEXT,
            raw_content TEXT
        )
    ''')
    
    # Comparisons table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS comparisons (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            college_1 TEXT NOT NULL,
            college_2 TEXT NOT NULL,
            college_1_fees TEXT,
            college_2_fees TEXT,
            college_1_nirf INTEGER,
            college_2_nirf INTEGER,
            college_1_courses INTEGER,
            college_2_courses INTEGER,
            college_1_year INTEGER,
            college_2_year INTEGER,
            college_1_students INTEGER,
            college_2_students INTEGER,
            college_1_type TEXT,
            college_2_type TEXT,
            college_1_rating REAL,
            college_2_rating REAL,
            college_1_location TEXT,
            college_2_location TEXT,
            url TEXT,
            UNIQUE(college_1, college_2)
        )
    ''')
    
    # Blogs table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS blogs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT,
            author TEXT,
            date TEXT,
            college_mentioned TEXT,
            url TEXT UNIQUE,
            content TEXT
        )
    ''')
    
    conn.commit()


def insert_colleges(conn: sqlite3.Connection, colleges: List[Dict]):
    """Insert colleges into database."""
    cursor = conn.cursor()

    for college in colleges:
        try:
            cursor.execute('''
                INSERT OR IGNORE INTO colleges
                (name, location, college_type, established_year, nirf_rank,
                 rating, total_students, courses_offered, fee_range, url)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (
                college.get('name'),
                college.get('location'),
                college.get('college_type'),
                college.get('established_year'),
                college.get('nirf_rank'),
                college.get('rating'),
                college.get('total_students'),
                college.get('courses_offered'),
                college.get('fee_range'),
                college.get('url')
            ))
        except Exception as e:
            print(f"Error inserting college {college.get('name')}: {e}")

    conn.commit()


def insert_exams(conn: sqlite3.Connection, exams: List[Dict]):
    """Insert exams into database."""
    cursor = conn.cursor()
    
    for exam in exams:
        try:
            cursor.execute('''
                INSERT INTO exams 
                (name, exam_date, conducting_body, exam_mode, duration, url, raw_content)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            ''', (
                exam.get('exam_name'),
                exam.get('exam_date'),
                exam.get('conducting_body'),
                exam.get('exam_mode'),
                exam.get('duration'),
                exam.get('url'),
                exam.get('raw_content')
            ))
        except Exception as e:
            print(f"Error inserting exam: {e}")
    
    conn.commit()


def insert_comparisons(conn: sqlite3.Connection, comparisons: List[Dict]):
    """Insert comparisons into database."""
    cursor = conn.cursor()

    for comp in comparisons:
        try:
            cursor.execute('''
                INSERT OR IGNORE INTO comparisons
                (college_1, college_2,
                 college_1_fees, college_2_fees,
                 college_1_nirf, college_2_nirf,
                 college_1_courses, college_2_courses,
                 college_1_year, college_2_year,
                 college_1_students, college_2_students,
                 college_1_type, college_2_type,
                 college_1_rating, college_2_rating,
                 college_1_location, college_2_location,
                 url)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (
                comp.get('college_1'),
                comp.get('college_2'),
                comp.get('college_1_fees'),
                comp.get('college_2_fees'),
                comp.get('college_1_nirf'),
                comp.get('college_2_nirf'),
                comp.get('college_1_courses'),
                comp.get('college_2_courses'),
                comp.get('college_1_year'),
                comp.get('college_2_year'),
                comp.get('college_1_students'),
                comp.get('college_2_students'),
                comp.get('college_1_type'),
                comp.get('college_2_type'),
                comp.get('college_1_rating'),
                comp.get('college_2_rating'),
                comp.get('college_1_location'),
                comp.get('college_2_location'),
                comp.get('url')
            ))
        except Exception as e:
            print(f"Error inserting comparison: {e}")

    conn.commit()


def insert_blogs(conn: sqlite3.Connection, blogs: List[Dict]):
    """Insert blogs into database."""
    cursor = conn.cursor()

    for blog in blogs:
        try:
            cursor.execute('''
                INSERT OR IGNORE INTO blogs
                (title, author, date, college_mentioned, url, content)
                VALUES (?, ?, ?, ?, ?, ?)
            ''', (
                blog.get('title'),
                blog.get('author'),
                blog.get('date'),
                blog.get('college_mentioned'),
                blog.get('url'),
                blog.get('content')
            ))
        except Exception as e:
            print(f"Error inserting blog: {e}")

    conn.commit()


def setup_database():
    """Main function to set up the database."""
    print(f"Setting up database at {SQLITE_DB}...")
    
    # Create data directory if needed
    SQLITE_DB.parent.mkdir(parents=True, exist_ok=True)
    
    # Extract data
    print("Extracting data from JSONL...")
    extracted = extract_all_data(JSONL_FILE)
    
    # Get unique colleges
    unique_colleges = get_unique_colleges(extracted)
    
    # Connect and create tables
    conn = sqlite3.connect(SQLITE_DB)
    create_tables(conn)
    
    # Insert data
    print(f"Inserting {len(unique_colleges)} colleges...")
    insert_colleges(conn, unique_colleges)
    
    print(f"Inserting {len(extracted['exams'])} exams...")
    insert_exams(conn, extracted['exams'])
    
    print(f"Inserting {len(extracted['comparisons'])} comparisons...")
    insert_comparisons(conn, extracted['comparisons'])
    
    print(f"Inserting {len(extracted['blogs'])} blogs...")
    insert_blogs(conn, extracted['blogs'])
    
    conn.close()
    print("Database setup complete!")


def get_connection() -> sqlite3.Connection:
    """Get database connection."""
    return sqlite3.connect(SQLITE_DB)


def query_college(name: str) -> Dict:
    """Query college by name (fuzzy match)."""
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute('''
        SELECT * FROM colleges
        WHERE name LIKE ?
        LIMIT 1
    ''', (f'%{name}%',))

    row = cursor.fetchone()
    conn.close()

    if row:
        columns = ['id', 'name', 'location', 'college_type', 'established_year',
                   'nirf_rank', 'rating', 'total_students', 'courses_offered',
                   'fee_range', 'url']
        return dict(zip(columns, row))
    return None


def query_comparison(college1: str, college2: str) -> Dict:
    """Query comparison between two colleges."""
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute('''
        SELECT * FROM comparisons
        WHERE (college_1 LIKE ? AND college_2 LIKE ?)
           OR (college_1 LIKE ? AND college_2 LIKE ?)
        LIMIT 1
    ''', (f'%{college1}%', f'%{college2}%', f'%{college2}%', f'%{college1}%'))

    row = cursor.fetchone()
    conn.close()

    if row:
        columns = [
            'id', 'college_1', 'college_2',
            'college_1_fees', 'college_2_fees',
            'college_1_nirf', 'college_2_nirf',
            'college_1_courses', 'college_2_courses',
            'college_1_year', 'college_2_year',
            'college_1_students', 'college_2_students',
            'college_1_type', 'college_2_type',
            'college_1_rating', 'college_2_rating',
            'college_1_location', 'college_2_location',
            'url'
        ]
        return dict(zip(columns, row))
    return None


def query_exam(name: str) -> Dict:
    """Query exam by name."""
    conn = get_connection()
    cursor = conn.cursor()
    
    cursor.execute('''
        SELECT * FROM exams 
        WHERE name LIKE ? OR full_name LIKE ?
        LIMIT 1
    ''', (f'%{name}%', f'%{name}%'))
    
    row = cursor.fetchone()
    conn.close()
    
    if row:
        columns = ['id', 'name', 'full_name', 'exam_date', 'application_start',
                   'application_end', 'result_date', 'conducting_body', 'exam_mode',
                   'duration', 'url', 'raw_content']
        return dict(zip(columns, row))
    return None


def query_top_colleges(limit: int = 10, location: str = None) -> List[Dict]:
    """Query top colleges by NIRF rank."""
    conn = get_connection()
    cursor = conn.cursor()
    
    if location:
        cursor.execute('''
            SELECT * FROM colleges 
            WHERE nirf_rank IS NOT NULL AND location LIKE ?
            ORDER BY nirf_rank ASC
            LIMIT ?
        ''', (f'%{location}%', limit))
    else:
        cursor.execute('''
            SELECT * FROM colleges 
            WHERE nirf_rank IS NOT NULL
            ORDER BY nirf_rank ASC
            LIMIT ?
        ''', (limit,))
    
    rows = cursor.fetchall()
    conn.close()

    columns = ['id', 'name', 'location', 'college_type', 'established_year',
               'nirf_rank', 'rating', 'total_students', 'courses_offered',
               'fee_range', 'url']
    return [dict(zip(columns, row)) for row in rows]


if __name__ == "__main__":
    setup_database()
