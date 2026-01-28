from django.db import models
from django.utils import timezone
from django.conf import settings
import base64
import hashlib
import logging
import os

try:
    from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
    from cryptography.hazmat.primitives import hashes
except Exception:
    PBKDF2HMAC = None
    hashes = None

try:
    from cryptography.fernet import Fernet
except Exception:
    Fernet = None

logger = logging.getLogger(__name__)

class ServerSetting(models.Model):
    # Increase max_length to accommodate encrypted values
    server_ip = models.CharField(max_length=512, verbose_name='Server IP Address with Port')
    real_account_login = models.CharField(max_length=100, verbose_name='Real Account Login ID')
    real_account_password = models.CharField(max_length=512, verbose_name='Real Account Password')
    server_name_client = models.CharField(max_length=100, verbose_name='Server Name for Live Accounts')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'Server Setting'
        verbose_name_plural = 'Server Settings'

    def __str__(self):
        try:
            ip = self.__getattribute__('server_ip')
        except Exception:
            ip = getattr(self, 'server_ip', '')
        return f"{self.server_name_client} ({ip})"

    # --- Encryption helpers ---
    @staticmethod
    def _get_fernet():
        # Determine key material: prefer explicit setting, otherwise use SECRET_KEY
        key_material = getattr(settings, 'MT5_ENCRYPTION_KEY', None) or settings.SECRET_KEY
        raw = key_material.encode()
        # No salt => fallback to previous deterministic derivation (sha256)
        digest = hashlib.sha256(raw).digest()
        fkey = base64.urlsafe_b64encode(digest)
        if Fernet is None:
            return None
        return Fernet(fkey)

    @staticmethod
    def _get_fernet_with_salt(salt: bytes):
        """
        Derive a per-value Fernet key using PBKDF2HMAC with the provided salt.
        If PBKDF2HMAC is unavailable, fall back to the deterministic SHA256 derivation.
        """
        key_material = getattr(settings, 'MT5_ENCRYPTION_KEY', None) or settings.SECRET_KEY
        raw = key_material.encode()
        if PBKDF2HMAC is None or hashes is None:
            # fallback
            digest = hashlib.sha256(raw).digest()
            fkey = base64.urlsafe_b64encode(digest)
            if Fernet is None:
                return None
            return Fernet(fkey)
        # Derive key using PBKDF2HMAC
        kdf = PBKDF2HMAC(
            algorithm=hashes.SHA256(),
            length=32,
            salt=salt,
            iterations=390000,
        )
        key = kdf.derive(raw)
        fkey = base64.urlsafe_b64encode(key)
        if Fernet is None:
            return None
        return Fernet(fkey)

    @classmethod
    def _encrypt_value(cls, plaintext: str) -> str:
        if plaintext is None:
            return None
        # Create a random salt per-value and derive a Fernet key from it
        try:
            salt = os.urandom(16)
            f = cls._get_fernet_with_salt(salt)
            if f is None:
                logger.warning('cryptography not available, storing plaintext (insecure)')
                return plaintext
            token = f.encrypt(plaintext.encode()).decode()
            b64salt = base64.urlsafe_b64encode(salt).decode()
            # Store salt and token compactly as '<b64salt>:<token>' (no literal prefixes)
            return f"{b64salt}:{token}"
        except Exception as e:
            logger.warning(f"Encryption failed, storing plaintext: {e}")
            return plaintext

    @classmethod
    def _decrypt_value(cls, token: str) -> str:
        if token is None:
            return None
        # If cryptography missing, return token as-is
        # If value includes per-value salt in compact '<b64salt>:<token>' format, parse it
        if isinstance(token, str) and ':' in token:
            try:
                b64salt, enc = token.split(':', 1)
                # validate salt looks like base64 of 16 bytes
                salt = base64.urlsafe_b64decode(b64salt.encode())
                if len(salt) >= 8:  # crude sanity check (we expect 16 bytes)
                    f = cls._get_fernet_with_salt(salt)
                    if f is None:
                        return token
                    return f.decrypt(enc.encode()).decode()
            except Exception:
                # not our compact format, continue to legacy handling
                pass

        # Fallback: accept tokens with or without our legacy 'SALT:' prefix or legacy 'ENC:' prefix
        if isinstance(token, str) and token.startswith('SALT:'):
            try:
                rest = token[5:]
                b64salt, enc = rest.split(':ENC:', 1)
                salt = base64.urlsafe_b64decode(b64salt.encode())
                f = cls._get_fernet_with_salt(salt)
                if f is None:
                    return token
                return f.decrypt(enc.encode()).decode()
            except Exception:
                return token

        f = cls._get_fernet()
        if f is None:
            return token
        raw = token
        if raw.startswith('ENC:'):
            raw = raw[4:]
        try:
            return f.decrypt(raw.encode()).decode()
        except Exception:
            return token

    # NOTE: We intentionally do NOT auto-decrypt on attribute access so
    # API/views that read `server_ip` or `real_account_password` will see
    # the stored (encrypted) value. Use the explicit accessors below
    # when plaintext is required (e.g., inside MT5 connection code).

    def __setattr__(self, name: str, value):
        # Intercept assignments to sensitive fields and store encrypted values
        if name in ('server_ip', 'real_account_password'):
            if value is None:
                return object.__setattr__(self, name, None)
            # If value already appears encrypted (our prefix), store as-is
            if isinstance(value, str) and (value.startswith('ENC:') or value.startswith('SALT:') or type(self)._looks_like_compact_encrypted(value)):
                return object.__setattr__(self, name, value)
            # If value looks like an encrypted token (try decrypt), keep as-is
            if isinstance(value, str):
                try:
                    dec = type(self)._decrypt_value(value)
                    # decryption succeeded and returned different value -> it's encrypted
                    if dec is not None and dec != value:
                        return object.__setattr__(self, name, value)
                except Exception:
                    pass
            # Otherwise encrypt plaintext and store
            try:
                enc = type(self)._encrypt_value(str(value))
                return object.__setattr__(self, name, enc)
            except Exception:
                return object.__setattr__(self, name, value)
        return object.__setattr__(self, name, value)

    @classmethod
    def _looks_like_compact_encrypted(cls, value: str) -> bool:
        """Return True if value appears to be in compact '<b64salt>:<token>' encrypted form.
        This avoids confusing plaintext server IPs like '127.0.0.1:443' for encrypted values.
        """
        if not isinstance(value, str) or ':' not in value:
            return False
        left, _ = value.split(':', 1)
        try:
            decoded = base64.urlsafe_b64decode(left.encode())
            # Expect salt length of 8-32 bytes; our code uses 16 bytes
            return 8 <= len(decoded) <= 32
        except Exception:
            return False

    # Explicit decrypt helpers (call these where plaintext is required)
    def get_decrypted_server_ip(self):
        try:
            raw = object.__getattribute__(self, 'server_ip')
        except Exception:
            raw = getattr(self, 'server_ip', None)
        return type(self)._decrypt_value(raw)

    def get_decrypted_real_account_password(self):
        try:
            raw = object.__getattribute__(self, 'real_account_password')
        except Exception:
            raw = getattr(self, 'real_account_password', None)
        return type(self)._decrypt_value(raw)

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
