from django.db import models
from django.utils import timezone
import os
import binascii
import hashlib
from django.utils.crypto import constant_time_compare
from django.core import signing

class ServerSetting(models.Model):
    server_ip = models.CharField(max_length=100, verbose_name='Server IP Address with Port')
    real_account_login = models.CharField(max_length=100, verbose_name='Real Account Login ID')
    # Stored as: pbkdf2_sha512$iterations$salt$hash (salt is hex-encoded random bytes)
    real_account_password = models.CharField(max_length=2048, verbose_name='Real Account Password (hashed)')
    # Encrypted (signed) raw password for MT5 manager use. Use `get_real_account_password()` to decrypt.
    real_account_password_encrypted = models.TextField(blank=True, null=True, verbose_name='Real Account Password (encrypted)')
    server_name_client = models.CharField(max_length=100, verbose_name='Server Name for Live Accounts')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'Server Setting'
        verbose_name_plural = 'Server Settings'

    def __str__(self):
        return f"{self.server_name_client} ({self.server_ip})"

    def set_real_account_password(self, raw_password: str, iterations: int = 200000):
        """Hash and set the real account password using PBKDF2-HMAC-SHA512.

        Uses a 64-byte random salt encoded in URL-safe base64 and stores the
        derived key also in URL-safe base64. This keeps the total stored value
        well under typical DB column limits (e.g. 512 chars).
        """
        # 32 bytes of random salt; hex-encoded to 64 chars
        salt_bytes = os.urandom(32)
        salt = binascii.hexlify(salt_bytes).decode()
        dk = hashlib.pbkdf2_hmac('sha512', raw_password.encode(), salt_bytes, iterations)
        hash_hex = binascii.hexlify(dk).decode()
        self.real_account_password = f"pbkdf2_sha512${iterations}${salt}${hash_hex}"
        # Also store a signed (encrypted-like) copy so services can retrieve the raw password
        try:
            self.real_account_password_encrypted = signing.dumps(raw_password)
        except Exception:
            self.real_account_password_encrypted = None

    def check_real_account_password(self, raw_password: str) -> bool:
        """Verify a raw password against the stored PBKDF2-SHA512 hash."""
        try:
            algorithm, iterations, salt, hash_hex = self.real_account_password.split('$')
            if algorithm != 'pbkdf2_sha512':
                return False
            iterations = int(iterations)
            salt_bytes = binascii.unhexlify(salt.encode())
            dk = hashlib.pbkdf2_hmac('sha512', raw_password.encode(), salt_bytes, iterations)
            return constant_time_compare(binascii.hexlify(dk).decode(), hash_hex)
        except Exception:
            return False

    def get_real_account_password(self) -> str | None:
        """Return the decrypted raw password (or None on failure)."""
        # Try signed encrypted value first
        if self.real_account_password_encrypted:
            try:
                return signing.loads(self.real_account_password_encrypted)
            except Exception:
                pass

        # Fallback: if the stored `real_account_password` appears to be a hashed value
        # (pbkdf2_sha512$...), we cannot recover the raw password.
        raw_candidate = (self.real_account_password or '').strip()
        if raw_candidate.startswith('pbkdf2_sha512$'):
            return None

        # If it's not a hashed value, assume it's a raw password stored previously
        return raw_candidate or None

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
