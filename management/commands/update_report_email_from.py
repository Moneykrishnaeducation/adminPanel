from django.core.management.base import BaseCommand

class Command(BaseCommand):
    help = 'Update existing ReportGenerationSchedule.email_from to support@vtindex.com (if different)'

    def add_arguments(self, parser):
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='Show what would be changed without modifying the database'
        )
        parser.add_argument(
            '--confirm',
            action='store_true',
            help='Apply the changes'
        )

    def handle(self, *args, **options):
        from adminPanel.models import ReportGenerationSchedule

        target = 'support@vtindex.com'
        schedules = ReportGenerationSchedule.objects.all()
        changed = 0
        total = schedules.count()

        if total == 0:
            self.stdout.write(self.style.WARNING('No ReportGenerationSchedule entries found'))
            return

        for sched in schedules:
            if sched.email_from != target:
                self.stdout.write(f"Would change schedule '{sched.name}' (id={sched.id}) from '{sched.email_from}' to '{target}'")
                if options['confirm'] and not options['dry_run']:
                    sched.email_from = target
                    sched.save()
                    changed += 1
            else:
                self.stdout.write(f"Schedule '{sched.name}' (id={sched.id}) already has '{target}'")

        if options['confirm'] and not options['dry_run']:
            self.stdout.write(self.style.SUCCESS(f'Updated {changed}/{total} schedules to {target}'))
        else:
            self.stdout.write(self.style.WARNING('Dry run mode or --confirm not provided; no changes applied'))
