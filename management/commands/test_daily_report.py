from django.core.management.base import BaseCommand
from django.utils import timezone
from adminPanel.models import TradingAccount
from adminPanel.tasks.daily_reports import process_account_for_daily_report


class Command(BaseCommand):
    help = 'Run per-account daily report for a given user email (synchronous)'

    def add_arguments(self, parser):
        parser.add_argument('--email', type=str, required=True, help='User email')
        parser.add_argument('--date', type=str, help='Report date YYYY-MM-DD (defaults to today)')

    def handle(self, *args, **options):
        email = options['email']
        date_str = options.get('date')
        if date_str:
            report_date = date_str
        else:
            report_date = timezone.now().date().isoformat()

        accounts = TradingAccount.objects.filter(user__email=email)
        if not accounts.exists():
            self.stdout.write(self.style.ERROR(f'No trading accounts found for {email}'))
            return

        for acc in accounts:
            self.stdout.write(f'Processing account {acc.account_id} (id={acc.id}) for {report_date}')
            # Execute the Celery task synchronously for testing using apply()
            result = process_account_for_daily_report.apply(args=(acc.id, report_date))
            # `apply` returns an AsyncResult-like object; extract result value if available
            try:
                res = result.get(timeout=30)
            except Exception:
                res = getattr(result, 'result', None)
            self.stdout.write(f'Result: {res}')
