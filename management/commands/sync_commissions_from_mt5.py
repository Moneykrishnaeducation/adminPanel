from django.core.management.base import BaseCommand
from django.db import IntegrityError
from adminPanel.models import TradingAccount, CommissionTransaction
from adminPanel.mt5.services import MT5ManagerActions
from adminPanel.mt5.process_commission import process_commission_for_trade
from datetime import datetime, timedelta
from django.utils import timezone
import time
import logging

logger = logging.getLogger(__name__)

class Command(BaseCommand):
    help = 'Sync closed trades from MT5 and create IB commissions in real time.'
    
    # Track last check time for each account to implement smart cooldown
    account_last_check = {}

    def get_active_accounts(self):
        """
        EXPANDED FILTERING: Include ALL accounts with potential trading activity.
        FIXED: No longer excludes accounts without parent_ib to prevent missing trades.
        
        This ensures all trading history is captured, even from accounts
        that might not have commission relationships configured.
        """
        from django.db.models import Q
        from adminPanel.models import TradeGroup
        
        # Get demo group names to exclude
        demo_group_names = list(TradeGroup.objects.filter(type='demo').values_list('name', flat=True))
        
        # FIXED: Include ALL non-demo accounts to prevent missing trade history
        # Commission processing logic will handle whether to create commission records
        active_accounts = TradingAccount.objects.exclude(
            group_name__in=demo_group_names
        ).distinct().select_related('user', 'user__parent_ib')
        
        # Fallback: If still too few accounts, add first 100 non-demo accounts
        if active_accounts.count() < 50:
            additional_accounts = TradingAccount.objects.exclude(
                group_name__in=demo_group_names
            ).exclude(
                id__in=active_accounts.values_list('id', flat=True)
            ).select_related('user')[:100]
            
            # Combine using Python (simpler than SQL UNION)
            active_ids = list(active_accounts.values_list('id', flat=True))
            additional_ids = list(additional_accounts.values_list('id', flat=True))
            all_ids = active_ids + additional_ids
            
            active_accounts = TradingAccount.objects.filter(
                id__in=all_ids
            ).select_related('user', 'user__parent_ib')
        
        return active_accounts
    
    def should_check_account(self, account_id):
        """
        Cooldown logic: Don't check same account too frequently.
        Reduces redundant MT5 API calls.
        Lightning mode: 500ms cooldown for faster detection!
        """
        last_check = self.account_last_check.get(account_id, 0)
        time_since_check = time.time() - last_check
        
        # Lightning mode: Check frequently for first 10 accounts, minimal cooldown for others
        if len(self.account_last_check) < 10:
            return True
        return time_since_check > 0.5  # 500ms cooldown (lightning fast!)

    def handle(self, *args, **options):
        start_time = time.time()
        mt5 = MT5ManagerActions()
        
        # Use smart filtering instead of checking all accounts
        accounts = self.get_active_accounts()
        query_time = time.time()
        created_count = 0
        checked_count = 0
        
        # Lightning mode: Silent operation for maximum speed
        
        # Lightning mode: Process accounts as fast as possible
        for account in accounts:
            # Skip if checked too recently (cooldown)
            if not self.should_check_account(account.id):
                continue
                
            checked_count += 1
            
            # print(f"Processing account: {account.account_id} for user: {account.user.email}")
            mt5_start = time.time()
            
            # CONTINUOUS MODE: Check ALL closed trades (no time limit)
            # This ensures we catch any missed trades from any time period
            closed_trades = mt5.get_closed_trades(account.account_id, from_date=None)
            
            mt5_end = time.time()
            
            # Update last check time
            self.account_last_check[account.id] = time.time()
            
            # Lightning mode: Logging disabled for maximum speed
            # mt5_duration = (mt5_end - mt5_start) * 1000
            # if mt5_duration > 50:
            #     logger.warning(f"MT5 query for account {account.account_id} took {mt5_duration:.1f}ms")
            
            for deal in closed_trades:
                # Use Deal as trade_id if available, fallback to Position
                trade_id = str(getattr(deal, 'Deal', None))
                if not trade_id or trade_id == 'None':
                    trade_id = str(getattr(deal, 'Position', None))
                if not trade_id or trade_id == 'None':
                    continue
                if CommissionTransaction.objects.filter(position_id=trade_id, client_trading_account=account).exists():
                    continue
                # Extract volume from the deal and convert to standard lots.
                # Prefer VolumeClosed (used when selecting closed deals), fallback to Volume.
                # MT5 usually stores volume in units where 10000 = 1.0 lot.
                volume_src = getattr(deal, 'VolumeClosed', None) or getattr(deal, 'Volume', 0)
                try:
                    volume_val = float(volume_src or 0)
                except Exception:
                    volume_val = 0.0
                lot_size = float(volume_val) / 10000.0 if volume_val > 0 else 0.0
                
                # Extract deal ticket and close time from MT5 deal object
                deal_ticket = str(getattr(deal, 'Deal', None))
                mt5_close_time_unix = getattr(deal, 'Time', None)  # Unix timestamp
                
                # Convert Unix timestamp to timezone-aware datetime
                mt5_close_time = None
                if mt5_close_time_unix:
                    try:
                        # MT5 Time is Unix timestamp (seconds since epoch)
                        mt5_close_time = timezone.make_aware(datetime.fromtimestamp(int(mt5_close_time_unix)))
                    except (ValueError, TypeError, OSError) as e:
                        # If conversion fails, log and continue without the timestamp
                        import logging
                        logging.getLogger(__name__).warning(f"Failed to convert MT5 time {mt5_close_time_unix}: {e}")
                
                trade_data = {
                    'client_email': account.user.email,
                    'trade_id': trade_id,
                    'trading_account_id': account.id,
                    'symbol': getattr(deal, 'Symbol', ''),
                    'position_type': 'buy' if getattr(deal, 'Type', 0) == 0 else 'sell',
                    'position_direction': 'in',
                    'total_commission': float(getattr(deal, 'Commission', 0)),
                    'lot_size': lot_size,
                    'profit': float(getattr(deal, 'Profit', 0) or 0),
                    'deal_ticket': deal_ticket if deal_ticket and deal_ticket != 'None' else None,
                    'mt5_close_time': mt5_close_time,  # Pass datetime object directly
                }
                try:
                    # process_commission_for_trade internally creates CommissionTransaction(s).
                    # It may raise IntegrityError if duplicates are attempted; catch and ignore.
                    result = process_commission_for_trade(trade_data)
                    
                    if result:
                        created_count += 1
                        # Silent operation - logging removed for speed
                except IntegrityError:
                    # Duplicate detected (likely created by a concurrent run) - ignore
                    continue
                except Exception as e:
                    # Log other exceptions but continue with next trade
                    try:
                        import logging
                        logging.getLogger(__name__).error(f"Error processing trade {trade_id}: {e}")
                    except Exception:
                        pass
        
        # Log cycle summary - only show when commissions are created
        total_time = (time.time() - start_time) * 1000
        if created_count > 0:
            logger.info(f"⚡ {created_count} commission(s) created | {checked_count}/{accounts.count()} accounts | {total_time:.1f}ms")
        # Silent operation - no output when no new commissions
