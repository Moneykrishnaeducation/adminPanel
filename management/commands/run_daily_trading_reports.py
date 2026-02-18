from django.core.management.base import BaseCommand
from adminPanel.tasks.daily_reports import daily_trading_report_runner

class Command(BaseCommand):
    help = 'Run daily trading report runner (enqueue per-account jobs)'

    def add_arguments(self, parser):
        parser.add_argument('--date', type=str, help='Report date in YYYY-MM-DD (defaults to yesterday)')
        parser.add_argument('--dry-run', action='store_true', help='Do not enqueue tasks, only create DB rows')

    def handle(self, *args, **options):
        date = options.get('date')
        dry = options.get('dry_run', False)
        if dry:
            self.stdout.write('Running in dry-run mode (no tasks enqueued)')
        daily_trading_report_runner.delay(date, dry)
        self.stdout.write(self.style.SUCCESS('Daily trading report runner enqueued'))
