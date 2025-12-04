import os
import time
import signal
import hashlib
from datetime import datetime, timedelta, timezone
from dotenv import load_dotenv
from LogsProvider import LogsProvider
from Ingestion import ingest_logs


class LogScheduler:
    def __init__(self, loki_query: str, interval_seconds: int = 60, lookback_buffer_seconds: int = 10):
        """
        Initialize the scheduler with Loki query and interval.
        
        Args:
            loki_query: The Loki query to fetch logs
            interval_seconds: How often to fetch logs (default: 60 seconds)
            lookback_buffer_seconds: Extra seconds to look back for deduplication overlap (default: 10)
        """
        load_dotenv()
        self.logs_provider = LogsProvider(
            os.getenv("LOKI_API_KEY"), 
            os.getenv("LOKI_URL")
        )
        self.loki_query = loki_query
        self.interval_seconds = interval_seconds
        self.lookback_buffer_seconds = lookback_buffer_seconds
        self.last_fetch_time_file = "last_sync_time.txt"
        self.last_fetch_time = self._load_last_fetch_time()
        self.running = False
        
        # Deduplication: track ingested log hashes
        self.seen_log_hashes = set()
        self.max_seen_hashes = 10000  # Limit memory usage

    def _load_last_fetch_time(self):
        """Load the last fetch time from file system."""
        try:
            if os.path.exists(self.last_fetch_time_file):
                with open(self.last_fetch_time_file, 'r') as f:
                    timestamp_str = f.read().strip()
                    if timestamp_str:
                        last_time = datetime.fromisoformat(timestamp_str)
                        # Ensure timezone awareness
                        if last_time.tzinfo is None:
                            last_time = last_time.replace(tzinfo=timezone.utc)
                        print(f"Loaded last sync time from file: {last_time.isoformat()}")
                        return last_time
        except Exception as e:
            print(f"Error loading last fetch time from file: {e}")
        return None

    def _save_last_fetch_time(self):
        """Save the last fetch time to file system."""
        try:
            if self.last_fetch_time:
                with open(self.last_fetch_time_file, 'w') as f:
                    f.write(self.last_fetch_time.isoformat())
        except Exception as e:
            print(f"Error saving last fetch time to file: {e}")

    def _compute_log_hash(self, log: dict) -> str:
        """Compute a unique hash for a log entry to detect duplicates."""
        h = hashlib.sha256()
        
        # Handle both dict and string types for robustness
        if isinstance(log, str):
            content = log
        else:
            content = f"{log.get('timestamp', '')}{log.get('message', '')}{log.get('level', '')}"
        
        h.update(content.encode('utf-8'))
        return h.hexdigest()

    def _deduplicate_logs(self, logs: list) -> list:
        """Remove logs that have already been ingested."""
        unique_logs = []
        for log in logs:
            log_hash = self._compute_log_hash(log)
            if log_hash not in self.seen_log_hashes:
                unique_logs.append(log)
                self.seen_log_hashes.add(log_hash)
        
        # Prune old hashes if exceeding limit
        if len(self.seen_log_hashes) > self.max_seen_hashes:
            hashes_list = list(self.seen_log_hashes)
            self.seen_log_hashes = set(hashes_list[-(self.max_seen_hashes // 2):])
            print(f"Pruned seen hashes from {len(hashes_list)} to {len(self.seen_log_hashes)}")
        
        return unique_logs

    def fetch_and_ingest(self):
        """Fetch logs from Loki and ingest them into Pinecone."""
        try:
            current_time = datetime.now(timezone.utc)
            print(f"\n[{current_time.isoformat()}] Starting log fetch and ingestion...")
            
            state = {"query": self.loki_query}
            
            # Calculate time window
            end_time = current_time
            if self.last_fetch_time:
                start_time = self.last_fetch_time - timedelta(seconds=self.lookback_buffer_seconds)
                print(f"Fetching logs from {start_time.isoformat()} to {end_time.isoformat()}")
            else:
                start_time = end_time - timedelta(hours=1)
                print("First run: fetching logs from last hour")
            
            # Fetch logs from Loki with time window
            self.logs_provider.get_logs(state, start_time=start_time, end_time=end_time, limit=1000)
            
            if not state.get("logs"):
                print("No logs fetched from Loki")
                self.last_fetch_time = current_time
                self._save_last_fetch_time()
                return
            
            print(f"Fetched {len(state['logs'])} logs from Loki")
            
            # Normalize logs
            self.logs_provider.normalize_logs(state)
            
            if not state.get("clean_logs"):
                print("No logs after normalization")
                self.last_fetch_time = current_time
                self._save_last_fetch_time()
                return
            
            # Deduplicate logs
            original_count = len(state["clean_logs"])
            unique_logs = self._deduplicate_logs(state["clean_logs"])
            duplicates_removed = original_count - len(unique_logs)
            
            if duplicates_removed > 0:
                print(f"Removed {duplicates_removed} duplicate logs")
            
            if not unique_logs:
                print("All logs were duplicates, skipping ingestion")
                self.last_fetch_time = current_time
                self._save_last_fetch_time()
                return
            
            # Ingest into Pinecone
            result = ingest_logs(unique_logs)
            
            if result:
                print(f"Successfully ingested {result['indexed']} documents into Pinecone")
            
            self.last_fetch_time = current_time
            self._save_last_fetch_time()
            
        except Exception as e:
            print(f"Error during fetch and ingest: {e}")
            import traceback
            traceback.print_exc()

    def start(self):
        """Start the scheduler loop."""
        self.running = True
        print(f"Starting log scheduler with {self.interval_seconds}s interval")
        print(f"Loki query: {self.loki_query}")
        print("-" * 50)
        
        # Register signal handlers for graceful shutdown
        signal.signal(signal.SIGINT, self._signal_handler)
        signal.signal(signal.SIGTERM, self._signal_handler)
        
        # Run immediately on start
        self.fetch_and_ingest()
        
        while self.running:
            try:
                print(f"\nWaiting {self.interval_seconds} seconds until next fetch...")
                
                # Sleep in 1-second intervals to respond quickly to stop signals
                for i in range(self.interval_seconds):
                    if not self.running:
                        break
                    time.sleep(1)
                
                if self.running:
                    self.fetch_and_ingest()
                    
            except KeyboardInterrupt:
                print("\nKeyboard interrupt received")
                self.stop()
                break
            except Exception as e:
                print(f"Error in scheduler loop: {e}")
                if not self.running:
                    break

    def _signal_handler(self, signum, frame):
        """Handle shutdown signals gracefully."""
        print(f"\nReceived signal {signum}, stopping scheduler...")
        self.stop()

    def stop(self):
        """Stop the scheduler."""
        self.running = False
        print("Scheduler stopped")


def main():
    load_dotenv()
    
    # Configure your Loki query here
    loki_query = '{namespace="dev-group2", app="cloud-radius", container=~"cloud-radius|gorad"}'
    
    # Create scheduler with 1 minute (60 seconds) interval
    scheduler = LogScheduler(
        loki_query=loki_query,
        interval_seconds=60,  # 1 minute
        lookback_buffer_seconds=10  # 10 second overlap for safety
    )
    
    # Start the scheduler
    scheduler.start()


if __name__ == "__main__":
    main()
