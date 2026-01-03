from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from django.utils.decorators import method_decorator
from django.views.decorators.csrf import csrf_exempt
from django.core.cache import cache
from adminPanel.mt5.services import reset_manager_instance, get_manager_instance, force_refresh_trading_groups
from adminPanel.mt5.models import ServerSetting
import logging
from adminPanel.models import ActivityLog

logger = logging.getLogger(__name__)

@method_decorator(csrf_exempt, name='dispatch')
class RefreshMT5ConnectionAPIView(APIView):
    """
    API View to force refresh MT5 Manager connection
    POST: Force refresh the MT5 connection to use new credentials
    """
    permission_classes = [IsAuthenticated]  # Require authentication
    http_method_names = ['post', 'head', 'options']

    def post(self, request):
        try:
            # Check if server settings exist
            if not ServerSetting.objects.exists():
                return Response({
                    "error": "No server settings found. Please configure MT5 server settings first."
                }, status=status.HTTP_400_BAD_REQUEST)

            latest_setting = ServerSetting.objects.latest('created_at')
            
            # Reset the manager instance
            reset_manager_instance()
            
            # Clear MT5-related cache entries
            cache_keys = [
                'mt5_manager_error',
                'mt5_groups_sync',
                'mt5_connection_status'
            ]
            for key in cache_keys:
                cache.delete(key)
            
            # Force refresh trading groups
            groups_refreshed = False
            groups_error = None
            try:
                groups_refreshed = force_refresh_trading_groups()
                if groups_refreshed:
                    logger.info("Trading groups refreshed successfully after connection reset")
                else:
                    groups_error = "Groups refresh returned False"
            except Exception as e:
                groups_error = str(e)
                logger.error(f"Error refreshing trading groups: {e}")
            
            # Test the new connection
            try:
                manager = get_manager_instance()
                connection_status = "connected" if manager and manager.connected else "failed"
            except Exception as e:
                connection_status = f"failed: {str(e)}"
                logger.error(f"MT5 connection test failed after refresh: {e}")

            # Log the activity
            from django.utils import timezone
            
            # Get client IP from request
            def get_client_ip(request):
                x_forwarded_for = request.META.get('HTTP_X_FORWARDED_FOR')
                if x_forwarded_for:
                    ip = x_forwarded_for.split(',')[0]
                else:
                    ip = request.META.get('REMOTE_ADDR')
                return ip
            
            ActivityLog.objects.create(
                user=request.user,
                activity="Forced MT5 Manager connection refresh",
                ip_address=get_client_ip(request),
                endpoint=request.path,
                activity_type="refresh",
                activity_category="management",
                user_agent=request.META.get("HTTP_USER_AGENT", ""),
                timestamp=timezone.now(),
                related_object_id=latest_setting.id,
                related_object_type="ServerSetting"
            )

            return Response({
                "message": "MT5 Manager connection refreshed successfully",
                "connection_status": connection_status,
                "groups_refreshed": groups_refreshed,
                "groups_error": groups_error,
                "server_info": {
                    "server_ip": latest_setting.server_ip,
                    "login_id": latest_setting.real_account_login,
                    "server_name": latest_setting.server_name_client
                },
                "timestamp": timezone.now().isoformat()
            }, status=status.HTTP_200_OK)

        except Exception as e:
            logger.error(f"Error in RefreshMT5ConnectionAPIView: {e}")
            return Response({
                "error": f"Failed to refresh MT5 connection: {str(e)}"
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
