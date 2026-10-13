from rest_framework.permissions import BasePermission
from rest_framework.exceptions import PermissionDenied
from .models import Section

def is_admin(user):
    return user.is_authenticated and user.is_active and user.role == 'admin'

class IsStaffRole(BasePermission):
    def has_permission(self, request, view):
        return request.user.is_authenticated and request.user.is_active and request.user.role in ('teacher', 'admin')

class IsAdminRole(BasePermission):
    def has_permission(self, request, view): return is_admin(request.user)

def sections_for(user):
    return Section.objects.all() if is_admin(user) else Section.objects.filter(teachers=user)

def authorize_section(user, section):
    if not is_admin(user) and not (user.is_authenticated and user.is_active and user.role == 'teacher'
                                 and section.teachers.filter(pk=user.pk).exists()):
        raise PermissionDenied('This section is not assigned to you.')
