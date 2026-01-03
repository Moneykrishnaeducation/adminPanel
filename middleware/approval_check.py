"""
Middleware to check if authenticated users have been approved by admin before accessing protected APIs
"""
from django.http import JsonResponse
from django.utils.deprecation import MiddlewareMixin
from rest_framework import status
import logging

logger = logging.getLogger(__name__)


class AdminApprovalCheckMiddleware(MiddlewareMixin):
    """
    Middleware to check admin approval status for API endpoints.
    Blocks access to protected APIs if user is not approved by admin.
    """
    
    # Paths that require admin approval
    PROTECTED_API_PATHS = [
        '/api/client/',
        '/client-api/',
        '/api/trading/',
    ]
    
    # Paths that are exempt from approval check (login, verification, etc.)
    EXEMPT_PATHS = [
        '/api/profile/',  # Allow unapproved users to check their approval status
        '/api/client/login/',
        '/api/client/signup/',
        '/api/client/validate-token/',
        '/api/client/logout/',
        '/api/client/verify-otp/',
        '/api/client/send-otp/',
        '/api/client/reset-password/',
        '/api/client/send-reset-otp/',
        '/client-api/login/',
        '/client-api/signup/',
        '/client-api/validate-token/',
        '/client-api/logout/',
        '/client-api/verify-otp/',
        '/client-api/send-otp/',
        '/client-api/reset-password/',
        '/client-api/send-reset-otp/',
    ]
    
    def should_check_approval(self, request_path):
        """
        Check if the request path requires admin approval check.
        """
        # Check if path is in protected paths
        is_protected = any(request_path.startswith(path) for path in self.PROTECTED_API_PATHS)
        
        # Check if path is exempt
        is_exempt = any(request_path.startswith(path) for path in self.EXEMPT_PATHS)
        
        return is_protected and not is_exempt
    
    def process_request(self, request):
        """
        Process incoming request and check approval status if needed.
        """
        # Only check API endpoints
        if not self.should_check_approval(request.path):
            logger.debug(f"[AdminApprovalCheck] Path {request.path} does not require approval check")
            return None
        
        # Check if user is authenticated
        if not request.user or not request.user.is_authenticated:
            logger.debug(f"[AdminApprovalCheck] User not authenticated for {request.path}")
            return None
        
        # Check if user is approved by admin
        if hasattr(request.user, 'is_approved_by_admin'):
            if not request.user.is_approved_by_admin:
                logger.warning(f"[AdminApprovalCheck] User {request.user.email} denied access to {request.path} - not approved")
                return JsonResponse({
                    'error': 'Your account has not been approved by the admin yet. Please wait for admin approval to access this feature.',
                    'code': 'user_not_approved'
                }, status=status.HTTP_403_FORBIDDEN)
        
        logger.debug(f"[AdminApprovalCheck] User {request.user.email} approved for {request.path}")
        return None