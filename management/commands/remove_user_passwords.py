from django.core.management.base import BaseCommand
from django.db import transaction
from adminPanel.models import CustomUser


class Command(BaseCommand):
    help = "Remove all users' usable passwords and clear plaintext Access_Key."

    def add_arguments(self, parser):
        parser.add_argument(
            '--yes',
            action='store_true',
            help='Run without confirmation prompt'
        )

    def handle(self, *args, **options):
        confirm = options.get('yes', False)

        total = CustomUser.objects.count()
        if total == 0:
            self.stdout.write(self.style.WARNING('No users found.'))
            return

        if not confirm:
            answer = input(f"About to remove passwords for {total} users. Continue? [y/N]: ")
            if answer.strip().lower() != 'y':
                self.stdout.write(self.style.ERROR('Aborted by user.'))
                return

        batch_size = 500
        processed = 0

        # Use a transaction per batch to avoid long transactions
        qs = CustomUser.objects.all().order_by('pk')
        pks = list(qs.values_list('pk', flat=True))

        for i in range(0, len(pks), batch_size):
            chunk = pks[i:i+batch_size]
            with transaction.atomic():
                users = CustomUser.objects.select_for_update().filter(pk__in=chunk)
                for u in users:
                    try:
                        # Mark password unusable (Django stores a special value)
                        u.set_unusable_password()
                        # Clear plaintext Access_Key if present
                        if hasattr(u, 'Access_Key'):
                            u.Access_Key = None
                        u.save(update_fields=['password', 'Access_Key'] if hasattr(u, 'Access_Key') else ['password'])
                        processed += 1
                    except Exception as e:
                        self.stderr.write(f"Failed to process user {u.pk}: {e}")

            self.stdout.write(f"Processed {min(i+batch_size, len(pks))}/{len(pks)} users...")

        self.stdout.write(self.style.SUCCESS(f"Completed: removed usable passwords for {processed} users."))
