
import logging
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from django.contrib.auth import get_user_model
from adminPanel.authentication import BlacklistCheckingJWTAuthentication
from rest_framework.decorators import authentication_classes

logger = logging.getLogger(__name__)

@api_view(['GET'])
@authentication_classes([BlacklistCheckingJWTAuthentication])
@permission_classes([IsAuthenticated])
def get_user_profile(request):
    """Get the authenticated user's profile data"""
    try:
        user = request.user
        if not user.is_authenticated:
            logger.warning("[get_user_profile] User not authenticated")
            return Response({'error': 'User not authenticated'}, status=401)

        # Log successful authentication - no admin privilege check needed for profile endpoint
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
        }
        return Response(data)

    except Exception as e:
        logger.error(f"[get_user_profile] Exception: {str(e)}", exc_info=True)
        return Response({'error': f'Profile error: {str(e)}'}, status=500)
