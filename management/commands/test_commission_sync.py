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
    help = 'Test commission sync with extended time window and debug logging.'

    def add_arguments(self, parser):
        parser.add_argument('--days', type=int, default=7, help='Number of days to look back for trades')
        parser.add_argument('--max-accounts', type=int, default=10, help='Maximum number of accounts to test')

    def handle(self, *args, **options):
        days_back = options['days']
        max_accounts = options['max_accounts']
        
        print(f"🔍 Testing commission sync with {days_back} days lookback, max {max_accounts} accounts")
        
        start_time = time.time()
        mt5 = MT5ManagerActions()
        
        # Get IB clients and their trading accounts for testing
        from adminPanel.models import CustomUser
        ib_clients = CustomUser.objects.filter(parent_ib__isnull=False)[:5]
        
        accounts_to_test = []
        for client in ib_clients:
            client_accounts = TradingAccount.objects.filter(user=client)[:2]  # Max 2 per client
            accounts_to_test.extend(client_accounts)
            if len(accounts_to_test) >= max_accounts:
                break
        
        print(f"📊 Testing {len(accounts_to_test)} accounts from {len(ib_clients)} IB clients")
        
        created_count = 0
        checked_count = 0
        
        for account in accounts_to_test:
            checked_count += 1
            
            print(f"\n🏦 Account {checked_count}/{len(accounts_to_test)}: {account.account_id}")
            print(f"   Client: {account.user.email}")
            print(f"   Parent IB: {account.user.parent_ib.email if account.user.parent_ib else 'None'}")
            
            # Check commission profile
            if account.user.parent_ib and hasattr(account.user.parent_ib, 'commissioning_profile'):
                profile = account.user.parent_ib.commissioning_profile
                print(f"   Commission Profile: {profile.name if profile else 'None'}")
            
            try:
                # Extended time window for testing
                from_date = timezone.now() - timedelta(days=days_back)
                closed_trades = mt5.get_closed_trades(account.account_id, from_date=from_date)
                
                print(f"   📈 Found {len(closed_trades) if closed_trades else 0} closed trades ({days_back} days)")
                
                if not closed_trades:
                    continue
                
                # Process first few trades for testing
                for i, deal in enumerate(closed_trades[:3]):  # Max 3 trades per account
                    # Use Deal as trade_id if available, fallback to Position
                    trade_id = str(getattr(deal, 'Deal', None))
                    if not trade_id or trade_id == 'None':
                        trade_id = str(getattr(deal, 'Position', None))
                    if not trade_id or trade_id == 'None':
                        continue
                    
                    # Check if already exists
                    if CommissionTransaction.objects.filter(position_id=trade_id, client_trading_account=account).exists():
                        print(f"   ⏭️  Trade {trade_id}: Commission already exists")
                        continue
                    
                    # Extract trade details
                    volume_src = getattr(deal, 'VolumeClosed', None) or getattr(deal, 'Volume', 0)
                    try:
                        volume_val = float(volume_src or 0)
                    except Exception:
                        volume_val = 0.0
                    lot_size = float(volume_val) / 10000.0 if volume_val > 0 else 0.0
                    
                    commission = float(getattr(deal, 'Commission', 0))
                    symbol = getattr(deal, 'Symbol', '')
                    
                    print(f"   💰 Trade {i+1}: {trade_id}")
                    print(f"      Symbol: {symbol}")
                    print(f"      Lots: {lot_size}")
                    print(f"      Commission: ${commission}")
                    
                    # Create trade data
                    trade_data = {
                        'client_email': account.user.email,
                        'trade_id': trade_id,
                        'trading_account_id': account.id,
                        'symbol': symbol,
                        'position_type': 'buy' if getattr(deal, 'Type', 0) == 0 else 'sell',
                        'position_direction': 'in',
                        'total_commission': commission,
                        'lot_size': lot_size,
                        'profit': float(getattr(deal, 'Profit', 0) or 0),
                    }
                    
                    try:
                        result = process_commission_for_trade(trade_data)
                        if result:
                            created_count += 1
                            print(f"      ✅ Commission created successfully!")
                        else:
                            print(f"      ❌ Commission creation failed")
                    except Exception as e:
                        print(f"      💥 Error: {e}")
                        
            except Exception as e:
                print(f"   💥 Error getting trades: {e}")
        
        # Summary
        total_time = (time.time() - start_time) * 1000
        print(f"\n📊 Summary:")
        print(f"   Accounts checked: {checked_count}")
        print(f"   Commissions created: {created_count}")
        print(f"   Total time: {total_time:.1f}ms")
        
        if created_count > 0:
            print(f"\n🎉 Commission system is working! {created_count} new commissions created.")
        else:
            print(f"\n🤔 No new commissions created. This could mean:")
            print(f"   - No recent trading activity")
            print(f"   - All trades already have commissions") 
            print(f"   - Commission configuration issues")