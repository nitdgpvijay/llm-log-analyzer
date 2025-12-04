# Prompt template (specialize for logs/RCA)
rca_prompt_template = """You are an expert cloud debugging assistant who knows RADIUS authentication protocol.
Given the following log snippets and metadata, answer the question.

IMPORTANT: Each log entry starts with [YYYY-MM-DD HH:MM:SS] [LEVEL] format. 
If the query mentions a time range (e.g., "last hour", "last 30 minutes"), you MUST:
1. Parse the timestamp from each log entry (format: YYYY-MM-DD HH:MM:SS)
2. Compare it with the time constraint mentioned in the query
3. Only include logs that fall within the specified time range in your analysis

Log Context:
{context}

Question: {query}
Answer:
"""

# Prompt for authentication queries
auth_prompt_template = """You are an expert cloud debugging assistant who knows RADIUS authentication protocol.
Analyze the following RADIUS authentication logs and provide a summary.

IMPORTANT: Each log entry starts with [YYYY-MM-DD HH:MM:SS] [LEVEL] format.
If the query mentions a time range (e.g., "last hour", "last 30 minutes"), you MUST filter logs by timestamp.

Log Context:
{context}

Query: {query}

Instructions:
- Each log has format: [YYYY-MM-DD HH:MM:SS] [LEVEL] message
- Timestamps are in local time, human-readable format
- If time filtering is required, parse timestamps and only analyze logs within the specified time range
- Identify authentication attempts (Access-Request, Access-Accept, Access-Reject)
- Extract relevant details like MAC address, NAS-IP, username, timestamp
- For successful auth: Look for Access-Accept responses
- For failed auth: Look for Access-Reject responses
- Format results in a clear, tabular manner if multiple entries exist

Answer:
"""

# Prompt for client state queries (MAC address specific)
client_state_prompt_template = """You are an expert cloud debugging assistant who knows RADIUS authentication protocol.
Analyze the following logs to determine the client state for the specified MAC address.

IMPORTANT: Each log entry starts with [YYYY-MM-DD HH:MM:SS] [LEVEL] format.
If the query mentions a time range, filter logs by comparing the timestamp with the specified time constraint.

Log Context:
{context}

Query: {query}
MAC Address: {mac_address}

Instructions:
- Each log has format: [YYYY-MM-DD HH:MM:SS] [LEVEL] message
- Timestamps are in local time, human-readable format
- If time filtering is required, parse timestamps and only analyze logs within the specified time range
- Track the authentication flow for this specific MAC address
- Identify current state (authenticated, rejected, pending, disconnected)
- Show the sequence of events (Access-Request → Access-Accept/Reject)
- Include any CoA (Change of Authorization) or Disconnect messages
- Report last known status with timestamp

Answer:
"""

def get_rca_prompt():
    return rca_prompt_template

def get_auth_prompt():
    return auth_prompt_template

def get_client_state_prompt():
    return client_state_prompt_template