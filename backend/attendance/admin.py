from django.contrib import admin
from django.contrib.auth.admin import UserAdmin
from .models import User, Department, Course, Section, Schedule, Student, Membership

class StaffUserAdmin(UserAdmin):
    fieldsets = UserAdmin.fieldsets + (('University role', {'fields': ('role',)}),)
    add_fieldsets = UserAdmin.add_fieldsets + (('University role', {'fields': ('role',)}),)
    def has_module_permission(self, request): return request.user.role == 'admin'
    def has_view_permission(self, request, obj=None): return request.user.role == 'admin'
    def has_change_permission(self, request, obj=None): return request.user.role == 'admin'
    def has_add_permission(self, request): return request.user.role == 'admin'
    def has_delete_permission(self, request, obj=None): return request.user.role == 'admin'
    def log_addition(self, request, obj, message):
        from .services import audit
        audit('admin.created', request.user, model='User', id=obj.pk)
        return super().log_addition(request, obj, message)
    def log_change(self, request, obj, message):
        from .services import audit
        audit('admin.updated', request.user, model='User', id=obj.pk)
        return super().log_change(request, obj, message)
    def log_deletions(self, request, queryset):
        from .services import audit
        for obj in queryset: audit('admin.deleted', request.user, model='User', id=obj.pk)
        return super().log_deletions(request, queryset)

admin.site.register(User, StaffUserAdmin)
# Master data management is implemented in the audited admin REST/UI. Biometric data and attendance
# deliberately have no Django admin registrations to prevent unaudited edits and accidental exposure.
