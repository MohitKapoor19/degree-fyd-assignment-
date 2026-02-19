import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

# Paths
BASE_DIR = Path(__file__).parent.parent
DATA_DIR = BASE_DIR / "data"
DATA_DIR.mkdir(exist_ok=True)

# Data files
JSONL_FILE = BASE_DIR / "degreefyd_data.jsonl"
SQLITE_DB = DATA_DIR / "degreefyd.db"
CHROMA_DIR = DATA_DIR / "chroma_db"

# Groq API
GROQ_API_KEY = os.getenv("GROQ_API_KEY")
GROQ_MODEL = "compound-beta"  # Using compound model for web search capability
GROQ_ROUTER_MODEL = "llama-3.1-8b-instant"  # Fast model for routing

# Embeddings
EMBEDDING_MODEL = "sentence-transformers/all-MiniLM-L6-v2"

# ChromaDB
CHROMA_COLLECTION = "degreefyd_docs"

# RAG Settings
CHUNK_SIZE = 1000
CHUNK_OVERLAP = 200
TOP_K_RESULTS = 5

# Query Categories
CATEGORIES = [
    "COLLEGE",
    "EXAM", 
    "COMPARISON",
    "PREDICTOR",
    "TOP_COLLEGES",
    "GENERAL"
]

# Web Search Settings
DEFAULT_WEB_SEARCH = False
