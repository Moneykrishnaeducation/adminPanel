from django.db import models
from django.utils import timezone

class ServerSetting(models.Model):
    server_ip = models.CharField(max_length=100, verbose_name='Server IP Address with Port')
    real_account_login = models.CharField(max_length=100, verbose_name='Real Account Login ID')
    real_account_password = models.CharField(max_length=100, verbose_name='Real Account Password')
    server_name_client = models.CharField(max_length=100, verbose_name='Server Name for Live Accounts')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'Server Setting'
        verbose_name_plural = 'Server Settings'

    def __str__(self):
        return f"{self.server_name_client} ({self.server_ip})"

class MT5GroupConfig(models.Model):
    """Model to store MT5 trading groups configuration"""
    group_name = models.CharField(max_length=255, unique=True)
    is_demo = models.BooleanField(default=False)
    is_enabled = models.BooleanField(default=True)
    leverage = models.IntegerField(default=100)
    min_deposit = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    description = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    last_sync = models.DateTimeField(null=True)

    class Meta:
        db_table = 'mt5_group_config'
        ordering = ['group_name']

    def __str__(self):
        return f"{self.group_name} ({'Demo' if self.is_demo else 'Real'})"

    def mark_synced(self):
        self.last_sync = timezone.now()
        self.save()
