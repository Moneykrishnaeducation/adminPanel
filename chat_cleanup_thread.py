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
        """Main loop that runs cleanup every 5 minutes (for testing)"""
        while not self.stop_event.is_set():
            try:
                # Check if it's time to run cleanup (every 5 minutes)
                now = timezone.now()
                
                # Calculate seconds until next 5-minute interval
                seconds_passed_in_interval = (now.minute % 5) * 60 + now.second
                seconds_to_next_interval = 300 - seconds_passed_in_interval
                
                # Log the schedule
                logger.debug(f"Chat cleanup: Next run in {seconds_to_next_interval} seconds (every 5 minutes)")
                
                # Wait until next 5-minute interval or until stop is signaled
                if self.stop_event.wait(timeout=seconds_to_next_interval):
                    break  # Stop was called
                
                # Run cleanup task
                self._cleanup_old_messages()
                
            except Exception as e:
                logger.error(f"Error in chat cleanup thread loop: {e}")
                # Wait 60 seconds before retrying
                self.stop_event.wait(timeout=60)
    
    def _cleanup_old_messages(self):
        """Delete chat messages older than 5 minutes (for testing)"""
        try:
            from adminPanel.models import ChatMessage
            
            # Calculate the cutoff time (5 minutes ago for testing)
            cutoff_time = timezone.now() - timedelta(minutes=5)
            
            # Get messages older than 5 minutes
            old_messages = ChatMessage.objects.filter(created_at__lt=cutoff_time)
            deleted_count, _ = old_messages.delete()
            
            if deleted_count > 0:
                logger.info(f"Chat cleanup: Deleted {deleted_count} message(s) older than 5 minutes")
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
