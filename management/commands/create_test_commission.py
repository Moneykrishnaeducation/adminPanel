from django.core.management.base import BaseCommand
from django.contrib.auth import get_user_model
from adminPanel.models import CommissionTransaction, TradingAccount
from decimal import Decimal
from django.utils import timezone

class Command(BaseCommand):
    help = 'Create a test CommissionTransaction for a given IB email and client email.'

    def add_arguments(self, parser):
        parser.add_argument('--ib_email', type=str, required=True, help='Email of the IB user')
        parser.add_argument('--client_email', type=str, required=True, help='Email of the client user')
        parser.add_argument('--amount', type=float, default=10.0, help='Total commission amount')
        parser.add_argument('--symbol', type=str, default='TESTUSD', help='Symbol for the trade')

    def handle(self, *args, **options):
        User = get_user_model()
        ib_email = options['ib_email']
        client_email = options['client_email']
        amount = Decimal(str(options['amount']))
        symbol = options['symbol']

        try:
            ib_user = User.objects.get(email=ib_email)
            client_user = User.objects.get(email=client_email)
        except User.DoesNotExist:
            self.stdout.write(self.style.ERROR('IB or client user not found.'))
            return

        trading_account = TradingAccount.objects.filter(user=client_user).first()
        if not trading_account:
            self.stdout.write(self.style.ERROR('Client trading account not found.'))
            return

        commission_to_ib = amount * Decimal('0.5')  # 50% for test
        try:
            tx, created = CommissionTransaction.objects.get_or_create(
                position_id='TEST123',
                client_trading_account=trading_account,
                ib_user=ib_user,
                ib_level=1,
                defaults={
                    'client_user': client_user,
                    'total_commission': amount,
                    'commission_to_ib': commission_to_ib,
                    'position_type': 'buy',
                    'position_symbol': symbol,
                    'position_direction': 'in',
                    'created_at': timezone.now()
                }
            )
            if created:
                self.stdout.write(self.style.SUCCESS(f'Test CommissionTransaction created: {tx.id}'))
            else:
                self.stdout.write(self.style.WARNING(f'Test CommissionTransaction already exists: {tx.id}'))
        except Exception as e:
            self.stdout.write(self.style.ERROR(f'Failed to create test commission: {e}'))
