"""
Celery task for cleaning up old notifications
Runs automatically every day at midnight
"""

from celery import shared_task
from django.utils import timezone
import logging

logger = logging.getLogger(__name__)


@shared_task(name='cleanup_old_notifications')
def cleanup_old_notifications(days=7):
    """
    Delete notifications that have been read for more than specified days
    This task runs automatically every day
    
    Args:
        days: Number of days after which read notifications will be deleted (default: 7)
    
    Returns:
        Number of notifications deleted
    """
    try:
        from adminPanel.models_notification import Notification
        
        deleted_count = Notification.delete_old_read_notifications(days=days)
        
        logger.info(f'Cleanup task: Deleted {deleted_count} old notification(s)')
        
        return {
            'success': True,
            'deleted_count': deleted_count,
            'timestamp': timezone.now().isoformat()
        }
    
    except Exception as e:
        logger.error(f'Error in cleanup_old_notifications task: {str(e)}')
        return {
            'success': False,
            'error': str(e),
            'timestamp': timezone.now().isoformat()
        }
