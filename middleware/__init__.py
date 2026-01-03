# Middleware package
import logging
from django.core.cache import cache
from adminPanel.mt5.services import MT5ManagerActions
from django.utils.deprecation import MiddlewareMixin

logger = logging.getLogger(__name__)

class IPAddressMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        
        ip_address = request.META.get('HTTP_X_FORWARDED_FOR')
        if ip_address:
            request.ip_address = ip_address.split(',')[0]  
        else:
            request.ip_address = request.META.get('REMOTE_ADDR')  
        return self.get_response(request)


class DisableCSRFMiddleware(MiddlewareMixin):
    def process_request(self, request):
        request.csrf_processing_done = True

class MT5ConnectionMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response
        self._has_run = False

    def __call__(self, request):
        if not self._has_run:
            try:
                self.run_once()
            except Exception as e:
                logger.error(f"MT5 Connection Error: {str(e)}")
                # Store the error in cache for admin notification
                cache.set('mt5_connection_error', str(e), 300)  # Cache for 5 minutes
        return self.get_response(request)

    def run_once(self):
        try:
            if not cache.get('mt5_connected'):
                initgo = MT5ManagerActions()
                if initgo.manager and initgo.manager.is_connected():
                    cache.set('mt5_connected', True, 3600)  # Cache for 1 hour
                    self._has_run = True
                    logger.info("Successfully connected to MT5 Manager")
        except Exception as e:
            logger.error(f"Error initializing MT5 Manager: {str(e)}")
            raise e
