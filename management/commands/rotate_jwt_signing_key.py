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


def write_env(replacements: dict, dry_run: bool = True):
    if not os.path.exists(ENV_PATH):
        raise FileNotFoundError(f'.env not found at {ENV_PATH}')

    with open(ENV_PATH, 'r', encoding='utf-8') as f:
        content = f.read()

    for key, val in replacements.items():
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
    help = 'Rotate JWT signing key. Supports RS* (generates PEM files) or HS* (updates JWT_SIGNING_KEY in .env).'

    def add_arguments(self, parser):
        parser.add_argument('--dry-run', action='store_true', help='Show changes but do not write')

    def handle(self, *args, **options):
        dry_run = options.get('dry_run', False)

        alg = getattr(settings, 'JWT_ALGORITHM', settings.SIMPLE_JWT.get('ALGORITHM', 'HS512'))
        alg = alg.upper()

        timestamp = datetime.utcnow().strftime('%Y%m%d%H%M%S')

        if alg.startswith('RS'):
            if not HAS_CRYPTO:
                self.stderr.write('cryptography package is required to generate RSA keys')
                return

            # Create new RSA keypair (2048 bits)
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

            priv_filename = f'jwt_private_{timestamp}.pem'
            pub_filename = f'jwt_public_{timestamp}.pem'
            priv_path = os.path.join(settings.BASE_DIR, priv_filename)
            pub_path = os.path.join(settings.BASE_DIR, pub_filename)

            if dry_run:
                self.stdout.write(f'Would write private key to: {priv_path}')
                self.stdout.write(f'Would write public key to: {pub_path}')
                self.stdout.write('\n.DRY RUN .env changes:')
                content = write_env({'JWT_PRIVATE_KEY_PATH': priv_filename, 'JWT_PUBLIC_KEY_PATH': pub_filename}, dry_run=True)
                self.stdout.write(content)
                return

            # Write files
            with open(priv_path, 'wb') as f:
                f.write(priv_pem)
            with open(pub_path, 'wb') as f:
                f.write(pub_pem)

            write_env({'JWT_PRIVATE_KEY_PATH': priv_filename, 'JWT_PUBLIC_KEY_PATH': pub_filename}, dry_run=False)
            self.stdout.write(self.style.SUCCESS(f'Wrote RSA keys and updated .env to use {priv_filename} / {pub_filename}'))

        else:
            # HS* algorithm: rotate HMAC key
            new_key = secrets.token_hex(64)
            if dry_run:
                self.stdout.write('.DRY RUN .env changes:')
                content = write_env({'JWT_SIGNING_KEY': new_key}, dry_run=True)
                self.stdout.write(content)
                return

            write_env({'JWT_SIGNING_KEY': new_key}, dry_run=False)
            self.stdout.write(self.style.SUCCESS('Updated JWT_SIGNING_KEY in .env'))
import os
import re
import secrets
from django.core.management.base import BaseCommand


ENV_FILENAME = '.env'


def find_env_path():
    # Look in current working dir then walk up
    path = os.getcwd()
    for _ in range(6):
        candidate = os.path.join(path, ENV_FILENAME)
        if os.path.exists(candidate):
            return candidate
        path = os.path.dirname(path)
    return os.path.join(os.getcwd(), ENV_FILENAME)


class Command(BaseCommand):
    help = 'Rotate JWT_SIGNING_KEY in .env to immediately invalidate existing signed tokens (access + refresh).'

    def add_arguments(self, parser):
        parser.add_argument('--dry-run', action='store_true', help='Show new key but do not write to .env')
        parser.add_argument('--length', type=int, default=2048, help='Length of generated key (characters)')

    def handle(self, *args, **options):
        env_path = find_env_path()
        new_key = secrets.token_urlsafe(max(32, options.get('length', 2048)))
        self.stdout.write(f'Using .env path: {env_path}')
        self.stdout.write('WARNING: Rotating the signing key will immediately invalidate ALL existing access and refresh tokens.')

        if options.get('dry_run'):
            self.stdout.write('DRY RUN -- new JWT_SIGNING_KEY (do not apply):')
            self.stdout.write(new_key)
            return

        # Ensure file exists (create if not)
        if not os.path.exists(env_path):
            try:
                with open(env_path, 'w', encoding='utf-8') as f:
                    f.write(f"JWT_SIGNING_KEY={new_key}\n")
                self.stdout.write('Created new .env and wrote JWT_SIGNING_KEY')
                return
            except Exception as e:
                self.stderr.write(f'Failed to create .env: {e}')
                return

        # Read and replace or append
        try:
            with open(env_path, 'r', encoding='utf-8') as f:
                content = f.read()
        except Exception as e:
            self.stderr.write(f'Failed to read .env: {e}')
            return

        pattern = re.compile(r'^(JWT_SIGNING_KEY\s*=\s*).*$', re.MULTILINE)
        if pattern.search(content):
            # Use a callable replacement to avoid accidental backreference
            # interpretation when the new key contains digits like \1
            new_content = pattern.sub(lambda m: m.group(1) + new_key, content)
            action = 'updated'
        else:
            if content and not content.endswith('\n'):
                content += '\n'
            new_content = content + f"JWT_SIGNING_KEY={new_key}\n"
            action = 'appended'

        try:
            with open(env_path, 'w', encoding='utf-8') as f:
                f.write(new_content)
        except Exception as e:
            self.stderr.write(f'Failed to write .env: {e}')
            return

        self.stdout.write(f'Successfully {action} JWT_SIGNING_KEY in {env_path}')
        self.stdout.write('Restart your Django server processes to apply the new key.')
        self.stdout.write('Note: Clients will need to re-authenticate. Refresh tokens will no longer be usable.')
