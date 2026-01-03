from django.core.management.base import BaseCommand
from decimal import Decimal
from adminPanel.models import TradingAccount, CommissionTransaction

try:
    from adminPanel.mt5.services import MT5ManagerActions
except Exception:
    MT5ManagerActions = None


class Command(BaseCommand):
    help = 'Update existing CommissionTransaction rows with lot_size and profit from MT5 closed trades.'

    def add_arguments(self, parser):
        parser.add_argument('--account', type=str, help='Optional trading account id to limit the update')

    def handle(self, *args, **options):
        if MT5ManagerActions is None:
            self.stdout.write(self.style.ERROR('MT5ManagerActions not available (check adminPanel.mt5.services import).'))
            return

        account_filter = options.get('account')
        accounts = TradingAccount.objects.all()
        if account_filter:
            accounts = accounts.filter(account_id=account_filter)

        mt5 = MT5ManagerActions()
        total_updated = 0
        total_checked = 0

        for account in accounts:
            try:
                closed_trades = mt5.get_closed_trades(account.account_id)
            except Exception as e:
                self.stdout.write(self.style.WARNING(f'Failed to fetch closed trades for account {account.account_id}: {e}'))
                continue

            self.stdout.write(f'Account {account.account_id}: fetched {len(closed_trades)} closed trades')

            for deal in closed_trades:
                # Determine trade id: prefer Deal, fallback to Position
                trade_id = str(getattr(deal, 'Deal', None) or getattr(deal, 'Position', None) or '')
                if not trade_id or trade_id in ('None', ''):
                    continue
                # Compute lot_size from VolumeClosed when available, fallback to Volume.
                volume_src = getattr(deal, 'VolumeClosed', None) or getattr(deal, 'Volume', 0)
                try:
                    volume_val = float(volume_src or 0)
                except Exception:
                    volume_val = 0.0
                try:
                    lot_size = float(volume_val) / 10000.0 if volume_val > 0 else 0.0
                except Exception:
                    lot_size = 0.0
                # Profit
                try:
                    profit = float(getattr(deal, 'Profit', 0) or 0)
                except Exception:
                    profit = 0.0

                # Update matching CommissionTransaction rows
                qs = CommissionTransaction.objects.filter(client_trading_account=account, position_id=trade_id)
                total_checked += qs.count()
                if qs.exists():
                    updated = qs.update(lot_size=lot_size, profit=Decimal(str(profit)))
                    total_updated += updated
                    self.stdout.write(f'Updated {updated} commission(s) for trade {trade_id} (lot_size={lot_size}, profit={profit})')

        self.stdout.write(self.style.SUCCESS(f'Update complete. Checked {total_checked} matching commission rows, updated {total_updated} rows.'))
