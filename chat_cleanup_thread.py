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
        """Main loop that runs cleanup every 5 minutes to check for messages 24 hours old"""
        while not self.stop_event.is_set():
            try:
                # Run cleanup task every 5 minutes to catch messages at their 24-hour mark
                self._cleanup_old_messages()
                
                # Wait 5 minutes before next check (300 seconds)
                # This ensures we catch messages within 5 minutes of their 24-hour creation time
                logger.debug("Chat cleanup: Next check in 5 minutes")
                
                # Wait 5 minutes before next check or until stop is signaled
                if self.stop_event.wait(timeout=300):
                    break  # Stop was called
                
            except Exception as e:
                logger.error(f"Error in chat cleanup thread loop: {e}")
                # Wait 60 seconds before retrying
                self.stop_event.wait(timeout=60)
    
    def _cleanup_old_messages(self):
        """Delete chat messages exactly 24 hours after they were created"""
        try:
            from adminPanel.models import ChatMessage
            
            # Calculate the cutoff time (messages older than 24 hours from now)
            # If a message was created at 01:00, it will be deleted when current time > 01:00 (next day)
            cutoff_time = timezone.now() - timedelta(hours=24)
            
            # Get messages older than 24 hours
            old_messages = ChatMessage.objects.filter(created_at__lt=cutoff_time)
            deleted_count, _ = old_messages.delete()
            
            if deleted_count > 0:
                logger.info(f"Chat cleanup: Deleted {deleted_count} message(s) that are 24+ hours old")
                logger.debug(f"Cutoff time: {cutoff_time.isoformat()} - Messages created before this time were deleted")
            else:
                logger.debug("Chat cleanup: No messages older than 24 hours to delete")
            
            return {
                'success': True,
                'deleted_count': deleted_count,
                'cutoff_time': cutoff_time.isoformat(),
                'cleanup_type': 'auto_24hours',
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
