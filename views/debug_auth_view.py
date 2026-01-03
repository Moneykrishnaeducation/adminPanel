from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import AllowAny
from rest_framework.permissions import IsAuthenticated


class AuthDebugView(APIView):
    """Debug view to check authentication status"""
    
    def get(self, request):
        user_role = getattr(request.user, 'role', 'unknown') if request.user.is_authenticated else None
        manager_admin_status = getattr(request.user, 'manager_admin_status', None) if request.user.is_authenticated else None
        is_admin = (
            (request.user.is_superuser if hasattr(request.user, 'is_superuser') else False) or
            user_role == 'admin' or
            ('admin' in str(manager_admin_status).lower() if manager_admin_status else False)
        )
        is_manager = (
            user_role == 'manager' or
            ('manager' in str(manager_admin_status).lower() if manager_admin_status else False)
        )
        
        return Response({
            "authenticated": request.user.is_authenticated,
            "user": str(request.user) if request.user.is_authenticated else None,
            "user_id": request.user.id if request.user.is_authenticated else None,
            "role": user_role,
            "manager_admin_status": manager_admin_status,
            "is_superuser": request.user.is_superuser if hasattr(request.user, 'is_superuser') else False,
            "is_admin": is_admin,
            "is_manager": is_manager,
            "path": request.path,
            "method": request.method,
        }, status=status.HTTP_200_OK)


@api_view(['GET'])
@permission_classes([AllowAny])
def auth_debug_public(request):
    """Public debug view - no authentication required"""
    auth_header = request.headers.get('Authorization', 'No auth header')
    
    return Response({
        "message": "Public auth debug endpoint",
        "has_auth_header": 'Authorization' in request.headers,
        "auth_header_preview": auth_header[:50] + "..." if len(auth_header) > 50 else auth_header,
        "authenticated": request.user.is_authenticated,
        "user": str(request.user) if request.user.is_authenticated else "AnonymousUser",
        "path": request.path,
        "method": request.method,
    }, status=status.HTTP_200_OK)
