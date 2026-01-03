from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = 'Blacklist all outstanding refresh tokens (rest_framework_simplejwt token_blacklist)'

    def add_arguments(self, parser):
        parser.add_argument('--dry-run', action='store_true', help='Show how many tokens would be blacklisted')

    def handle(self, *args, **options):
        try:
            from rest_framework_simplejwt.token_blacklist.models import OutstandingToken, BlacklistedToken
        except Exception as e:
            self.stderr.write('token_blacklist app not available or import failed: %s' % e)
            return

        tokens = OutstandingToken.objects.all()
        total = tokens.count()
        if options.get('dry_run'):
            self.stdout.write(f'Outstanding tokens: {total}')
            return

        blacklisted = 0
        for t in tokens:
            if not BlacklistedToken.objects.filter(token=t).exists():
                try:
                    BlacklistedToken.objects.create(token=t)
                    blacklisted += 1
                except Exception as e:
                    self.stderr.write(f'Failed to blacklist token {t.jti}: {e}')
        self.stdout.write(f'Blacklisted {blacklisted}/{total} outstanding tokens')
