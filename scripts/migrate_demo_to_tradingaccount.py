from adminPanel.models import DemoAccount, TradingAccount
from django.db import transaction
from decimal import Decimal

def migrate_demo_to_tradingaccount():
    with transaction.atomic():
        migrated = 0
        for demo in DemoAccount.objects.all():
            # Check if already exists in TradingAccount
            if TradingAccount.objects.filter(account_id=demo.account_id).exists():
                continue
            TradingAccount.objects.create(
                user=demo.user,
                account_id=demo.account_id,
                account_name=demo.account_name or f"Demo Account {demo.account_id}",
                leverage=int(demo.leverage) if demo.leverage else 100,
                balance=demo.balance if demo.balance else Decimal('10000.00'),
                is_enabled=demo.is_enabled,
                is_algo_enabled=getattr(demo, 'is_algo_enabled', True),
                account_type='demo',
            )
            migrated += 1
        print(f"Migrated {migrated} demo accounts to TradingAccount.")

if __name__ == '__main__':
    migrate_demo_to_tradingaccount()
