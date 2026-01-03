from django.core.management.base import BaseCommand
from adminPanel.models import CustomUser, TradingAccount, CommissionTransaction
from adminPanel.mt5.process_commission import process_commission_for_trade
# You must implement this function to fetch closed trades from MT5 for a given account
# Example: from adminPanel.mt5.services import fetch_closed_trades_for_account

from django.db import IntegrityError
from adminPanel.mt5.services import MT5ManagerActions

def fetch_closed_trades_for_account(account_id):
    mt5 = MT5ManagerActions()
    closed_trades = mt5.get_closed_trades(account_id)
    # Map MT5 deal fields to expected dict format
    result = []
    for deal in closed_trades:
        # Prefer VolumeClosed when available, fallback to Volume
        volume_src = getattr(deal, 'VolumeClosed', None) or getattr(deal, 'Volume', 0)
        try:
            volume_val = float(volume_src or 0)
        except Exception:
            volume_val = 0.0
        lot_size = float(volume_val) / 10000.0 if volume_val > 0 else 0.0
        result.append({
            'trade_id': str(getattr(deal, 'Position', None)),
            'symbol': getattr(deal, 'Symbol', ''),
            'position_type': 'buy' if getattr(deal, 'Type', 0) == 0 else 'sell',
            'position_direction': 'in',
            'total_commission': float(getattr(deal, 'Commission', 0)),
            'lot_size': lot_size,
        })
    return result

class Command(BaseCommand):
    help = 'Backfill IB commissions for all past closed trades (MT5 fetch required)'

    def handle(self, *args, **options):
        ib_clients = CustomUser.objects.filter(parent_ib__isnull=False)
        for client in ib_clients:
            trading_accounts = TradingAccount.objects.filter(user=client)
            for account in trading_accounts:
                closed_trades = fetch_closed_trades_for_account(account.account_id)
                for trade in closed_trades:
                    # Check if commission already exists for this trade
                    exists = CommissionTransaction.objects.filter(
                        client_user=client,
                        client_trading_account=account,
                        position_id=trade['trade_id']
                    ).exists()
                    if exists:
                        continue
                    # Prepare trade dict for commission processing
                    trade_data = {
                        'client_email': client.email,
                        'trade_id': trade['trade_id'],
                        'trading_account_id': account.id,
                        'symbol': trade['symbol'],
                        'position_type': trade.get('position_type', 'buy'),
                        'position_direction': trade.get('position_direction', 'in'),
                        'total_commission': trade['total_commission'],
                        'lot_size': trade.get('lot_size', 1.0),
                        'profit': trade.get('profit', 0.0),
                    }
                    try:
                        process_commission_for_trade(trade_data)
                        self.stdout.write(self.style.SUCCESS(f'Commission created for trade {trade["trade_id"]} (client: {client.email})'))
                    except IntegrityError:
                        # Duplicate detected, likely already created
                        self.stdout.write(self.style.WARNING(f'Commission already exists for trade {trade["trade_id"]} (client: {client.email})'))
                    except Exception as e:
                        self.stdout.write(self.style.ERROR(f'Error processing trade {trade["trade_id"]}: {e}'))
        self.stdout.write(self.style.SUCCESS('Backfill complete.'))
