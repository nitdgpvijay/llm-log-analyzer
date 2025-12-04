import requests
import re
import json
import os
from dotenv import load_dotenv

from datetime import datetime, timedelta, timezone
class LogsProvider:
    def __init__(self, api_key: str, loki_url: str):
        self.api_key = api_key
        self.loki_url = loki_url.rstrip("/")

    def get_logs(self, state: dict, start_time: datetime = None, end_time: datetime = None, limit: int = 100):
        """
        Fetch logs from Loki given a state dictionary.
        
        Args:
            state: Dictionary containing the query and will be updated with logs
            start_time: Optional start time for the query window (defaults to 1 hour ago)
            end_time: Optional end time for the query window (defaults to now)
            limit: Maximum number of logs to fetch (default: 100)
        """
        headers = {
            "Authorization": f"Bearer {self.api_key}"
        }
        params = {
            "query": state.get("query", ""),
            "limit": limit,
            "direction": "BACKWARD"
        }

        # Use provided times or default to last hour
        if end_time is None:
            end_time = datetime.now(timezone.utc)
        if start_time is None:
            start_time = end_time - timedelta(hours=1)
        
        # Ensure times are timezone-aware (convert to UTC if needed)
        if start_time.tzinfo is None:
            start_time = start_time.replace(tzinfo=timezone.utc)
        else:
            start_time = start_time.astimezone(timezone.utc)
            
        if end_time.tzinfo is None:
            end_time = end_time.replace(tzinfo=timezone.utc)
        else:
            end_time = end_time.astimezone(timezone.utc)
            
        # Use Unix timestamps in nanoseconds (Loki's standard format)
        # Round to whole seconds first to avoid precision issues
        start_ns = int(start_time.timestamp()) * 1_000_000_000
        end_ns = int(end_time.timestamp()) * 1_000_000_000

        url = f"{self.loki_url}/loki/api/v1/query_range"
        # Insert start and end time to params for Loki query
        params["start"] = str(start_ns)
        params["end"] = str(end_ns)
        print(f"Fetching logs from {url} with params {params}")
        try:
            response = requests.get(url, headers=headers, params=params, timeout=30)
            print(f"Response status: {response.status_code}")
            if response.status_code != 200:
                print(f"Response body: {response.text}")
            response.raise_for_status()
            data = response.json()
            # Extract logs from the response
            logs = []
            for stream in data.get("data", {}).get("result", []):
                labels = stream.get("stream", {})
                for ts, line in stream.get("values", []):
                    logs.append({"timestamp": ts, "line": line, "labels": labels})

            state["logs"] = logs
            # print("Fetched logs:", logs)

        except requests.RequestException as e:
            print(f"Failed to fetch logs: {e}")
            return None


    def normalize_logs(self, state: dict):
        """
        Normalize logs by parsing JSON structure and extracting relevant fields.
        """
        if "logs" not in state:
            print("No logs to normalize")
            return state
        
        cleaned = []
        for log in state["logs"]:
            # ts is in nanoseconds, convert to milliseconds
            ts = int(int(log["timestamp"]) / 1_000_000)
            line = log["line"]
            
            # Try to parse as JSON; if it matches parseable JSON structure, extract relevant fields
            try:
                log_data = json.loads(line)
                filtered = {
                    "level": log_data.get("level", "unknown"),
                    "message": log_data.get("message", line),  # Fallback to raw line
                    "timestamp": ts
                }
                cleaned.append(filtered)
            except Exception:
                # If not JSON, create a structured log with the raw line as message
                print("Invalid log")

        state["clean_logs"] = cleaned

    def to_nanos(self, dt: datetime) -> int:
        """Convert datetime to Unix nanoseconds."""
        return int(dt.timestamp() * 1_000_000_000)

def main():
    load_dotenv()
    logs_provider = LogsProvider(os.getenv("LOKI_API_KEY"), os.getenv("LOKI_URL"))
    state = {"query": '{namespace="dev-group2", app="cloud-radius", container=~"cloud-radius|gorad"}'}
    logs_provider.get_logs(state)
    logs_provider.normalize_logs(state)
    print(len(state["clean_logs"]))

if __name__ == "__main__":
    main()