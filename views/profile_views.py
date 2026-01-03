import logging
from rest_framework.decorators import api_view, permission_classes, authentication_classes
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from django.contrib.auth import get_user_model
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.cache import never_cache
from rest_framework_simplejwt.authentication import JWTAuthentication
from rest_framework.authentication import SessionAuthentication, TokenAuthentication

logger = logging.getLogger(__name__)

@csrf_exempt
@never_cache
@api_view(['GET'])
@authentication_classes([JWTAuthentication, TokenAuthentication, SessionAuthentication])
@permission_classes([AllowAny])
def get_user_profile(request):
    """Get the authenticated user's profile data"""
    try:
        user = request.user
        
        # Check if user is authenticated - if not, try to authenticate from token
        if not user.is_authenticated:
            # Try to extract token from cookies and authenticate
            for auth_class in [JWTAuthentication(), TokenAuthentication(), SessionAuthentication()]:
                try:
                    auth_result = auth_class.authenticate(request)
                    if auth_result:
                        user, _ = auth_result
                        request.user = user
                        break
                except Exception:
                    continue
        
        # If still not authenticated, return 401
        if not user.is_authenticated:
            logger.warning("[get_user_profile] User not authenticated after auth attempt")
            return Response({'error': 'User not authenticated'}, status=401)

        # Log successful authentication
        logger.debug(f"[get_user_profile] Authenticated user: {getattr(user, 'username', user.email)}")

        # Create a user-friendly name
        name = ''
        if hasattr(user, 'first_name') and hasattr(user, 'last_name') and user.first_name and user.last_name:
            name = f"{user.first_name} {user.last_name}"
        elif hasattr(user, 'first_name') and user.first_name:
            name = user.first_name
        elif hasattr(user, 'last_name') and user.last_name:
            name = user.last_name
        elif hasattr(user, 'username') and user.username:
            name = user.username
        else:
            name = user.email.split('@')[0] if user.email else 'User'

        data = {
            'id': user.id,
            'name': name,
            'username': getattr(user, 'username', ''),
            'email': user.email,
            'first_name': getattr(user, 'first_name', ''),
            'last_name': getattr(user, 'last_name', ''),
            'is_staff': user.is_staff,
            'is_superuser': user.is_superuser,
            'manager_admin_status': getattr(user, 'manager_admin_status', 'User'),
            'is_approved_by_admin': getattr(user, 'is_approved_by_admin', False),
        }
        return Response(data)

    except Exception as e:
        logger.error(f"[get_user_profile] Exception: {str(e)}", exc_info=True)
        return Response({'error': f'Profile error: {str(e)}'}, status=500)