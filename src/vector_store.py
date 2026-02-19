import chromadb
from chromadb.utils import embedding_functions
from typing import List, Dict, Optional
from pathlib import Path

from config import CHROMA_DIR, CHROMA_COLLECTION, EMBEDDING_MODEL, JSONL_FILE, CHUNK_SIZE, CHUNK_OVERLAP
from data_extractor import load_jsonl

# ── Singletons — created once, reused across all requests ─────────────────────
_embedding_fn = None
_chroma_client = None
_collection = None


def get_embedding_function():
    """Get cached embedding function (loaded once)."""
    global _embedding_fn
    if _embedding_fn is None:
        _embedding_fn = embedding_functions.SentenceTransformerEmbeddingFunction(
            model_name=EMBEDDING_MODEL
        )
    return _embedding_fn


def get_chroma_client():
    """Get cached ChromaDB persistent client."""
    global _chroma_client
    if _chroma_client is None:
        CHROMA_DIR.mkdir(parents=True, exist_ok=True)
        _chroma_client = chromadb.PersistentClient(path=str(CHROMA_DIR))
    return _chroma_client


def get_or_create_collection():
    """Get cached collection (created once, reused)."""
    global _collection
    if _collection is None:
        client = get_chroma_client()
        embedding_fn = get_embedding_function()
        _collection = client.get_or_create_collection(
            name=CHROMA_COLLECTION,
            embedding_function=embedding_fn,
            metadata={"hnsw:space": "cosine"}
        )
    return _collection


def chunk_text(text: str, chunk_size: int = CHUNK_SIZE, overlap: int = CHUNK_OVERLAP) -> List[str]:
    """Split text into overlapping chunks."""
    if len(text) <= chunk_size:
        return [text]
    
    chunks = []
    start = 0
    
    while start < len(text):
        end = start + chunk_size
        
        # Try to break at sentence boundary
        if end < len(text):
            # Look for sentence ending
            for sep in ['. ', '.\n', '? ', '!\n']:
                last_sep = text[start:end].rfind(sep)
                if last_sep > chunk_size // 2:
                    end = start + last_sep + len(sep)
                    break
        
        chunk = text[start:end].strip()
        if chunk:
            chunks.append(chunk)
        
        start = end - overlap
    
    return chunks


def extract_college_names_from_content(content: str) -> List[str]:
    """Extract college names mentioned in content for metadata."""
    import re
    
    # Common patterns for college names
    patterns = [
        r"Compare\s+(.+?)\s+and\s+(.+?)\s+across",
        r"([A-Z][A-Za-z\s]+(?:University|Institute|College|IIM|IIT|NIT)[A-Za-z\s]*)"
    ]
    
    names = []
    for pattern in patterns:
        matches = re.findall(pattern, content)
        for match in matches:
            if isinstance(match, tuple):
                names.extend(match)
            else:
                names.append(match)
    
    # Clean and deduplicate
    cleaned = list(set([n.strip() for n in names if n and len(n) > 3]))
    return cleaned[:5]  # Limit to 5 names


def extract_exam_names_from_content(content: str) -> List[str]:
    """Extract exam names mentioned in content."""
    import re
    
    exam_patterns = [
        r'\b(JEE\s*(?:Main|Advanced)?)\b',
        r'\b(NEET)\b',
        r'\b(CAT)\b',
        r'\b(GATE)\b',
        r'\b(CLAT)\b',
        r'\b(MHT\s*CET)\b',
        r'\b(TS\s*EAMCET)\b',
        r'\b(AP\s*EAMCET)\b',
        r'\b(BITSAT)\b',
        r'\b(VITEEE)\b'
    ]
    
    exams = []
    for pattern in exam_patterns:
        matches = re.findall(pattern, content, re.IGNORECASE)
        exams.extend(matches)
    
    return list(set([e.upper() for e in exams]))


def ingest_documents():
    """Ingest all documents into ChromaDB."""
    print("Loading documents...")
    records = load_jsonl(JSONL_FILE)
    
    collection = get_or_create_collection()
    
    # Check if already ingested
    existing_count = collection.count()
    if existing_count > 0:
        print(f"Collection already has {existing_count} documents. Skipping ingestion.")
        print("To re-ingest, delete the chroma_db folder first.")
        return
    
    print(f"Processing {len(records)} records...")
    
    all_ids = []
    all_documents = []
    all_metadatas = []
    
    for idx, record in enumerate(records):
        content = record.get('content', '')
        url = record.get('url', '')
        doc_type = record.get('type', 'page')
        
        # Chunk the content
        chunks = chunk_text(content)
        
        # Extract metadata
        college_names = extract_college_names_from_content(content)
        exam_names = extract_exam_names_from_content(content)
        
        for chunk_idx, chunk in enumerate(chunks):
            doc_id = f"{idx}_{chunk_idx}"
            
            metadata = {
                'type': doc_type,
                'url': url,
                'chunk_index': chunk_idx,
                'total_chunks': len(chunks),
                'college_names': ','.join(college_names) if college_names else '',
                'exam_names': ','.join(exam_names) if exam_names else ''
            }
            
            all_ids.append(doc_id)
            all_documents.append(chunk)
            all_metadatas.append(metadata)
        
        if (idx + 1) % 1000 == 0:
            print(f"Processed {idx + 1}/{len(records)} records...")
    
    # Batch insert (ChromaDB has a limit of ~5000 per batch)
    batch_size = 5000
    total_docs = len(all_ids)
    
    print(f"Inserting {total_docs} chunks into ChromaDB...")
    
    for i in range(0, total_docs, batch_size):
        end = min(i + batch_size, total_docs)
        collection.add(
            ids=all_ids[i:end],
            documents=all_documents[i:end],
            metadatas=all_metadatas[i:end]
        )
        print(f"Inserted {end}/{total_docs} chunks...")
    
    print(f"Ingestion complete! Total chunks: {collection.count()}")


def search_documents(
    query: str,
    n_results: int = 5,
    doc_type: Optional[str] = None,
    college_name: Optional[str] = None
) -> List[Dict]:
    """Search documents in ChromaDB."""
    collection = get_or_create_collection()
    
    # Build where filter
    where_filter = None
    if doc_type:
        where_filter = {"type": doc_type}
    
    # Search
    results = collection.query(
        query_texts=[query],
        n_results=n_results,
        where=where_filter,
        include=["documents", "metadatas", "distances"]
    )
    
    # Format results
    formatted = []
    if results['documents'] and results['documents'][0]:
        for i, doc in enumerate(results['documents'][0]):
            formatted.append({
                'content': doc,
                'metadata': results['metadatas'][0][i] if results['metadatas'] else {},
                'distance': results['distances'][0][i] if results['distances'] else None
            })
    
    # Filter by college name if specified
    if college_name and formatted:
        college_lower = college_name.lower()
        formatted = [
            r for r in formatted 
            if college_lower in r['content'].lower() or 
               college_lower in r['metadata'].get('college_names', '').lower()
        ]
    
    return formatted


def search_by_type(query: str, doc_type: str, n_results: int = 5) -> List[Dict]:
    """Search documents filtered by type."""
    return search_documents(query, n_results=n_results, doc_type=doc_type)


def search_comparisons(college1: str, college2: str, n_results: int = 3) -> List[Dict]:
    """Search for comparison documents between two colleges."""
    query = f"Compare {college1} and {college2}"
    results = search_documents(query, n_results=n_results, doc_type='comparison')
    
    # Filter to ensure both colleges are mentioned
    filtered = []
    for r in results:
        content_lower = r['content'].lower()
        if college1.lower() in content_lower and college2.lower() in content_lower:
            filtered.append(r)
    
    return filtered if filtered else results


if __name__ == "__main__":
    ingest_documents()
