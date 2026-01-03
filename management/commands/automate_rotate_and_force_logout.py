import os
import re
import secrets
from datetime import datetime
from django.core.management.base import BaseCommand
from django.conf import settings

try:
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import rsa
    from cryptography.hazmat.backends import default_backend
    HAS_CRYPTO = True
except Exception:
    HAS_CRYPTO = False


ENV_PATH = os.path.join(settings.BASE_DIR, '.env')


def _write_env_updates(updates: dict, dry_run: bool = True):
    if not os.path.exists(ENV_PATH):
        raise FileNotFoundError(f'.env not found at {ENV_PATH}')

    with open(ENV_PATH, 'r', encoding='utf-8') as f:
        content = f.read()

    for key, val in updates.items():
        pattern = re.compile(rf'^{re.escape(key)}=.*$', re.MULTILINE)
        if pattern.search(content):
            content = pattern.sub(f'{key}={val}', content)
        else:
            content += f"\n{key}={val}"

    if dry_run:
        return content

    with open(ENV_PATH, 'w', encoding='utf-8') as f:
        f.write(content)

    return content


class Command(BaseCommand):
    help = 'Automate key rotation (PEM generation or HS key) and force global logout. Supports dry-run.'

    def add_arguments(self, parser):
        parser.add_argument('--algorithm', type=str, default=None, help='Algorithm to rotate to (e.g. RS512 or HS512). Defaults to settings.JWT_ALGORITHM')
        parser.add_argument('--dry-run', action='store_true', help='Show changes but do not write files or apply rotation')
        parser.add_argument('--pem-dir', type=str, default=None, help='Directory to write PEM files (defaults to project root)')
        parser.add_argument('--blacklist-only', action='store_true', help='Only blacklist outstanding tokens without rotating keys')

    def handle(self, *args, **options):
        dry_run = options.get('dry_run', False)
        pem_dir = options.get('pem_dir') or settings.BASE_DIR
        algorithm = (options.get('algorithm') or getattr(settings, 'JWT_ALGORITHM', settings.SIMPLE_JWT.get('ALGORITHM', 'HS512'))).upper()
        blacklist_only = options.get('blacklist_only', False)

        self.stdout.write(f'Using algorithm: {algorithm}')
        if dry_run:
            self.stdout.write('DRY RUN mode: no files will be written and no DB mutations will be made')

        if blacklist_only:
            # Only call force_global_logout (dry-run if requested)
            try:
                from django.core.management import call_command
                if dry_run:
                    call_command('force_global_logout', '--dry-run')
                else:
                    call_command('force_global_logout')
                self.stdout.write(self.style.SUCCESS('force_global_logout executed'))
            except Exception as e:
                self.stderr.write(f'Failed to run force_global_logout: {e}')
            return

        updates = {}

        if algorithm.startswith('RS'):
            if not HAS_CRYPTO:
                self.stderr.write('cryptography is required to generate RSA keys. Install it in the environment.')
                return

            # Generate RSA keypair
            key = rsa.generate_private_key(public_exponent=65537, key_size=2048, backend=default_backend())
            priv_pem = key.private_bytes(
                encoding=serialization.Encoding.PEM,
                format=serialization.PrivateFormat.TraditionalOpenSSL,
                encryption_algorithm=serialization.NoEncryption(),
            )
            pub_pem = key.public_key().public_bytes(
                encoding=serialization.Encoding.PEM,
                format=serialization.PublicFormat.SubjectPublicKeyInfo,
            )

            timestamp = datetime.utcnow().strftime('%Y%m%d%H%M%S')
            priv_filename = f'jwt_private_{timestamp}.pem'
            pub_filename = f'jwt_public_{timestamp}.pem'
            priv_path = os.path.join(pem_dir, priv_filename)
            pub_path = os.path.join(pem_dir, pub_filename)

            if dry_run:
                self.stdout.write(f'Would write private PEM to: {priv_path}')
                self.stdout.write(f'Would write public PEM to:  {pub_path}')
                # Show .env changes
                updates = {'JWT_PRIVATE_KEY_PATH': priv_filename, 'JWT_PUBLIC_KEY_PATH': pub_filename}
                preview = _write_env_updates(updates, dry_run=True)
                self.stdout.write('\n.DRY RUN .env changes:')
                self.stdout.write(preview)
            else:
                # Write PEM files
                with open(priv_path, 'wb') as f:
                    f.write(priv_pem)
                with open(pub_path, 'wb') as f:
                    f.write(pub_pem)
                updates = {'JWT_PRIVATE_KEY_PATH': priv_filename, 'JWT_PUBLIC_KEY_PATH': pub_filename}
                _write_env_updates(updates, dry_run=False)
                self.stdout.write(self.style.SUCCESS(f'Wrote PEM files: {priv_path}, {pub_path}'))

        else:
            # HS* path — generate a strong HMAC key
            new_key = secrets.token_urlsafe(96)
            updates = {'JWT_SIGNING_KEY': new_key}
            if dry_run:
                preview = _write_env_updates(updates, dry_run=True)
                self.stdout.write('\n.DRY RUN .env changes:')
                self.stdout.write(preview)
            else:
                _write_env_updates(updates, dry_run=False)
                self.stdout.write(self.style.SUCCESS('Updated JWT_SIGNING_KEY in .env'))

        # Now force global logout (blacklist outstanding tokens). If dry-run, call with --dry-run
        try:
            from django.core.management import call_command
            if dry_run:
                call_command('force_global_logout', '--dry-run')
            else:
                call_command('force_global_logout')
            self.stdout.write(self.style.SUCCESS('force_global_logout executed'))
        except Exception as e:
            self.stderr.write(f'Failed to run force_global_logout: {e}')

        # Final notes
        if not dry_run:
            self.stdout.write('\nRotation complete. Please restart Django server processes to apply new keys.')
            self.stdout.write('Clients will need to re-authenticate after key rotation.')
