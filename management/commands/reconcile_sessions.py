from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

class Command(BaseCommand):
    help = 'Reconcile UserSession rows with OutstandingToken records so server-side token blacklisting can operate on legacy sessions.'

    def add_arguments(self, parser):
        parser.add_argument('--dry-run', action='store_true', help='Show what would be created without making changes')
        parser.add_argument('--limit', type=int, default=0, help='Limit number of sessions to process (0 = no limit)')
        parser.add_argument('--user', type=str, help='Process sessions only for the given user id or email')

    def handle(self, *args, **options):
        dry_run = options.get('dry_run')
        limit = options.get('limit') or 0
        user_filter = options.get('user')

        try:
            from adminPanel.models import UserSession
        except Exception as e:
            raise CommandError(f'Failed to import UserSession model: {e}')

        try:
            from rest_framework_simplejwt.token_blacklist.models import OutstandingToken
        except Exception:
            OutstandingToken = None

        qs = UserSession.objects.all().order_by('-created_at')
        if user_filter:
            # try by numeric id first, otherwise by email
            try:
                uid = int(user_filter)
                qs = qs.filter(user__id=uid)
            except Exception:
                qs = qs.filter(user__email__iexact=user_filter)

        total = qs.count()
        self.stdout.write(self.style.NOTICE(f'Found {total} UserSession records to inspect'))

        created = 0
        skipped = 0
        processed = 0

        for us in qs:
            if limit and processed >= limit:
                break
            processed += 1

            jti = us.jti
            if not jti:
                skipped += 1
                continue

            if OutstandingToken is None:
                self.stdout.write(self.style.WARNING('token_blacklist app not available; cannot create OutstandingToken records'))
                skipped += 1
                continue

            try:
                exists = OutstandingToken.objects.filter(user=us.user, jti=jti).exists()
            except Exception:
                # Some environments may have a broken OutstandingToken; skip
                self.stdout.write(self.style.WARNING(f'Could not query OutstandingToken for jti={jti}; skipping'))
                skipped += 1
                continue

            if exists:
                skipped += 1
                continue

            self.stdout.write(f'Will create OutstandingToken for user={us.user} jti={jti} expires_at={us.expires_at}')
            if not dry_run:
                try:
                    # Use a recognizable token string since original refresh is not available
                    token_string = f'reconciled:{jti}'
                    OutstandingToken.objects.create(
                        user=us.user,
                        jti=jti,
                        token=token_string,
                        created_at=us.created_at or timezone.now(),
                        expires_at=us.expires_at or timezone.now()
                    )
                    created += 1
                except Exception as e:
                    self.stdout.write(self.style.ERROR(f'Failed to create OutstandingToken for jti={jti}: {e}'))
                    skipped += 1
            else:
                created += 1

        self.stdout.write(self.style.SUCCESS(f'Processed {processed} sessions; created={created}; skipped={skipped}'))