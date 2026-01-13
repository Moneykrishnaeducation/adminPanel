import logging
import json
from django.utils.deprecation import MiddlewareMixin
from adminPanel.models import ActivityLog

logger = logging.getLogger(__name__)


class ActivityLoggingMiddleware(MiddlewareMixin):
    """
    Middleware to log all non-GET API requests (POST, PUT, PATCH, DELETE, etc.)
    for both Admin Panel and Client Panel to the ActivityLog model for audit purposes.
    
    Logs activities from:
    - Admin panel routes (/admin/, /api/)
    - Client panel routes (/api/, /client-api/, etc.)
    - Authentication endpoints
    - Management endpoints
    """

    # Paths to skip logging
    SKIP_PATHS = [
        '/static/',
        '/media/',
        '/health/',
        '/status/',
        '/debug/',
        '/__debug__/',
        '/auth/login',  # Admin login - already logged in views
        '/login',  # Client login endpoint - already logged in views
        '/logout',  # Logout - already manually logged in views
        '/otp/send',  # OTP send - already logged in views
        '/otp/verify',  # OTP verify - already logged in views
        '/otp/resend',  # OTP resend - already logged in views
        '/otp/check',  # OTP check - already logged in views
    ]

    # API endpoints to log (both admin and client)
    API_PATHS = [
        '/api/',
        '/client-api/',
        '/auth/',
        '/otp/',
    ]

    def should_log_request(self, request):
        """Check if the request should be logged"""
        # Only log non-GET requests
        if request.method == 'GET':
            return False

        # Check if path is in skip list (login, logout, OTP already logged in views)
        for skip_path in self.SKIP_PATHS:
            if skip_path in request.path:
                return False

        # Log all other non-GET requests that aren't in skip paths
        return True

    def process_request(self, request):
        """Store request info for later use in process_response"""
        if self.should_log_request(request):
            request._activity_start_time = __import__('time').time()
        return None

    def process_response(self, request, response):
        """Log the API request and response"""
        if not self.should_log_request(request):
            return response

        try:
            # Get user
            user = request.user if request.user and request.user.is_authenticated else None

            # Get activity info from request
            method = request.method
            endpoint = request.path
            ip_address = self.get_client_ip(request)
            user_agent = request.META.get('HTTP_USER_AGENT', '')[:500]
            status_code = response.status_code

            # Determine activity type based on HTTP method
            activity_type_map = {
                'POST': 'create',
                'PUT': 'update',
                'PATCH': 'update',
                'DELETE': 'delete',
            }
            activity_type = activity_type_map.get(method, 'other')

            # Determine activity category (management/admin or client)
            # Admin panel: /admin/, /api/admin/, management routes
            # Client panel: /api/, /client-api/, client routes
            if '/admin/' in endpoint or '/admin-' in endpoint:
                activity_category = 'management'
            else:
                activity_category = 'client'

            # Create user-friendly activity description based on endpoint
            activity = self.get_activity_message(method, endpoint)

            # Add response body info if available (for error details)
            if status_code >= 400:
                try:
                    response_data = response.data if hasattr(response, 'data') else {}
                    if response_data:
                        # Get error message from response
                        error_msg = response_data.get('detail') or response_data.get('error') or response_data.get('message')
                        if error_msg:
                            activity = f"{activity} - {str(error_msg)[:200]}"
                except Exception as e:
                    logger.warning(f"Failed to extract error message: {e}")

            # Check if a similar log already exists for this user from the last 2 seconds
            # This avoids duplicates when manual logging already exists
            from django.utils import timezone
            from datetime import timedelta
            
            recent_logs = ActivityLog.objects.filter(
                user=user,
                endpoint=endpoint,
                timestamp__gte=timezone.now() - timedelta(seconds=2)
            ).order_by('-timestamp')
            
            # If a recent log exists, update it with status code if needed or skip creating duplicate
            if recent_logs.exists():
                existing_log = recent_logs.first()
                # If status code is missing (None or 0), add it
                if existing_log.status_code is None or existing_log.status_code == 0:
                    existing_log.status_code = status_code
                    existing_log.save()
                # Skip creating duplicate log - return early
                return response
            
            # Create new activity log entry only if no duplicate exists
            ActivityLog.objects.create(
                user=user,
                activity=activity,
                activity_type=activity_type,
                activity_category=activity_category,
                status_code=status_code,
                ip_address=ip_address,
                user_agent=user_agent,
                endpoint=endpoint,
            )

        except Exception as e:
            logger.error(f"Error logging activity: {e}", exc_info=True)

        return response

    def get_client_ip(self, request):
        """
        Get client IP address from request,
        accounting for proxy headers.
        """
        x_forwarded_for = request.META.get('HTTP_X_FORWARDED_FOR')
        if x_forwarded_for:
            ip = x_forwarded_for.split(',')[0]
        else:
            ip = request.META.get('REMOTE_ADDR')
        return ip[:45]  # Limit to DB field size

    def get_activity_message(self, method, endpoint):
        """
        Generate user-friendly activity message based on HTTP method and endpoint.
        """
        # Map of endpoint patterns to friendly messages
        endpoint_messages = {
            # Auth endpoints
            '/auth/login': 'User login attempt',
            '/login': 'User login',
            '/logout': 'User logout',
            '/otp/send': 'OTP request sent',
            '/otp/verify': 'OTP verification attempted',
            '/otp/check': 'OTP status checked',
            
            # Profile endpoints
            '/profile/edit': 'Profile updated',
            '/profile/update': 'Profile updated',
            '/account/update': 'Account information updated',
            '/user/update': 'User information updated',
            '/personal/info': 'Personal information requested',
            
            # IB endpoints
            '/ib/request': 'IB request created',
            '/ib/apply': 'Applied for IB program',
            
            # Withdrawal endpoints
            '/withdrawal/request': 'Withdrawal request submitted',
            '/withdraw': 'Withdrawal initiated',
            
            # Commission endpoints
            '/commission/withdraw': 'Commission withdrawal requested',
            '/commission': 'Commission operation performed',
            
            # Account endpoints
            '/account/toggle': 'Account settings toggled',
            '/account/toggle-demo': 'Demo account toggled',
            '/account/create': 'Account created',
            '/account/delete': 'Account deleted',
            
            # User management (admin)
            '/user/create': 'User account created',
            '/user/delete': 'User account deleted',
            '/user/approve': 'User account approved',
            '/user/reject': 'User account rejected',
            '/user/verify': 'User verification updated',
            '/user/status': 'User status changed',
            '/user/role': 'User role assigned',
            
            # Transaction endpoints
            '/transaction': 'Transaction processed',
            '/transfer': 'Transfer initiated',
            
            # Settings endpoints
            '/settings/update': 'Settings updated',
            '/settings': 'Settings changed',
            
            # Client assignment (admin)
            '/client/assign': 'Client assigned to manager',
            '/assign-client': 'Client assignment processed',
            
            # Server settings (admin)
            '/server/settings': 'Server settings configured',
            '/settings/server': 'Server settings updated',
        }
        
        # Check if endpoint matches any pattern
        for pattern, message in endpoint_messages.items():
            if pattern in endpoint:
                return f"{message} ({method})"
        
        # Fallback: generate generic message from endpoint
        # Convert /api/profile/edit/ to "Profile edit"
        path_parts = endpoint.strip('/').split('/')
        # Remove 'api' and empty parts
        path_parts = [p for p in path_parts if p and p != 'api']
        
        if path_parts:
            # Join parts and capitalize
            action = ' '.join(path_parts).replace('-', ' ').replace('_', ' ')
            action = action.title()
            return f"{action} ({method})"
        
        return f"{method} request to {endpoint}"
