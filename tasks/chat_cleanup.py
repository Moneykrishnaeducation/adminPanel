"""
Celery task for automatically clearing old chat messages
Runs automatically every hour to clean up messages older than 24 hours
"""

from celery import shared_task
from django.utils import timezone
from datetime import timedelta
import logging

logger = logging.getLogger(__name__)


@shared_task(name='cleanup_old_chat_messages')
def cleanup_old_chat_messages(hours=24):
    """
    Delete chat messages that are older than specified hours
    This task runs automatically every hour by default
    
    Args:
        hours: Number of hours after which chat messages will be deleted (default: 24)
    
    Returns:
        Dictionary with status and count of deleted messages
    """
    try:
        from adminPanel.models import ChatMessage
        
        # Calculate the cutoff time (24 hours ago by default)
        cutoff_time = timezone.now() - timedelta(hours=hours)
        
        # Get the messages to be deleted
        old_messages = ChatMessage.objects.filter(created_at__lt=cutoff_time)
        deleted_count, _ = old_messages.delete()
        
        logger.info(f'Chat cleanup task: Deleted {deleted_count} old chat message(s) (older than {hours} hours)')
        
        return {
            'success': True,
            'deleted_count': deleted_count,
            'cutoff_time': cutoff_time.isoformat(),
            'hours': hours,
            'timestamp': timezone.now().isoformat()
        }
    
    except Exception as e:
        logger.error(f'Error in cleanup_old_chat_messages task: {str(e)}')
        return {
            'success': False,
            'error': str(e),
            'timestamp': timezone.now().isoformat()
        }