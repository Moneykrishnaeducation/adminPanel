from functools import wraps
from rest_framework.response import Response
from rest_framework import status

def role_required(allowed_roles):
    def decorator(view_func):
        @wraps(view_func)
        def _wrapped_view(request, *args, **kwargs):
            # Check if user is authenticated
            if not request.user.is_authenticated:
                return Response({
                    "error": "Authentication credentials were not provided."
                }, status=status.HTTP_401_UNAUTHORIZED)
            
            user_status = getattr(request.user, 'manager_admin_status', 'None')
            user_status_lower = user_status.lower() if isinstance(user_status, str) else str(user_status).lower()
            
            
            # Check if user has permission based on their manager_admin_status
            has_permission = False
            
            for role in allowed_roles:
                role_lower = role.lower() if isinstance(role, str) else str(role).lower()
                if role_lower == 'admin' and user_status_lower in ['admin']:
                    has_permission = True
                    break
                elif role_lower == 'manager' and user_status_lower in ['manager']:
                    has_permission = True
                    break
                elif role_lower == 'client' and user_status_lower in ['none', 'client']:
                    has_permission = True
                    break
            
            if not has_permission:
                print(f"DEBUG: Permission denied for user {request.user.username} with status '{user_status}' for roles {allowed_roles}")
                return Response({
                    "error": "You don't have permission to perform this action."
                }, status=status.HTTP_403_FORBIDDEN)
            
            return view_func(request, *args, **kwargs)
        return _wrapped_view
    return decorator
