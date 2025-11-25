from rest_framework import permissions

class IsStaffOrSuperuser(permissions.BasePermission):
    """
    Custom permission to only allow staff or superusers to delete users.
    """
    def has_permission(self, request, view):
        if request.user.is_authenticated:
            return request.user.is_staff or request.user.is_superuser
        return False


class IsAdmin(permissions.BasePermission):
    def has_permission(self, request, view):
        if request.user.is_authenticated:
            return request.user.is_admin
        return False
    

class IsAdminOrSuperuser(permissions.BasePermission):
    """
    Custom permission to only allow admin or superusers to create companies.
    """
    def has_permission(self, request, view):
        if request.user.is_authenticated:
            return request.user.is_admin or request.user.is_superuser
        return False
    
class IsAuthenticated(permissions.BasePermission):
    """
    Custom permission to allow only authenticated users to create a user
    """
    def has_permission(self, request, view):
        if request.user.is_authenticated:
            return request.user.is_authenticated
        return False