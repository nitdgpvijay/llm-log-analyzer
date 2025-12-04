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


def convert_nanosecond_timestamps(text: str) -> str:
    """
    Convert nanosecond Unix timestamps in logs to human-readable local time.
    
    Looks for patterns like [1764871955816] and converts them to seconds and then to local time.
    [2025-12-04 10:30:55] format.
    """
    def replace_timestamp(match):
        try:
            nano_timestamp = int(match.group(1))
            # Convert nanoseconds to seconds
            seconds = nano_timestamp / 1_000 # convert to seconds
            # Convert to local datetime
            dt = datetime.fromtimestamp(seconds)
            # Format as readable string
            return f"[{dt.strftime('%Y-%m-%d %H:%M:%S')}]"
        except (ValueError, OSError):
            # If conversion fails, return original
            return match.group(0)
    
    # Pattern to match timestamps in brackets that are 18-19 digits (nanoseconds)
    pattern = r'\[(\d{18,19})\]'
    return re.sub(pattern, replace_timestamp, text)


def format_docs(docs):
    """
    Format retrieved documents into a single string with human-readable timestamps.
    Converts nanosecond timestamps to local time format.
    """
    formatted_content = "\n\n".join(doc.page_content for doc in docs)
    # Convert nanosecond timestamps to readable format
    return convert_nanosecond_timestamps(formatted_content)


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


def augment_query(query: str, query_type: str) -> str:
    """
    Augment query with domain-specific keywords to improve retrieval.
    
    Args:
        query: Original user query
        query_type: Detected query type ('general', 'authentication', 'client_state')
    
    Returns:
        Augmented query with additional relevant keywords
    """
    query_lower = query.lower()
    augmented_parts = [query]
    
    if query_type == 'authentication':
        # Add RADIUS-specific terms for authentication queries
        augmentation_terms = []
        
        # If query mentions successful/failed, add corresponding RADIUS codes
        if any(kw in query_lower for kw in ['successful', 'success', 'accepted']):
            augmentation_terms.append('Access-Accept')
        elif any(kw in query_lower for kw in ['failed', 'failure', 'rejected', 'denied']):
            augmentation_terms.append('Access-Reject')
        else:
            # Generic authentication query - add both
            augmentation_terms.extend(['Access-Accept', 'Access-Reject'])
        
        # Add RADIUS if not already mentioned
        if 'radius' not in query_lower:
            augmentation_terms.append('RADIUS')
        
        if augmentation_terms:
            augmented_parts.append(' '.join(augmentation_terms))
    
    elif query_type == 'client_state':
        # Add client/device related terms
        augmentation_terms = []
        augmentation_terms.append('Could not verify Client Certificate')
        
        if 'state' not in query_lower and 'status' not in query_lower:
            augmentation_terms.append('state status')
        
        if 'client' not in query_lower and 'device' not in query_lower:
            augmentation_terms.append('client device')
        
        if augmentation_terms:
            augmented_parts.append(' '.join(augmentation_terms))
    
    elif query_type == 'general':
        # For general queries, add common log analysis terms
        error_keywords = ['error', 'failure', 'exception', 'critical', 'warning']
        if any(kw in query_lower for kw in error_keywords):
            if 'error' not in query_lower:
                augmented_parts.append('error')
            if 'exception' not in query_lower:
                augmented_parts.append('exception')
    
    # Combine original query with augmentation terms
    augmented = ' '.join(augmented_parts)
    
    # Print augmentation for debugging
    if augmented != query:
        print(f"Query augmented: '{query}' -> '{augmented}'")
    
    return augmented


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
    
    # Augment query with domain-specific keywords for better retrieval
    augmented_query = augment_query(query, query_type)
    
    # Extract time range if present
    time_range = extract_time_range(query)
    
    # Increase k if time filtering is needed (we'll retrieve more and let LLM filter)
    retrieval_k = k * 3 if time_range else k
    
    chain = get_chain(query_type=query_type, k=retrieval_k)
    
    # Prepare input based on query type
    enhanced_query = augmented_query
    
    # Add time context to help LLM understand the time filtering requirement
    if time_range:
        current_time_str = time_range['current_time'].strftime('%Y-%m-%dT%H:%M:%S')
        cutoff_time_str = time_range['cutoff_time'].strftime('%Y-%m-%dT%H:%M:%S')
        enhanced_query = f"{augmented_query}\n\nIMPORTANT: Current time is {current_time_str}. Only consider logs from {time_range['description']} (after {cutoff_time_str})."
    
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