import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

from db_setup import setup_database
from vector_store import ingest_documents


def main():
    print("=" * 60)
    print("DegreeFYD RAG - Data Ingestion Pipeline")
    print("=" * 60)

    print("\n[Step 1/2] Setting up SQLite database...")
    setup_database()

    print("\n[Step 2/2] Ingesting documents into ChromaDB...")
    ingest_documents()

    print("\n" + "=" * 60)
    print("Ingestion complete! You can now run the API and UI.")
    print("=" * 60)


if __name__ == "__main__":
    main()
