from django.contrib import admin
from .models import UserProfile

@admin.register(UserProfile)
class UserProfileAdmin(admin.ModelAdmin):
    list_display = ("user", "must_change_password", "no")
    list_filter = ("must_change_password", "no")
    search_fields = ("user__username", "user__first_name", "user__last_name", "user__email")
