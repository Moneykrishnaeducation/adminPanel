from django.apps import AppConfig

class AdminPanelConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'adminPanel'
    
    def ready(self):
        """Start background threads when Django app is ready"""
        try:
            # Start chat message cleanup thread
            from adminPanel.chat_cleanup_thread import chat_cleanup_thread
            chat_cleanup_thread.start()
        except Exception as e:
            import logging
            logger = logging.getLogger(__name__)
            logger.warning(f"Failed to start chat cleanup thread: {e}")