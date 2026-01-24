import logging
import requests
import time
from django.conf import settings

logger = logging.getLogger(__name__)


def verify_email_with_abstractapi(email: str) -> (bool, str):
    key = getattr(settings, 'ABSTRACTAPI_EMAIL_VALIDATION_KEY', None)
    if not key:
        return True, 'no_key'
    url = 'https://emailvalidation.abstractapi.com/v1/'
    attempts = getattr(settings, 'EMAIL_VERIFICATION_ATTEMPTS', 2)
    delay = 0.5
    for i in range(attempts):
        try:
            resp = requests.get(url, params={'api_key': key, 'email': email}, timeout=5)
            if resp.status_code != 200:
                logger.debug('AbstractAPI non-200: %s', resp.status_code)
                return True, 'unknown'
            data = resp.json()
            # AbstractAPI returns `deliverability` with values like 'DELIVERABLE' or 'UNDELIVERABLE'
            deliverability = (data.get('deliverability') or '').upper()
            if deliverability == 'DELIVERABLE' or deliverability == 'UNKNOWN':
                return True, 'deliverable'
            return False, deliverability.lower()
        except Exception as e:
            logger.exception('AbstractAPI check failed (attempt %s): %s', i + 1, e)
            if i == attempts - 1:
                return True, 'error'
            try:
                time.sleep(delay * (2 ** i))
            except Exception:
                pass


def verify_email_with_zerobounce(email: str) -> (bool, str):
    key = getattr(settings, 'ZEROBOUNCE_API_KEY', None)
    if not key:
        return True, 'no_key'
    url = 'https://api.zerobounce.net/v2/validate'
    attempts = getattr(settings, 'EMAIL_VERIFICATION_ATTEMPTS', 2)
    delay = 0.5
    for i in range(attempts):
        try:
            resp = requests.get(url, params={'api_key': key, 'email': email}, timeout=5)
            if resp.status_code != 200:
                logger.debug('ZeroBounce non-200: %s', resp.status_code)
                return True, 'unknown'
            data = resp.json()
            # ZeroBounce returns `status` like 'valid', 'invalid', 'catch-all'
            status = (data.get('status') or '').lower()
            if status in ('valid', 'catch-all', 'unknown'):
                return True, status
            return False, status
        except Exception as e:
            logger.exception('ZeroBounce check failed (attempt %s): %s', i + 1, e)
            if i == attempts - 1:
                return True, 'error'
            try:
                time.sleep(delay * (2 ** i))
            except Exception:
                pass


def verify_email_with_disify(email: str) -> (bool, str):
    """Use Disify public API to validate email. No API key required.

    Returns (True, reason) when likely deliverable; (False, reason) when undeliverable.
    """
    url = f"https://disify.org/api/email/{email}"
    attempts = getattr(settings, 'EMAIL_VERIFICATION_ATTEMPTS', 2)
    delay = 0.5
    for i in range(attempts):
        try:
            resp = requests.get(url, timeout=5)
            if resp.status_code != 200:
                logger.debug('Disify non-200: %s', resp.status_code)
                return True, 'unknown'
            data = resp.json()
            # Disify response contains fields like 'format', 'mx', 'dns', 'disposable'
            disposable = data.get('disposable')
            mx = data.get('mx')
            fmt = data.get('format')
            if disposable:
                return False, 'disposable'
            if mx and fmt:
                return True, 'deliverable'
            # If format ok and DNS present but MX False, treat as undeliverable (stricter)
            # Some providers report DNS presence without MX; treat this as undeliverable
            # to avoid sending OTPs to addresses that likely can't receive mail.
            if fmt and data.get('dns'):
                return False, 'dns_only'
            return False, 'undeliverable'
        except Exception as e:
            logger.exception('Disify check failed (attempt %s): %s', i + 1, e)
            if i == attempts - 1:
                return True, 'error'
            try:
                time.sleep(delay * (2 ** i))
            except Exception:
                pass


def verify_email_third_party(email: str) -> (bool, str):
    provider = getattr(settings, 'EMAIL_VERIFICATION_PROVIDER', None)
    if not provider:
        return True, 'none'
    provider = provider.lower()
    if provider == 'abstract':
        return verify_email_with_abstractapi(email)
    if provider == 'zerobounce':
        return verify_email_with_zerobounce(email)
    if provider == 'disify':
        return verify_email_with_disify(email)
    # Unknown provider: do not block
    logger.debug('Unknown email verification provider configured: %s', provider)
    return True, 'unknown_provider'
