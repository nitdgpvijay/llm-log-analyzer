import json
from datetime import datetime, timedelta, timezone
from typing import Optional
from opensearchpy import OpenSearch


class ElasticsearchLogsProvider:
    """Provider for fetching RADIUS transaction logs from OpenSearch."""

    def __init__(
        self,
        host: str,
        port: int = 9200,
        username: Optional[str] = None,
        password: Optional[str] = None,
        use_ssl: bool = True,
        verify_certs: bool = True,
        ssl_show_warn: bool = True,
    ):
        """
        Initialize OpenSearch connection.

        Args:
            host: OpenSearch host (e.g., 'search-domain.region.es.amazonaws.com')
            port: Port number (default: 9200)
            username: Username for authentication
            password: Password for authentication
            use_ssl: Whether to use SSL (default: True)
            verify_certs: Whether to verify SSL certificates (default: True)
            ssl_show_warn: Whether to show SSL warnings (default: True)
        """
        if not host:
            raise ValueError("OpenSearch host is required. Set OPENSEARCH_HOST environment variable.")

        auth = (username, password) if username and password else None

        self.client = OpenSearch(
            hosts=[{"host": host, "port": port}],
            http_auth=auth,
            use_ssl=use_ssl,
            verify_certs=verify_certs,
            ssl_show_warn=ssl_show_warn,
        )

        self._verify_connection()

    def _verify_connection(self):
        """Verify the OpenSearch connection is working."""
        try:
            info = self.client.info()
            print(f"Connected to OpenSearch cluster: {info.get('cluster_name', 'unknown')}")
        except Exception as e:
            print(f"Failed to connect to OpenSearch: {e}")
            raise

    def get_logs(
        self,
        state: dict,
        start_time: Optional[datetime] = None,
        end_time: Optional[datetime] = None,
        limit: int = 1000,
    ):
        """
        Fetch RADIUS transaction logs from OpenSearch.

        Args:
            state: Dictionary containing:
                - index: OpenSearch index pattern (default: 'dev-group2-cloud-radius*')
                - query: Optional query dict or Lucene query string
                - timestamp_field: Field name for timestamp (default: 'authTime')
            start_time: Optional start time for the query window (defaults to 1 hour ago)
            end_time: Optional end time for the query window (defaults to now)
            limit: Maximum number of logs to fetch (default: 1000)
        """
        index = state.get("index", "dev-group2-cloud-radius*")
        timestamp_field = state.get("timestamp_field", "authTime")
        custom_query = state.get("query")

        # Use provided times or default to last 24 hours
        if end_time is None:
            end_time = datetime.now(timezone.utc)
        if start_time is None:
            start_time = end_time - timedelta(hours=24)

        # Ensure times are timezone-aware
        if start_time.tzinfo is None:
            start_time = start_time.replace(tzinfo=timezone.utc)
        if end_time.tzinfo is None:
            end_time = end_time.replace(tzinfo=timezone.utc)

        # Convert to epoch milliseconds for authTime field
        start_ms = int(start_time.timestamp() * 1000)
        end_ms = int(end_time.timestamp() * 1000)

        # Build the query
        must_clauses = [
            {
                "range": {
                    timestamp_field: {
                        "gte": start_ms,
                        "lte": end_ms,
                    }
                }
            }
        ]

        # Add custom query if provided
        if custom_query:
            if isinstance(custom_query, str) and custom_query != "*":
                must_clauses.append({"query_string": {"query": custom_query}})
            elif isinstance(custom_query, dict):
                must_clauses.append(custom_query)

        query_body = {
            "query": {"bool": {"must": must_clauses}},
            "size": limit,
            "sort": [{timestamp_field: {"order": "desc"}}],
        }

        print(f"Fetching logs from index '{index}'")
        print(f"Time range: {start_time.isoformat()} to {end_time.isoformat()}")

        try:
            response = self.client.search(index=index, body=query_body)

            hits = response.get("hits", {}).get("hits", [])
            logs = []

            for hit in hits:
                source = hit.get("_source", {})
                logs.append(
                    {
                        "id": hit.get("_id"),
                        "index": hit.get("_index"),
                        "source": source,
                    }
                )

            state["logs"] = logs
            print(f"Fetched {len(logs)} logs from OpenSearch")

        except Exception as e:
            print(f"Failed to fetch logs from OpenSearch: {e}")
            state["logs"] = []
            return None

    def normalize_logs(self, state: dict):
        """
        Normalize RADIUS transaction logs for ingestion into Pinecone.

        Extracts key fields from the transaction log format and creates
        a meaningful message for vector search.

        Args:
            state: Dictionary containing 'logs' list from get_logs()
        """
        if "logs" not in state:
            print("No logs to normalize")
            return state

        cleaned = []

        for log in state["logs"]:
            source = log.get("source", {})

            # Extract timestamp from authTime (epoch milliseconds)
            auth_time_ms = source.get("authTime")
            if auth_time_ms:
                timestamp = datetime.fromtimestamp(auth_time_ms / 1000, tz=timezone.utc).isoformat()
            else:
                timestamp = ""

            # Extract status as the log level
            status = source.get("status", "unknown").lower()

            # Parse authLogs JSON string for detailed information
            auth_logs_str = source.get("authLogs", "{}")
            try:
                auth_logs = json.loads(auth_logs_str) if auth_logs_str else {}
            except json.JSONDecodeError:
                auth_logs = {}

            # Extract reject reason if present
            request_summary = auth_logs.get("Request Details Summary", {})
            reject_reason = request_summary.get("rejectReason", "")

            # Build a comprehensive message for vector search
            message_parts = [
                f"RADIUS Auth Transaction - Status: {source.get('status', 'unknown')}",
                f"User: {source.get('userName', 'unknown')}",
                f"MAC: {source.get('mac', 'unknown')}",
                f"EAP Method: {source.get('eapMethod', 'unknown')}",
                f"AP/Switch: {source.get('apSwitch', 'unknown')}",
                f"Latency: {source.get('txnLat', 'unknown')}ms",
            ]

            if reject_reason:
                message_parts.append(f"Reject Reason: {reject_reason}")

            # Add site info if available
            geo_scope = source.get("geoScope", {})
            if geo_scope:
                message_parts.append(f"Site: {geo_scope.get('siteId', 'unknown')}")

            # Add input RADIUS attributes summary
            input_attrs = auth_logs.get("Input Radius Attributes", {})
            if input_attrs:
                attrs_summary = ", ".join([f"{k}={v}" for k, v in list(input_attrs.items())[:5]])
                message_parts.append(f"Input Attrs: {attrs_summary}")

            message = " | ".join(message_parts)

            # Module/service name
            module = "cloud-radius"

            cleaned.append(
                {
                    "timestamp": timestamp,
                    "level": status,  # Use status as level (e.g., timeout, success, reject)
                    "module": module,
                    "message": message,
                    "es_id": log.get("id"),
                    "es_index": log.get("index"),
                    # Additional metadata for filtering
                    "user_name": source.get("userName"),
                    "mac": source.get("mac"),
                    "status": source.get("status"),
                    "eap_method": source.get("eapMethod"),
                    "reject_reason": reject_reason,
                }
            )

        state["clean_logs"] = cleaned
        print(f"Normalized {len(cleaned)} logs")

    def _extract_nested_field(self, source: dict, field_path: str):
        """
        Extract a nested field from a dictionary using dot notation.

        Args:
            source: The source dictionary
            field_path: Dot-separated field path (e.g., 'log.level')

        Returns:
            The field value or None if not found
        """
        parts = field_path.split(".")
        value = source

        for part in parts:
            if isinstance(value, dict):
                value = value.get(part)
            else:
                return None

        return value

    def close(self):
        """Close the OpenSearch connection."""
        self.client.close()


def main():
    """Example usage of ElasticsearchLogsProvider."""
    import os
    from dotenv import load_dotenv

    load_dotenv()

    provider = ElasticsearchLogsProvider(
        host=os.getenv("OPENSEARCH_HOST"),
        port=int(os.getenv("OPENSEARCH_PORT", "443")),
        username=os.getenv("OPENSEARCH_USERNAME"),
        password=os.getenv("OPENSEARCH_PASSWORD"),
        use_ssl=os.getenv("OPENSEARCH_USE_SSL", "true").lower() == "true",
        verify_certs=os.getenv("OPENSEARCH_VERIFY_CERTS", "true").lower() == "true",
    )

    state = {
        "index": os.getenv("OPENSEARCH_INDEX", "dev-group2-cloud-radius*"),
        "query": os.getenv("OPENSEARCH_QUERY", "*"),
        "timestamp_field": "authTime",
    }

    provider.get_logs(state, limit=100)
    provider.normalize_logs(state)

    print(f"\nFound {len(state.get('clean_logs', []))} logs")
    for log in state.get("clean_logs", [])[:5]:
        print(f"  [{log['level']}] {log['message'][:150]}...")

    provider.close()


if __name__ == "__main__":
    main()
