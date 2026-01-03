from django.apps import AppConfig

class MT5Config(AppConfig):
    name = 'adminPanel.mt5'
    verbose_name = 'MT5 Integration'
    default_auto_field = 'django.db.models.BigAutoField'
    
    def ready(self):
        # Import signals or perform other initialization here if needed
        pass
