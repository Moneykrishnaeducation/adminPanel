import os
from pathlib import Path
from typing import Set


DATA_FILE = Path(__file__).resolve().parent.parent.joinpath('data', 'disposable_email_domains.txt')


def _load_builtin_domains() -> Set[str]:
    return {
        'mailinator.com', '10minutemail.com', 'temp-mail.org', 'trashmail.com',
        'guerrillamail.com', 'yopmail.com', 'dispostable.com', 'maildrop.cc',
        'tempmail.com', 'getnada.com', 'fakeinbox.com'
    }


def load_disposable_domains() -> Set[str]:
    domains = set()
    try:
        if DATA_FILE.exists():
            with open(DATA_FILE, 'r', encoding='utf-8') as fh:
                for line in fh:
                    d = line.strip()
                    if d and not d.startswith('#'):
                        domains.add(d.lower())
    except Exception:
        return _load_builtin_domains()

    if not domains:
        return _load_builtin_domains()

    return domains


_DISPOSABLE_DOMAINS = load_disposable_domains()


def _domain_variants(domain: str):
    parts = domain.split('.')
    for i in range(len(parts) - 1):
        yield '.'.join(parts[i:])


def is_disposable_email(email: str) -> bool:
    try:
        domain = email.split('@', 1)[1].lower().strip()
    except Exception:
        return False

    for variant in _domain_variants(domain):
        if variant in _DISPOSABLE_DOMAINS:
            return True
    return False


def validate_signup_email(email: str) -> None:
    if not email:
        raise ValueError('Email must be provided')
    if is_disposable_email(email):
        raise ValueError('Disposable or temporary email addresses are not allowed')
