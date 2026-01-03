from enum import Enum

class UserRole(Enum):
    ADMIN = "admin"
    MANAGER = "manager"
    CLIENT = "client"

def is_admin(user):
    return user.is_superuser or (user.manager_admin_status and user.manager_admin_status.startswith("Admin"))

def is_manager(user):
    return user.manager_admin_status and user.manager_admin_status.startswith("Manager")

def is_client(user):
    return not is_admin(user) and not is_manager(user)
