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
            # Call the processing function directly (synchronous)
            try:
                res = process_account_for_daily_report(acc.id, report_date)
            except Exception as exc:
                res = {'status': 'failed', 'error': str(exc)}
            self.stdout.write(f'Result: {res}')
