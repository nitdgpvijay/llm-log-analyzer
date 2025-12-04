import hashlib
import os
from langchain_pinecone import PineconeVectorStore
from Embedding import getEmbeddings
from dotenv import load_dotenv
from LogsProvider import LogsProvider
from langchain_core.documents import Document

def make_point_id(line_text, ts, level, idx):
    """
    Generate a unique ID for a log entry using SHA1 hash.
    
    Args:
        line_text: The log message content
        ts: Timestamp of the log
        level: Log level (e.g., 'info', 'error')
        idx: Index of the log in the batch
        
    Returns:
        Hexadecimal hash string
    """
    h = hashlib.sha1()
    # Use first 200 chars of message + timestamp + level + index for uniqueness
    content = f"{ts}|{level}|{line_text[:200]}|{idx}"
    h.update(content.encode('utf-8'))
    return h.hexdigest()


def ingest_logs(logs):
    """
    Ingest logs into Pinecone vector store.
    
    Args:
        logs: List of normalized log dictionaries with keys: timestamp, level, module, message
        
    Returns:
        Dictionary with 'indexed' count or None on error
    """
    if not logs:
        print("No logs to ingest")
        return {"indexed": 0}
    
    print(f"Preparing {len(logs)} logs for ingestion...")
    
    try:
        # Build documents with metadata and unique IDs
        docs = []
        ids = []
        # Also write the raw normalized logs to a local file for auditing/debugging
        logs_dir = "logs_ingested"
        os.makedirs(logs_dir, exist_ok=True)
        log_file_path = os.path.join(logs_dir, "latest_ingest.jsonl")
        try:
            with open(log_file_path, "w", encoding="utf-8") as f:
                for log in logs:
                    import json
                    f.write(json.dumps(log, ensure_ascii=False) + "\n")
            print(f"Wrote {len(logs)} normalized logs to {log_file_path}")
        except Exception as file_exc:
            print(f"Failed to write logs to local file: {file_exc}")

        # Ingest into Pinecone - no need to pass metadatas separately as they're in docs
        for i, log in enumerate(logs):
            # Create comprehensive metadata
            timestamp = log.get("timestamp", "")
            level = log.get("level", "unknown")
            
            metadata = {
                "timestamp": timestamp,
                "level": level
            }
            
            # Create document with message as content
            message = log.get("message", "")
            if not message:
                continue  # Skip logs with empty messages
            
            # Format content with timestamp and metadata for LLM context
            # This allows LLM to filter by time and understand context
            content = f"[{timestamp}] [{level.upper()}] {message}"
                
            docs.append(Document(page_content=content, metadata=metadata))
            
            # Generate unique ID for deduplication
            ids.append(make_point_id(message, timestamp, level, i))
        
        if not docs:
            print("No valid documents to ingest (all messages were empty)")
            return {"indexed": 0}
        
        print(f"Ingesting {len(docs)} documents into Pinecone...")
        
        # Ingest into Pinecone - no need to pass metadatas separately as they're in docs
        PineconeVectorStore.from_documents(
            documents=docs,
            embedding=getEmbeddings(),
            index_name=os.getenv("PINECONE_INDEX_NAME"),
            ids=ids,
            namespace=os.getenv("PINECONE_NAMESPACE")
        )
        
        print(f"Successfully ingested {len(docs)} documents")
        return {"indexed": len(docs)}
        
    except Exception as e:
        print(f"Error during ingestion: {e}")
        import traceback
        traceback.print_exc()
        return None


def main():
    load_dotenv()
    logs_provider = LogsProvider(os.getenv("LOKI_API_KEY"), os.getenv("LOKI_URL"))
    state = {"query": '{namespace="dev-group2", app="cloud-radius", container=~"cloud-radius|gorad"}'}
    logs_provider.get_logs(state)
    logs_provider.normalize_logs(state)
    result = ingest_logs(state["clean_logs"])
    print(result)

if __name__ == "__main__":
    main()