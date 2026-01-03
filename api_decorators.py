from functools import wraps
from django.utils.decorators import method_decorator
from rest_framework.response import Response
from rest_framework import status 
from rest_framework_simplejwt.exceptions import InvalidToken, TokenError
from rest_framework_simplejwt.tokens import UntypedToken
import jwt


def _is_admin_path(path: str) -> bool:
    if not path:
        return False
    p = path.lower()
    return ('/api/admin/' in p) or p.startswith('/admin-api') or ('/admin-api/' in p)

def api_auth_required(view_func):
    """
    Decorator for API views to return JSON responses for authentication failures
    instead of redirecting to login page.
    """
    @wraps(view_func)
    def _wrapped_view(request, *args, **kwargs):
        if not request.user.is_authenticated:
            # Check if token is expired
            auth_header = request.headers.get('Authorization')
            if auth_header and auth_header.startswith('Bearer '):
                token = auth_header.split(' ')[1]
                try:
                    UntypedToken(token)  # This will fail if token is expired
                    # Reject tokens with wrong audience on admin endpoints
                    try:
                        payload = jwt.decode(token, options={"verify_signature": False})
                        aud = payload.get('aud')
                    except Exception:
                        aud = None
                    if _is_admin_path(request.path) and aud != 'admin.vtindex':
                        return Response({
                            "error": "Token audience not permitted for this endpoint.",
                            "code": "invalid_audience"
                        }, status=status.HTTP_401_UNAUTHORIZED)
                    return Response({
                        "error": "Invalid authentication credentials.",
                        "code": "invalid_token"
                    }, status=status.HTTP_401_UNAUTHORIZED)
                except (InvalidToken, TokenError):
                    return Response({
                        "error": "Authentication token has expired.",
                        "code": "token_expired"
                    }, status=status.HTTP_401_UNAUTHORIZED)
            
            return Response({
                "error": "Authentication credentials were not provided.",
                "code": "not_authenticated"
            }, status=status.HTTP_401_UNAUTHORIZED)
        return view_func(request, *args, **kwargs)
    return _wrapped_view

def api_role_required(allowed_roles):
    """
    Decorator for API views to check user roles and return JSON responses.
    This combines authentication check and role permission check.
    """
    def decorator(view_func):
        @wraps(view_func)
        def _wrapped_view(request, *args, **kwargs):
            # First check if user is authenticated
            auth_header = request.headers.get('Authorization')
            if not request.user.is_authenticated:
                if auth_header and auth_header.startswith('Bearer '):
                    token = auth_header.split(' ')[1]
                    try:
                        UntypedToken(token)  # This will fail if token is expired
                        try:
                            payload = jwt.decode(token, options={"verify_signature": False})
                            aud = payload.get('aud')
                        except Exception:
                            aud = None
                        if _is_admin_path(request.path) and aud != 'admin.vtindex':
                            return Response({
                                "error": "Token audience not permitted for this endpoint.",
                                "code": "invalid_audience"
                            }, status=status.HTTP_401_UNAUTHORIZED)
                        return Response({
                            "error": "Invalid authentication credentials.",
                            "code": "invalid_token"
                        }, status=status.HTTP_401_UNAUTHORIZED)
                    except (InvalidToken, TokenError):
                        return Response({
                            "error": "Authentication token has expired.",
                            "code": "token_expired"
                        }, status=status.HTTP_401_UNAUTHORIZED)
                
                return Response({
                    "error": "Authentication credentials were not provided.",
                    "code": "not_authenticated"
                }, status=status.HTTP_401_UNAUTHORIZED)
            
            # Role mapping
            role_map = {
                'admin': 'Admin',
                'manager': 'Manager',
                'client': 'Client'
            }
            
            # Convert allowed roles to their corresponding manager_admin_status values
            allowed_statuses = [role_map[role.lower()] for role in allowed_roles]
            
            has_permission = request.user.manager_admin_status in allowed_statuses
            
            if has_permission:
                return view_func(request, *args, **kwargs)
            
            return Response({
                "error": "You don't have permission to perform this action.",
                "code": "permission_denied"
            }, status=status.HTTP_403_FORBIDDEN)
        return _wrapped_view
    return decorator
