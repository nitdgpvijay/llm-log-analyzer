from langchain_pinecone import PineconeVectorStore
from Prompt import get_rca_prompt, get_auth_prompt, get_client_state_prompt
from langchain_core.prompts import PromptTemplate
from llm import get_llm
from Embedding import getEmbeddings
from dotenv import load_dotenv
from operator import itemgetter
from datetime import datetime, timedelta, timezone
import os
import re


def format_docs(docs):
    return "\n\n".join(doc.page_content for doc in docs)


def extract_mac_address(query: str) -> str | None:
    """Extract MAC address from query string (supports multiple formats)."""
    # Common MAC address patterns:
    # XX:XX:XX:XX:XX:XX, XX-XX-XX-XX-XX-XX, XXXXXXXXXXXX
    patterns = [
        r'([0-9A-Fa-f]{2}[:-]){5}[0-9A-Fa-f]{2}',  # XX:XX:XX:XX:XX:XX or XX-XX-XX-XX-XX-XX
        r'[0-9A-Fa-f]{12}',  # XXXXXXXXXXXX
    ]
    for pattern in patterns:
        match = re.search(pattern, query)
        if match:
            return match.group(0)
    return None


def extract_time_range(query: str) -> dict | None:
    """
    Extract time range from query (e.g., 'last hour', 'last 30 minutes').
    
    Returns:
        Dictionary with 'cutoff_time' and 'description', or None if no time range found
    """
    query_lower = query.lower()
    current_time = datetime.now(timezone.utc)
    
    # Pattern: "last X hour(s)"
    match = re.search(r'last\s+(\d+)\s+hours?', query_lower)
    if match:
        hours = int(match.group(1))
        cutoff = current_time - timedelta(hours=hours)
        return {
            'cutoff_time': cutoff,
            'description': f'last {hours} hour{"s" if hours > 1 else ""}',
            'current_time': current_time
        }
    
    # Pattern: "last X minute(s)"
    match = re.search(r'last\s+(\d+)\s+minutes?', query_lower)
    if match:
        minutes = int(match.group(1))
        cutoff = current_time - timedelta(minutes=minutes)
        return {
            'cutoff_time': cutoff,
            'description': f'last {minutes} minute{"s" if minutes > 1 else ""}',
            'current_time': current_time
        }
    
    # Pattern: "last X day(s)"
    match = re.search(r'last\s+(\d+)\s+days?', query_lower)
    if match:
        days = int(match.group(1))
        cutoff = current_time - timedelta(days=days)
        return {
            'cutoff_time': cutoff,
            'description': f'last {days} day{"s" if days > 1 else ""}',
            'current_time': current_time
        }
    
    # Pattern: just "last hour" (default to 1)
    if 'last hour' in query_lower or 'past hour' in query_lower:
        cutoff = current_time - timedelta(hours=1)
        return {
            'cutoff_time': cutoff,
            'description': 'last hour',
            'current_time': current_time
        }
    
    return None


def detect_query_type(query: str) -> str:
    """Detect the type of query based on keywords."""
    query_lower = query.lower()
    
    # Check for MAC address presence
    if extract_mac_address(query):
        if any(kw in query_lower for kw in ['state', 'status', 'client']):
            return 'client_state'
    
    # Check for authentication related queries
    auth_keywords = ['authentication', 'authenticate', 'auth', 'login', 'access-accept', 
                     'access-reject', 'successful', 'failed', 'radius']
    if any(kw in query_lower for kw in auth_keywords):
        return 'authentication'
    
    return 'general'


def get_vector_store():
    """Get the Pinecone vector store instance."""
    return PineconeVectorStore(
        index_name=os.getenv("PINECONE_INDEX_NAME"),
        embedding=getEmbeddings(),
        namespace=os.getenv("PINECONE_NAMESPACE"),
        text_key="text",
    )


def get_chain(query_type: str = 'general', k: int = 10):
    """
    Get a chain configured for the specified query type.
    
    Args:
        query_type: 'general', 'authentication', or 'client_state'
        k: Number of documents to retrieve
    """
    vector_store = get_vector_store()
    retriever = vector_store.as_retriever(search_kwargs={"k": k})
    
    # Select prompt based on query type
    if query_type == 'authentication':
        prompt_template = PromptTemplate.from_template(get_auth_prompt())
    elif query_type == 'client_state':
        prompt_template = PromptTemplate.from_template(get_client_state_prompt())
    else:
        prompt_template = PromptTemplate.from_template(get_rca_prompt())
    
    # Build chain based on query type
    if query_type == 'client_state':
        # For client state, we include MAC address in the context
        chain = (
            {
                "context": itemgetter("query") | retriever | format_docs,
                "query": itemgetter("query"),
                "mac_address": itemgetter("mac_address")
            }
            | prompt_template
            | get_llm()
        )
    else:
        chain = (
            {
                "context": itemgetter("query") | retriever | format_docs,
                "query": itemgetter("query")
            }
            | prompt_template
            | get_llm()
        )
    return chain


def query_logs(query: str, k: int = 10) -> str:
    """
    Main entry point for querying logs with automatic query type detection.
    
    Args:
        query: The user's query string
        k: Number of documents to retrieve
    
    Returns:
        The LLM's response content
    """
    query_type = detect_query_type(query)
    
    # Extract time range if present
    time_range = extract_time_range(query)
    
    # Increase k if time filtering is needed (we'll retrieve more and let LLM filter)
    retrieval_k = k * 3 if time_range else k
    
    chain = get_chain(query_type=query_type, k=retrieval_k)
    
    # Prepare input based on query type
    enhanced_query = query
    
    # Add time context to help LLM understand the time filtering requirement
    if time_range:
        current_time_str = time_range['current_time'].strftime('%Y-%m-%dT%H:%M:%S')
        cutoff_time_str = time_range['cutoff_time'].strftime('%Y-%m-%dT%H:%M:%S')
        enhanced_query = f"{query}\n\nIMPORTANT: Current time is {current_time_str}. Only consider logs from {time_range['description']} (after {cutoff_time_str})."
    
    input_data = {"query": enhanced_query}
    
    if query_type == 'client_state':
        mac_address = extract_mac_address(query)
        input_data["mac_address"] = mac_address or "Not specified"
        # Enhance query for better retrieval
        input_data["query"] = f"{enhanced_query} MAC {mac_address}"
    
    print('Calling chain with input data: ', input_data['query'])
    result = chain.invoke(input_data)
    return result.content


def main():
    load_dotenv()
    
    # Example queries
    queries = [
        "Find all successful authentication",
        "Get client state for MAC address AA:BB:CC:DD:EE:FF",
        "What is the most common error in the logs?",
        "Show failed authentication attempts in the last hour",
    ]
    
    for query in queries:
        print(f"\n{'='*60}")
        print(f"Query: {query}")
        print(f"Detected Type: {detect_query_type(query)}")
        print(f"{'='*60}")
        result = query_logs(query)
        print(result)


if __name__ == "__main__":
    main()