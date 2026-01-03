
from rest_framework.permissions import BasePermission

class IsAdminOrManager(BasePermission):
    """
    Allows access if user is admin or manager.
    """
    def has_permission(self, request, view):
        from adminPanel.permissions import IsAdmin, IsManager
        return IsAdmin().has_permission(request, view) or IsManager().has_permission(request, view)


def OrPermission(*permissions):
    """Factory that returns a DRF permission class which allows access when any
    of the provided permission classes grant access.

    Usage in views: ``permission_classes = [OrPermission(IsAdmin, IsManager)]``
    This factory returns a class (not an instance) which DRF can instantiate.
    """

    class _OrPermission(BasePermission):
        def __init__(self):
            # store the provided permission classes/instances
            self._raw_permissions = permissions

        def _instantiate_permissions(self):
            instances = []
            for permission in self._raw_permissions:
                if isinstance(permission, type):
                    instances.append(permission())
                else:
                    instances.append(permission)
            return instances

        def has_permission(self, request, view):
            # Instantiate each permission and evaluate
            permission_instances = self._instantiate_permissions()
            for perm in permission_instances:
                try:
                    if perm.has_permission(request, view):
                        return True
                except Exception:
                    # swallow errors from individual perms to allow other perms to decide
                    continue
            return False

        def has_object_permission(self, request, view, obj):
            permission_instances = self._instantiate_permissions()
            for perm in permission_instances:
                try:
                    if getattr(perm, 'has_object_permission', lambda *_: False)(request, view, obj):
                        return True
                except Exception:
                    continue
            return False

    return _OrPermission

class IsAuthenticatedUser(BasePermission):
    """
    Allow access only to authenticated users.
    """
    def has_permission(self, request, view):
        return request.user and request.user.is_authenticated

class IsAdmin(IsAuthenticatedUser):
    """
    Allow access to Admin users only.
    """
    def has_permission(self, request, view):
        if not super().has_permission(request, view):
            return False
        
        # Check if user is superuser
        if request.user.is_superuser:
            return True
            
        # Check manager_admin_status (handle both 'Admin' and 'admin')
        if hasattr(request.user, 'manager_admin_status') and request.user.manager_admin_status:
            status = request.user.manager_admin_status.lower()
            return 'admin' in status
            
        return False

class IsManager(IsAuthenticatedUser):
    """
    Allow access to Manager users only.
    """
    def has_permission(self, request, view):
        if not super().has_permission(request, view):
            return False
            
        # Check manager_admin_status (handle both 'Manager' and 'manager')
        if hasattr(request.user, 'manager_admin_status') and request.user.manager_admin_status:
            status = request.user.manager_admin_status.lower()
            return 'manager' in status
            
        return False


class IsAdminOrManager(IsAuthenticatedUser):
    """
    Allow access to Admin or Manager users.
    """
    def has_permission(self, request, view):
        if not super().has_permission(request, view):
            return False
        
        # Check if user is superuser
        if request.user.is_superuser:
            return True
            
        # Check manager_admin_status (handle case insensitive)
        if hasattr(request.user, 'manager_admin_status') and request.user.manager_admin_status:
            status = request.user.manager_admin_status.lower()
            return any(role in status for role in ['admin', 'manager'])
            
        return False
