"""
Background thread for automatic chat message cleanup
Runs every hour to delete messages older than 24 hours
Similar to monthly_reports_thread.py, no external dependencies needed
"""

import threading
import time
from datetime import timedelta
from django.utils import timezone
import logging

logger = logging.getLogger(__name__)


class ChatCleanupThread:
    """Background thread to automatically cleanup old chat messages every hour"""
    
    def __init__(self):
        self.thread = None
        self.stop_event = threading.Event()
        self.is_running = False
    
    def start(self):
        """Start the background cleanup thread"""
        if self.is_running:
            logger.debug("Chat cleanup thread is already running")
            return
        
        self.stop_event.clear()
        self.is_running = True
        self.thread = threading.Thread(target=self._run_loop, daemon=True)
        self.thread.start()
        logger.info("Chat cleanup thread started - will run every hour")
    
    def stop(self):
        """Stop the background cleanup thread"""
        self.stop_event.set()
        self.is_running = False
        if self.thread:
            self.thread.join(timeout=5)
        logger.info("Chat cleanup thread stopped")
    
    def _run_loop(self):
        """Main loop that runs cleanup every hour"""
        while not self.stop_event.is_set():
            try:
                # Check if it's time to run cleanup (every hour at minute 0)
                now = timezone.now()
                
                # Calculate seconds until the next hour
                seconds_to_next_hour = 3600 - (now.minute * 60 + now.second)
                
                # Log the schedule
                logger.debug(f"Chat cleanup: Next run in {seconds_to_next_hour} seconds (at next hour)")
                
                # Wait until next hour or until stop is signaled
                if self.stop_event.wait(timeout=seconds_to_next_hour):
                    break  # Stop was called
                
                # Run cleanup task
                self._cleanup_old_messages()
                
            except Exception as e:
                logger.error(f"Error in chat cleanup thread loop: {e}")
                # Wait 60 seconds before retrying
                self.stop_event.wait(timeout=60)
    
    def _cleanup_old_messages(self):
        """Delete chat messages older than 24 hours"""
        try:
            from adminPanel.models import ChatMessage
            
            # Calculate the cutoff time (24 hours ago)
            cutoff_time = timezone.now() - timedelta(hours=24)
            
            # Get messages older than 24 hours
            old_messages = ChatMessage.objects.filter(created_at__lt=cutoff_time)
            deleted_count, _ = old_messages.delete()
            
            if deleted_count > 0:
                logger.info(f"Chat cleanup: Deleted {deleted_count} message(s) older than 24 hours")
                logger.debug(f"Cutoff time: {cutoff_time.isoformat()}")
            else:
                logger.debug("Chat cleanup: No messages to delete")
            
            return {
                'success': True,
                'deleted_count': deleted_count,
                'cutoff_time': cutoff_time.isoformat(),
                'hours': 24,
                'timestamp': timezone.now().isoformat()
            }
        
        except Exception as e:
            logger.error(f"Error cleaning up old chat messages: {e}")
            return {
                'success': False,
                'error': str(e),
                'timestamp': timezone.now().isoformat()
            }
    
    def force_cleanup(self, hours=24):
        """Manually trigger cleanup (used for testing or admin requests)"""
        try:
            from adminPanel.models import ChatMessage
            
            cutoff_time = timezone.now() - timedelta(hours=hours)
            old_messages = ChatMessage.objects.filter(created_at__lt=cutoff_time)
            deleted_count, _ = old_messages.delete()
            
            logger.info(f"Manual chat cleanup: Deleted {deleted_count} message(s) older than {hours} hours")
            
            return {
                'success': True,
                'deleted_count': deleted_count,
                'cutoff_time': cutoff_time.isoformat(),
                'hours': hours,
                'timestamp': timezone.now().isoformat(),
                'manual': True
            }
        except Exception as e:
            logger.error(f"Error in manual chat cleanup: {e}")
            return {
                'success': False,
                'error': str(e),
                'timestamp': timezone.now().isoformat()
            }


# Global instance
chat_cleanup_thread = ChatCleanupThread()
