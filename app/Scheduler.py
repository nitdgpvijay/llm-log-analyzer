import os
import time
from datetime import datetime, timedelta, timezone
from dotenv import load_dotenv
from LogsProvider import LogsProvider
from Ingestion import ingest_logs

class LogScheduler:
    def __init__(self, loki_query: str, interval_seconds: int = 60):
        """
        Initialize the scheduler with Loki query and interval.
        
        Args:
            loki_query: The Loki query to fetch logs
            interval_seconds: How often to fetch logs (default: 60 seconds)
        """
        load_dotenv()
        self.logs_provider = LogsProvider(
            os.getenv("LOKI_API_KEY"), 
            os.getenv("LOKI_URL")
        )
        self.loki_query = loki_query
        self.interval_seconds = interval_seconds
        self.last_fetch_time = None
        self.running = False

    def fetch_and_ingest(self):
        """Fetch logs from Loki and ingest them into Pinecone."""
        try:
            current_time = datetime.now(timezone.utc)
            print(f"\n[{current_time.isoformat()}] Starting log fetch and ingestion...")
            
            state = {"query": self.loki_query}
            
            # Fetch logs from Loki
            self.logs_provider.get_logs(state)
            
            if not state.get("logs"):
                print("No logs fetched from Loki")
                return
            
            print(f"Fetched {len(state['logs'])} logs from Loki")
            
            # Normalize logs
            self.logs_provider.normalize_logs(state)
            
            if not state.get("clean_logs"):
                print("No logs after normalization")
                return
            
            # Ingest into Pinecone
            result = ingest_logs(state["clean_logs"])
            
            if result:
                print(f"Successfully ingested {result['indexed']} documents into Pinecone")
            
            self.last_fetch_time = current_time
            
        except Exception as e:
            print(f"Error during fetch and ingest: {e}")

    def start(self):
        """Start the scheduler loop."""
        self.running = True
        print(f"Starting log scheduler with {self.interval_seconds}s interval")
        print(f"Loki query: {self.loki_query}")
        print("-" * 50)
        
        # Run immediately on start
        self.fetch_and_ingest()
        
        while self.running:
            try:
                print(f"\nWaiting {self.interval_seconds} seconds until next fetch...")
                time.sleep(self.interval_seconds)
                
                if self.running:
                    self.fetch_and_ingest()
                    
            except KeyboardInterrupt:
                print("\nReceived interrupt signal, stopping scheduler...")
                self.stop()
                break

    def stop(self):
        """Stop the scheduler."""
        self.running = False
        print("Scheduler stopped")


def main():
    load_dotenv()
    
    # Configure your Loki query here
    loki_query = '{namespace="dev-group2", app="cloud-radius"}'
    
    # Create scheduler with 1 minute (60 seconds) interval
    scheduler = LogScheduler(
        loki_query=loki_query,
        interval_seconds=60  # 1 minute
    )
    
    # Start the scheduler
    scheduler.start()


if __name__ == "__main__":
    main()

