# Tasks module for adminPanel
from .monthly_reports import MonthlyReportGenerator
from .notification_cleanup import cleanup_old_notifications
from .chat_cleanup import cleanup_old_chat_messages
# Ensure Celery autodiscovery finds tasks defined in submodules
from . import daily_reports  # registers shared_task-decorated functions

__all__ = [
    'MonthlyReportGenerator',
    'cleanup_old_notifications',
    'cleanup_old_chat_messages',
    'daily_reports'
]