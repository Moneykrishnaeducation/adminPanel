import threading
import time
import logging
from django.core.management import call_command

logger = logging.getLogger(__name__)

class CommissionSyncThread:
    def __init__(self, interval_seconds=0):  # Default: 0 -> near real-time (uses tiny sleep to avoid CPU spin)
        # interval_seconds <= 0 means run as frequently as possible with a tiny sleep
        self.interval = interval_seconds
        self.thread = None
        self.running = False
        
    def start(self):
        if not self.running:
            self.running = True
            self.thread = threading.Thread(target=self._run_sync, daemon=True)
            self.thread.start()
    
    def stop(self):
        self.running = False
        if self.thread:
            self.thread.join()
    
    def _run_sync(self):
        while self.running:
            try:
                call_command('sync_commissions_from_mt5')
            except Exception as e:
                logger.error(f"Commission sync failed: {e}")
            # If interval is <= 0, use a very small sleep to avoid busy CPU spin while keeping near real-time
            try:
                sleep_duration = float(self.interval)
            except Exception:
                sleep_duration = 0

            if sleep_duration <= 0:
                time.sleep(0.025)  # 25ms = LIGHTNING FAST ⚡
            else:
                time.sleep(sleep_duration)

# Global instance
commission_sync_thread = CommissionSyncThread()
