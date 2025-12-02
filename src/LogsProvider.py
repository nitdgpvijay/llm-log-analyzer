import requests
import re
import json

from datetime import datetime, timedelta, timezone
class LogsProvider:
    def __init__(self, api_key: str, loki_url: str):
        self.api_key = api_key
        self.loki_url = loki_url.rstrip("/")

    def get_logs(self, state: dict):
        """
        Fetch logs from Loki given a state dictionary.
        Returns logs as a string.
        """
        headers = {
            "Authorization": f"Bearer {self.api_key}"
        }
        params = {
            "query": state.get("query", ""),
            "limit": 10,  # You may configure limit as needed
            "direction": "BACKWARD"
        }

        # Calculate end time (now) and start time (one hour ago) in RFC3339Nano/ISO format
        end_time = datetime.now(timezone.utc)
        start_time = end_time - timedelta(hours=1)
        end_str = self.to_nanos(end_time)
        start_str = self.to_nanos(start_time)

        url = f"{self.loki_url}/loki/api/v1/query_range"
        # Insert start and end time to params for Loki query
        params["start"] = str(start_str)
        params["end"] = str(end_str)
        print(f"Fetching logs from {url} with params {params}")
        try:
            response = requests.get(url, headers=headers, params=params, timeout=10)
            response.raise_for_status()
            data = response.json()
            # Extract logs from the response
            logs = []
            for stream in data.get("data", {}).get("result", []):
                labels = stream.get("stream", {})
                for ts, line in stream.get("values", []):
                    logs.append({"ts": ts, "line": line, "labels": labels})

            state["logs"] = logs
            #print("Fetched logs:", logs)

        except requests.RequestException as e:
            print(f"Failed to fetch logs: {e}")
            return None


    def normalize_logs(self, state: dict):
        """
        Normalize logs by replacing timestamps and GUIDs with placeholders.
        """
        if "logs" not in state:
            print("No logs to normalize")
            return state
        logs = [l["line"] for l in state["logs"]]
        cleaned = []
        for line in logs:
             # Try to parse as JSON; if it matches parseable JSON structure, extract relevant fields
            try:
                log_data = json.loads(line)
                filtered = {
                    "level": log_data.get("level"),
                    "module": log_data.get("module"),
                    "message": log_data.get("message"),
                    "timestamp": log_data.get("timestamp")
                }
                cleaned.append(filtered)
            except Exception:
                # If not JSON, just append the raw line as fallback
                cleaned.append(line)
        state["clean_logs"] = cleaned

    def to_nanos(self, dt: datetime) -> int:
        """Convert datetime to Unix nanoseconds."""
        return int(dt.timestamp() * 1_000_000_000)