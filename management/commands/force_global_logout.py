from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = 'Force global logout by blacklisting all outstanding tokens. Optionally rotate signing key.'

    def add_arguments(self, parser):
        parser.add_argument('--dry-run', action='store_true', help='Show how many tokens would be blacklisted')
        parser.add_argument('--rotate-key', action='store_true', help='Also rotate the JWT signing key after blacklisting')

    def handle(self, *args, **options):
        dry_run = options.get('dry_run')
        rotate_key = options.get('rotate_key')

        try:
            from rest_framework_simplejwt.token_blacklist.models import OutstandingToken, BlacklistedToken
        except Exception as e:
            self.stderr.write('token_blacklist app not available or import failed: %s' % e)
            return

        tokens = OutstandingToken.objects.all()
        total = tokens.count()
        if dry_run:
            self.stdout.write(f'Outstanding tokens: {total}')
        else:
            blacklisted = 0
            for t in tokens:
                if not BlacklistedToken.objects.filter(token=t).exists():
                    try:
                        BlacklistedToken.objects.create(token=t)
                        blacklisted += 1
                    except Exception as e:
                        self.stderr.write(f'Failed to blacklist token {t.jti}: {e}')
            self.stdout.write(f'Blacklisted {blacklisted}/{total} outstanding tokens')

        if rotate_key:
            # Call the rotate_jwt_signing_key management command (supports --dry-run)
            try:
                from django.core.management import call_command
                if dry_run:
                    call_command('rotate_jwt_signing_key', '--dry-run')
                else:
                    call_command('rotate_jwt_signing_key')
                self.stdout.write(self.style.SUCCESS('rotate_jwt_signing_key executed'))
            except Exception as e:
                self.stderr.write(f'Failed to rotate signing key: {e}')
