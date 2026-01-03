

from django.contrib import admin
from adminPanel.models import Transaction

# Custom admin for Transaction to make document field visible and editable
class TransactionAdmin(admin.ModelAdmin):
    list_display = [field.name for field in Transaction._meta.fields]
    search_fields = ['id', 'user', 'trading_account']
    readonly_fields = []

# Unregister if already registered by auto-register
if Transaction in admin.site._registry:
    admin.site.unregister(Transaction)
admin.site.register(Transaction, TransactionAdmin)


from django.contrib import admin
from adminPanel.models import CustomUser

class CustomUserAdmin(admin.ModelAdmin):
    list_display = [
        'user_id', 'email', 'first_name', 'last_name', 'role',
        'user_verified', 'id_proof_verified', 'address_proof_verified',
        'is_active', 'date_joined'
    ]
    list_filter = ['role', 'id_proof_verified', 'address_proof_verified', 'is_active']
    search_fields = ['email', 'first_name', 'last_name', 'user_id']
    readonly_fields = ['user_verified']
    actions = ['approve_kyc', 'reject_kyc']

    def approve_kyc(self, request, queryset):
        updated = queryset.update(id_proof_verified=True, address_proof_verified=True)
        self.message_user(request, f"KYC approved for {updated} user(s).")

    def reject_kyc(self, request, queryset):
        updated = queryset.update(id_proof_verified=False, address_proof_verified=False)
        self.message_user(request, f"KYC rejected for {updated} user(s).")

    approve_kyc.short_description = "Approve KYC for selected users"
    reject_kyc.short_description = "Reject KYC for selected users"

if CustomUser in admin.site._registry:
    admin.site.unregister(CustomUser)
admin.site.register(CustomUser, CustomUserAdmin)
from django.contrib import admin
from django.apps import apps
from django.db import models  
from adminPanel.mt5.models import ServerSetting

app = apps.get_app_config('adminPanel')

# Remove the previous registration attempt
if hasattr(admin.site, '_registry') and ServerSetting in admin.site._registry:
    admin.site.unregister(ServerSetting)

@admin.register(ServerSetting)
class ServerSettingAdmin(admin.ModelAdmin):
    list_display = ['server_ip', 'server_name_client', 'created_at', 'updated_at']
    readonly_fields = ['created_at', 'updated_at']

# Register other models
for model_name, model in app.models.items():
    if model not in admin.site._registry and model != ServerSetting:  # Skip ServerSetting as it's registered above
        list_display = [field.name for field in model._meta.fields]
        search_fields = [field.name for field in model._meta.fields if isinstance(field, (models.CharField, models.TextField))]
        list_filter = [field.name for field in model._meta.fields if isinstance(field, (models.BooleanField, models.DateField, models.DateTimeField))]
        ordering = [model._meta.pk.name]

        admin_class = type(
            f"{model_name}Admin",
            (admin.ModelAdmin,),
            {
                "list_display": list_display,
                "search_fields": search_fields,
                "list_filter": list_filter,
                "ordering": ordering,
            }
        )
        
        try:
            admin.site.register(model, admin_class)
        except admin.sites.AlreadyRegistered:
            pass
