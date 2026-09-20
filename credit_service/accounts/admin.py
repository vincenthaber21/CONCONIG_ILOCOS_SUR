from django.contrib import admin
from django.contrib.auth.admin import UserAdmin

from .models import User


@admin.register(User)
class CustomUserAdmin(UserAdmin):
    fieldsets = UserAdmin.fieldsets + (
        ("Cooperative profile", {"fields": ("role", "phone_number", "member_number")}),
    )
    add_fieldsets = UserAdmin.add_fieldsets + (
        ("Cooperative profile", {"fields": ("role", "phone_number", "member_number")}),
    )
    list_display = ("username", "email", "first_name", "last_name", "role", "is_staff")
    list_filter = UserAdmin.list_filter + ("role",)
    search_fields = ("username", "email", "first_name", "last_name", "member_number")
