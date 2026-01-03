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
    help = 'Sync closed trades from MT5 and create IB commissions - INCLUDES ALL TRADING ACCOUNTS'
    
    # Track last check time for each account to implement smart cooldown
    account_last_check = {}

    def get_active_accounts(self):
        """
        EXPANDED FILTERING: Include ALL accounts with trading activity.
        This fixes the missing trade history issue by not excluding accounts
        without parent_ib that may still have trading activity.
        """
        from django.db.models import Q
        from adminPanel.models import TradeGroup
        
        # Get demo group names to exclude
        demo_group_names = list(TradeGroup.objects.filter(type='demo').values_list('name', flat=True))
        
        # FIXED: Include ALL non-demo accounts with ANY trading activity
        # This ensures we don't miss trades from accounts without parent_ib
        all_active_accounts = TradingAccount.objects.exclude(
            group_name__in=demo_group_names
        ).distinct().select_related('user', 'user__parent_ib')
        
        # Priority 1: IB client accounts (always process these)
        ib_client_accounts = all_active_accounts.filter(user__parent_ib__isnull=False)
        
        # Priority 2: Non-IB accounts that have trading activity
        # Note: We'll check if they should generate commissions in process_commission_for_trade
        non_ib_accounts = all_active_accounts.filter(user__parent_ib__isnull=True)
        
        # Combine both sets - this ensures ALL trading accounts are checked
        combined_accounts = ib_client_accounts.union(non_ib_accounts)
        
        logger.info(f"Account filtering: IB clients: {ib_client_accounts.count()}, Non-IB: {non_ib_accounts.count()}, Total: {combined_accounts.count()}")
        
        return combined_accounts
    
    def should_check_account(self, account_id):
        """
        Cooldown logic: Don't check same account too frequently.
        Reduces redundant MT5 API calls.
        """
        last_check = self.account_last_check.get(account_id, 0)
        time_since_check = time.time() - last_check
        
        # Check frequently for first 10 accounts, minimal cooldown for others
        if len(self.account_last_check) < 10:
            return True
        return time_since_check > 0.5  # 500ms cooldown

    def handle(self, *args, **options):
        start_time = time.time()
        mt5 = MT5ManagerActions()
        
        # Use expanded filtering to include ALL trading accounts
        accounts = self.get_active_accounts()
        query_time = time.time()
        created_count = 0
        checked_count = 0
        skipped_count = 0
        
        logger.info(f"Starting sync for {accounts.count()} accounts (IB + Non-IB)")
        
        # Process accounts as fast as possible
        for account in accounts:
            # Skip if checked too recently (cooldown)
            if not self.should_check_account(account.id):
                skipped_count += 1
                continue
                
            checked_count += 1
            
            mt5_start = time.time()
            
            # Check ALL closed trades (no time limit) to catch any missed trades
            closed_trades = mt5.get_closed_trades(account.account_id, from_date=None)
            
            mt5_end = time.time()
            
            # Update last check time
            self.account_last_check[account.id] = time.time()
            
            for deal in closed_trades:
                # Use Deal as trade_id if available, fallback to Position
                trade_id = str(getattr(deal, 'Deal', None))
                if not trade_id or trade_id == 'None':
                    trade_id = str(getattr(deal, 'Position', None))
                if not trade_id or trade_id == 'None':
                    continue
                    
                # Skip if commission already exists
                if CommissionTransaction.objects.filter(position_id=trade_id, client_trading_account=account).exists():
                    continue
                    
                # Extract volume from the deal and convert to standard lots
                volume_src = getattr(deal, 'VolumeClosed', None) or getattr(deal, 'Volume', 0)
                try:
                    volume_val = float(volume_src or 0)
                except Exception:
                    volume_val = 0.0
                lot_size = float(volume_val) / 10000.0 if volume_val > 0 else 0.0
                
                # Extract deal ticket and close time from MT5 deal object
                deal_ticket = str(getattr(deal, 'Deal', None))
                mt5_close_time_unix = getattr(deal, 'Time', None)
                
                # Convert Unix timestamp to timezone-aware datetime
                mt5_close_time = None
                if mt5_close_time_unix:
                    try:
                        mt5_close_time = timezone.make_aware(datetime.fromtimestamp(int(mt5_close_time_unix)))
                    except (ValueError, TypeError, OSError) as e:
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
                    'mt5_close_time': mt5_close_time,
                }
                
                try:
                    # process_commission_for_trade will handle whether commission should be created
                    # It will skip non-IB accounts gracefully if no parent_ib exists
                    result = process_commission_for_trade(trade_data)
                    
                    if result:
                        created_count += 1
                        logger.info(f"Created commission for trade {trade_id} on account {account.account_id}")
                        
                except IntegrityError:
                    # Duplicate detected (likely created by a concurrent run) - ignore
                    continue
                except Exception as e:
                    # Log other exceptions but continue with next trade
                    logger.error(f"Error processing trade {trade_id} for account {account.account_id}: {e}")
        
        # Log cycle summary
        total_time = (time.time() - start_time) * 1000
        logger.info(f"Sync complete: {created_count} commissions created | {checked_count} accounts checked | {skipped_count} skipped by cooldown | {total_time:.1f}ms")
        
        if created_count > 0:
            print(f"✅ Created {created_count} new commission transactions")
        else:
            print(f"ℹ️  No new trades found to process")